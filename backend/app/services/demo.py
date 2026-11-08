"""Modo demonstração: um computador falso cujas leituras sintéticas passam pelo MESMO caminho
de ingestão das reais (detectores, modelo, IA, incidentes, notificações)."""
import math
import random
import secrets
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS, SEVERITY_LABELS
from app.core.timeutil import utcnow
from app.models.demo import DemoSession
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.user import User

INTERVAL = 30  # segundos "virtuais" entre leituras injetadas

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "cpu_loop": {"label": "Programa travado no processador", "warmup": 12, "attack": 8,
                 "expect": "cpu_loop"},
    "memory_leak": {"label": "Vazamento de memória", "warmup": 12, "attack": 12, "expect": "memory_leak"},
    "ransomware": {"label": "Sequestro de dados (ransomware)", "warmup": 8, "attack": 4, "expect": "ransomware_canary"},
    # Passos de uma hora virtual: a previsão de disco exige meio dia de histórico.
    "disk_filling": {"label": "Disco enchendo rápido", "warmup": 20, "attack": 10, "expect": "disk_forecast",
                     "interval": 3600},
    "masquerade": {"label": "Vírus disfarçado de svchost.exe", "warmup": 8, "attack": 3, "expect": "process_masquerading"},
    "beaconing": {"label": "Programa contatando servidor em intervalos", "warmup": 8, "attack": 8, "expect": "beaconing"},
}

