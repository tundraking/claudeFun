import re
from database import SessionLocal, Waiver, migrate_db

# All 50 states + DC
_US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|"
    "MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|"
    "WA|WV|WI|WY|DC"
)

# State abbreviation optionally followed by a ZIP code
STATE_RE = re.compile(rf"\b({_US_STATES})\b(?:[,\s]+\d{{5}}(?:-\d{{4}})?)?")


def _extract_state(pdf_text):
    """Scan the first 15 lines of pdf_text for a US state abbreviation."""
    lines = pdf_text.splitlines()[:15]
    for line in lines:
        m = STATE_RE.search(line)
        if m:
            return m.group(1)
    return None


def parse_states_for_new_waivers():
    """Parse state from waivers that have pdf_text but no state value.

    Creates its own database session so it is safe to call from within a
    Flask request context.  Returns the number of waivers that were
    successfully updated during this call.
    """
    session = SessionLocal()
    try:
        waivers = (
            session.query(Waiver)
            .filter(Waiver.pdf_text.isnot(None), Waiver.state.is_(None))
            .all()
        )
        print(f"[ParseStates] {len(waivers)} waiver(s) without a state.")

        succeeded = 0
        for waiver in waivers:
            state = _extract_state(waiver.pdf_text)
            if state:
                waiver.state = state
                session.commit()
                print(f"[ParseStates] [OK]   {waiver.waiver_number} → {state}")
                succeeded += 1
            else:
                print(f"[ParseStates] [FAIL] {waiver.waiver_number} — no state found")

        return succeeded
    finally:
        session.close()


def run():
    migrate_db()

    session = SessionLocal()
    try:
        waivers = (
            session.query(Waiver)
            .filter(Waiver.pdf_text.isnot(None), Waiver.state.is_(None))
            .all()
        )
        total = len(waivers)
        print(f"Found {total} waiver(s) to parse.")

        succeeded = 0
        failed = 0
        skipped = 0

        for waiver in waivers:
            if not waiver.pdf_text:
                skipped += 1
                continue

            state = _extract_state(waiver.pdf_text)
            if state:
                waiver.state = state
                session.commit()
                print(f"[OK]   {waiver.waiver_number} → {state}")
                succeeded += 1
            else:
                print(f"[FAIL] {waiver.waiver_number} — no state found in first 15 lines")
                failed += 1

        print(
            f"\nDone. {succeeded} succeeded, {failed} failed, {skipped} skipped "
            f"(of {total} total)."
        )
    finally:
        session.close()


if __name__ == "__main__":
    run()
