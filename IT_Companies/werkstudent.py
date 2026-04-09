import csv
import time
import sys
import os
import re
import random
from datetime import datetime, timezone
from urllib.parse import urlencode
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, WebDriverException

# --- NEW GOOGLE SHEETS OAUTH IMPORTS ---
try:
    import gspread
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    GSHEETS_AVAILABLE = True
except ImportError:
    gspread = None
    Credentials = None
    InstalledAppFlow = None
    Request = None
    GSHEETS_AVAILABLE = False

# Change only this value before running: "data", "devops", or "both"
RUN_MODE = "both"  # Options: "devops", "data", "both"

# Temporary switch: set to True to skip scraping and only upload an existing CSV.
UPLOAD_ONLY_MODE = True

# ⚠️ DEVOPS_SEARCH_KEYWORDS: TESTING STATE
# Currently limited to 1 keyword for initial testing.
# Uncomment additional keywords below as needed to expand search scope.
DEVOPS_SEARCH_KEYWORDS = [
    # --- Werkstudent (German) ---
    "Werkstudent DevOps",
    "Werkstudent DevOps Cloud",
    "Werkstudent Platform Engineer",
    "Werkstudent Platform Engineering",
    "Werkstudent Infrastructure",
    "Werkstudent Cloud",
    "Werkstudent Cloud Engineer",
    "Werkstudent Site Reliability Engineer",
    "Werkstudent SRE",
    "Werkstudent CI/CD",
    "Werkstudent Kubernetes",
    "Werkstudent Terraform",
    "Werkstudent Automation Engineer",
    "Werkstudent Monitoring",
    # --- Werkstudentin (German feminine form) ---
    "Werkstudentin DevOps",
    "Werkstudentin Cloud",
    # --- Working Student (English) ---
    "Working Student DevOps",
    "Working Student Platform Engineer",
    "Working Student Platform Engineering",
    "Working Student Infrastructure",
    "Working Student Cloud",
    "Working Student Cloud Engineer",
    "Working Student Site Reliability Engineer",
    "Working Student SRE",
    "Working Student CI/CD",
    "Working Student Kubernetes",
    "Working Student Terraform",
    "Working Student Automation Engineer",
    "Working Student Monitoring"
]

DATA_SEARCH_KEYWORDS = [
    # --- Werkstudent (German) ---
    "Werkstudent Python AI",
    "Werkstudent Data Engineering",
    "Werkstudent Data Engineer",
    "Werkstudent Data Analyst",
    "Werkstudent Data Science",
    "Werkstudent Analytics",
    "Werkstudent Machine Learning",
    "Werkstudent ML",
    "Werkstudent KI",
    "Werkstudent AI",
    "Werkstudent NLP",
    "Werkstudent MLOps",
    "Werkstudent Business Intelligence",
    "Werkstudent BI",
    "Werkstudent Datenanalyse",
    "Werkstudent Daten",
    # --- Werkstudentin (German feminine form) ---
    "Werkstudentin Data",
    "Werkstudentin Machine Learning",
    # --- Working Student (English) ---
    "Working Student Data Engineer",
    "Working Student Data Engineering",
    "Working Student Data Engineer",
    "Working Student Data Analyst",
    "Working Student Data Science",
    "Working Student Analytics",
    "Working Student Machine Learning",
    "Working Student ML",
    "Working Student KI",
    "Working Student AI",
    "Working Student NLP",
    "Working Student MLOps",
    "Working Student Business Intelligence",
    "Working Student BI"
]

def unique_keywords(keywords):
    """Return de-duplicated keywords preserving insertion order."""
    seen = set()
    ordered = []
    for kw in keywords:
        normalized = kw.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(kw)
    return ordered


normalized_mode = (RUN_MODE or "").strip().lower()
if normalized_mode == "data":
    SEARCH_KEYWORDS = unique_keywords(DATA_SEARCH_KEYWORDS)
elif normalized_mode == "devops":
    SEARCH_KEYWORDS = unique_keywords(DEVOPS_SEARCH_KEYWORDS)
elif normalized_mode == "both":
    SEARCH_KEYWORDS = unique_keywords(DATA_SEARCH_KEYWORDS + DEVOPS_SEARCH_KEYWORDS)
else:
    print(f"⚠️ Unknown RUN_MODE='{RUN_MODE}'. Falling back to 'both'.")
    SEARCH_KEYWORDS = unique_keywords(DATA_SEARCH_KEYWORDS + DEVOPS_SEARCH_KEYWORDS)

