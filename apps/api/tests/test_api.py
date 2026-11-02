from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.api.deps import today_dep
from bankboard.demo.seed import connect_demo
from bankboard.main import app
from bankboard.models import User
from conftest import TODAY

ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[today_dep] = lambda: TODAY
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client: TestClient, email: str = "me@test.local") -> None:
    r = client.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "display_name": "Me"},
                    headers=ORIGIN)
    assert r.status_code == 201, r.text


@pytest.fixture()
def demo_client(client: TestClient, db: Session) -> TestClient:
    register(client)
    user = db.scalars(select(User).where(User.email == "me@test.local")).one()
    connect_demo(db, user, today=TODAY)
    db.commit()
    return client


def test_auth_required_and_origin_check(client: TestClient) -> None:
    assert client.get("/api/command-center").status_code == 401
    r = client.post("/api/auth/register", json={"email": "x@test.local", "password": "correct-horse-1"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    register(client)
    assert client.get("/api/me").json()["email"] == "me@test.local"
    assert client.post("/api/auth/login", json={"email": "me@test.local", "password": "wrong-password"},
                       headers=ORIGIN).status_code == 401


def test_command_center_on_demo_data(demo_client: TestClient) -> None:
    cc = demo_client.get("/api/command-center").json()
    assert cc["has_data"] and float(cc["now"]["spending_cash"]) > 0
    safe = cc["now"]["safe_to_spend"]
    assert safe["explanation"]["lines"][-1]["label"] == "Safe to spend"
    assert cc["next"]["next_income"]["date"] == "2026-11-27"
    assert 1 <= len(cc["attention"]) <= 5 and len(cc["opportunities"]) <= 3
    for path in ("/api/state", "/api/timeline?days=30", "/api/what-changed?preset=mtd", "/api/data-health",
                 "/api/metrics/cashflow/monthly", "/api/snapshots?days=30", "/api/recurring", "/api/feed",
                 "/api/widgets", "/api/net-worth-change?days=7", "/api/snapshots/2026-03-12"):
        assert demo_client.get(path).status_code == 200, path


def test_manual_recategorization(demo_client: TestClient) -> None:
    page = demo_client.get("/api/transactions", params={"q": "Grand Vefour"}).json()
    tx = page["items"][0]
    r = demo_client.patch(f"/api/transactions/{tx['id']}", json={"category_key": "gifts"}, headers=ORIGIN)
    assert r.status_code == 200
    body = r.json()
    assert body["category_key"] == "gifts" and body["category_source"] == "manual"


def test_layout_roundtrip_and_validation(demo_client: TestClient) -> None:
    assert demo_client.get("/api/dashboard/layout").json()["is_default"]
    items = [{"i": "a", "widget": "safe_to_spend", "x": 0, "y": 0, "w": 6, "h": 4}]
    assert demo_client.put("/api/dashboard/layout", json={"items": items}, headers=ORIGIN).status_code == 200
    assert demo_client.get("/api/dashboard/layout").json()["items"][0]["widget"] == "safe_to_spend"
    bad = [{"i": "b", "widget": "nope", "x": 0, "y": 0, "w": 6, "h": 4}]
    assert demo_client.put("/api/dashboard/layout", json={"items": bad}, headers=ORIGIN).status_code == 422


def test_module_toggle_hides_widgets(demo_client: TestClient) -> None:
    demo_client.put("/api/preferences", json={"modules": {"subscriptions": False}}, headers=ORIGIN)
    assert "subscriptions" not in {w["id"] for w in demo_client.get("/api/widgets").json()}


def test_ask_offline(demo_client: TestClient) -> None:
    r = demo_client.post("/api/ask", json={"question": "Combien puis-je dépenser ce week-end ?"}, headers=ORIGIN)
    body = r.json()
    assert r.status_code == 200 and body["tools_used"] == ["get_safe_to_spend"]
    assert body["unverified_numbers"] == []


def test_user_isolation_and_delete(demo_client: TestClient, db: Session) -> None:
    other = TestClient(app)
    register(other, "other@test.local")
    assert other.get("/api/transactions").json()["total"] == 0
    assert demo_client.delete("/api/me", headers=ORIGIN).status_code == 204
    assert db.scalars(select(User).where(User.email == "me@test.local")).first() is None


def _start_demo_connect(client: TestClient) -> str:
    r = client.post("/api/bank/connect", json={"provider": "demo", "institution_name": "Revolut (démo)",
                                               "institution_country": "FR"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    url: str = r.json()["url"]
    return url[url.index("/api/bank/callback"):]


def test_bank_callback_without_session_cookie(client: TestClient, db: Session) -> None:
    """iOS opens the bank redirect in Safari, outside the installed PWA and its cookies."""
    register(client)
    callback = _start_demo_connect(client)
    with TestClient(app) as safari:  # fresh cookie jar
        r = safari.get(callback, follow_redirects=False)
        assert r.status_code == 200 and "Banque connectée" in r.text
        again = safari.get(callback, follow_redirects=False)  # state is single use
        assert again.status_code == 200 and "déjà utilisé" in again.text
    conns = client.get("/api/bank/connections").json()
    assert len(conns) == 1 and conns[0]["provider"] == "demo"


def test_bank_callback_rejects_other_logged_in_user(client: TestClient) -> None:
    register(client)
    callback = _start_demo_connect(client)
    with TestClient(app) as other:
        register(other, "other@test.local")
        r = other.get(callback, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/settings?bank=invalid")
        assert other.get("/api/bank/connections").json() == []
    assert client.get("/api/bank/connections").json() == []


def test_bank_callback_logged_in_redirects(client: TestClient) -> None:
    register(client)
    r = client.get(_start_demo_connect(client), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/settings?bank=connected")
