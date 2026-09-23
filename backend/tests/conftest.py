import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, make_session_factory


@pytest.fixture
def db_session() -> Session:
    engine = make_engine("sqlite://")
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
