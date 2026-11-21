"""A ingestão não pode parar por causa de um detector.

Caso real: um `datetime` no JSON do aviso de beaconing fazia a ingestão responder 500
e o agente reenviava a mesma leitura para sempre.
"""
from datetime import datetime, timezone

from tests.test_pipeline import BASE

BEACON = {
    "process": "beacon.exe", "remote_ip": "8.8.8.8", "remote_port": 443,
    "events": 10, "median_interval": 240.0, "jitter": 0.05,
}


def _ingest(client, token, **over):
    return client.post("/api/metrics/ingest", json={**BASE, **over}, headers={"X-Agent-Token": token})


def test_known_program_beacon_becomes_alert(client, machine, db):
    from app.models.anomaly import Anomaly
    from app.models.identity import ProcessIdentity

    # Programa já visto neste computador: é o caminho que punha a data no JSON
    db.add(ProcessIdentity(machine_id=machine["id"], name="beacon.exe", signed="unsigned",
                           first_seen=datetime.now(timezone.utc), seen_count=5))
    db.commit()

    res = _ingest(client, machine["agent_token"], beacons=[BEACON])

    assert res.status_code == 202
    alert = db.query(Anomaly).filter(Anomaly.anomaly_type == "beaconing").first()
    assert alert is not None
    assert alert.responsible_process == "beacon.exe"


def test_broken_detector_does_not_break_ingestion(client, machine, db, monkeypatch):
    from app.models.metric import Metric
    from app.services import agent_events

    def broken(*args, **kwargs):
        raise RuntimeError("defeito simulado no detector")

    monkeypatch.setattr(agent_events, "evaluate_beacons", broken)

    res = _ingest(client, machine["agent_token"], beacons=[BEACON])

    # A leitura foi aceita e o agente recebe a resposta normal (intervalo,
    # comandos); o aviso que falhou fica só no log do servidor.
    assert res.status_code == 202
    assert "next_interval" in res.json()
    assert db.query(Metric).filter(Metric.machine_id == machine["id"]).count() == 1
