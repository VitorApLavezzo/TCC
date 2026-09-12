"""Testes de unidade dos serviços novos, sem depender de IA nem de rede."""
from datetime import datetime, timedelta, timezone


class TestRedaction:
    def test_password_flag(self):
        from app.core.redaction import redact_secrets
        out = redact_secrets("myapp.exe --password=Hunter2 --verbose")
        assert "Hunter2" not in out and "REMOVIDO" in out

    def test_connection_string(self):
        from app.core.redaction import redact_secrets
        out = redact_secrets("postgres://user:s3cr3t@db:5432/x")
        assert "s3cr3t" not in out

    def test_bearer_token(self):
        from app.core.redaction import redact_secrets
        out = redact_secrets("curl -H 'Authorization: Bearer abcdef0123456789xyz'")
        assert "abcdef0123456789xyz" not in out

    def test_keeps_normal_path(self):
        from app.core.redaction import redact_secrets
        p = "C:\\Program Files\\App\\app.exe"
        assert redact_secrets(p) == p

    def test_personal_only_for_cloud(self):
        from app.core.redaction import redact_for_llm
        t = "arquivo em C:\\Users\\joao\\Documents"
        assert "joao" in redact_for_llm(t, "local")
        assert "joao" not in redact_for_llm(t, "cloud")


class TestIncidents:
    def test_chain_orders_cause_before_effect(self):
        from app.services.incidents import build_chain
        chain = build_chain(["cpu_pressure", "disk_pressure", "swap_pressure"])
        signals = [n["signal"] for n in chain["nodes"]]
        assert signals.index("disk_pressure") < signals.index("swap_pressure")
        assert signals.index("swap_pressure") < signals.index("cpu_pressure")
        assert "disk_pressure" in chain["roots"]


class TestConditions:
    def test_high_cpu_still_happening(self, db):
        from app.models.user import User
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.anomaly import Anomaly
        from app.services.conditions import condition_status
        from app.core.security import get_password_hash

        u = User(email="c@c.com", username="cc", hashed_password=get_password_hash("x"))
        db.add(u); db.flush()
        m = Machine(name="m", hostname="h", agent_token="tok-cond", owner_id=u.id)
        db.add(m); db.flush()
        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        a = Anomaly(machine_id=m.id, anomaly_type="high_cpu", severity="high", detected_at=base)
        db.add(a); db.flush()
        for i in range(6):
            db.add(Metric(machine_id=m.id, cpu_percent=95, mem_percent=40,
                          timestamp=base + timedelta(minutes=i + 1)))
        db.commit()
        still, note = condition_status(db, a)
        assert still is True and "%" in note


class TestForecasting:
    def test_disk_fills_forecast(self, db):
        from app.models.user import User
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services.forecasting import disk_forecast
        from app.core.security import get_password_hash

        u = User(email="f@f.com", username="ff", hashed_password=get_password_hash("x"))
        db.add(u); db.flush()
        m = Machine(name="m", hostname="h", agent_token="tok-fc", owner_id=u.id)
        db.add(m); db.flush()
        start = datetime.now(timezone.utc) - timedelta(days=10)
        total = 100 * 1024 ** 3
        for i in range(240):  # 10 dias, 1/h, 2 GB/dia
            t = start + timedelta(hours=i)
            used = (30 + i / 24 * 2) * 1024 ** 3
            db.add(Metric(machine_id=m.id, timestamp=t, disk_used=used, disk_free=total - used,
                          disk_percent=used / total * 100))
        db.commit()
        f = disk_forecast(db, m, days=14)
        assert f["ready"] and f["trend"] == "enchendo"
        assert f["eta_days"] is not None and f["eta_days"] > 0


class TestEnergy:
    def test_estimate_positive(self):
        from app.services.energy import estimate_power
        from types import SimpleNamespace
        m = SimpleNamespace(power_watts=None, power_source=None, cpu_percent=50, gpu_metrics=None,
                            user_idle_seconds=0, battery_percent=None)
        watts, source = estimate_power(m, {"form_factor": "desktop"})
        assert watts > 0 and source == "estimado"


class TestPreferences:
    def test_defaults_and_merge(self):
        from types import SimpleNamespace
        from app.services.preferences import get_preferences, update_preferences
        u = SimpleNamespace(preferences=None)
        prefs = get_preferences(u)
        assert prefs["language_level"] == "leigo"
        update_preferences(u, {"language_level": "tecnico", "notifications": {"min_severity": "high"}})
        prefs = get_preferences(u)
        assert prefs["language_level"] == "tecnico"
        assert prefs["notifications"]["min_severity"] == "high"
        # não apaga o resto
        assert "channels" in prefs["notifications"]


class TestMasquerade:
    def test_svchost_outside_system32_flagged(self):
        from app.services.behavior_analyzer import detect_process_masquerading, DetectionContext
        from types import SimpleNamespace
        proc = SimpleNamespace(name="svchost.exe", exe="C:\\Users\\x\\AppData\\Local\\Temp\\svchost.exe",
                               pid=10, parent_name="cmd.exe", signed="unsigned", publisher=None, sha256=None,
                               cmdline="svchost.exe", username="x")
        result = detect_process_masquerading(None, [proc], [], None, DetectionContext())
        assert result is not None and result.anomaly_type == "process_masquerading"

    def test_real_svchost_ok(self):
        from app.services.behavior_analyzer import detect_process_masquerading, DetectionContext
        from types import SimpleNamespace
        proc = SimpleNamespace(name="svchost.exe", exe="C:\\Windows\\System32\\svchost.exe",
                               pid=10, parent_name="services.exe", signed="signed", publisher="Microsoft",
                               sha256=None, cmdline="svchost.exe -k netsvcs", username="system")
        assert detect_process_masquerading(None, [proc], [], None, DetectionContext()) is None
