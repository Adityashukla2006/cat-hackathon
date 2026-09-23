"""Phase 0: the app starts, connects to Postgres, creates all tables, and health is OK."""

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db import Base
from app.main import create_app


def test_app_starts_creates_tables_and_reports_healthy(pg_engine):
    assert inspect(pg_engine).get_table_names() == []

    with TestClient(create_app(pg_engine)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}
    assert pg_engine.dialect.name == "postgresql"
    assert set(inspect(pg_engine).get_table_names()) == set(Base.metadata.tables)
