import os
from dotenv import load_dotenv
import anthropic
from database import SessionLocal, Waiver

load_dotenv()

PROMPT_TEMPLATE = """Read the following FAA drone waiver text and return a JSON object with these fields:

- ai_summary: a 2-3 sentence plain-English summary of what the waiver allows
- max_altitude: integer altitude in feet, or null if not specified
- remote_operations: true if the waiver covers remote/BVLOS operations, false if not, null if unclear
- docking_station: true if a docking station is involved, false if not, null if unclear
- visibility_minimum: string describing the minimum visibility requirement, or null if not specified
- cloud_clearance: string describing the cloud clearance requirement, or null if not specified
- location_based: true if the waiver is restricted to specific locations, false if it is general, null if unclear
- specific_locations: string describing the specific locations covered, or null if not location-restricted

Return only raw JSON with no markdown formatting, no code fences, and no additional explanation.

Waiver text:
{pdf_text}"""


def main():
    session = SessionLocal()
    try:
        waivers = (
            session.query(Waiver)
            .filter(Waiver.ai_processed == False)
            .filter(Waiver.pdf_text != None)
            .filter(Waiver.pdf_text != "")
            .all()
        )
    finally:
        session.close()

    if not waivers:
        print("No unprocessed waivers found.")
        return

    print(f"Found {len(waivers)} unprocessed waiver(s). Building batch...")

    requests = [
        {
            "custom_id": str(waiver.id),
            "params": {
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": PROMPT_TEMPLATE.format(pdf_text=waiver.pdf_text),
                    }
                ],
            },
        }
        for waiver in waivers
    ]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    batch = client.beta.messages.batches.create(requests=requests)

    print(f"Batch submitted.")
    print(f"  Batch ID: {batch.id}")
    print(f"  Status:   {batch.processing_status}")

    with open("batch_id.txt", "w") as f:
        f.write(batch.id)

    print(f"Batch ID saved to batch_id.txt")


if __name__ == "__main__":
    main()
