"""Delivery channels: email via Resend, plus handoff links for WhatsApp/SMS/mail.

Design rule: the app must work with no credentials at all. With RESEND_API_KEY
set, the server sends the email itself and the reporter does nothing. Without
it, `email.sent` is False and the reporter still gets working wa.me and mailto:
links, so the report can always reach the authority one way or another.

Nothing here raises. A delivery failure is reported back as data so the UI can
fall back to the handoff links and tell the reporter the truth.
"""
import base64
import os
import urllib.parse

import requests

RESEND_ENDPOINT = "https://api.resend.com/emails"
# Resend's shared sender works with no domain verification, which keeps setup to
# a single API key. Point MAIL_FROM at your own verified domain for production.
DEFAULT_FROM = os.environ.get("MAIL_FROM", "Spot India <onboarding@resend.dev>")
MAX_ATTACH_BYTES = 4 * 1024 * 1024  # Resend caps a message at ~40MB; stay well under


def email_configured():
    return bool(os.environ.get("RESEND_API_KEY"))


def send_email(report, photo_bytes=None, photo_name="incident.jpg", timeout=20):
    """Send the report to its routed authority. Returns a status dict, never raises."""
    key = os.environ.get("RESEND_API_KEY")
    to = report["authority"]["email"]
    if not key:
        return {"sent": False, "channel": "resend", "to": to,
                "reason": "RESEND_API_KEY not set", "configured": False}

    payload = {
        "from": DEFAULT_FROM,
        "to": [to],
        "subject": report["subject"],
        "text": report["body"],
        "headers": {"X-Spot-Tracking-Id": report["tracking_id"]},
    }
    if report.get("reply_to"):
        payload["reply_to"] = report["reply_to"]

    attached = False
    if photo_bytes and len(photo_bytes) <= MAX_ATTACH_BYTES:
        payload["attachments"] = [{
            "filename": photo_name,
            "content": base64.b64encode(photo_bytes).decode("ascii"),
        }]
        attached = True

    try:
        r = requests.post(RESEND_ENDPOINT, json=payload, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"})
        if r.status_code >= 400:
            # Surface Resend's own message: usually an unverified sender domain.
            detail = ""
            try:
                detail = (r.json() or {}).get("message", "")
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            return {"sent": False, "channel": "resend", "to": to, "configured": True,
                    "reason": f"HTTP {r.status_code}: {detail}"}
        return {"sent": True, "channel": "resend", "to": to, "configured": True,
                "id": (r.json() or {}).get("id"), "photo_attached": attached}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "channel": "resend", "to": to, "configured": True,
                "reason": f"{type(e).__name__}: {e}"}


def handoff_links(report):
    """Links the reporter can tap to deliver the report from their own device.

    These always work and need no credentials, so they double as the fallback
    whenever server email is unset or fails.
    """
    auth = report["authority"]
    wa_text = urllib.parse.quote(report["whatsapp_text"], safe="")
    subject = urllib.parse.quote(report["subject"], safe="")
    body = urllib.parse.quote(report["body"], safe="")
    sms_body = urllib.parse.quote(report["sms_text"], safe="")
    return {
        "whatsapp": f"https://wa.me/{auth['phone_e164']}?text={wa_text}",
        "mailto": f"mailto:{auth['email']}?subject={subject}&body={body}",
        "sms": f"sms:+{auth['phone_e164']}?body={sms_body}",
        "tel": f"tel:+{auth['phone_e164']}",
    }
