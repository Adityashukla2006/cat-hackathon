from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db import Base, make_engine
from app.main import create_app


def test_startup_creates_tables_and_health_ok():
    engine = make_engine("sqlite://")
    with TestClient(create_app(engine)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)


def test_health_degraded_when_database_unreachable():
    engine = make_engine("sqlite://")
    with TestClient(create_app(engine)) as client:
        client.app.state.engine = make_engine("sqlite:///Z:/no/such/dir/x.db")
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": False}
