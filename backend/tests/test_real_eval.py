"""
Avaliação em dado real: o resultado do TCC.

Cruza o que a pessoa marcou que estava fazendo (os rótulos de sessão) com o
que o sistema avisou. Sessão de jogo com aviso que interrompeu é alarme falso;
teste de minerador só conta como acerto com a evidência certa — um aviso sobre
outro programa, no mesmo horário, não é ter visto o minerador.
"""
from datetime import timedelta

import pytest

from app.core.timeutil import utcnow
from tests.test_trust import _machine


def _marcar(db, machine, label, quando):
    from app.services import activity_labels
    activity_labels.mark(db, machine, label, "tray", now=quando)


def _aviso(db, machine, quando, tipo="high_cpu", responsavel=None, status=None, programas=None, severidade="high"):
    from app.models.anomaly import Anomaly
    from app.models.notification import Notification
    a = Anomaly(machine_id=machine.id, anomaly_type=tipo, severity=severidade, detected_at=quando,
                last_seen_at=quando, responsible_process=responsavel,
                affected_metrics={"programas": programas} if programas else {})
    db.add(a)
    db.flush()
    if status:
        db.add(Notification(user_id=machine.owner_id, machine_id=machine.id, anomaly_id=a.id, kind="anomaly",
                            severity=severidade, title="t", status=status, created_at=quando))
    db.commit()
    return a


def _sessao(resultado, label):
    return next(s for s in resultado["sessions"] if s["label"] == label)