LOCATION = "Germany"
JOB_TYPE_FILTER = "P"  # LinkedIn: part-time only
TIME_FILTER = "r86400"
TIME_FILTER_LABEL = "Past 24 Hours"
STRICT_GERMANY_LOCATION = True
WAIT_SECONDS = 15
MAX_PAGES_PER_KEYWORD = 1  # Quality over quantity: 1 page captures most-relevant (fresh) jobs + faster execution
RETENTION_HOURS = 24
SCRAPED_DATE_FORMAT = "%Y-%m-%d %H:%M"
DEBUG_MODE = True
AUTO_HEADLESS_WHEN_NO_DISPLAY = True
ACTION_DELAY_RANGE_SECONDS = (1.2, 3.4)
PAGE_TRANSITION_DELAY_RANGE_SECONDS = (1.8, 4.2)
KEYWORD_COOLDOWN_EVERY = 5
KEYWORD_COOLDOWN_RANGE_SECONDS = (14.0, 24.0)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_ONLY_CSV_FILENAME = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs.csv")
OUTPUT_FIELDNAMES = [
    "Scraped Date",
    "Time Filter",
    "Keyword",
    "Job Title",
    "Company",
    "Location",
    "Apply Link",
    "Relevance",
]

# Google Sheets Configuration
GOOGLE_SHEET_ID = "1EtJXQmaOu2M51KAQ-KbXF_MiWaVOoVx7oE_xRrMG76o"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

JOB_CARD_SELECTOR = "div.base-search-card, li.jobs-search-results__list-item, div.job-card-container"
TITLE_SELECTOR = "h3.base-search-card__title, a.job-card-list__title, a.job-card-container__link strong"
COMPANY_SELECTOR = (
    "h4.base-search-card__subtitle, "
    "span.job-card-container__primary-description, "
    ".job-card-container__company-name, "
    ".artdeco-entity-lockup__subtitle, "
    ".artdeco-entity-lockup__subtitle span[aria-hidden='true'], "
    ".job-card-list__company-name"
)
LOCATION_SELECTOR = "span.job-search-card__location, ul.job-card-container__metadata-wrapper li"
LINK_SELECTOR = "a.base-card__full-link, a.job-card-list__title, a.job-card-container__link"
PAGINATION_CONTAINER_SELECTOR = "div.jobs-search-pagination"


def debug_log(message):
    if DEBUG_MODE:
        print(f"[DEBUG] {message}")


def human_pause(delay_range, reason=""):
    """Sleep with jitter to avoid fully deterministic timing between actions."""
    low, high = delay_range
    if high < low:
        low, high = high, low
    duration = random.uniform(low, high)
    if reason:
        debug_log(f"Pause {duration:.2f}s ({reason})")
    time.sleep(duration)


def should_run_headless():
    """Use headless mode automatically in non-GUI environments (e.g., cron)."""
    if not AUTO_HEADLESS_WHEN_NO_DISPLAY:
        return False
    display = (os.environ.get("DISPLAY") or "").strip()
    return display == ""

TITLE_MATCH_TOKENS = ("werkstudent", "werkstudentin", "working student", "student worker", "intern")
GERMANY_LOCATION_TOKENS = (
    "germany",
    "deutschland",
    "berlin",
    "munich",
    "muenchen",
    "hamburg",
    "frankfurt",
    "cologne",
    "koln",
    "stuttgart",
    "dusseldorf",
    "dortmund",
    "essen",
    "bremen",
    "leipzig",
    "hanover",
    "hannover",
    "nuremberg",
    "nuernberg",
    "karlsruhe",
)

GERMANY_STATE_TOKENS = (
    "baden-wurttemberg",
    "baden wuerttemberg",
    "baden-wuerttemberg",
    "bavaria",
    "bayern",
    "berlin",
    "brandenburg",
    "bremen",
    "hamburg",
    "hesse",
    "hessen",
    "lower saxony",
    "niedersachsen",
    "mecklenburg-western pomerania",
    "mecklenburg vorpommern",
    "north rhine-westphalia",
    "north rhine westphalia",
    "nordrhein-westfalen",
    "nordrhein westfalen",
    "nrw",
    "rhineland-palatinate",
    "rhineland palatinate",
    "rheinland-pfalz",
    "rheinland pfalz",
    "saarland",
    "saxony",
    "sachsen",
    "saxony-anhalt",
    "saxony anhalt",
    "sachsen-anhalt",
    "sachsen anhalt",
    "schleswig-holstein",
    "schleswig holstein",
    "thuringia",
    "thueringen",
    "thuringen",
)

