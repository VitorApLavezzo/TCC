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
    m.timestamp = datetime.utcnow()
    return m


class TestMLService:
    def test_metric_to_vector_shape(self):
        from app.services.ml_service import _metric_to_vector
        m = make_mock_metric()
        vec = _metric_to_vector(m)
        assert len(vec) == 10

    def test_train_insufficient_data(self):
        from app.services.ml_service import train_model
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = train_model(1, db)
        assert result is False

    def test_predict_no_model(self):
        from app.services.ml_service import predict_anomaly
        m = make_mock_metric()
        with patch("app.services.ml_service._load_model", return_value=(None, None)):
            is_anomaly, score = predict_anomaly(1, m)
        assert is_anomaly is False
        assert score == 0.0

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
