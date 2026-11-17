"""Testy integracyjne działają na prawdziwym PostgreSQL (nie SQLite).

Domyślnie: postgresql+psycopg://offcut:offcut@localhost:5433/offcut_test
(np. ``docker compose -f docker-compose.test.yml up -d``). Zmiana: OFFCUT_TEST_DATABASE_URL.
Schemat tworzony jest migracjami Alembic – testy sprawdzają też migracje od pustej bazy.
"""

import os

TEST_DB = os.environ.get(
    "OFFCUT_TEST_DATABASE_URL", "postgresql+psycopg://offcut:offcut@localhost:5433/offcut_test"
)
os.environ["OFFCUT_DATABASE_URL"] = TEST_DB
os.environ.setdefault("OFFCUT_SECRET_KEY", "test-secret-key-do-not-use-in-production")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

PASSWORD = "Haslo1234!"


@pytest.fixture(scope="session")
def migrated_db():
    from alembic import command
    from alembic.config import Config

    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_clean(migrated_db):
    with migrated_db.begin() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
        )).scalars().all()
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db(db_clean):
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def client(db_clean):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class Api:
    """Mały klient testowy: logowanie, CSRF i skróty do typowych operacji."""

    def __init__(self, client):
        self.c = client

    def register(self, email, workshop="Warsztat", name="Właściciel"):
        r = self.c.post("/api/auth/register", json={"email": email, "password": PASSWORD,
                                                     "full_name": name, "workshop_name": workshop})
        assert r.status_code == 201, r.text
        self.c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return r.json()["user"]["memberships"][0]["workshop_id"]

    def login(self, email, password=PASSWORD):
        self.c.cookies.clear()
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self.c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return r.json()

    def ok(self, method, url, status=200, **kw):
        r = self.c.request(method, url, **kw)
        assert r.status_code == status, f"{method} {url} -> {r.status_code}: {r.text}"
        return r.json() if r.content else None

    def spec(self, ws, material="Sosna", section="40x20"):
        return self.ok("POST", f"/api/workshops/{ws}/materials", 201,
                       json={"material": material, "section": section})["id"]

    def stock(self, ws, spec, lengths, remnant=False):
        ids = []
        for length in lengths:
            ids += [s["id"] for s in self.ok("POST", f"/api/workshops/{ws}/stock", 201, json={
                "material_spec_id": spec, "length_mm": length, "is_remnant": remnant})]
        return ids

    def project(self, ws, name="Projekt", kerf=3, min_remnant=300, demand=()):
        pid = self.ok("POST", f"/api/workshops/{ws}/projects", 201,
                      json={"name": name, "kerf_mm": kerf, "min_remnant_mm": min_remnant})["id"]
        for spec, length, qty in demand:
            self.ok("POST", f"/api/projects/{pid}/demand", 201,
                    json={"material_spec_id": spec, "length_mm": length, "quantity": qty})
        return pid


@pytest.fixture
def api(client):
    return Api(client)


@pytest.fixture
def demo(api):
    """Warsztat z przykładem z dokumentacji (heurystyka 5450 mm, B&B 4900 mm) i operatorem."""
    ws = api.register("owner@test.pl", "Warsztat A")
    api.ok("POST", f"/api/workshops/{ws}/members", 201, json={
        "email": "operator@test.pl", "full_name": "Operator", "password": PASSWORD, "role": "OPERATOR"})
    spec = api.spec(ws)
    remnants = api.stock(ws, spec, [1250, 1900, 1400, 900], remnant=True)
    bars = api.stock(ws, spec, [3000, 3000, 3000])
    pid = api.project(ws, "Regał", demand=[(spec, 560, 3), (spec, 950, 2), (spec, 600, 1)])
    return {"ws": ws, "spec": spec, "project": pid, "stock": remnants + bars}
