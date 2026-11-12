"""A small local website used by the crawler/pipeline tests."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAV = """<nav class="main-nav"><a href="/">Home</a><a href="/category/trail-shoes/">Trail Shoes</a>
<a href="/blog/how-to-choose-trail-shoes">Blog</a><a href="/about-us">About</a><a href="/private/admin">Admin</a></nav>"""
FOOTER = """<footer><p>Copyright Acme Outdoor. All rights reserved. Footer boilerplate text that should be ignored.</p>
<a href="/contact">Contact</a></footer><div id="cookie-banner">We use cookies to improve your experience. Accept all cookies.</div>"""


def page(title, desc, h1, body, extra_head=""):
    t = f"<title>{title}</title>" if title is not None else ""
    d = f'<meta name="description" content="{desc}">' if desc is not None else ""
    return f"""<!doctype html><html lang="en-GB"><head>{t}{d}{extra_head}</head>
<body><header class="site-header">Acme Outdoor header</header>{NAV}<main><h1>{h1}</h1>{body}</main>{FOOTER}</body></html>"""


PRODUCT_BODY = """<h2>Features</h2><p>The Ridge Runner 2 trail running shoe has a 6mm drop, a Vibram Megagrip outsole and a
breathable recycled mesh upper. It weighs 280 grams in a UK size 8.</p><ul><li>Vibram Megagrip outsole</li>
<li>Rock plate for protection on technical trails</li><li>Available in UK sizes 6 to 12</li></ul>
<p>Designed for runners who tackle muddy fell routes and rocky mountain paths in wet conditions.</p>"""

ROUTES = {
    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n"),
    "/sitemap.xml": (200, "application/xml", """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>{base}/sitemap-pages.xml</loc></sitemap></sitemapindex>"""),
    "/sitemap-pages.xml": (200, "application/xml", """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{base}/</loc></url><url><loc>{base}/products/ridge-runner-2</loc></url>
<url><loc>{base}/products/summit-gtx?utm_source=sitemap</loc></url><url><loc>{base}/old-page</loc></url>
<url><loc>{base}/thin-page</loc></url></urlset>"""),
    "/": (200, "text/html", page("Home", "Welcome to our website.", "Trail running shoes and outdoor gear",
          "<p>Acme Outdoor designs trail running shoes and waterproof jackets for mountain runners in the UK.</p>"
          "<p>Shop trail shoes, read our running guides and find the right fit for wet and rocky terrain.</p>"
          '<a href="/products/ridge-runner-2?utm_campaign=home&gclid=abc">Ridge Runner</a>'
          '<a href="/missing-page">Broken link</a><a href="/server-error">Error</a><a href="/noindex-page">Old offers</a>'
          '<a href="mailto:hello@example.com">Email</a><a href="https://external.example.org/">External</a>'
          '<a href="/brochure.pdf">Brochure</a>')),
    "/category/trail-shoes/": (200, "text/html", page("Trail Shoes | Acme Outdoor", "Shop trail shoes.", "Trail running shoes",
          "<p>Browse our range of trail running shoes for muddy, rocky and mixed terrain, with grippy outsoles.</p>"
          '<a href="/products/ridge-runner-2">Ridge Runner 2</a><a href="/products/summit-gtx">Summit GTX</a>'
          '<a href="/category/trail-shoes/?page=2">Next</a>',
          extra_head='<link rel="next" href="/category/trail-shoes/?page=2">')),
    "/category/trail-shoes/?page=2": (200, "text/html", page("Trail Shoes | Acme Outdoor", "Shop trail shoes.", "Trail running shoes page 2",
          "<p>More trail running shoes including lightweight racing models and cushioned shoes for long ultras.</p>")),
    "/products/ridge-runner-2": (200, "text/html", page("Ridge Runner 2 | Acme Outdoor", None, "Ridge Runner 2 Trail Running Shoe",
          PRODUCT_BODY, extra_head='<script type="application/ld+json">{"@type":"Product","name":"Ridge Runner 2"}</script>')),
    "/products/summit-gtx": (200, "text/html", page("Ridge Runner 2 | Acme Outdoor", "Waterproof trail shoe.", "Summit GTX Waterproof Trail Shoe",
          "<p>The Summit GTX is a waterproof trail shoe with a Gore-Tex membrane for wet winter running in the hills.</p>"
          "<p>It has a 4mm drop, a wide toe box and aggressive 5mm lugs for grip on soft ground.</p>")),
    "/blog/how-to-choose-trail-shoes": (200, "text/html", page(None, "", "How to choose trail running shoes",
          "<p>Choosing trail running shoes depends on the terrain you run on, the distance and how much cushioning you need.</p>"
          "<h2>Terrain</h2><p>For mud, look for deep lugs. For rocky paths, a rock plate protects your feet.</p>"
          "<h2>Fit</h2><p>Leave a thumb's width of space at the toe for descents.</p>",
          extra_head='<script type="application/ld+json">{"@type":"BlogPosting","headline":"How to choose"}</script>')),
    "/about-us": (200, "text/html", page("About Us | Acme Outdoor", "Learn about Acme Outdoor, a UK brand making trail running gear since 2009.",
          "About Acme Outdoor", "<p>Acme Outdoor was founded in the Lake District in 2009 by fell runners who wanted better shoes.</p>")),
    "/contact": (200, "text/html", page("Contact | Acme Outdoor", "Contact us.", "Contact us", "<p>Email our support team.</p>")),
    "/noindex-page": (200, "text/html", page("Old Offers", "Old offers page.", "Old offers", "<p>Expired offers.</p>",
          extra_head='<meta name="robots" content="noindex, follow">')),
    "/thin-page": (200, "text/html", "<html><head><title>Thin</title></head><body><div></div></body></html>"),
    "/server-error": (500, "text/html", "<h1>Internal error</h1>"),
    "/private/admin": (200, "text/html", page("Admin", "Admin", "Admin", "<p>Secret</p>")),
}
REDIRECTS = {"/old-page": "/about-us"}


class FixtureSite:
    def __init__(self):
        self.hits: dict[str, int] = {}

    def start(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                site.hits[self.path] = site.hits.get(self.path, 0) + 1
                if self.path in REDIRECTS:
                    self.send_response(301)
                    self.send_header("Location", REDIRECTS[self.path])
                    self.end_headers()
                    return
                route = ROUTES.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>Not found</h1>")
                    return
                status, ctype, body = route
                body = body.replace("{base}", site.base)
                self.send_response(status)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
