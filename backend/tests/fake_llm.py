"""Deterministic stand-in for an LLM provider, used to test the pipeline without network access."""
import re

from app.ai.providers import LLMProvider, Usage


def _field(prompt: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}: (.*)$", prompt, re.M)
    return m.group(1).strip() if m else ""


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, scripted: dict | None = None, review_fail_urls: set | None = None, insufficient_urls: set | None = None):
        super().__init__(model="fake-model", api_key="x")
        self.calls: list[dict] = []
        self.scripted = scripted or {}  # url-substring -> list of (title, description) per attempt
        self.review_fail_urls = review_fail_urls or set()
        self.insufficient_urls = insufficient_urls or set()
        self._attempts: dict[str, int] = {}

    def complete_json(self, stage, system, user, schema, schema_name):
        self.calls.append({"stage": stage, "system": system, "user": user})
        if self.on_usage:
            self.on_usage(stage, Usage("fake", self.model, 100, 50), True, None)
        url = _field(user, "URL")
        h1 = re.search(r"H1: (.*)", user)
        h1 = h1.group(1).strip() if h1 else "Page"
        if schema_name == "page_understanding":
            insufficient = any(u in url for u in self.insufficient_urls)
            return {
                "page_type": "Product" if "/products/" in url else "Homepage" if url.endswith("/") and url.count("/") == 3 else "Other",
                "primary_topic": h1, "search_intent": "commercial", "target_audience": "trail runners",
                "primary_keyword": h1.lower(), "secondary_keywords": ["trail shoes"], "entities": [h1],
                "usps": [{"usp": "Grippy outsole", "evidence_quote": "Vibram Megagrip outsole"},
                         {"usp": "Invented claim", "evidence_quote": "Lifetime warranty on all shoes"}],
                "key_message": h1, "positioning": "performance", "content_relevance": "focused",
                "content_sufficient": not insufficient, "insufficiency_reason": "Placeholder page" if insufficient else "",
            }
        if schema_name == "metadata_evaluation":
            return {"scores": {k: 5 for k in ("title_relevance", "title_intent_alignment", "title_ctr_appeal", "description_relevance",
                                              "description_intent_alignment", "description_value_clarity", "description_ctr_appeal",
                                              "naturalness", "brand_voice_fit")},
                    "issues": [{"field": "title", "name": "Weak value proposition", "severity": "Medium",
                                "explanation": "Title does not say what is unique.", "recommendation": "Mention the key feature."}],
                    "unsupported_claims": [], "summary": "Existing metadata is generic."}
        if schema_name == "metadata_generation":
            n = self._attempts.get(url, 0)
            self._attempts[url] = n + 1
            for key, outputs in self.scripted.items():
                if key in url:
                    t, d = outputs[min(n, len(outputs) - 1)]
                    return {"title": t, "description": d, "primary_keyword_used": h1.lower(), "claims_used": [], "rationale": "scripted"}
            title = f"{h1} | Acme Outdoor"
            desc = (f"{h1}: see what this page covers, from key features to fit and terrain, and decide whether it is right "
                    f"for your next run.")
            return {"title": title, "description": desc, "primary_keyword_used": h1.lower(), "claims_used": [], "rationale": "default"}
        if schema_name == "metadata_validation":
            fail = any(u in url for u in self.review_fail_urls)
            return {
                "accurate_representation": not fail, "follows_brand_guidelines": True, "follows_custom_instructions": True,
                "follows_page_type_rules": True, "keyword_usage_appropriate": True, "natural_language": True,
                "unsupported_claims": [], "issues": ([{"field": "description", "name": "Misrepresents page", "severity": "High",
                                                       "explanation": "Describes a different product.", "recommendation": "Rewrite."}] if fail else []),
                "scores": {k: 8 for k in ("title_relevance", "title_intent_alignment", "title_ctr_appeal", "description_relevance",
                                          "description_intent_alignment", "description_value_clarity", "description_ctr_appeal",
                                          "naturalness", "brand_voice_fit")},
                "verdict": "fail" if fail else "pass", "summary": "Reviewed.",
            }
        raise AssertionError(f"unexpected schema {schema_name}")
