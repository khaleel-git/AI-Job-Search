"""LinkedIn Profile Visit and Connection Request."""

import os
import time
import random
import warnings

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchWindowException
from selenium.webdriver.chrome.options import Options

warnings.filterwarnings("ignore")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_linkedin_profile")

ACTION_MODE = "connect"  # options: 'connect' or 'follow'
SESSION_LIMIT = 500

def launch_driver_with_profile():
    options = Options()
    options.add_argument(f"user-data-dir={PROFILE_DIR}")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def ensure_linkedin_login(driver):
    """Only use existing session from Chrome profile; exit if not logged in."""
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    if "linkedin.com/feed" in driver.current_url or "linkedin.com/in/" in driver.current_url:
        print("✅ Using existing LinkedIn session from Chrome profile")
        return

    raise RuntimeError(
        "LinkedIn session does not exist in chrome_linkedin_profile. "
        "Run your login script to create/save a session first."
    )


VISITED_PROFILES_FILE = "visited_profiles.txt"

def load_visited_profiles():
    """Load previously visited profiles from file."""
    if os.path.exists(VISITED_PROFILES_FILE):
        with open(VISITED_PROFILES_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_visited_profile(profile_url):
    """Save a visited profile URL to file."""
    with open(VISITED_PROFILES_FILE, "a", encoding="utf-8") as f:
        f.write(profile_url + "\n")


def visit_and_connect(driver, profile_url, mode, timeout):
    """
    Visit a LinkedIn profile and attempt to connect or follow.

    Returns one of: 'connect', 'follow', 'visited_only'
    """
    driver.get(profile_url)
    wait = WebDriverWait(driver, timeout)
    time.sleep(2)
    base = "//main//*[self::a or self::button]"

    # Keep only connect/follow/visited_only result states.
    if driver.find_elements(By.XPATH, f"{base}[.//span[normalize-space()='Pending']]"):
        print("⏳ Connection request already sent (Pending)")
        return "visited_only"

    message_exists = bool(driver.find_elements(By.XPATH, f"{base}[.//span[normalize-space()='Message']]"))
    connect_exists = bool(driver.find_elements(By.XPATH, f"{base}[.//span[normalize-space()='Connect']]"))
    follow_exists = bool(driver.find_elements(By.XPATH, f"{base}[.//span[normalize-space()='Follow']]"))
    if message_exists and not connect_exists and not follow_exists:
        print("✓ Already connected with this person")
        return "visited_only"

    if mode == "connect":
        try:
            connect_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, f"{base}[.//span[normalize-space()='Connect']]")
                )
            )
            driver.execute_script("arguments[0].click();", connect_btn)
            print("📤 Connect button clicked")
            return "connect"
        except TimeoutException:
            print("   Connect button not found in main profile, trying fallback XPath...")
            try:
                connect_btn = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//main//a[contains(@aria-label, 'to connect')]")
                    )
                )
                driver.execute_script("arguments[0].click();", connect_btn)
                print("📤 Connect button clicked (fallback)")
                return "connect"
            except TimeoutException:
                print("   Connect button not found with fallback either")

    try:
        follow_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"{base}[.//span[normalize-space()='Follow']]")
            )
        )
        driver.execute_script("arguments[0].click();", follow_btn)
        print("✓ Follow button clicked successfully")
        return "follow"
    except TimeoutException:
        print("❌ Follow button not found either")
        return "visited_only"


if __name__ == "__main__":
    driver = launch_driver_with_profile()
    ensure_linkedin_login(driver)

    url = "https://www.linkedin.com/company/bik-gmbh/people/"
    driver.get(url)
    time.sleep(4)

    # Load previously visited profiles
    seen_urls = load_visited_profiles()
    print(f"📂 Loaded {len(seen_urls)} previously visited profiles from file")

    # Store the main window handle
    main_window = driver.current_window_handle
    total_connects = 0
    total_follows = 0
    visit_only = 0
    total_profiles_visit = 0

    while True:
        # Collect profiles currently loaded on the page
        profile_links = driver.find_elements(
            By.XPATH,
            "//a[contains(@href, 'linkedin.com/in/')]"
        )

        # Extract all URLs first and remove duplicates
        profile_urls = []
        seen_in_batch = set()
        for link in profile_links:
            href = link.get_attribute("href")
            if href:
                # Clean URL: remove query parameters
                clean_url = href.split('?')[0].rstrip('/')
                if clean_url not in seen_urls and clean_url not in seen_in_batch:
                    seen_in_batch.add(clean_url)
                    profile_urls.append(clean_url)

        print(f"\n✅ Found {len(profile_urls)} new profiles to visit")

        # Visit each profile in a new tab
        for i, url in enumerate(profile_urls, 1):
            if url in seen_urls:
                print(f"⏭️  [{i}/{len(profile_urls)}] Already visited, skipping: {url}")
                continue

            print(f"\n{'='*60}")
            print(f"🔍 [{i}/{len(profile_urls)}] Visiting Profile: {url}")
            print(f"{'='*60}")

            try:
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[-1])

                status = visit_and_connect(driver, url, mode=ACTION_MODE, timeout=5)

                print(f"🔔 Action taken: {status}")
                if status == 'connect':
                    total_connects += 1
                    print(f"📈 Total connection requests sent: {total_connects}")
                elif status == 'follow':
                    total_follows += 1
                    print(f"📈 Total follows done: {total_follows}")
                else:
                    visit_only += 1
                    print(f"📈 Total profiles visited only: {visit_only}")

                total_profiles_visit += 1
                wait_time = random.uniform(6.5, 17.3)
                print(f"⏳ Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)

                driver.close()
                driver.switch_to.window(main_window)
                time.sleep(1)

                seen_urls.add(url)
                save_visited_profile(url)
                print("✅ Profile saved to tracking file")

            except Exception as e:
                print(f"❌ Error visiting profile: {e}")
                seen_urls.add(url)
                save_visited_profile(url)
                try:
                    handles = driver.window_handles
                    if len(handles) > 1 and driver.current_window_handle != main_window:
                        driver.close()
                    driver.switch_to.window(main_window)
                except (NoSuchWindowException, Exception):
                    try:
                        driver.switch_to.window(driver.window_handles[0])
                        main_window = driver.window_handles[0]
                    except Exception:
                        pass

            if total_profiles_visit >= SESSION_LIMIT:
                print(f"\n🚫 Reached {SESSION_LIMIT} profiles visit limit for this session.")
                break

        if total_profiles_visit >= SESSION_LIMIT:
            break

        # Try to load more results
        show_more_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(@class, 'scaffold-finite-scroll__load-button') and .//span[normalize-space()='Show more results']]"
        )
        if show_more_buttons:
            print("\n📜 Loading more results...")
            driver.execute_script("arguments[0].click();", show_more_buttons[0])
            time.sleep(3)
        else:
            print("\n🎯 No more results to load. Finished!")
            break

    print(f"\n{'='*60}")
    print(f"✅ COMPLETED!")
    print(f"📊 Total Connects: {total_connects}")
    print(f"📊 Total Follows: {total_follows}")
    print(f"📊 Total Visit Only: {visit_only}")
    print(f"📊 Total profiles visited: {total_profiles_visit}")
    print(f"{'='*60}")