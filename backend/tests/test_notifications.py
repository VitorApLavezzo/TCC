"""
A política de excesso de notificações.

O painel sempre registra tudo; o que estes testes fixam é quando algo sai (ou
não sai) por fora — severidade mínima, horário silencioso, agrupamento e
resumo diário. É decisão tomada em nome do usuário, então precisa ser previsível.
"""
from datetime import timedelta

import pytest

from app.core.security import get_password_hash
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.notification import Notification
from app.models.user import User
from app.services import notifications
from app.services.preferences import update_preferences


@pytest.fixture()
def scene(db):
    user = User(email="n@n.com", username="nn", hashed_password=get_password_hash("x"))
    db.add(user)
    db.flush()
    machine = Machine(name="PC", hostname="H", agent_token="tok-notif", owner_id=user.id,
                      system_info={"tz_offset_minutes": -180})
    db.add(machine)
    db.flush()
    db.commit()
    return user, machine


def make_anomaly(db, machine, severity="medium", anomaly_type="high_cpu"):
    a = Anomaly(machine_id=machine.id, anomaly_type=anomaly_type, severity=severity, detected_at=utcnow())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


class TestPolicyAtCreation:
    def test_below_min_severity_is_suppressed(self, db, scene):
        user, machine = scene
        update_preferences(user, {"notifications": {"min_severity": "high"}})
        db.commit()
        n = notifications.on_anomaly(db, make_anomaly(db, machine, "medium"))
        assert n.status == "suppressed"
        assert "severidade" in (n.status_reason or "")

    def test_low_goes_to_digest_when_enabled(self, db, scene):
        user, machine = scene
        update_preferences(user, {"notifications": {"min_severity": "high", "digest": {"enabled": True}}})
        db.commit()
        n = notifications.on_anomaly(db, make_anomaly(db, machine, "low"))
        assert n.status == "held"

    def test_critical_is_not_delayed(self, db, scene):
        """Crítico não espera a explicação da IA: sai na hora."""
        _, machine = scene
        n = notifications.on_anomaly(db, make_anomaly(db, machine, "critical", "ransomware_canary"))
        assert n.status == "pending"
        assert aware(n.deliver_after) <= utcnow() + timedelta(seconds=1)

    def test_normal_waits_for_the_explanation(self, db, scene):
        _, machine = scene
        n = notifications.on_anomaly(db, make_anomaly(db, machine, "high"))
        assert n.status == "pending"
        assert aware(n.deliver_after) > utcnow() + timedelta(seconds=30)


class TestDispatch:
    def _ready(self, db, machine, severity="high"):
        n = notifications.on_anomaly(db, make_anomaly(db, machine, severity))
        n.deliver_after = utcnow() - timedelta(seconds=1)
        db.commit()
        return n

    def test_sends_and_records_channel(self, db, scene):
        _, machine = scene
        n = self._ready(db, machine)
        assert notifications.dispatch(db) == 1
        db.refresh(n)
        assert n.status == "sent" and n.sent_at is not None
        assert n.channels.get("panel") == "ok"

    def test_groups_notifications_in_the_same_window(self, db, scene):
        _, machine = scene
        first = self._ready(db, machine)
        second = self._ready(db, machine)
        notifications.dispatch(db)
        db.refresh(first)
        db.refresh(second)
        assert {first.status, second.status} == {"sent", "grouped"}

    def test_quiet_hours_postpone_instead_of_dropping(self, db, scene):
        user, machine = scene
        update_preferences(user, {"notifications": {"quiet_hours": {"enabled": True, "from": 0, "to": 24}}})
        db.commit()
        n = self._ready(db, machine, "high")
        assert notifications.dispatch(db) == 0
        db.refresh(n)
        assert n.status == "pending"
        assert aware(n.deliver_after) > utcnow()
        assert n.status_reason == "horário silencioso"

    def test_critical_ignores_quiet_hours(self, db, scene):
        user, machine = scene
        update_preferences(user, {"notifications": {"quiet_hours": {"enabled": True, "from": 0, "to": 24}}})
        db.commit()
        n = notifications.on_anomaly(db, make_anomaly(db, machine, "critical", "malware_pattern"))
        n.deliver_after = utcnow() - timedelta(seconds=1)
        db.commit()
        assert notifications.dispatch(db) == 1
        db.refresh(n)
        assert n.status == "sent"

    def test_resolved_before_sending_is_dropped(self, db, scene):
        """Se a pessoa já resolveu enquanto a notificação esperava, não avisa."""
        _, machine = scene
        anomaly = make_anomaly(db, machine, "high")
        n = notifications.on_anomaly(db, anomaly)
        n.deliver_after = utcnow() - timedelta(seconds=1)
        anomaly.is_resolved = True
        db.commit()
        notifications.dispatch(db)
        db.refresh(n)
        assert n.status == "suppressed"
        assert "resolvido" in (n.status_reason or "")
