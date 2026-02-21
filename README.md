# FAA Part 107 Waiver Browser

A tool for scraping, storing, and browsing FAA Part 107 drone waiver records.

The FAA publishes a public table of all issued Part 107 waivers at:
`https://www.faa.gov/uas/commercial_operators/part_107_waivers/waivers_issued`

This project scrapes that table (~1,900 records across ~76 pages), stores records in a local SQLite database, downloads the associated waiver PDFs, extracts their text for full-text search, and provides a web UI for browsing and searching everything.

## Project Structure

```
faa-waiver-app/
├── scraper.py        # Scrapes FAA waiver table and downloads PDFs
├── extract_text.py   # Extracts text from downloaded PDFs into the database
├── database.py       # SQLAlchemy models, DB init, and FTS index management
├── app.py            # Flask web app
├── templates/
│   ├── base.html         # Shared layout and navbar
│   ├── index.html        # Waiver list with filters, sorting, and pagination
│   ├── waiver.html       # Individual waiver detail page
│   └── search_results.html  # Full-text search results
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
pip install -r faa-waiver-app/requirements.txt
```

## Initial Data Load

Run these three commands once to populate the database from scratch:

**Step 1 — Scrape the FAA table and download PDFs:**

```bash
python faa-waiver-app/scraper.py
```

This will:
- Create `waivers.db` on first run
- Walk all pages of the FAA waiver table
- Insert new records, skipping any already in the database
- Download the waiver PDF for each record into `pdfs/`
- Print progress page-by-page

Re-running is safe — existing records and already-downloaded PDFs are skipped automatically.

Example output:
```
Found 0 existing records in database.
Detected columns: ['date of issuance', 'expiration date', 'company name', 'responsible person', 'waivered regulation']
Processing page 1 (https://www.faa.gov/uas/...) ...
  Page 1: +25 new, 0 duplicates (running total: 25 added)
...
Done. Added 1891 new records, skipped 0 duplicates across 76 page(s).
```

**Step 2 — Extract text from PDFs:**

```bash
python faa-waiver-app/extract_text.py
```

Reads each downloaded PDF and writes its extracted text to the `pdf_text` column. Only processes PDFs that don't already have extracted text. Skips any PDF file with no matching database record.

**Step 3 — Build the full-text search index:**

```bash
python faa-waiver-app/database.py
```

Creates and populates the `waivers_fts` FTS5 virtual table used by the full-text search feature.

## Running the Web App

```bash
python faa-waiver-app/app.py
```

Then open `http://127.0.0.1:5000` in your browser.

The app automatically creates the database schema and FTS table on startup if they don't exist.

## Web UI Features

### Waiver List (`/`)
- Browse all waivers with sortable columns (waiver number, date, company, person, regulation)
- Filter by date, responsible person, company name, or waivered regulation
- Paginated results (25 per page)

### Waiver Detail (`/waiver/<id>`)
- Full metadata for a single waiver
- Links to the FAA source PDF and a local downloaded copy
- Extracted PDF text displayed in a scrollable panel, cleaned up for readability:
  - Extra blank lines collapsed
  - Repeated footer lines removed (page numbers, "Federal Aviation Administration", certificate header after the first page)

### Full-Text Search (`/search`)
- Searches across all extracted PDF text using SQLite FTS5
- Results show a snippet of the matching text around the keyword

### Fetch New Waivers (button on home page)
- Click **"Fetch new Part 107 waivers from the FAA table"** to run all three pipeline steps in sequence without leaving the browser:
  1. Scrape the FAA table for new records and download any new PDFs
  2. Extract text from any newly downloaded PDFs
  3. Rebuild the full-text search index
- The button shows a spinner while running and displays a summary on completion (e.g. "Done — 3 new waiver(s) added, 3 PDF(s) processed.")
- Progress is also logged to the server console.

## Database Schema

Records are stored in a `waivers` table:

| Column                | Description                                       |
|-----------------------|---------------------------------------------------|
| `id`                  | Auto-increment primary key                        |
| `waiver_number`       | Waiver ID from PDF filename, or composite key     |
| `date_of_issuance`    | Date the waiver was issued                        |
| `responsible_person`  | Named responsible person on the waiver            |
| `company_name`        | Applicant company name                            |
| `waivered_regulation` | FAA regulation(s) waived                          |
| `pdf_url`             | Source URL of the waiver PDF on faa.gov           |
| `pdf_local_path`      | Local path to the downloaded PDF                  |
| `pdf_text`            | Full text extracted from the PDF                  |

A `waivers_fts` FTS5 virtual table mirrors the above for full-text search.

You can query the database directly:

```bash
sqlite3 faa-waiver-app/waivers.db "SELECT waiver_number, company_name, date_of_issuance FROM waivers LIMIT 10;"
```

## Dependencies

| Package          | Purpose                              |
|------------------|--------------------------------------|
| `requests`       | HTTP requests to the FAA website     |
| `beautifulsoup4` | HTML parsing and table scraping      |
| `SQLAlchemy`     | ORM and SQLite database management   |
| `Flask`          | Web app framework                    |
| `pdfplumber`     | PDF text extraction                  |
