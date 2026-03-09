# AI Job Search Project Overview

This repository contains automation scripts and utilities for job discovery, outreach tracking, and profile/connection workflows across multiple platforms.

## Project Modules

### 1. Google-Map
Purpose: Collect and track leads from Google Maps and related search workflows.

Key files:
- `Google-Map/main.py`: Main script for Google Maps related scraping/search logic.
- `Google-Map/requirements.txt`: Python dependencies for this module.
- `Google-Map/berlin_restaurant_searches.txt`, `Google-Map/tech_jobs.txt`, `Google-Map/english_speaking_jobs.txt`: Search input lists.
- `Google-Map/tracked_emails.txt`, `Google-Map/tracked_websites.txt`: Current tracked lead outputs.
- `Google-Map/oldtracked_emails.txt`, `Google-Map/oldtracked_websites.txt`: Historical tracking files.
- `Google-Map/useragents.txt`: User-agent list used by scraping requests.

### 2. IT_Companies
Purpose: Track IT companies and scrape live Working Student job postings (LinkedIn flow).

Key files:
- `IT_Companies/werkstudent.py`: Main LinkedIn job scraping script for Werkstudent and Working Student roles.
- `IT_Companies/top500.py`: Company data processing script.
- `IT_Companies/top500.csv`: Company list data.
- `IT_Companies/requirements.txt`: Python dependencies for this module.
- `IT_Companies/chrome_linkedin_profile/`: Persistent Chrome profile for logged-in scraping sessions.

Notes:
- `credentials.json` and `token.json` are sensitive OAuth files used for Google Sheets integration.
- Virtual environment expected in `IT_Companies/venv/`.

### 3. Linkedin
Purpose: LinkedIn workflows for networking and job-related processing.

Key files:
- `Linkedin/linkedin_profile.py`: Python automation/utilities for profile handling.
- `Linkedin/similarity_search.py`: Similarity matching/search logic.
- `Linkedin/jobs_search.ipynb`: Notebook for job search experiments.
- `Linkedin/linkedin_connections.ipynb`: Notebook for connection-related workflows.
- `Linkedin/accept_requests.ipynb`: Notebook for connection request handling.
- `Linkedin/similarity_search.ipynb`: Notebook version of similarity search workflow.
- `Linkedin/requirements.txt`: Python dependencies for this module.

### 4. Whatsapp
Purpose: WhatsApp automation utilities.

Key files:
- `Whatsapp/main.py`: Main script for WhatsApp workflow.

## Typical Workflow

1. Run module-specific scripts from their own folder (recommended).
2. Use module `requirements.txt` and local `venv` for dependency isolation.
3. Keep sensitive credentials and session artifacts out of git tracking.
4. Store final outputs and logs in non-source files as needed.

## Security and Hygiene

- Keep OAuth and token files private (`credentials.json`, `token.json`, `.env*`).
- Do not commit browser profile/session directories (for example `chrome_linkedin_profile/`).
- Commit only source code and documentation (`.py`, `.md`) where possible.