IT_RELEVANT_TITLE_PHRASES = (
    "software",
    "softwareentwicklung",
    "software engineer",
    "software engineering",
    "software developer",
    "developer",
    "development",
    "programming",
    "full-stack",
    "fullstack",
    "backend",
    "frontend",
    "web development",
    "qa",
    "quality assurance",
    "testing",
    "automation",
    "it-engineering",
    "it engineering",
    "systemintegration",
    "system integration",
    "system engineer",
    "api-management",
    "api management",
    "cloud",
    "infrastructure",
    "platform",
    "site reliability",
    "sre",
    "devops",
    "security",
    "cyber security",
    "cybersecurity",
    "identity access",
    "data",
    "data engineering",
    "data engineer",
    "data analyst",
    "data science",
    "data platform",
    "data warehouse",
    "business intelligence",
    "analytics engineering",
    "datenanalyse",
    "datenanalyst",
    "dateningenieur",
    "datenplattform",
    "mlops",
    "machine learning",
    "devops",
    "site reliability",
    "sre",
    "platform engineer",
    "platform engineering",
    "cloud engineer",
    "infrastructure",
    "kubernetes",
    "terraform",
    "ci/cd",
    "ci cd",
)

IT_RELEVANT_WORD_TOKENS = (
    "it",
    "ai",
    "ml",
    "qa",
    "api",
    "sre",
)

NON_IT_TITLE_PHRASES = (
    "hr",
    "human resources",
    "people & culture",
    "people service",
    "recruiting",
    "employer branding",
    "active sourcing",
    "sales",
    "telesales",
    "marketing",
    "influencer",
    "campaign",
    "communication",
    "customer success",
    "finance",
    "faktura",
    "procurement",
    "legal",
    "logistik",
    "logistics",
    "asset management",
    "immobilien",
    "facility management",
    "bauingenieur",
    "maschinenbau",
)


def contains_whole_word(text, token):
    return bool(re.search(rf"\b{re.escape(token)}\b", text))


