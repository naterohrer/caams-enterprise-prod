"""Shared fixtures for the CAAMS test suite.

Sets CAAMS_SECRET_KEY before any app import so the startup guard doesn't fire.
Uses an in-memory SQLite database isolated per test session.
"""

import os
os.environ.setdefault("CAAMS_SECRET_KEY", "test-secret-key-for-testing-only-32ch")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models
from app.auth import hash_password
from app.limiter import limiter

# Disable rate limiting during tests so repeated login calls don't hit 429
limiter.enabled = False

# StaticPool ensures every session/connection in-process shares the SAME
# in-memory SQLite database — without it each new connection gets an empty DB.
_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_ENGINE)


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    Base.metadata.create_all(bind=_ENGINE)
    yield
    Base.metadata.drop_all(bind=_ENGINE)


@pytest.fixture
def db():
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
    user = models.User(
        username="testadmin",
        hashed_password=hash_password("TestPass123!"),
        role="admin",
        is_active=True,
        full_name="Test Admin",
        email="admin@test.local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.delete(user)
    db.commit()


@pytest.fixture
def admin_token(client, admin_user):
    resp = client.post(
        "/auth/login",
        data={"username": "testadmin", "password": "TestPass123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def framework(db):
    fw = models.Framework(name="TestFW", version="1.0", description="Test framework")
    db.add(fw)
    db.flush()
    for i in range(1, 4):
        db.add(models.Control(
            framework_id=fw.id,
            control_id=f"T-{i}",
            title=f"Control {i}",
            description="",
            required_tags=["tag-a"] if i < 3 else [],
            optional_tags=[],
            evidence=[],
            sub_controls=[],
        ))
    db.commit()
    db.refresh(fw)
    yield fw
    db.delete(fw)
    db.commit()


@pytest.fixture
def assessment(db, admin_user, framework):
    a = models.Assessment(
        name="Test Assessment",
        framework_id=framework.id,
        created_by_id=admin_user.id,
        status="draft",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    yield a
    db.delete(a)
    db.commit()
