"""Testes do serviço de Machine Learning."""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime


def make_mock_metric(cpu=30.0, mem=40.0, disk=50.0, net_s=100000, net_r=200000,
                     conn=10, disk_r=50000, disk_w=30000, load=0.3, procs=80):
    m = MagicMock()
    m.machine_id = 1
    m.cpu_percent = cpu
    m.mem_percent = mem
    m.disk_percent = disk
    m.net_bytes_sent = net_s
    m.net_bytes_recv = net_r
    m.net_connections = conn
    m.disk_read_bytes = disk_r
    m.disk_write_bytes = disk_w
    m.load_avg_1 = load
    m.process_count = procs
    m.swap_percent = 5.0
    m.gpu_metrics = None
    m.timestamp = datetime.utcnow()
    return m


class TestMLService:
    def test_metric_to_vector_shape(self):
        from app.services.ml_service import _metric_to_vector, FEATURES
        m = make_mock_metric()
        vec = _metric_to_vector(m)
        assert len(vec) == len(FEATURES)

    def test_vector_encodes_hour_cyclically(self):
        """23h e 0h precisam ficar perto; 0h e 12h, longe."""
        from app.services.ml_service import _metric_to_vector, FEATURE_KEYS
        from datetime import timezone
        i_sin, i_cos = FEATURE_KEYS.index("hour_sin"), FEATURE_KEYS.index("hour_cos")

        def at(hour):
            m = make_mock_metric()
            m.timestamp = datetime(2026, 9, 7, hour, 0, tzinfo=timezone.utc)
            v = _metric_to_vector(m, offset_minutes=0)
            return np.array([v[i_sin], v[i_cos]])

        assert np.linalg.norm(at(23) - at(0)) < np.linalg.norm(at(0) - at(12))

    def test_train_insufficient_data(self):
        from app.services.ml_service import train_model
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = train_model(1, db)
        assert result is False

    def test_predict_no_model(self):
        from app.services.ml_service import predict_anomaly
        m = make_mock_metric()
        with patch("app.services.ml_service._load_bundle", return_value=None):
            is_anomaly, score = predict_anomaly(1, m)
        assert is_anomaly is False
        assert score is None

    def test_classify_high_cpu(self):
        from app.services.ml_service import classify_anomaly
        m = make_mock_metric(cpu=97.0, mem=30.0)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            make_mock_metric(cpu=20.0) for _ in range(20)
        ]
        result = classify_anomaly(m, db)
        assert result["anomaly_type"] == "high_cpu"
        assert result["severity"] in ("high", "critical")

    def test_classify_high_memory(self):
        from app.services.ml_service import classify_anomaly
        m = make_mock_metric(cpu=20.0, mem=94.0)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            make_mock_metric(mem=40.0) for _ in range(20)
        ]
        result = classify_anomaly(m, db)
        assert result["anomaly_type"] in ("high_memory", "resource_exhaustion")

    def test_classify_disk_full(self):
        from app.services.ml_service import classify_anomaly
        m = make_mock_metric(disk=97.0)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            make_mock_metric(disk=50.0) for _ in range(20)
        ]
        result = classify_anomaly(m, db)
        assert result["anomaly_type"] == "disk_full"
        assert result["severity"] == "critical"

    def test_classify_uses_contributions_when_no_threshold_matches(self):
        from app.services.ml_service import classify_anomaly
        m = make_mock_metric(cpu=30.0, mem=40.0, disk=50.0)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        contributions = [{"group": "time", "label": "Horário incomum", "percent": 70.0}]
        result = classify_anomaly(m, db, contributions)
        assert result["anomaly_type"] == "unusual_time"


BASE_17 = [
    "cpu_percent", "mem_percent", "disk_percent", "net_bytes_sent", "net_bytes_recv", "net_connections",
    "disk_read_bytes", "disk_write_bytes", "load_avg_1", "process_count", "swap_percent", "gpu_load",
    "gpu_mem", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]
