"""Create or verify LinkedIn session using persistent Chrome profile.

Behavior:
- If a saved session exists, exits without asking for credentials.
- If no session exists, opens login page and asks user to log in manually.
- Session is saved in chrome_linkedin_profile for future scripts.
"""

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_linkedin_profile")


def launch_driver_with_profile():
    options = Options()
    options.add_argument(f"user-data-dir={PROFILE_DIR}")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def has_active_session(driver):
    driver.get("https://www.linkedin.com/feed/")
    time.sleep(3)
    return "linkedin.com/feed" in driver.current_url


def main():
    driver = None
    try:
        driver = launch_driver_with_profile()

        if has_active_session(driver):
            print("Saved LinkedIn session already exists. Nothing to do.")
            return

        print("No saved LinkedIn session found.")
        print("Please log in manually in the opened browser window.")
        input("After login completes and feed is visible, press ENTER here...")

        if has_active_session(driver):
            print("LinkedIn session saved successfully in chrome_linkedin_profile.")
        else:
            print("Session was not created. Please try again.")
            sys.exit(1)

    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    main()
