"""Scrape job runner: one background thread per job, with pause / resume / stop.

Progress is stored per query, so a stopped or interrupted job resumes at the next query.
"""
import json
import random
import threading
import time
from urllib.parse import urlparse

from . import crawler, db, filters
from .providers import PROVIDERS, api_providers, selenium_maps


def build_queries(search):
    keywords = [k.strip() for k in search.get("keywords", []) if k.strip()]
    locations = [l.strip() for l in search.get("locations", []) if l.strip()]
    city = search.get("city", "").strip()
    queries = []
    for kw in keywords:
        if locations:
            for loc in locations:
                queries.append({"q": f"{kw} in {loc} {city}".strip(), "district": loc})
        else:
            queries.append({"q": f"{kw} in {city}".strip(), "district": city})
    return queries


def domain_of(url):
    netloc = urlparse(url if "://" in url else f"http://{url}").netloc.lower()
    return netloc.removeprefix("www.").split(":")[0]


class _Context:
    def __init__(self, runner, search, browser):
        self.runner = runner
        self.search = search
        self.browser = browser
        self.max_results = int(search.get("max_results_per_query", 60))
        self.center = None
        self._driver = None

    def log(self, level, msg):
        self.runner.log(level, msg)

    def should_stop(self):
        return self.runner.stop_event.is_set()

    def wait_if_paused(self):
        while self.runner.paused and not self.should_stop():
            time.sleep(0.5)

    def delay(self):
        return random.uniform(float(self.browser.get("delay_min", 1)), float(self.browser.get("delay_max", 3)))

    def driver(self):
        if self._driver is None:
            self._driver = selenium_maps.create_driver(self.browser, self.log)
        return self._driver

    def close(self):
        # In attach mode the Chrome window belongs to the user; only detach.
        if self._driver is not None and self.browser.get("mode") != "attach":
            try:
                self._driver.quit()
            except Exception:
                pass