class TestAoVivo:
    def test_sessao_benigna_sem_aviso_e_acerto_negativo(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "jogando", t0)
        _marcar(db, m, "parar", t0 + timedelta(hours=1))
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["true_negatives"] == 1 and r["confusion"]["false_positives"] == 0
        assert r["benign"]["interruptions"] == 0
        assert r["benign"]["hours"] == pytest.approx(1.0)

    def test_aviso_que_interrompeu_no_jogo_e_falso_positivo(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "jogando", t0)
        _marcar(db, m, "parar", t0 + timedelta(hours=2))
        _aviso(db, m, t0 + timedelta(minutes=30), status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 1
        assert r["benign"]["interruptions"] == 1
        assert r["benign"]["interruptions_per_hour"] == pytest.approx(0.5)
        assert r["benign"]["sessions_with_interruption"] == 1

    def test_aviso_registrado_sem_interromper_nao_e_alarme_que_incomoda(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "jogando", t0)
        _marcar(db, m, "parar", t0 + timedelta(hours=1))
        _aviso(db, m, t0 + timedelta(minutes=10), status="suppressed", severidade="low")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 0
        assert r["confusion"]["false_positives_generated"] == 1

    def test_minerador_so_conta_com_a_evidencia_certa(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "teste_minerador", t0)
        _marcar(db, m, "parar", t0 + timedelta(minutes=30))
        _aviso(db, m, t0 + timedelta(minutes=1), tipo="unknown_process", responsavel="outro.exe", status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert _sessao(r, "teste_minerador")["detected"] is False
        assert r["confusion"]["false_negatives"] == 1

    def test_minerador_detectado_registra_o_tempo(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "teste_minerador_em_uso", t0)
        _marcar(db, m, "parar", t0 + timedelta(minutes=30))
        _aviso(db, m, t0 + timedelta(minutes=4), tipo="background_load", responsavel="SVC_UPDATE.EXE", status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        s = _sessao(r, "teste_minerador_em_uso")
        assert s["detected"] is True and s["interrupted"] is True
        assert s["seconds_to_detection"] == pytest.approx(240)
        assert r["confusion"]["true_positives"] == 1

    def test_programa_agregado_tambem_e_evidencia(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "teste_minerador", t0)
        _marcar(db, m, "parar", t0 + timedelta(minutes=30))
        _aviso(db, m, t0 + timedelta(minutes=2), tipo="unknown_process", responsavel="x.exe",
               programas=["x.exe", "svc_update.exe"], status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert _sessao(r, "teste_minerador")["detected"] is True

    @pytest.mark.parametrize("status,interrompeu", [("sent", True), ("grouped", True), ("pending", True),
                                                    ("held", False), ("suppressed", False)])
    def test_interrompeu_vem_do_status_da_notificacao(self, db, status, interrompeu):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "teste_disfarce", t0)
        _marcar(db, m, "parar", t0 + timedelta(minutes=20))
        _aviso(db, m, t0 + timedelta(minutes=1), tipo="process_masquerading", status=status)
        s = _sessao(real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow()), "teste_disfarce")
        assert s["detected"] is True and s["interrupted"] is interrompeu

    def test_sessao_esquecida_aberta_termina_em_6_horas(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=10)
        _marcar(db, m, "jogando", t0)
        _aviso(db, m, t0 + timedelta(hours=7), status="sent")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        s = _sessao(r, "jogando")
        assert s["hours"] == pytest.approx(real_eval.MAX_SESSION_HOURS)
        assert r["confusion"]["false_positives"] == 0

    def test_sessao_termina_no_proximo_rotulo(self, db):
        from app.services import real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=5)
        _marcar(db, m, "jogando", t0)
        _marcar(db, m, "teste_isca", t0 + timedelta(hours=1))
        _marcar(db, m, "parar", t0 + timedelta(hours=2))
        _aviso(db, m, t0 + timedelta(hours=1, minutes=5), tipo="ransomware_canary", status="sent",
               severidade="critical")
        r = real_eval.live(db, m.id, t0 - timedelta(hours=1), utcnow())
        assert r["confusion"]["false_positives"] == 0
        assert _sessao(r, "teste_isca")["detected"] is True

    def test_matriz_bate_com_as_sessoes(self, db):
        from app.services import real_eval
        m = _machine(db)
        t = utcnow() - timedelta(hours=10)
        for i, label in enumerate(["jogando", "teste_minerador", "trabalho_pesado", "teste_periodico", "uso_normal"]):
            _marcar(db, m, label, t + timedelta(hours=i))
        _marcar(db, m, "parar", t + timedelta(hours=5))
        _aviso(db, m, t + timedelta(hours=3, minutes=5), tipo="beaconing", status="sent")
        r = real_eval.live(db, m.id, t - timedelta(hours=1), utcnow())
        c = r["confusion"]
        assert c["true_positives"] + c["false_negatives"] == 2
        assert c["true_negatives"] + c["false_positives"] == 3
        assert (c["true_positives"], c["false_negatives"]) == (1, 1)
        assert c["recall"] == pytest.approx(0.5)


class TestEvidencia:
    def test_tabela_de_evidencias(self):
        from app.services import real_eval
        assert real_eval.EVIDENCE["teste_minerador"] == {"process": "svc_update.exe"}
        assert real_eval.EVIDENCE["teste_minerador_em_uso"] == {"process": "svc_update.exe"}
        assert real_eval.EVIDENCE["teste_disfarce"] == {"type": "process_masquerading"}
        assert real_eval.EVIDENCE["teste_isca"] == {"type": "ransomware_canary"}
        assert real_eval.EVIDENCE["teste_periodico"] == {"type": "beaconing"}
        assert real_eval.INTERRUPTING == {"sent", "grouped", "pending"}


class TestReproducao:
    def test_cada_configuracao_roda_com_a_chave_certa_e_tudo_e_restaurado(self, db, monkeypatch):
        from app.services import anomaly_service, benchmark, context, real_eval
        m = _machine(db)
        t0 = utcnow() - timedelta(hours=3)
        _marcar(db, m, "jogando", t0)
        _marcar(db, m, "parar", t0 + timedelta(hours=1))
        vistos = []

        def falso(db_, origem, dono, inicio, fim, warmup_hours=6):
            vistos.append((context.context_on(), anomaly_service.detection_layer()))
            if not context.context_on():
                return [{"type": "high_cpu", "severity": "high", "responsible": "jogo.exe", "programas": [],
                         "detected_at": t0 + timedelta(minutes=5)}]
            return []

        monkeypatch.setattr(benchmark, "replay_window", falso)
        r = real_eval.replay(db, m.id, m.owner_id, t0 - timedelta(hours=1), utcnow())
        assert sorted(vistos) == sorted([(True, "ambas"), (False, "ambas"), (True, "regras"), (True, "ml")])
        assert context.context_on() is True and anomaly_service.detection_layer() == "ambas"
        assert r["configs"]["contexto_desligado"]["confusion"]["false_positives"] == 1
        assert r["configs"]["contexto_ligado"]["confusion"]["false_positives"] == 0

    def test_reproduz_leituras_reais_numa_maquina_efemera(self, db):
        """Pelo caminho real: aquecimento antes da sessão, só avisos dentro dela."""
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import benchmark
        origem = _machine(db)
        fim = utcnow() - timedelta(minutes=5)
        inicio = fim - timedelta(minutes=20)
        n = 180
        primeira = inicio - timedelta(hours=1)
        passo = (fim - primeira) / n
        for i in range(n):
            ts = primeira + passo * i
            pesado = ts >= inicio
            met = Metric(machine_id=origem.id, timestamp=ts, cpu_percent=97.0 if pesado else 15.0 + (i % 5),
                         mem_percent=45.0, net_connections=50, process_count=190, cpu_count_logical=8,
                         user_idle_seconds=5.0, foreground_pid=2500, foreground_name="chrome.exe")
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=2500, name="chrome.exe", cpu_percent=8.0, mem_percent=10.0,
                                   exe="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", signed="signed",
                                   ancestors=[1500]))
            if pesado:
                db.add(ProcessSnapshot(metric_id=met.id, pid=6600, name="svc_update.exe", cpu_percent=760.0,
                                       mem_percent=4.0, exe="C:\\Users\\v\\AppData\\Local\\svc_update.exe",
                                       signed="unsigned", ancestors=[1500]))
        db.commit()
        antes = db.query(Machine).count()
        avisos = benchmark.replay_window(db, origem.id, origem.owner_id, inicio, fim, warmup_hours=1)
        assert db.query(Machine).count() == antes
        assert avisos, "o minerador deveria gerar algum aviso"
        for a in avisos:
            assert inicio <= a["detected_at"] <= fim
            assert {"type", "severity", "responsible", "programas", "user_driven"} <= set(a)
        assert any(a["responsible"] == "svc_update.exe" or "svc_update.exe" in a["programas"] for a in avisos)

    def test_reproducao_carrega_pid_e_pais(self):
        from types import SimpleNamespace
        from app.services import benchmark
        snap = SimpleNamespace(name="a.exe", pid=7, ancestors=[3, 1], cpu_percent=1.0, mem_percent=1.0, exe=None,
                               signed=None, publisher=None, username=None, cmdline=None, sha256=None,
                               ppid=3, parent_name="b.exe")
        proc = benchmark._replay_proc(snap)
        assert proc["pid"] == 7 and proc["ancestors"] == [3, 1] and proc["sha256"] is None


