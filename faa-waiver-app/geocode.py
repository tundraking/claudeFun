import re
import time
import requests
from database import SessionLocal, Waiver, migrate_db

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "faa-waiver-geocoder/1.0 (FAA Part 107 waiver location research tool)"
}
SLEEP_SECONDS = 1.1

SECTION_HEADER_RE = re.compile(
    r"^(?:[A-Z][A-Z\s]{2,}|.*\b(?:CONDITION|WAIVER|SECTION|FAA)\b|\d+)$"
)


def extract_address(pdf_text):
    """Extract an address from the first 15 lines of pdf_text.

    Skips line 0 (waiver number header), then collects non-empty lines until
    hitting a line that looks like a section header. Returns a comma-joined
    string, or None if nothing was collected.
    """
    lines = pdf_text.splitlines()[:15]
    collected = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if SECTION_HEADER_RE.match(stripped):
            break
        collected.append(stripped)
    return ", ".join(collected) if collected else None


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
                print(f"[SKIP] {waiver.waiver_number} — no address extracted")
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
