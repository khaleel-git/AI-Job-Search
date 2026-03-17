"""LinkedIn Profile Visit and Connection Request."""

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

warnings.filterwarnings("ignore")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_linkedin_profile")
PEOPLE_PAGE_WAIT_SECONDS = 12

# Action and pacing configuration
ACTION_MODE = "connect_or_follow"  # options: connect, follow, connect_or_follow
PACE_PROFILE = "balanced"  # options: conservative, balanced, faster

PACE_PROFILES = {
    "conservative": {
        "short_wait_min": 12.0,
        "short_wait_max": 28.0,
        "long_break_every": 12,
        "long_break_min": 75.0,
        "long_break_max": 140.0,
    },
    "balanced": {
        "short_wait_min": 8.0,
        "short_wait_max": 20.0,
        "long_break_every": 20,
        "long_break_min": 45.0,
        "long_break_max": 90.0,
    },
    "faster": {
        "short_wait_min": 5.0,
        "short_wait_max": 12.0,
        "long_break_every": 30,
        "long_break_min": 25.0,
        "long_break_max": 55.0,
    },
}

if PACE_PROFILE not in PACE_PROFILES:
    raise ValueError("Invalid PACE_PROFILE. Use one of: conservative, balanced, faster")

_pace = PACE_PROFILES[PACE_PROFILE]
SHORT_WAIT_MIN = _pace["short_wait_min"]
SHORT_WAIT_MAX = _pace["short_wait_max"]
LONG_BREAK_EVERY = _pace["long_break_every"]
LONG_BREAK_MIN = _pace["long_break_min"]
LONG_BREAK_MAX = _pace["long_break_max"]


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

    # If profile session is active, LinkedIn redirects away from login page.
    if "linkedin.com/feed" in driver.current_url:
        print("Using existing LinkedIn session from Chrome profile")
        return

    raise RuntimeError(
        "LinkedIn session does not exist in chrome_linkedin_profile. "
        "Run linkedin_session.py to create/save a session first."
    )


def collect_profile_urls(driver, seen_urls, max_scroll_rounds=5):
    """Collect visible LinkedIn profile URLs from the current people page."""
    discovered = set()

    for _ in range(max_scroll_rounds):
        links = driver.find_elements(By.XPATH, "//a[contains(@href, '/in/')]")
        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue
            clean_url = href.split("?")[0].rstrip("/")
            if "/in/" in clean_url and clean_url not in seen_urls:
                discovered.add(clean_url)

        # Try loading more cards if button exists.
        show_more_buttons = driver.find_elements(
            By.XPATH,
            "//button[.//span[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]]"
        )
        if show_more_buttons:
            try:
                driver.execute_script("arguments[0].click();", show_more_buttons[0])
            except Exception:
                pass

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    return sorted(discovered)


driver = launch_driver_with_profile()
ensure_linkedin_login(driver)


url = "https://www.linkedin.com/company/peec-ai/people/"
driver.get(url)
time.sleep(4)

