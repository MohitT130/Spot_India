"""Turns a classified report into the actual message sent to the authority.

One source of truth for wording, used by every channel: the email body, the
WhatsApp text and the SMS text are all derived from the same facts, so the
authority reads the same thing however it arrives.

Deliberately template-based, not LLM-written: an incident report must never
contain invented detail, and a civic authority needs the same fields in the
same order every time so it can be processed at a glance.
"""
import datetime as dt
import secrets

from catalog import SEVERITY, route

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1: read aloud over a phone


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def tracking_id(now=None):
    """Short, human-readable, collision-resistant: SPOT-261102-K7QX9F.

    Dated in IST, not UTC, so the code a reporter reads matches the date they
    and the authority are living in.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(6))
    return f"SPOT-{now.astimezone(IST):%y%m%d}-{rand}"


def _ist(now):
    """India Standard Time, written out. Authorities work in IST."""
    return now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def build(category_id, location, *, note=None, reporter=None, confidence=None,
          alternatives=None, tid=None, now=None, answer=None, nearby=None):
    """Assemble every piece of text and metadata for one report."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cat, auth = route(category_id)
    sev = SEVERITY[cat["severity"]]
    tid = tid or tracking_id(now)

    where = location.get("short") or "Location unavailable"
    addr = location.get("address") or where
    maps = location.get("maps")
    lat, lng = location.get("lat"), location.get("lng")
    coords = f"{lat:.6f}, {lng:.6f}" if isinstance(lat, float) and isinstance(lng, float) else "not available"
    acc = location.get("accuracy")

    subject = f"[{sev['label'].upper()}] {cat['name']} at {where} ({tid})"

    lines = [
        f"INCIDENT REPORT  {tid}",
        "",
        f"Category    : {cat['name']}",
        f"Severity    : {sev['label']} - {sev['blurb']}",
        f"Routed to   : {auth['name']}",
        f"Department  : {auth['dept']}",
        f"Reported at : {_ist(now)}",
        "",
        "LOCATION",
        f"  Address   : {addr}",
        f"  Coordinates: {coords}" + (f" (accurate to ~{round(acc)} m)" if acc else ""),
    ]
    if maps:
        lines.append(f"  Map       : {maps}")
    lines.append("")

    lines.append("WHAT WAS DETECTED")
    if confidence is not None:
        lines.append(f"  On-device image analysis matched this scene to '{cat['name']}'")
        lines.append(f"  with {round(confidence * 100)}% confidence.")
    else:
        lines.append("  Category chosen manually by the reporter.")
    if alternatives:
        others = ", ".join(f"{a['name']} ({round(a['score'] * 100)}%)" for a in alternatives[:3])
        lines.append(f"  Other possibilities considered: {others}")
    lines.append("")

    if nearby:
        lines += ["NEAREST HELP TO THE SCENE",
                  f"  {nearby['name']} ({nearby['amenity'].replace('_', ' ')}), "
                  f"about {nearby['distance_km']} km away"]
        if nearby.get("phone"):
            lines.append(f"  Phone: {nearby['phone']}")
        if nearby.get("maps"):
            lines.append(f"  Map  : {nearby['maps']}")
        lines.append("")

    if answer:
        lines += ["REPORTER'S ANSWER", f"  Q: {cat['ask']}", f"  A: {answer}", ""]
    if note:
        lines += ["REPORTER'S NOTE", f"  {note}", ""]

    if cat.get("caution"):
        lines += ["IMPORTANT", f"  {cat['caution']}", ""]
    if auth.get("extra_helplines"):
        lines.append("OTHER HELPLINES")
        for h in auth["extra_helplines"]:
            lines.append(f"  {h['label']}: {h['number']}")
        lines.append("")

    lines += [
        "REPORTER",
        f"  {reporter or 'Anonymous citizen'}",
        "",
        "ESCALATION PATH",
        f"  If unresolved within {sev['sla_hours']} hour(s): {auth['escalation']}",
        "",
        f"Reference this report as {tid} in any reply.",
        "Sent via Spot India, a citizen incident reporting platform.",
    ]
    body = "\n".join(lines)

    # WhatsApp and SMS get a compressed form: a responder reads these on a phone.
    wa = "\n".join([
        f"*Spot India - {sev['label']} report*",
        f"*{cat['name']}*",
        f"Ref: {tid}",
        f"Where: {where}",
        f"Coords: {coords}",
        *( [f"Map: {maps}"] if maps else [] ),
        *( [f"Note: {note}"] if note else [] ),
        f"For: {auth['public_name']}",
        *( [f"Helpline: {auth['helpline']}"] if auth.get("helpline") else [] ),
        *( [f"Nearest: {nearby['name']} ({nearby['distance_km']} km)"] if nearby else [] ),
        f"Time: {_ist(now)}",
    ])
    sms = (f"SPOT INDIA {sev['label'].upper()}: {cat['name']} at {where}. "
           f"Ref {tid}. {maps or coords}")

    return {
        "tracking_id": tid,
        "category": {"id": cat["id"], "name": cat["name"], "group": cat["group"],
                     "icon": cat["icon"], "ask": cat["ask"],
                     "caution": cat.get("caution")},
        "severity": {"id": cat["severity"], **sev},
        "authority": {k: auth[k] for k in ("id", "name", "public_name", "dept",
                                           "helpline", "extra_helplines", "email",
                                           "phone", "phone_e164", "escalation", "mock")},
        "nearby": nearby,
        "subject": subject,
        "body": body,
        "whatsapp_text": wa,
        "sms_text": sms,
        "location": location,
        "note": note,
        "answer": answer,
        "reporter": reporter,
        "confidence": confidence,
        "created_at": now.isoformat(),
    }
