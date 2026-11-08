"""Rótulos de sessão: o gabarito da avaliação em dado real, que a detecção nunca pode ler."""
import os
import re
from datetime import timedelta

import pytest

from app.core.timeutil import aware, utcnow


def _db_machine(db, machine):
    from app.models.machine import Machine
    return db.query(Machine).filter(Machine.id == machine["id"]).one()


def test_mark_opens_session(db, machine):
    from app.services import activity_labels
    session = activity_labels.mark(db, _db_machine(db, machine), "jogando", "tray")
    assert session.label == "jogando"
    assert session.source == "tray"
    assert session.started_at is not None and session.ended_at is None


def test_switching_label_closes_previous_at_same_time(db, machine):
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _db_machine(db, machine)
    start = utcnow() - timedelta(minutes=30)
    activity_labels.mark(db, m, "jogando", "tray", now=start)
    switch_time = start + timedelta(minutes=20)
    new = activity_labels.mark(db, m, "teste_minerador", "tray", now=switch_time)
    old = db.query(ActivityLabel).filter(ActivityLabel.label == "jogando").one()
    assert aware(old.ended_at) == switch_time
    assert aware(new.started_at) == switch_time and new.ended_at is None


def test_stop_only_closes(db, machine):
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _db_machine(db, machine)
    activity_labels.mark(db, m, "uso_normal", "tray")
    assert activity_labels.mark(db, m, "parar", "tray") is None
    rows = db.query(ActivityLabel).all()
    assert len(rows) == 1 and rows[0].ended_at is not None


def test_same_label_again_does_not_split_session(db, machine):
    """Clique duplo na bandeja não pode virar duas sessões."""
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _db_machine(db, machine)
    first = activity_labels.mark(db, m, "jogando", "tray")
    second = activity_labels.mark(db, m, "jogando", "tray")
    assert first.id == second.id
    assert db.query(ActivityLabel).count() == 1


def test_unknown_label_is_rejected(db, machine):
    from app.services import activity_labels
    with pytest.raises(ValueError):
        activity_labels.mark(db, _db_machine(db, machine), "minerando_de_verdade", "tray")


def test_sessions_overlapping_window(db, machine):
    from app.services import activity_labels
    m = _db_machine(db, machine)
    now = utcnow()
    activity_labels.mark(db, m, "uso_normal", "tray", now=now - timedelta(hours=10))
    activity_labels.mark(db, m, "parar", "tray", now=now - timedelta(hours=9))
    activity_labels.mark(db, m, "jogando", "tray", now=now - timedelta(hours=2))
    found = activity_labels.sessions(db, m.id, now - timedelta(hours=3), now)
    assert [s.label for s in found] == ["jogando"]


def test_catalog_ids():
    from app.services import activity_labels
    assert set(activity_labels.LABELS) == {
        "jogando", "trabalho_pesado", "uso_normal", "teste_minerador",
        "teste_minerador_em_uso", "teste_disfarce", "teste_isca", "teste_periodico",
    }
    assert activity_labels.BENIGN == {"jogando", "trabalho_pesado", "uso_normal"}


def test_agent_endpoint_requires_token(client):
    res = client.post("/api/agent/activity-label", json={"label": "jogando"},
                      headers={"X-Agent-Token": "token-que-nao-existe"})
    assert res.status_code == 401


def test_agent_endpoint_marks(client, machine):
    res = client.post("/api/agent/activity-label", json={"label": "jogando"},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 200
    assert res.json()["open"]["label"] == "jogando"


def test_endpoint_rejects_unknown_label(client, machine):
    res = client.post("/api/agent/activity-label", json={"label": "xyz"},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 422


def test_panel_marks_and_lists(client, machine, auth):
    res = client.post(f"/api/machines/{machine['id']}/activity-label", json={"label": "trabalho_pesado"},
                      headers=auth)
    assert res.status_code == 200
    listing = client.get(f"/api/machines/{machine['id']}/activity-labels?days=7", headers=auth).json()
    assert listing["open"]["label"] == "trabalho_pesado"
    assert listing["open"]["source"] == "panel"
    assert [s["label"] for s in listing["sessions"]] == ["trabalho_pesado"]
    assert {c["id"] for c in listing["catalog"]} >= {"jogando", "teste_minerador"}


def test_panel_requires_owner(client, machine):
    client.post("/api/auth/register", json={"email": "o@o.com", "username": "outro", "password": "outrasenha123"})
    tok = client.post("/api/auth/login", data={"username": "outro", "password": "outrasenha123"}).json()["access_token"]
    other = {"Authorization": f"Bearer {tok}"}
    res = client.post(f"/api/machines/{machine['id']}/activity-label", json={"label": "jogando"}, headers=other)
    assert res.status_code == 404
    res = client.get(f"/api/machines/{machine['id']}/activity-labels", headers=other)
    assert res.status_code == 404


ALLOWED = {
    "models/activity_label.py", "models/__init__.py", "services/activity_labels.py",
    "services/real_eval.py", "routers/agent_api.py", "routers/machines.py", "routers/evaluation.py",
}


def test_detection_never_reads_labels():
    """Só o cadastro e a avaliação conhecem os rótulos; senão a avaliação mediria a própria resposta."""
    app_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    offenders = []
    for root, _, files in os.walk(app_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, app_dir).replace(os.sep, "/")
            with open(path, encoding="utf-8") as f:
                if re.search(r"activity_label|ActivityLabel", f.read()) and rel not in ALLOWED:
                    offenders.append(rel)
    assert offenders == []
