"""Google Maps via Selenium — the original main.py approach, as a provider.

Selectors (feed ``div[role=feed]``, cards ``a.hfpxzc``, title ``h1.DUwDvf``,
website ``data-item-id=authority``) come from main.py.
"""
import os
import random
import re
import subprocess
import time
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import urlopen

CARD_XPATH = ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/')]"
CONSENT_XPATHS = [
    "//button[contains(., 'Alle akzeptieren')]", "//button[contains(., 'Accept all')]",
    "//button[contains(., 'Zustimmen')]", "//button[@aria-label='Accept all']",
    "//button[@aria-label='Alle akzeptieren']",
]
SPONSORED_TOKENS = ("sponsored", "gesponsert", "promoted", "anzeige")


def create_driver(browser_cfg, log):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    mode = browser_cfg.get("mode", "attach")
    options = Options()
    if mode == "attach":
        port = int(browser_cfg.get("debug_port", 9222))
        address = f"127.0.0.1:{port}"
        if not _debug_endpoint_up(address):
            chrome = browser_cfg.get("chrome_path")
            if not chrome or not os.path.exists(chrome):
                raise RuntimeError("Chrome not found. Set the Chrome path under Crawler & Browser.")
            os.makedirs(browser_cfg["profile_dir"], exist_ok=True)
            log("info", f"Starting Chrome with remote debugging on {address}")
            subprocess.Popen([chrome, f"--remote-debugging-port={port}",
                              f"--user-data-dir={browser_cfg['profile_dir']}",
                              "--no-first-run", "--no-default-browser-check"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                if _debug_endpoint_up(address):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Chrome debug endpoint {address} did not come up.")
        options.add_experimental_option("debuggerAddress", address)
        log("ok", f"Attached to Chrome at {address}")
    else:
        if mode == "headless":
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,1000")
        options.add_argument("--lang=de-DE")
    # Selenium 4.6+ resolves a matching chromedriver by itself (Selenium Manager).
    return webdriver.Chrome(options=options)


def _debug_endpoint_up(address):
    try:
        with urlopen(f"http://{address}/json/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def resolve_google_redirect(url):
    if url and "google." in url and "/url?" in url:
        q = parse_qs(urlparse(url).query)
        target = (q.get("q") or q.get("url") or [None])[0]
        if target:
            return unquote(target)
    return url


def _accept_consent(driver):
    from selenium.webdriver.common.by import By
    for xp in CONSENT_XPATHS:
        buttons = driver.find_elements(By.XPATH, xp)
        if buttons:
            try:
                buttons[0].click()
                time.sleep(1)
                return True
            except Exception:
                continue
    return False


def _text(driver, xpath):
    from selenium.webdriver.common.by import By
    els = driver.find_elements(By.XPATH, xpath)
    return els[0].text.strip() if els else None


def _attr(driver, xpath, attr):
    from selenium.webdriver.common.by import By
    els = driver.find_elements(By.XPATH, xpath)
    return els[0].get_attribute(attr) if els else None


def _place_details(driver):
    name = _text(driver, "//h1[contains(@class,'DUwDvf')]")
    website = _attr(driver, "//a[contains(@data-item-id,'authority') and @href]", "href") \
        or _attr(driver, "//a[contains(@aria-label,'Website') and @href]", "href") \
        or _attr(driver, "//a[contains(@aria-label,'Webseite') and @href]", "href")
    address = _attr(driver, "//button[@data-item-id='address']", "aria-label")
    phone = _attr(driver, "//button[starts-with(@data-item-id,'phone:tel:')]", "data-item-id")
    rating_label = _attr(driver, "//div[contains(@class,'F7nice')]//span[@role='img']", "aria-label") or ""
    reviews_label = _attr(driver, "//div[contains(@class,'F7nice')]//span[contains(@aria-label,'Rezension') or contains(@aria-label,'review')]", "aria-label") or ""
    category = _text(driver, "//button[contains(@jsaction,'category')]")
    closed_text = (_text(driver, "//span[contains(., 'Dauerhaft geschlossen') or contains(., 'Permanently closed')]") or "")
    return {
        "name": name,
        "website": resolve_google_redirect(website).split("?")[0] if website else None,
        "address": address.split(":", 1)[-1].strip() if address else None,
        "phone": phone.replace("phone:tel:", "") if phone else None,
        "rating": _num(rating_label),
        "reviews": int(_num(reviews_label.replace(".", "").replace(",", "")) or 0) if reviews_label else None,
        "category": category,
        "closed": bool(closed_text),
    }


def _num(label):
    m = re.search(r"\d+(?:[.,]\d+)?", label or "")
    return float(m.group(0).replace(",", ".")) if m else None


def search(query, ctx):
    from selenium.webdriver.common.by import By

    driver = ctx.driver()
    zoom = ctx.search.get("zoom", 14)
    url = f"https://www.google.com/maps/search/{quote_plus(query)}/?hl={ctx.search.get('language', 'de')}"
    if ctx.center:
        url = f"https://www.google.com/maps/search/{quote_plus(query)}/@{ctx.center['lat']},{ctx.center['lng']},{zoom}z?hl={ctx.search.get('language', 'de')}"
    driver.get(url)
    time.sleep(2)
    if _accept_consent(driver):
        ctx.log("info", "Privacy dialog accepted")

    seen, yielded, stagnant = set(), 0, 0
    while yielded < ctx.max_results and stagnant < 4 and not ctx.should_stop():
        ctx.wait_if_paused()
        feeds = driver.find_elements(By.XPATH, "//div[@role='feed']")
        if not feeds:
            # A single exact match opens the place panel directly.
            details = _place_details(driver)
            if details["name"]:
                details.update(maps_url=driver.current_url, sponsored=False, lat=None, lng=None)
                yield details
            return
        feed = feeds[0]
        cards = feed.find_elements(By.XPATH, CARD_XPATH)
        fresh = [c for c in cards if c.get_attribute("href") not in seen]
        if not fresh:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
            time.sleep(1.5 + random.random())
            stagnant += 1
            if _text(driver, "//span[contains(., 'Ende der Liste') or contains(., \"You've reached the end\")]"):
                return
            continue
        stagnant = 0
        ctx.log("info", f"Feed loaded {len(cards)} listings")
        for card in fresh:
            if ctx.should_stop() or yielded >= ctx.max_results:
                return
            ctx.wait_if_paused()
            href = card.get_attribute("href")
            seen.add(href)
            label = " ".join(filter(None, [card.get_attribute("aria-label"), card.text])).lower()
            parent_text = ""
            try:
                parent_text = card.find_element(By.XPATH, "./..").text.lower()
            except Exception:
                pass
            sponsored = any(t in label or t in parent_text for t in SPONSORED_TOKENS)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", card)
                card.click()
                time.sleep(ctx.delay())
                details = _place_details(driver)
            except Exception as e:
                ctx.log("warn", f"Could not open listing: {type(e).__name__}")
                continue
            m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", unquote(href or ""))
            details.update(maps_url=href, sponsored=sponsored,
                           lat=float(m.group(1)) if m else None, lng=float(m.group(2)) if m else None)
            if not details["name"]:
                details["name"] = card.get_attribute("aria-label")
            yielded += 1
            yield details
