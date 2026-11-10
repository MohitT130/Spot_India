"""Persistence and merge layer. Seed data is immutable; live scrapes append to a history file."""
import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from seed import SEED

_LOCK = threading.Lock()


def _history_path():
    base = os.environ.get("CI_DATA_DIR") or os.path.join(os.path.dirname(__file__), "data")
    try:
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".w")
        open(probe, "w").close()
        os.remove(probe)
    except OSError:  # read-only filesystem (e.g. serverless): fall back to the temp dir
        base = tempfile.gettempdir()
    return os.path.join(base, "history.json")


def _empty():
    return {"runs": [], "metrics": [], "events": [], "hashes": {}, "pain_live": {}, "site_hits": {}, "last_refresh": None, "log": []}


def load_history():
    p = _history_path()
    try:
        with open(p) as f:
            h = json.load(f)
            for k, v in _empty().items():
                h.setdefault(k, v)
            return h
    except (OSError, json.JSONDecodeError):
        return _empty()


def save_history(h):
    p = _history_path()
    try:
        with open(p, "w") as f:
            json.dump(h, f, indent=1)
    except OSError:
        pass


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def apply_results(results, persist=True, base=None):
    """Fold a list of scraper results into history. Returns (summary notes, history dict)."""
    with _LOCK:
        h = base if _valid(base) else load_history()
        for k, v in _empty().items():
            h.setdefault(k, v)
        today = _today()
        notes = []
        for r in results:
            cid = r["competitor"]
            d = r.get("data") or {}
            if not r["ok"]:
                continue
            kind = r["kind"]
            src = r["source"]
            if kind == "play":
                if d.get("installs"):
                    h["metrics"].append({"date": today, "competitor": cid, "key": "reach", "value": d["installs"], "kind": "Play installs (live)", "src": "live"})
                if d.get("rating"):
                    h["metrics"].append({"date": today, "competitor": cid, "key": "rating", "value": d["rating"], "kind": "Play rating (live)", "src": "live"})
                if d.get("reviews"):
                    h["metrics"].append({"date": today, "competitor": cid, "key": "reviews", "value": d["reviews"], "kind": "Play reviews (live)", "src": "live"})
                if d.get("updated"):
                    h["events"].append({"date": d["updated"], "competitor": cid, "precision": "day", "phase": None, "type": "feature", "conf": "high",
                                        "title": "Play Store listing updated", "detail": (d.get("whats_new") or "")[:200], "src": "live", "url": d.get("url")})
                if d.get("pain_hits"):
                    h["pain_live"].setdefault(cid, {})
                    for t, n in d["pain_hits"].items():
                        h["pain_live"][cid][t] = max(h["pain_live"][cid].get(t, 0), n)
                notes.append(f"{src}: {d.get('installs_bucket') or 'listing parsed'}")
            elif kind == "ios":
                if d.get("rating"):
                    h["metrics"].append({"date": today, "competitor": cid, "key": "rating", "value": d["rating"], "kind": "App Store rating (live)", "src": "live"})
                if d.get("updated"):
                    h["events"].append({"date": d["updated"], "competitor": cid, "precision": "day", "phase": None, "type": "feature", "conf": "high",
                                        "title": f"App Store release {d.get('version', '')}".strip(), "detail": (d.get("whats_new") or "")[:200], "src": "live"})
                notes.append(f"{src}: v{d.get('version')}")
            elif kind == "site":
                prev = h["hashes"].get(src)
                cur = d.get("content_hash")
                if prev and cur and prev != cur:
                    h["events"].append({"date": today, "competitor": cid, "precision": "day", "phase": None, "type": "news", "conf": "medium",
                                        "title": "Website content changed since last scrape", "detail": src, "src": "live"})
                    notes.append(f"{src}: CONTENT CHANGED")
                if cur:
                    h["hashes"][src] = cur
                h["site_hits"][cid] = sorted(set(h["site_hits"].get(cid, [])) | set(d.get("feature_hits", [])))
                for k, v in (d.get("kpis") or {}).items():
                    if k in ("cities", "complaints") and v.get("value"):
                        key = "cities" if k == "cities" else "complaints"
                        h["metrics"].append({"date": today, "competitor": cid, "key": key, "value": v["value"], "kind": f"{k} (website, live)", "src": "live"})
            elif kind == "github":
                if d.get("stars") is not None:
                    h["metrics"].append({"date": today, "competitor": cid, "key": "stars", "value": d["stars"], "kind": "GitHub stars", "src": "live"})
                if d.get("commits"):
                    h["metrics"].append({"date": today, "competitor": cid, "key": "commits", "value": d["commits"], "kind": "GitHub commits", "src": "live"})
                notes.append(f"{src}: {d.get('stars')} stars, {d.get('commits')} commits")
            elif kind == "news":
                seen = {e.get("url") for e in h["events"] if e.get("url")}
                added = 0
                for it in d.get("items", []):
                    if it["url"] in seen:
                        continue
                    h["events"].append({"date": it["date"], "competitor": cid, "precision": "day", "phase": None, "type": it["type"], "conf": "medium",
                                        "title": it["title"], "detail": it.get("publisher", ""), "src": "live", "url": it["url"]})
                    added += 1
                if added:
                    notes.append(f"{src}: +{added} headlines")
        # de-duplicate metrics recorded twice on the same day for the same key
        uniq = {}
        for m in h["metrics"]:
            uniq[(m["competitor"], m["key"], m["date"], m["kind"])] = m
        h["metrics"] = list(uniq.values())
        h["last_refresh"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        h["log"] = [{"source": r["source"], "ok": r["ok"], "ms": r["ms"], "error": r["error"], "kind": r["kind"]} for r in results]
        h["runs"].append({"ts": h["last_refresh"], "ok": sum(1 for r in results if r["ok"]), "total": len(results)})
        h["runs"] = h["runs"][-50:]
        if persist:
            save_history(h)
        return notes, h


def _valid(h):
    return isinstance(h, dict) and all(isinstance(h.get(k), list) for k in ("metrics", "events", "log")) and isinstance(h.get("pain_live"), dict) and isinstance(h.get("site_hits"), dict)


def dataset(override=None):
    """Seed merged with live history. `override` is a client-held history (used on stateless hosts)."""
    h = override if _valid(override) else load_history()
    h.setdefault("runs", [])
    seed = copy.deepcopy(SEED)
    for cid, c in seed["competitors"].items():
        c["id"] = cid
        c["live_metrics"] = 0
        for m in h["metrics"]:
            if m["competitor"] == cid:
                c["metrics"].append({k: v for k, v in m.items() if k != "competitor"})
                c["live_metrics"] += 1
        for e in h["events"]:
            if e["competitor"] == cid:
                c["events"].append({k: v for k, v in e.items() if k != "competitor"})
        for t, n in (h["pain_live"].get(cid) or {}).items():
            c["pain"].append({"theme": t, "text": f"{n} mention(s) in live Play listing text", "basis": "live", "src": "live"})
        # last_release moves forward if a live release date is newer
        rel = [e["date"] for e in c["events"] if e["type"] in ("feature", "launch") and e["date"] <= _today()]
        if rel:
            newest = max(rel)
            if not c.get("last_release") or newest > c["last_release"]:
                c["last_release"] = newest
        c["site_hits"] = h["site_hits"].get(cid, [])
    seed["meta"] = {"last_refresh": h["last_refresh"], "runs": h["runs"][-5:], "log": h["log"], "stateless": bool(os.environ.get("VERCEL")), "history_path": _history_path()}
    return seed
