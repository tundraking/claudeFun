import re
import time
import requests
from database import SessionLocal, Waiver, migrate_db

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "faa-waiver-geocoder/1.0 (FAA Part 107 waiver location research tool)"
}
SLEEP_SECONDS = 1.1

# Only stop on lines that are strongly section-header-like.
# Require specific known keywords — not just any all-caps text, since company
# names, state names, and document titles are also all-caps.
SECTION_KEYWORDS_RE = re.compile(
    r"\b(CONDITIONS?|LIMITATIONS?|AUTHORIZED\s+AREA|OPERATIONAL|REQUIREMENTS?|SECTION)\b",
    re.IGNORECASE,
)

# A lone number or numbered-section like "1." or "1)" — classic section header
LONE_NUMBER_RE = re.compile(r"^\d+[\.\)]?\s*$")

# Looks like a US ZIP code — a good indicator of an address line
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")

# Looks like a street address — starts with digits followed by a word
STREET_RE = re.compile(r"^\d+\s+\w")

# Known boilerplate titles at the top of FAA waiver PDFs to skip rather than stop on
BOILERPLATE_RE = re.compile(
    r"^\s*(certificate\s+of\s+(waiver|authorization)|faa\s+form\s+\d|"
    r"part\s+107|unmanned\s+aircraft|uas\b)",
    re.IGNORECASE,
)


def is_section_header(line):
    """Return True if the line is a section boundary, not part of the address block."""
    if LONE_NUMBER_RE.match(line):
        return True
    if SECTION_KEYWORDS_RE.search(line):
        return True
    return False


def extract_address(pdf_text):
    """Extract an address from the first 15 lines of pdf_text.

    Skips line 0 (waiver number header) and known boilerplate titles, then
    collects non-empty lines until a section header is detected. Returns the
    most address-like subset of collected lines joined with commas, or None.
    """
    lines = pdf_text.splitlines()[:15]
    collected = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if is_section_header(stripped):
            break
        # Skip known FAA boilerplate document titles rather than stopping on them
        if BOILERPLATE_RE.match(stripped):
            continue
        collected.append(stripped)

    if not collected:
        return None

    # Prefer lines that look like actual postal address components (street or ZIP).
    # This avoids sending the person's name or company name to Nominatim.
    address_lines = [l for l in collected if ZIP_RE.search(l) or STREET_RE.match(l)]
    query_lines = address_lines if address_lines else collected

    return ", ".join(query_lines) + ", USA"


def geocode_address(address):
    """Query Nominatim for the address. Returns (lat, lon) floats or (None, None)."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"format": "json", "q": address},
            headers=NOMINATIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"  Nominatim error: {e}")
    return None, None


def run():
    migrate_db()

    session = SessionLocal()
    try:
        waivers = (
            session.query(Waiver)
            .filter(Waiver.pdf_text.isnot(None), Waiver.latitude.is_(None))
            .all()
        )
        total = len(waivers)
        print(f"Found {total} waiver(s) to geocode.")

        succeeded = 0
        failed = 0
        skipped = 0

        for waiver in waivers:
            address = extract_address(waiver.pdf_text)
            if not address:
                # Print first 5 lines to help diagnose why extraction failed
                preview = waiver.pdf_text.splitlines()[:5]
                print(f"[SKIP] {waiver.waiver_number} — no address extracted")
                for i, l in enumerate(preview):
                    print(f"       line {i}: {l!r}")
                skipped += 1
                continue

            lat, lon = geocode_address(address)
            if lat is not None:
                waiver.latitude = lat
                waiver.longitude = lon
                session.commit()
                print(f"[OK]   {waiver.waiver_number} → {lat}, {lon}")
                succeeded += 1
            else:
                print(f"[FAIL] {waiver.waiver_number} — no results for: {address!r}")
                failed += 1

            time.sleep(SLEEP_SECONDS)

        print(
            f"\nDone. {succeeded} succeeded, {failed} failed, {skipped} skipped "
            f"(of {total} total)."
        )
    finally:
        session.close()


if __name__ == "__main__":
    run()
