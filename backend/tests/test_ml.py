"""
Testes do serviço de Machine Learning.
"""
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
CONTEXTO = {"user_idle_seconds": 30.0, "top_proc_cpu": 20.0, "top_proc_user_driven": 1, "top_proc_trust": 2,
            "top_proc_known": 1, "cpu_std_10m": 8.0, "gpu_std_10m": 5.0}


def _leitura_solta(**over):
    from types import SimpleNamespace
    base = {k: None for k in CONTEXTO}
    return SimpleNamespace(**{**base, **over})


def _historico(db, machine_id, n, com_contexto, inicio_horas, rng):
    from datetime import timedelta
    from app.core.timeutil import utcnow
    from app.models.metric import Metric
    agora = utcnow()
    for i in range(n):
        extra = {}
        if com_contexto:
            extra = {"user_idle_seconds": float(rng.uniform(0, 120)), "top_proc_cpu": float(rng.normal(20, 4)),
                     "top_proc_user_driven": 1, "top_proc_trust": 2, "top_proc_known": 1,
                     "cpu_std_10m": float(rng.normal(8, 2)), "gpu_std_10m": float(rng.normal(5, 1))}
        db.add(Metric(machine_id=machine_id, cpu_percent=float(rng.normal(30, 5)), mem_percent=float(rng.normal(50, 3)),
                      disk_percent=60.0, net_bytes_sent=float(rng.normal(5e4, 5e3)), net_bytes_recv=float(rng.normal(9e4, 9e3)),
                      net_connections=int(rng.normal(40, 4)), disk_read_bytes=float(rng.normal(1e5, 1e4)),
                      disk_write_bytes=float(rng.normal(1e5, 1e4)), load_avg_1=1.0, process_count=int(rng.normal(150, 5)),
                      swap_percent=5.0, cpu_count_logical=8,
                      timestamp=agora - timedelta(hours=inicio_horas) + timedelta(minutes=2 * i), **extra))
    db.commit()


