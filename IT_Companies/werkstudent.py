import csv
import time
import sys
import os
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

DEVOPS_SEARCH_KEYWORDS = [
    # --- Werkstudent (German) ---
    "Werkstudent DevOps",
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
    "Working Student Monitoring",
]

DATA_SEARCH_KEYWORDS = [
    # --- Werkstudent (German) ---
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
    "Working Student BI",
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
MAX_PAGES_PER_KEYWORD = 3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FIELDNAMES = [
    "Scraped Date",
    "Time Filter",
    "Keyword",
    "Job Title",
    "Company",
    "Location",
    "Job Match",
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
    "it",
    "it-engineering",
    "it engineering",
    "systemintegration",
    "system integration",
    "system engineer",
    "api",
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

    # Fallback for generic titles from IT-focused keywords.
    keyword_signals = (
        "data",
        "devops",
        "mlops",
        "machine learning",
        "ai",
        "software",
        "developer",
        "engineering",
        "programming",
        "cloud",
        "it",
        "site reliability",
        "sre",
        "platform engineer",
        "cloud engineer",
        "kubernetes",
        "terraform",
    )
    if any(signal in keyword_normalized for signal in keyword_signals):
        if any(token in title_normalized for token in ("engineering", "engineer", "developer", "software", "platform", "cloud", "automation", "analytics", "data", "ml", "ai", "it", "qa", "testing")):
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


def extract_job_match_level(driver):
    """Extract LinkedIn Premium job match level: high/medium/low/generating/unknown."""
    try:
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class,'job-details-fit-level-card')] | //h2[contains(., 'Job match is')]")
            )
        )
    except TimeoutException:
        pass

    # 1) Most precise: the highlighted level span inside the Premium fit card header.
    precise_level_paths = [
        "//div[contains(@class,'job-details-fit-level-card')]//h2//span[contains(@class,'tvm__text') and normalize-space()]",
        "//div[contains(@class,'job-details-fit-level-card')]//h2//strong",
        "//h2[contains(normalize-space(.), 'Job match is')]",
    ]

    for xpath in precise_level_paths:
        try:
            text = (driver.find_element(By.XPATH, xpath).text or "").strip().lower()
            if "currently being generated" in text or "check back soon" in text:
                return "generating"
            if "high" in text:
                return "high"
            if "medium" in text:
                return "medium"
            if "low" in text:
                return "low"
        except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
            continue

    # 2) Visual fallback: LinkedIn animation class encodes fit quality.
    class_checks = [
        ("//span[contains(@class,'job-details-fit-level-card__animation-light-good') or contains(@class,'job-details-fit-level-card__animation-good')]", "high"),
        ("//span[contains(@class,'job-details-fit-level-card__animation-light-medium') or contains(@class,'job-details-fit-level-card__animation-medium')]", "medium"),
        ("//span[contains(@class,'job-details-fit-level-card__animation-light-low') or contains(@class,'job-details-fit-level-card__animation-low') or contains(@class,'job-details-fit-level-card__animation-light-poor') or contains(@class,'job-details-fit-level-card__animation-poor')]", "low"),
    ]
    for xpath, level in class_checks:
        try:
            if driver.find_elements(By.XPATH, xpath):
                return level
        except (StaleElementReferenceException, WebDriverException):
            continue

    # Explicit fallback when Premium card says match is not ready yet.
    generating_paths = [
        "//div[contains(@class,'job-details-fit-level-card')]//h2[contains(normalize-space(.), 'currently being generated')]",
        "//div[contains(@class,'job-details-fit-level-card')]//h3[contains(normalize-space(.), 'Check back soon')]",
    ]
    for xpath in generating_paths:
        try:
            if driver.find_elements(By.XPATH, xpath):
                return "generating"
        except (StaleElementReferenceException, WebDriverException):
            continue

    return "unknown"


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
    xpaths = [
        f"//button[.//span[normalize-space()='{page_text}']]",
        f"//li[contains(@class,'artdeco-pagination__indicator')]//button[.//span[normalize-space()='{page_text}']]",
        f"//span[normalize-space()='{page_text}']/ancestor::button[1]",
    ]
    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", btn)
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue
    return False


