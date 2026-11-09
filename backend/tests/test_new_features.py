"""Testes das funcionalidades novas, nos pontos em que o erro seria silencioso."""
import time
from datetime import timedelta

import pytest

from app.core import ratelimit
from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.mlhealth import ExplanationOutcome
from app.models.playbook import Playbook, PlaybookRun
from app.models.study import StudyResponse
from app.services import drift, fidelity, hardware_risk, integrity, playbooks, study


class TestRateLimit:
    def test_allows_up_to_limit_then_blocks(self):
        ratelimit.reset()
        for _ in range(3):
            assert ratelimit.check("teste", times=3, seconds=60) == 0
        # A quarta tentativa na mesma janela é recusada, com o tempo de espera
        assert ratelimit.check("teste", times=3, seconds=60) > 0

    def test_window_slides(self):
        ratelimit.reset()
        now = time.monotonic()
        ratelimit.check("desliza", 1, 10, now=now)
        assert ratelimit.check("desliza", 1, 10, now=now + 1) > 0
        # Passada a janela, a tentativa antiga não conta mais
        assert ratelimit.check("desliza", 1, 10, now=now + 11) == 0

    def test_login_returns_429_after_many_attempts(self, client):
        ratelimit.reset()
        for _ in range(10):
            client.post("/api/auth/login", data={"username": "ninguem", "password": "errada"})
        response = client.post("/api/auth/login", data={"username": "ninguem", "password": "errada"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestAuditLedger:
    def test_intact_chain_is_verifiable(self, db):
        for i in range(3):
            integrity.append(db, kind="anomaly", ref_id=i, payload={"tipo": "high_cpu", "i": i})
        result = integrity.verify(db)
        assert result["ok"] is True
        assert result["entries"] == 3

    def test_tampering_breaks_chain(self, db):
        integrity.append(db, kind="anomaly", ref_id=1, payload={"tipo": "high_cpu"})
        target = integrity.append(db, kind="action", ref_id=2, payload={"comando": "kill_process"})
        integrity.append(db, kind="anomaly", ref_id=3, payload={"tipo": "disk_full"})

        # Alguém edita o registro do meio direto no banco
        target.payload = {"comando": "clean_temp"}
        db.commit()

        result = integrity.verify(db)
        assert result["ok"] is False
        assert result["broken_at"] == target.id

    def test_date_not_in_seal(self, db):
        """PostgreSQL devolve data com fuso e SQLite sem: com ela no hash, o livro só seria íntegro num banco."""
        entry = integrity.append(db, kind="anomaly", ref_id=9, payload={"tipo": "high_cpu"})
        db.expire_all()
        assert integrity.verify(db)["ok"] is True
        assert entry.payload["_at"]  # a hora é lacrada dentro do conteúdo


class TestDrift:
    def test_equal_distributions_do_not_drift(self):
        import numpy as np
        rng = np.random.default_rng(1)
        a = rng.normal(40, 5, 500)
        b = rng.normal(40, 5, 500)
        assert drift.jensen_shannon(a, b) < 0.1

    def test_machine_with_changed_usage_drifts(self):
        import numpy as np
        rng = np.random.default_rng(1)
        before = rng.normal(20, 4, 500)     # máquina ociosa
        after = rng.normal(85, 4, 500)    # virou servidor
        assert drift.jensen_shannon(before, after) > 0.8

    def test_levels_follow_configured_thresholds(self):
        assert drift._level(0.05) == "ok"
        assert drift._level(0.25) == "warn"
        assert drift._level(0.90) == "critical"


class TestHardwareRisk:
    def test_disk_with_pending_sectors_is_high_risk(self):
        factors = hardware_risk._disk_factors(
            {"device": "C:", "pending_sectors": 4, "reallocated_sectors": 30,
             "power_on_hours": 45000, "temperature": 56},
            recent_errors=1,
        )
        risk = hardware_risk._risk_from_weights([f["peso"] for f in factors])
        assert risk > 0.4
        assert hardware_risk._level(risk) in ("alto", "critico")

    def test_healthy_disk_does_not_alarm(self):
        factors = hardware_risk._disk_factors(
            {"device": "C:", "health": "ok", "pending_sectors": 0, "reallocated_sectors": 0,
             "power_on_hours": 4000, "temperature": 35},
            recent_errors=0,
        )
        risk = hardware_risk._risk_from_weights([f["peso"] for f in factors])
        assert risk == 0.0
        assert hardware_risk._level(risk) == "baixo"


class TestForecastFidelity:
    def _prepare(self, db, machine_id, predicted):
        from app.models.anomaly import Anomaly
        from app.models.explanation import AIExplanation

        anomaly = Anomaly(machine_id=machine_id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process="chrome.exe")
        db.add(anomaly)
        db.flush()
        db.add(AIExplanation(anomaly_id=anomaly.id, summary="...", model_used="ollama",
                             counterfactual={"process": "chrome.exe", "mem_now": 91.0,
                                             "mem_after": predicted, "cpu_now": 20.0, "cpu_after": 19.0}))
        db.commit()
        return anomaly

    def test_confirmed_prediction_counts_as_hit(self, db, machine):
        anomaly = self._prepare(db, machine["id"], predicted=48.0)
        fidelity.register_from_action(db, anomaly.id, machine["id"], "kill_process")

        # A leitura seguinte mostra a memória onde a IA disse que ficaria
        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=20, mem_percent=50.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=10,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100))
        db.commit()

        outcome = db.query(ExplanationOutcome).first()
        # A medição só acontece depois de alguns minutos: envelhece o registro
        outcome.created_at = utcnow() - timedelta(minutes=10)
        db.commit()

        assert fidelity.measure_pending(db) == 1
        db.refresh(outcome)
        assert outcome.status == "measured"
        assert outcome.hit is True

    def test_very_wrong_prediction_is_not_hit(self, db, machine):
        anomaly = self._prepare(db, machine["id"], predicted=40.0)
        fidelity.register_from_action(db, anomaly.id, machine["id"], "kill_process")
        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=20, mem_percent=88.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=10,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100))
        db.commit()
        outcome = db.query(ExplanationOutcome).first()
        outcome.created_at = utcnow() - timedelta(minutes=10)
        db.commit()

        fidelity.measure_pending(db)
        db.refresh(outcome)
        assert outcome.hit is False


