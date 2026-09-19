"""開発用の初期マスタデータ投入。 `python -m app.seed` で実行する。"""
from .database import Base, SessionLocal, engine
from .models import Company, Organization


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Company).count() > 0:
            print("Companies already seeded, skipping.")
            return

        jp = Company(code="JP001", name="Example Japan K.K.", active=True)
        us = Company(code="US001", name="Example US Inc.", active=True)
        db.add_all([jp, us])
        db.flush()

        db.add_all(
            [
                Organization(code="SALES01", name="Sales Division", company_id=jp.id, active=True),
                Organization(code="HR01", name="Human Resources", company_id=jp.id, active=True),
                Organization(code="HR01", name="Human Resources", company_id=us.id, active=True),
                Organization(code="ENG01", name="Engineering", company_id=us.id, active=True),
            ]
        )
        db.commit()
        print("Seeded companies JP001, US001 and sample organizations.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
