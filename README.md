# Spot India

Two apps that go together: one lets citizens report civic incidents from a
photo, the other tracks who else is doing it.

| | What it is | Live |
|---|---|---|
| [`spot-report/`](spot-report/) | **The product.** Point a camera at a civic problem; it is classified on the device, routed to the authority responsible, and delivered with exact location. | https://spot-report-tau.vercel.app |
| [`spot-ci/`](spot-ci/) | **Competitor intelligence.** An owner-facing dashboard tracking rival civic apps: feature gaps, growth modelling, scraped signals. | https://spot-ci.vercel.app |

Each folder has its own README with the detail. Start with
[`spot-report/README.md`](spot-report/README.md).

## The interesting bit

The photo is classified **in the browser**, with zero-shot CLIP via
[transformers.js](https://github.com/xenova/transformers.js). No vision API, no
API key, no model training, no per-request cost.

This matters because conventional object detection cannot do the job. A
COCO-trained detector returns `dog`, `person`, `car`. It cannot tell an
*injured* dog from a healthy one, cannot recognise harassment, and has no class
for potholes or garbage at all. CLIP scores the image against full sentences
instead, so condition and scene become reachable:

```
"an injured street dog bleeding on the road"      0.86
"a large pothole in an asphalt road surface"      0.07
"an ordinary empty street with nothing wrong"     0.04
```

Control prompts like that last one sit alongside the real ones. If a control
wins, or nothing clears the confidence floor, the app shows a manual picker
rather than guessing. Routing a wrong report to a real authority is worse than
asking the reporter.

Measured in a headless browser: weights ~50 MB, cached after first load;
inference 524 ms.

## Flow

1. **Capture** a photo, or upload one.
2. **Classify** on-device against 15 categories in 5 groups.
3. **Confirm**, with confidence, the authority it routes to, and one targeted
   follow-up question.
4. **Locate** via GPS, reverse geocoded through OpenStreetMap Nominatim.
5. **Review** the exact message, verbatim, before anything is sent.
6. **Deliver** by email, with WhatsApp, SMS and call links as fallbacks.
7. **Track** by a tracking ID such as `SPOT-261111-HM7PMT`.

## Two contact layers

Deliberately separate, and worth understanding before changing anything:

- **What the reporter is shown**: the real body that handles this incident, and
  its genuine public helpline. Someone standing over an injured person sees
  "Hospital and 108 ambulance", a tap-to-call 108, and the nearest actual
  hospital with its distance.
- **Where the report is delivered**: during testing, a single mock inbox set by
  `MOCK_AUTHORITY_EMAIL` / `MOCK_AUTHORITY_PHONE`. The committed defaults are
  non-functional placeholders.

The UI says plainly which is which, so a real authority is never implied to have
received something it did not.

## Running it

```bash
cd spot-report
pip install -r requirements.txt
python app.py          # http://localhost:5001
```

The camera needs a secure context. `localhost` qualifies; a LAN IP does not, so
browsers will refuse camera access there without HTTPS.

Everything is optional configuration: with no environment variables set, the app
still classifies, composes and hands off to the reporter's own WhatsApp and mail
apps. See [`spot-report/README.md`](spot-report/README.md) for the full table and
the Supabase setup.

## Credentials

No keys are committed, and none should be. Every credential is read from the
environment, and `.gitignore` covers `.env`. If you fork this, set your own.
