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

# The specific job roles you are looking for as a Working Student
SEARCH_KEYWORDS = [
    "Werkstudent Data Engineering",
    "Werkstudent AI",
    "Werkstudent DevOps",
    "Werkstudent Platform Engineering",
    "Werkstudent Infrastructure",
    "Werkstudent Cloud",
    "Working Student Data Engineering",
    "Working Student AI",
    "Working Student DevOps",
    "Working Student Platform Engineering",
    "Working Student Infrastructure",
    "Working Student Cloud"
]

LOCATION = "Germany"
TIME_FILTER = "r3600" 
TIME_FILTER_LABEL = "Past 1 Hour"
WAIT_SECONDS = 15
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

TITLE_MATCH_TOKENS = ("werkstudent", "working student", "student worker", "intern")


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


def build_search_url(keyword):
    query = urlencode({"keywords": keyword, "location": LOCATION, "f_TPR": TIME_FILTER})
    return f"https://www.linkedin.com/jobs/search/?{query}"


def load_all_jobs_for_keyword(driver, wait):
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
    except Exception:
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
        except Exception:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

    return driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)

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
            worksheet.append_row(["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link"])

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
                job["Apply Link"]
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

        all_jobs = []

        for keyword in SEARCH_KEYWORDS:
            print(f"\n🔍 Searching for: {keyword} ({TIME_FILTER_LABEL})...")

            url = build_search_url(keyword)
            driver.get(url)

            job_cards = load_all_jobs_for_keyword(driver, wait)
            print(f"   Found {len(job_cards)} recent jobs for {keyword} on this page.")

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

                    if should_keep_title(title):
                        all_jobs.append({
                            "Scraped Date": run_timestamp_display,
                            "Time Filter": TIME_FILTER_LABEL,
                            "Keyword": keyword,
                            "Job Title": title,
                            "Company": company,
                            "Location": location,
                            "Apply Link": clean_link
                        })
                except Exception as e:
                    print(f"   Skipping card {idx} for '{keyword}' due to parse error: {e}")

    except Exception as e:
        print(f"Failed to launch or run Chrome. Error: {e}")
        sys.exit(1)
    finally:
        if driver is not None:
            print("\n✅ Finished scraping. Closing browser...")
            driver.quit()

    output_filename = os.path.join(BASE_DIR, "Live_Werkstudent_Jobs.csv")
    existing_jobs = []
    seen_links = set()
    seen_fallback_keys = set()

    if os.path.exists(output_filename):
        with open(output_filename, 'r', encoding='utf-8-sig') as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                if "Time Filter" not in row:
                    row["Time Filter"] = "Unknown"
                existing_jobs.append(row)
                apply_link = (row.get("Apply Link", "") or "").strip()
                if apply_link:
                    seen_links.add(apply_link)
                fallback_key = (
                    row.get("Job Title", "").strip().lower(),
                    row.get("Company", "").strip().lower(),
                    row.get("Location", "").strip().lower()
                )
                seen_fallback_keys.add(fallback_key)

    fresh_jobs = []
    for job in all_jobs:
        fallback_key = (
            job["Job Title"].strip().lower(),
            job["Company"].strip().lower(),
            job["Location"].strip().lower()
        )
        if job["Apply Link"] not in seen_links and fallback_key not in seen_fallback_keys:
            fresh_jobs.append(job)
            seen_links.add(job["Apply Link"])
            seen_fallback_keys.add(fallback_key)

    final_jobs = fresh_jobs + existing_jobs

    print(f"💾 Found {len(fresh_jobs)} NEW jobs! Saving locally to {output_filename}...")
    
    if final_jobs:
        # Save to local CSV file
        with open(output_filename, 'w', encoding='utf-8-sig', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=["Scraped Date", "Time Filter", "Keyword", "Job Title", "Company", "Location", "Apply Link"])
            writer.writeheader()
            writer.writerows(final_jobs)
            
        # Push the NEW jobs to Google Sheets
        upload_to_google_sheets(fresh_jobs, google_tab_name)
    else:
        print("⚠️ No exact matches found or no new jobs to add.")

if __name__ == '__main__':
    scrape_linkedin_jobs()