"""Configurable port of ``normalize_email_address`` from main.py.

Returns which layer rejected an address so the UI can explain every drop.
Layers can be switched off individually in settings.
"""
import fnmatch
import re

LAYER_NAMES = {
    1: "Pattern match",
    2: "Exact domain blacklist",
    3: "Domain suffix",
    4: "File-extension domain",
    5: "Exact local part",
    6: "Local-part prefix",
    7: "Local-part contains",
    8: "Placeholder names (test123…)",
    9: "Single-char local part",
    10: "Format validation",
    11: "Own domain only (off by default)",
}
OFF_BY_DEFAULT = {11}
LAYER_LISTS = {1: "patterns", 2: "domains", 3: "domain_suffixes", 4: "domain_extensions",
               5: "localparts", 6: "localpart_prefixes", 7: "localpart_contains"}

_INVISIBLE = (" ", " ", "​", "﻿")
_PLACEHOLDER = re.compile(r"(?:test|fake|dummy|sample|example|demo)[._-]?\d*")


# Two-letter TLDs are all country codes; longer ones must be real generic TLDs.
# This drops text fragments like "year@lums.with" that the plain regex matches.
GENERIC_TLDS = {
    "com", "net", "org", "info", "biz", "io", "ai", "co", "app", "dev", "tech", "digital", "online", "cloud",
    "berlin", "hamburg", "koeln", "bayern", "nrw", "ruhr", "saarland", "wien", "swiss", "eu", "gmbh", "group",
    "company", "solutions", "systems", "software", "agency", "studio", "design", "media", "consulting", "services",
    "network", "global", "world", "email", "team", "work", "jobs", "careers", "edu", "gov", "int", "mil", "pro",
    "name", "mobi", "xyz", "site", "space", "store", "shop", "life", "live", "one", "data", "health", "law",
    "legal", "finance", "capital", "ventures", "energy", "engineering", "expert", "partners", "institute", "academy",
}


def plausible_tld(domain):
    tld = domain.rsplit(".", 1)[-1].lower()
    return tld.isalpha() and (len(tld) == 2 or tld in GENERIC_TLDS)



def check_email(value, filter_cfg, site_domain=None):
    """Return (normalized_email_or_None, layer, reason). layer 0 means kept."""
    layers = filter_cfg.get("layers", {})
    lists = filter_cfg.get("lists", {})

    def on(n):
        return layers.get(str(n), n not in OFF_BY_DEFAULT)

    if not value:
        return None, 10, "empty"
    if value.lower().startswith("http://"):
        value = value[7:]
    if value.lower().startswith("mailto:"):
        value = value[7:]
    for ch in _INVISIBLE:
        value = value.replace(ch, "")
    email = value.strip().lower()

    # Format checks always run: without them the remaining layers can't parse the address.
    if any(ord(ch) > 127 for ch in email) or any(ch.isspace() for ch in email):
        return None, 10, "non-ASCII or whitespace"
    if email.count("@") != 1:
        return None, 10, "not a single @"
    local, domain = email.split("@", 1)
    if not local or not domain or "." not in domain or ".." in domain or domain.endswith("."):
        return None, 10, "invalid domain"
    if "/" in domain or "\\" in domain:
        return None, 10, "path characters in domain"
    if domain.startswith("www."):
        return None, 10, "www. in mail domain (text fragment)"
    if not plausible_tld(domain):
        return None, 10, "not a real TLD (text fragment)"

    if on(9) and len(local) == 1:
        return None, 9, "single-char local part"
    if on(1):
        for p in lists.get("patterns", []):
            if fnmatch.fnmatch(email, p):
                return None, 1, f"pattern {p}"
    if on(2) and domain in set(lists.get("domains", [])):
        return None, 2, f"domain {domain}"
    if on(3):
        for s in lists.get("domain_suffixes", []):
            if domain.endswith(s):
                return None, 3, f"suffix {s}"
    if on(4):
        for s in lists.get("domain_extensions", []):
            if domain.endswith(s):
                return None, 4, f"extension {s}"
    if on(5) and local in set(lists.get("localparts", [])):
        return None, 5, f"local part {local}"
    if on(6):
        for p in lists.get("localpart_prefixes", []):
            if local.startswith(p):
                return None, 6, f"prefix {p}"
    if on(7):
        for t in lists.get("localpart_contains", []):
            if t in local:
                return None, 7, f"contains {t}"
    if on(8) and _PLACEHOLDER.fullmatch(local):
        return None, 8, "placeholder name"
    if on(11) and site_domain and not (domain == site_domain or domain.endswith("." + site_domain)
                                       or site_domain.endswith("." + domain)):
        return None, 11, f"not on {site_domain}"
    return email, 0, "kept"


JOB_WORDS = ("job", "karriere", "career", "hr", "bewerbung", "recruit", "talent", "personal")
GENERIC_WORDS = ("info", "hello", "hallo", "contact", "kontakt", "office", "mail", "team", "sales", "service")


def email_type(email):
    local = email.split("@", 1)[0]
    if any(w in local for w in JOB_WORDS):
        return "jobs/hr"
    if any(local == w or local.startswith(w) for w in GENERIC_WORDS):
        return "generic"
    return "personal"


def priority_rank(email, priority):
    local = email.split("@", 1)[0]
    for i, word in enumerate(priority):
        if word in local:
            return i
    return len(priority) if email_type(email) != "personal" else max(0, len(priority) // 2)


def first_name(email):
    """Best-effort first name from a personal address like anna.schmidt@ → Anna."""
    if email_type(email) != "personal":
        return ""
    token = re.split(r"[._-]", email.split("@", 1)[0])[0]
    if len(token) < 3 or not token.isalpha():
        return ""
    return token.capitalize()
