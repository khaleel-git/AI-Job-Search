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

# Temporary switch: set to True to skip scraping and only upload an existing CSV.
UPLOAD_ONLY_MODE = False

# Basic working student keyword filter only.
SEARCH_KEYWORDS = [
    "working student",
    "werkstudent",
]

LOCATION = "Germany"
JOB_TYPE_FILTER = ""  # Optional LinkedIn filter, e.g. "P" (part-time) or "P,I"
TIME_FILTER = "r86400"
TIME_FILTER_LABEL = "Past 24 Hours"
STRICT_GERMANY_LOCATION = True
WAIT_SECONDS = 15
MAX_PAGES_PER_KEYWORD = 5  # Quality over quantity: 1 page captures most-relevant (fresh) jobs + faster execution
RETENTION_HOURS = 24
SCRAPED_DATE_FORMAT = "%Y-%m-%d %H:%M"
DEBUG_MODE = True
AUTO_HEADLESS_WHEN_NO_DISPLAY = True
ACTION_DELAY_RANGE_SECONDS = (1.2, 3.4)
PAGE_TRANSITION_DELAY_RANGE_SECONDS = (1.8, 4.2)
KEYWORD_COOLDOWN_EVERY = 5
KEYWORD_COOLDOWN_RANGE_SECONDS = (14.0, 24.0)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE_DIR, "Jobs")
UPLOAD_ONLY_CSV_FILENAME = os.path.join(JOBS_DIR, "Live_Werkstudent_Jobs.csv")
UPLOAD_ONLY_NON_RELEVANT_CSV_FILENAME = os.path.join(JOBS_DIR, "Live_Werkstudent_Jobs_Non_Relevant.csv")
OUTPUT_FIELDNAMES = [
    "Scraped Date",
    "Time Filter",
    "Keyword",
    "Job Title",
    "Company",
    "Location",
    "Apply Link",
    "Skills Found",
    "German_Level",
    "Relevance_Score",
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
JOB_DESCRIPTION_SELECTORS = (
    "div.show-more-less-html__markup",
    "div.jobs-description__content",
    "div.jobs-box__html-content",
)


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

TITLE_MATCH_TOKENS = ("werkstudent", "working student")
GERMANY_LOCATION_TOKENS = (
    "germany",
    "deutschland",
)

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


def extract_skills_from_description(job_description):
    """Extract skills found in description as comma-separated string."""
    normalized = (job_description or "").lower()
    skills_map = {
        r"\bpython\b": "Python",
        r"\bsql\b": "SQL",
        r"\bpower\s*bi\b": "Power BI",
        r"\blinux\b": "Linux",
        r"\bmachine\s+learning\b": "Machine Learning",
        r"\bartificial\s+intelligence\b": "AI",
        r"\bdata\s+engineering\b": "Data Engineering",
        r"\bdata\s+science\b": "Data Science",
        r"\bdata\s+analytics\b": "Data Analytics",
        r"\bdata\s+analysis\b": "Data Analysis",
        r"\bpandas\b": "Pandas",
        r"\bnumpy\b": "NumPy",
        r"\bexcel\b": "Excel",
        r"\btableau\b": "Tableau",
    }
    found_skills = []
    for pattern, label in skills_map.items():
        if re.search(pattern, normalized):
            found_skills.append(label)
    
    # Check for cloud platforms
    if re.search(r"\baws\b", normalized):
        found_skills.append("AWS")
    if re.search(r"\bazure\b", normalized):
        found_skills.append("Azure")
    if re.search(r"\bgcp\b|\bgoogle\s+cloud\b", normalized):
        found_skills.append("GCP")
    
    # Check for KI / AI patterns
    if re.search(r"künstliche\s+intelligenz|kuenstliche\s+intelligenz", normalized):
        if "AI" not in found_skills:
            found_skills.append("KI")
    elif re.search(r"\bai\b", normalized):
        if "AI" not in found_skills:
            found_skills.append("AI")
    elif re.search(r"\bki\b", normalized):
        if "AI" not in found_skills and "KI" not in found_skills:
            found_skills.append("KI")
    
    return ", ".join(found_skills) if found_skills else ""


def check_german_required(job_description):
    """Classify German language requirement as: required / preferred / not_required."""
    text = (job_description or "").lower()
    
    # Strong indicators of REQUIRED German
    required_patterns = [
        r"\bfließend\s+deutsch\b|\bfliessend\s+deutsch\b",
        r"\bverhandlungssicher\b",
        r"\bsehr\s+gute\s+deutschkenntnisse\b",
        r"\bdeutsch\s+in\s+wort\s+und\s+schrift\b",
        r"\bgerman\s+(required|mandatory)\b",
        r"\bdeutsch\s+(required|mandatory|erforderlich)\b",
        r"\b(b2|c1|c2)\b.*(deutsch|german)",
        r"(deutsch|german).*(b2|c1|c2)",
    ]
    
    # Soft indicators of PREFERRED German (contextual with negative lookahead)
    preferred_patterns = [
        r"\bgute\s+deutschkenntnisse\b",
        r"\bdeutschkenntnisse\b(?=.*(?:von\s+vorteil|wünschenswert|nice\s+to\s+have|plus))",
        r"\bgerman\s+(nice\s+to\s+have|plus|preferred|advantage)\b",
        r"\b(a1|a2|b1)\b.*(deutsch|german)",
    ]
    
    # Check for REQUIRED
    for pattern in required_patterns:
        if re.search(pattern, text):
            return "required"
    
    # Check for PREFERRED
    for pattern in preferred_patterns:
        if re.search(pattern, text):
            return "preferred"
    
    # Check for explicitly English-only
    if re.search(r"\benglish\s+(required|mandatory|only)", text) and not re.search(r"deutsch|german", text):
        return "not_required"
    
    return "not_required"


def classify_relevance_from_description(job_description):
    """
    Classify relevance using OR logic: if ANY target skill is found, mark as relevant.
    Excludes jobs matching certain patterns (data entry, admin, sales, HR, customer service).
    Returns (relevance_str, skill_count_float): relevant/non_relevant and count of skills found.
    """
    text = (job_description or "").lower()
    
    # All target skills - if ANY of these are found, job is relevant (OR logic)
    target_skills = [
        r"\bpython\b",
        r"\bsql\b",
        r"\bpower\s*bi\b",
        r"\blinux\b",
        r"\bmachine\s+learning\b",
        r"\bartificial\s+intelligence\b",
        r"\bdata\s+engineering\b",
        r"\bdata\s+science\b",
        r"\bdata\s+analytics?\b",
        r"\bdata\s+analysis\b",
        r"\bpandas\b",
        r"\bnumpy\b",
        r"\bexcel\b",
        r"\btableau\b",
        r"\baws\b",
        r"\bazure\b",
        r"\bgcp\b",
        r"\bgoogle\s+cloud\b",
        r"künstliche\s+intelligenz|kuenstliche\s+intelligenz",
        r"\bai\b",
        r"\bki\b",
    ]
    
    # EXCLUDE patterns: jobs that are NOT relevant even if skills are mentioned
    # (data entry, admin, sales, HR, reception, customer service)
    exclude_patterns = [
        r"\bdata\s+entry\b",
        r"\badministrative\b",
        r"\badmin\b",
        r"\bsales\b",
        r"\bhr\b",
        r"\bhuman\s+resources\b",
        r"\breception\b",
        r"\bcustomer\s+service\b",
    ]
    
    # If any exclude pattern matches, job is non-relevant regardless of skills
    for pattern in exclude_patterns:
        if re.search(pattern, text):
            debug_log(f"Excluded job due to pattern match: {pattern}")
            return "non_relevant", 0.0
    
    # Check if ANY target skill is found (OR logic)
    skill_count = 0
    for pattern in target_skills:
        if re.search(pattern, text):
            skill_count += 1
    
    # If any skill found, mark as relevant
    if skill_count > 0:
        return "relevant", float(skill_count)
    else:
        return "non_relevant", 0.0


def extract_job_description(driver, wait, card):
    try:
        clickable = None
        links = card.find_elements(By.CSS_SELECTOR, LINK_SELECTOR)
        if links:
            clickable = links[0]
        else:
            clickable = card

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable)
        human_pause((0.15, 0.4), "before opening job details")
        driver.execute_script("arguments[0].click();", clickable)
    except WebDriverException:
        return ""

    human_pause((0.35, 0.8), "waiting for description panel")

    for selector in JOB_DESCRIPTION_SELECTORS:
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            descriptions = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in descriptions:
                text = (element.text or "").strip()
                if text:
                    return text
        except TimeoutException:
            continue
        except WebDriverException:
            continue

    return ""


