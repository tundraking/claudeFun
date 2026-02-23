"""
extract_shielding_csv.py — Scan FAA waiver pdf_text for shielding type mentions
and export a CSV summary.

USAGE
-----
Run from the faa-waiver-app/ directory:
    python extract_shielding_csv.py

OUTPUT
------
shielding_export.csv (written to the faa-waiver-app/ directory)

DATABASE_URL: sqlite:///waivers.db
"""

import csv
import re
from collections import Counter

from sqlalchemy import text

from database import engine

OUTPUT_CSV = "shielding_export.csv"

# Order matters: more specific phrases must come before shorter overlapping ones
# so that a line matching "Non-Shielded Operations with Visual Observers" is not
# also flagged as matching the shorter "Non-Shielded Operations".
KNOWN_TYPES = [
    "Non-Shielded Operations with Visual Observers",
    "Beyond Visual Line of Sight Non-Critical Infrastructure Shielding",
    "Long Range Linear Infrastructure Shielding",
    "Electrical Transmission Line Shielded Operations",
    "Closed Access Construction Site Shielding",
    "Public Safety Organization Shielded Operations",
    "Buried Right of Way Non-Shielded Operations",
    "Critical Infrastructure Shielding",
    "Closed Access Site Shielding",
    "Standard Shielding",
    "Non-Shielded Operations",
]

KNOWN_PATTERNS = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in KNOWN_TYPES]

# Matches any word starting with "shield" (shield, shielded, shielding, shields …)
SHIELD_RE = re.compile(r"\bshield\w*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Per-waiver analysis helpers
# ---------------------------------------------------------------------------

def find_known_types(pdf_text: str) -> list[str]:
    """Return known shielding types present in pdf_text, in definition order."""
    return [name for name, pat in KNOWN_PATTERNS if pat.search(pdf_text)]


def find_unknown_variants(pdf_text: str) -> list[str]:
    """Return deduplicated lines that contain a shield word but match no known type.

    Each line is included verbatim (stripped) so reviewers can inspect the raw text.
    """
    unknowns: list[str] = []
    seen: set[str] = set()

    for raw_line in pdf_text.splitlines():
        line = raw_line.strip()
        if not line or not SHIELD_RE.search(line):
            continue
        if any(pat.search(line) for _, pat in KNOWN_PATTERNS):
            continue
        key = line.lower()
        if key not in seen:
            seen.add(key)
            unknowns.append(line)

    return unknowns


def count_shield_mentions(pdf_text: str) -> int:
    """Count every occurrence of a shield-root word in the document."""
    return len(SHIELD_RE.findall(pdf_text))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Query: all waivers whose pdf_text contains the word "shield"
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT waiver_number, date_of_issuance, company_name, pdf_text "
                    "FROM waivers "
                    "WHERE pdf_text LIKE '%shield%'"
                )
            ).fetchall()
    except Exception as exc:
        print(f"Database query failed: {exc}")
        return

    total_scanned = len(rows)
    print(f"Waivers returned by SQL LIKE query: {total_scanned}")

    # 2. Analyse each waiver
    csv_rows: list[dict] = []
    type_frequency: Counter = Counter()

    for waiver_number, date_of_issuance, company_name, pdf_text in rows:
        pdf_text = pdf_text or ""

        known_found = find_known_types(pdf_text)
        unknown_found = find_unknown_variants(pdf_text)
        total_mentions = count_shield_mentions(pdf_text)

        # Only include waivers with at least one match in either category
        if not known_found and not unknown_found:
            continue

        type_frequency.update(known_found)

        csv_rows.append(
            {
                "waiver_number": waiver_number or "",
                "date_of_issuance": date_of_issuance or "",
                "company_name": company_name or "",
                "known_types_found": "|".join(known_found),
                "unknown_variants_found": "|".join(unknown_found),
                "total_shielding_mentions": total_mentions,
            }
        )

    # 3. Write CSV
    fieldnames = [
        "waiver_number",
        "date_of_issuance",
        "company_name",
        "known_types_found",
        "unknown_variants_found",
        "total_shielding_mentions",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"CSV written → {OUTPUT_CSV}  ({len(csv_rows)} row(s))")

    # 4. Summary
    print("\n--- Summary ---")
    print(f"Total waivers scanned:            {total_scanned}")
    print(f"Total with any shielding mention: {len(csv_rows)}")
    print("\nKnown shielding type frequency (across all waivers):")
    if type_frequency:
        for name in KNOWN_TYPES:
            count = type_frequency.get(name, 0)
            if count:
                print(f"  {count:4d}  {name}")
    else:
        print("  (none found)")


if __name__ == "__main__":
    main()
