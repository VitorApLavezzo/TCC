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


def _processo(**over):
    base = {"pid": 500, "name": "avp.exe", "cpu_percent": 68.0, "mem_percent": 6.0, "mem_rss": 4e8,
            "num_threads": 30, "status": "running", "username": "SYSTEM",
            "exe": "C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
            "signed": "signed", "publisher": "Kaspersky Lab JSC", "cmdline": "avp.exe -scan",
            "ppid": 4, "parent_name": "services.exe", "sha256": "d" * 64}
    return {**base, **over}


def _maquina_formada(db, machine_id, leituras=150, horas=7, net=50000):
    """Máquina além do período de aprendizado: histórico de rede e um baseline
    de processos já estabelecido, senão o detector de processo desconhecido
    nem chega a rodar e o teste passaria por engano."""
    from datetime import timedelta
    from app.core.timeutil import utcnow
    from app.models.metric import Metric
    from app.models.process_baseline import ProcessBaseline
    agora = utcnow()
    passo = timedelta(hours=horas) / leituras
    for i in range(leituras):
        db.add(Metric(machine_id=machine_id, cpu_percent=20, mem_percent=40,
                      net_bytes_sent=net, net_bytes_recv=net,
                      timestamp=agora - timedelta(hours=horas) + passo * i))
    for nome in ("explorer.exe", "chrome.exe", "Code.exe"):
        db.add(ProcessBaseline(machine_id=machine_id, process_name=nome, seen_count=40,
                               is_known=True, avg_cpu=4.0, max_cpu=30.0,
                               avg_mem_percent=3.0, max_mem_percent=10.0))
    db.commit()


def test_antivirus_varrendo_nao_vira_aviso_de_malware(client, machine, db):
    """O caso relatado, pelo caminho real da ingestão: varredura de antivírus
    é processador alto + rede alta + privilégio, e nada disso é evidência."""
    from app.models.anomaly import Anomaly
    _maquina_formada(db, machine["id"])
    res = _ingest(client, machine["agent_token"], cpu_percent=72.0,
                  net_bytes_sent=50000, net_bytes_recv=50000, processes=[_processo()])
    assert res.status_code == 202
    # Nenhum aviso, não "nenhum aviso daquele tipo": só o candidato mais grave
    # de cada coleta vira linha no banco, então conferir um tipo específico
    # passaria por acidente sempre que outro detector chegasse na frente.
    assert db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).all() == []


def test_minerador_no_mesmo_cenario_continua_sendo_pego(client, machine, db):
    """A contraprova: mesma máquina, mesma carga, executável diferente."""
    from app.models.anomaly import Anomaly
    _maquina_formada(db, machine["id"])
    minerador = _processo(name="xmrig.exe", exe="C:\\Users\\vitor\\AppData\\Local\\Temp\\xmrig.exe",
                          signed="unsigned", publisher=None, username="vitor", cpu_percent=95.0)
    res = _ingest(client, machine["agent_token"], cpu_percent=96.0,
                  net_bytes_sent=4e6, net_bytes_recv=4e6, processes=[minerador])
    assert res.status_code == 202
    tipos = {a.anomaly_type for a in db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).all()}
    assert tipos & {"malware_pattern", "suspicious_process"}


def test_primeiras_coletas_nao_geram_notificacao(client, machine, db):
    """Máquina recém-instalada: o que for detectado fica no painel, calado."""
    from app.models.notification import Notification
    for _ in range(3):
        _ingest(client, machine["agent_token"], cpu_percent=99.0, mem_percent=97.0,
                processes=[_processo(name="estranho.exe", exe="C:\\Users\\v\\Downloads\\estranho.exe",
                                     signed="unsigned", publisher=None, username="v")])
    entregues = db.query(Notification).filter(Notification.status == "pending").all()
    assert entregues == []


def test_mesmo_programa_sem_assinatura_vira_processo_desconhecido(client, machine, db):
    """Contraprova da camada de confiança pelo caminho real: o que separa este
    caso do anterior é só a identidade do executável, não o comportamento."""
    from app.models.anomaly import Anomaly
    _maquina_formada(db, machine["id"])
    # Mesmo nome, mesma carga, mesmo privilégio — muda só de onde ele roda e
    # o fato de ninguém ter assinado. Sem indício concreto, para não cair no
    # detector de malware e mascarar o que este teste quer provar.
    pirata = _processo(name="avp.exe", exe="D:\\apps\\avp.exe",
                       signed="unknown", publisher=None)
    # Rede no mesmo patamar do histórico: sem pico, para que nenhum detector
    # mais grave roube o lugar de principal e esconda o que se quer medir.
    res = _ingest(client, machine["agent_token"], cpu_percent=72.0,
                  net_bytes_sent=50000, net_bytes_recv=50000, processes=[pirata])
    assert res.status_code == 202
    tipos = {a.anomaly_type for a in db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).all()}
    assert "unknown_process" in tipos


def test_demonstracao_continua_detectando(client, auth, db):
    """A demonstração da banca tem 8 a 20 passos de aquecimento — bem menos que
    o período de aprendizado. Ela é isenta, e isto prova que continua isenta."""
    from app.models.anomaly import Anomaly
    from app.services import demo
    from app.models.demo import DemoSession

    for cenario in ("cpu_loop", "memory_leak", "masquerade", "beaconing"):
        res = client.post("/api/demo/start", json={"scenario": cenario, "auto_run": False}, headers=auth)
        assert res.status_code == 200
        sessao = db.query(DemoSession).filter(DemoSession.id == res.json()["id"]).first()
        for _ in range(sessao.total_steps):
            demo.step(db, sessao)
            db.refresh(sessao)
        machine_id = sessao.machine_ids[0]
        tipos = {a.anomaly_type for a in db.query(Anomaly).filter(Anomaly.machine_id == machine_id).all()}
        assert demo.SCENARIOS[cenario]["expect"] in tipos, f"{cenario} parou de detectar: {tipos}"
