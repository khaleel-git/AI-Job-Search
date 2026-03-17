import os
import time
import random
import warnings

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoSuchWindowException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "chrome_linkedin_profile")
VISITED_PROFILES_FILE = "visited_profiles.txt"
TARGET_URL = "https://www.linkedin.com/company/bik-gmbh/people/"
MODE = "connect"          # 'connect' or 'follow'
SESSION_LIMIT = 500      # max profiles to visit per session
WAIT_TIMEOUT = 5         # selenium wait timeout in seconds


# ──────────────────────────────────────────────
# Driver & Session
# ──────────────────────────────────────────────
def launch_driver_with_profile():
    """Launch Chrome reusing an existing profile (preserves LinkedIn session)."""
    options = Options()
    options.add_argument(f"user-data-dir={PROFILE_DIR}")
    # Intentionally NOT maximizing the window to keep the sidebar hidden
    driver = webdriver.Chrome(options=options)
    return driver


def ensure_linkedin_login(driver):
    """Use existing session from Chrome profile; raise if not logged in."""
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    if "linkedin.com/feed" in driver.current_url or "linkedin.com/in/" in driver.current_url:
        print("✅ Using existing LinkedIn session from Chrome profile")
        return

    raise RuntimeError(
        "LinkedIn session does not exist in chrome_linkedin_profile. "
        "Run your login script to create/save a session first."
    )