class TestAtributosOpcionais:
    """Presença, programa dominante e estabilidade — só onde há histórico deles."""

    def test_os_17_de_sempre_entram_mesmo_sem_contexto(self):
        from app.services import ml_service
        assert ml_service.available_features([_leitura_solta() for _ in range(200)]) == BASE_17

    def test_opcional_com_99_leituras_fica_fora(self):
        from app.services import ml_service
        leituras = [_leitura_solta(top_proc_cpu=10.0) for _ in range(99)] + [_leitura_solta() for _ in range(101)]
        assert "top_proc_cpu" not in ml_service.available_features(leituras)

    def test_opcional_com_100_leituras_entra(self):
        from app.services import ml_service
        leituras = [_leitura_solta(top_proc_cpu=10.0) for _ in range(100)] + [_leitura_solta() for _ in range(100)]
        escolhidos = ml_service.available_features(leituras)
        assert "top_proc_cpu" in escolhidos and escolhidos[:17] == BASE_17

    def test_presenca_vem_do_tempo_ocioso(self):
        from app.services import ml_service
        leituras = [_leitura_solta(user_idle_seconds=5.0) for _ in range(100)]
        assert ml_service.OPTIONAL_FEATURES["user_presence"] == "user_idle_seconds"
        assert "user_presence" in ml_service.available_features(leituras)

    def test_contexto_desligado_so_os_17(self):
        from app.services import context, ml_service
        leituras = [_leitura_solta(**CONTEXTO) for _ in range(200)]
        anterior = context.set_context_mode(False)
        try:
            assert ml_service.available_features(leituras) == BASE_17
        finally:
            context.set_context_mode(anterior)

    def test_presenca_e_logaritmo_do_tempo_ocioso_limitado_a_uma_hora(self):
        import math
        from app.services import ml_service
        m = make_mock_metric()
        keys = BASE_17 + ["user_presence"]
        m.user_idle_seconds = 7200.0
        assert ml_service._metric_to_vector(m, keys=keys)[-1] == pytest.approx(math.log1p(3600))
        m.user_idle_seconds = None
        assert ml_service._metric_to_vector(m, keys=keys, fill={"user_presence": 2.5})[-1] == 2.5

    def test_treino_misto_usa_os_novos_e_grava_o_preenchimento(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        rng = np.random.default_rng(1)
        m = _machine(db)
        _historico(db, m.id, 150, com_contexto=False, inicio_horas=20, rng=rng)
        _historico(db, m.id, 120, com_contexto=True, inicio_horas=4, rng=rng)
        assert ml_service.train_model(m.id, db)
        bundle = ml_service._load_bundle(m.id)
        assert bundle["features"][:17] == BASE_17
        assert set(bundle["features"][17:]) == set(ml_service.OPTIONAL_FEATURES)
        assert bundle["fill"]["top_proc_cpu"] == pytest.approx(20.0, abs=2.0)
        assert set(bundle["fill"]) == set(ml_service.OPTIONAL_FEATURES)

    def test_modelo_antigo_de_17_continua_prevendo(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _historico(db, m.id, 150, com_contexto=False, inicio_horas=6, rng=np.random.default_rng(2))
        assert ml_service.train_model(m.id, db)
        assert ml_service._load_bundle(m.id)["features"] == BASE_17
        leitura = make_mock_metric()
        for k, v in CONTEXTO.items():
            setattr(leitura, k, v)
        _, score = ml_service.predict_anomaly(m.id, leitura)
        assert score is not None

    def test_bundle_com_atributo_desconhecido_e_descartado(self, db):
        import os
        import pickle
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _historico(db, m.id, 150, com_contexto=False, inicio_horas=6, rng=np.random.default_rng(3))
        assert ml_service.train_model(m.id, db)
        caminho = ml_service._model_path(m.id)
        with open(caminho, "rb") as f:
            bundle = pickle.load(f)
        bundle["features"] = bundle["features"] + ["atributo_que_nao_existe"]
        with open(caminho, "wb") as f:
            pickle.dump(bundle, f)
        ml_service._cache.clear()
        assert ml_service.predict_anomaly(m.id, make_mock_metric()) == (False, None)
        assert not os.path.exists(caminho)

    def test_explicacao_so_fala_dos_grupos_do_modelo(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _historico(db, m.id, 150, com_contexto=False, inicio_horas=6, rng=np.random.default_rng(4))
        assert ml_service.train_model(m.id, db)
        leitura = make_mock_metric(cpu=99.0, mem=97.0)
        for k, v in CONTEXTO.items():
            setattr(leitura, k, v)
        grupos = {c["group"] for c in ml_service.explain_contributions(m.id, leitura)}
        assert grupos and not grupos & {"presence", "dominant_process", "stability"}

    def test_explicacao_aponta_o_programa_dominante(self, db):
        from app.services import ml_service
        from tests.test_trust import _machine
        m = _machine(db)
        _historico(db, m.id, 150, com_contexto=True, inicio_horas=6, rng=np.random.default_rng(5))
        assert ml_service.train_model(m.id, db)
        # Igual ao histórico em tudo, menos no programa dominante
        leitura = make_mock_metric(cpu=30.0, mem=50.0, disk=60.0, net_s=5e4, net_r=9e4, conn=40,
                                   disk_r=1e5, disk_w=1e5, load=1.0, procs=150)
        from datetime import timedelta
        from app.core.timeutil import utcnow
        leitura.timestamp = utcnow() - timedelta(hours=3)  # dentro das horas do histórico
        for k, v in {**CONTEXTO, "top_proc_cpu": 95.0, "top_proc_user_driven": 0, "top_proc_trust": 0,
                     "top_proc_known": 0}.items():
            setattr(leitura, k, v)
        contribs = ml_service.explain_contributions(m.id, leitura)
        assert contribs and contribs[0]["group"] == "dominant_process"
        assert contribs[0]["label"] == "Programa dominante"
