"""HTTP fetching with SSRF-safe redirect handling, retries and optional JS rendering."""
from __future__ import annotations

import asyncio
import gzip
import logging
import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx

from app.crawler.url_utils import UnsafeURLError, assert_public_url

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    text: str = ""
    redirect_chain: list[dict] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0
    attempts: int = 0
    rendered_with_js: bool = False
    blocked_reason: str | None = None
    raw: bytes = b""

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return "html" in ct or (not ct and self.text.lstrip()[:200].lower().startswith(("<!doctype html", "<html")))


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 20.0,
        max_bytes: int = 5_000_000,
        max_redirects: int = 10,
        max_retries: int = 3,
        allow_private: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.max_retries = max_retries
        self.allow_private = allow_private
        self.client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "*",
            },
            transport=transport,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _single(self, url: str) -> FetchResult:
        result = FetchResult(url=url, final_url=url)
        current = url
        start = time.monotonic()
        for _hop in range(self.max_redirects + 1):
            try:
                await asyncio.to_thread(assert_public_url, current, self.allow_private)
            except UnsafeURLError as exc:
                result.error = f"Blocked for security reasons: {exc}"
                result.blocked_reason = str(exc)
                result.final_url = current
                return result
            async with self.client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    nxt = urljoin(current, resp.headers["location"])
                    result.redirect_chain.append({"url": current, "status": resp.status_code, "location": nxt})
                    current = nxt
                    continue
                chunks: list[bytes] = []
                size = 0
                ct = resp.headers.get("content-type", "")
                # Only download bodies for HTML / XML / text.
                wants_body = (not ct) or any(t in ct.lower() for t in ("html", "xml", "text", "gzip", "octet-stream"))
                if wants_body:
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            result.error = f"Response exceeded {self.max_bytes} bytes and was truncated"
                            break
                        chunks.append(chunk)
                body = b"".join(chunks)
                result.raw = body
                result.status = resp.status_code
                result.headers = {k.lower(): v for k, v in resp.headers.items()}
                result.content_type = ct
                result.final_url = str(resp.url)
                encoding = resp.charset_encoding or _sniff_encoding(body) or "utf-8"
                try:
                    result.text = body.decode(encoding, errors="replace")
                except LookupError:
                    result.text = body.decode("utf-8", errors="replace")
                result.elapsed_ms = int((time.monotonic() - start) * 1000)
                if result.error and "truncated" in result.error:
                    result.error = None  # keep partial page, it is still useful
                return result
        result.error = f"Too many redirects (> {self.max_redirects})"
        result.final_url = current
        return result

    async def fetch(self, url: str) -> FetchResult:
        """Fetch with retries (exponential backoff + jitter, honours Retry-After)."""
        last: FetchResult | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                res = await self._single(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                res = FetchResult(url=url, final_url=url, error=f"{type(exc).__name__}: {exc}" or type(exc).__name__)
            res.attempts = attempt
            last = res
            if res.blocked_reason:
                return res
            retryable = (res.error is not None and res.status is None) or (res.status in RETRYABLE_STATUS)
            if not retryable or attempt > self.max_retries:
                return res
            delay = min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 0.5))
            ra = res.headers.get("retry-after") if res.headers else None
            if ra:
                delay = min(60.0, _parse_retry_after(ra) or delay)
            await asyncio.sleep(delay)
        assert last is not None
        return last

    async def fetch_text(self, url: str) -> FetchResult:
        res = await self.fetch(url)
        if res.ok and res.raw[:2] == b"\x1f\x8b":
            try:
                res.text = gzip.decompress(res.raw).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                res.error = "Could not decompress gzip sitemap"
        res.raw = b""
        return res


def _sniff_encoding(body: bytes) -> str | None:
    head = body[:2048].decode("ascii", errors="ignore").lower()
    import re

    m = re.search(r'charset=["\']?([a-z0-9_\-]+)', head)
    return m.group(1) if m else None


def _parse_retry_after(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            return max(0.0, dt.timestamp() - time.time())
        except Exception:  # noqa: BLE001
            return None


class JSRenderer:
    """Renders JavaScript-heavy pages with Playwright (Chromium). Created lazily."""

    def __init__(self, user_agent: str, allow_private: bool = False, executable_path: str | None = None, timeout_ms: int = 30000):
        self.user_agent = user_agent
        self.allow_private = allow_private
        self.executable_path = executable_path
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None

    async def _ensure(self):
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            kwargs = {"headless": True, "args": ["--no-sandbox"]}
            if self.executable_path:
                kwargs["executable_path"] = self.executable_path
            self._browser = await self._pw.chromium.launch(**kwargs)
        return self._browser

    async def render(self, url: str) -> FetchResult:
        result = FetchResult(url=url, final_url=url, rendered_with_js=True)
        start = time.monotonic()
        try:
            browser = await self._ensure()
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()

            async def guard(route):
                req_url = route.request.url
                if req_url.startswith(("data:", "blob:")):
                    return await route.continue_()
                rtype = route.request.resource_type
                if rtype in ("image", "media", "font"):
                    return await route.abort()
                try:
                    await asyncio.to_thread(assert_public_url, req_url, self.allow_private)
                except UnsafeURLError:
                    return await route.abort()
                return await route.continue_()

            await page.route("**/*", guard)
            resp = await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            result.text = await page.content()
            result.final_url = page.url
            if resp is not None:
                result.status = resp.status
                result.headers = {k.lower(): v for k, v in (await resp.all_headers()).items()}
                result.content_type = result.headers.get("content-type", "text/html")
            await context.close()
        except Exception as exc:  # noqa: BLE001
            result.error = f"JS rendering failed: {exc}"
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result

    async def close(self):
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = None
        self._pw = None
