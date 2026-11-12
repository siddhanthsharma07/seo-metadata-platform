from app.seo.audit import score
from app.seo.guidelines import DEFAULT_GUARDRAILS, DEFAULT_SEO_GUIDELINES, ProjectContext, merge_defaults
from app.seo.rules import PageFacts, SiteIndex, check_pair


def ctx(**guard):
    g = merge_defaults(DEFAULT_GUARDRAILS, guard)
    return ProjectContext(
        project_id=1, project_name="Acme Outdoor", domain="acme.test", language="en-GB", target_country="UK",
        primary_market="UK", target_audience="trail runners", business_category="Outdoor", guideline_version_id=1,
        guideline_version=1, brand={"brand_name": "Acme Outdoor"}, seo=dict(DEFAULT_SEO_GUIDELINES), guardrails=g,
    )


FACTS = PageFacts(page_id=1, url="https://acme.test/p", page_type="Product", primary_keyword="trail running shoes",
                  secondary_keywords=["waterproof trail shoes"], content="Our trail running shoes have Vibram soles.")


def codes(issues):
    return {i["code"] for i in issues}


def test_good_metadata_has_no_blocking_issues():
    title = "Trail Running Shoes with Vibram Grip | Acme Outdoor"  # 51 chars
    desc = ("Explore trail running shoes with Vibram soles for muddy and rocky routes. Compare fits, drops and "
            "grip to find the right pair for your next run.")
    issues = check_pair(title, desc, ctx(), FACTS, SiteIndex(), "validate")
    assert not [i for i in issues if i["blocking"]], issues


def test_guardrails_are_enforced_deterministically():
    c = ctx(never_use_words=["affordable"], prohibited_phrases=["best in class"], competitor_brands=["Salomon"],
            formatting={"no_em_dash": True}, must_use_words=["Acme Outdoor"])
    title = "Affordable Trail Running Shoes — Better than Salomon"
    desc = "Best in class trail running shoes for every runner."
    issues = check_pair(title, desc, c, FACTS, SiteIndex(), "validate")
    cs = codes(issues)
    assert {"guardrail_prohibited_word", "guardrail_prohibited_phrase", "guardrail_competitor", "format_em_dash",
            "guardrail_must_use_missing", "title_brand_missing", "description_too_short"} <= cs
    assert all(i["blocking"] for i in issues if i["code"].startswith("guardrail_"))


def test_duplicates_and_missing():
    site = SiteIndex()
    site.add(2, "Trail Running Shoes | Acme Outdoor", "Shop our trail running shoes range today with free advice.")
    issues = check_pair("Trail Running Shoes | Acme Outdoor", None, ctx(), FACTS, site, "audit")
    cs = codes(issues)
    assert "title_duplicate" in cs and "description_missing" in cs
    assert check_pair(None, None, ctx(), FACTS, site, "audit")[0]["code"] == "title_missing"


def test_keyword_stuffing_and_brand_repetition():
    issues = check_pair("Shoes Shoes Shoes Trail Running | Acme Outdoor | Acme Outdoor", "x" * 150, ctx(), FACTS, SiteIndex(), "validate")
    cs = codes(issues)
    assert "title_keyword_stuffing" in cs and "title_brand_repeated" in cs


def test_score_is_transparent_and_bounded():
    c = ctx()
    t = "Trail Running Shoes with Vibram Grip | Acme Outdoor"
    d = ("Explore trail running shoes with Vibram soles for muddy and rocky routes. Compare fits, drops and "
         "grip to find the right pair for your next run.")
    good = score(t, d, check_pair(t, d, c, FACTS, SiteIndex(), "audit"), c, FACTS)
    bad = score("Home", None, check_pair("Home", None, c, FACTS, SiteIndex(), "audit"), c, FACTS)
    assert 0 <= bad[2] < good[2] <= 100
    assert good[3]["title"]["length"] == 20 and "relevance" in good[3]["description"]
    assert bad[1] == 0 and bad[3]["description"] == {"missing": True}