def normalize_geo_text(text):
    normalized = (text or "").strip().lower()
    return (
        normalized
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def first_text(container, selector, default):
    elements = container.find_elements(By.CSS_SELECTOR, selector)
    if not elements:
        return default
    text = elements[0].text.strip()
    return text if text else default


def first_href(container, selector):
    elements = container.find_elements(By.CSS_SELECTOR, selector)
    if not elements:
        return ""
    href = elements[0].get_attribute("href") or ""
    return href.split("?")[0].strip()


def should_keep_title(title):
    normalized = title.lower()
    return any(token in normalized for token in TITLE_MATCH_TOKENS)


def is_it_related(title, keyword=""):
    """Return yes/no relevance for IT jobs (programming/devops/data/ml) based on title and keyword."""
    title_normalized = (title or "").strip().lower()
    keyword_normalized = (keyword or "").strip().lower()

    if any(phrase in title_normalized for phrase in NON_IT_TITLE_PHRASES):
        return "no"

    if any(phrase in title_normalized for phrase in IT_RELEVANT_TITLE_PHRASES):
        return "yes"

    if any(contains_whole_word(title_normalized, token) for token in IT_RELEVANT_WORD_TOKENS):
        return "yes"

    # Fallback for generic titles from IT-focused keywords.
    keyword_signals = (
        "data",
        "devops",
        "mlops",
        "machine learning",
        "software",
        "developer",
        "engineering",
        "programming",
        "cloud",
        "site reliability",
        "platform engineer",
        "cloud engineer",
        "kubernetes",
        "terraform",
    )
    keyword_word_signals = ("it", "ai", "sre")
    keyword_has_it_signal = any(signal in keyword_normalized for signal in keyword_signals) or any(
        contains_whole_word(keyword_normalized, signal) for signal in keyword_word_signals
    )
    if keyword_has_it_signal:
        if any(token in title_normalized for token in ("engineering", "engineer", "developer", "software", "platform", "cloud", "automation", "analytics", "data", "testing")):
            return "yes"
        if any(contains_whole_word(title_normalized, token) for token in IT_RELEVANT_WORD_TOKENS):
            return "yes"

    return "no"


def with_relevance(rows):
    enriched = []
    for row in rows:
        current = dict(row)
        current["Relevance"] = is_it_related(current.get("Job Title", ""), current.get("Keyword", ""))
        enriched.append(current)
    return enriched


def is_germany_location(location_text):
    normalized = normalize_geo_text(location_text)
    if not normalized:
        return False

    if any(token in normalized for token in GERMANY_LOCATION_TOKENS):
        return True

    if any(token in normalized for token in GERMANY_STATE_TOKENS):
        return True

    return False


def build_search_url(keyword):
    query = urlencode(
        {
            "keywords": keyword,
            "location": LOCATION,
            "f_TPR": TIME_FILTER,
            "f_JT": JOB_TYPE_FILTER,
        }
    )
    return f"https://www.linkedin.com/jobs/search/?{query}"


def click_jobs_page_number(driver, page_number):
    """Click an explicit jobs pagination button by number (e.g., 2, 3)."""
    page_text = str(page_number)
    selectors = [
        f"{PAGINATION_CONTAINER_SELECTOR} button.jobs-search-pagination__indicator-button[aria-label='Page {page_text}']",
        f"{PAGINATION_CONTAINER_SELECTOR} li.jobs-search-pagination__indicator button[aria-label='Page {page_text}']",
    ]
    xpaths = [
        f"//div[contains(@class,'jobs-search-pagination')]//button[@aria-label='Page {page_text}']",
    ]

    for selector in selectors:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            human_pause((0.18, 0.55), "before clicking page button")
            driver.execute_script("arguments[0].click();", btn)
            debug_log(f"Clicked page {page_number} using selector: {selector}")
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue

    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            human_pause((0.18, 0.55), "before clicking page button (xpath)")
            driver.execute_script("arguments[0].click();", btn)
            debug_log(f"Clicked page {page_number} using xpath: {xpath}")
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue

    debug_log(f"Failed to click page {page_number}")
    return False


def click_jobs_next_page(driver):
    """Click pagination Next button."""
    selectors = [
        f"{PAGINATION_CONTAINER_SELECTOR} button.jobs-search-pagination__button--next",
        f"{PAGINATION_CONTAINER_SELECTOR} button[aria-label='View next page']",
    ]
    xpaths = [
        "//div[contains(@class,'jobs-search-pagination')]//button[contains(@class,'jobs-search-pagination__button--next')]",
        "//button[@aria-label='View next page']",
    ]

    for selector in selectors:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            if (btn.get_attribute("disabled") or "").strip().lower() in ("true", "disabled"):
                debug_log("Next button is disabled")
                return False
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            human_pause((0.18, 0.55), "before clicking next page")
            driver.execute_script("arguments[0].click();", btn)
            debug_log(f"Clicked next using selector: {selector}")
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue

    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            if (btn.get_attribute("disabled") or "").strip().lower() in ("true", "disabled"):
                debug_log("Next button is disabled")
                return False
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            human_pause((0.18, 0.55), "before clicking next page (xpath)")
            driver.execute_script("arguments[0].click();", btn)
            debug_log(f"Clicked next using xpath: {xpath}")
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue
    debug_log("Failed to click next page button")
    return False


def get_current_jobs_page(driver):
    selectors = [
        f"{PAGINATION_CONTAINER_SELECTOR} button.jobs-search-pagination__indicator-button--active",
        f"{PAGINATION_CONTAINER_SELECTOR} button[aria-current='page']",
    ]
    for selector in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            label = (el.get_attribute("aria-label") or "").strip().lower()
            match = re.search(r"page\s+(\d+)", label)
            if match:
                return int(match.group(1))
            text = (el.text or "").strip()
            if text.isdigit():
                return int(text)
        except (NoSuchElementException, WebDriverException):
            continue

    # Fallback: parse "Page X of Y" state text.
    try:
        state = driver.find_element(By.CSS_SELECTOR, f"{PAGINATION_CONTAINER_SELECTOR} p.jobs-search-pagination__page-state")
        text = (state.text or "").strip().lower()
        match = re.search(r"page\s+(\d+)\s+of\s+(\d+)", text)
        if match:
            return int(match.group(1))
    except (NoSuchElementException, WebDriverException):
        pass

    return None


def get_max_jobs_pages(driver):
    try:
        state = driver.find_element(By.CSS_SELECTOR, f"{PAGINATION_CONTAINER_SELECTOR} p.jobs-search-pagination__page-state")
        text = (state.text or "").strip().lower()
        match = re.search(r"page\s+\d+\s+of\s+(\d+)", text)
        if match:
            return int(match.group(1))
    except (NoSuchElementException, WebDriverException):
        pass

    # Fallback: highest numeric page button currently visible.
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, f"{PAGINATION_CONTAINER_SELECTOR} button.jobs-search-pagination__indicator-button")
        nums = []
        for btn in buttons:
            label = (btn.get_attribute("aria-label") or "").strip().lower()
            m = re.search(r"page\s+(\d+)", label)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            return max(nums)
    except WebDriverException:
        pass

    return 1


