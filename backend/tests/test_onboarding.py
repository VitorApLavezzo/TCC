"""Configuração inicial: só contas novas passam por ela, e uma vez só."""
from app.services.preferences import get_preferences
from tests.conftest import TEST_USER
from tests.test_security import google  # noqa: F401  (fixture)


def _prefs(client, headers):
    return client.get("/api/account/preferences", headers=headers).json()["preferences"]


def test_new_password_account_starts_onboarding(client, auth):
    assert _prefs(client, auth)["onboarding_done"] is False


def test_account_created_before_onboarding_existed_skips_it():
    old_user = type("U", (), {"preferences": None})()
    assert get_preferences(old_user)["onboarding_done"] is True


def test_finishing_onboarding_is_remembered(client, auth):
    client.patch("/api/account/preferences", json={"changes": {"onboarding_done": True}}, headers=auth)
    assert _prefs(client, auth)["onboarding_done"] is True


def test_new_google_account_starts_onboarding_once(client, google):  # noqa: F811
    first = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-9")}).json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    assert _prefs(client, headers)["onboarding_done"] is False

    client.patch("/api/account/preferences", json={"changes": {"onboarding_done": True}}, headers=headers)
    again = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-9")}).json()
    assert _prefs(client, {"Authorization": f"Bearer {again['access_token']}"})["onboarding_done"] is True


def test_register_response_unchanged(client):
    res = client.post("/api/auth/register", json={**TEST_USER, "email": "x@x.com", "username": "xx"})
    assert res.status_code == 201 and "hashed_password" not in res.json()