def load_visited_profiles():
    """Load previously visited profiles from file."""
    if os.path.exists(VISITED_PROFILES_FILE):
        with open(VISITED_PROFILES_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_visited_profile(url):
    """Save a visited profile URL to file."""
    with open(VISITED_PROFILES_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def visit_and_connect(driver, profile_url, mode, timeout):
    """
    Visit a LinkedIn profile and attempt to connect or follow.

    Args:
        driver:       Selenium WebDriver instance
        profile_url:  LinkedIn profile URL
        mode:         'connect' or 'follow'
        timeout:      WebDriverWait timeout in seconds

    Returns:
        str: Action taken – 'connect', 'follow', 'already_pending',
             'already_connected', or 'visited_only'
    """
    driver.get(profile_url)
    wait = WebDriverWait(driver, timeout)
    time.sleep(2)
    action_taken = None

    # Check for pending connection request
    try:
        driver.find_element(
            By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Pending']]"
        )
        print("⏳ Connection request already sent (Pending)")
        action_taken = "already_pending"
    except NoSuchElementException:
        pass

    # Check if already connected (Message button present, no Connect/Follow)
    if action_taken is None:
        try:
            driver.find_element(
                By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Message']]"
            )
            connect_exists = len(driver.find_elements(
                By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Connect']]"
            )) > 0
            follow_exists = len(driver.find_elements(
                By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Follow']]"
            )) > 0

            if not connect_exists and not follow_exists:
                print("✓ Already connected with this person")
                action_taken = "already_connected"
        except NoSuchElementException:
            pass

    # Attempt connect / follow
    if action_taken is None:
        if mode == "connect":
            try:
                connect_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//main//a[.//span[normalize-space()='Connect']]")
                ))
                print("📤 Connect button found")
                driver.execute_script("arguments[0].click();", connect_btn)
                print("   Connect button clicked")
                input("   Please complete the connection flow manually (e.g. add note, send) and press Enter here to continue...")
                try:
                    send_btn = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//button[.//span[normalize-space()='Send without a note']]")
                    ))
                    driver.execute_script("arguments[0].click();", send_btn)
                    print("✓ Sent connection request without a note")
                    time.sleep(2)
                    action_taken = "connect"
                except TimeoutException:
                    print("⚠️  'Send without a note' button not found")
                    try:
                        driver.find_element(
                            By.XPATH, "//button[@aria-label='Dismiss']"
                        ).click()
                    except Exception:
                        pass

            except TimeoutException:
                print("   Connect button not found in main profile, trying fallback XPath...")
                try:
                    connect_span = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//main//a[contains(@aria-label, 'to connect')]")
                    ))
                    print("📤 Connect button found (fallback XPath)")
                    driver.execute_script("arguments[0].click();", connect_span)
                    print("   Connect button clicked")
                    input("   Please complete the connection flow manually (e.g. add note, send) and press Enter here to continue...")
                    try:
                        send_btn = wait.until(EC.element_to_be_clickable(
                            (By.XPATH, "//button[.//span[normalize-space()='Send without a note']]")
                        ))
                        driver.execute_script("arguments[0].click();", send_btn)
                        print("✓ Sent connection request without a note")
                        time.sleep(2)
                        action_taken = "connect"
                    except TimeoutException:
                        print("⚠️  'Send without a note' button not found")
                        try:
                            driver.find_element(
                                By.XPATH, "//button[@aria-label='Dismiss']"
                            ).click()
                        except Exception:
                            pass
                except TimeoutException:
                    print("   Connect button not found with fallback either")

        # Try Follow button (runs for both modes if connect wasn't taken)
        try:
            follow_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Follow']]")
            ))
            driver.execute_script("arguments[0].click();", follow_btn)
            print("✓ Follow button clicked successfully")
            action_taken = "follow"
        except TimeoutException:
            print("❌ Follow button not found either")
            action_taken = "visited_only"

    return action_taken


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    # Launch browser using saved Chrome profile (no credentials needed)
    driver = launch_driver_with_profile()
    ensure_linkedin_login(driver)

    # Navigate to target page
    driver.get(TARGET_URL)
    time.sleep(3)

    # Load state
    seen_urls = load_visited_profiles()
    print(f"📂 Loaded {len(seen_urls)} previously visited profiles from file")

    main_window = driver.current_window_handle
    total_connects = 0
    total_follows = 0
    total_profiles_visit = 0
    total = len(seen_urls)

    while True:
        # Collect profile links currently on page
        profile_links = driver.find_elements(
            By.XPATH, "//a[contains(@href, 'linkedin.com/in/')]"
        )

        profile_urls = []
        for link in profile_links:
            href = link.get_attribute("href")
            if href:
                clean_url = href.split("?")[0].rstrip("/")
                if clean_url not in seen_urls:
                    profile_urls.append(clean_url)

        total += len(profile_urls)
        print(f"\n✅ Found {len(profile_urls)} new profiles to visit")
        print(f"📊 Total tracked profiles: {total}")

        for i, url in enumerate(profile_urls, 1):
            if url in seen_urls:
                print(f"⏭️  [{i}/{len(profile_urls)}] Already visited, skipping: {url}")
                continue

            print(f"\n{'=' * 60}")
            print(f"🔍 [{i}/{len(profile_urls)}] Visiting Profile: {url}")
            print(f"{'=' * 60}")

            try:
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[-1])

                status = visit_and_connect(driver, url, mode=MODE, timeout=WAIT_TIMEOUT)

                print(f"🔔 Action taken: {status}")
                if status == "connect":
                    total_connects += 1
                    print(f"📈 Total connection requests sent: {total_connects}")
                elif status == "follow":
                    total_follows += 1
                    print(f"📈 Total follows done: {total_follows}")
                elif status == "visited_only":
                    total_profiles_visit += 1
                    print(f"📈 Total profiles visited only (no follow/connect): {total_profiles_visit}")

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

        # Try to load more results
        try:
            show_more = driver.find_element(
                By.XPATH, "//button[.//span[text()='Show more results']]"
            )
            print("\n📜 Loading more results...")
            driver.execute_script("arguments[0].click();", show_more)
            time.sleep(3)
        except NoSuchElementException:
            print("\n🎯 No more results to load. Finished!")
            break

        if total_profiles_visit >= SESSION_LIMIT:
            print(f"\n🚫 Reached {SESSION_LIMIT} profiles visit limit for this session.")
            break

    print(f"\n{'=' * 60}")
    print("✅ COMPLETED!")
    print(f"📊 Total Connects:        {total_connects}")
    print(f"📊 Total Follows:         {total_follows}")
    print(f"📊 Total profiles visited:{total_profiles_visit}")
    print(f"{'=' * 60}")

    driver.quit()


if __name__ == "__main__":
    main()