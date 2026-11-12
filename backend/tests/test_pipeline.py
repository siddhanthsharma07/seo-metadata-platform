import re

from sqlalchemy import select

from app.ai.pipeline import run_ai_job
from app.models import AIJob, AIUsageLog, AuditResult, GuidelineVersion, MetadataVersion, Page, PageAnalysis, ValidationResult
from app.seo.guidelines import DEFAULT_GUARDRAILS, DEFAULT_SEO_GUIDELINES, merge_defaults
from tests.fake_llm import FakeProvider
from tests.test_crawler import make_project, start


def setup_project(db, site, guard=None, seo=None, custom=""):
    p = make_project(db, site)
    db.add(GuidelineVersion(project_id=p.id, version=1, is_active=True, brand_context={"brand_name": "Acme Outdoor"},
                            seo_guidelines=merge_defaults(DEFAULT_SEO_GUIDELINES, {"title_min": 15, "title_max": 70,
                                                                                   "description_min": 80, "description_max": 175, **(seo or {})}),
                            guardrails=merge_defaults(DEFAULT_GUARDRAILS, guard or {}), keywords=[], custom_instructions=custom))
    db.commit()
    start(db, p)
    return p


def run_job(db, p, kind="generate", provider=None, **params):
    job = AIJob(project_id=p.id, kind=kind, status="pending", params=params)
    db.add(job)
    db.commit()
    provider = provider or FakeProvider()
    run_ai_job(job.id, provider_override=provider)
    db.expire_all()
    return db.get(AIJob, job.id), provider


def page_for(db, p, suffix):
    return db.execute(select(Page).where(Page.project_id == p.id, Page.url.like(f"%{suffix}"))).scalar_one()


def current(db, page):
    return db.execute(select(MetadataVersion).where(MetadataVersion.page_id == page.id, MetadataVersion.is_current.is_(True))).scalar_one()


def test_generation_with_independent_validation(db, site):
    p = setup_project(db, site)
    job, prov = run_job(db, p)
    assert job.status == "completed", (job.error, job.log)
    stages = {c["stage"] for c in prov.calls}
    assert {"understanding", "evaluation", "generation", "validation"} <= stages
    rr = page_for(db, p, "/products/ridge-runner-2")
    mv = current(db, rr)
    assert mv.validation_status == "passed" and mv.title.startswith("Ridge Runner 2")
    an = db.execute(select(PageAnalysis).where(PageAnalysis.page_id == rr.id)).scalar_one()
    assert an.usps == ["Grippy outsole"]  # USP without evidence on the page is dropped
    proposed = db.execute(select(AuditResult).where(AuditResult.page_id == rr.id, AuditResult.target == "proposed")).scalar_one()
    existing = db.execute(select(AuditResult).where(AuditResult.page_id == rr.id, AuditResult.target == "existing",
                                                    AuditResult.is_current.is_(True))).scalar_one()
    assert existing.ai_evaluated and proposed.overall_score > existing.overall_score
    assert db.execute(select(AIUsageLog)).scalars().first() is not None
    # noindex page is not processed by default
    assert db.execute(select(MetadataVersion).where(MetadataVersion.page_id == page_for(db, p, "/noindex-page").id)).first() is None

    # Unchanged content + instructions => no duplicate AI processing on a second run
    n_before = len(prov.calls)
    job2, prov2 = run_job(db, p)
    assert not [c for c in prov2.calls if c["stage"] in ("understanding", "generation")]


def test_regeneration_loop_fixes_guardrail_violation(db, site):
    p = setup_project(db, site, guard={"never_use_words": ["cheap"]})
    prov = FakeProvider(scripted={"/products/ridge-runner-2": [
        ("Cheap Ridge Runner 2 Trail Running Shoe | Acme Outdoor", "Cheap trail running shoe with a Vibram Megagrip outsole for muddy fell routes and rocky paths."),
        ("Ridge Runner 2 Trail Running Shoe | Acme Outdoor", "Ridge Runner 2 trail running shoe with a Vibram Megagrip outsole and rock plate for muddy fell routes."),
    ]})
    job, prov = run_job(db, p, provider=prov, page_ids=[page_for(db, p, "/products/ridge-runner-2").id])
    rr = page_for(db, p, "/products/ridge-runner-2")
    mv = current(db, rr)
    assert mv.validation_status == "passed" and "Cheap" not in mv.title and mv.attempts == 2
    vals = db.execute(select(ValidationResult).where(ValidationResult.page_id == rr.id).order_by(ValidationResult.attempt)).scalars().all()
    assert vals[0].passed is False and any(i["code"] == "guardrail_prohibited_word" for i in vals[0].deterministic_issues)
    regen_prompt = [c for c in prov.calls if c["stage"] == "regeneration"][0]["user"]
    assert "FAILED validation" in regen_prompt and "prohibited" in regen_prompt.lower()


def test_flags_manual_review_after_max_attempts(db, site):
    p = setup_project(db, site)
    prov = FakeProvider(review_fail_urls={"/products/summit-gtx"})
    run_job(db, p, provider=prov, page_ids=[page_for(db, p, "/products/summit-gtx").id])
    mv = current(db, page_for(db, p, "/products/summit-gtx"))
    assert mv.validation_status == "failed" and mv.attempts == 3
    assert "manual review" in mv.validation_summary


def test_insufficient_content_is_flagged_not_guessed(db, site):
    p = setup_project(db, site)
    prov = FakeProvider(insufficient_urls={"/contact"})
    run_job(db, p, provider=prov)
    thin = current(db, page_for(db, p, "/thin-page"))
    assert thin.validation_status == "needs_review" and "Insufficient" in thin.validation_summary
    contact = current(db, page_for(db, p, "/contact"))
    assert contact.validation_status == "needs_review"
    assert not any(c["stage"] == "generation" and re.search(r"^URL: \S*/contact$", c["user"], re.M) for c in prov.calls)


def test_guidelines_are_isolated_per_project(db, site):
    from app.models import Project

    p1 = setup_project(db, site, guard={"never_use_words": ["affordable"]}, custom="ALPHA-ONLY-INSTRUCTION")
    p2 = Project(owner_id=p1.owner_id, name="Beta Brand", domain="127.0.0.1", base_url=site.base + "/",
                 crawl_settings=p1.crawl_settings, ai_settings={})
    db.add(p2)
    db.commit()
    db.add(GuidelineVersion(project_id=p2.id, version=1, is_active=True, brand_context={"brand_name": "Beta Brand"},
                            seo_guidelines=DEFAULT_SEO_GUIDELINES, guardrails=merge_defaults(DEFAULT_GUARDRAILS, {"never_use_words": ["luxurious"]}),
                            keywords=[], custom_instructions="BETA-ONLY-INSTRUCTION"))
    db.commit()
    start(db, p2)
    _, prov2 = run_job(db, p2, kind="analyze")
    systems = " ".join(c["system"] for c in prov2.calls)
    assert "BETA-ONLY-INSTRUCTION" in systems and "luxurious" in systems
    assert "ALPHA-ONLY-INSTRUCTION" not in systems and "affordable" not in systems and "Acme Outdoor" not in systems
