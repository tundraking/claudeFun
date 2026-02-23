"""
extract_shielding.py — Extract and analyze shielding provisions from FAA waiver PDFs.

SETUP
-----
1. Install Ollama from https://ollama.com and ensure the daemon is running.
2. Pull the default model:
       ollama pull llama3.2:3b

USAGE
-----
Run from the repository root:
    python faa-waiver-app/extract_shielding.py

Optional flags:
    --model mistral:7b   Use a different Ollama model (default: llama3.2:3b)
    --reprocess          Re-run for waivers that already have a shielding_analysis
                         record, overwriting previous results
    --skip-ollama        Extract and save raw blocks/shielding_types only;
                         skip the Ollama call and clear structured_data

DEPENDENCIES
------------
No new packages are required beyond what is already in requirements.txt.
The script uses only the Python standard library plus:
    - requests   (already in requirements.txt)
    - sqlalchemy (already in requirements.txt)
"""
import argparse
import json
import re

import requests
from sqlalchemy import or_

from database import SessionLocal, Waiver, ShieldingAnalysis, init_shielding_table

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:3b"

PROMPT_TEMPLATE = """You are analyzing FAA drone waiver text about shielding provisions.
Below are the raw shielding-related sections extracted from a waiver document:

{raw_blocks}

Return a JSON object with exactly these fields:
- shielding_types: list of shielding category names found (e.g. ["Standard Shielding", "Non-Shielded Operations"])
- provisions: a list of objects, one per shielding type, each with:
  - type: the shielding category name (string)
  - altitude_limits: extracted altitude values and conditions as a text block (string, or null if none found)
  - distance_limits: extracted distance/radius values and conditions as a text block (string, or null if none found)
  - other_conditions: any remaining sub-rule text that does not fit the above categories (string, or null if none)
- summary: a 1-2 sentence plain English summary of all shielding provisions combined

Return only raw JSON with no markdown formatting, no code fences, and no additional explanation."""

# Normalized shielding operation types.  Section headings are matched against
# this list; only sections whose heading contains one of these exact phrases
# (case-insensitive) are kept.
NORMALIZED_TYPES = [
    "Long Range Linear Infrastructure Shielding",
    "Electrical Transmission Line Shielded Operations",
    "Closed Access Construction Site Shielding",
    "Buried Right of Way Non-Shielded Operations",
    "Critical Infrastructure Shielding",
    "Closed Access Site Shielding",
    "Standard Shielding",
    "Public Safety Organization Shielded Operations",
]

NORMALIZED_TYPE_PATTERNS = [
    (t, re.compile(re.escape(t), re.IGNORECASE)) for t in NORMALIZED_TYPES
]


def extract_shielding_blocks(pdf_text):
    """Split pdf_text at top-level numbered sections and return those whose heading
    matches a normalized shielding type.

    Only the first two lines of each section (the heading zone) are tested so that
    sections which merely mention a shielding term in their body are not captured.
    The stored type name is always the canonical normalized form, not the raw heading.

    Returns:
        (blocks, types) where blocks is a list of raw text strings and types is a list
        of normalized type names matched in those blocks.
    """
    # Split at lines that start a new top-level numbered section (e.g. "11. ").
    # The lookahead keeps the section number at the start of each part.
    parts = re.split(r"(?m)(?=^\d+\.)", pdf_text)

    shielding_blocks = []
    shielding_types = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Test only the heading zone (first two lines).
        heading_zone = "\n".join(part.split("\n")[:2])

        matched_type = None
        for type_name, pattern in NORMALIZED_TYPE_PATTERNS:
            if pattern.search(heading_zone):
                matched_type = type_name
                break

        if matched_type is None:
            continue

        shielding_blocks.append(part)
        shielding_types.append(matched_type)

    return shielding_blocks, shielding_types


