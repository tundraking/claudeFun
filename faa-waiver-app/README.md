# FAA Part 107 Waiver App

A tool for scraping, storing, and browsing FAA Part 107 drone waiver records.

The FAA publishes a public table of all issued Part 107 waivers at:
`https://www.faa.gov/uas/commercial_operators/part_107_waivers/waivers_issued`

This project scrapes that table (all ~1,900 records across ~76 pages), stores the records in a local SQLite database, and downloads the associated waiver PDFs.

## Project Structure

```
faa-waiver-app/
├── scraper.py        # Scrapes FAA waiver table and populates the database
├── database.py       # SQLAlchemy models and DB initialization
├── app.py            # Flask web app for browsing records (in development)
├── templates/        # Flask HTML templates
├── pdfs/             # Downloaded waiver PDF files
└── requirements.txt  # Python dependencies
```

## Setup

**1. Create and activate a virtual environment (recommended):**

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

## Usage

### Scrape waiver records

```bash
python scraper.py
```

This will:
- Create a `waivers.db` SQLite database on first run
- Walk all pages of the FAA waiver table
- Insert new records, skipping any already in the database
- Download the waiver PDF for each record into the `pdfs/` folder
- Print progress page-by-page

Re-running the scraper is safe — existing records and already-downloaded PDFs are skipped automatically.

Example output:

```
Found 0 existing records in database.
Detected columns: ['date of issuance', 'expiration date', 'company name', 'responsible person', 'waivered regulation']
Processing page 1 (https://www.faa.gov/uas/commercial_operators/part_107_waivers/waivers_issued) ...
  Page 1: +25 new, 0 duplicates (running total: 25 added)
Processing page 2 (...?page=1) ...
  Page 2: +25 new, 0 duplicates (running total: 50 added)
...
Done. Added 1891 new records, skipped 0 duplicates across 76 page(s).
```

### Database schema

Records are stored in a single `waivers` table:

| Column               | Description                                      |
|----------------------|--------------------------------------------------|
| `id`                 | Auto-increment primary key                       |
| `waiver_number`      | Waiver ID from PDF filename, or composite key    |
| `date_of_issuance`   | Date the waiver was issued                       |
| `responsible_person` | Named responsible person on the waiver           |
| `company_name`       | Applicant company name                           |
| `waivered_regulation`| FAA regulation(s) waived                         |
| `pdf_url`            | Source URL of the waiver PDF                     |
| `pdf_local_path`     | Local path to the downloaded PDF                 |
| `pdf_text`           | Extracted PDF text (populated separately)        |

You can query the database directly:

```bash
sqlite3 waivers.db "SELECT waiver_number, company_name, date_of_issuance FROM waivers LIMIT 10;"
```

## Dependencies

| Package          | Purpose                              |
|------------------|--------------------------------------|
| `requests`       | HTTP requests to the FAA website     |
| `beautifulsoup4` | HTML parsing and table scraping      |
| `SQLAlchemy`     | ORM and SQLite database management   |
| `Flask`          | Web app framework                    |
| `pdfplumber`     | PDF text extraction                  |
