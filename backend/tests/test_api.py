"""Testes de integração da API. Usam as fixtures de conftest.py."""

TEST_USER = {"email": "t@t.com", "username": "tester", "password": "testpass123"}


class TestAuth:
    def test_register(self, client):
        res = client.post("/api/auth/register", json={"email": "a@a.com", "username": "aa", "password": "abcdef123"})
        assert res.status_code == 201
        assert res.json()["email"] == "a@a.com"

    def test_register_duplicate_email(self, client):
        client.post("/api/auth/register", json=TEST_USER)
        res = client.post("/api/auth/register", json=TEST_USER)
        assert res.status_code == 400

    def test_login_wrong_password(self, client):
        client.post("/api/auth/register", json=TEST_USER)
        res = client.post("/api/auth/login", data={"username": TEST_USER["username"], "password": "wrong"})
        assert res.status_code == 401

    def test_me(self, client, auth):
        res = client.get("/api/auth/me", headers=auth)
        assert res.status_code == 200
        assert res.json()["username"] == "tester"


class TestMachines:
    def test_create_and_list(self, client, auth):
        client.post("/api/machines", json={"name": "PC1", "hostname": "H1"}, headers=auth)
        client.post("/api/machines", json={"name": "PC2", "hostname": "H2"}, headers=auth)
        res = client.get("/api/machines", headers=auth)
        assert len(res.json()) == 2

    def test_delete_machine(self, client, machine, auth):
        res = client.delete(f"/api/machines/{machine['id']}", headers=auth)
        assert res.status_code == 204

    def test_delete_machine_with_activity_labels(self, client, machine, auth, db):
        """As marcações "o que estou fazendo" ficaram fora da limpeza: no PostgreSQL a exclusão falhava."""
        from app.core.timeutil import utcnow
        from app.models.activity_label import ActivityLabel
        db.add(ActivityLabel(machine_id=machine["id"], label="jogando", started_at=utcnow()))
        db.commit()
        assert client.delete(f"/api/machines/{machine['id']}", headers=auth).status_code == 204
        db.expire_all()
        assert db.query(ActivityLabel).filter(ActivityLabel.machine_id == machine["id"]).count() == 0

    def test_set_ai_privacy(self, client, machine, auth):
        res = client.patch(f"/api/machines/{machine['id']}", json={"ai_privacy": "no_ai"}, headers=auth)
        assert res.status_code == 200
        assert res.json()["ai_privacy"] == "no_ai"