def click_jobs_next_page(driver):
    """Click pagination Next button."""
    xpaths = [
        "//button[.//span[normalize-space()='Next']]",
        "//span[normalize-space()='Next']/ancestor::button[1]",
    ]
    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", btn)
            return True
        except TimeoutException:
            continue
        except WebDriverException:
            continue
    return False


def move_to_jobs_page(driver, page_number):
    """Move to target page (1..N) using page number first, then Next as fallback."""
    if page_number <= 1:
        return True

    if click_jobs_page_number(driver, page_number):
        time.sleep(2)
        return True

    # Fallback: Next once for page 2 and once more for page 3.
    steps = 1 if page_number == 2 else 2
    for _ in range(steps):
        if not click_jobs_next_page(driver):
            return False
        time.sleep(2)
    return True


def load_all_jobs_for_keyword(driver, wait):
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
    except TimeoutException:
        return []

    print("   Scrolling to load more jobs...")
    last_count = 0
    stagnant_scrolls = 0

    while stagnant_scrolls < 2:
        job_cards = driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)
        current_count = len(job_cards)
        if current_count <= last_count:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0
            last_count = current_count

        try:
            scroll_container = driver.find_element(By.CSS_SELECTOR, ".jobs-search-results-list")
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_container)
        except (NoSuchElementException, WebDriverException):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

    return driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)


def load_existing_jobs(output_filename):
    existing_jobs = []
    seen_links = set()
    seen_fallback_keys = set()

    if not os.path.exists(output_filename):
        return existing_jobs, seen_links, seen_fallback_keys

    with open(output_filename, 'r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            if "Time Filter" not in row:
                row["Time Filter"] = "Unknown"
            if "Job Match" not in row:
                row["Job Match"] = "unknown"
            if "Relevance" not in row:
                row["Relevance"] = is_it_related(row.get("Job Title", ""), row.get("Keyword", ""))
            existing_jobs.append(row)

            apply_link = (row.get("Apply Link", "") or "").strip()
            if apply_link:
                seen_links.add(apply_link)

            fallback_key = (
                row.get("Job Title", "").strip().lower(),
                row.get("Company", "").strip().lower(),
                row.get("Location", "").strip().lower(),
            )
            seen_fallback_keys.add(fallback_key)

    return existing_jobs, seen_links, seen_fallback_keys

def upload_to_google_sheets(fresh_jobs, tab_name):
    """Handles the connection and uploading of new data to Google Sheets via User OAuth."""
    if not fresh_jobs:
        return

    print("\n☁️ Uploading new jobs to Google Sheets...")
    
    if not GSHEETS_AVAILABLE:
        print("⚠️ Missing libraries. Please run: pip install gspread google-auth-oauthlib")
        return
         
    try:
        creds = None
        token_path = os.path.join(BASE_DIR, "token.json")
        credentials_path = os.path.join(BASE_DIR, "credentials.json")
        
        # The file token.json stores the user's access and refresh tokens.
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
            
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("\n🔔 Google Authentication Required! A browser window should open...")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GOOGLE_SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run so you don't have to login again
            with open(token_path, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())

        client = gspread.authorize(creds)
        
        # Open the workbook
        workbook = client.open_by_key(GOOGLE_SHEET_ID)
        
        # Find or Create the "live tab"
        try:
            worksheet = workbook.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"   Creating '{tab_name}' because it didn't exist...")
            worksheet = workbook.add_worksheet(title=tab_name, rows="1000", cols="10")
            worksheet.append_row(["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Job Match", "Apply Link", "Relevance"])

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
                job["Job Match"],
                job["Apply Link"],
                job.get("Relevance", "no")
            ])
            
        # Push data to the cloud
        worksheet.append_rows(rows_to_append)
        print(f"✅ Successfully added {len(fresh_jobs)} jobs to your Google Sheet!")
        
    except FileNotFoundError:
        print("⚠️ 'credentials.json' not found in the folder.")
        print("   Please download an 'OAuth 2.0 Client ID' JSON file from Google Cloud Console.")
    except Exception as e:
        print(f"⚠️ Google Sheets Upload Failed: {e}")

