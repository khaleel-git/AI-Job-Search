"""Default settings for the web app.

The email block lists are read from ``main.py`` with ``ast`` (never executed),
so the CLI scraper and the web app share one source of truth for the defaults.
"""
import ast
import copy
import os

GOOGLE_MAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("MAPLEADS_DATA_DIR", os.path.join(GOOGLE_MAP_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "mapleads.sqlite3")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")

FILTER_LIST_NAMES = {
    "patterns": "EMAIL_BLOCK_PATTERNS",
    "domains": "EMAIL_BLOCK_DOMAINS",
    "domain_suffixes": "EMAIL_BLOCK_DOMAIN_SUFFIXES",
    "domain_extensions": "EMAIL_BLOCK_DOMAIN_EXTENSIONS",
    "localparts": "EMAIL_BLOCK_LOCALPARTS",
    "localpart_prefixes": "EMAIL_BLOCK_LOCALPART_PREFIXES",
    "localpart_contains": "EMAIL_BLOCK_LOCALPART_CONTAINS",
}


def _filter_lists_from_main():
    path = os.path.join(GOOGLE_MAP_DIR, "main.py")
    wanted = {v: k for k, v in FILTER_LIST_NAMES.items()}
    lists = {k: [] for k in FILTER_LIST_NAMES}
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return lists
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            key = wanted.get(node.targets[0].id)
            if key:
                lists[key] = sorted(ast.literal_eval(node.value))
    return lists


DEFAULT_CONFIG = {
    "search": {
        "city": "Berlin",
        "country_code": "de",
        "keywords": ["software companies", "tech startups", "IT companies"],
        "locations": ["Mitte", "Kreuzberg", "Friedrichshain", "Prenzlauer Berg",
                      "Neukölln", "Charlottenburg", "Schöneberg"],
        "exclude_names": ["Recruiting", "Personalvermittlung"],
        "language": "de",
        "zoom": 14,
        "min_rating": 0.0,
        "min_reviews": 0,
        "max_results_per_query": 60,
        "skip_sponsored": True,
        "require_website": True,
        "skip_tracked_websites": True,
        "skip_closed": True,
    },
    "crawl": {
        "enabled": True,
        "max_relevant_pages": 8,
        "timeout": 20,
        "ssl_fallback": True,
        "same_domain_only": True,
        "decode_obfuscation": True,
        "stop_after_first_hit": False,
        "keywords": ["contact", "kontakt", "about", "über", "impressum", "job", "career",
                     "karriere", "stellenangebot", "jobs", "stellen", "work with us",
                     "join us", "team", "contact us", "kontaktieren sie uns", "reach out"],
        "never_visit": ["datenschutz", "privacy", "agb", "cookie", "shop", "blog", "login"],
        "rotate_user_agents": True,
        "proxies": [],
        "concurrency": 3,
    },
    "browser": {
        "mode": "attach",  # attach | headless | visible
        "chrome_path": os.getenv("CHROME_EXE_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        "debug_port": int(os.getenv("CHROME_DEBUG_PORT", "9222")),
        "profile_dir": os.path.join(GOOGLE_MAP_DIR, "chrome_google_profile"),
        "delay_min": 1.0,
        "delay_max": 3.0,
    },
    "filters": {
        "layers": {**{str(i): True for i in range(1, 11)}, "11": False},
        "lists": _filter_lists_from_main(),
        "priority": ["jobs", "karriere", "career", "hr", "bewerbung", "personal", "hello", "contact", "kontakt", "info"],
    },
    "outreach": {
        "delay_min": 120,
        "delay_max": 240,
        "daily_cap": 60,
        "window_start": "09:00",
        "window_end": "17:30",
        "weekdays_only": True,
        "dry_run": True,
        "one_per_domain": True,
        "verify_hunter": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "sender_name": os.getenv("SENDER_NAME", ""),
    },
    "providers": {
        "selenium_maps": {"enabled": True},
        "places_api": {"enabled": False},
        "serpapi": {"enabled": False},
        "outscraper": {"enabled": False},
        "crawler": {"enabled": True},
        "hunter": {"enabled": False},
        "nominatim": {"enabled": True},
    },
}


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