NORMAL_PROCS = [
    ("explorer.exe", 1.5, 2.0, "C:\\Windows\\explorer.exe", "signed"),
    ("chrome.exe", 8.0, 12.0, "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "signed"),
    ("Code.exe", 4.0, 6.0, "C:\\Users\\demo\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe", "signed"),
    ("Spotify.exe", 1.0, 3.0, "C:\\Users\\demo\\AppData\\Roaming\\Spotify\\Spotify.exe", "signed"),
    ("svchost.exe", 0.5, 1.0, "C:\\Windows\\System32\\svchost.exe", "signed"),
]


# Tudo aberto pela pessoa descende do explorer.exe; o svchost vem do services.exe.
NORMAL_PIDS = {"explorer.exe": 1500, "chrome.exe": 2500, "Code.exe": 3100, "Spotify.exe": 3400,
               "svchost.exe": 900}
NORMAL_ANCESTORS = {"explorer.exe": [700], "chrome.exe": [1500, 700], "Code.exe": [1500, 700],
                    "Spotify.exe": [1500, 700], "svchost.exe": [640, 4]}


def _base_metric(step: int) -> Dict[str, Any]:
    wave = math.sin(step / 4) * 6
    return {
        # Sem `random` de propósito: mudar a sequência do gerador mudaria os números já publicados.
        "user_idle_seconds": 3.0 + (step % 9) * 6,
        "foreground_pid": NORMAL_PIDS["chrome.exe"],
        "foreground_name": "chrome.exe",
        "cpu_percent": max(3.0, 14 + wave + random.uniform(-3, 3)),
        "mem_percent": 46 + math.sin(step / 6) * 4 + random.uniform(-2, 2),
        "disk_percent": 58.0,
        "swap_percent": 8.0,
        "net_bytes_sent": random.uniform(2e4, 8e4),
        "net_bytes_recv": random.uniform(1e5, 3e5),
        "net_connections": random.randint(40, 70),
        "disk_read_bytes": random.uniform(2e4, 9e4),
        "disk_write_bytes": random.uniform(2e4, 9e4),
        "disk_used": 58.0 * 5e9,
        "disk_free": 42.0 * 5e9,
        "mem_used": 0.46 * 16 * 1024 ** 3,
        "mem_available": 0.54 * 16 * 1024 ** 3,
        "mem_total": 16 * 1024 ** 3,
        "load_avg_1": 1.0 + wave / 10,
        "process_count": random.randint(180, 210),
        "cpu_count_logical": 8,
        "cpu_freq_current": 3200,
        "cpu_freq_max": 4200,
        "uptime_seconds": 3600 + step * INTERVAL,
        "temperatures": {"coretemp": [{"label": "Package", "current": 52 + wave}]},
    }


def _normal_processes() -> List[Dict[str, Any]]:
    out = []
    for name, cpu_b, mem_b, exe, signed in NORMAL_PROCS:
        out.append({"name": name, "cpu_percent": max(0, cpu_b + random.uniform(-1, 1)),
                    "mem_percent": max(0, mem_b + random.uniform(-1, 1)), "exe": exe, "signed": signed,
                    "publisher": "Microsoft" if signed == "signed" and "svchost" in name else "—",
                    "username": "demo", "pid": NORMAL_PIDS[name], "ancestors": NORMAL_ANCESTORS[name]})
    return out


def _scenario_step(scenario: str, phase: str, k: int, metric: Dict, procs: List[Dict]) -> Dict[str, Any]:
    events, beacons, starts = [], [], []
    if phase == "warmup":
        return {"events": events, "beacons": beacons, "process_starts": starts}
    if scenario == "cpu_loop":
        metric["cpu_percent"] = 96 + random.uniform(-2, 2)
        metric["load_avg_1"] = 8.0
        procs.append({"name": "runaway.exe", "cpu_percent": 99.0, "mem_percent": 2.0,
                      "exe": "C:\\Users\\demo\\Downloads\\runaway.exe", "signed": "unsigned", "username": "demo",
                      "cmdline": "runaway.exe"})
    elif scenario == "memory_leak":
        metric["mem_percent"] = min(46 + k * 4.0, 96)
        procs.append({"name": "leaky_app.exe", "cpu_percent": 6.0, "mem_percent": min(4 + k * 4.0, 55),
                      "exe": "C:\\Program Files\\LeakyApp\\leaky_app.exe", "signed": "signed", "username": "demo"})
    elif scenario == "disk_filling":
        # Mantém o tamanho do disco da leitura-base, senão o uso em GB cai enquanto o percentual sobe.
        total = metric["disk_used"] + metric["disk_free"]
        metric["disk_percent"] = min(58 + k * 3.5, 99)
        metric["disk_used"] = metric["disk_percent"] / 100 * total
        metric["disk_free"] = total - metric["disk_used"]
    elif scenario == "masquerade":
        procs.append({"name": "svchost.exe", "cpu_percent": 35.0, "mem_percent": 4.0,
                      "exe": "C:\\Users\\demo\\AppData\\Local\\Temp\\svchost.exe", "signed": "unsigned",
                      "username": "demo", "cmdline": "svchost.exe -k netsvcs"})
    elif scenario == "beaconing":
        metric["net_connections"] += 2
        # IP público real (scanme.nmap.org): o detector exige destino público e o Python
        # classifica as faixas de documentação da RFC 5737 como privadas.
        beacons.append({"process": "updater_x.exe", "exe": "C:\\Users\\demo\\AppData\\Roaming\\updater_x.exe",
                        "remote_ip": "45.33.32.156", "remote_port": 443, "events": 6 + k,
                        "median_interval": 60.0, "jitter": 0.03})
        procs.append({"name": "updater_x.exe", "cpu_percent": 1.5, "mem_percent": 1.0,
                      "exe": "C:\\Users\\demo\\AppData\\Roaming\\updater_x.exe", "signed": "unsigned", "username": "demo"})
    elif scenario == "ransomware":
        if k == 0:
            events.append({"type": "canary_tripped", "details": {
                "files": [{"path": "C:\\Users\\demo\\Documents\\_isca_1.docx", "change": "encrypted"},
                          {"path": "C:\\Users\\demo\\Documents\\_isca_2.xlsx", "change": "renamed"}],
                "suspect_processes": [{"name": "crypt0r.exe", "pid": 6644}]}})
        procs.append({"name": "crypt0r.exe", "cpu_percent": 45.0, "mem_percent": 6.0,
                      "exe": "C:\\Users\\demo\\AppData\\Local\\Temp\\crypt0r.exe", "signed": "unsigned",
                      "username": "demo", "cmdline": "crypt0r.exe --all"})
        metric["disk_write_bytes"] = 8e7
    return {"events": events, "beacons": beacons, "process_starts": starts}


def start(db: Session, user: User, scenario: str) -> DemoSession:
    if scenario not in SCENARIOS:
        raise ValueError("Cenário desconhecido")
    spec = SCENARIOS[scenario]
    machine = Machine(
        name=f"[DEMO] {spec['label']}",
        hostname=f"demo-{scenario}-{secrets.token_hex(2)}",
        os_type="Windows", os_version="11", os_pretty="Windows 11 Pro (demonstração)",
        agent_token=secrets.token_urlsafe(24), owner_id=user.id, is_active=True, is_demo=True,
        last_seen=utcnow(),
        system_info={"form_factor": "desktop", "is_admin": True, "cpu_model": "Demo CPU", "tz_offset_minutes": -180},
    )
    db.add(machine)
    db.flush()
    session = DemoSession(user_id=user.id, scenario=scenario, status="running", machine_ids=[machine.id],
                          total_steps=spec["warmup"] + spec["attack"], state={"machine_id": machine.id},
                          log=[f"Computador de demonstração criado: {machine.name}"])
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def step(db: Session, session: DemoSession) -> Dict[str, Any]:
    """Injeta uma leitura. Chamado repetidamente pelo agendador da demo ou pelo botão "avançar"."""
    from app.routers.metrics import metric_payload, anomaly_ws_payload
    from app.core.websocket import manager
    from app.services.anomaly_service import process_metric
    from app.services import agent_events
    import asyncio

    spec = SCENARIOS[session.scenario]
    machine = db.query(Machine).filter(Machine.id == session.state["machine_id"]).first()
    if not machine or session.status != "running":
        return {"done": True}

    k = session.step
    phase = "warmup" if k < spec["warmup"] else "attack"
    attack_k = k - spec["warmup"] if phase == "attack" else 0

    # Tempo virtual: leituras espaçadas de INTERVAL no passado→agora para as janelas dos detectores fecharem
    virtual_ts = utcnow() - timedelta(seconds=(session.total_steps - k) * spec.get("interval", INTERVAL))
    data = _base_metric(k)
    procs = _normal_processes()
    extra = _scenario_step(session.scenario, phase, attack_k, data, procs)

    metric = Metric(machine_id=machine.id, timestamp=virtual_ts, **data)
    db.add(metric)
    db.flush()
    for p in procs:
        db.add(ProcessSnapshot(metric_id=metric.id, timestamp=virtual_ts, **{
            "name": p["name"], "cpu_percent": p.get("cpu_percent", 0), "mem_percent": p.get("mem_percent", 0),
            "mem_rss": p.get("mem_percent", 0) / 100 * 16 * 1024 ** 3, "num_threads": 8, "status": "running",
            "username": p.get("username"), "exe": p.get("exe"), "signed": p.get("signed"),
            "publisher": p.get("publisher"), "cmdline": p.get("cmdline")}))
    machine.last_seen = utcnow()
    db.commit()
    db.refresh(metric)

    created = []
    a = process_metric(metric, machine, db, process_starts=extra["process_starts"])
    if a:
        created.append(a)
    if extra["events"]:
        created += agent_events.handle_events(db, machine, extra["events"], metric, virtual_ts)
    if extra["beacons"]:
        created += agent_events.evaluate_beacons(db, machine, extra["beacons"], virtual_ts)
    if session.scenario == "disk_filling" and phase == "attack":
        # Mesma reconferência que o agendador faz em produção; quem cria o aviso é o check_machine.
        from app.services import forecasting
        forecast_anomaly = forecasting.check_machine(db, machine)
        if forecast_anomaly is not None:
            created.append(forecast_anomaly)
        if attack_k == spec["attack"] - 1:
            f = forecasting.disk_forecast(db, machine)
            session.log = (session.log or []) + [f"Previsão de disco: {f.get('sentence') or f.get('reason')}"]

    log = list(session.log or [])
    for anomaly in created:
        # O log aparece na tela da demonstração: nome do aviso como a pessoa o vê.
        label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
        sev = SEVERITY_LABELS.get(anomaly.severity, anomaly.severity).lower()
        log.append(f"Leitura {k + 1} · aviso: {label} (gravidade {sev})")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast_metric(machine.id, metric_payload(metric)))
            for anomaly in created:
                loop.create_task(manager.broadcast_anomaly(machine.id, machine.owner_id, anomaly_ws_payload(anomaly)))
    except Exception:
        pass

    session.step = k + 1
    session.log = log[-40:]
    if session.step >= session.total_steps:
        session.status = "done"
        session.finished_at = utcnow()
    db.commit()
    return {"done": session.status == "done", "step": session.step, "total": session.total_steps,
            "detected": [a.anomaly_type for a in created]}


def run_to_completion(db: Session, session_id: int):
    """Executa todos os passos em segundo plano (usado pelo botão "rodar demonstração")."""
    session = db.query(DemoSession).filter(DemoSession.id == session_id).first()
    guard = 0
    while session and session.status == "running" and guard < 100:
        step(db, session)
        db.refresh(session)
        guard += 1


def cleanup(db: Session, session: DemoSession):
    from app.routers.machines import delete_machine_cascade
    for mid in session.machine_ids or []:
        machine = db.query(Machine).filter(Machine.id == mid, Machine.is_demo == True).first()  # noqa: E712
        if machine:
            delete_machine_cascade(mid, db)
    session.status = "stopped"
    db.commit()
