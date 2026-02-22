import os
import re
from flask import Flask, render_template, request, abort, send_from_directory, g, jsonify
from sqlalchemy import text
from database import SessionLocal, Waiver, ShieldingAnalysis, init_db, migrate_db, setup_fts, populate_fts
from scraper import scrape_waivers
from extract_text import extract_text_from_pdfs
from geocode import geocode_new_waivers
from parse_states import parse_states_for_new_waivers

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


_FOOTER_LINE = re.compile(
    r"^\s*("
    r"page\s+\d+\s+of\s+\d+"          # "Page 1 of 5"
    r"|page\s+\d+"                      # "Page 1"
    r"|\d+"                             # bare page number
    r"|federal\s+aviation\s+administration"  # repeated header
    r"|www\.faa\.gov"                   # URL footers
    r")\s*$",
    re.IGNORECASE,
)

_CERT_HEADER = re.compile(
    r"^\s*certificate\s+of\s+waiver\s+number\s+107W-\d{4}-\d+\s*$",
    re.IGNORECASE,
)


@app.template_filter("clean_pdf_text")
def clean_pdf_text_filter(value):
    """Clean up PDF-extracted text for display only; original data is unchanged."""
    if not value:
        return value
    lines = value.splitlines()
    seen_cert_header = False
    cleaned = []
    for line in lines:
        if _CERT_HEADER.match(line):
            if not seen_cert_header:
                seen_cert_header = True
                cleaned.append(line)   # keep the first occurrence
            # drop all subsequent occurrences
        elif not _FOOTER_LINE.match(line):
            cleaned.append(line)
    # Collapse runs of more than one blank line into a single blank line
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned))
    return result.strip()


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
    state = request.args.get("state", "").strip()
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
    if state:
        query = query.filter(Waiver.state.ilike(f"%{state}%"))

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
        state=state,
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


@app.route("/waiver/<waiver_number>")
def waiver_by_number(waiver_number):
    waiver = g.db.query(Waiver).filter(
        Waiver.waiver_number.ilike(f"{waiver_number}%")
    ).first()
    if waiver is None:
        abort(404)
    return render_template("waiver_detail.html", waiver=waiver)


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


@app.route("/map")
def map_view():
    return render_template("map.html")


@app.route("/api/waivers/geo")
def waivers_geo():
    rows = (
        g.db.query(
            Waiver.waiver_number,
            Waiver.company_name,
            Waiver.responsible_person,
            Waiver.latitude,
            Waiver.longitude,
        )
        .filter(Waiver.latitude.isnot(None), Waiver.longitude.isnot(None))
        .all()
    )
    return jsonify([
        {
            "waiver_number": r.waiver_number,
            "company_name": r.company_name,
            "responsible_person": r.responsible_person,
            "latitude": r.latitude,
            "longitude": r.longitude,
        }
        for r in rows
    ])


@app.route("/analysis")
def analysis():
    waivers = (
        g.db.query(Waiver)
        .filter(Waiver.ai_processed == True)
        .order_by(Waiver.date_of_issuance.desc())
        .all()
    )
    return render_template("analysis.html", waivers=waivers)