def test_maquina_de_benchmark_nunca_notifica_de_verdade(db):
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
    def test_dono_ve_a_avaliacao(self, client, machine, auth):
        res = client.get(f"/api/evaluation/real/{machine['id']}?days=7", headers=auth)
        assert res.status_code == 200
        corpo = res.json()
        assert "live" in corpo and "replay" in corpo
        assert corpo["live"]["confusion"]["true_positives"] == 0

    def test_outro_usuario_nao_ve(self, client, machine):
        client.post("/api/auth/register", json={"email": "z@z.com", "username": "zz", "password": "zzsenha12345"})
        tok = client.post("/api/auth/login", data={"username": "zz", "password": "zzsenha12345"}).json()["access_token"]
        res = client.get(f"/api/evaluation/real/{machine['id']}", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 404

    def test_reproducao_roda_em_segundo_plano(self, client, machine, auth, monkeypatch):
        from app.services import real_eval
        monkeypatch.setattr(real_eval, "replay", lambda *a, **k: {"configs": {}, "sentence": "ok"})
        res = client.post(f"/api/evaluation/real/{machine['id']}/replay?days=7", headers=auth)
        assert res.status_code == 200 and res.json()["started"] is True
        corpo = client.get(f"/api/evaluation/real/{machine['id']}?days=7", headers=auth).json()
        assert corpo["replay"]["status"] == "done"


class TestChavesPorThread:
    """A reprodução roda minutos em segundo plano com o contexto desligado ou só
    com o modelo; a coleta ao vivo, nas outras threads, não pode sentir isso."""

    def _em_outra_thread(self, fn):
        import threading
        visto = {}
        t = threading.Thread(target=lambda: visto.setdefault("v", fn()))
        t.start()
        t.join()
        return visto["v"]

    def test_contexto_desligado_numa_thread_nao_vaza(self):
        from app.services import context
        anterior = context.set_context_mode(False)
        try:
            assert self._em_outra_thread(context.context_on) is True
        finally:
            context.set_context_mode(anterior)

    def test_camada_trocada_numa_thread_nao_vaza(self):
        from app.services import anomaly_service
        anterior = anomaly_service.set_detection_layer("ml")
        try:
            assert self._em_outra_thread(anomaly_service.detection_layer) == "ambas"
        finally:
            anomaly_service.set_detection_layer(anterior)


def test_tarefa_longa_nao_ocupa_a_fila_das_conversas(monkeypatch):
    """A reprodução leva dezenas de minutos; os 2 workers da fila são das conversas e diagnósticos."""
    import threading
    from app.services import jobs

    def proibido(*a, **k):
        raise AssertionError("tarefa longa não pode entrar no executor compartilhado")

    monkeypatch.setattr(jobs, "RUN_INLINE", False)
    monkeypatch.setattr(jobs._executor, "submit", proibido)
    feito = threading.Event()
    jobs.submit_long(lambda db: feito.set())
    assert feito.wait(5)
