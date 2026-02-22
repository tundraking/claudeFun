from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///waivers.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Waiver(Base):
    __tablename__ = "waivers"

    id = Column(Integer, primary_key=True)
    waiver_number = Column(String)
    date_of_issuance = Column(String)
    responsible_person = Column(String)
    company_name = Column(String)
    waivered_regulation = Column(String)
    pdf_url = Column(String)
    pdf_local_path = Column(String)
    pdf_text = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    max_altitude = Column(Integer, nullable=True)
    remote_operations = Column(Boolean, nullable=True)
    docking_station = Column(Boolean, nullable=True)
    visibility_minimum = Column(Text, nullable=True)
    cloud_clearance = Column(Text, nullable=True)
    location_based = Column(Boolean, nullable=True)
    specific_locations = Column(Text, nullable=True)
    ai_processed = Column(Boolean, default=False, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    state = Column(String, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)


def setup_fts():
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS waivers_fts
            USING fts5(
                waiver_number,
                responsible_person,
                company_name,
                waivered_regulation,
                pdf_text,
                content='waivers',
                content_rowid='id'
            )
            """
        ))


def populate_fts():
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO waivers_fts(waivers_fts) VALUES('rebuild')"))


def migrate_db():
    new_columns = [
        ("ai_summary", "TEXT"),
        ("max_altitude", "INTEGER"),
        ("remote_operations", "BOOLEAN"),
        ("docking_station", "BOOLEAN"),
        ("visibility_minimum", "TEXT"),
        ("cloud_clearance", "TEXT"),
        ("location_based", "BOOLEAN"),
        ("specific_locations", "TEXT"),
        ("ai_processed", "BOOLEAN DEFAULT 0"),
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("state", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE waivers ADD COLUMN {col_name} {col_type}"))
            print(f"Added column: {col_name}")
        except Exception:
            print(f"Column already exists (skipped): {col_name}")


if __name__ == "__main__":
    init_db()
    migrate_db()
    setup_fts()
    populate_fts()
