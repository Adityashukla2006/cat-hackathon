from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, make_session_factory
from app.llm import FakeLLM, set_llm


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory) -> Path:
    """Small models trained once per test session on seed-42 synthetic data."""
    from data.generate import generate
    from ml.train import run

    root = tmp_path_factory.mktemp("shadow")
    generate(seed=42, out_dir=root / "data", n_shifts=150)
    run(root / "data" / "history.csv", root / "models", seed=42)
    return root / "models"


@pytest.fixture(scope="session")
def predictor(model_dir):
    from app.shadow.predictor import ShadowPredictor

    return ShadowPredictor.load(model_dir)


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