class TestAutomation:
    def _rule(self, db, user_id, machine_id, autonomy, dry_run=False):
        playbook = Playbook(user_id=user_id, machine_id=machine_id, name="Fechar o chrome",
                            anomaly_type="high_memory", action="kill_process",
                            autonomy=autonomy, dry_run=dry_run, cooldown_minutes=5, enabled=True)
        db.add(playbook)
        db.commit()
        return playbook

    def _alert(self, db, machine_id):
        from app.models.anomaly import Anomaly
        anomaly = Anomaly(machine_id=machine_id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process="chrome.exe")
        db.add(anomaly)
        db.commit()
        return anomaly

    def test_cautious_rule_only_suggests(self, db, machine):
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._rule(db, db_machine.owner_id, db_machine.id, "sugerir")
        runs = playbooks.on_anomaly(db, db_machine, self._alert(db, db_machine.id))
        assert [d.status for d in runs] == ["sugerido"]
        # Sugerir não manda comando nenhum para a máquina
        assert db.query(PlaybookRun).first().command_id is None

    def test_automatic_rule_waits_for_undo_window(self, db, machine):
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._rule(db, db_machine.owner_id, db_machine.id, "automatico")
        run = playbooks.on_anomaly(db, db_machine, self._alert(db, db_machine.id))[0]
        assert run.status == "agendado"
        assert run.undo_until is not None

        # Enquanto a janela não vence, nada acontece
        assert playbooks.dispatch_due(db) == 0
        run.undo_until = utcnow() - timedelta(seconds=1)
        db.commit()
        assert playbooks.dispatch_due(db) == 1
        db.refresh(run)
        assert run.status == "executado"
        assert run.command_id is not None

    def test_cancelling_in_time_prevents_action(self, db, machine):
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._rule(db, db_machine.owner_id, db_machine.id, "automatico")
        run = playbooks.on_anomaly(db, db_machine, self._alert(db, db_machine.id))[0]
        playbooks.decide(db, run, accept=False, user_id=db_machine.owner_id)
        assert run.status == "desfeito"
        assert run.command_id is None

    def test_dry_run_records_without_acting(self, db, machine):
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._rule(db, db_machine.owner_id, db_machine.id, "automatico", dry_run=True)
        run = playbooks.on_anomaly(db, db_machine, self._alert(db, db_machine.id))[0]
        assert run.status == "ensaio"
        assert run.command_id is None

    def test_without_responsible_program_nothing_to_kill(self, db, machine):
        from app.models.anomaly import Anomaly
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._rule(db, db_machine.owner_id, db_machine.id, "automatico")
        anomaly = Anomaly(machine_id=db_machine.id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process=None)
        db.add(anomaly)
        db.commit()
        run = playbooks.on_anomaly(db, db_machine, anomaly)[0]
        assert run.status == "bloqueado"


