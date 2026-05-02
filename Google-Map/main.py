import time
import os
import subprocess
import fnmatch
from urllib.request import urlopen
from urllib.parse import urlparse
from urllib.parse import unquote
from urllib.parse import parse_qs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException, TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait as wait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import ActionChains

# For static content scraping
import re, random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.exceptions import SSLError


# Keep a dedicated Selenium profile for Google Maps login/session reuse.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_PROFILE_DIR = os.getenv(
    "GOOGLE_PROFILE_DIR",
    os.path.join(BASE_DIR, "chrome_google_profile"),
)
CHROME_DEBUG_PORT = os.getenv("CHROME_DEBUG_PORT", "9222")
CHROME_DEBUG_ADDRESS = os.getenv("CHROME_DEBUG_ADDRESS", f"127.0.0.1:{CHROME_DEBUG_PORT}")
CHROME_EXE_PATH = os.getenv("CHROME_EXE_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
MAX_RELEVANT_PAGES = int(os.getenv("MAX_RELEVANT_PAGES", "8"))
START_URL = "https://www.google.com/maps/search/software+company+in+Prenzlauer+Berg,+Berlin-Pankow/@52.5357196,13.405509,15z/data=!3m1!4b1?entry=ttu&g_ep=EgoyMDI2MDQwMS4wIKXMDSoASAFQAw%3D%3D"

EMAIL_BLOCK_PATTERNS = {
    "dpo*@*",
    "*+noreply@*",
    "*+no-reply@*",
    "*@personion.*",
    "*@*.invalid",
    "*@*.local",
}

EMAIL_BLOCK_DOMAINS = {
    "email.com",
    "beispiel.ch",
    "example.com",
    "example.net",
    "example.org",
    "example.de",
    "test.com",
    "invalid",
    "localhost",
    "localdomain",
    "mailinator.com",
    "yopmail.com",
    "tempmail.com",
    "10minutemail.com",
    "company.com",
    "doe.com",
}

EMAIL_BLOCK_LOCALPARTS = {
    "noreply",
    "no-reply",
    "do-not-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "hostmaster",
    "abuse",
    "spam",
    "unsubscribe",
    "privacy",
    "gdpr",
    "dpo",
    "sales",
    "billing",
    "invoice",
    "help",
    "helpdesk",
    "customer",
    "hotline",
    "test",
    "testing",
    "example",
    "sample",
    "demo",
    "fake",
    "dummy",
    "null",
    "none",
    "unknown",
    "webmaster",
    # Clearly problematic placeholder names
    "name",
    "and",
    # System / API / technical
    "api",
    "engineer",
    "implementation",
    "support",
    "security",
    # Legal / GDPR
    "dataprotection",
    "datenschutz",
    # Customer / service
    "kundenbetreuung",
}

EMAIL_BLOCK_LOCALPART_PREFIXES = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "mailer-daemon",
    "bounce",
    "bounces",
    "dmarc",
    "dpo",
    "privacy",
    "gdpr",
}

EMAIL_BLOCK_LOCALPART_CONTAINS = {
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
    "mailer-daemon",
    "bounce",
    "unsubscribe",
    "automated",
    "auto-reply",
    "autoresponder",
}

EMAIL_BLOCK_DOMAIN_SUFFIXES = {
    ".invalid",
    ".example",
    ".test",
    ".localhost",
    ".local",
    ".for",
    ".we",
    ".not",
    ".our",
    ".that",
    ".traditional",
    ".together",
}

# File extensions commonly found in domains (indicates corrupted email)
EMAIL_BLOCK_DOMAIN_EXTENSIONS = {
    ".js",
    ".min.js",
    ".css",
    ".json",
    ".html",
    ".htm",
    ".xml",
    ".map",
    ".tar",
    ".gz",
    ".zip",
    ".rar",
    ".7z",
}


