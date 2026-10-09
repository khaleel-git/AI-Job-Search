"""SQLite storage. One connection per call keeps it safe across worker threads."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, source TEXT, status TEXT,
  config TEXT, queries TEXT, query_index INTEGER DEFAULT 0,
  listings INTEGER DEFAULT 0, websites INTEGER DEFAULT 0, emails_kept INTEGER DEFAULT 0,
  emails_filtered INTEGER DEFAULT 0, error TEXT, created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS job_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, ts TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, domain TEXT UNIQUE, website TEXT,
  district TEXT, query TEXT, address TEXT, phone TEXT, rating REAL, reviews INTEGER,
  category TEXT, lat REAL, lng REAL, maps_url TEXT, source TEXT, job_id INTEGER,
  status TEXT DEFAULT 'new', tags TEXT DEFAULT '[]', notes TEXT DEFAULT '',
  pages_crawled TEXT DEFAULT '[]', excluded INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER, email TEXT, kept INTEGER,
  layer INTEGER, reason TEXT, found_on TEXT, type TEXT, created_at TEXT,
  UNIQUE(lead_id, email));
CREATE TABLE IF NOT EXISTS templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, subject TEXT, body TEXT,
  attachments TEXT DEFAULT '[]', updated_at TEXT);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, template_id INTEGER, status TEXT, dry_run INTEGER,
  total INTEGER, sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, created_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS sent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, lead_id INTEGER, email TEXT,
  template TEXT, result TEXT, error TEXT, dry_run INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS presets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, source TEXT,
  search TEXT, is_default INTEGER DEFAULT 0, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_logs_job ON job_logs(job_id, id);
CREATE INDEX IF NOT EXISTS ix_emails_lead ON emails(lead_id);
"""

_init_lock = threading.Lock()
_initialized_for = None


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path():
    return os.getenv("MAPLEADS_DB", config.DB_PATH)


@contextmanager
def connect():
    conn = sqlite3.connect(_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    global _initialized_for
    with _init_lock:
        path = _path()
        if _initialized_for == path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with connect() as c:
            c.executescript(SCHEMA)
            if not c.execute("SELECT 1 FROM settings").fetchone():
                c.execute("INSERT INTO settings (id, data) VALUES (1, ?)", (json.dumps(config.default_config()),))
            if not c.execute("SELECT 1 FROM templates").fetchone():
                _seed_templates(c)
            if not c.execute("SELECT 1 FROM presets").fetchone():
                _seed_presets(c)
        _initialized_for = path


def _seed_templates(c):
    body = (
        "Guten Tag{first_name_sp},\n\n"
        "I came across {company} and wanted to reach out directly. I work in Data Engineering and AI, "
        "building production data pipelines with Python, SQL and Airflow, and deploying LLM-powered automation.\n\n"
        "If you have anything relevant open or coming up at {company}, I would love to hear about it.\n\n"
        "Best regards,\n{sender_name}"
    )
    c.execute("INSERT INTO templates (name, subject, body, attachments, updated_at) VALUES (?,?,?,?,?)",
              ("Data / AI Engineer – EN", "Data Engineer / AI Engineer – Open to New Roles in Germany",
               body, "[]", now()))
    body_de = (
        "Guten Tag{first_name_sp},\n\n"
        "ich bin auf {company} aufmerksam geworden und möchte mich initiativ bei Ihnen vorstellen. "
        "Ich arbeite im Bereich Data Engineering und KI.\n\n"
        "Falls bei Ihnen eine passende Stelle offen ist oder bald frei wird, freue ich mich über eine Rückmeldung.\n\n"
        "Mit freundlichen Grüßen\n{sender_name}"
    )
    c.execute("INSERT INTO templates (name, subject, body, attachments, updated_at) VALUES (?,?,?,?,?)",
              ("Initiativbewerbung – DE", "Initiativbewerbung – Data / AI Engineer", body_de, "[]", now()))


def _seed_presets(c):
    presets = [
        ("Berlin tech sweep", "software companies, tech startups × Berlin districts", "selenium_maps",
         {"keywords": ["software companies", "tech startups"]}, 1),
        ("AI startups (Places API)", "AI startups, ML companies in Berlin", "places_api",
         {"keywords": ["AI startups", "machine learning companies"]}, 0),
        ("IT consulting Mitte + Kreuzberg", "IT consulting in two districts", "serpapi",
         {"keywords": ["IT consulting"], "locations": ["Mitte", "Kreuzberg"]}, 0),
    ]
    for name, desc, source, search, default in presets:
        c.execute("INSERT INTO presets (name, description, source, search, is_default, created_at) VALUES (?,?,?,?,?,?)",
                  (name, desc, source, json.dumps(search), default, now()))


def get_settings():
    with connect() as c:
        stored = json.loads(c.execute("SELECT data FROM settings WHERE id = 1").fetchone()["data"])
    return config.deep_merge(config.default_config(), stored)


def save_settings(data):
    with connect() as c:
        c.execute("UPDATE settings SET data = ? WHERE id = 1", (json.dumps(data),))


def rows(sql, params=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql, params=()):
    with connect() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql, params=()):
    with connect() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def log(job_id, level, message):
    execute("INSERT INTO job_logs (job_id, ts, level, message) VALUES (?,?,?,?)", (job_id, now(), level, message))