def ensure_pagination_loaded(driver):
    """LinkedIn pagination often appears only after list pane is scrolled down."""
    for _ in range(4):
        scrolled = False
        for container_selector in (
            ".scaffold-layout__list",
            ".jobs-search-results-list",
            ".jobs-search-results-list__list-container",
        ):
            try:
                container = driver.find_element(By.CSS_SELECTOR, container_selector)
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
                scrolled = True
                break
            except (NoSuchElementException, WebDriverException):
                continue

        if not scrolled:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        try:
            WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f"{PAGINATION_CONTAINER_SELECTOR} p.jobs-search-pagination__page-state"))
            )
            return True
        except TimeoutException:
            human_pause((0.45, 1.1), "waiting for pagination render")

    return False


def get_results_summary_text(driver):
    selectors = [
        ".jobs-search-results-list__title-heading small span",
        "#results-list__title",
    ]
    for selector in selectors:
        try:
            text = (driver.find_element(By.CSS_SELECTOR, selector).text or "").strip()
            if text:
                return text
        except (NoSuchElementException, WebDriverException):
            continue
    return ""


def move_to_jobs_page(driver, page_number):
    """Move to target page using page number first, then Next fallback until reached."""
    if page_number <= 1:
        return True

    if click_jobs_page_number(driver, page_number):
        try:
            WebDriverWait(driver, 6).until(lambda d: get_current_jobs_page(d) == page_number)
            debug_log(f"Reached page {page_number} via direct click")
            return True
        except TimeoutException:
            human_pause((1.0, 2.2), "page switch fallback wait")
            if get_current_jobs_page(driver) == page_number:
                debug_log(f"Reached page {page_number} after wait fallback")
                return True

    current = get_current_jobs_page(driver) or 1
    debug_log(f"Direct click failed, using Next fallback from page {current} to {page_number}")
    while current < page_number:
        if not click_jobs_next_page(driver):
            return False
        try:
            WebDriverWait(driver, 6).until(lambda d: (get_current_jobs_page(d) or 0) > current)
        except TimeoutException:
            human_pause((1.0, 2.2), "next-page fallback wait")
        new_current = get_current_jobs_page(driver) or current
        if new_current <= current:
            debug_log(f"Page did not advance (still {new_current})")
            return False
        debug_log(f"Advanced from page {current} to {new_current}")
        current = new_current
    return current == page_number


def load_all_jobs_for_keyword(driver, wait):
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
    except TimeoutException:
        return []

    print("   Scrolling to load more jobs...")
    last_count = len(driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR))
    stagnant_scrolls = 0

    while stagnant_scrolls < 4:
        job_cards = driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)
        current_count = len(job_cards)
        if current_count <= last_count:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0
            last_count = current_count

        scrolled = False
        for container_selector in (
            ".scaffold-layout__list",
            ".jobs-search-results-list",
            ".jobs-search-results-list__list-container",
            "div[aria-label='Jobs search'] .scaffold-layout__list",
        ):
            try:
                scroll_container = driver.find_element(By.CSS_SELECTOR, container_selector)
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scroll_container)
                scrolled = True
                break
            except (NoSuchElementException, WebDriverException):
                continue

        if not scrolled:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        if job_cards:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'end'});", job_cards[-1])
            except WebDriverException:
                pass

        debug_log(f"Scroll loop: cards={current_count}, last={last_count}, stagnant={stagnant_scrolls}")
        human_pause((0.6, 1.4), "lazy list load")

    return driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)


def parse_scraped_date(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, SCRAPED_DATE_FORMAT)
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_within_retention(row, now_utc):
    scraped_dt = parse_scraped_date(row.get("Scraped Date", ""))
    if scraped_dt is None:
        return False
    age_seconds = (now_utc - scraped_dt).total_seconds()
    return age_seconds <= RETENTION_HOURS * 3600


