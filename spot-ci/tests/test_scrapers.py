"""Parser tests using fixtures that mimic each source. Run: python -m pytest tests -q  (or python tests/test_scrapers.py)"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scrapers

class R:
    def __init__(self, text="", js=None, headers=None):
        self.text = text; self.content = text.encode(); self._js = js; self.url = "http://x"; self.headers = headers or {}; self.ok = True
    def raise_for_status(self): pass
    def json(self): return self._js

PLAY = """<html><head><script type="application/ld+json">{"@type":"SoftwareApplication","name":"Swachhata-MoHUA","aggregateRating":{"ratingValue":"2.3","ratingCount":"65600"}}</script></head>
<body><div>2.3 star 65.9K reviews</div><div>5M+ Downloads</div><div>Updated on May 13, 2026</div><div>What's new Users can edit or delete complaints, gallery upload not working for some, login crash</div></body></html>"""
NEWS = """<?xml version="1.0"?><rss><channel>
<item><title>GHMC launches MyCURE app to integrate civic services</title><link>https://n/1</link><pubDate>Thu, 19 Feb 2026 08:00:00 GMT</pubDate><source>Siasat</source></item>
<item><title>High Court orders pothole app extension</title><link>https://n/2</link><pubDate>Fri, 24 Jan 2025 08:00:00 GMT</pubDate><source>DC</source></item></channel></rss>"""
SITE = """<html><head><title>Swachhata Technology Platform</title><meta name="description" content="Citizen app, engineer app and councillor app"></head>
<body><h1>Swachhata</h1><p>2.15 crore+ citizens engaged. 2.7 crore+ complaints registered. 4,503 cities onboarded. Average 93% resolution rate. Reopen and feedback supported. Hindi and Kannada.</p></body></html>"""

def test_parse_count():
    assert scrapers.parse_count("50L+") == 5_000_000
    assert scrapers.parse_count("1M+") == 1_000_000
    assert scrapers.parse_count("22.2K") == 22_200
    assert scrapers.parse_count("2.7 crore") == 27_000_000
    assert scrapers.parse_count("4,503") == 4503

def test_play(monkeypatch=None):
    scrapers._get = lambda *a, **k: R(PLAY)
    d = scrapers.scrape_play("x")
    assert d["rating"] == 2.3 and d["reviews"] == 65600 and d["installs"] == 5_000_000 and d["updated"] == "2026-05-13", d
    assert "crashes_login" in d["pain_hits"] and "no_gallery_upload" in d["pain_hits"], d["pain_hits"]

def test_news():
    scrapers._get = lambda *a, **k: R(NEWS)
    d = scrapers.scrape_news("q")
    assert len(d["items"]) == 2 and d["items"][0]["date"] == "2026-02-19" and d["items"][0]["type"] == "launch", d
    assert d["items"][1]["type"] == "policy", d

def test_site_kpis():
    scrapers._get = lambda *a, **k: R(SITE)
    d = scrapers.scrape_site("http://x", "kpi")
    k = d["kpis"]
    assert k["complaints"]["value"] == 27_000_000, k
    assert k["cities"]["value"] == 4503, k
    assert "reopen_feedback" in d["feature_hits"] and "multilingual" in d["feature_hits"], d["feature_hits"]

def test_ios():
    scrapers._get = lambda *a, **k: R(js={"results": [{"trackName": "X", "averageUserRating": 3.4, "userRatingCount": 89, "version": "3.6.47", "currentVersionReleaseDate": "2026-04-25T10:00:00Z", "releaseNotes": "n"}]})
    d = scrapers.scrape_ios("1")
    assert d["rating"] == 3.4 and d["updated"] == "2026-04-25"

def test_failure_is_contained():
    def boom(*a, **k): raise RuntimeError("down")
    scrapers._get = boom
    r = scrapers._wrap("src", "c", lambda: scrapers.scrape_ios("1"))
    assert r["ok"] is False and "down" in r["error"]

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
