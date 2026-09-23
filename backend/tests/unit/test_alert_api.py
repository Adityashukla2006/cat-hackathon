import pytest
from fastapi.testclient import TestClient

from app.db import Alert, make_engine, make_session_factory
from app.main import create_app
from app.runtime import seed_demo_shift
from data.generate import generate


@pytest.fixture
def client():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as c:
        db = make_session_factory(app.state.engine)()
        seed_demo_shift(db, generate(seed=42, n_shifts=2)["demo"], None)
        db.add_all(
            [
                Alert(
                    shift_id=1, minute=159, kind="idle_deviation", severity="warning", message="b"
                ),
                Alert(shift_id=1, minute=2, kind="seatbelt", severity="critical", message="a"),
            ]
        )
        db.commit()
        db.close()
        yield c


def test_list_alerts_in_minute_order(client):
    body = client.get("/shifts/1/alerts").json()
    assert [a["minute"] for a in body] == [2, 159]
    assert client.get("/shifts/99/alerts").json() == []


def test_acknowledge_alert(client):
    alert_id = client.get("/shifts/1/alerts").json()[0]["id"]
    response = client.post(f"/alerts/{alert_id}/ack")
    assert response.status_code == 200 and response.json()["acknowledged"] is True
    assert client.get("/shifts/1/alerts").json()[0]["acknowledged"] is True
    assert client.post("/alerts/9999/ack").status_code == 404