class TestUserStudy:
    def test_sus_score_follows_brooke_formula(self):
        # Todas as respostas no melhor valor possível: 5 nas positivas (ímpares)
        # e 1 nas negativas (pares) dão 100.
        best = [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]
        assert study.sus_score(best) == 100.0
        worst = [1, 5, 1, 5, 1, 5, 1, 5, 1, 5]
        assert study.sus_score(worst) == 0.0
        # Tudo no meio da escala dá exatamente a metade
        assert study.sus_score([3] * 10) == 50.0

    def test_proportion_test_detects_large_difference(self):
        # 90 de 100 contra 40 de 100 não é acaso
        p = study._two_proportion_p(90, 100, 40, 100)
        assert p is not None and p < 0.01
        # 51 contra 49 é empate
        assert study._two_proportion_p(51, 100, 49, 100) > 0.05

    def _explained_anomaly(self, db, machine_id, anomaly_type, model_used):
        metric = Metric(machine_id=machine_id, cpu_percent=90.0)
        db.add(metric)
        db.flush()
        anomaly = Anomaly(machine_id=machine_id, metric_id=metric.id, anomaly_type=anomaly_type, severity="high")
        db.add(anomaly)
        db.flush()
        db.add(AIExplanation(anomaly_id=anomaly.id, summary="texto", model_used=model_used))
        db.commit()
        return anomaly.id

    def test_session_never_shows_static_text_as_ai_explanation(self, db, machine):
        owner_id = db.get(Machine, machine["id"]).owner_id
        generated = {
            self._explained_anomaly(db, machine["id"], "high_cpu", "claude-cli/sonnet"),
            self._explained_anomaly(db, machine["id"], "memory_leak", "ollama/qwen2.5:14b"),
        }
        self._explained_anomaly(db, machine["id"], "cpu_loop", "análise local")

        session_id = study.create_session(db, owner_id, "P1")["session_id"]

        items = db.query(StudyResponse).filter(StudyResponse.session_id == session_id).all()
        assert {item.anomaly_id for item in items} == generated

    def test_session_refused_when_only_static_text_exists(self, db, machine):
        owner_id = db.get(Machine, machine["id"]).owner_id
        self._explained_anomaly(db, machine["id"], "high_cpu", "análise local")
        self._explained_anomaly(db, machine["id"], "memory_leak", "análise local")

        with pytest.raises(ValueError):
            study.create_session(db, owner_id, "P1")


class TestObservability:
    def test_metrics_responds_in_prometheus_format(self, client):
        from app.core import observability
        observability.inc("anomalydetect_scheduler_runs_total", {"routine": "teste", "result": "ok"})
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "anomalydetect_scheduler_runs_total" in response.text
        assert "# TYPE" in response.text


class TestDetectionLayers:
    def test_layer_switch_is_reversible(self):
        from app.services import anomaly_service
        previous = anomaly_service.set_detection_layer("regras")
        try:
            assert anomaly_service.detection_layer() == "regras"
        finally:
            anomaly_service.set_detection_layer(previous)
        assert anomaly_service.detection_layer() == "ambas"


READING = {
    "cpu_percent": 12.0, "mem_used": 1.0, "mem_available": 1.0, "mem_percent": 40.0, "mem_total": 2.0,
    "disk_used": 1.0, "disk_free": 1.0, "disk_percent": 30.0, "disk_read_bytes": 0.0,
    "disk_write_bytes": 0.0, "net_bytes_sent": 0.0, "net_bytes_recv": 0.0, "net_connections": 10,
    "uptime_seconds": 1000.0, "process_count": 120,
}


