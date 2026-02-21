import os
import re
from flask import Flask, render_template, request, abort, send_from_directory, g
from sqlalchemy import text
from database import SessionLocal, Waiver, init_db

app = Flask(__name__)
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
PER_PAGE = 25

SORT_COLUMNS = {
    "waiver_number": Waiver.waiver_number,
    "date": Waiver.date_of_issuance,
    "company": Waiver.company_name,
    "person": Waiver.responsible_person,
    "regulation": Waiver.waivered_regulation,
}


@app.template_filter("basename")
def basename_filter(path):
    return os.path.basename(path) if path else ""


@app.template_filter("clean_waiver_number")
def clean_waiver_number_filter(value):
    if not value:
        return value
    m = re.match(r"(107W-\d{4}-\d+)", value)
    return m.group(1) if m else value


@app.template_filter("clean_person")
def clean_person_filter(value):
    if not value:
        return value
    return re.sub(r"\s*\(pdf\)\s*$", "", value, flags=re.IGNORECASE).strip()


@app.before_request
def open_db():
    g.db = SessionLocal()


@app.teardown_request
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/")
def index():
    date = request.args.get("date", "").strip()
    person = request.args.get("person", "").strip()
    company = request.args.get("company", "").strip()
    regulation = request.args.get("regulation", "").strip()
    sort = request.args.get("sort", "id")
    order = request.args.get("order", "asc")
    page = max(1, request.args.get("page", 1, type=int))

    query = g.db.query(Waiver)
    if date:
        query = query.filter(Waiver.date_of_issuance.ilike(f"%{date}%"))
    if person:
        query = query.filter(Waiver.responsible_person.ilike(f"%{person}%"))
    if company:
        query = query.filter(Waiver.company_name.ilike(f"%{company}%"))
    if regulation:
        query = query.filter(Waiver.waivered_regulation.ilike(f"%{regulation}%"))

    sort_col = SORT_COLUMNS.get(sort, Waiver.id)
    query = query.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    total = query.count()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    waivers = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()

    return render_template(
        "index.html",
        waivers=waivers,
        date=date,
        person=person,
        company=company,
        regulation=regulation,
        sort=sort,
        order=order,
        page=page,
        total=total,
        total_pages=total_pages,
    )


@app.route("/waiver/<int:id>")
def waiver_detail(id):
    waiver = g.db.get(Waiver, id)
    if waiver is None:
        abort(404)
    return render_template("waiver.html", waiver=waiver)


def _snippet(pdf_text, keyword, max_len=300):
    if not pdf_text:
        return ""
    idx = pdf_text.lower().find(keyword.lower())
    if idx == -1:
        text_preview = pdf_text[:max_len]
        return text_preview + ("…" if len(pdf_text) > max_len else "")
    start = max(0, idx - max_len // 2)
    end = min(len(pdf_text), start + max_len)
    snippet = pdf_text[start:end]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(pdf_text) else "")


@app.route("/search")
def search():
    keyword = request.args.get("keyword", "").strip()
    results = []
    error = None
    if keyword:
        try:
            rows = g.db.execute(
                text("""
                    SELECT w.id, w.waiver_number, w.date_of_issuance,
                           w.responsible_person, w.company_name,
                           w.waivered_regulation, w.pdf_url, w.pdf_text
                    FROM waivers_fts
                    JOIN waivers w ON waivers_fts.rowid = w.id
                    WHERE waivers_fts MATCH :kw
                    ORDER BY rank
                """),
                {"kw": keyword},
            ).fetchall()
            for row in rows:
                results.append({
                    "id": row.id,
                    "waiver_number": row.waiver_number,
                    "date_of_issuance": row.date_of_issuance,
                    "responsible_person": row.responsible_person,
                    "company_name": row.company_name,
                    "waivered_regulation": row.waivered_regulation,
                    "pdf_url": row.pdf_url,
                    "snippet": _snippet(row.pdf_text, keyword),
                })
        except Exception as e:
            error = str(e)
    return render_template("search_results.html", results=results, keyword=keyword, error=error)


@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    return send_from_directory(PDF_DIR, filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
