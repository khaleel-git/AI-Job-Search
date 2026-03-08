import csv
import time
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Pre-filled dictionary for the top Tier A companies to save time and API requests!
PREFILLED_URLS = {
    "Google": "https://careers.google.com/jobs/results/",
}

def search_career_page(driver, company_name):
    """Uses Selenium to visually find the most relevant career page URL for a company."""
    if company_name in PREFILLED_URLS:
        return PREFILLED_URLS[company_name]
    
    query = f"{company_name} careers jobs Germany"
    try:
        # 1. Navigate to DuckDuckGo
        driver.get("https://duckduckgo.com/")
        
        # 2. Wait for the search box to load, type the query, and press Enter
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "q"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)
        
        # 3. Wait for the search results to load and extract the first link
        first_result = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='result-title-a']"))
        )
        url = first_result.get_attribute("href")
        
        # Add a 2-second visual pause so you can actually watch it work!
        time.sleep(2) 
        
        return url
        
    except TimeoutException:
        print(f"  -> [Timeout] Could not find search results for {company_name}")
    except Exception as e:
        print(f"  -> [Error] Issue searching for {company_name}: {e}")
        
    return ""

def process_csv(input_filename, output_filename):
    print(f"Reading {input_filename}...")
    
    try:
        with open(input_filename, 'r', encoding='utf-8-sig') as infile:
            reader = csv.DictReader(infile)
            fieldnames = reader.fieldnames
            rows = list(reader)
    except FileNotFoundError:
        print(f"Could not find the file: {input_filename}")
        print("Please ensure the script and the CSV file are in the same folder.")
        sys.exit(1)

    print(f"Found {len(rows)} companies. Starting automation...\n")

    # --- NEW: Open the live Chrome browser! ---
    print("Launching Chrome browser...")
    try:
        driver = webdriver.Chrome()
    except Exception as e:
        print(f"Failed to launch Chrome. Do you have Google Chrome installed? Error: {e}")
        sys.exit(1)

    with open(output_filename, 'w', encoding='utf-8-sig', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for i, row in enumerate(rows):
            company = row.get('company', '')
            current_url = row.get('Career Page', '')
            
            # If the career page is blank, automatically search for it
            if company and not current_url.strip():
                print(f"[{i+1}/{len(rows)}] Finding careers page for: {company}...")
                
                # Pass the live browser 'driver' to the search function
                new_url = search_career_page(driver, company)
                row['Career Page'] = new_url
                
            else:
                print(f"[{i+1}/{len(rows)}] Skipping {company} (URL already exists)")

            writer.writerow(row)

    # Close the browser when finished
    print("\nClosing browser...")
    driver.quit()

    print(f"\n✅ All done! Saved your fully updated list to: {output_filename}")

if __name__ == '__main__':
    # Make sure these filenames match exactly what you have on your computer!
    INPUT_CSV = "top500.csv"
    OUTPUT_CSV = "Germany Job Logs - Top 500 - UPDATED.csv"
    
    process_csv(INPUT_CSV, OUTPUT_CSV)