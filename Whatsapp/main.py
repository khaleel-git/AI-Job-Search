import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as wait
from selenium.webdriver.support import expected_conditions as EC

# STEP 1: Close ALL Chrome windows manually before running this!
print("⚠️  Make sure ALL Chrome windows are closed!")
input("Press Enter when Chrome is completely closed...")

options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

# Use your Profile 19
options.add_argument("user-data-dir=C:\\Users\\khale\\AppData\\Local\\Google\\Chrome\\User Data")
options.add_argument("profile-directory=Profile 19")

# Disable automation detection
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("--disable-blink-features=AutomationControlled")

try:
    print("🚀 Starting with Profile 19...")
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    driver.get("https://web.whatsapp.com/")
    print("✅ WhatsApp opened with Profile 19!")
    time.sleep(5)
    
    try:
        wait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true'][@data-tab='3']")))
        print("✅ Already logged in!")
    except:
        input("📷 Scan QR and press Enter...")
    
    print("\n🎯 Ready!\n")
    input("Press Enter to close...")
    
except Exception as e:
    print(f"❌ Error: {e}")
finally:
    if 'driver' in locals():
        driver.quit()