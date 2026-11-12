import os

# Must be set before app modules are imported.
# Tests drop and recreate all tables, so they only ever use TEST_DATABASE_URL (never DATABASE_URL).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://seo:seo@localhost:5432/seo_metadata_test")
assert "test" in os.environ["DATABASE_URL"], "TEST_DATABASE_URL must point at a dedicated test database"
os.environ["ALLOW_PRIVATE_NETWORKS"] = "true"  # the fixture site runs on 127.0.0.1
os.environ["TASK_BACKEND"] = "inline"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-1234567890"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from tests.fixture_site import FixtureSite  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="session")
def site():
    s = FixtureSite()
    s.start()
    yield s
    s.stop()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def register(client, email="owner@example.com"):
    r = client.post("/api/auth/register", json={"email": email, "password": "correct-horse-battery", "full_name": "Owner"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