class TestAgentQueue:
    """A fila do agente devolve leituras antigas quando a conexão volta."""

    def test_late_reading_keeps_collection_time(self, client, machine, db):
        # Leitura guardada com o servidor fora não pode chegar com a hora da reconexão.
        collected_at = utcnow() - timedelta(hours=2)
        response = client.post("/api/metrics/ingest",
                               json={**READING, "collected_at": collected_at.timestamp()},
                               headers={"X-Agent-Token": machine["agent_token"]})
        assert response.status_code == 202

        stored = db.query(Metric).order_by(Metric.id.desc()).first()
        assert abs((stored.timestamp.replace(tzinfo=None) - collected_at.replace(tzinfo=None)).total_seconds()) < 5

    def test_absurd_date_is_ignored(self, client, machine, db):
        # Relógio errado na máquina monitorada não pode reescrever o histórico
        old_time = utcnow() - timedelta(days=400)
        client.post("/api/metrics/ingest",
                    json={**READING, "collected_at": old_time.timestamp()},
                    headers={"X-Agent-Token": machine["agent_token"]})
        stored = db.query(Metric).order_by(Metric.id.desc()).first()
        assert stored.timestamp.replace(tzinfo=None) > (utcnow() - timedelta(hours=1)).replace(tzinfo=None)


class TestAgentLocalGuard:
    """O agente não fica cego quando o servidor cai (agent/localguard.py)."""

    def _guard(self):
        import os
        import sys
        from tests._paths import AGENT_DIR
        sys.path.insert(0, AGENT_DIR)
        from localguard import LocalGuard
        return LocalGuard()

    def test_sustained_spike_becomes_local_finding(self):
        guard = self._guard()
        for _ in range(60):
            guard.observe({"cpu_percent": 10.0, "mem_percent": 30.0, "disk_percent": 40.0})
        findings = []
        for _ in range(3):
            findings = guard.check({"cpu_percent": 99.0, "mem_percent": 30.0, "disk_percent": 40.0})
        assert any(a["metric"] == "cpu_percent" for a in findings)

    def test_normal_reading_does_not_alarm(self):
        guard = self._guard()
        for _ in range(60):
            guard.observe({"cpu_percent": 10.0, "mem_percent": 30.0, "disk_percent": 40.0})
        assert guard.check({"cpu_percent": 12.0, "mem_percent": 31.0, "disk_percent": 40.0}) == []


class TestMachineRemoval:
    """Tabela nova que aponte para a máquina precisa soltar a referência, senão o Postgres recusa o delete."""

    def test_deletes_everything_and_keeps_ledger(self, db, machine):
        from app.models.anomaly import Anomaly
        from app.models.hardware import HardwareRisk
        from app.models.ledger import LedgerEntry
        from app.models.mlhealth import DriftCheck
        from app.routers.machines import delete_machine_cascade

        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        anomaly = Anomaly(machine_id=db_machine.id, anomaly_type="high_cpu", severity="medium",
                          detected_at=utcnow())
        db.add(anomaly)
        db.add(DriftCheck(machine_id=db_machine.id, distance=0.1, level="ok"))
        db.add(HardwareRisk(machine_id=db_machine.id, component="disk:C", risk_pct=5.0, level="baixo"))
        db.commit()
        integrity.append(db, kind="anomaly", ref_id=anomaly.id, machine_id=db_machine.id,
                         payload={"tipo": "high_cpu"})

        delete_machine_cascade(db_machine.id, db)

        assert db.query(Machine).filter(Machine.id == machine["id"]).first() is None
        assert db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).count() == 0
        assert db.query(DriftCheck).count() == 0
        assert db.query(HardwareRisk).count() == 0

        # O registro lacrado sobrevive sem o ponteiro para a máquina, e a cadeia continua conferindo.
        entry = db.query(LedgerEntry).first()
        assert entry is not None and entry.machine_id is None
        assert integrity.verify(db)["ok"] is True

        # A própria remoção também fica registrada.
        removal = db.query(LedgerEntry).filter(LedgerEntry.kind == "machine_removed").first()
        assert removal is not None
        assert removal.payload["avisos_apagados"] == 1

    def test_benchmark_machine_not_in_ledger(self, db, machine):
        db_machine = db.query(Machine).filter(Machine.id == machine["id"]).first()
        assert integrity.is_auditable(db_machine) is True
        db_machine.name = "[BENCH] Cenário sintético"
        assert integrity.is_auditable(db_machine) is False


