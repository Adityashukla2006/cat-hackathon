import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.db import Base, make_engine

DEFAULT_URL = "postgresql+psycopg://shadow:shadow@localhost:5433/shadow_shift"


@pytest.fixture
def pg_engine() -> Engine:
    """Clean Docker Postgres database. Start it with `docker compose up -d db`."""
    engine = make_engine(os.environ.get("DATABASE_URL", DEFAULT_URL))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"Postgres not reachable, run `docker compose up -d db`: {exc.orig}")
    Base.metadata.drop_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
