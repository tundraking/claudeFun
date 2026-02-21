import os
import pdfplumber
from database import SessionLocal, Waiver

PDFS_DIR = os.path.join(os.path.dirname(__file__), "pdfs")


def extract_text_from_pdfs():
    session = SessionLocal()
    try:
        pdf_files = [f for f in os.listdir(PDFS_DIR) if f.lower().endswith(".pdf")]

        if not pdf_files:
            print("No PDF files found in pdfs/ folder.")
            return

        for filename in pdf_files:
            local_path = os.path.join(PDFS_DIR, filename)
            record = session.query(Waiver).filter(Waiver.pdf_local_path == local_path).first()

            if record is None:
                print(f"[SKIP] No matching record for {filename}")
                continue

            pdf_path = os.path.join(PDFS_DIR, filename)
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    pages_text = [page.extract_text() or "" for page in pdf.pages]
                extracted_text = "\n".join(pages_text).strip()
                record.pdf_text = extracted_text
                session.commit()
                print(f"[OK] Extracted text from {filename} ({len(extracted_text)} chars)")
            except Exception as e:
                print(f"[FAIL] Could not extract text from {filename}: {e}")
                session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    extract_text_from_pdfs()