CONTEXT = {"user_idle_seconds": 30.0, "top_proc_cpu": 20.0, "top_proc_user_driven": 1, "top_proc_trust": 2,
            "top_proc_known": 1, "cpu_std_10m": 8.0, "gpu_std_10m": 5.0}


def _bare_reading(**over):
    from types import SimpleNamespace
    base = {k: None for k in CONTEXT}
    return SimpleNamespace(**{**base, **over})


def _history(db, machine_id, n, with_context, start_hours, rng):
    from datetime import timedelta
    from app.core.timeutil import utcnow
    from app.models.metric import Metric
    now = utcnow()
    for i in range(n):
        extra = {}
        if with_context:
            extra = {"user_idle_seconds": float(rng.uniform(0, 120)), "top_proc_cpu": float(rng.normal(20, 4)),
                     "top_proc_user_driven": 1, "top_proc_trust": 2, "top_proc_known": 1,
                     "cpu_std_10m": float(rng.normal(8, 2)), "gpu_std_10m": float(rng.normal(5, 1))}
        db.add(Metric(machine_id=machine_id, cpu_percent=float(rng.normal(30, 5)), mem_percent=float(rng.normal(50, 3)),
                      disk_percent=60.0, net_bytes_sent=float(rng.normal(5e4, 5e3)), net_bytes_recv=float(rng.normal(9e4, 9e3)),
                      net_connections=int(rng.normal(40, 4)), disk_read_bytes=float(rng.normal(1e5, 1e4)),
                      disk_write_bytes=float(rng.normal(1e5, 1e4)), load_avg_1=1.0, process_count=int(rng.normal(150, 5)),
                      swap_percent=5.0, cpu_count_logical=8,
                      timestamp=now - timedelta(hours=start_hours) + timedelta(minutes=2 * i), **extra))
    db.commit()