def load_existing_jobs(output_filenames, now_utc):
    existing_jobs = []
    seen_links = set()
    expired_count = 0

    if isinstance(output_filenames, str):
        output_filenames = [output_filenames]

    for output_filename in output_filenames:
        if not os.path.exists(output_filename):
            continue

        with open(output_filename, 'r', encoding='utf-8-sig') as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                if "Time Filter" not in row:
                    row["Time Filter"] = "Unknown"
                if "Relevance" not in row:
                    row["Relevance"] = is_it_related(row.get("Job Title", ""), row.get("Keyword", ""))

                if not is_within_retention(row, now_utc):
                    expired_count += 1
                    continue

                apply_link = (row.get("Apply Link", "") or "").strip()
                if not apply_link:
                    continue

                if apply_link in seen_links:
                    continue

                existing_jobs.append(row)

                seen_links.add(apply_link)

    return existing_jobs, seen_links, expired_count


def save_jobs_csv(output_filename, jobs):
    with open(output_filename, 'w', encoding='utf-8-sig', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows([{key: job.get(key, "") for key in OUTPUT_FIELDNAMES} for job in jobs])


def get_google_sheets_client():
    if not GSHEETS_AVAILABLE:
        print("⚠️ Google Sheets upload skipped. Missing libraries: pip install gspread google-auth-oauthlib")
        return None

    token_path = os.path.join(BASE_DIR, "token.json")
    credentials_path = os.path.join(BASE_DIR, "credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("\n🔔 Google Authentication Required! A browser window should open...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'w', encoding='utf-8') as token:
            token.write(creds.to_json())

    return gspread.authorize(creds)


def build_sheet_row_key(row_values):
    """Build a stable dedupe key for a sheet row (prefer Apply Link when present)."""
    padded = list(row_values[:8]) + [""] * max(0, 8 - len(row_values))
    normalized = [str(cell or "").strip() for cell in padded[:8]]
    apply_link = normalized[6]
    if apply_link:
        return ("link", apply_link)
    return ("row", tuple(normalized))


def get_existing_sheet_keys(worksheet, header):
    values = worksheet.get_all_values()
    if not values:
        return set()

    first_row = [str(cell or "").strip() for cell in values[0][:len(header)]]
    has_header = first_row == header
    data_rows = values[1:] if has_header else values

    keys = set()
    for row in data_rows:
        keys.add(build_sheet_row_key(row))
    return keys


def filter_unique_rows_for_sheet(rows, existing_keys):
    unique_rows = []
    skipped_count = 0
    for row in rows:
        key = build_sheet_row_key(row)
        if key in existing_keys:
            skipped_count += 1
            continue
        unique_rows.append(row)
        existing_keys.add(key)
    return unique_rows, skipped_count

def upload_to_google_sheets(fresh_jobs, tab_name):
    """Handles the connection and uploading of new data to Google Sheets via User OAuth."""
    if not fresh_jobs:
        return

    print("\n☁️ Uploading new jobs to Google Sheets...")
    
    try:
        client = get_google_sheets_client()
        if client is None:
            return
        
        # Open the workbook
        workbook = client.open_by_key(GOOGLE_SHEET_ID)
        
        # Find or Create the single "live" tab for all runs
        try:
            worksheet = workbook.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"   Creating '{tab_name}' tab because it didn't exist...")
            worksheet = workbook.add_worksheet(title=tab_name, rows="10000", cols="9")
            worksheet.append_row(["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Relevance"])

        header = ["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Relevance"]
        if not worksheet.row_values(1):
            worksheet.append_row(header)

        # Convert dictionaries to a flat list of lists for GSpread
        rows_to_append = []
        for job in fresh_jobs:
            rows_to_append.append([
                job["Scraped Date"],
                job["Time Filter"],
                job["Keyword"],
                job["Job Title"],
                job["Company"],
                job["Location"],
                job["Apply Link"],
                job.get("Relevance", "no")
            ])

        existing_keys = get_existing_sheet_keys(worksheet, header)
        unique_rows, skipped_count = filter_unique_rows_for_sheet(rows_to_append, existing_keys)
            
        # Push data to the cloud
        if unique_rows:
            worksheet.append_rows(unique_rows)
        print(f"✅ Successfully added {len(unique_rows)} new jobs to your Google Sheet! Skipped {skipped_count} duplicates.")
        
    except FileNotFoundError:
        print("⚠️ 'credentials.json' not found in the folder.")
        print("   Please download an 'OAuth 2.0 Client ID' JSON file from Google Cloud Console.")
    except Exception as e:
        print(f"⚠️ Google Sheets Upload Failed: {e}")