class TestEnrollment:
    """A comparação de datas do código quebrava com SQLite (sem fuso contra com fuso) e derrubava o pareamento."""

    def test_agent_enrolls_with_code(self, client, auth):
        code = client.post("/api/machines/enroll-code", headers=auth).json()["code"]
        res = client.post("/api/machines/enroll", json={
            "code": code, "hostname": "NOTEBOOK-1", "os_type": "Windows", "os_version": "11"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["machine_name"] == "NOTEBOOK-1" and body["agent_token"]

    def test_code_works_lowercase_and_spaced(self, client, auth):
        """O código é digitado por gente: aceita minúsculas e espaço."""
        code = client.post("/api/machines/enroll-code", headers=auth).json()["code"]
        res = client.post("/api/machines/enroll", json={"code": f" {code.lower()} ", "hostname": "PC"})
        assert res.status_code == 200

    def test_code_is_single_use(self, client, auth):
        code = client.post("/api/machines/enroll-code", headers=auth).json()["code"]
        assert client.post("/api/machines/enroll", json={"code": code, "hostname": "A"}).status_code == 200
        again = client.post("/api/machines/enroll", json={"code": code, "hostname": "B"})
        assert again.status_code == 400

    def test_expired_code_is_refused(self, client, auth, db):
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.enrollment import EnrollmentCode
        code = client.post("/api/machines/enroll-code", headers=auth).json()["code"]
        row = db.query(EnrollmentCode).filter(EnrollmentCode.code == code).first()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        res = client.post("/api/machines/enroll", json={"code": code, "hostname": "PC"})
        assert res.status_code == 400

    def test_bulk_key_enrolls_many(self, client, auth):
        key = client.post("/api/machines/enroll-keys", json={"label": "TI", "max_uses": 2}, headers=auth).json()["code"]
        assert client.post("/api/machines/enroll", json={"code": key, "hostname": "PC-1"}).status_code == 200
        assert client.post("/api/machines/enroll", json={"code": key, "hostname": "PC-2"}).status_code == 200
        # Terceira excede o limite declarado
        assert client.post("/api/machines/enroll", json={"code": key, "hostname": "PC-3"}).status_code == 400


METRIC = {
    "cpu_percent": 45.2, "cpu_per_core": [40.0, 50.0], "mem_used": 4e9, "mem_available": 4e9,
    "mem_percent": 50.0, "mem_total": 8e9, "disk_used": 5e10, "disk_free": 5e10, "disk_percent": 50.0,
    "disk_read_bytes": 100000, "disk_write_bytes": 50000, "net_bytes_sent": 1e6, "net_bytes_recv": 2e6,
    "net_connections": 20, "uptime_seconds": 3600, "load_avg_1": 0.5, "load_avg_5": 0.4, "load_avg_15": 0.3,
    "process_count": 120,
    "processes": [{"pid": 1234, "name": "chrome.exe", "cpu_percent": 15.0, "mem_percent": 5.0, "mem_rss": 4e8,
                   "num_threads": 20, "status": "running", "username": "user",
                   "exe": "C:\\Program Files\\Google\\Chrome\\chrome.exe", "signed": "signed"}],
}


class TestMetrics:
    def test_ingest(self, client, machine):
        res = client.post("/api/metrics/ingest", json=METRIC, headers={"X-Agent-Token": machine["agent_token"]})
        assert res.status_code == 202
        body = res.json()
        assert body["metric_id"] is not None
        assert "next_interval" in body and "commands" in body

    def test_invalid_token(self, client):
        res = client.post("/api/metrics/ingest", json=METRIC, headers={"X-Agent-Token": "nope"})
        assert res.status_code == 401

    def test_ingest_redacts_secrets_in_cmdline(self, client, machine, db):
        from app.models.process import ProcessSnapshot
        payload = {**METRIC, "processes": [{**METRIC["processes"][0],
                   "cmdline": "app.exe --password=Sup3rSecret --user demo"}]}
        client.post("/api/metrics/ingest", json=payload, headers={"X-Agent-Token": machine["agent_token"]})
        snap = db.query(ProcessSnapshot).filter(ProcessSnapshot.name == "chrome.exe").first()
        assert snap is not None
        assert "Sup3rSecret" not in (snap.cmdline or "")
        assert "REMOVIDO" in (snap.cmdline or "")

    def test_paused_machine_discards(self, client, machine, auth):
        client.patch(f"/api/machines/{machine['id']}", json={"is_active": False}, headers=auth)
        res = client.post("/api/metrics/ingest", json=METRIC, headers={"X-Agent-Token": machine["agent_token"]})
        assert res.json()["paused"] is True


class TestAnomaliesFeedback:
    def _make_anomaly(self, db, machine_id):
        from app.models.anomaly import Anomaly
        from app.models.explanation import AIExplanation
        a = Anomaly(machine_id=machine_id, anomaly_type="high_cpu", severity="high", responsible_process="game.exe",
                    affected_metrics={"cpu": 97}, source="behavior")
        db.add(a)
        db.flush()
        db.add(AIExplanation(anomaly_id=a.id, summary="teste", possible_causes=["x"], recommendations=["y"]))
        db.commit()
        return a.id

    def test_feedback_normal_creates_rule_and_suppresses(self, client, machine, auth, db):
        from app.services import feedback
        from app.models.anomaly import Anomaly
        from app.models.machine import Machine
        anomaly_id = self._make_anomaly(db, machine["id"])
        res = client.post(f"/api/anomalies/{anomaly_id}/feedback", json={"kind": "normal", "scope": "process"},
                          headers=auth)
        assert res.status_code == 200
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        # A regra deve suprimir um novo aviso igual
        rule = feedback.matching_rule(db, machine["id"], "high_cpu", "game.exe", 12)
        assert rule is not None

    def test_resolve_with_cause_starts_verification(self, client, machine, auth, db):
        from app.models.anomaly import Anomaly
        anomaly_id = self._make_anomaly(db, machine["id"])
        res = client.patch(f"/api/anomalies/{anomaly_id}/resolve",
                           json={"is_resolved": True, "cause": "era o backup", "verify": True}, headers=auth)
        assert res.status_code == 200
        a = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
        assert a.resolution_cause == "era o backup"
        assert a.verification_status == "watching"


class TestFocusMode:
    def test_focus_mode_suppresses_performance_anomaly(self, client, machine, auth, db):
        from app.services.anomaly_service import Candidate, persist_candidate, focus_mode_active
        from app.models.machine import Machine
        client.post(f"/api/actions/machine/{machine['id']}/focus-mode", json={"minutes": 60}, headers=auth)
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        assert focus_mode_active(m)
        result = persist_candidate(db, m, Candidate(anomaly_type="high_cpu", severity="high"))
        assert result is None  # desempenho é suprimido no modo atividade pesada

    def test_focus_mode_does_not_suppress_security(self, client, machine, auth, db):
        from app.services.anomaly_service import Candidate, persist_candidate
        from app.models.machine import Machine
        client.post(f"/api/actions/machine/{machine['id']}/focus-mode", json={"minutes": 60}, headers=auth)
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        result = persist_candidate(db, m, Candidate(anomaly_type="malware_pattern", severity="critical",
                                                    responsible="x.exe"))
        assert result is not None  # segurança nunca é silenciada


def test_health(client):
    res = client.get("/health")
    assert res.json()["status"] == "ok"
