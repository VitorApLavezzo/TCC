"""Cenário "Disco enchendo": a demonstração e o benchmark precisam gerar o aviso de previsão de disco."""
from app.core.security import get_password_hash
from app.models.anomaly import Anomaly
from app.models.user import User


def _user(db):
    u = User(email="disco@t.com", username="disco", hashed_password=get_password_hash("x"))
    db.add(u)
    db.commit()
    return u


class TestUnits:
    def test_disk_size_is_constant_and_usage_only_grows(self):
        from app.services import demo
        base = demo._base_metric(0)
        total = base["disk_used"] + base["disk_free"]
        used = []
        for k in range(demo.SCENARIOS["disk_filling"]["attack"]):
            m = demo._base_metric(k)
            demo._scenario_step("disk_filling", "attack", k, m, [])
            assert abs((m["disk_used"] + m["disk_free"]) - total) < 1e6
            assert abs(m["disk_used"] / total * 100 - m["disk_percent"]) < 0.01
            used.append(m["disk_used"])
        assert used == sorted(used) and used[-1] > used[0]
        assert used[0] >= base["disk_used"]


class TestDemo:
    def test_creates_forecast_alert(self, db):
        from app.services import demo
        s = demo.start(db, _user(db), "disk_filling")
        while s.status != "done":
            demo.step(db, s)
            db.refresh(s)
        types = {a.anomaly_type for a in db.query(Anomaly).filter(
            Anomaly.machine_id == s.state["machine_id"]).all()}
        assert "disk_forecast" in types

    def test_log_does_not_say_no_trend(self, db):
        from app.services import demo
        s = demo.start(db, _user(db), "disk_filling")
        while s.status != "done":
            demo.step(db, s)
            db.refresh(s)
        forecast_lines = [l for l in s.log if l.startswith("Previsão de disco")]
        assert forecast_lines and "sem tendência" not in forecast_lines[-1]


class TestBenchmark:
    def test_disk_forecast_detected_through_real_path(self, db):
        """Sem trocar o gabarito: o benchmark roda a reconferência que o agendador roda em produção."""
        from app.services import benchmark
        r = benchmark.run_scenario(db, "disk_filling", _user(db).id)
        assert r.error is None
        assert "disk_forecast" in r.detected
        assert r.verdict == "acerto"


class TestForecastSentence:
    """Aparece no log da demonstração e no aviso, na frente de quem assiste."""

    def test_one_day_singular(self):
        from app.services.forecasting import forecast_sentence
        sentence = forecast_sentence(span_days=1.2, gb_per_day=92.7, eta_days=3.0)
        assert "do último dia" in sentence and "1 dias" not in sentence

    def test_less_than_one_day_without_about(self):
        from app.services.forecasting import forecast_sentence
        sentence = forecast_sentence(span_days=1.2, gb_per_day=92.7, eta_days=0.4)
        assert "enche em menos de um dia" in sentence and "cerca de menos" not in sentence

    def test_several_days_unchanged(self):
        from app.services.forecasting import forecast_sentence
        sentence = forecast_sentence(span_days=5, gb_per_day=2.5, eta_days=6)
        assert sentence == "No ritmo dos últimos 5 dias (2,5 GB por dia), o disco enche em cerca de 6 dias."

    def test_two_weeks(self):
        from app.services.forecasting import forecast_sentence
        assert "das últimas duas semanas" in forecast_sentence(span_days=12, gb_per_day=1.0, eta_days=20)


class TestAblation:
    def test_forecast_not_credited_to_single_layer(self, db):
        """Não é regra nem Isolation Forest: na ablação só conta na linha do sistema completo."""
        from app.services import anomaly_service, benchmark
        u = _user(db)
        for layer in ("ml", "regras"):
            previous = anomaly_service.set_detection_layer(layer)
            try:
                r = benchmark.run_scenario(db, "disk_filling", u.id)
            finally:
                anomaly_service.set_detection_layer(previous)
            assert "disk_forecast" not in r.detected, layer
