"""Avaliação em dado real: cruza os rótulos de sessão com os avisos do sistema.

Aviso que interrompeu jogo é alarme falso; teste de minerador só é acerto com a evidência certa.
"""
from datetime import timedelta

import pytest

from app.core.timeutil import aware, utcnow
from tests.test_trust import _machine


def _mark(db, machine, label, when):
    from app.services import activity_labels
    activity_labels.mark(db, machine, label, "tray", now=when)


def _alert(db, machine, when, kind="high_cpu", responsible=None, status=None, programs=None, severity="high"):
    from app.models.anomaly import Anomaly
    from app.models.notification import Notification
    a = Anomaly(machine_id=machine.id, anomaly_type=kind, severity=severity, detected_at=when,
                last_seen_at=when, responsible_process=responsible,
                affected_metrics={"programas": programs} if programs else {})
    db.add(a)
    db.flush()
    if status:
        db.add(Notification(user_id=machine.owner_id, machine_id=machine.id, anomaly_id=a.id, kind="anomaly",
                            severity=severity, title="t", status=status, created_at=when))
    db.commit()
    return a


def _session(result, label):
    return next(s for s in result["sessions"] if s["label"] == label)


class TestLive:
    def test_benign_session_without_alert_is_true_negative(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "jogando", t0)
        _mark(db, m, "parar", t0 + timedelta(hours=1))
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["true_negatives"] == 1 and r["confusion"]["false_positives"] == 0
        assert r["benign"]["interruptions"] == 0
        assert r["benign"]["hours"] == pytest.approx(1.0)

    def test_interrupting_alert_during_game_is_false_positive(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "jogando", t0)
        _mark(db, m, "parar", t0 + timedelta(hours=2))
        _alert(db, m, t0 + timedelta(minutes=30), status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 1
        assert r["benign"]["interruptions"] == 1
        assert r["benign"]["interruptions_per_hour"] == pytest.approx(0.5)
        assert r["benign"]["sessions_with_interruption"] == 1

    def test_alert_recorded_without_interrupting_is_not_annoying(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "jogando", t0)
        _mark(db, m, "parar", t0 + timedelta(hours=1))
        _alert(db, m, t0 + timedelta(minutes=10), status="suppressed", severity="low")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 0
        assert r["confusion"]["false_positives_generated"] == 1

    def test_miner_counts_only_with_right_evidence(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "teste_minerador", t0)
        _mark(db, m, "parar", t0 + timedelta(minutes=30))
        _alert(db, m, t0 + timedelta(minutes=1), kind="unknown_process", responsible="outro.exe", status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert _session(r, "teste_minerador")["detected"] is False
        assert r["confusion"]["false_negatives"] == 1

    def test_detected_miner_records_time(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "teste_minerador_em_uso", t0)
        _mark(db, m, "parar", t0 + timedelta(minutes=30))
        _alert(db, m, t0 + timedelta(minutes=4), kind="background_load", responsible="SVC_UPDATE.EXE", status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        s = _session(r, "teste_minerador_em_uso")
        assert s["detected"] is True and s["interrupted"] is True
        assert s["seconds_to_detection"] == pytest.approx(240)
        assert r["confusion"]["true_positives"] == 1

    def test_aggregated_program_is_also_evidence(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "teste_minerador", t0)
        _mark(db, m, "parar", t0 + timedelta(minutes=30))
        _alert(db, m, t0 + timedelta(minutes=2), kind="unknown_process", responsible="x.exe",
               programs=["x.exe", "svc_update.exe"], status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert _session(r, "teste_minerador")["detected"] is True

    @pytest.mark.parametrize("status,interrupted", [("sent", True), ("grouped", True), ("pending", True),
                                                    ("held", False), ("suppressed", False)])
    def test_interrupted_comes_from_notification_status(self, db, status, interrupted):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "teste_disfarce", t0)
        _mark(db, m, "parar", t0 + timedelta(minutes=20))
        _alert(db, m, t0 + timedelta(minutes=1), kind="process_masquerading", status=status)
        s = _session(real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow()), "teste_disfarce")
        assert s["detected"] is True and s["interrupted"] is interrupted

    def test_session_left_open_ends_after_6_hours(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=10)
        _mark(db, m, "jogando", t0)
        _alert(db, m, t0 + timedelta(hours=7), status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        s = _session(r, "jogando")
        assert s["hours"] == pytest.approx(real_eval.MAX_SESSION_HOURS)
        assert r["confusion"]["false_positives"] == 0

    def test_session_ends_at_next_label(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=5)
        _mark(db, m, "jogando", t0)
        _mark(db, m, "teste_isca", t0 + timedelta(hours=1))
        _mark(db, m, "parar", t0 + timedelta(hours=2))
        _alert(db, m, t0 + timedelta(hours=1, minutes=5), kind="ransomware_canary", status="sent",
               severity="critical")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 0
        assert _session(r, "teste_isca")["detected"] is True

    def test_matrix_matches_sessions(self, db):
        from app.services import real_eval
        m = _machine(db)
        t = utcnow() - timedelta(hours=10)
        for i, label in enumerate(["jogando", "teste_minerador", "trabalho_pesado", "teste_periodico", "uso_normal"]):
            _mark(db, m, label, t + timedelta(hours=i))
        _mark(db, m, "parar", t + timedelta(hours=5))
        _alert(db, m, t + timedelta(hours=3, minutes=5), kind="beaconing", status="sent")
        r = real_eval.live(db, m.id, t - timedelta(hours=1), utcnow())
        c = r["confusion"]
        assert c["true_positives"] + c["false_negatives"] == 2
        assert c["true_negatives"] + c["false_positives"] == 3
        assert (c["true_positives"], c["false_negatives"]) == (1, 1)
        assert c["recall"] == pytest.approx(0.5)


class TestEvidence:
    def test_evidence_table(self):
        from app.services import real_eval
        assert real_eval.EVIDENCE["teste_minerador"] == {"process": "svc_update.exe"}
        assert real_eval.EVIDENCE["teste_minerador_em_uso"] == {"process": "svc_update.exe"}
        assert real_eval.EVIDENCE["teste_disfarce"] == {"type": "process_masquerading"}
        assert real_eval.EVIDENCE["teste_isca"] == {"type": "ransomware_canary"}
        assert real_eval.EVIDENCE["teste_periodico"] == {"type": "beaconing"}
        assert real_eval.INTERRUPTING == {"sent", "grouped", "pending"}


class TestReplay:
    def test_each_config_runs_with_right_switch_and_restores(self, db, monkeypatch):
        from app.services import anomaly_service, benchmark, context, real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _mark(db, m, "jogando", t0)
        _mark(db, m, "parar", t0 + timedelta(hours=1))
        seen = []

        def fake(db_, origin, owner, start, end, warmup_hours=6, limit=None, meta=None):
            seen.append((context.context_on(), anomaly_service.detection_layer()))
            if not context.context_on():
                return [{"type": "high_cpu", "severity": "high", "responsible": "jogo.exe", "programas": [],
                         "detected_at": t0 + timedelta(minutes=5)}]
            return []

        monkeypatch.setattr(benchmark, "replay_window", fake)
        r = real_eval.replay(db, m.id, m.owner_id, t0 - timedelta(hours=1), utcnow())
        assert sorted(seen) == sorted([(True, "ambas"), (False, "ambas"), (True, "regras"), (True, "ml")])
        assert context.context_on() is True and anomaly_service.detection_layer() == "ambas"
        assert r["configs"]["contexto_desligado"]["confusion"]["false_positives"] == 1
        assert r["configs"]["contexto_ligado"]["confusion"]["false_positives"] == 0

    def test_replays_real_readings_on_ephemeral_machine(self, db):
        """Pelo caminho real: aquecimento antes da sessão, só avisos dentro dela."""
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import benchmark
        origin = _machine(db)
        end = utcnow() - timedelta(minutes=5)
        start = end - timedelta(minutes=20)
        n = 180
        first = start - timedelta(hours=1)
        step = (end - first) / n
        for i in range(n):
            ts = first + step * i
            heavy = ts >= start
            met = Metric(machine_id=origin.id, timestamp=ts, cpu_percent=97.0 if heavy else 15.0 + (i % 5),
                         mem_percent=45.0, net_connections=50, process_count=190, cpu_count_logical=8,
                         user_idle_seconds=5.0, foreground_pid=2500, foreground_name="chrome.exe")
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=2500, name="chrome.exe", cpu_percent=8.0, mem_percent=10.0,
                                   exe="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", signed="signed",
                                   ancestors=[1500]))
            if heavy:
                db.add(ProcessSnapshot(metric_id=met.id, pid=6600, name="svc_update.exe", cpu_percent=760.0,
                                       mem_percent=4.0, exe="C:\\Users\\v\\AppData\\Local\\svc_update.exe",
                                       signed="unsigned", ancestors=[1500]))
        db.commit()
        before = db.query(Machine).count()
        alerts = benchmark.replay_window(db, origin.id, origin.owner_id, start, end, warmup_hours=1)
        assert db.query(Machine).count() == before
        assert alerts, "o minerador deveria gerar algum aviso"
        for a in alerts:
            assert start <= a["detected_at"] <= end
            assert {"type", "severity", "responsible", "programas", "user_driven"} <= set(a)
        assert any(a["responsible"] == "svc_update.exe" or "svc_update.exe" in a["programas"] for a in alerts)

    def test_replay_carries_pid_and_ancestors(self):
        from types import SimpleNamespace
        from app.services import benchmark
        snap = SimpleNamespace(name="a.exe", pid=7, ancestors=[3, 1], cpu_percent=1.0, mem_percent=1.0, exe=None,
                               signed=None, publisher=None, username=None, cmdline=None, sha256=None,
                               ppid=3, parent_name="b.exe")
        proc = benchmark._replay_proc(snap)
        assert proc["pid"] == 7 and proc["ancestors"] == [3, 1] and proc["sha256"] is None


def test_benchmark_machine_never_really_notifies(db):
    """A reprodução dura minutos: sem isto, cada aviso reproduzido virava mensagem no celular."""
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.services import notifications
    m = _machine(db)
    bench = Machine(name="[BENCH] reproducao", hostname="b", agent_token="tok-bench-n", owner_id=m.owner_id)
    db.add(bench)
    db.flush()
    a = Anomaly(machine_id=bench.id, anomaly_type="high_cpu", severity="critical", detected_at=utcnow())
    db.add(a)
    db.commit()
    assert notifications.on_anomaly(db, a).status == "suppressed"


class TestEndpoint:
    def test_owner_sees_evaluation(self, client, machine, auth):
        res = client.get(f"/api/evaluation/real/{machine['id']}?days=7", headers=auth)
        assert res.status_code == 200
        body = res.json()
        assert "live" in body and "replay" in body
        assert body["live"]["confusion"]["true_positives"] == 0

    def test_other_user_cannot_see(self, client, machine):
        client.post("/api/auth/register", json={"email": "z@z.com", "username": "zz", "password": "zzsenha12345"})
        tok = client.post("/api/auth/login", data={"username": "zz", "password": "zzsenha12345"}).json()["access_token"]
        res = client.get(f"/api/evaluation/real/{machine['id']}", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 404

    def test_replay_runs_in_background(self, client, machine, auth, monkeypatch):
        from app.services import real_eval
        monkeypatch.setattr(real_eval, "replay", lambda *a, **k: {"configs": {}, "sentence": "ok"})
        res = client.post(f"/api/evaluation/real/{machine['id']}/replay?days=7", headers=auth)
        assert res.status_code == 200 and res.json()["started"] is True
        body = client.get(f"/api/evaluation/real/{machine['id']}?days=7", headers=auth).json()
        assert body["replay"]["status"] == "done"


class TestPerThreadSwitches:
    """A reprodução troca contexto e camada só na própria thread; a coleta ao vivo não pode sentir isso."""

    def _in_other_thread(self, fn):
        import threading
        seen_value = {}
        t = threading.Thread(target=lambda: seen_value.setdefault("v", fn()))
        t.start()
        t.join()
        return seen_value["v"]

    def test_context_off_in_thread_does_not_leak(self):
        from app.services import context
        previous = context.set_context_mode(False)
        try:
            assert self._in_other_thread(context.context_on) is True
        finally:
            context.set_context_mode(previous)

    def test_layer_switch_in_thread_does_not_leak(self):
        from app.services import anomaly_service
        previous = anomaly_service.set_detection_layer("ml")
        try:
            assert self._in_other_thread(anomaly_service.detection_layer) == "ambas"
        finally:
            anomaly_service.set_detection_layer(previous)


def test_long_task_does_not_use_chat_queue(monkeypatch):
    """A reprodução leva dezenas de minutos; os 2 workers da fila são das conversas e diagnósticos."""
    import threading
    from app.services import jobs

    def forbidden(*a, **k):
        raise AssertionError("tarefa longa não pode entrar no executor compartilhado")

    monkeypatch.setattr(jobs, "RUN_INLINE", False)
    monkeypatch.setattr(jobs._executor, "submit", forbidden)
    done = threading.Event()
    jobs.submit_long(lambda db: done.set())
    assert done.wait(5)


class TestReplayTruncation:
    """Janela longa não pode descartar as sessões mais novas em silêncio."""

    def test_replay_window_covers_end_and_flags_truncation(self, db):
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import benchmark
        origin = _machine(db)
        base = utcnow() - timedelta(hours=3)
        step = timedelta(minutes=1)
        for i in range(30):
            ts = base + step * i
            met = Metric(machine_id=origin.id, timestamp=ts, cpu_percent=15.0 + (i % 5), mem_percent=40.0,
                         net_connections=50, process_count=190, cpu_count_logical=8,
                         user_idle_seconds=5.0, foreground_pid=2500, foreground_name="chrome.exe")
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=2500, name="chrome.exe", cpu_percent=8.0, mem_percent=10.0,
                                   exe="C:\\x\\chrome.exe", signed="signed", ancestors=[1500]))
        db.commit()
        meta = {}
        benchmark.replay_window(db, origin.id, origin.owner_id, base, base + step * 29, warmup_hours=1,
                                limit=10, meta=meta)
        assert meta["truncated"] is True
        # Mantém as 10 MAIS NOVAS (i=20..29): a cobertura começa na 20ª leitura
        assert meta["covered_from"] == aware(base + step * 20)

    def test_no_truncation_no_flag(self, db):
        from app.models.metric import Metric
        from app.services import benchmark
        origin = _machine(db)
        base = utcnow() - timedelta(hours=2)
        for i in range(5):
            db.add(Metric(machine_id=origin.id, timestamp=base + timedelta(minutes=i), cpu_percent=15.0,
                          mem_percent=40.0, cpu_count_logical=8))
        db.commit()
        meta = {}
        benchmark.replay_window(db, origin.id, origin.owner_id, base, base + timedelta(minutes=4),
                                warmup_hours=1, limit=10, meta=meta)
        assert meta["truncated"] is False and meta["covered_from"] is None

    def test_replay_excludes_sessions_outside_coverage(self, db, monkeypatch):
        from app.services import benchmark, real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=6)
        _mark(db, m, "jogando", t0)                                   # sessão perdida (antes do corte)
        _mark(db, m, "teste_minerador", t0 + timedelta(hours=3))      # sessão coberta
        _mark(db, m, "parar", t0 + timedelta(hours=4))
        cutoff = t0 + timedelta(hours=2)

        def fake(db_, origin, owner, start, end, warmup_hours=6, limit=None, meta=None):
            if meta is not None:
                meta["truncated"] = True
                meta["covered_from"] = cutoff
            return []

        monkeypatch.setattr(benchmark, "replay_window", fake)
        r = real_eval.replay(db, m.id, m.owner_id, t0 - timedelta(hours=1), utcnow())
        assert r["truncated"] is True and r["covered_from"] == cutoff
        # A sessão de jogo (antes do corte) não entra na conta de nenhuma config
        for cfg in r["configs"].values():
            assert cfg["benign"]["sessions"] == 0
            assert cfg["confusion"]["true_positives"] + cfg["confusion"]["false_negatives"] == 1
