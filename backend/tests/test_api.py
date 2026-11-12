import io
import time

from openpyxl import load_workbook

from app.ai.pipeline import run_ai_job
from app.config import get_settings
from app.models import AIJob
from tests.conftest import register
from tests.fake_llm import FakeProvider


def create_project(client, h, site, **kw):
    body = {"name": "Acme Outdoor", "base_url": site.base + "/", "language": "en-GB", "target_country": "UK",
            "crawl_settings": {"delay_ms": 0, "render_js": "never", "max_urls": 100}, **kw}
    r = client.post("/api/projects", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def crawl(client, h, pid):
    r = client.post(f"/api/projects/{pid}/crawls", json={}, headers=h)
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    for _ in range(200):
        j = client.get(f"/api/projects/{pid}/crawls/{job_id}", headers=h).json()
        if j["status"] in ("completed", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError("crawl did not finish")


def test_auth_required_and_login(client):
    assert client.get("/api/projects").status_code == 401
    register(client)
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "OWNER@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.post("/api/auth/register", json={"email": "owner@example.com", "password": "another-password"}).status_code == 409


def test_ssrf_rejected_on_project_creation(client, monkeypatch):
    h = register(client)
    monkeypatch.setattr(get_settings(), "allow_private_networks", False)
    for url in ("http://localhost:8000", "http://169.254.169.254/", "http://10.1.2.3", "file:///etc/passwd"):
        r = client.post("/api/projects", json={"name": "x", "base_url": url}, headers=h)
        assert r.status_code == 422, (url, r.text)


def test_projects_are_isolated_between_users(client, site):
    h1 = register(client, "a@example.com")
    h2 = register(client, "b@example.com")
    p = create_project(client, h1, site)
    assert client.get(f"/api/projects/{p['id']}", headers=h2).status_code == 404
    assert client.get(f"/api/projects/{p['id']}/pages", headers=h2).status_code == 404
    assert client.post(f"/api/projects/{p['id']}/crawls", json={}, headers=h2).status_code == 404
    assert client.get("/api/projects", headers=h2).json() == []


def test_guidelines_versioning(client, site):
    h = register(client)
    p = create_project(client, h, site)
    g1 = client.get(f"/api/projects/{p['id']}/guidelines", headers=h).json()
    assert g1["version"] == 1 and g1["brand_context"]["brand_name"] == "Acme Outdoor"
    body = {"brand_context": {"brand_name": "Acme Outdoor", "tone_of_voice": "premium"},
            "seo_guidelines": {"title_min": 40, "title_max": 65}, "guardrails": {"never_use_words": ["affordable"]},
            "keywords": [{"keyword": "trail running shoes", "priority": "high"}], "custom_instructions": "Do not use em dashes."}
    r = client.post(f"/api/projects/{p['id']}/guidelines", json=body, headers=h)
    assert r.status_code == 201 and r.json()["version"] == 2
    bad = client.post(f"/api/projects/{p['id']}/guidelines", json={**body, "seo_guidelines": {"title_min": 80, "title_max": 60}}, headers=h)
    assert bad.status_code == 422
    versions = client.get(f"/api/projects/{p['id']}/guidelines/versions", headers=h).json()
    assert [v["version"] for v in versions] == [2, 1] and sum(v["is_active"] for v in versions) == 1
    r = client.post(f"/api/projects/{p['id']}/guidelines/1/restore", headers=h)
    assert r.json()["version"] == 3 and r.json()["guardrails"]["never_use_words"] == []


def test_end_to_end_review_and_export(client, site, db):
    h = register(client)
    p = create_project(client, h, site)
    pid = p["id"]
    client.post(f"/api/projects/{pid}/guidelines", headers=h, json={
        "brand_context": {"brand_name": "Acme Outdoor"},
        "seo_guidelines": {"title_min": 15, "title_max": 70, "description_min": 80, "description_max": 175},
        "guardrails": {"never_use_words": ["cheap"]}})
    r = client.post(f"/api/projects/{pid}/crawls/urls", headers=h, json={"urls": ["/about-us", "https://other-domain.example/x", "/x.pdf"]})
    assert r.json()["rejected_count"] == 2
    job = crawl(client, h, pid)
    assert job["status"] == "completed"

    dash = client.get(f"/api/projects/{pid}/dashboard", headers=h).json()
    assert dash["crawled"] >= 8 and dash["missing_titles"] >= 1 and dash["missing_descriptions"] >= 1
    assert dash["duplicate_titles"] >= 2 and dash["avg_existing_score"] is not None

    # AI provider is not configured in tests -> clear error, nothing pretends to work
    r = client.post(f"/api/projects/{pid}/ai/jobs", headers=h, json={"kind": "generate"})
    assert r.status_code == 412 and "API key" in r.json()["detail"]

    ai = AIJob(project_id=pid, kind="generate", status="pending", params={})
    db.add(ai)
    db.commit()
    run_ai_job(ai.id, provider_override=FakeProvider())

    rows = client.get(f"/api/projects/{pid}/pages", headers=h, params={"limit": 100}).json()
    assert rows["total"] >= 8
    item = next(i for i in rows["items"] if i["url"].endswith("/products/ridge-runner-2"))
    assert item["proposed_title"] and item["validation_status"] == "passed" and item["approval_status"] == "pending"
    assert client.get(f"/api/projects/{pid}/pages", headers=h, params={"missing": "description"}).json()["total"] >= 1
    assert client.get(f"/api/projects/{pid}/pages", headers=h, params={"duplicate": "title"}).json()["total"] >= 2
    assert client.get(f"/api/projects/{pid}/pages", headers=h, params={"critical": True}).json()["total"] >= 1
    srt = client.get(f"/api/projects/{pid}/pages", headers=h, params={"sort": "existing_score", "order": "desc"}).json()["items"]
    scores = [i["existing_score"] for i in srt if i["existing_score"] is not None]
    assert scores == sorted(scores, reverse=True)

    page_id = item["id"]
    # Manual edit that breaks a guardrail is saved as failed and cannot be approved
    r = client.post(f"/api/projects/{pid}/pages/{page_id}/actions", headers=h,
                    json={"action": "edit", "title": "Cheap Ridge Runner 2 Shoes | Acme Outdoor"})
    assert r.status_code == 200
    r = client.post(f"/api/projects/{pid}/pages/{page_id}/actions", headers=h, json={"action": "approve_title"})
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["code"] == "guardrail_prohibited_word"
    # Approve description only (it is still valid), then fix the title and approve it
    assert client.post(f"/api/projects/{pid}/pages/{page_id}/actions", headers=h, json={"action": "approve_description"}).status_code == 200
    client.post(f"/api/projects/{pid}/pages/{page_id}/actions", headers=h,
                json={"action": "edit", "title": "Ridge Runner 2 Trail Running Shoe | Acme Outdoor"})
    assert client.post(f"/api/projects/{pid}/pages/{page_id}/actions", headers=h, json={"action": "approve_title"}).status_code == 200

    detail = client.get(f"/api/projects/{pid}/pages/{page_id}", headers=h).json()
    assert detail["page"]["title_status"] == "approved" and detail["page"]["description_status"] == "approved"
    assert [v["source"] for v in detail["versions"]][:3] == ["manual_edit", "manual_edit", "ai_generated"]
    assert {e["action"] for e in detail["events"]} >= {"edit", "approve"}
    assert detail["analysis"]["primary_keyword"] and detail["existing_audit"]["issues"]

    # Bulk approve skips pages without proposals or failing guardrails, reporting why
    ids = [i["id"] for i in rows["items"]]
    r = client.post(f"/api/projects/{pid}/pages/bulk", headers=h, json={"page_ids": ids, "action": "approve_both"})
    assert r.status_code == 200 and r.json()["done"] >= 1

    # Exports
    r = client.get(f"/api/projects/{pid}/exports/approved", headers=h, params={"format": "xlsx"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Approved Metadata"]
    assert ws.freeze_panes == "B2" and ws.auto_filter.ref
    titles = [c.value for c in ws["E"][1:]]
    assert "Ridge Runner 2 Trail Running Shoe | Acme Outdoor" in titles
    r = client.get(f"/api/projects/{pid}/exports/complete_audit", headers=h, params={"format": "csv"})
    text = r.content.decode("utf-8-sig")
    assert text.startswith("S. No.,Page URL") and site.base in text
    for t in ("needs_improvement", "missing", "duplicates", "crawl_errors"):
        r = client.get(f"/api/projects/{pid}/exports/{t}", headers=h)
        assert r.status_code == 200, (t, r.text)
    errs = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/exports/crawl_errors", headers=h).content))["Crawl Errors"]
    assert any("missing-page" in str(c.value) for c in errs["A"])
    assert len(client.get(f"/api/projects/{pid}/exports/history", headers=h).json()) == 7
