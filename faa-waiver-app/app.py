import os
from flask import Flask, render_template, request, abort, send_from_directory, g
from database import SessionLocal, Waiver, init_db

app = Flask(__name__)
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
PER_PAGE = 25


@app.template_filter("basename")
def basename_filter(path):
    return os.path.basename(path) if path else ""


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
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    query = g.db.query(Waiver)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            Waiver.company_name.ilike(pattern) | Waiver.responsible_person.ilike(pattern)
        )
    total = query.count()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    waivers = (
        query.order_by(Waiver.id)
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
        .all()
    )
    return render_template(
        "index.html",
        waivers=waivers,
        q=q,
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


@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    return send_from_directory(PDF_DIR, filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
