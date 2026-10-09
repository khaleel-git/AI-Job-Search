"""Website crawler: homepage + ranked relevant pages, email extraction with de-obfuscation.

Same scoring as ``find_relevant_pages`` / ``fetch_emails`` in main.py, but HTTP-only
(no Chrome per page) and driven by settings.
"""
import os
import random
import re
from urllib.parse import unquote, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from . import filters
from .config import GOOGLE_MAP_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
OBFUSCATED_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+\s*(?:\(at\)|\[at\]|\{at\}|\sat\s)\s*[A-Za-z0-9.-]+\s*(?:\.|\(dot\)|\[dot\]|\{dot\}|\sdot\s)\s*[A-Za-z]{2,}\b",
    re.IGNORECASE,
)
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_user_agents = None


def _ua(rotate):
    global _user_agents
    if not rotate:
        return DEFAULT_UA
    if _user_agents is None:
        try:
            with open(os.path.join(GOOGLE_MAP_DIR, "useragents.txt"), encoding="utf-8", errors="ignore") as f:
                _user_agents = [l.strip() for l in f if l.strip()]
        except OSError:
            _user_agents = []
    return random.choice(_user_agents) if _user_agents else DEFAULT_UA


def _deobfuscate(token):
    value = token.strip().lower()
    for old, new in (("(at)", "@"), ("[at]", "@"), ("{at}", "@"), (" at ", "@"),
                     ("(dot)", "."), ("[dot]", "."), ("{dot}", "."), (" dot ", "."), (" ", "")):
        value = value.replace(old, new)
    return value


def get(url, crawl_cfg):
    headers = {"User-Agent": _ua(crawl_cfg.get("rotate_user_agents", True)),
               "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    proxies = None
    if crawl_cfg.get("proxies"):
        p = random.choice(crawl_cfg["proxies"])
        proxies = {"http": p, "https": p}
    timeout = crawl_cfg.get("timeout", 20)
    try:
        return requests.get(url, headers=headers, timeout=timeout, proxies=proxies)
    except requests.exceptions.SSLError:
        if not crawl_cfg.get("ssl_fallback", True):
            raise
        return requests.get(url, headers=headers, timeout=timeout, proxies=proxies, verify=False)


def extract_emails(html, decode_obfuscation=True):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    found = set(EMAIL_RE.findall(html)) | set(EMAIL_RE.findall(text))
    if decode_obfuscation:
        for token in OBFUSCATED_RE.findall(text):
            found.add(_deobfuscate(token))
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            mail = unquote(href.split(":", 1)[1].split("?", 1)[0]).strip()
            if mail:
                found.add(mail)
    return {e.strip().lower() for e in found if filters.plausible_tld(e.strip().rsplit("@", 1)[-1])}, soup


def rank_relevant_pages(soup, base_url, crawl_cfg):
    keywords = [k.lower() for k in crawl_cfg.get("keywords", [])]
    never = [k.lower() for k in crawl_cfg.get("never_visit", [])]
    base_domain = urlparse(base_url).netloc.lower().removeprefix("www.")
    scored = {}
    for a in soup.find_all("a", href=True):
        href_raw = a["href"]
        href = href_raw.lower()
        text = a.get_text(strip=True).lower()
        if not (any(k in href for k in keywords) or any(k in text for k in keywords)):
            continue
        parsed = urlparse(urljoin(base_url, href_raw))
        if parsed.scheme not in ("http", "https"):
            continue
        if crawl_cfg.get("same_domain_only", True) and parsed.netloc.lower().removeprefix("www.") != base_domain:
            continue
        path = parsed.path.lower()
        if any(n in path for n in never):
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        score = 0
        if any(k in path for k in ("impressum", "kontakt", "contact")):
            score += 100
        if any(k in path for k in ("career", "karriere", "jobs", "job", "stellen")):
            score += 70
        if any(k in path for k in ("about", "ueber", "team")):
            score += 40
        if path.count("/") <= 2:
            score += 15
        scored[clean] = max(score, scored.get(clean, 0))
    base_clean = base_url.rstrip("/")
    ranked = sorted((u for u in scored if u != base_clean),
                    key=lambda u: (-scored[u], len(urlparse(u).path), u))
    return ranked[: int(crawl_cfg.get("max_relevant_pages", 8))]


def crawl_site(website, crawl_cfg, log=lambda level, msg: None, should_stop=lambda: False):
    """Return (emails: dict email -> page path, pages_crawled: list)."""
    emails, pages = {}, []
    try:
        r = get(website, crawl_cfg)
        r.raise_for_status()
    except Exception as e:
        log("warn", f"   homepage failed: {website} ({type(e).__name__})")
        return emails, pages
    found, soup = extract_emails(r.text, crawl_cfg.get("decode_obfuscation", True))
    pages.append("/")
    for e in found:
        emails.setdefault(e, "/")
    targets = rank_relevant_pages(soup, r.url or website, crawl_cfg)
    if targets:
        log("info", "   crawling " + " ".join(urlparse(u).path or "/" for u in targets))
    for url in targets:
        if should_stop():
            break
        if crawl_cfg.get("stop_after_first_hit") and emails:
            break
        try:
            pr = get(url, crawl_cfg)
            if pr.status_code >= 400:
                continue
        except Exception:
            continue
        path = urlparse(url).path or "/"
        pages.append(path)
        page_emails, _ = extract_emails(pr.text, crawl_cfg.get("decode_obfuscation", True))
        for e in page_emails:
            emails.setdefault(e, path)
    return emails, pages
