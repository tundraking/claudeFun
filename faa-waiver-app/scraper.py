import os
import requests
from bs4 import BeautifulSoup
from database import SessionLocal, Waiver, init_db

FAA_URL = "https://www.faa.gov/uas/commercial_operators/part_107_waivers/waivers_issued"
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def make_session():
    """Return a requests.Session with browser-like headers."""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def download_pdf(http_session, pdf_url):
    """Download a PDF to the pdfs/ folder. Returns the local path, or None on failure."""
    os.makedirs(PDF_DIR, exist_ok=True)
    filename = pdf_url.rstrip("/").split("/")[-1]
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    local_path = os.path.join(PDF_DIR, filename)
    if os.path.exists(local_path):
        return local_path
    try:
        response = http_session.get(pdf_url, timeout=30)
        response.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(response.content)
        return local_path
    except requests.RequestException as e:
        print(f"  Warning: could not download {pdf_url}: {e}")
        return None


def _next_page_url(soup, current_url):
    """Return the absolute URL of the next page, or None if this is the last page.

    Handles both Drupal-style pagers (li.pager__item--next a) and any <a>
    whose visible text is 'next' (case-insensitive).
    """
    # Drupal pager: <li class="pager__item--next"><a href="...">
    next_li = soup.find("li", class_=lambda c: c and "next" in c.lower())
    if next_li:
        a = next_li.find("a", href=True)
        if a:
            href = a["href"]
            if href.startswith("http"):
                return href
            from urllib.parse import urljoin
            return urljoin(current_url, href)

    # Generic fallback: any link whose text is "next"
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True).lower() in ("next", "next »", "›", "»"):
            href = a["href"]
            if href.startswith("http"):
                return href
            from urllib.parse import urljoin
            return urljoin(current_url, href)

    return None


def _process_table(soup, existing, session, http, idx_date, idx_person, idx_company, idx_regulation):
    """Parse one page's table and insert new rows. Returns (added, skipped)."""
    table = soup.find("table")
    if not table:
        return 0, 0

    rows = table.find_all("tr")
    added = 0
    skipped = 0

    for row in rows[1:]:  # skip header row
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        def cell_text(idx):
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx].get_text(strip=True)

        date_of_issuance    = cell_text(idx_date)
        responsible_person  = cell_text(idx_person)
        company_name        = cell_text(idx_company)
        waivered_regulation = cell_text(idx_regulation)

        # Find PDF link anywhere in the row
        pdf_url = None
        pdf_local_path = None
        anchor = row.find("a", href=True)
        if anchor:
            href = anchor["href"]
            if href.lower().endswith(".pdf") or "pdf" in href.lower():
                pdf_url = href if href.startswith("http") else f"https://www.faa.gov{href}"

        # Derive waiver number from PDF filename, or fall back to a composite key
        if pdf_url:
            waiver_number = pdf_url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]
        else:
            waiver_number = f"{date_of_issuance}|{company_name}|{responsible_person}"

        if not waiver_number:
            continue

        if waiver_number in existing:
            skipped += 1
            continue

        if pdf_url:
            print(f"  Downloading PDF for {waiver_number}...")
            pdf_local_path = download_pdf(http, pdf_url)

        waiver = Waiver(
            waiver_number=waiver_number,
            date_of_issuance=date_of_issuance,
            responsible_person=responsible_person,
            company_name=company_name,
            waivered_regulation=waivered_regulation,
            pdf_url=pdf_url,
            pdf_local_path=pdf_local_path,
            pdf_text=None,
        )
        session.add(waiver)
        existing.add(waiver_number)
        added += 1

    return added, skipped


def scrape_waivers():
    init_db()
    session = SessionLocal()
    http = make_session()

    try:
        existing = {w.waiver_number for w in session.query(Waiver.waiver_number).all()}
        print(f"Found {len(existing)} existing records in database.")

        # Fetch first page and detect column layout once
        url = FAA_URL
        response = http.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        table = soup.find("table")
        if not table:
            print("Error: no table found on the page.")
            return

        header_row = table.find("tr")
        if not header_row:
            print("Error: table has no rows.")
            return

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        print(f"Detected columns: {headers}")

        def col_index(keywords):
            for i, h in enumerate(headers):
                if any(k in h for k in keywords):
                    return i
            return None

        idx_date       = col_index(["date of issuance"])
        idx_person     = col_index(["responsible person", "person"])
        idx_company    = col_index(["company"])
        idx_regulation = col_index(["regulation", "waivered"])

        total_added = 0
        total_skipped = 0
        page_num = 1

        while True:
            print(f"Processing page {page_num} ({url}) ...")
            added, skipped = _process_table(soup, existing, session, http,
                                            idx_date, idx_person, idx_company, idx_regulation)
            total_added += added
            total_skipped += skipped
            session.commit()
            print(f"  Page {page_num}: +{added} new, {skipped} duplicates "
                  f"(running total: {total_added} added)")

            next_url = _next_page_url(soup, url)
            if not next_url:
                break

            url = next_url
            page_num += 1
            try:
                response = http.get(url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                print(f"Error fetching page {page_num} ({url}): {e}")
                break

        print(f"Done. Added {total_added} new records, skipped {total_skipped} duplicates "
              f"across {page_num} page(s).")
        return total_added

    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    scrape_waivers()
