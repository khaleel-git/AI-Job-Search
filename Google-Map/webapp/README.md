# MapLeads — web UI for the Google Maps scraper

A local web app that runs the Google Maps scraper from a browser. You can build searches, watch jobs live, review and export leads, tune every filter and send outreach. It adds three paid data sources (Google Places API, SerpAPI and Outscraper) alongside the original Selenium scraper.

## Quick start

```bash
cd Google-Map
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r webapp/requirements.txt
python -m webapp                 # opens http://127.0.0.1:8000
```

Then click **Dashboard → Import tracked_*.txt** to load what the CLI scraper already collected.

## What's in the UI

| Screen | What you can do |
|---|---|
| **Dashboard** | Totals, leads per day, funnel (listings → websites → emails → sent → replied), recent jobs, top districts |
| **Search Builder** | Keywords × locations grid, auto-load a city's districts from OpenStreetMap, zoom, language, min rating/reviews, skip sponsored / no-website / already-tracked / closed, pick the data source, time and cost estimate, save as preset |
| **Live Run** | Live log (server-sent events), progress, counters, per-query coverage grid, pause / resume / stop; stopped or interrupted jobs resume at the next query |
| **Leads** | Search, filter (district, status, email type, job), sort, paginate, bulk actions, CSV/JSON export; detail drawer with every email found, why rejected ones were filtered, pages crawled, notes, tags, re-crawl, exclude + block domain |
| **Outreach** | Templates with `{company} {district} {website} {first_name} {first_name_sp} {sender_name}`, attachments (your CV), live preview per lead, dry run, pacing, daily cap, send window, one-email-per-domain, Hunter verification, SMTP test, campaign + sent log |
| **Email Filters** | The 10 layers of `normalize_email_address()` (default lists are read from `main.py`), each switchable, editable block lists, live and batch tester, re-apply rules to stored emails, email priority order. Optional layer 11 keeps only addresses on the company's own domain |
| **Crawler & Browser** | Pages per site, timeout, SSL fallback, same-domain, de-obfuscation, page keywords, never-visit paths, proxies, UA rotation; Chrome mode (attach to debug port / headless / visible), path, profile, delays |
| **Data Sources / APIs** | Enable sources and save API keys (written to `Google-Map/.env`, never returned to the browser) and test them |
| **Presets** | Saved searches, load or run in one click |

## Data sources

| Source | Key (`Google-Map/.env`) | Notes |
|---|---|---|
| Selenium · Google Maps | — | The original approach; needs Chrome. `attach` mode starts Chrome with a debug port like `main.py` |
| Google Places API (New) | `GOOGLE_PLACES_KEY` | Text Search, 20 per page |
| SerpAPI · Maps | `SERPAPI_KEY` | `engine=google_maps` |
| Outscraper | `OUTSCRAPER_KEY` | `maps/search-v3` |
| Hunter.io | `HUNTER_KEY` | Adds domain contacts; optional verification before sending |
| OpenStreetMap | — | District list (Overpass) and geocoding (Nominatim) |

SMTP uses `SENDER_EMAIL` and `APP_PASSWORD` (same as `email_sender.py`), settable from **Outreach → SMTP account**.

## API

All UI actions go through a JSON API under `/api/v1`. Interactive docs are at `http://127.0.0.1:8000/docs`. Main endpoints:

`POST /jobs` · `GET /jobs/{id}/stream` (SSE) · `POST /jobs/{id}/pause|resume|stop` · `GET /leads` · `GET /leads/export?format=csv|json` · `POST /leads/{id}/recrawl` · `GET|PUT /config` · `POST /filters/test` · `POST /outreach/campaigns` · `PUT /providers/{id}` · `GET /geo/districts?city=`

## Layout

```
webapp/
  app.py            FastAPI routes + static UI
  jobs.py           job runner thread (pause/stop/resume) and lead enrichment
  crawler.py        homepage + ranked relevant pages, email extraction
  filters.py        configurable port of normalize_email_address()
  outreach.py       templates, campaigns, SMTP
  providers/        selenium_maps.py, api_providers.py (Places, SerpAPI, Outscraper, Hunter, OSM)
  db.py, config.py, secrets_store.py
  static/           index.html, app.js, app.css
  tests/            pytest
```

Local data lives in `Google-Map/data/` (SQLite + attachments) and is gitignored.

## Tests

```bash
python -m pytest webapp/tests -q
```

## Notes

- Dry run is **on** by default for campaigns. Turn it off on the Composer tab when you're ready to really send.
- Only one scrape job runs at a time, which keeps Google Maps from rate-limiting.
- Google Maps changes its markup from time to time. If Selenium stops finding websites, update the selectors in `providers/selenium_maps.py`, or use an API source.