def is_germany_location(location_text):
    normalized = normalize_geo_text(location_text)
    if not normalized:
        return False

    return any(token in normalized for token in GERMANY_LOCATION_TOKENS)


def build_search_url(keyword):
    params = {
        "keywords": keyword,
        "location": LOCATION,
        "f_TPR": TIME_FILTER,
    }
    if (JOB_TYPE_FILTER or "").strip():
        params["f_JT"] = JOB_TYPE_FILTER

    query = urlencode(params)
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

                apply_link = (row.get("Apply Link", "") or "").strip()
                if not apply_link:
                    continue

                if apply_link in seen_links:
                    continue

                existing_jobs.append(row)

                seen_links.add(apply_link)

    return existing_jobs, seen_links, expired_count


def save_jobs_csv(output_filename, jobs):
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, 'w', encoding='utf-8-sig', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows([{key: job.get(key, "") for key in OUTPUT_FIELDNAMES} for job in jobs])


def build_run_csv_paths(now_utc):
    """Return canonical and timestamped CSV paths for the current run."""
    os.makedirs(JOBS_DIR, exist_ok=True)
    day_folder = now_utc.strftime("%d-%m-%Y")
    run_time = now_utc.strftime("%H:%M")
    day_dir = os.path.join(JOBS_DIR, day_folder)
    os.makedirs(day_dir, exist_ok=True)

    canonical_relevant = os.path.join(JOBS_DIR, "Live_Werkstudent_Jobs.csv")
    canonical_non_relevant = os.path.join(JOBS_DIR, "Live_Werkstudent_Jobs_Non_Relevant.csv")
    run_relevant = os.path.join(day_dir, f"{run_time}_relevant.csv")
    run_non_relevant = os.path.join(day_dir, f"{run_time}_non_relevant.csv")

    return {
        "day_dir": day_dir,
        "run_time": run_time,
        "canonical_relevant": canonical_relevant,
        "canonical_non_relevant": canonical_non_relevant,
        "run_relevant": run_relevant,
        "run_non_relevant": run_non_relevant,
    }


