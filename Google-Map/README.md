# Google Maps Business/Restaurant Email Scraper

This project scrapes restaurant/business websites and emails from Google Maps search results, focusing on Berlin restaurants.  
It uses **Selenium** to interact with Google Maps and **Requests + BeautifulSoup** to extract emails from websites and relevant pages (like Contact, Careers, Jobs).

---

## Features

- Navigate Google Maps restaurant/business listings using Selenium
- Extract restaurant names and websites
- Detect and resolve Google redirect URLs to final website URLs
- Scrape homepage and relevant pages for emails (contact, career, job pages)
- Supports English and German keywords for relevant page detection
- Tracks processed websites and emails to avoid duplicates
- Handles cookie popups on Google Maps
- Graceful shutdown on interruption

---

## Requirements

- Python 3.8+
- Google Chrome browser installed
- Recommended: run in a virtual environment

---

## Installation

1. Clone the repository or download the script.
2. Install required Python packages:

```bash
pip install -r requirements.txt
````

---

## Usage

1. Run the script:

```bash
python scraper.py
```

2. The script will open Google Maps searching for Berlin restaurants and start scraping.

3. Found emails and websites are saved to:

* `tracked_emails.txt`
* `tracked_websites.txt`

4. Interrupt the script anytime with `Ctrl+C`.

---

## Configuration

* To run Chrome in headless mode, uncomment the line in `scraper.py`:

```python
options.add_argument('--headless')
```

* Modify keywords in the `find_relevant_pages` function to suit your target language or use case.

---

## File Structure

* `scraper.py` — Main script file with scraping logic
* `tracked_emails.txt` — Output file with collected emails (one per line)
* `tracked_websites.txt` — Output file with processed websites (one per line)
* `requirements.txt` — List of required Python packages

---

## Notes

* The script includes delays between requests to avoid overwhelming servers.
* Some websites may block automated scraping; consider adding proxy support or headers if necessary.
* The email regex is basic and may capture false positives or miss some complex email formats.

---

## Troubleshooting

* **ChromeDriver version mismatch:** Ensure your Chrome browser is updated; `webdriver-manager` handles driver versioning automatically.
* **Timeouts or no results:** Network issues or Google Maps page updates may require selector or wait time adjustments.
* **Google Maps interface language:** The script clicks the German "Alle akzeptieren" cookie button; update this for other locales.

---

## License

This project is released under the MIT License.

---

## Author
Khaleel Ahmad,
Contact: [khaleel.eu@gmail.com](mailto:khaleel.eu@gmail.com)