import os
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, get_db
from app.main import app
from app.models import Company, Organization
from app.security import CurrentUser, create_access_token


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seed_companies(db_session):
    jp = Company(code="JP001", name="Example Japan K.K.", active=True)
    db_session.add(jp)
    db_session.flush()
    db_session.add(Organization(code="SALES01", name="Sales", company_id=jp.id, active=True))
    db_session.commit()
    return jp


def auth_headers(sub="tester", roles=None, companies=None) -> dict:
    user = CurrentUser(sub=sub, display_name=sub, roles=roles or ["CENTRAL_ADMIN"], companies=companies or ["*"])
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}