# If company page redirects to login/checkpoint/consent, fail fast with guidance.
if "linkedin.com/company" not in driver.current_url:
    raise RuntimeError(
        f"People page did not load correctly (current URL: {driver.current_url}). "
        "Open the page manually in the same Chrome profile once, then rerun."
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

    Args:
        driver: Selenium WebDriver instance
        profile_url: LinkedIn profile URL
        timeout: Wait timeout in seconds

    Returns:
        str: Action taken ('connect', 'follow', 'already_pending',
             'already_connected', 'visited_only')
    """
    driver.get(profile_url)
    wait = WebDriverWait(driver, timeout)
    time.sleep(random.uniform(2.0, 4.5))
    action_taken = None

    # Check for "Pending" button (connection request already sent)
    try:
        driver.find_element(By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Pending']]")
        print("Connection request already sent (Pending)")
        action_taken = "already_pending"
    except NoSuchElementException:
        pass

    # Check for "Message" button without Connect/Follow (already connected)
    if action_taken is None:
        try:
            driver.find_element(By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Message']]")
            connect_exists = len(driver.find_elements(By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Connect']]")) > 0
            follow_exists = len(driver.find_elements(By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Follow']]")) > 0

            if not connect_exists and not follow_exists:
                print("Already connected with this person")
                action_taken = "already_connected"
        except NoSuchElementException:
            pass

    if action_taken is None:
        if mode in ("connect", "connect_or_follow"):
            try:
                connect_btn = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Connect']]")
                    )
                )
                print("Connect button found")
                driver.execute_script("arguments[0].click();", connect_btn)
                print("Connect button clicked")

                try:
                    send_without_note_btn = wait.until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//button[.//span[normalize-space()='Send without a note']]")
                        )
                    )
                    driver.execute_script("arguments[0].click();", send_without_note_btn)
                    print("Sent connection request without a note")
                    time.sleep(2)
                    action_taken = "connect"
                except TimeoutException:
                    print("'Send without a note' button not found")
                    try:
                        close_btn = driver.find_element(By.XPATH, "//button[@aria-label='Dismiss']")
                        driver.execute_script("arguments[0].click();", close_btn)
                    except Exception:
                        pass
            except TimeoutException:
                print("Connect button not found in main profile, trying fallback XPath...")
                try:
                    connect_btn = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//main//a[contains(@aria-label, 'to connect')]")
                    ))
                    print("Connect button found (fallback XPath)")
                    driver.execute_script("arguments[0].click();", connect_btn)
                    print("Connect button clicked")
                    try:
                        send_without_note_btn = wait.until(EC.element_to_be_clickable(
                            (By.XPATH, "//button[.//span[normalize-space()='Send without a note']]")
                        ))
                        driver.execute_script("arguments[0].click();", send_without_note_btn)
                        print("Sent connection request without a note")
                        time.sleep(2)
                        action_taken = "connect"
                    except TimeoutException:
                        print("'Send without a note' button not found")
                        try:
                            driver.find_element(By.XPATH, "//button[@aria-label='Dismiss']").click()
                        except Exception:
                            pass
                except TimeoutException:
                    print("Connect button not found with fallback either")

        if action_taken is None and mode in ("follow", "connect_or_follow"):
            try:
                follow_btn = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//main//*[self::a or self::button][.//span[normalize-space()='Follow']]")
                    )
                )
                driver.execute_script("arguments[0].click();", follow_btn)
                print("Follow button clicked successfully")
                action_taken = "follow"
            except TimeoutException:
                print("Follow button not found either")

        if action_taken is None:
            action_taken = "visited_only"

    return action_taken


seen_urls = load_visited_profiles()
print(f"Loaded {len(seen_urls)} previously visited profiles from file")
print(f"Action mode: {ACTION_MODE} | Pace profile: {PACE_PROFILE}")

main_window = driver.current_window_handle
total_connects = 0
total_follows = 0
visit_only = 0
total_profiles_visit = 0
total = len(seen_urls)

while True:
    profile_urls = collect_profile_urls(driver, seen_urls)

    total += len(profile_urls)
    print(f"\nFound {len(profile_urls)} new profiles to visit")
    print(f"Total tracked profiles: {total}")

    for i, profile_url in enumerate(profile_urls, 1):
        if profile_url in seen_urls:
            print(f"[{i}/{len(profile_urls)}] Already visited, skipping: {profile_url}")
            continue

        print("\n" + "=" * 60)
        print(f"[{i}/{len(profile_urls)}] Visiting Profile: {profile_url}")
        print("=" * 60)

        try:
            driver.execute_script("window.open('');")
            driver.switch_to.window(driver.window_handles[-1])

            status = visit_and_connect(driver, profile_url, mode=ACTION_MODE, timeout=5)

            print(f"Action taken: {status}")
            if status == "connect":
                total_connects += 1
                print(f"Total connection requests sent: {total_connects}")
            elif status == "follow":
                total_follows += 1
                print(f"Total follows done: {total_follows}")
            elif status == "visited_only":
                visit_only += 1
                print(f"Total profiles visited only (no follow/connect): {visit_only}")

            total_profiles_visit += 1
            wait_time = random.uniform(SHORT_WAIT_MIN, SHORT_WAIT_MAX)
            print(f"Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

            if total_profiles_visit > 0 and total_profiles_visit % LONG_BREAK_EVERY == 0:
                long_break = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
                print(f"Taking a longer pause for {long_break:.1f}s...")
                time.sleep(long_break)

            driver.close()
            driver.switch_to.window(main_window)
            time.sleep(1)

            seen_urls.add(profile_url)
            save_visited_profile(profile_url)
            print("Profile saved to tracking file")

        except Exception as e:
            print(f"Error visiting profile: {e}")
            seen_urls.add(profile_url)
            save_visited_profile(profile_url)
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

    show_more_buttons = driver.find_elements(
        By.XPATH,
        "//button[.//span[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]]"
    )
    if show_more_buttons:
        print("\nLoading more results...")
        try:
            driver.execute_script("arguments[0].click();", show_more_buttons[0])
        except Exception:
            pass
        time.sleep(3)
    else:
        print("\nNo more results to load. Finished!")
        break

    if total_profiles_visit >= 500:
        print("\nReached 100 profiles visit limit for this session.")
        break

print("\n" + "=" * 60)
print("COMPLETED!")
print(f"Total Connects: {total_connects}")
print(f"Total Follows: {total_follows}")
print(f"Total Visit Only: {visit_only}")
print(f"Total profiles visited: {total_profiles_visit}")
print("=" * 60)
