from sqlalchemy import create_engine, Column, Integer, String, Text, text
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


def init_db():
    Base.metadata.create_all(bind=engine)


def setup_fts():
    with engine.connect() as conn:
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
        conn.commit()


def populate_fts():
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO waivers_fts(waivers_fts) VALUES('rebuild')"))
        conn.commit()


if __name__ == "__main__":
    setup_fts()
    populate_fts()