def resolve_upload_only_csv_paths(now_utc):
    """Prefer latest timestamped CSVs from today's folder; fallback to canonical files."""
    run_paths = build_run_csv_paths(now_utc)
    day_dir = run_paths["day_dir"]

    latest_relevant = ""
    latest_non_relevant = ""
    latest_relevant_time = ""
    latest_non_relevant_time = ""

    if os.path.isdir(day_dir):
        for name in os.listdir(day_dir):
            full_path = os.path.join(day_dir, name)
            if not os.path.isfile(full_path):
                continue

            relevant_match = re.match(r"^(\d{2}:\d{2})_relevant\.csv$", name)
            non_relevant_match = re.match(r"^(\d{2}:\d{2})_non_relevant\.csv$", name)

            if relevant_match:
                time_text = relevant_match.group(1)
                if time_text >= latest_relevant_time:
                    latest_relevant_time = time_text
                    latest_relevant = full_path

            if non_relevant_match:
                time_text = non_relevant_match.group(1)
                if time_text >= latest_non_relevant_time:
                    latest_non_relevant_time = time_text
                    latest_non_relevant = full_path

    return {
        "relevant": latest_relevant or run_paths["canonical_relevant"],
        "non_relevant": latest_non_relevant or run_paths["canonical_non_relevant"],
    }


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
            worksheet = workbook.add_worksheet(title=tab_name, rows="10000", cols="10")
            worksheet.append_row(["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Skills Found", "German_Level", "Relevance_Score", "Relevance"])

        header = ["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Skills Found", "German_Level", "Relevance_Score", "Relevance"]
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
                job.get("Skills Found", ""),
                job.get("German_Level", "not_required"),
                job.get("Relevance_Score", 0),
                job.get("Relevance", "non_relevant"),
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
                row.get("Skills Found", ""),
                row.get("German_Level", "not_required"),
                row.get("Relevance_Score", 0),
                row.get("Relevance", "non_relevant"),
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
            worksheet = workbook.add_worksheet(title=tab_name, rows="10000", cols="10")

        header = ["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link", "Skills Found", "German_Level", "Relevance_Score", "Relevance"]
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
    run_paths = build_run_csv_paths(now_utc)
    relevant_google_tab_name = "Werkstudent Jobs (Relevant)"
    non_relevant_google_tab_name = "Werkstudent Jobs (Non Relevant)"
    output_filename = run_paths["canonical_relevant"]
    non_relevant_output_filename = run_paths["canonical_non_relevant"]

    # Backward compatibility: include legacy root-level CSVs if they exist.
    legacy_output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs.csv")
    legacy_non_relevant_output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs_Non_Relevant.csv")

    existing_jobs, seen_links, expired_count = load_existing_jobs([
        output_filename,
        non_relevant_output_filename,
        legacy_output_filename,
        legacy_non_relevant_output_filename,
    ], now_utc)
    fresh_jobs = []
    run_seen_links = set()
    
    driver = None

    try:
        options = webdriver.ChromeOptions()
        profile_path = os.path.join(BASE_DIR, "chrome_linkedin_profile")
        options.add_argument(f"user-data-dir={profile_path}")
        options.add_argument("profile-directory=Default")

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

                        description_text = extract_job_description(driver, wait, card)
                        
                        # Classify relevance using OR logic: any target skill found = relevant
                        relevance, relevance_score = classify_relevance_from_description(description_text)
                        
                        # Extract skills (informational only, not used for relevance)
                        skills_found = extract_skills_from_description(description_text)
                        
                        # Check German requirement level
                        german_level = check_german_required(description_text)

                        fresh_jobs.append({
                            "Scraped Date": run_timestamp_display,
                            "Time Filter": TIME_FILTER_LABEL,
                            "Keyword": keyword,
                            "Job Title": title,
                            "Company": company,
                            "Location": location,
                            "Apply Link": clean_link,
                            "Skills Found": skills_found,
                            "German_Level": german_level,
                            "Relevance_Score": relevance_score,
                            "Relevance": relevance,
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

    final_jobs = []
    for row in (fresh_jobs + existing_jobs):
        item = dict(row)
        if not item.get("Relevance"):
            item["Relevance"] = "non_relevant"
        final_jobs.append(item)

    relevant_jobs = [job for job in final_jobs if job.get("Relevance") == "relevant"]
    non_relevant_jobs = [job for job in final_jobs if job.get("Relevance") == "non_relevant"]

    print(f"💾 Found {len(fresh_jobs)} NEW jobs! Saving locally to {output_filename}...")
    print(f"🗂️ Current day folder: {run_paths['day_dir']}")
    print("🧾 Local history policy: keep all scraped rows (no retention purge).")
    print(f"📌 Total saved jobs: {len(final_jobs)}")
    print(f"✅ Relevant (contains target skill): {len(relevant_jobs)}")
    print(f"📁 Non-relevant (no target skill): {len(non_relevant_jobs)}")
    
    save_jobs_csv(output_filename, relevant_jobs)
    save_jobs_csv(non_relevant_output_filename, non_relevant_jobs)
    save_jobs_csv(run_paths["run_relevant"], relevant_jobs)
    save_jobs_csv(run_paths["run_non_relevant"], non_relevant_jobs)

    if fresh_jobs:
        fresh_relevant = [job for job in fresh_jobs if job.get("Relevance") == "relevant"]
        fresh_non_relevant = [job for job in fresh_jobs if job.get("Relevance") == "non_relevant"]
        upload_to_google_sheets(fresh_relevant, relevant_google_tab_name)
        upload_to_google_sheets(fresh_non_relevant, non_relevant_google_tab_name)
    else:
        print("⚠️ No new jobs found in this run.")

if __name__ == '__main__':
    if UPLOAD_ONLY_MODE:
        upload_only_paths = resolve_upload_only_csv_paths(datetime.now(timezone.utc))
        upload_csv_to_google_sheets(upload_only_paths["relevant"], "Werkstudent Jobs (Relevant)")
        upload_csv_to_google_sheets(upload_only_paths["non_relevant"], "Werkstudent Jobs (Non Relevant)")
    else:
        scrape_linkedin_jobs()