def parse_ollama_response(response_text):
    """Return a parsed JSON dict from the Ollama response, or None if unparseable.

    Tries a direct parse first, then falls back to finding a JSON object inside
    the response text (in case the model added surrounding prose despite instructions).
    """
    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def call_ollama(raw_blocks_text, model):
    """Send raw shielding blocks to Ollama and return the model's response string.

    Raises RuntimeError on network or HTTP errors.
    """
    prompt = PROMPT_TEMPLATE.format(raw_blocks=raw_blocks_text)
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["response"]
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}")


def process_waiver(session, waiver, model, reprocess, use_ollama):
    existing = session.query(ShieldingAnalysis).filter_by(waiver_id=waiver.id).first()
    if existing and not reprocess:
        print(f"    [SKIP] Already processed (use --reprocess to reprocess)")
        return

    blocks, types = extract_shielding_blocks(waiver.pdf_text)
    if not blocks:
        print(f"    [WARN] No normalized shielding sections found in pdf_text — skipping")
        return

    raw_blocks_text = "\n\n".join(blocks)
    shielding_types_json = json.dumps(types)
    print(f"    Extracted {len(blocks)} block(s): {types}")

    # Persist raw extraction and clear any prior Ollama output.
    if existing:
        record = existing
    else:
        record = ShieldingAnalysis(waiver_id=waiver.id)
        session.add(record)

    record.waiver_number = waiver.waiver_number
    record.raw_blocks = raw_blocks_text
    record.shielding_types = shielding_types_json
    record.structured_data = None
    record.ollama_processed = False
    session.commit()

    if not use_ollama:
        print(f"    [OK] Raw extraction saved (Ollama skipped)")
        return

    # Call Ollama and persist structured output.
    print(f"    Sending to Ollama ({model})...")
    try:
        response_text = call_ollama(raw_blocks_text, model)
        parsed = parse_ollama_response(response_text)
        if parsed is not None:
            record.structured_data = json.dumps(parsed)
            record.ollama_processed = True
            session.commit()
            print(f"    [OK] Ollama succeeded")
        else:
            record.structured_data = response_text
            session.commit()
            print(f"    [WARN] Ollama response was not valid JSON; raw output stored")
    except RuntimeError as e:
        session.rollback()
        print(f"    [FAIL] {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and analyze shielding provisions from FAA waiver PDFs"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Reprocess waivers that already have a shielding_analysis record",
    )
    parser.add_argument(
        "--skip-ollama",
        action="store_true",
        help="Save raw blocks and shielding_types only; skip Ollama and clear structured_data",
    )
    args = parser.parse_args()

    init_shielding_table()

    session = SessionLocal()
    try:
        waivers = (
            session.query(Waiver)
            .filter(Waiver.pdf_text != None)
            .filter(Waiver.pdf_text != "")
            .filter(
                or_(
                    Waiver.pdf_text.ilike("%shield%"),
                    Waiver.pdf_text.ilike("%shielded%"),
                    Waiver.pdf_text.ilike("%shielding%"),
                )
            )
            .all()
        )
    except Exception as e:
        print(f"Database query failed: {e}")
        session.close()
        return

    if not waivers:
        print("No waivers found with shielding-related content.")
        session.close()
        return

    use_ollama = not args.skip_ollama

    print(f"Found {len(waivers)} waiver(s) with shielding content.")
    if use_ollama:
        print(f"Using Ollama model: {args.model}")
    else:
        print("--skip-ollama set: raw extraction only, structured_data will be cleared.")
    if args.reprocess:
        print("--reprocess flag set: existing records will be overwritten.")
    print()

    for i, waiver in enumerate(waivers, 1):
        wnum = waiver.waiver_number or f"id={waiver.id}"
        print(f"[{i}/{len(waivers)}] Waiver {wnum}")
        try:
            process_waiver(session, waiver, args.model, args.reprocess, use_ollama)
        except Exception as e:
            session.rollback()
            print(f"    [ERROR] Unexpected error: {e}")

    session.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