def upload_csv_to_google_sheets(csv_path, tab_name):
    """Append CSV rows to a worksheet without removing existing contents."""
    if not os.path.exists(csv_path):
        print(f"⚠️ CSV file not found: {csv_path}")
        return

    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            rows.append([
                row.get("Scraped Date", ""),
                row.get("Time Filter", ""),
                row.get("Keyword", ""),
                row.get("Job Title", ""),
                row.get("Company", ""),
                row.get("Location", ""),
                row.get("Apply Link", ""),
                row.get("Relevance", "no"),
            ])

    print(f"\n☁️ Upload-only mode: pushing {len(rows)} CSV rows to Google Sheets...")

    try:
        client = get_google_sheets_client()
        if client is None:
            return

        workbook = client.open_by_key(GOOGLE_SHEET_ID)
        try:
            worksheet = workbook.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"   Creating '{tab_name}' tab because it didn't exist...")
            worksheet = workbook.add_worksheet(title=tab_name, rows="10000", cols="9")

        header = ["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Relevance"]
        # Add header once if the sheet is empty.
        if not worksheet.row_values(1):
            worksheet.append_row(header)

        existing_keys = get_existing_sheet_keys(worksheet, header)
        unique_rows, skipped_count = filter_unique_rows_for_sheet(rows, existing_keys)

        # Append new CSV rows under existing data.
        if unique_rows:
            worksheet.append_rows(unique_rows)

        print(f"✅ Upload-only complete. Appended {len(unique_rows)} rows from CSV to '{tab_name}', skipped {skipped_count} duplicates.")
    except FileNotFoundError:
        print("⚠️ 'credentials.json' not found in the folder.")
        print("   Please download an 'OAuth 2.0 Client ID' JSON file from Google Cloud Console.")
    except Exception as e:
        print(f"⚠️ Google Sheets Upload Failed: {e}")

