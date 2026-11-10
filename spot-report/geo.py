"""Reverse geocoding: GPS coordinates -> a human-readable Indian address.

Uses OpenStreetMap Nominatim, which is free and needs no API key. Their usage
policy requires an identifying User-Agent and at most one request per second,
so this runs server-side (the browser cannot set a User-Agent) and keeps a
small in-process cache plus a rate gate.

Never raises. A failure returns coordinates only, because a report with exact
GPS and no street name is still perfectly actionable.
"""
import os
import threading
import time

import requests

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
CONTACT = os.environ.get("NOMINATIM_CONTACT", "spot-india-report")
UA = f"SpotIndiaReport/1.0 ({CONTACT})"

_lock = threading.Lock()
_last_call = [0.0]
_cache = {}
_CACHE_MAX = 256
# ~4 decimal places is about 11 m: tight enough to be a distinct place, loose
# enough that repeated reports from one spot reuse the cached address.
_PRECISION = 4


def _gate():
    """Hold callers to Nominatim's one-request-per-second policy."""
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def describe(lat, lng, timeout=8):
    """Return a dict describing the location. Always succeeds."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return {"ok": False, "error": "no coordinates", "lat": None, "lng": None,
                "address": None, "short": "Location not provided", "maps": None}

    out = {"ok": False, "lat": lat, "lng": lng, "address": None,
           "maps": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}",
           "osm": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=19/{lat}/{lng}"}

    key = (round(lat, _PRECISION), round(lng, _PRECISION))
    if key in _cache:
        return {**out, **_cache[key], "cached": True}

    try:
        _gate()
        r = requests.get(
            NOMINATIM,
            params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18,
                    "addressdetails": 1, "accept-language": "en"},
            headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        a = d.get("address") or {}
        # Nominatim's locality key varies by place; take the first that exists.
        locality = next((a[k] for k in ("suburb", "neighbourhood", "village",
                                        "town", "city_district", "county")
                         if a.get(k)), None)
        city = next((a[k] for k in ("city", "town", "municipality", "state_district")
                     if a.get(k)), None)
        road = a.get("road") or a.get("pedestrian") or a.get("footway")
        short = ", ".join([p for p in (road, locality, city) if p]) or d.get("display_name")
        found = {
            "ok": True,
            "address": d.get("display_name"),
            "short": short,
            "road": road, "locality": locality, "city": city,
            "ward": a.get("city_block") or a.get("quarter"),
            "postcode": a.get("postcode"),
            "state": a.get("state"),
        }
        with _lock:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = found
        return {**out, **found}
    except Exception as e:  # noqa: BLE001 - never let geocoding break a report
        return {**out, "error": f"{type(e).__name__}", "short": f"{lat:.5f}, {lng:.5f}"}


# --- Nearest real facility -------------------------------------------------
# For an emergency the reporter needs to know where actual help is, not just
# which department owns the paperwork. Overpass is free and keyless; it is also
# sometimes slow or down, so every failure here is silent and non-blocking.
# Overpass returns 502 "at capacity" fairly often, so try mirrors in turn.
OVERPASS_MIRRORS = [m for m in [
    os.environ.get("OVERPASS_URL"),
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
] if m]
_fac_cache = {}


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 6371.0 * 2 * asin(sqrt(a))


def _from_nominatim(lat, lng, amenity, radius_m, timeout):
    """Bounded viewbox search on Nominatim. Far more reliable than Overpass,
    which is frequently at capacity, so this is tried first."""
    from math import cos, radians
    dlat = radius_m / 111_320.0
    dlng = radius_m / max(1.0, 111_320.0 * cos(radians(lat)))
    viewbox = f"{lng - dlng},{lat + dlat},{lng + dlng},{lat - dlat}"
    try:
        _gate()
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": amenity.replace("_", " "), "format": "jsonv2",
                    "viewbox": viewbox, "bounded": 1, "limit": 20,
                    "extratags": 1, "accept-language": "en"},
            headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        best = None
        for d in r.json() or []:
            if d.get("type") != amenity and d.get("class") != "amenity":
                continue
            try:
                dl, dn = float(d["lat"]), float(d["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            name = (d.get("name") or "").strip() or (d.get("display_name") or "").split(",")[0]
            if not name:
                continue
            km = _haversine_km(lat, lng, dl, dn)
            if best is None or km < best["distance_km"]:
                best = {
                    "name": name, "amenity": amenity, "distance_km": round(km, 2),
                    "phone": (d.get("extratags") or {}).get("phone"),
                    "lat": dl, "lng": dn,
                    "maps": f"https://www.google.com/maps/search/?api=1&query={dl},{dn}",
                    "source": "nominatim",
                }
        return best
    except Exception:  # noqa: BLE001
        return None


def nearest(lat, lng, amenity, radius_m=4000, timeout=12):
    """Closest facility of this kind. Returns None when nothing is found.

    Advisory only: it tells the reporter where real help is. Never blocks a
    report, because both upstreams are free services that go down.
    """
    if not amenity:
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None

    key = (round(lat, 3), round(lng, 3), amenity)
    if key in _fac_cache:
        return _fac_cache[key]

    hit = _from_nominatim(lat, lng, amenity, radius_m, timeout)
    if hit:
        with _lock:
            if len(_fac_cache) >= _CACHE_MAX:
                _fac_cache.clear()
            _fac_cache[key] = hit
        return hit

    # `out` takes verbosity BEFORE geometry: "tags center", not "center tags".
    # The wrong order is a parse error and silently yields nothing.
    q = (f'[out:json][timeout:{timeout}];'
         f'nwr(around:{radius_m},{lat},{lng})["amenity"="{amenity}"];'
         f'out tags center 20;')
    data = None
    for mirror in OVERPASS_MIRRORS:
        try:
            r = requests.post(mirror, data={"data": q},
                              headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code >= 400:
                continue  # at capacity or rate limited: try the next mirror
            data = r.json()
            break
        except Exception:  # noqa: BLE001
            continue
    if data is None:
        return None

    try:
        best = None
        for el in (data.get("elements") or []):
            c = el.get("center") or ({"lat": el.get("lat"), "lon": el.get("lon")})
            if c.get("lat") is None or c.get("lon") is None:
                continue
            tags = el.get("tags") or {}
            name = tags.get("name") or tags.get("operator")
            if not name:
                continue  # an unnamed point is useless to a person on the street
            d = _haversine_km(lat, lng, c["lat"], c["lon"])
            if best is None or d < best["distance_km"]:
                best = {
                    "name": name,
                    "amenity": amenity,
                    "distance_km": round(d, 2),
                    "phone": tags.get("phone") or tags.get("contact:phone"),
                    "lat": c["lat"], "lng": c["lon"],
                    "maps": f"https://www.google.com/maps/search/?api=1&query={c['lat']},{c['lon']}",
                }
        if len(_fac_cache) >= _CACHE_MAX:
            _fac_cache.clear()
        _fac_cache[key] = best
        return best
    except Exception:  # noqa: BLE001 - advisory only, never block a report
        return None
