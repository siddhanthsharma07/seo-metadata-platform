"""URL normalisation, scoping and SSRF protection."""
from __future__ import annotations

import ipaddress
import posixpath
import re
import socket
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "gclid", "gclsrc", "dclid", "fbclid", "msclkid", "yclid", "twclid", "ttclid", "li_fat_id",
    "mc_cid", "mc_eid", "_ga", "_gl", "_hsenc", "_hsmi", "hsctatracking", "igshid", "si",
    "ref_src", "spm", "srsltid", "wbraid", "gbraid", "oly_anon_id", "oly_enc_id", "vero_id",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "matomo_", "hsa_")
SESSION_PARAMS = {"sid", "sessionid", "session_id", "phpsessid", "jsessionid", "cfid", "cftoken"}

NON_HTML_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tif", ".tiff", ".avif",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt", ".rtf",
    ".zip", ".gz", ".rar", ".7z", ".tar", ".dmg", ".exe", ".msi", ".apk",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".webm", ".ogg", ".wav", ".flac",
    ".css", ".js", ".json", ".xml", ".rss", ".atom", ".woff", ".woff2", ".ttf", ".eot", ".map",
}

PAGINATION_PARAMS = {"page", "p", "pg", "paged", "pagenum", "page_no", "start", "offset"}


class UnsafeURLError(ValueError):
    """Raised when a URL targets a disallowed network location (SSRF protection)."""


def ensure_scheme(url: str) -> str:
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def normalize_url(url: str, base: str | None = None, strip_query_params: set[str] | None = None) -> str | None:
    """Return a canonical form of ``url`` or None when it is not a crawlable http(s) URL."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("mailto:", "tel:", "javascript:", "data:", "#", "sms:", "whatsapp:")):
        return None
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    trailing = path.endswith("/")
    path = posixpath.normpath(path)
    if path == ".":
        path = "/"
    if trailing and not path.endswith("/"):
        path += "/"
    if not path.startswith("/"):
        path = "/" + path
    path = quote(unquote(path), safe="/:@!$&'()*+,;=-._~%")
    # strip session ids embedded in path (e.g. ;jsessionid=...)
    path = re.sub(r";jsessionid=[^/?#]*", "", path, flags=re.I)

    extra = {p.lower() for p in (strip_query_params or set())}
    query_items = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACKING_PARAMS or kl in SESSION_PARAMS or kl in extra or kl.startswith(TRACKING_PREFIXES):
            continue
        query_items.append((k, v))
    query_items.sort()
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def variation_key(url: str) -> str:
    """Key used to detect URL variations (http/https, www, trailing slash, case of path)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    for suffix in ("/index.html", "/index.htm", "/index.php", "/default.aspx"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)] or "/"
    return f"{host}{path.lower()}?{parts.query}" if parts.query else f"{host}{path.lower()}"


def registrable_host(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def in_scope(url: str, root_host: str, include_subdomains: bool = False, allowed_hosts: list[str] | None = None) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    root = registrable_host(root_host)
    if registrable_host(host) == root:
        return True
    if include_subdomains and host.endswith("." + root):
        return True
    if allowed_hosts and registrable_host(host) in {registrable_host(h) for h in allowed_hosts}:
        return True
    return False


def has_non_html_extension(url: str) -> bool:
    path = urlsplit(url).path.lower()
    ext = posixpath.splitext(path)[1]
    return ext in NON_HTML_EXTENSIONS


def is_pagination_url(url: str) -> bool:
    parts = urlsplit(url)
    if re.search(r"/page/\d+/?$", parts.path, re.I):
        return True
    return any(k.lower() in PAGINATION_PARAMS for k, _ in parse_qsl(parts.query))


def matches_any(url: str, patterns: list[str] | None) -> bool:
    for pat in patterns or []:
        pat = pat.strip()
        if not pat:
            continue
        try:
            if re.search(pat, url):
                return True
        except re.error:
            if pat in url:
                return True
    return False


# ---------------------------------------------------------------- SSRF protection

_BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal", "metadata", "instance-data", "metadata.azure.com",
}


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
        or (isinstance(ip, ipaddress.IPv6Address) and ip in ipaddress.ip_network("fd00::/8"))
    )


def assert_public_url(url: str, allow_private: bool = False) -> None:
    """Raise UnsafeURLError when the URL resolves to loopback/private/metadata addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http and https URLs can be crawled.")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs containing credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURLError("URL has no host.")
    if allow_private:
        return
    if host in _BLOCKED_HOSTNAMES or host.endswith((".localhost", ".internal", ".local")):
        raise UnsafeURLError(f"Host '{host}' is not allowed.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise UnsafeURLError(f"IP address {host} is in a private or reserved range.")
        return
    # Reject decimal/hex/octal integer hosts ("2130706433", "0x7f000001").
    if re.fullmatch(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){0,3}", host):
        raise UnsafeURLError(f"Numeric host '{host}' is not allowed.")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"Host '{host}' resolves to a private or reserved address ({ip}).")


def is_safe_url(url: str, allow_private: bool = False) -> bool:
    try:
        assert_public_url(url, allow_private)
        return True
    except UnsafeURLError:
        return False
