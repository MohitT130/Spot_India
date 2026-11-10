"""Report persistence on Supabase, over the PostgREST HTTP API.

Talks HTTP rather than using a Postgres driver, because Vercel's Python
functions are short-lived and a connection pool buys nothing there.

Unconfigured is a supported state, not an error: with no SUPABASE_URL the app
still classifies, composes and delivers, and simply does not keep a record.
Every function returns a status dict and never raises, so a database outage can
never stop a report from reaching the authority.
"""
import os

import requests

TABLE = "spot_reports"
TIMEOUT = 12


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    # Prefer the service key (bypasses RLS, server-side only); fall back to the
    # publishable/anon key, which works with the insert policy in schema.sql.
    key = (os.environ.get("SUPABASE_SERVICE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY")
           or os.environ.get("SUPABASE_KEY"))
    return url, key


def configured():
    url, key = _conf()
    return bool(url and key)


def _headers(key, extra=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def save(report, photo_url=None, delivery=None):
    """Insert one report. Returns {"saved": bool, ...}."""
    url, key = _conf()
    if not (url and key):
        return {"saved": False, "reason": "Supabase not configured", "configured": False}

    loc = report.get("location") or {}
    row = {
        "tracking_id": report["tracking_id"],
        "category_id": report["category"]["id"],
        "category_name": report["category"]["name"],
        "severity": report["severity"]["id"],
        "authority_id": report["authority"]["id"],
        "authority_name": report["authority"]["name"],
        "authority_email": report["authority"]["email"],
        "confidence": report.get("confidence"),
        "lat": loc.get("lat"), "lng": loc.get("lng"),
        "accuracy_m": loc.get("accuracy"),
        "address": loc.get("address"),
        "address_short": loc.get("short"),
        "city": loc.get("city"), "locality": loc.get("locality"),
        "note": report.get("note"), "answer": report.get("answer"),
        "reporter": report.get("reporter"),
        "subject": report["subject"], "body": report["body"],
        "photo_url": photo_url,
        "status": "submitted",
        "delivery": delivery or {},
    }
    try:
        r = requests.post(f"{url}/rest/v1/{TABLE}", json=row, timeout=TIMEOUT,
                          headers=_headers(key, {"Prefer": "return=representation"}))
        if r.status_code >= 400:
            return {"saved": False, "configured": True,
                    "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
        rows = r.json()
        return {"saved": True, "configured": True,
                "id": (rows[0] if isinstance(rows, list) and rows else {}).get("id")}
    except Exception as e:  # noqa: BLE001
        return {"saved": False, "configured": True, "reason": f"{type(e).__name__}: {e}"}


def fetch(tracking_id):
    """Look up one report by tracking id. Returns the row, or None."""
    url, key = _conf()
    if not (url and key):
        return None
    try:
        r = requests.get(f"{url}/rest/v1/{TABLE}", timeout=TIMEOUT,
                         headers=_headers(key),
                         params={"tracking_id": f"eq.{tracking_id}", "limit": 1,
                                 "select": "*"})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001
        return None


def recent(limit=50, category=None):
    """Latest reports, newest first. Powers the authority-side feed."""
    url, key = _conf()
    if not (url and key):
        return []
    params = {"select": "tracking_id,category_id,category_name,severity,status,"
                        "address_short,city,lat,lng,created_at,authority_name",
              "order": "created_at.desc", "limit": max(1, min(int(limit), 200))}
    if category:
        params["category_id"] = f"eq.{category}"
    try:
        r = requests.get(f"{url}/rest/v1/{TABLE}", headers=_headers(key),
                         params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001
        return []


def upload_photo(tracking_id, photo_bytes, content_type="image/jpeg"):
    """Put the photo in the `report-photos` storage bucket, return its public URL.

    Returns None when storage is unconfigured or the bucket is missing; the
    report still goes out with the photo attached to the email.
    """
    url, key = _conf()
    bucket = os.environ.get("SUPABASE_BUCKET", "report-photos")
    if not (url and key and photo_bytes):
        return None
    path = f"{tracking_id}.jpg"
    try:
        r = requests.post(
            f"{url}/storage/v1/object/{bucket}/{path}",
            data=photo_bytes, timeout=TIMEOUT,
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": content_type, "x-upsert": "true"})
        if r.status_code >= 400:
            return None
        return f"{url}/storage/v1/object/public/{bucket}/{path}"
    except Exception:  # noqa: BLE001
        return None
