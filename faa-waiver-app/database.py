from sqlalchemy import create_engine, Column, Integer, String, Text
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