def launch_driver_attached_to_existing_chrome():
    debug_endpoint = f"http://{CHROME_DEBUG_ADDRESS}/json/version"

    def _wait_for_debug_endpoint(timeout_seconds=20):
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                with urlopen(debug_endpoint, timeout=1.5) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _attach():
        options = Options()
        options.add_experimental_option("debuggerAddress", CHROME_DEBUG_ADDRESS)
        return webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )

    print(f"Starting NEW Chrome debug instance at: {CHROME_DEBUG_ADDRESS}")
    os.makedirs(GOOGLE_PROFILE_DIR, exist_ok=True)

    if not os.path.exists(CHROME_EXE_PATH):
        raise RuntimeError(
            "Chrome executable was not found. Set CHROME_EXE_PATH to your chrome.exe location."
        )

    subprocess.Popen(
        [
            CHROME_EXE_PATH,
            f"--remote-debugging-port={CHROME_DEBUG_PORT}",
            f"--user-data-dir={GOOGLE_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    endpoint_ready = _wait_for_debug_endpoint(timeout_seconds=20)
    if not endpoint_ready:
        raise RuntimeError(
            f"Chrome debug endpoint did not become ready at {debug_endpoint}. "
            "Close existing Chrome processes for this profile and try again."
        )

    for _ in range(6):
        try:
            return _attach()
        except Exception:
            time.sleep(1)
            continue

    raise RuntimeError(
        "Could not attach to the newly started Chrome debug instance. "
        "Close existing Chrome windows and run again."
    )


# Functions
def random_line(afile):
    lines = afile.readlines()
    return random.choice(lines)

def normalize_email_address(value):
    """
    CENTRAL EMAIL FILTERING FUNCTION
    ================================
    All emails pass through this function before storage to ensure consistent filtering.
    
    Applies 10-layer filtering:
    1. Pattern matching (wildcard patterns like dpo*@*, *@personion.*)
    2. Exact domain blacklist (google.com, example.com, etc.)
    3. Domain suffix matching (.invalid, .local, .test, etc.)
    4. Domain extension matching (file extensions like .js, .css, .html)
    5. Exact local-part matching (noreply, support, test, etc.)
    6. Local-part prefix matching (bounce*, dmarc*, privacy*, etc.)
    7. Local-part substring matching (contains "no-reply", "unsubscribe", etc.)
    8. Placeholder name patterns (test123, fake_user, demo.mail, etc.)
    9. Single-character local-parts (too suspicious: a@, s@, i@, etc.)
    10. Basic format validation (must contain @, valid domain structure)
    
    Returns: normalized email (lowercase) or None if filtered
    """
    if not value:
        return None
    
    # Remove http:// prefix if present (cleanup for accidental inclusions)
    if value.lower().startswith("http://"):
        value = value[7:]
    
    # Remove hidden unicode separators/control chars that can sneak in from HTML text.
    cleaned_value = (
        value.strip()
        .replace("\u2028", "")
        .replace("\u2029", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )
    normalized = cleaned_value.lower()

    # Keep email persistence ASCII-safe to avoid terminal/file encoding crashes on Windows.
    if any(ord(ch) > 127 for ch in normalized):
        return None

    if any(ch.isspace() for ch in normalized):
        return None

    if "@" not in normalized:
        return None

    local_part, domain = normalized.split("@", 1)
    if not local_part or not domain:
        return None

    # Drop malformed addresses early (must have valid domain structure)
    if "." not in domain or ".." in domain or domain.endswith("."):
        return None
    
    # Reject single-character local parts (clearly suspicious: a@, s@, i@, etc.)
    if len(local_part) == 1:
        return None
    
    # Reject domains with file path patterns or slashes (corrupted data)
    if "/" in domain or "\\" in domain:
        return None

    if any(fnmatch.fnmatch(normalized, pattern) for pattern in EMAIL_BLOCK_PATTERNS):
        return None

    if domain in EMAIL_BLOCK_DOMAINS:
        return None

    if any(domain.endswith(suffix) for suffix in EMAIL_BLOCK_DOMAIN_SUFFIXES):
        return None
    
    # Check for file extensions in domain (e.g., sdk@0.1.26-site.compat.min.js)
    if any(domain.endswith(ext) for ext in EMAIL_BLOCK_DOMAIN_EXTENSIONS):
        return None

    if local_part in EMAIL_BLOCK_LOCALPARTS:
        return None

    if any(local_part.startswith(prefix) for prefix in EMAIL_BLOCK_LOCALPART_PREFIXES):
        return None

    if any(token in local_part for token in EMAIL_BLOCK_LOCALPART_CONTAINS):
        return None

    # Reject obvious placeholder names like test123, fake_user, demo.mail, etc.
    if re.fullmatch(r"(?:test|fake|dummy|sample|example|demo)[._-]?\d*", local_part):
        return None

    return normalized

# save_to_file with filtering safeguard
def save_to_file(filename, data_set):
    """Save data to file. For email files, apply filtering to ensure no invalid emails are saved."""
    with open(filename, "w", encoding="utf-8") as f:
        for item in sorted(data_set):
            # Apply extra filtering for email files to ensure safety
            if filename == "tracked_emails.txt":
                filtered_item = normalize_email_address(item)
                if filtered_item:
                    f.write(f"{filtered_item}\n")
            else:
                f.write(f"{item}\n")

# tracked URLs/Emails
def load_tracked_set(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def load_tracked_emails(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return set(
                normalized
                for line in f
                if (normalized := normalize_email_address(line))
            )
    except FileNotFoundError:
        return set()

def is_google_redirect(url):
    return any(x in url for x in ["google.com/aclk", "google.com/url"])

def get_final_url_via_selenium(redirect_url):
    try:
        parsed = urlparse(redirect_url)
        query = parse_qs(parsed.query)
        # Prefer explicit adurl when available to avoid relying on browser redirect behavior.
        adurl = query.get("adurl", [""])[0].strip()
        if adurl:
            return adurl

        # Create a temporary headless Selenium session
        temp_options = Options()
        # temp_options.add_argument("--headless")
        temp_options.add_argument("--no-sandbox")
        temp_options.add_argument("--disable-gpu")
        temp_driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=temp_options)

        # Visit the redirect URL
        temp_driver.get(redirect_url)
        wait(temp_driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")

        # Get the final resolved URL after redirects
        final_url = temp_driver.current_url

        temp_driver.quit()
        return final_url

    except Exception as e:
        print("Error getting final URL:", e)
        return None

def fetch_emails(url):
    try:
        # --- Selenium setup ---
        temp_options = Options()
        # temp_options.add_argument("--headless")
        temp_options.add_argument("--no-sandbox")
        temp_options.add_argument("--disable-gpu")
        temp_driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=temp_options)

        temp_driver.get(url)
        wait(temp_driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")

        page_source = temp_driver.page_source
        page_text = temp_driver.find_element(By.TAG_NAME, "body").text
        temp_driver.quit()

        # --- Extract possible emails from HTML/text/mailto ---
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        obfuscated_pattern = r"\b[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\]|\sat\s)\s*[A-Za-z0-9.-]+\s*(?:\.|\(dot\)|\[dot\]|\sdot\s)\s*[A-Za-z]{2,}\b"

        def normalize_email_candidate(candidate):
            value = candidate.strip().lower()
            replacements = {
                "(at)": "@",
                "[at]": "@",
                " at ": "@",
                "(dot)": ".",
                "[dot]": ".",
                " dot ": ".",
                " ": "",
            }
            for old, new in replacements.items():
                value = value.replace(old, new)
            return value

        raw_emails = set(re.findall(email_pattern, page_source))
        raw_emails.update(re.findall(email_pattern, page_text))

        for token in re.findall(obfuscated_pattern, page_source, flags=re.IGNORECASE):
            raw_emails.add(normalize_email_candidate(token))
        for token in re.findall(obfuscated_pattern, page_text, flags=re.IGNORECASE):
            raw_emails.add(normalize_email_candidate(token))

        soup = BeautifulSoup(page_source, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if href.lower().startswith("mailto:"):
                mail = unquote(href.split("mailto:", 1)[1].split("?", 1)[0]).strip()
                if mail:
                    raw_emails.add(normalize_email_candidate(mail))

        # --- Post-filter unwanted ones ---
        blacklist_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
        blacklist_domains = {"domain.com", "example.com"}
        filtered_emails = []

        for email in raw_emails:
            lower_email = email.lower()

            # Skip image/asset filenames
            if any(lower_email.endswith(ext) for ext in blacklist_extensions):
                continue
            # Skip placeholder domains
            if lower_email.split("@")[-1] in blacklist_domains:
                continue
            # Skip Sentry/system tracking IDs
            if re.match(r"^[0-9a-f]{16,}@sentry", lower_email):
                continue
            filtered_emails.append(email)

        return set(
            normalized
            for email in filtered_emails
            if (normalized := normalize_email_address(email))
        )

    except Exception as e:
        print(f"Error fetching emails from {url}: {e}")
        return set()
    
# find_relevant_pages
def find_relevant_pages(base_url):
    keywords = [
        "contact", "kontakt", "about", "über", "impressum", 
        "job", "career", "karriere", "stellenangebot", "jobs", "stellen",
        "work with us", "join us", "team", "teammitglied", "team member",
        "contact us", "kontaktieren sie uns", "reach out", "reachout"
    ]
    relevant_candidates = {}

    try:
        try:
            with open("useragents.txt", "r") as afile:
                headers = random_line(afile).rstrip()
        except Exception as e:
            print(f"⚠ User-Agent list empty, using default. Error: {e}")
            headers = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"

        print(f"Using User-Agent: {headers}")
        try:
            r = requests.get(base_url, headers={'User-Agent': headers}, timeout=50, verify=True)
        except SSLError:
            print(f"⚠ TLS certificate verification failed for {base_url}; retrying without verification.")
            r = requests.get(base_url, headers={'User-Agent': headers}, timeout=50, verify=False)
        r.raise_for_status()

        base_domain = urlparse(base_url).netloc.lower().removeprefix("www.")
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href_raw = a["href"]
            href = href_raw.lower()
            text = a.get_text(strip=True).lower()

            if any(kw in href for kw in keywords) or any(kw in text for kw in keywords):
                abs_url = urljoin(base_url, href_raw)
                parsed = urlparse(abs_url)

                if parsed.scheme not in {"http", "https"}:
                    continue

                candidate_domain = parsed.netloc.lower().removeprefix("www.")
                if candidate_domain != base_domain:
                    continue

                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                path = parsed.path.lower()

                score = 0
                if any(k in path for k in ["impressum", "kontakt", "contact"]):
                    score += 100
                if any(k in path for k in ["career", "karriere", "jobs", "job", "stellen"]):
                    score += 70
                if any(k in path for k in ["about", "ueber", "team"]):
                    score += 40
                if path.count("/") <= 2:
                    score += 15

                # Keep the best score per URL.
                relevant_candidates[clean_url] = max(score, relevant_candidates.get(clean_url, 0))

    except Exception as e:
        print(f"Error scanning homepage for relevant pages: {e}")

    ranked_urls = sorted(
        relevant_candidates.items(),
        key=lambda item: (-item[1], len(urlparse(item[0]).path), item[0])
    )

    limited = [url for url, _ in ranked_urls[:MAX_RELEVANT_PAGES]]
    if ranked_urls:
        print(f"Limiting relevant page scan to top {len(limited)} pages (MAX_RELEVANT_PAGES={MAX_RELEVANT_PAGES}).")

    return limited


def extract_place_token(url):
    """Extract the stable place token from a Maps listing URL (the !1s... segment)."""
    match = re.search(r"!1s([^!]+)", unquote(url or ""))
    return match.group(1) if match else None


def is_sponsored_listing(listing):
    """Detect sponsored/promoted Google Maps cards so they can be skipped."""
    try:
        parts = [
            listing.text,
            listing.get_attribute("aria-label") or "",
            listing.get_attribute("title") or "",
        ]
        combined = " ".join(parts).lower()
        return any(
            token in combined
            for token in (
                "sponsored",
                "gesponsert",
                "promoted",
                "ad",
                "anzeige",
            )
        )
    except StaleElementReferenceException:
        return False


def accept_privacy_dialog_if_present(target_driver, timeout_seconds=4, source_label="session"):
    """Best-effort consent click for Google/website privacy dialogs."""
    consent_xpaths = [
        "//button[contains(., 'Alle akzeptieren')]",
        "//button[contains(., 'Accept all')]",
        "//button[contains(., 'I agree')]",
        "//button[contains(., 'Agree')]",
        "//button[contains(., 'Zustimmen')]",
        "//button[contains(., 'Akzeptieren')]",
        "//button[@aria-label='Accept all']",
        "//button[@aria-label='Alle akzeptieren']",
    ]

    for xpath in consent_xpaths:
        try:
            button = wait(target_driver, timeout_seconds).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            button.click()
            print(f"✅ Privacy dialog accepted in {source_label}")
            time.sleep(1)
            return True
        except Exception:
            continue

    return False


def get_listing_feed_and_scroll_target(driver, timeout_seconds=10, retries=3):
    """Find the feed that actually contains listings and the real scrollable parent."""
    for attempt in range(retries):
        try:
            wait(driver, timeout_seconds).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='feed']"))
            )
            feeds = driver.find_elements(By.XPATH, "//div[@role='feed']")

            best_feed = None
            best_count = -1
            for feed in feeds:
                try:
                    count = len(feed.find_elements(By.XPATH, ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/') ]"))
                except StaleElementReferenceException:
                    continue
                if count > best_count:
                    best_count = count
                    best_feed = feed

            if best_feed is None:
                raise TimeoutException("No stable feed found")

            scroll_target = driver.execute_script(
                """
                let el = arguments[0];
                while (el) {
                    const style = window.getComputedStyle(el);
                    const overflowY = style.overflowY;
                    const canScroll = (el.scrollHeight - el.clientHeight) > 20;
                    if (canScroll && (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay')) {
                        return el;
                    }
                    el = el.parentElement;
                }
                return arguments[0];
                """,
                best_feed,
            )

            return best_feed, scroll_target, best_count
        except (TimeoutException, StaleElementReferenceException):
            print(f"⚠ Listing feed not stable yet (attempt {attempt + 1}/{retries}); retrying...")
            time.sleep(2 + random.uniform(0.5, 1.5))

    print("⚠ Feed did not stabilize after retries; returning to the search results page.")
    driver.get(START_URL)
    wait(driver, timeout_seconds).until(
        EC.presence_of_element_located((By.XPATH, "//div[@role='feed']"))
    )
    feeds = driver.find_elements(By.XPATH, "//div[@role='feed']")
    fallback_feed = feeds[0]
    return fallback_feed, fallback_feed, len(fallback_feed.find_elements(By.XPATH, ".//a[contains(@class,'hfpxzc')]"))


def try_load_more_listings(driver, previous_count, step_attempts=5):
    """Scroll the true listing panel and wait for card growth."""
    listing_feed, scroll_target, _ = get_listing_feed_and_scroll_target(driver, timeout_seconds=8, retries=2)

    current_count = previous_count

    for step in range(step_attempts):
        try:
            before_scroll = driver.execute_script("return arguments[0].scrollTop", scroll_target)
            driver.execute_script(
                "arguments[0].scrollTop = Math.min(arguments[0].scrollTop + Math.max(arguments[0].clientHeight * 1.2, 900), arguments[0].scrollHeight);",
                scroll_target,
            )
            ActionChains(driver).move_to_element(scroll_target).click().send_keys(Keys.PAGE_DOWN).send_keys(Keys.END).perform()
            after_scroll = driver.execute_script("return arguments[0].scrollTop", scroll_target)
            if after_scroll <= before_scroll + 10:
                print(f"⚠ Scroll may not have moved (before: {before_scroll}, after: {after_scroll}); trying again...")
        except StaleElementReferenceException:
            listing_feed, scroll_target, _ = get_listing_feed_and_scroll_target(driver, timeout_seconds=8, retries=2)
            continue

        max_wait_for_cards = 9 + random.uniform(1, 2)
        start_wait = time.time()
        while time.time() - start_wait < max_wait_for_cards:
            try:
                listing_feed, scroll_target, _ = get_listing_feed_and_scroll_target(driver, timeout_seconds=8, retries=2)
                current_listings = listing_feed.find_elements(By.XPATH, ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/')]")
                current_count = len(current_listings)
                if current_count > previous_count:
                    print(f"✅ New cards detected! Count grew from {previous_count} to {current_count}.")
                    return True, listing_feed, scroll_target, current_count
                time.sleep(1 + random.uniform(0.3, 0.8))
            except (StaleElementReferenceException, TimeoutException):
                time.sleep(0.7)

        print(f"⚠ No new cards after scroll step {step + 1}/{step_attempts} (waited {max_wait_for_cards:.1f}s, saw {current_count} total cards); trying more aggressive scroll...")

    return False, listing_feed, scroll_target, current_count


def scrape_listing_details_via_temp_driver(listing_url):
    """Open a Maps listing in a temporary Chrome session and extract name + website without disturbing the main feed."""
    temp_options = Options()
    temp_options.add_argument("--no-sandbox")
    temp_options.add_argument("--disable-gpu")

    temp_driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=temp_options)
    try:
        temp_driver.get(listing_url)
        wait(temp_driver, 12).until(lambda d: d.execute_script("return document.readyState") == "complete")
        accept_privacy_dialog_if_present(temp_driver, timeout_seconds=4, source_label="temp listing driver")

        try:
            name = wait(temp_driver, 6).until(
                EC.presence_of_element_located((By.XPATH, "//h1[contains(@class,'DUwDvf')]"))
            ).text
        except Exception:
            name = None

        try:
            website_elem = None
            website_selectors = [
                "//a[contains(@aria-label, 'Website')]",
                "//a[contains(@aria-label, 'Webseite')]",
                "//a[contains(@data-item-id, 'authority')]",
            ]
            for selector in website_selectors:
                try:
                    website_elem = temp_driver.find_element(By.XPATH, selector)
                    if website_elem:
                        break
                except Exception:
                    continue

            raw_url = website_elem.get_attribute("href") if website_elem else None
            if not raw_url:
                return name, None

            if is_google_redirect(raw_url):
                url = get_final_url_via_selenium(raw_url)
                website = url.split('?')[0] if url else None
            else:
                website = raw_url.split('?')[0]
        except Exception:
            website = None

        return name, website
    except Exception as e:
        print(f"Error scraping listing details from temp driver for {listing_url}: {e}")
        return None, None
    finally:
        try:
            temp_driver.quit()
        except Exception:
            pass


# selenium Initialize Chrome WebDriver
driver = launch_driver_attached_to_existing_chrome()
driver.get(START_URL)
# Main Logic .......................................
try:
    tracked_emails = load_tracked_emails("tracked_emails.txt")
    tracked_websites = load_tracked_set("tracked_websites.txt")
    processed_listing_hrefs = set()
    last_seen_redirect_url = None
    stagnation_rounds = 0
    max_stagnation_rounds = 3

    # Accept cookies/privacy prompts if present.
    if not accept_privacy_dialog_if_present(driver, timeout_seconds=8, source_label="main maps driver"):
        print("⚠️ No cookie/privacy popup found")

    print("Sponsored content check...")
    # --- Keep refreshing until no sponsored content ---
    while True:
        html = driver.page_source.lower()
        if "gesponsert" in html:
            print(f"⚠ Sponsored content detected — refreshing...")
            time.sleep(2)  # small pause to avoid spam-refresh
            driver.refresh()
            time.sleep(2)
        else:
            print("✅ No sponsored content detected. Continuing...")
            break

    # print(input("Press Enter to continue..."))
    while True:
        try:
            listing_feed, scroll_target, _ = get_listing_feed_and_scroll_target(driver, timeout_seconds=10, retries=3)
            listings = listing_feed.find_elements(By.XPATH, ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/')]")
        except (StaleElementReferenceException, TimeoutException):
            print("⚠ Feed updated while reading listings; retrying...")
            continue

        if not listings:
            break

        new_listings = []
        for listing in listings:
            try:
                href = listing.get_attribute("href")
            except StaleElementReferenceException:
                continue

            if href and href not in processed_listing_hrefs and not is_sponsored_listing(listing):
                new_listings.append((listing, href))

        if listings and not new_listings:
            print("⚠ Only sponsored or already-processed listings are visible in this viewport; loading more...")

        if not new_listings:
            print("⚠ No new listings in current viewport; trying to load more...")

        for i, (listing, href) in enumerate(new_listings):
            previous_name = None
            name = None
            website = None
            try:
                previous_name = driver.find_element(By.XPATH, "//h1[contains(@class,'DUwDvf')]").text.strip()
            except Exception:
                pass

            place_token = extract_place_token(href)
            print(f"\n\nProcessing listing {i+1}/{len(new_listings)}: {href}")

            try:
                ActionChains(driver).move_to_element(listing).pause(random.uniform(0.5, 1.5)).click().perform()
            except StaleElementReferenceException:
                print("⚠ Listing became stale before click; scraping the listing in a separate Chrome instance.")
                name, website = scrape_listing_details_via_temp_driver(href)

            # Some cards ignore ActionChains click; JS click improves reliability.
            try:
                driver.execute_script("arguments[0].click();", listing)
            except Exception:
                pass

            def details_changed(d):
                try:
                    if place_token and place_token in unquote(d.current_url):
                        return True

                    header_text = d.find_element(By.XPATH, "//h1[contains(@class,'DUwDvf')]").text.strip()
                    if not header_text:
                        return False

                    return previous_name is None or header_text != previous_name
                except (StaleElementReferenceException, NoSuchElementException):
                    return False

            try:
                wait(driver, 8).until(details_changed)
            except TimeoutException:
                print("⚠ Listing details did not update after click; scraping the listing in a separate Chrome instance.")
                name, website = scrape_listing_details_via_temp_driver(href)

            # Ensure the page has had a chance to settle before extraction.
            time.sleep(1 + random.uniform(1, 3))  # keep some post-click delay
            processed_listing_hrefs.add(href)

            # Extract restaurant name
            if name is None:
                try:
                    name = wait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//h1[contains(@class,'DUwDvf')]"))
                    ).text
                except:
                    name = None

            # Extract website
            if website is None:
                try:
                    website_elem = None
                    matched_selector_name = None
                    website_selectors = [
                        ("authority", "//a[contains(@data-item-id, 'authority') and @href]"),
                        ("website-en", "//a[contains(@aria-label, 'Website') and @href]"),
                        ("website-de", "//a[contains(@aria-label, 'Webseite') and @href]"),
                    ]

                    for selector_name, selector in website_selectors:
                        candidates = driver.find_elements(By.XPATH, selector)
                        if candidates:
                            website_elem = candidates[0]
                            matched_selector_name = selector_name
                            break

                    raw_url = website_elem.get_attribute("href") if website_elem else None

                    if not raw_url:
                        raise NoSuchElementException("No website URL found on listing panel")

                    print(f"Website selector used: {matched_selector_name or 'none'}")
                    print(f"Website raw URL: {raw_url}")

                    if is_google_redirect(raw_url):
                        print(f"⚠️ Redirect URL detected: {raw_url}")

                        # If Maps keeps returning the same ad redirect across different listings,
                        # scrape the listing directly to avoid reusing stale website links.
                        if raw_url == last_seen_redirect_url:
                            print("⚠ Same redirect URL as previous listing; using listing-level fallback extraction.")
                            _, fallback_website = scrape_listing_details_via_temp_driver(href)
                            website = fallback_website
                        else:
                            url = get_final_url_via_selenium(raw_url)
                            website = url.split('?')[0] if url else None

                        last_seen_redirect_url = raw_url
                        print(f"Resolved final URL: {website}")
                    else:
                        website = raw_url.split('?')[0]
                        last_seen_redirect_url = None

                except Exception as e:
                    print(f"Error extracting website: {e}")
                    website = None

            # Extract domain name only
            if website:
                parsed = urlparse(website)
                domain = parsed.netloc  # Gets the domain part (e.g., "example.com")
                # Remove 'www.' prefix if present
                if domain.startswith('www.'):
                    domain = domain[4:]

                print(f"\n\n")
                print("=" * 40)
                print(f"Extracted domain: {domain}")

                # Check against tracked domains
                if domain in tracked_websites:
                    print(f"⚠️ Skipping {domain} — already processed")
                    continue
                tracked_websites.add(domain)

            print(f"Name: {name or 'Unknown'}")
            print(f"Website: {website}")

            if website:
                # Fetch emails from homepage
                emails = fetch_emails(website)
                if emails:
                    print(f"New emails found on {website}: {emails}")
                    for i, email in enumerate(emails, 1):
                        normalized_email = normalize_email_address(email)
                        if normalized_email:
                            tracked_emails.add(normalized_email)
                            print(f"email {i}: {normalized_email}")
                else: 
                    print(f"⚠️ No emails found on homepage of {website}")

                # Check other relevant pages too
                print(f"Searching for relevant pages on {website}...")        
                relevant_pages = find_relevant_pages(website)
                print(f"Found {len(relevant_pages)} relevant pages.")
                if relevant_pages:
                    for url in relevant_pages:
                        print(f"Checking {url} for emails...")
                        emails = fetch_emails(url)
                        # new_emails = relevant_emails - tracked_emails
                        if emails:
                            print(f"New emails found on {website}: {emails}")
                            for i, email in enumerate(emails, 1):
                                normalized_email = normalize_email_address(email)
                                if normalized_email:
                                    print(f"email {i}: {normalized_email}")
                                    tracked_emails.add(normalized_email)
                            break  # stop after finding emails
                    else:
                        # no break happened → no emails found on any relevant page
                        print("⚠️ No emails found on any relevant page.")
                else:
                    print("⚠️ No relevant pages found.")
                # Return to list
                save_to_file("tracked_emails.txt", tracked_emails)
                save_to_file("tracked_websites.txt", tracked_websites)

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", listing)
            except StaleElementReferenceException:
                print("⚠ Feed became stale during scroll; reloading feed.")
                continue

            time.sleep(1+random.uniform(1, 3))  # random delay for human-like behavior
        # Scroll to load more listings with several incremental attempts.
        try:
            prev_count = len(listings)
            grew, listing_feed, scroll_target, new_count = try_load_more_listings(
                driver,
                previous_count=prev_count,
                step_attempts=5,
            )
        except TimeoutException:
            print("⚠ Feed unavailable while trying to load more; retrying current batch.")
            continue

        if not grew and new_count <= prev_count:
            stagnation_rounds += 1
            print(f"⚠ No additional listings loaded (attempt {stagnation_rounds}/{max_stagnation_rounds}).")
        else:
            stagnation_rounds = 0
            print("\n\n@@@@@@@@@@@@@@@@@ Loading more listings...")

        if stagnation_rounds >= max_stagnation_rounds:
            print("Reached end of results after multiple no-growth scroll attempts.")
            break

except KeyboardInterrupt:
    print("\n🛑 Interrupted by user, exiting...")
finally:
    driver.quit()