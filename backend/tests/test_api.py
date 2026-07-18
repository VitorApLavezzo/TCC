"""
Testes de integração da API.
Execute: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

TEST_USER = {"email": "test@test.com", "username": "testuser", "password": "testpass123"}


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def get_auth_token():
    client.post("/api/auth/register", json=TEST_USER)
    res = client.post("/api/auth/login", data={"username": TEST_USER["username"], "password": TEST_USER["password"]})
    return res.json()["access_token"]


def auth_headers():
    return {"Authorization": f"Bearer {get_auth_token()}"}


class TestAuth:
    def test_register(self):
        res = client.post("/api/auth/register", json=TEST_USER)
        assert res.status_code == 201
        assert res.json()["email"] == TEST_USER["email"]

    def test_register_duplicate_email(self):
        client.post("/api/auth/register", json=TEST_USER)
        res = client.post("/api/auth/register", json=TEST_USER)
        assert res.status_code == 400

    def test_login(self):
        client.post("/api/auth/register", json=TEST_USER)
        res = client.post("/api/auth/login", data={"username": TEST_USER["username"], "password": TEST_USER["password"]})
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_login_wrong_password(self):
        client.post("/api/auth/register", json=TEST_USER)
        res = client.post("/api/auth/login", data={"username": TEST_USER["username"], "password": "wrong"})
        assert res.status_code == 401

    def test_me(self):
        res = client.get("/api/auth/me", headers=auth_headers())
        assert res.status_code == 200
        assert res.json()["username"] == TEST_USER["username"]


class TestMachines:
    def test_create_machine(self):
        res = client.post(
            "/api/machines",
            json={"name": "Test PC", "hostname": "TESTPC", "os_type": "Windows"},
            headers=auth_headers(),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Test PC"
        assert "agent_token" in data

    def test_list_machines(self):
        headers = auth_headers()
        client.post("/api/machines", json={"name": "PC1", "hostname": "HOST1"}, headers=headers)
        client.post("/api/machines", json={"name": "PC2", "hostname": "HOST2"}, headers=headers)
        res = client.get("/api/machines", headers=headers)
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_delete_machine(self):
        headers = auth_headers()
        created = client.post("/api/machines", json={"name": "PC", "hostname": "HOST"}, headers=headers)
        mid = created.json()["id"]
        res = client.delete(f"/api/machines/{mid}", headers=headers)
        assert res.status_code == 204


class TestMetrics:
    METRIC_PAYLOAD = {
        "cpu_percent": 45.2,
        "cpu_per_core": [40.0, 50.0],
        "mem_used": 4000000000,
        "mem_available": 4000000000,
        "mem_percent": 50.0,
        "mem_total": 8000000000,
        "disk_used": 50000000000,
        "disk_free": 50000000000,
        "disk_percent": 50.0,
        "disk_read_bytes": 100000,
        "disk_write_bytes": 50000,
        "net_bytes_sent": 1000000,
        "net_bytes_recv": 2000000,
        "net_connections": 20,
        "uptime_seconds": 3600,
        "load_avg_1": 0.5,
        "load_avg_5": 0.4,
        "load_avg_15": 0.3,
        "process_count": 120,
        "processes": [
            {
                "pid": 1234,
                "name": "chrome.exe",
                "cpu_percent": 15.0,
                "mem_percent": 5.0,
                "mem_rss": 400000000,
                "num_threads": 20,
                "status": "running",
                "username": "user",
            }
        ],
    }

    def _create_machine_and_token(self):
        headers = auth_headers()
        res = client.post("/api/machines", json={"name": "Test", "hostname": "HOST"}, headers=headers)
        return res.json()["agent_token"]

    def test_ingest_metrics(self):
        token = self._create_machine_and_token()
        res = client.post(
            "/api/metrics/ingest",
            json=self.METRIC_PAYLOAD,
            headers={"X-Agent-Token": token},
        )
        assert res.status_code == 202
        assert "metric_id" in res.json()

    def test_invalid_token(self):
        res = client.post(
            "/api/metrics/ingest",
            json=self.METRIC_PAYLOAD,
            headers={"X-Agent-Token": "invalid-token"},
        )
        assert res.status_code == 401


class TestAnomalies:
    def test_list_anomalies_empty(self):
        res = client.get("/api/anomalies", headers=auth_headers())
        assert res.status_code == 200
        assert res.json() == []

    def test_anomaly_stats(self):
        res = client.get("/api/anomalies/stats/summary", headers=auth_headers())
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "by_severity" in data


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
