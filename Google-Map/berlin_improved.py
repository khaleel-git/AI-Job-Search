import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as wait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import ActionChains

# For static content scraping
import re, random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Functions
def random_line(afile):
    lines = afile.readlines()
    return random.choice(lines)
# save_to_file
def save_to_file(filename, data_set):
    with open(filename, "w") as f:
        for item in sorted(data_set):
            f.write(f"{item}\n")

# tracked URLs/Emails
def load_tracked_set(filename):
    try:
        with open(filename, "r") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def is_google_redirect(url):
    return any(x in url for x in ["google.com/aclk", "google.com/url"])

def get_final_url_via_selenium(redirect_url):
    try:
        # Create a temporary headless Selenium session
        temp_options = Options()
        temp_options.add_argument("--headless")
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
        temp_options.add_argument("--headless")
        temp_options.add_argument("--no-sandbox")
        temp_options.add_argument("--disable-gpu")
        temp_driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=temp_options)

        temp_driver.get(url)
        wait(temp_driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")

        page_source = temp_driver.page_source
        temp_driver.quit()

        # --- Extract possible emails ---
        raw_emails = set(re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", page_source))

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

        return set(filtered_emails)

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
    relevant_urls = set()

    try:
        try:
            afile = open("useragents.txt")
            headers = random_line(afile).rstrip()
        except Exception as e:
            print(f"⚠ User-Agent list empty, using default. Error: {e}")
            headers = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"

        print(f"Using User-Agent: {headers}")
        r = requests.get(base_url, headers={'User-Agent': headers}, timeout=50, verify=False)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).lower()

            if any(kw in href for kw in keywords) or any(kw in text for kw in keywords):
                abs_url = urljoin(base_url, a["href"])
                relevant_urls.add(abs_url)

    except Exception as e:
        print(f"Error scanning homepage for relevant pages: {e}")

    return list(relevant_urls)


# selenium Initialize Chrome WebDriver
options = Options()
# options.add_argument('--headless')  # optional
options.add_argument('--no-sandbox')
options.add_argument("--ignore-certificate-errors")
options.add_argument("--ignore-ssl-errors")
options.add_argument("--allow-insecure-localhost")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

driver.get("https://www.google.com/maps/search/restaurants+in+kreuzberg+berlin/@52.4968168,13.3920245,14z/data=!3m1!4b1?entry=ttu&g_ep=EgoyMDI1MDgxMC4wIKXMDSoASAFQAw%3D%3D")
# Main Logic .......................................
try:
    tracked_emails = load_tracked_set("tracked_emails.txt")
    tracked_websites = load_tracked_set("tracked_websites.txt")
    # Accept cookies
    try: # only german cookies
        accept_btn = wait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Alle akzeptieren')]"))
        )
        accept_btn.click()
        print("✅ Cookies accepted")
    except:
        print("⚠️ No cookie popup found")

    # Scrollable results container
    scrollable_div = wait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//div[@role='feed']"))
    )

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
        listings = scrollable_div.find_elements(By.XPATH, ".//a[contains(@class,'hfpxzc')]")
        if not listings:
            break
        
        for listing in listings:
            href = listing.get_attribute("href")

            ActionChains(driver).move_to_element(listing).pause(random.uniform(0.5, 1.5)).click().perform()
            time.sleep(1 + random.uniform(1, 3))  # keep some post-click delay

            # Extract restaurant name
            try:
                name = wait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//h1[contains(@class,'DUwDvf')]"))
                ).text
            except:
                name = None

            # Extract website
            try:
                website_elem = driver.find_element(By.XPATH, "//a[contains(@aria-label, 'Website')]")
                raw_url = website_elem.get_attribute("href")

                if is_google_redirect(raw_url):
                    print(f"⚠️ Redirect URL detected: {raw_url}")
                    url = get_final_url_via_selenium(raw_url)
                    website = url.split('?')[0] if url else None
                else:
                    website = raw_url.split('?')[0]
                
                if website in tracked_websites:
                    print(f"⚠️ Skipping {website} — already processed")
                    continue

            except Exception as e:
                print(f"Error extracting website: {e}")
                website = None

            print(f"\n\n")
            print("=" * 40)
            print(f"Name: {name or 'Unknown'}")
            print(f"Website: {website}")

            if website:
                # Fetch emails from homepage
                emails = fetch_emails(website)
                if emails:
                    print(f"New emails found on {website}: {emails}")
                    for i, email in enumerate(emails, 1):
                        tracked_emails.add(email)
                        print(f"email {i}: {email}")
                    tracked_websites.add(website)
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
                                print(f"email {i}: {email}")
                                tracked_emails.add(email)
                            tracked_websites.add(website)
                            break  # stop after finding emails
                    else:
                        # no break happened → no emails found on any relevant page
                        print("⚠️ No emails found on any relevant page.")
                else:
                    print("⚠️ No relevant pages found.")
                # Return to list
                save_to_file("tracked_emails.txt", tracked_emails)
                save_to_file("tracked_websites.txt", tracked_websites)

            driver.execute_script("arguments[0].scrollIntoView();", scrollable_div)
            time.sleep(1+random.uniform(1, 3))  # random delay for human-like behavior
        # Scroll to load more listings
        prev_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_div)
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
        time.sleep(1+random.uniform(1, 3))  # random delay for human-like behavior
        new_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_div)
        if new_height == prev_height:
            break
        print("\n\n@@@@@@@@@@@@@@@@@ Loading more listings...")

except KeyboardInterrupt:
    print("\n🛑 Interrupted by user, exiting...")
finally:
    driver.quit()