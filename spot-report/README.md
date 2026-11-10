# Spot India: citizen incident reporting

Point a camera at a civic problem. The photo is classified **on the device**,
mapped to the authority responsible for that kind of problem, and delivered as a
written report with exact location.

Live: https://spot-report-tau.vercel.app

## How the classification works

No paid vision API, no model training, no subscription.

The browser runs **CLIP zero-shot image classification** via
[transformers.js](https://github.com/xenova/transformers.js). CLIP scores the
photo against full sentences rather than object labels, which is what makes
condition reachable:

| approach | can detect | cannot detect |
|---|---|---|
| COCO object detector | `dog`, `person`, `car` | *injured* dog, abuse, pothole, garbage |
| CLIP zero-shot (used here) | "an injured street dog bleeding on the road" | fine-grained counts, exact measurements |

`catalog.py` holds the prompt set: several phrasings per category, because CLIP
is sensitive to wording, plus **control prompts** ("an ordinary empty street
with nothing wrong"). If a control prompt wins, or nothing clears
`MIN_CONFIDENCE`, the app shows the manual picker instead of guessing. Routing a
wrong report to a real authority is worse than asking the reporter.

Measured in a headless browser: model ready in ~20 s cold (cached afterwards),
inference **524 ms**. The weights are ~50 MB and cached by the browser, so later
reports are instant and work offline.

## The flow

1. **Capture**: camera, or upload. Downscaled to 1024 px, JPEG q0.82.
2. **Analyse**: CLIP scores 49 prompts, folded up into 14 categories.
3. **Confirm**: top category with confidence, the authority it routes to, one
   targeted follow-up question, and alternatives the reporter can switch to.
4. **Locate**: GPS fix, reverse geocoded server-side via OpenStreetMap
   Nominatim (free, no key).
5. **Review**: the exact message, shown verbatim before sending. Template-built,
   never LLM-written: an incident report must not contain invented detail.
6. **Deliver**: email to the routed authority, plus WhatsApp / SMS / call links.
7. **Track**: tracking ID like `SPOT-261102-DGMHTV`, dated in IST.

## Categories and routing

14 categories across 5 groups, each routed to one of 12 authorities:

- **Animal**: injured or sick animal, cruelty or abuse, stray hazard
- **Emergency**: road accident, person needing urgent help, fire
- **Infrastructure**: pothole, waterlogging, street light, fallen tree
- **Sanitation**: garbage dumping, open drain or sewage
- **Civic**: encroachment, something else

Every authority currently resolves to the **same mock contact** for testing, so
the whole routing loop can be exercised against one inbox. Set it with the
`MOCK_AUTHORITY_EMAIL` and `MOCK_AUTHORITY_PHONE` environment variables; the
committed defaults are non-functional placeholders.

Swapping in real per-department contacts means editing only the `email`/`phone`
fields in `catalog.py`. No code changes anywhere else.

## Configuration

Everything is optional. With nothing set, the app classifies, composes and hands
off to the reporter's own WhatsApp and mail apps. Each variable switches on one
more capability.

| variable | effect when set |
|---|---|
| `RESEND_API_KEY` | server sends the email itself, photo attached |
| `MAIL_FROM` | sender address; defaults to Resend's shared sender |
| `SUPABASE_URL` | enables persistence, tracking and the public feed |
| `SUPABASE_SERVICE_KEY` | preferred DB key (bypasses RLS, server-side only) |
| `SUPABASE_ANON_KEY` | fallback DB key; works with the policies in `schema.sql` |
| `SUPABASE_BUCKET` | photo bucket name, default `report-photos` |
| `MOCK_AUTHORITY_EMAIL` / `MOCK_AUTHORITY_PHONE` | override the mock contact |
| `MIN_CONFIDENCE` | classification floor, default `0.18` |
| `CLIP_MODEL` | default `Xenova/clip-vit-base-patch32` |

Set them in Vercel under **Settings → Environment Variables**, then redeploy.

### Supabase setup

1. Create a project, then **SQL Editor → New query**, paste `schema.sql`, Run.
   It creates `spot_reports`, a `spot_report_events` timeline with an automatic
   insert trigger, RLS policies, and the public photo bucket.
2. From **Settings → API**, copy the project URL and a key into Vercel as
   `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`.

Note on RLS: `schema.sql` leaves `select` open so the public accountability feed
works. If reports should be private, drop the `spot_reports_select` policy and
read the feed with the service key only.

## Local development

```bash
pip install -r requirements.txt
python app.py        # http://localhost:5001
```

The camera needs a secure context: `localhost` counts, so it works locally.
On a LAN IP, browsers will refuse camera access without HTTPS.

## Deploying

```bash
vercel --prod
```

One gotcha, learned the hard way on the sibling CI project: **the framework
preset must be "Other"** (`framework: null`). If Vercel auto-detects `flask`,
its zero-config routing collides with the catch-all rewrite in `vercel.json`
and every path collapses to `/api/index`, so every route 404s while the app
itself loads fine.

## Layout

```
catalog.py    categories, CLIP prompts, authorities, severity  <- edit to re-route
compose.py    builds the authority message; one source of truth for wording
deliver.py    Resend email + WhatsApp/SMS/mailto handoff links
geo.py        Nominatim reverse geocoding, rate-gated and cached
storage.py    Supabase persistence over PostgREST; optional everywhere
app.py        Flask routes
schema.sql    run once in Supabase
static/       index.html (capture flow), track.html, feed.html, app.js, styles.css
```

Every module degrades rather than failing: geocoding falls back to raw
coordinates, delivery falls back to handoff links, storage is skippable. A
report can always reach the authority by some route.
