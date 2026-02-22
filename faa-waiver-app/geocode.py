import re
import time
import requests
from database import SessionLocal, Waiver, migrate_db

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "faa-waiver-geocoder/1.0 (FAA Part 107 waiver location research tool)"
}
SLEEP_SECONDS = 1.1

# Matches the "ADDRESS –" label in FAA waiver PDFs (em-dash, en-dash, hyphen, or colon)
ADDRESS_LABEL_RE = re.compile(r"^ADDRESS\s*[–—\-:]?\s*(.*)", re.IGNORECASE)

# End of an address block: a new labeled field (e.g. "NAME –") or a section keyword
FIELD_LABEL_RE = re.compile(r"^[A-Z][A-Z\s]{2,}[–—\-:]", re.IGNORECASE)
SECTION_STOP_RE = re.compile(
    r"\b(CONDITIONS?|LIMITATIONS?|AUTHORIZED\s+AREA|SECTION|REQUIREMENTS?)\b",
    re.IGNORECASE,
)

# Looks like a US ZIP code
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def extract_address(pdf_text):
    """Extract a postal address from pdf_text by finding the ADDRESS label.

    Scans for a line starting with 'ADDRESS' (followed by an optional dash/colon),
    then collects subsequent lines until a blank line or another labeled field.
    Returns a comma-joined string suitable for Nominatim, or None if not found.
    """
    lines = pdf_text.splitlines()

    for i, line in enumerate(lines):
        m = ADDRESS_LABEL_RE.match(line.strip())
        if m is None:
            continue

        collected = []
        # The rest of the ADDRESS label line may itself contain address text
        inline = m.group(1).strip()
        if inline:
            collected.append(inline)
            if ZIP_RE.search(inline):
                # Entire address was on one line — done
                return ", ".join(collected) + ", USA"

        # Collect subsequent lines until blank, next labeled field, section keyword,
        # or we've already seen a ZIP code (which ends any US postal address).
        for follow in lines[i + 1:]:
            stripped = follow.strip()
            if not stripped:
                break
            if FIELD_LABEL_RE.match(stripped) or SECTION_STOP_RE.search(stripped):
                break
            collected.append(stripped)
            if ZIP_RE.search(stripped):
                break  # ZIP code marks the end of the address block

        if not collected:
            return None

        # Build the query: prefer the line(s) that contain a ZIP for tighter geocoding,
        # but include all collected lines so Nominatim has city/state context too.
        return ", ".join(collected) + ", USA"

    return None


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
