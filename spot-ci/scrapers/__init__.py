"""Live scrapers. Each scraper returns a dict: {ok, source, competitor, data, error, ms}.

Design rules
- Never raise. A failed source must not break the dashboard, it just shows red in the scrape log.
- Parse with several strategies and report which fields were found, so a changed page layout is visible.
- Sites are fetched politely: one request per source per refresh, a real User-Agent, a hard timeout.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

from config import COMPETITORS, FEATURES, PAIN_THEMES

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 SpotIndia-CI-Research/1.0"
TIMEOUT = 12


def _get(url, **kw):
    return requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=TIMEOUT, **kw)


def _wrap(source, competitor, fn):
    t0 = time.time()
    try:
        data = fn()
        ok = bool(data) and not data.get("_empty")
        return {"ok": ok, "source": source, "competitor": competitor, "data": data, "error": None if ok else "no fields parsed",
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001 - deliberate: scrapers must never crash the app
        return {"ok": False, "source": source, "competitor": competitor, "data": {}, "error": ("Network unreachable from this host" if "ProxyError" in str(e) or "ConnectionError" in type(e).__name__ else f"{type(e).__name__}: {str(e)[:100]}"),
                "ms": int((time.time() - t0) * 1000)}


# ----------------------------------------------------------------------------- number helpers
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "l": 1e5, "lakh": 1e5, "cr": 1e7, "crore": 1e7, "million": 1e6, "thousand": 1e3}


def parse_count(text):
    """'50L+' -> 5_000_000, '1M+' -> 1_000_000, '22.2K' -> 22200, '2.7 crore' -> 27_000_000."""
    if not text:
        return None
    m = re.search(r"([\d][\d,]*\.?\d*)\s*(k|m|b|l|lakh|cr|crore|million|thousand)?\b", text.strip(), re.I)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = _MULT.get((m.group(2) or "").lower(), 1)
    return int(num * mult)


# ----------------------------------------------------------------------------- Google Play (BeautifulSoup)
def scrape_play(pkg):
    """Parse a Play Store listing. Strategy 1: JSON-LD. Strategy 2: visible text. Strategy 3: raw HTML."""
    r = _get("https://play.google.com/store/apps/details", params={"id": pkg, "hl": "en", "gl": "US"})
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "lxml")
    out = {"url": r.url}

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(tag.string or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(ld, dict) and ld.get("name"):
            out["name"] = ld["name"]
            ar = ld.get("aggregateRating") or {}
            if ar.get("ratingValue") is not None:
                out["rating"] = round(float(ar["ratingValue"]), 2)
            if ar.get("ratingCount") is not None:
                out["reviews"] = int(float(ar["ratingCount"]))
            break

    text = soup.get_text(" ", strip=True)
    m = re.search(r"([\d.,]+\s*[KMB]?)\+?\s*Downloads", text, re.I)
    if m:
        out["installs"] = parse_count(m.group(1))
        out["installs_bucket"] = m.group(0).strip()
    if "rating" not in out:
        m = re.search(r"\b([1-5]\.\d)\s*star", text, re.I)
        if m:
            out["rating"] = float(m.group(1))
    if "reviews" not in out:
        m = re.search(r"([\d.,]+\s*[KMB]?)\s*reviews", text, re.I)
        if m:
            out["reviews"] = parse_count(m.group(1))
    m = re.search(r"Updated on\s+([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", text) or re.search(r"Updated on\s+([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", html)
    if m:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                out["updated"] = datetime.strptime(m.group(1), fmt).date().isoformat()
                break
            except ValueError:
                pass
    m = re.search(r"What.s new\s*(.{0,240})", text)
    if m:
        out["whats_new"] = m.group(1).strip()
    # A handful of review snippets are server-rendered. Count pain themes on whatever text is present.
    out["pain_hits"] = pain_hits(text)
    if not any(k in out for k in ("installs", "rating", "reviews", "updated")):
        out["_empty"] = True
    return out


def pain_hits(text):
    t = text.lower()
    return {theme: sum(t.count(k) for k in kws) for theme, kws in PAIN_THEMES.items() if any(k in t for k in kws)}


# ----------------------------------------------------------------------------- Apple App Store (iTunes lookup JSON)
def scrape_ios(app_id):
    r = _get("https://itunes.apple.com/lookup", params={"id": app_id, "country": "in"})
    r.raise_for_status()
    res = (r.json().get("results") or [None])[0]
    if not res:
        return {"_empty": True}
    return {
        "name": res.get("trackName"),
        "rating": round(res.get("averageUserRating", 0), 2) or None,
        "reviews": res.get("userRatingCount"),
        "version": res.get("version"),
        "updated": (res.get("currentVersionReleaseDate") or "")[:10] or None,
        "whats_new": (res.get("releaseNotes") or "")[:240],
    }


# ----------------------------------------------------------------------------- Google News RSS (BeautifulSoup, xml)
NEWS_RULES = [
    ("funding", ["raises", "funding", "grant", "invest", "award"]),
    ("expansion", ["expands", "rolled out", "extends", "now in", "cities", "districts", "ward"]),
    ("launch", ["launch", "unveil", "introduc", "inaugurat"]),
    ("policy", ["high court", "mou", "tender", "government", "ministry", "corporation", "directive", "order"]),
    ("feature", ["new feature", "update", "upgrade", "integrat", "ai-", "whatsapp"]),
]


def classify_news(title):
    t = title.lower()
    for typ, kws in NEWS_RULES:
        if any(k in t for k in kws):
            return typ
    return "news"


def scrape_news(query, max_items=8):
    r = _get("https://news.google.com/rss/search", params={"q": query + " when:730d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "xml")
    items = []
    for it in soup.find_all("item")[:max_items]:
        title = (it.title.get_text() if it.title else "").strip()
        link = (it.link.get_text() if it.link else "").strip()
        pub = it.pubDate.get_text() if it.pubDate else ""
        try:
            d = parsedate_to_datetime(pub).astimezone(timezone.utc).date().isoformat()
        except Exception:  # noqa: BLE001
            continue
        src = it.source.get_text() if it.source else ""
        items.append({"date": d, "title": title, "url": link, "publisher": src, "type": classify_news(title)})
    return {"items": items} if items else {"_empty": True}


# ----------------------------------------------------------------------------- Website (profile + KPI extraction)
KPI_PATTERNS = [
    ("citizens_engaged", r"([\d.,]+\s*(?:crore|lakh|million|cr|l|m)\+?)\s*(?:citizens|users|registered users)"),
    ("complaints", r"([\d.,]+\s*(?:crore|lakh|million|cr|l|m)\+?)\s*(?:complaints|reports|issues)"),
    ("cities", r"([\d,]+\+?)\s*(?:cities|towns|ulbs|wards)"),
    ("resolution_rate", r"(\d{2,3}(?:\.\d+)?\s*%)\s*(?:resolution|resolved|average)"),
    ("organizations", r"([\d,]+\+?)\s*(?:organi[sz]ations|campuses|institutions|clients)"),
]


def scrape_site(url, role="profile"):
    r = _get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    meta = {m.get("name") or m.get("property"): m.get("content") for m in soup.find_all("meta") if m.get("content")}
    out = {
        "title": (soup.title.string or "").strip() if soup.title else "",
        "description": meta.get("description") or meta.get("og:description") or "",
        "keywords": meta.get("keywords", ""),
        "headings": [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])][:12],
        "text_chars": len(text),
        "content_hash": hashlib.sha1((text + meta.get("description", "")).encode()).hexdigest()[:12],
    }
    blob = (text + " " + out["description"] + " " + out["keywords"]).lower()
    out["feature_hits"] = [f["id"] for f in FEATURES if any(k in blob for k in f["kw"])]
    if role == "kpi":
        kpis = {}
        for name, pat in KPI_PATTERNS:
            m = re.search(pat, text, re.I)
            if m:
                kpis[name] = {"raw": m.group(1).strip(), "value": parse_count(m.group(1))}
        out["kpis"] = kpis
    if not (out["title"] or out["description"] or out["text_chars"] > 200):
        out["_empty"] = True
    return out


# ----------------------------------------------------------------------------- GitHub (prototype competitors)
def scrape_github(repo):
    base = f"https://api.github.com/repos/{repo}"
    r = _get(base, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    d = r.json()
    commits = None
    rc = requests.get(base + "/commits", params={"per_page": 1}, headers={"User-Agent": UA}, timeout=TIMEOUT)
    if rc.ok:
        m = re.search(r'[?&]page=(\d+)>; rel="last"', rc.headers.get("Link", ""))
        commits = int(m.group(1)) if m else len(rc.json())
    return {"stars": d.get("stargazers_count"), "forks": d.get("forks_count"), "pushed_at": (d.get("pushed_at") or "")[:10],
            "created_at": (d.get("created_at") or "")[:10], "commits": commits, "open_issues": d.get("open_issues_count"),
            "description": d.get("description")}


# ----------------------------------------------------------------------------- job list
def jobs():
    """All scrape jobs as (label, competitor_id, callable)."""
    out = []
    for c in COMPETITORS:
        cid = c["id"]
        if c.get("play_pkg"):
            out.append((f"Play Store · {c['short']}", cid, "play", lambda p=c["play_pkg"]: scrape_play(p)))
        if c.get("ios_id"):
            out.append((f"App Store · {c['short']}", cid, "ios", lambda i=c["ios_id"]: scrape_ios(i)))
        for s in c.get("sites", []):
            host = re.sub(r"^https?://(www\.)?", "", s["url"]).rstrip("/")
            out.append((f"Website · {host[:46]}", cid, "site", lambda u=s["url"], ro=s["role"]: scrape_site(u, ro)))
        if c.get("github"):
            out.append((f"GitHub · {c['github']}", cid, "github", lambda g=c["github"]: scrape_github(g)))
        out.append((f"News · {c['short']}", cid, "news", lambda q=c["news_q"]: scrape_news(q)))
    return out


def run_job(job):
    label, cid, kind, fn = job
    res = _wrap(label, cid, fn)
    res["kind"] = kind
    return res
