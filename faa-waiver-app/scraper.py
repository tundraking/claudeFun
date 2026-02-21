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


def scrape_waivers():
    init_db()
    session = SessionLocal()
    http = make_session()

    try:
        existing = {w.waiver_number for w in session.query(Waiver.waiver_number).all()}
        print(f"Found {len(existing)} existing records in database.")

        response = http.get(FAA_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        table = soup.find("table")
        if not table:
            print("Error: no table found on the page.")
            return

        rows = table.find_all("tr")
        # Detect column order from header row
        header_row = rows[0] if rows else None
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

        idx_waiver     = col_index(["waiver number", "waiver no", "waiver#"])
        idx_date       = col_index(["date"])
        idx_person     = col_index(["responsible person", "person"])
        idx_company    = col_index(["company"])
        idx_regulation = col_index(["regulation", "waivered"])

        added = 0
        skipped = 0

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            def cell_text(idx):
                if idx is None or idx >= len(cells):
                    return ""
                return cells[idx].get_text(strip=True)

            waiver_number     = cell_text(idx_waiver)
            date_of_issuance  = cell_text(idx_date)
            responsible_person = cell_text(idx_person)
            company_name      = cell_text(idx_company)
            waivered_regulation = cell_text(idx_regulation)

            if not waiver_number:
                continue

            if waiver_number in existing:
                skipped += 1
                continue

            # Look for a PDF link in the waiver number cell (or anywhere in the row)
            pdf_url = None
            pdf_local_path = None
            link_cell = cells[idx_waiver] if idx_waiver is not None else None
            anchor = None
            if link_cell:
                anchor = link_cell.find("a", href=True)
            if not anchor:
                anchor = row.find("a", href=True)
            if anchor:
                href = anchor["href"]
                if href.lower().endswith(".pdf") or "pdf" in href.lower():
                    pdf_url = href if href.startswith("http") else f"https://www.faa.gov{href}"
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

        session.commit()
        print(f"Done. Added {added} new records, skipped {skipped} duplicates.")

    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    scrape_waivers()