class TestOptionalFeatures:
    """Presença, programa dominante e estabilidade — só onde há histórico deles."""

    def test_base_17_included_even_without_context(self):
        from app.services import ml_service
        assert ml_service.available_features([_bare_reading() for _ in range(200)]) == BASE_17

    def test_optional_with_99_readings_excluded(self):
        from app.services import ml_service
        readings = [_bare_reading(top_proc_cpu=10.0) for _ in range(99)] + [_bare_reading() for _ in range(101)]
        assert "top_proc_cpu" not in ml_service.available_features(readings)

    def test_optional_with_100_readings_included(self):
        from app.services import ml_service
        readings = [_bare_reading(top_proc_cpu=10.0) for _ in range(100)] + [_bare_reading() for _ in range(100)]
        chosen = ml_service.available_features(readings)
        assert "top_proc_cpu" in chosen and chosen[:17] == BASE_17

    def test_presence_comes_from_idle_time(self):
        from app.services import ml_service
        readings = [_bare_reading(user_idle_seconds=5.0) for _ in range(100)]
        assert ml_service.OPTIONAL_FEATURES["user_presence"] == "user_idle_seconds"
        assert "user_presence" in ml_service.available_features(readings)

    def test_context_off_only_17(self):
        from app.services import context, ml_service
        readings = [_bare_reading(**CONTEXT) for _ in range(200)]
        previous = context.set_context_mode(False)
        try:
            assert ml_service.available_features(readings) == BASE_17
        finally:
            context.set_context_mode(previous)

    def test_presence_is_log_of_idle_time_capped_at_one_hour(self):
        import math
        from app.services import ml_service
        m = make_mock_metric()
        keys = BASE_17 + ["user_presence"]
        m.user_idle_seconds = 7200.0
        assert ml_service._metric_to_vector(m, keys=keys)[-1] == pytest.approx(math.log1p(3600))
        m.user_idle_seconds = None
        assert ml_service._metric_to_vector(m, keys=keys, fill={"user_presence": 2.5})[-1] == 2.5

    def test_mixed_training_uses_new_features_and_stores_fill(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        rng = np.random.default_rng(1)
        m = _machine(db)
        _history(db, m.id, 150, with_context=False, start_hours=20, rng=rng)
        _history(db, m.id, 120, with_context=True, start_hours=4, rng=rng)
        assert ml_service.train_model(m.id, db)
        bundle = ml_service._load_bundle(m.id)
        assert bundle["features"][:17] == BASE_17
        assert set(bundle["features"][17:]) == set(ml_service.OPTIONAL_FEATURES)
        assert bundle["fill"]["top_proc_cpu"] == pytest.approx(20.0, abs=2.0)
        assert set(bundle["fill"]) == set(ml_service.OPTIONAL_FEATURES)

    def test_old_17_feature_model_still_predicts(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _history(db, m.id, 150, with_context=False, start_hours=6, rng=np.random.default_rng(2))
        assert ml_service.train_model(m.id, db)
        assert ml_service._load_bundle(m.id)["features"] == BASE_17
        reading = make_mock_metric()
        for k, v in CONTEXT.items():
            setattr(reading, k, v)
        _, score = ml_service.predict_anomaly(m.id, reading)
        assert score is not None

    def test_bundle_with_unknown_feature_is_discarded(self, db):
        import os
        import pickle
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _history(db, m.id, 150, with_context=False, start_hours=6, rng=np.random.default_rng(3))
        assert ml_service.train_model(m.id, db)
        path = ml_service._model_path(m.id)
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        bundle["features"] = bundle["features"] + ["atributo_que_nao_existe"]
        with open(path, "wb") as f:
            pickle.dump(bundle, f)
        ml_service._cache.clear()
        assert ml_service.predict_anomaly(m.id, make_mock_metric()) == (False, None)
        assert not os.path.exists(path)

    def test_explanation_only_mentions_model_groups(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _history(db, m.id, 150, with_context=False, start_hours=6, rng=np.random.default_rng(4))
        assert ml_service.train_model(m.id, db)
        reading = make_mock_metric(cpu=99.0, mem=97.0)
        for k, v in CONTEXT.items():
            setattr(reading, k, v)
        groups = {c["group"] for c in ml_service.explain_contributions(m.id, reading)}
        assert groups and not groups & {"presence", "dominant_process", "stability"}

    def test_explanation_points_to_dominant_program(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _history(db, m.id, 150, with_context=True, start_hours=6, rng=np.random.default_rng(5))
        assert ml_service.train_model(m.id, db)
        # Igual ao histórico em tudo, menos no programa dominante
        reading = make_mock_metric(cpu=30.0, mem=50.0, disk=60.0, net_s=5e4, net_r=9e4, conn=40,
                                   disk_r=1e5, disk_w=1e5, load=1.0, procs=150)
        from datetime import timedelta
        from app.core.timeutil import utcnow
        reading.timestamp = utcnow() - timedelta(hours=3)  # dentro das horas do histórico
        for k, v in {**CONTEXT, "top_proc_cpu": 95.0, "top_proc_user_driven": 0, "top_proc_trust": 0,
                     "top_proc_known": 0}.items():
            setattr(reading, k, v)
        contribs = ml_service.explain_contributions(m.id, reading)
        assert contribs and contribs[0]["group"] == "dominant_process"
        assert contribs[0]["label"] == "Programa dominante"


def _classify(cpu, user_driven, contributions=None, **over):
    from app.services.ml_service import classify_anomaly
    m = make_mock_metric(cpu=cpu, mem=over.pop("mem", 40.0), disk=50.0)
    m.top_proc_user_driven = user_driven
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        make_mock_metric(cpu=20.0) for _ in range(20)
    ]
    return classify_anomaly(m, db, contributions)


class TestBackgroundLoad:
    """O mesmo processador cheio: jogo na janela da frente × programa sozinho em segundo plano."""

    def test_full_cpu_without_user_driving_is_background(self):
        r = _classify(97.0, 0)
        assert (r["anomaly_type"], r["severity"]) == ("background_load", "high")

    def test_severity_follows_cpu(self):
        r = _classify(92.0, 0)
        assert (r["anomaly_type"], r["severity"]) == ("background_load", "medium")

    def test_user_driven_stays_cpu(self):
        assert _classify(97.0, 1)["anomaly_type"] == "high_cpu"

    def test_without_foreground_window_stays_cpu(self):
        assert _classify(97.0, None)["anomaly_type"] == "high_cpu"

    def test_dominant_program_group_without_fixed_threshold(self):
        group = [{"group": "dominant_process", "label": "Programa dominante", "percent": 80.0}]
        assert _classify(40.0, 0, group)["anomaly_type"] == "background_load"
        assert _classify(40.0, 1, group)["anomaly_type"] == "high_cpu"

    def test_stability_group(self):
        group = [{"group": "stability", "label": "Estabilidade da carga", "percent": 80.0}]
        r = _classify(40.0, None, group)
        assert (r["anomaly_type"], r["severity"]) == ("behavioral_anomaly", "medium")

    def test_presence_group(self):
        group = [{"group": "presence", "label": "Presença de quem usa", "percent": 80.0}]
        r = _classify(40.0, None, group)
        assert (r["anomaly_type"], r["severity"]) == ("unusual_time", "low")

    def test_context_off_never_gives_background(self):
        from app.services import context
        group = [{"group": "dominant_process", "label": "Programa dominante", "percent": 80.0}]
        previous = context.set_context_mode(False)
        try:
            assert _classify(97.0, 0)["anomaly_type"] == "high_cpu"
            assert _classify(40.0, 0, group)["anomaly_type"] == "high_cpu"
        finally:
            context.set_context_mode(previous)

    def test_type_registered_with_load_types(self):
        from app.core import labels
        from app.services import anomaly_service, incidents
        assert labels.ANOMALY_TYPE_LABELS["background_load"] == "Programa pesado rodando em segundo plano"
        assert "background_load" in labels.PERFORMANCE_TYPES
        assert "background_load" not in labels.SECURITY_TYPES
        assert "background_load" in labels.COUNTERFACTUAL_TYPES
        assert labels.DETECTOR_OF_TYPE["background_load"] == "ml"
        assert incidents.TYPE_SIGNALS["background_load"] == ["cpu_pressure"]
        # Sem isto o aviso sai sem programa responsável
        assert anomaly_service.BLAME_FIELD["background_load"] == "cpu_percent"

    def test_recheck_looks_at_cpu(self, db):
        """A reconferência de um aviso de segundo plano mede o processador, como a de CPU."""
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.models.metric import Metric
        from app.services import conditions
        from tests.test_trust import _machine
        m = _machine(db)
        now = utcnow()
        a = Anomaly(machine_id=m.id, anomaly_type="background_load", severity="high",
                    detected_at=now - timedelta(minutes=10), affected_metrics={})
        db.add(a)
        for i in range(4):
            db.add(Metric(machine_id=m.id, cpu_percent=97.0, timestamp=now - timedelta(minutes=8 - 2 * i)))
        db.commit()
        still, sentence = conditions.condition_status(db, a, since=now - timedelta(minutes=9))
        assert still is True and sentence.startswith("Processador em média 97%")


def test_no_ai_background_explanation_mentions_unopened_program():
    """Sem IA disponível, o aviso novo não pode cair nas causas genéricas."""
    from types import SimpleNamespace
    from app.services.ai_service import _generate_fallback_explanation
    anomaly = SimpleNamespace(anomaly_type="background_load", severity="high", responsible_process="svc_update.exe")
    out = _generate_fallback_explanation(anomaly, None)
    text = " ".join(out["possible_causes"]).lower()
    assert "segundo plano" in text and "minerador" in text
    assert any("você abriu" in r.lower() or "voce abriu" in r.lower() for r in out["recommendations"])