class TestBenchmarkCleanup:
    """A máquina efêmera some mesmo quando o cenário quebra no meio."""

    def test_interrupted_scenario_leaves_no_machine_in_panel(self, db, machine, monkeypatch):
        from app.services import benchmark

        owner_id = db.query(Machine).filter(Machine.id == machine["id"]).first().owner_id

        def vanish_and_raise(db_, db_machine, *args, **kwargs):
            # Caso real: a linha da máquina já não existe quando o `finally` roda.
            db_.query(Machine).filter(Machine.id == db_machine.id).delete(synchronize_session=False)
            db_.commit()
            raise RuntimeError("falha simulada no meio do cenário")

        monkeypatch.setattr(benchmark, "_feed", vanish_and_raise)
        scenario_name = next(iter(benchmark.scenarios()))

        result = benchmark.run_scenario(db, scenario_name, owner_id)

        assert result.error  # o cenário falhou, e isso fica registrado
        # ... mas nada sobrou para o usuário ver
        assert db.query(Machine).filter(Machine.name.like(f"{benchmark.BENCH_PREFIX}%")).count() == 0


class TestBenchmarkLeavesNothing:
    """A limpeza da máquina efêmera não pode depender do objeto em memória."""

    def test_scenario_failing_midway_still_cleans_up(self, db, monkeypatch, client, auth):
        from app.models.user import User
        from app.services import benchmark

        user_id = db.query(User.id).first()[0]
        scenario_name = list(benchmark.scenarios().keys())[0]

        def _feed_that_deletes_machine(db_, machine, *args, **kwargs):
            # Caso real: a linha some (contêiner reiniciado, varredura concorrente) e o cenário quebra.
            db_.query(Machine).filter(Machine.id == machine.id).delete(synchronize_session=False)
            db_.commit()
            raise RuntimeError("cenário quebrou no meio")

        monkeypatch.setattr(benchmark, "_feed", _feed_that_deletes_machine)
        result = benchmark.run_scenario(db, scenario_name, user_id)

        assert result.error is not None          # o cenário falhou, e isso fica registrado
        assert result.verdict == "erro"          # sem contaminar as métricas da rodada
        assert db.query(Machine).filter(Machine.name.like("[BENCH]%")).count() == 0


class TestBulkActions:
    def test_resolves_many_and_ignores_others(self, client, auth, machine, db):
        from app.models.anomaly import Anomaly
        from app.models.user import User

        mine = []
        for _ in range(3):
            a = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="medium",
                        detected_at=utcnow())
            db.add(a)
            mine.append(a)
        # Máquina de outra conta: os avisos dela não podem ser tocados
        other_user = User(email="o@o.com", username="outro", hashed_password="x")
        db.add(other_user)
        db.flush()
        foreign_machine = Machine(name="Alheia", hostname="h", agent_token="tok-alheio", owner_id=other_user.id)
        db.add(foreign_machine)
        db.flush()
        foreign_alert = Anomaly(machine_id=foreign_machine.id, anomaly_type="high_cpu", severity="medium",
                       detected_at=utcnow())
        db.add(foreign_alert)
        db.commit()

        ids = [a.id for a in mine] + [foreign_alert.id]
        response = client.post("/api/anomalies/resolve-bulk", json={"ids": ids}, headers=auth)
        assert response.status_code == 200
        assert response.json()["changed"] == 3

        db.expire_all()
        assert all(db.query(Anomaly).filter(Anomaly.id == a.id).first().is_resolved for a in mine)
        assert not db.query(Anomaly).filter(Anomaly.id == foreign_alert.id).first().is_resolved


class TestFleetView:
    def test_overview_has_vitals_and_worst_alert(self, client, auth, machine, db):
        from app.models.anomaly import Anomaly

        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=91.0, mem_percent=70.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=55.0,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100, process_count=100))
        db.add(Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="critical",
                       detected_at=utcnow()))
        db.commit()

        rows = client.get("/api/insights/fleet/overview", headers=auth).json()["machines"]
        assert len(rows) == 1
        row = rows[0]
        assert row["cpu"] == 91.0 and row["disk"] == 55.0
        assert row["open_count"] == 1
        assert row["worst_severity"] == "critical"
