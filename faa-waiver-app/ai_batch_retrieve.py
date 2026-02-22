import json
import os

from dotenv import load_dotenv
import anthropic

from database import SessionLocal, Waiver

load_dotenv()


def main():
    # Read batch ID
    try:
        with open("batch_id.txt") as f:
            batch_id = f.read().strip()
    except FileNotFoundError:
        print("Error: batch_id.txt not found. Run ai_batch_submit.py first.")
        return

    if not batch_id:
        print("Error: batch_id.txt is empty.")
        return

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Check batch status
    batch = client.beta.messages.batches.retrieve(batch_id)

    if batch.processing_status != "ended":
        print(f"Batch is not ready yet. Current status: {batch.processing_status}")
        print("Try again later.")
        return

    print(f"Batch {batch_id} has ended. Processing results...")
    print(f"  Succeeded: {batch.request_counts.succeeded}")
    print(f"  Errored:   {batch.request_counts.errored}")
    print(f"  Expired:   {batch.request_counts.expired}")
    print()

    session = SessionLocal()
    success_count = 0
    fail_count = 0

    try:
        for result in client.beta.messages.batches.results(batch_id):
            waiver_id = int(result.custom_id)

            if result.result.type != "succeeded":
                print(f"Warning: result for waiver {waiver_id} has status '{result.result.type}', skipping.")
                fail_count += 1
                continue

            raw_text = result.result.message.content[0].text

            try:
                data = json.loads(raw_text)
            except (json.JSONDecodeError, IndexError, AttributeError) as e:
                print(f"Warning: could not parse JSON for waiver {waiver_id}: {e}")
                fail_count += 1
                continue

            waiver = session.get(Waiver, waiver_id)
            if waiver is None:
                print(f"Warning: no waiver found with id={waiver_id}, skipping.")
                fail_count += 1
                continue

            waiver.ai_summary = data.get("ai_summary")
            waiver.max_altitude = data.get("max_altitude")
            waiver.remote_operations = data.get("remote_operations")
            waiver.docking_station = data.get("docking_station")
            waiver.visibility_minimum = data.get("visibility_minimum")
            waiver.cloud_clearance = data.get("cloud_clearance")
            waiver.location_based = data.get("location_based")
            waiver.specific_locations = data.get("specific_locations")
            waiver.ai_processed = True

            success_count += 1

        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error during database update: {e}")
        raise
    finally:
        session.close()

    print(f"Done. Successfully processed: {success_count}  Failed/skipped: {fail_count}")


if __name__ == "__main__":
    main()
