"""Fluxo ponta a ponta pela API: ingestão rica → detecção → contexto/ações."""

BASE = {
    "cpu_percent": 20.0, "mem_used": 4e9, "mem_available": 4e9, "mem_percent": 45.0, "mem_total": 8e9,
    "disk_used": 5e10, "disk_free": 5e10, "disk_percent": 55.0, "disk_read_bytes": 1e4, "disk_write_bytes": 1e4,
    "net_bytes_sent": 1e5, "net_bytes_recv": 2e5, "net_connections": 30, "uptime_seconds": 7200,
    "load_avg_1": 1.0, "process_count": 150, "cpu_count_logical": 8,
}


def _ingest(client, token, **over):
    payload = {**BASE, **over}
    return client.post("/api/metrics/ingest", json=payload, headers={"X-Agent-Token": token})


def test_masquerade_via_process_start(client, machine, db):
    """svchost.exe fora de System32, aberto por cmd.exe, deve virar aviso de disfarce."""
    from app.models.anomaly import Anomaly
    token = machine["agent_token"]
    res = _ingest(client, token, process_starts=[{
        "pid": 999, "name": "svchost.exe", "ppid": 4, "parent_name": "cmd.exe",
        "exe": "C:\\Users\\x\\AppData\\Local\\Temp\\svchost.exe", "signed": "unsigned", "cmdline": "svchost.exe"}])
    assert res.status_code == 202
    anomalies = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).all()
    types = {a.anomaly_type for a in anomalies}
    assert "process_masquerading" in types


def test_canary_event_creates_critical(client, machine, db):
    from app.models.anomaly import Anomaly
    res = client.post("/api/agent/events", headers={"X-Agent-Token": machine["agent_token"]}, json={"events": [{
        "type": "canary_tripped",
        "details": {"files": [{"path": "C:\\Users\\x\\Documents\\isca.docx", "change": "encrypted"}],
                    "suspect_processes": [{"name": "crypt0r.exe", "pid": 5}]}}]})
    assert res.status_code == 200
    a = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"],
                                 Anomaly.anomaly_type == "ransomware_canary").first()
    assert a is not None and a.severity == "critical"
    # A resposta manda capturar a caixa-preta
    assert res.json()["capture_blackbox"] is not None


def test_unexpected_shutdown_detected(client, machine, db):
    from app.models.anomaly import Anomaly
    # 1ª coleta fixa o boot_time
    _ingest(client, machine["agent_token"], boot_time=1000.0)
    # 2ª coleta com boot bem depois + evento de desligamento abrupto do registro
    res = client.post("/api/metrics/ingest",
                      json={**BASE, "boot_time": 99999.0,
                            "events": [{"type": "previous_shutdown", "details": {"kind": "unexpected"}}]},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 202
    a = db.query(Anomaly).filter(Anomaly.anomaly_type == "unexpected_shutdown").first()
    assert a is not None


def test_context_endpoint(client, machine, auth, db):
    from app.models.anomaly import Anomaly
    from app.models.explanation import AIExplanation
    a = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="high", affected_metrics={"cpu": 96})
    db.add(a); db.flush()
    db.add(AIExplanation(anomaly_id=a.id, summary="s", possible_causes=["c"], recommendations=["r"]))
    db.commit()
    res = client.get(f"/api/anomalies/{a.id}/context", headers=auth)
    assert res.status_code == 200
    assert "history" in res.json()


def test_action_requires_ownership(client, machine, auth, db):
    res = client.post(f"/api/actions/machine/{machine['id']}/run",
                      json={"command": "clean_temp", "params": {}}, headers=auth)
    assert res.status_code == 200
    assert "command_id" in res.json()
    # O agente busca o comando pendente
    poll = client.get("/api/agent/commands", headers={"X-Agent-Token": machine["agent_token"]})
    assert any(c["command"] == "clean_temp" for c in poll.json()["commands"])


def test_reputation_grows_with_observation(client, machine, db):
    from app.services import reputation
    _ingest(client, machine["agent_token"], processes=[{
        "pid": 1, "name": "novo.exe", "cpu_percent": 2, "mem_percent": 1, "mem_rss": 1e6, "num_threads": 2,
        "status": "running", "username": "u", "exe": "C:\\x\\novo.exe", "sha256": "a" * 64, "signed": "unsigned"}])
    info = reputation.for_process(db, "novo.exe", "C:\\x\\novo.exe", "a" * 64)
    assert info is not None and info["local_machines"] >= 1


def test_preferences_roundtrip(client, auth):
    r = client.patch("/api/account/preferences",
                     json={"changes": {"language_level": "tecnico"}}, headers=auth)
    assert r.status_code == 200
    assert r.json()["preferences"]["language_level"] == "tecnico"


def test_demo_scenario_runs(client, auth, db):
    from app.models.anomaly import Anomaly
    r = client.post("/api/demo/start", json={"scenario": "cpu_loop", "auto_run": True}, headers=auth)
    assert r.status_code == 200
    session = r.json()
    assert session["status"] in ("running", "done")
    # auto_run roda inline nos testes → deve terminar e ter detectado algo
    status = client.get(f"/api/demo/{session['id']}", headers=auth).json()
    assert status["status"] == "done"
    detected = db.query(Anomaly).filter(Anomaly.machine_id.in_(session["machine_ids"])).count()
    assert detected >= 1
