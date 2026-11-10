"""Spot India Competitive Intelligence platform: Flask app.

Run locally:   python app.py          (opens on http://localhost:5000)
Vercel:        api/index.py imports `app` from here.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

import engine
import scrapers
import store
from config import COMPETITORS, FEATURES, PHASES, SPOT_USP, EVENT_TYPES

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(ROOT, "static"), static_url_path="/static")


@app.get("/")
def index():
    return send_from_directory(os.path.join(ROOT, "static"), "index.html")


@app.get("/api/config")
def config():
    return jsonify({
        "competitors": [{k: c[k] for k in ("id", "name", "short", "color", "color_dark", "kind", "geo")} for c in COMPETITORS],
        "features": [{"id": f["id"], "name": f["name"]} for f in FEATURES],
        "phases": PHASES, "event_types": EVENT_TYPES, "usp": SPOT_USP,
        "defaults": engine.DEFAULT_ASSUMPTIONS, "stateless": bool(os.environ.get("VERCEL")), "llm": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


@app.post("/api/dashboard")
def dashboard():
    cfg = request.get_json(silent=True) or {}
    return jsonify(engine.build(store.dataset(cfg.get("live")), cfg))


@app.post("/api/refresh")
def refresh():
    """Run every scraper concurrently and stream one JSON line per finished source (NDJSON)."""
    jobs = scrapers.jobs()
    base = (request.get_json(silent=True) or {}).get("live")

    def gen():
        results = []
        yield json.dumps({"event": "start", "total": len(jobs), "sources": [j[0] for j in jobs]}) + "\n"
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(scrapers.run_job, j): j for j in jobs}
            for f in as_completed(futs):
                r = f.result()
                results.append(r)
                brief = {k: r[k] for k in ("source", "competitor", "ok", "ms", "error", "kind")}
                yield json.dumps({"event": "source", **brief}) + "\n"
        stateless = bool(os.environ.get("VERCEL"))
        notes, hist = store.apply_results(results, persist=not stateless, base=base)
        yield json.dumps({"event": "done", "ok": sum(1 for r in results if r["ok"]), "total": len(results), "notes": notes, "history": hist if stateless else None}) + "\n"

    return Response(gen(), mimetype="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/narrative")
def narrative():
    """Optional: a written briefing. Uses Claude when ANTHROPIC_API_KEY is set, otherwise a deterministic template."""
    cfg = request.get_json(silent=True) or {}
    out = engine.build(store.dataset(cfg.get("live")), cfg)
    top = out["steps"][:8]
    facts = {
        "insights": out["insights"],
        "competitors": [{k: c[k] for k in ("short", "phase_name", "status", "growth_index", "reach", "rating")} for c in out["cards"]],
        "steps": [{k: s[k] for k in ("phase", "type", "title", "why")} for s in top],
        "revenue": {"benchmark": out["revenue"]["benchmark"]["name"], "parity_month": out["revenue"]["parity_month"], "paces": out["revenue"]["paces"]},
    }
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 700,
                      "messages": [{"role": "user", "content": "You advise the owner of Spot India, a civic incident reporting startup (animals, accidents, abuse, potholes, who-to-contact routing). "
                                    "Using ONLY these competitor-intelligence facts, write a 150-word briefing: what competitors are doing, the three most important moves for Spot India, and one risk. "
                                    "Plain prose, no em dashes, no invented numbers.\n\n" + json.dumps(facts)}]},
                timeout=30)
            r.raise_for_status()
            return jsonify({"source": "claude", "text": r.json()["content"][0]["text"]})
        except Exception as e:  # noqa: BLE001
            err = f"Claude unavailable ({type(e).__name__}); showing rule-based briefing."
    else:
        err = None
    ins = {i["label"]: i for i in out["insights"]}
    lines = [
        f"{ins['Strongest active competitor']['value']} is the strongest active competitor ({ins['Strongest active competitor']['sub']}).",
        f"{ins['Dormant competitors']['value']} tracked competitor(s) have gone quiet: {ins['Dormant competitors']['sub']}.",
        "Top moves: " + "; ".join(f"{s['title']}" for s in top[:3]) + ".",
        f"Modelled revenue parity with {out['revenue']['benchmark']['name']}: {ins['Revenue parity']['value'].lower()}.",
    ]
    return jsonify({"source": "rules", "text": " ".join(lines), "note": err})


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Spot India CI platform: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
