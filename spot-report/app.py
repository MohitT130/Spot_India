"""Spot India: citizen incident reporting. Flask API + static PWA.

Run locally:   python app.py          (http://localhost:5001)
Vercel:        api/index.py imports `app` from here.

The photo is classified in the browser (CLIP zero-shot via transformers.js), so
no image ever needs to reach a paid vision API. The server's job is to reverse
geocode, compose the authority message, deliver it, and keep the record.
"""
import base64
import binascii
import os

from flask import Flask, jsonify, request, send_from_directory

import catalog
import compose
import deliver
import geo
import storage

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="/static")

MAX_PHOTO_BYTES = 6 * 1024 * 1024


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/track")
@app.get("/track/<tid>")
def track_page(tid=None):
    return send_from_directory(STATIC, "track.html")


@app.get("/feed")
def feed_page():
    return send_from_directory(STATIC, "feed.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(STATIC, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.get("/api/config")
def config():
    """Everything the client needs: categories, CLIP prompts, capability flags."""
    cfg = catalog.public_config()
    cfg["capabilities"] = {
        "server_email": deliver.email_configured(),
        "storage": storage.configured(),
        "photo_storage": storage.configured(),
    }
    cfg["model"] = {
        "id": os.environ.get("CLIP_MODEL", "Xenova/clip-vit-base-patch32"),
        "quantized": True,
        "min_confidence": float(os.environ.get("MIN_CONFIDENCE", "0.18")),
    }
    return jsonify(cfg)


@app.post("/api/locate")
def locate():
    """Reverse geocode. Called as soon as the browser has a GPS fix, so the
    address is already resolved by the time the reporter hits submit."""
    d = request.get_json(silent=True) or {}
    out = geo.describe(d.get("lat"), d.get("lng"))
    if d.get("accuracy") is not None:
        try:
            out["accuracy"] = float(d["accuracy"])
        except (TypeError, ValueError):
            pass
    return jsonify(out)


@app.post("/api/preview")
def preview():
    """Compose the message without sending it, so the reporter can read exactly
    what the authority will receive before deciding to submit."""
    d = request.get_json(silent=True) or {}
    loc = d.get("location") or {}
    if loc.get("lat") is not None and not loc.get("address"):
        loc = {**geo.describe(loc.get("lat"), loc.get("lng")),
               "accuracy": loc.get("accuracy")}
    report = compose.build(
        d.get("category"), loc, note=d.get("note"), reporter=d.get("reporter"),
        confidence=d.get("confidence"), alternatives=d.get("alternatives"),
        answer=d.get("answer"), nearby=_nearby_for(d.get("category"), loc))
    return jsonify({"report": _public(report), "links": deliver.handoff_links(report)})


def _nearby_for(category_id, loc):
    """Nearest real facility for this kind of incident, or None.

    This is what lets the app tell a reporter "Yashoda Hospital, 1.2 km" when
    someone is injured, instead of only naming a department.
    """
    _, auth = catalog.route(category_id)
    if not auth.get("facility") or loc.get("lat") is None:
        return None
    return geo.nearest(loc.get("lat"), loc.get("lng"), auth["facility"])


def _decode_photo(data_url):
    """data: URL -> raw bytes. Returns (bytes, error)."""
    if not data_url:
        return None, None
    try:
        head, _, b64 = data_url.partition(",")
        if not b64 or "base64" not in head:
            return None, "photo must be a base64 data URL"
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None, "photo is not valid base64"
    if len(raw) > MAX_PHOTO_BYTES:
        return None, f"photo exceeds {MAX_PHOTO_BYTES // (1024 * 1024)}MB"
    return raw, None


@app.post("/api/report")
def submit():
    """Compose, deliver and record one report. The order matters: the message is
    always built and the handoff links always returned, so even a total delivery
    and storage failure leaves the reporter able to send it themselves."""
    d = request.get_json(silent=True) or {}
    if not d.get("category"):
        return jsonify({"ok": False, "error": "category is required"}), 400

    loc = d.get("location") or {}
    if loc.get("lat") is not None and not loc.get("address"):
        loc = {**geo.describe(loc.get("lat"), loc.get("lng")),
               "accuracy": loc.get("accuracy")}

    photo, perr = _decode_photo(d.get("photo"))
    report = compose.build(
        d.get("category"), loc, note=d.get("note"), reporter=d.get("reporter"),
        confidence=d.get("confidence"), alternatives=d.get("alternatives"),
        answer=d.get("answer"), nearby=_nearby_for(d.get("category"), loc))
    if d.get("reply_to"):
        report["reply_to"] = d["reply_to"]

    photo_url = storage.upload_photo(report["tracking_id"], photo) if photo else None
    email = deliver.send_email(report, photo)
    links = deliver.handoff_links(report)
    saved = storage.save(report, photo_url=photo_url,
                         delivery={"email": email, "photo_url": photo_url})

    return jsonify({
        "ok": True,
        "tracking_id": report["tracking_id"],
        "report": _public(report),
        "delivery": {"email": email, "links": links, "photo_url": photo_url,
                     "photo_error": perr},
        "stored": saved,
    })


@app.get("/api/report/<tid>")
def get_report(tid):
    row = storage.fetch(tid)
    if not row:
        return jsonify({"ok": False, "error": "not found",
                        "stored": storage.configured()}), 404
    return jsonify({"ok": True, "report": row})


@app.get("/api/feed")
def api_feed():
    return jsonify({"ok": True, "configured": storage.configured(),
                    "reports": storage.recent(request.args.get("limit", 50),
                                              request.args.get("category"))})


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "email": deliver.email_configured(),
                    "storage": storage.configured(),
                    "categories": len(catalog.CATEGORIES)})


def _public(report):
    """Strip nothing today, but keep one place to redact if real authority
    contacts replace the mock ones."""
    return report


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"\n  Spot India report app: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
