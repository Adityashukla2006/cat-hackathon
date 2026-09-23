import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, make_session_factory
from app.llm import FakeLLM, set_llm


@pytest.fixture
def fake_llm() -> FakeLLM:
    fake = FakeLLM()
    set_llm(fake)
    try:
        yield fake
    finally:
        set_llm(None)


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
