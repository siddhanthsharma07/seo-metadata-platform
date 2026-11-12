import pytest

from app.crawler.extractor import extract, indexability
from app.crawler.url_utils import (
    UnsafeURLError,
    assert_public_url,
    in_scope,
    is_pagination_url,
    normalize_url,
    variation_key,
)
from tests.fixture_site import ROUTES


def test_normalize_strips_tracking_and_sorts_query():
    assert normalize_url("HTTPS://Example.COM:443/a//b/../c?utm_source=x&b=2&a=1&gclid=z#frag") == "https://example.com/a/c?a=1&b=2"
    assert normalize_url("/x?fbclid=1", base="https://example.com/y/") == "https://example.com/x"
    assert normalize_url("mailto:a@b.com") is None
    assert normalize_url("javascript:void(0)") is None
    assert normalize_url("ftp://example.com/file") is None


def test_variation_key_groups_url_variants():
    assert variation_key("https://www.example.com/Shoes/") == variation_key("http://example.com/shoes")
    assert variation_key("https://example.com/index.html") == variation_key("https://example.com/")


def test_scope_and_pagination():
    assert in_scope("https://www.example.com/a", "example.com")
    assert not in_scope("https://shop.example.com/a", "example.com")
    assert in_scope("https://shop.example.com/a", "example.com", include_subdomains=True)
    assert not in_scope("https://example.org/", "example.com")
    assert is_pagination_url("https://example.com/c/?page=2")
    assert is_pagination_url("https://example.com/blog/page/3/")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:8000/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/",
    "http://192.168.1.1/", "http://[::1]/", "http://2130706433/", "http://0x7f000001/", "http://metadata.google.internal/",
    "http://user:pass@example.com/", "file:///etc/passwd", "http://172.16.0.1/", "http://100.64.0.1/",
])
def test_ssrf_protection_blocks_private_targets(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url, allow_private=False)


def test_extracts_metadata_and_excludes_boilerplate():
    html = ROUTES["/products/ridge-runner-2"][2]
    ex = extract(html, "https://shop.example.com/products/ridge-runner-2", ["Acme Outdoor"])
    assert ex.title == "Ridge Runner 2 | Acme Outdoor"
    assert ex.meta_description is None
    assert ex.h1 == ["Ridge Runner 2 Trail Running Shoe"]
    assert "Features" in ex.h2
    assert ex.lang == "en-GB"
    assert "Vibram Megagrip" in ex.main_content
    assert "cookies" not in ex.main_content.lower()
    assert "Copyright" not in ex.main_content
    assert "Acme Outdoor header" not in ex.main_content
    assert ex.heuristic_page_type == "Product"
    assert "Ridge Runner 2" in ex.entities["products"]
    assert any(link.endswith("/category/trail-shoes/") for link in ex.links)
    assert ex.word_count > 40


def test_indexability_rules():
    assert indexability(200, "noindex,follow", None, None, "https://a.com/x", True) == (False, "noindex directive")
    assert indexability(200, None, "noindex", None, "https://a.com/x", True)[0] is False
    assert indexability(200, None, None, "https://a.com/y", "https://a.com/x", True)[0] is False
    assert indexability(404, None, None, None, "https://a.com/x", True)[0] is False
    assert indexability(200, None, None, None, "https://a.com/x", False) == (False, "Blocked by robots.txt")
    assert indexability(200, "index,follow", None, "https://a.com/x", "https://a.com/x", True) == (True, "Indexable")