def scrape_linkedin_jobs():
    print("🚀 Launching Chrome with Persistent Profile...\n")
    now_utc = datetime.now(timezone.utc)
    run_timestamp_display = now_utc.strftime(SCRAPED_DATE_FORMAT)
    run_timestamp_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    google_tab_name = "Werkstudent Jobs (Live)"  # Single live tab; appends data with run timestamps
    output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs.csv")
    non_relevant_output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs_Non_Relevant.csv")

    existing_jobs, seen_links, expired_count = load_existing_jobs([
        output_filename,
        non_relevant_output_filename,
    ], now_utc)
    fresh_jobs = []
    run_seen_links = set()
    
    driver = None

    try:
        options = webdriver.ChromeOptions()
        profile_path = os.path.join(BASE_DIR, "chrome_linkedin_profile")
        options.add_argument(f"user-data-dir={profile_path}")

        # Stability flags for VM/cron environments.
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        if should_run_headless():
            options.add_argument("--headless=new")
            debug_log("No DISPLAY detected. Starting Chrome in headless mode.")

        driver = webdriver.Chrome(options=options)
        driver.maximize_window()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        driver.get("https://www.linkedin.com/login")
        human_pause((2.2, 4.3), "initial login page load")
        #print("\n🛑 ACTION REQUIRED:")
        #print("1. Look at the Chrome window.")
        #print("2. If you are not logged in, please log in manually right now.")
        #print("3. Once you see your LinkedIn feed, come back here.")
        #input("👉 PRESS [ENTER] HERE IN THE TERMINAL TO START SCRAPING...")

        keywords_to_run = SEARCH_KEYWORDS[:]
        random.shuffle(keywords_to_run)

        for i, keyword in enumerate(keywords_to_run):
            if i > 0:
                human_pause(ACTION_DELAY_RANGE_SECONDS, "between keyword searches")

            if i > 0 and i % KEYWORD_COOLDOWN_EVERY == 0:
                human_pause(KEYWORD_COOLDOWN_RANGE_SECONDS, "periodic keyword cooldown")

            print(f"\n🔍 Searching for: {keyword} ({TIME_FILTER_LABEL})...")

            url = build_search_url(keyword)
            driver.get(url)
            human_pause(PAGE_TRANSITION_DELAY_RANGE_SECONDS, "search results page load")

            # Load page 1 cards first (also triggers lazy list/pagination rendering).
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
            except TimeoutException:
                print("   ⚠️ No job cards found on initial page load.")
                continue

            page1_cards = load_all_jobs_for_keyword(driver, wait)
            pagination_ready = ensure_pagination_loaded(driver)
            debug_log(f"Pagination container ready: {pagination_ready}")

            # Determine how many pages are available for this keyword and cap by config.
            detected_pages = get_max_jobs_pages(driver)
            total_pages_to_scan = max(1, min(MAX_PAGES_PER_KEYWORD, detected_pages))
            print(f"   Pagination detected: {detected_pages} pages (scanning up to {total_pages_to_scan}).")
            debug_log(f"Results summary: {get_results_summary_text(driver)}")

            for page_num in range(1, total_pages_to_scan + 1):
                if page_num == 1:
                    job_cards = page1_cards
                else:
                    human_pause((0.7, 1.8), "before pagination move")
                    moved = move_to_jobs_page(driver, page_num)
                    if not moved:
                        print(f"   ℹ️ Could not move to page {page_num}; stopping pagination for this keyword.")
                        break
                    job_cards = load_all_jobs_for_keyword(driver, wait)

                debug_log(f"Now on page state: {get_current_jobs_page(driver)} (target {page_num})")
                print(f"   Found {len(job_cards)} recent jobs for {keyword} on page {page_num}.")

                for idx, card in enumerate(job_cards, start=1):
                    try:
                        title = first_text(card, TITLE_SELECTOR, "Unknown Title")
                        company = first_text(card, COMPANY_SELECTOR, "Unknown Company")
                        location = first_text(card, LOCATION_SELECTOR, "Germany")
                        clean_link = first_href(card, LINK_SELECTOR)

                        if company == "Unknown Company":
                            print(f"   Company not found for title='{title}'")

                        if not clean_link:
                            continue

                        if STRICT_GERMANY_LOCATION and not is_germany_location(location):
                            continue

                        if not should_keep_title(title):
                            continue
                        if clean_link in seen_links or clean_link in run_seen_links:
                            continue

                        fresh_jobs.append({
                            "Scraped Date": run_timestamp_display,
                            "Time Filter": TIME_FILTER_LABEL,
                            "Keyword": keyword,
                            "Job Title": title,
                            "Company": company,
                            "Location": location,
                            "Apply Link": clean_link,
                        })
                        run_seen_links.add(clean_link)
                    except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
                        print(f"   Skipping card {idx} for '{keyword}' due to parse error: {e}")

    except WebDriverException as e:
        print(f"Failed to launch or run Chrome. Error: {e}")
        sys.exit(1)
    finally:
        if driver is not None:
            print("\n✅ Finished scraping. Closing browser...")
            driver.quit()

    final_jobs = fresh_jobs + existing_jobs
    final_jobs_with_relevance = with_relevance(final_jobs)
    relevant_jobs_only = [job for job in final_jobs_with_relevance if job.get("Relevance") == "yes"]
    non_relevant_jobs_only = [job for job in final_jobs_with_relevance if job.get("Relevance") == "no"]

    print(f"💾 Found {len(fresh_jobs)} NEW jobs! Saving locally to {output_filename}...")
    print(f"🧹 Expired rows removed (> {RETENTION_HOURS}h): {expired_count}")
    print(f"🎯 Relevant IT jobs after filtering: {len(relevant_jobs_only)} / {len(final_jobs_with_relevance)}")
    print(f"🗂️ Non-relevant jobs saved separately: {len(non_relevant_jobs_only)}")
    
    save_jobs_csv(output_filename, relevant_jobs_only)

    if relevant_jobs_only:
        # Push only NEW relevant jobs to Google Sheets.
        fresh_jobs_with_relevance = with_relevance(fresh_jobs)
        fresh_relevant_jobs = [job for job in fresh_jobs_with_relevance if job.get("Relevance") == "yes"]
        upload_to_google_sheets(fresh_relevant_jobs, google_tab_name)
    else:
        print("⚠️ No IT-related jobs found in this run.")

    save_jobs_csv(non_relevant_output_filename, non_relevant_jobs_only)

if __name__ == '__main__':
    if UPLOAD_ONLY_MODE:
        upload_csv_to_google_sheets(UPLOAD_ONLY_CSV_FILENAME, "Werkstudent Jobs (Live)")
    else:
        scrape_linkedin_jobs()