class JobRunner(threading.Thread):
    def __init__(self, job_id):
        super().__init__(daemon=True, name=f"job-{job_id}")
        self.job_id = job_id
        self.stop_event = threading.Event()
        self.paused = False

    def log(self, level, msg):
        db.log(self.job_id, level, msg)

    def _bump(self, **counts):
        sets = ", ".join(f"{k} = {k} + ?" for k in counts)
        db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*counts.values(), self.job_id))

    def run(self):
        job = db.row("SELECT * FROM jobs WHERE id = ?", (self.job_id,))
        cfg = json.loads(job["config"])
        queries = json.loads(job["queries"])
        source = job["source"]
        db.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, ?), error=NULL WHERE id=?",
                   (db.now(), self.job_id))
        ctx = _Context(self, cfg["search"], cfg["browser"])
        try:
            search_fn = PROVIDERS[source]
            for i in range(job["query_index"], len(queries)):
                if self.stop_event.is_set():
                    break
                ctx.wait_if_paused()
                q = queries[i]
                self.log("ok", f"▶ Query {i + 1}/{len(queries)}: {q['q']}")
                if source == "selenium_maps" and cfg["providers"].get("nominatim", {}).get("enabled"):
                    try:
                        ctx.center = api_providers.geocode(f"{q['district']}, {cfg['search'].get('city', '')}")
                    except Exception:
                        ctx.center = None
                for listing in search_fn(q["q"], ctx):
                    if self.stop_event.is_set():
                        break
                    self._handle_listing(listing, q, cfg, source)
                if not self.stop_event.is_set():
                    db.execute("UPDATE jobs SET query_index = ? WHERE id = ?", (i + 1, self.job_id))
            if self.stop_event.is_set():
                db.execute("UPDATE jobs SET status='stopped' WHERE id=?", (self.job_id,))
                self.log("error", "■ Stopped — progress saved, resume continues at the next query")
            else:
                db.execute("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (db.now(), self.job_id))
                j = db.row("SELECT emails_kept FROM jobs WHERE id=?", (self.job_id,))
                self.log("ok", f"✔ Job finished · {j['emails_kept']} emails kept")
        except Exception as e:
            db.execute("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                       (f"{type(e).__name__}: {e}", db.now(), self.job_id))
            self.log("error", f"✖ Job failed: {type(e).__name__}: {e}")
        finally:
            ctx.close()
            manager.forget(self.job_id)

    def _handle_listing(self, listing, query, cfg, source):
        s = cfg["search"]
        name = (listing.get("name") or "").strip() or "Unknown"
        self._bump(listings=1)
        if s.get("skip_sponsored", True) and listing.get("sponsored"):
            self.log("warn", f"⚠ Skipped sponsored listing: {name}")
            return
        if s.get("skip_closed", True) and listing.get("closed"):
            self.log("warn", f"⚠ Skipped closed business: {name}")
            return
        excluded = [x for x in s.get("exclude_names", []) if x and x.lower() in name.lower()]
        if excluded:
            self.log("warn", f"⚠ Skipped {name} (name contains '{excluded[0]}')")
            return
        if s.get("min_rating") and (listing.get("rating") or 0) < float(s["min_rating"]):
            self.log("info", f"   {name}: rating {listing.get('rating')} below minimum")
            return
        if s.get("min_reviews") and (listing.get("reviews") or 0) < int(s["min_reviews"]):
            self.log("info", f"   {name}: {listing.get('reviews') or 0} reviews below minimum")
            return
        website = listing.get("website")
        if not website:
            if s.get("require_website", True):
                self.log("warn", f"   {name}: no website — skipped")
                return
        domain = domain_of(website) if website else None
        if domain and s.get("skip_tracked_websites", True) and db.row("SELECT 1 FROM leads WHERE domain=?", (domain,)):
            self.log("info", f"   {domain} already tracked — skipped")
            return

        self.log("info", f"→ {name} · {domain or 'no website'}")
        lead_id = db.execute(
            """INSERT INTO leads (name, domain, website, district, query, address, phone, rating, reviews,
               category, lat, lng, maps_url, source, job_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(domain) DO UPDATE SET
                 name=CASE WHEN leads.source='import' THEN excluded.name ELSE leads.name END,
                 district=COALESCE(excluded.district, leads.district), query=excluded.query,
                 address=COALESCE(excluded.address, leads.address), phone=COALESCE(excluded.phone, leads.phone),
                 rating=COALESCE(excluded.rating, leads.rating), reviews=COALESCE(excluded.reviews, leads.reviews),
                 category=COALESCE(excluded.category, leads.category), lat=COALESCE(excluded.lat, leads.lat),
                 lng=COALESCE(excluded.lng, leads.lng), maps_url=COALESCE(excluded.maps_url, leads.maps_url),
                 source=excluded.source, job_id=excluded.job_id, updated_at=excluded.updated_at""",
            (name, domain, website, query["district"], query["q"], listing.get("address"), listing.get("phone"),
             listing.get("rating"), listing.get("reviews"), listing.get("category"), listing.get("lat"),
             listing.get("lng"), listing.get("maps_url"), source, self.job_id, db.now(), db.now()))
        if domain:
            lead_id = db.row("SELECT id FROM leads WHERE domain=?", (domain,))["id"]
            self._bump(websites=1)
            enrich_lead(lead_id, website, domain, cfg, self.log, self.stop_event.is_set, self._bump)


def enrich_lead(lead_id, website, domain, cfg, log, should_stop, bump=lambda **k: None):
    """Crawl the site (and Hunter if enabled), run every address through the filters, store results."""
    found = {}
    pages = []
    if cfg["crawl"].get("enabled", True) and cfg["providers"].get("crawler", {}).get("enabled", True):
        found, pages = crawler.crawl_site(website, cfg["crawl"], log, should_stop)
    if cfg["providers"].get("hunter", {}).get("enabled"):
        try:
            for e in api_providers.hunter_domain_emails(domain):
                found.setdefault(e.lower(), "hunter.io")
        except Exception as e:
            log("warn", f"   Hunter lookup failed: {e}")
    kept = dropped = 0
    for raw, page in found.items():
        email, layer, reason = filters.check_email(raw, cfg["filters"], domain)
        stored = email or raw
        db.execute(
            """INSERT INTO emails (lead_id, email, kept, layer, reason, found_on, type, created_at)
               VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(lead_id, email) DO UPDATE SET
               kept=excluded.kept, layer=excluded.layer, reason=excluded.reason""",
            (lead_id, stored, 1 if email else 0, layer, reason, page,
             filters.email_type(stored) if "@" in stored else "", db.now()))
        if email:
            kept += 1
            log("ok", f"   ✔ kept {email} ({page})")
        else:
            dropped += 1
            log("warn", f"   ✖ filtered {raw} (layer {layer}: {reason})")
    db.execute("UPDATE leads SET pages_crawled=?, updated_at=? WHERE id=?", (json.dumps(pages), db.now(), lead_id))
    if not found:
        log("info", "   no emails found")
    bump(emails_kept=kept, emails_filtered=dropped)
    return kept, dropped


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._runners = {}

    def create(self, name, source, cfg):
        if source not in PROVIDERS:
            raise ValueError(f"Unknown source {source}")
        queries = build_queries(cfg["search"])
        if not queries:
            raise ValueError("Add at least one keyword")
        return db.execute(
            "INSERT INTO jobs (name, source, status, config, queries, created_at) VALUES (?,?,?,?,?,?)",
            (name, source, "queued", json.dumps(cfg), json.dumps(queries), db.now()))

    def start(self, job_id):
        with self._lock:
            if job_id in self._runners:
                return
            if self._runners:
                # One browser-driven job at a time keeps Maps from rate-limiting us.
                raise RuntimeError("Another job is already running. Stop it first.")
            runner = JobRunner(job_id)
            self._runners[job_id] = runner
            runner.start()

    def pause(self, job_id, paused):
        runner = self._runners.get(job_id)
        if not runner:
            raise KeyError(job_id)
        runner.paused = paused
        db.execute("UPDATE jobs SET status=? WHERE id=?", ("paused" if paused else "running", job_id))
        db.log(job_id, "warn", "Paused by user" if paused else "Resumed")

    def stop(self, job_id):
        runner = self._runners.get(job_id)
        if runner:
            runner.paused = False
            runner.stop_event.set()
        else:
            db.execute("UPDATE jobs SET status='stopped' WHERE id=? AND status IN ('queued','running','paused')", (job_id,))

    def is_live(self, job_id):
        return job_id in self._runners

    def forget(self, job_id):
        with self._lock:
            self._runners.pop(job_id, None)

    def recover(self):
        """Jobs left running by a previous server process can no longer be running."""
        db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('running','paused','queued')")


manager = JobManager()
