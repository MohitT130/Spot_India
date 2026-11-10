# Spot India Competitive Intelligence console

Owner dashboard that tracks competitors, shows how they grew phase by phase, and generates the steps Spot India should take
(and a revenue path) from that evidence.

## Run locally (best for the live demo, real scraping)
    pip install -r requirements.txt
    python app.py            # http://localhost:5000
Press **Refresh live data**. Scrapers run in parallel and stream their status into the panel. Results are saved to `data/history.json`,
so every refresh adds a new dated data point.

Optional Claude-written briefing: `export ANTHROPIC_API_KEY=...` before starting.

## Free hosting (Vercel Hobby)
Import the folder as a Vercel project (framework: Other). `vercel.json` and `api/index.py` are already set up.
On Vercel the server is stateless, so the browser keeps the live scrape results (localStorage) and sends them back with each request.

## How it works
- `seed.py`      researched, sourced facts (9 Oct 2026) with confidence levels
- `scrapers/`    BeautifulSoup scrapers: Play Store, App Store (iTunes JSON), Google News RSS, websites (KPI regex + change detection), GitHub
- `store.py`     merges live scrapes into the seed; seed is never overwritten
- `engine.py`    phase classifier, growth index, pace, revenue scenarios, rule-based recommender (R1 to R9, every step shows its trigger)
- `static/`      dashboard (vanilla JS + Chart.js)

## Tests
    python tests/test_scrapers.py