def scrape_linkedin_jobs():
    print("🚀 Launching Chrome with Persistent Profile...\n")
    run_timestamp_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    run_timestamp_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    google_tab_name = f"Werkstudent_Jobs_{run_timestamp_slug}"
    output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs.csv")

    existing_jobs, seen_links, seen_fallback_keys = load_existing_jobs(output_filename)
    fresh_jobs = []
    run_seen_links = set()
    run_seen_fallback_keys = set()
    
    driver = None

    try:
        options = webdriver.ChromeOptions()
        profile_path = os.path.join(BASE_DIR, "chrome_linkedin_profile")
        options.add_argument(f"user-data-dir={profile_path}")

        driver = webdriver.Chrome(options=options)
        driver.maximize_window()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        driver.get("https://www.linkedin.com/login")
        time.sleep(3)  # Wait a moment for the page to load
        #print("\n🛑 ACTION REQUIRED:")
        #print("1. Look at the Chrome window.")
        #print("2. If you are not logged in, please log in manually right now.")
        #print("3. Once you see your LinkedIn feed, come back here.")
        #input("👉 PRESS [ENTER] HERE IN THE TERMINAL TO START SCRAPING...")

        for keyword in SEARCH_KEYWORDS:
            print(f"\n🔍 Searching for: {keyword} ({TIME_FILTER_LABEL})...")

            url = build_search_url(keyword)
            driver.get(url)

            for page_num in range(1, MAX_PAGES_PER_KEYWORD + 1):
                if page_num > 1:
                    moved = move_to_jobs_page(driver, page_num)
                    if not moved:
                        print(f"   ℹ️ Could not move to page {page_num}; stopping pagination for this keyword.")
                        break

                job_cards = load_all_jobs_for_keyword(driver, wait)
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

                        if should_keep_title(title):
                            # Click/read Premium match only for relevant titles to reduce run time.
                            job_match = "unknown"
                            try:
                                driver.execute_script("arguments[0].click();", card)
                                time.sleep(0.8)
                                job_match = extract_job_match_level(driver)
                            except (StaleElementReferenceException, WebDriverException):
                                pass

                            fallback_key = (
                                title.strip().lower(),
                                company.strip().lower(),
                                location.strip().lower(),
                            )
                            if clean_link in seen_links or clean_link in run_seen_links:
                                continue
                            if fallback_key in seen_fallback_keys or fallback_key in run_seen_fallback_keys:
                                continue

                            fresh_jobs.append({
                                "Scraped Date": run_timestamp_display,
                                "Time Filter": TIME_FILTER_LABEL,
                                "Keyword": keyword,
                                "Job Title": title,
                                "Company": company,
                                "Location": location,
                                "Job Match": job_match,
                                "Apply Link": clean_link
                            })
                            run_seen_links.add(clean_link)
                            run_seen_fallback_keys.add(fallback_key)
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

    print(f"💾 Found {len(fresh_jobs)} NEW jobs! Saving locally to {output_filename}...")
    print(f"🎯 Relevant IT jobs after filtering: {len(relevant_jobs_only)} / {len(final_jobs_with_relevance)}")
    
    if relevant_jobs_only:
        # Save to local CSV file
        with open(output_filename, 'w', encoding='utf-8-sig', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=OUTPUT_FIELDNAMES)
            writer.writeheader()
            writer.writerows(relevant_jobs_only)
            
        # Push the NEW jobs to Google Sheets
        fresh_jobs_with_relevance = with_relevance(fresh_jobs)
        fresh_relevant_jobs = [job for job in fresh_jobs_with_relevance if job.get("Relevance") == "yes"]
        upload_to_google_sheets(fresh_relevant_jobs, google_tab_name)
    else:
        print("⚠️ No IT-related jobs found to save.")

if __name__ == '__main__':
    scrape_linkedin_jobs()