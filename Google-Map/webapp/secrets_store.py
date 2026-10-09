"""API keys and SMTP credentials live in Google-Map/.env (gitignored), never in the database.

The API only reports whether a key is set; values are never sent back to the browser.
"""
import os
import threading

from .config import GOOGLE_MAP_DIR

ENV_PATH = os.path.join(GOOGLE_MAP_DIR, ".env")
ALLOWED_KEYS = {
    "SENDER_EMAIL", "APP_PASSWORD", "SENDER_NAME",
    "GOOGLE_PLACES_KEY", "SERPAPI_KEY", "OUTSCRAPER_KEY", "HUNTER_KEY",
}
_lock = threading.Lock()


def _read_file():
    values = {}
    if not os.path.exists(ENV_PATH):
        return values
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def get(key):
    return os.getenv(key) or _read_file().get(key) or ""


def is_set(key):
    return bool(get(key))


def set_value(key, value):
    if key not in ALLOWED_KEYS:
        raise ValueError(f"Unknown secret {key}")
    value = (value or "").strip()
    if "\n" in value or "\r" in value:
        raise ValueError("Secret must be a single line")
    with _lock:
        values = _read_file()
        if value:
            values[key] = value
        else:
            values.pop(key, None)
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")
    os.environ.pop(key, None)


def status():
    return {k: is_set(k) for k in sorted(ALLOWED_KEYS)}