def _parse_date_ymd(ymd):
    """Convert 'YYYY-MM-DD' to a datetime.date, or None on failure."""
    from datetime import datetime
    try:
        return datetime.strptime(ymd, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_issuance_date(raw):
    """Convert a human-readable date string (e.g. 'January 15, 2020') to date."""
    from datetime import datetime
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


@app.route("/api/waivers/by-state")
def waivers_by_state():
    from sqlalchemy import func
    date_from = _parse_date_ymd(request.args.get("date_from", "").strip())
    date_to = _parse_date_ymd(request.args.get("date_to", "").strip())
    regulation = request.args.get("regulation", "").strip()
    regulations = [r.strip() for r in regulation.split(",") if r.strip()] if regulation else []

    # Pull every waiver that has a state; filter in Python because
    # date_of_issuance is stored as a human-readable string.
    query = (
        g.db.query(Waiver.state, Waiver.date_of_issuance, Waiver.waivered_regulation)
        .filter(Waiver.state.isnot(None))
    )
    if regulations:
        from sqlalchemy import or_
        query = query.filter(or_(*(Waiver.waivered_regulation.ilike(f"%{r}%") for r in regulations)))

    from_year = date_from.year if date_from else None
    to_year = date_to.year if date_to else None

    counts = {}
    for row in query.all():
        if from_year or to_year:
            m = re.search(r'\b((?:19|20)\d{2})\b', row.date_of_issuance or '')
            if not m:
                continue
            year = int(m.group(1))
            if from_year and year < from_year:
                continue
            if to_year and year > to_year:
                continue
        counts[row.state] = counts.get(row.state, 0) + 1

    result = [{"state": s, "count": c} for s, c in sorted(counts.items())]
    return jsonify(result)


@app.route("/api/waivers/meta")
def waivers_meta():
    from sqlalchemy import distinct

    # date_of_issuance is stored as a human-readable string, so parse in Python
    # to find the true chronological min and max.
    date_rows = (
        g.db.query(distinct(Waiver.date_of_issuance))
        .filter(Waiver.date_of_issuance.isnot(None))
        .all()
    )
    years = set()
    for (raw,) in date_rows:
        if raw:
            m = re.search(r'\b((?:19|20)\d{2})\b', raw)
            if m:
                years.add(int(m.group(1)))

    date_range = {"min": None, "max": None}
    if years:
        date_range["min"] = str(min(years))
        date_range["max"] = str(max(years))

    reg_rows = (
        g.db.query(distinct(Waiver.waivered_regulation))
        .filter(Waiver.waivered_regulation.isnot(None))
        .all()
    )
    reg_codes = set()
    for (raw,) in reg_rows:
        if raw:
            for part in raw.split(","):
                part = part.strip()
                if part:
                    reg_codes.add(part)
    regulations = sorted(reg_codes)

    return jsonify({"date_range": date_range, "regulations": regulations})


@app.route("/shielding")
def shielding():
    import json as _json
    records = (
        g.db.query(ShieldingAnalysis)
        .order_by(ShieldingAnalysis.waiver_number)
        .all()
    )
    rows = []
    for rec in records:
        parsed = None
        if rec.structured_data:
            try:
                parsed = _json.loads(rec.structured_data)
            except (ValueError, TypeError):
                parsed = None

        shielding_types = []
        altitude_limits = []
        distance_limits = []
        if parsed and isinstance(parsed, dict):
            shielding_types = parsed.get("shielding_types") or []
            for prov in (parsed.get("provisions") or []):
                if not isinstance(prov, dict):
                    continue
                alt = prov.get("altitude_limits")
                dist = prov.get("distance_limits")
                if alt:
                    altitude_limits.append(alt)
                if dist:
                    distance_limits.append(dist)

        rows.append({
            "waiver_number": rec.waiver_number,
            "shielding_types": shielding_types,
            "altitude_limits": altitude_limits,
            "distance_limits": distance_limits,
            "raw_blocks": rec.raw_blocks or "",
            "structured_json": _json.dumps(parsed, indent=2) if parsed else (rec.structured_data or ""),
            "ollama_processed": rec.ollama_processed,
        })
    return render_template("shielding.html", rows=rows)


@app.route("/refresh", methods=["POST"])
def refresh():
    print("[Refresh] Step 1: Scraping for new waivers from FAA table...")
    new_waivers = scrape_waivers()

    print("[Refresh] Step 2: Extracting text from new PDFs...")
    pdfs_processed = extract_text_from_pdfs()

    print("[Refresh] Step 3: Rebuilding FTS index...")
    populate_fts()

    print("[Refresh] Step 4: Geocoding new waivers...")
    geocoded = geocode_new_waivers()

    print("[Refresh] Step 5: Parsing states for new waivers...")
    states_parsed = parse_states_for_new_waivers()

    print(f"[Refresh] Done. {new_waivers} new waiver(s) added, {pdfs_processed} PDF(s) processed, {geocoded} address(es) geocoded, {states_parsed} state(s) parsed.")
    return jsonify({"success": True, "new_waivers": new_waivers, "pdfs_processed": pdfs_processed, "geocoded": geocoded, "states_parsed": states_parsed})


@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    return send_from_directory(PDF_DIR, filename)


if __name__ == "__main__":
    init_db()
    migrate_db()
    setup_fts()
    app.run(debug=True)
