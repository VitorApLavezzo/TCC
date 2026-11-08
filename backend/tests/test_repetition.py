"""Repetição vira um aviso com contador, não vinte linhas iguais."""


def _machine(db, machine):
    from app.models.machine import Machine
    return db.query(Machine).filter(Machine.id == machine["id"]).first()


def _cand(kind="unknown_process", severity="medium", program=None, confidence=0.6):
    from app.services.anomaly_service import Candidate
    return Candidate(anomaly_type=kind, severity=severity, responsible=program, confidence=confidence)


class TestAggregation:
    def test_two_different_programs_become_one_alert(self, client, machine, db):
        """O detector devolve o primeiro que casa, e na coleta seguinte casa outro."""
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a1 = persist_candidate(db, m, _cand(program="alfa.exe"))
        a2 = persist_candidate(db, m, _cand(program="beta.exe"))

        assert a2 is not None and a2.id == a1.id
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1
        assert a1.occurrences == 2
        assert set(a1.affected_metrics["programas"]) == {"alfa.exe", "beta.exe"}

    def test_null_program_not_listed(self, client, machine, db):
        """Tipos do modelo não nomeiam programa: a lista não pode ganhar None."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(kind="disk_activity", program=None))
        a = persist_candidate(db, m, _cand(kind="disk_activity", program=None))
        assert a.occurrences == 2
        assert a.affected_metrics.get("programas", []) == []

    def test_group_severity_is_highest(self, client, machine, db):
        """Um crítico entrando na agregação puxa para cima, não se dilui."""
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(severity="low", program="alfa.exe"))
        a = persist_candidate(db, m, _cand(severity="critical", program="beta.exe"))
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1
        assert a.severity == "critical"

    def test_after_resolved_next_starts_at_one(self, client, machine, db):
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a1 = persist_candidate(db, m, _cand(program="alfa.exe"))
        a1.is_resolved = True
        a1.resolved_at = utcnow()
        db.commit()

        a2 = persist_candidate(db, m, _cand(program="beta.exe"))
        assert a2.id != a1.id
        assert a2.occurrences == 1
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 2


class TestEscalation:
    def test_escalates_when_crossing_threshold(self, client, machine, db):
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES):
            a = persist_candidate(db, m, _cand(program=f"p{i}.exe"))
        assert a.occurrences == ESCALATION_OCCURRENCES
        assert a.severity == "high"  # medium promovido uma vez

    def test_escalates_only_once(self, client, machine, db):
        """A 11ª, 12ª e 20ª ocorrência não podem promover de novo."""
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES + 10):
            a = persist_candidate(db, m, _cand(program=f"p{i}.exe"))
        assert a.severity == "high"


class TestWindowUsesReadingTime:
    def test_aggregates_in_replayed_time(self, client, machine, db):
        """Demonstração e benchmark datam a leitura no passado: a janela usa a hora dela, não o relógio."""
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate

        m = _machine(db, machine)
        past = utcnow() - timedelta(hours=6)

        a1 = persist_candidate(db, m, _cand(program="alfa.exe"), now=past)
        a2 = persist_candidate(db, m, _cand(program="beta.exe"),
                               now=past + timedelta(minutes=1))

        assert a2.id == a1.id
        assert a1.occurrences == 2
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1


class TestEscalationCannotBeSilent:
    """Achado grave absorvido por um aviso brando aberto do mesmo tipo precisa notificar."""

    def _notifications(self, db, anomaly_id):
        from app.models.notification import Notification
        return db.query(Notification).filter(Notification.anomaly_id == anomaly_id).count()

    def test_rising_severity_notifies(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a = persist_candidate(db, m, _cand(kind="beaconing", severity="medium",
                                           program="chrome.exe", confidence=None))
        before = self._notifications(db, a.id)

        after = persist_candidate(db, m, _cand(kind="beaconing", severity="high",
                                                  program="svch0st.exe", confidence=None))
        assert after.id == a.id and after.severity == "high"
        assert self._notifications(db, a.id) > before

    def test_non_rising_severity_does_not_notify_again(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, _cand(kind="beaconing", severity="high",
                                           program="um.exe", confidence=None))
        before = self._notifications(db, a.id)
        persist_candidate(db, m, _cand(kind="beaconing", severity="low",
                                       program="dois.exe", confidence=None))
        assert self._notifications(db, a.id) == before

    def test_absorbed_occurrence_evidence_is_kept(self, client, machine, db):
        """Destino do C2, assinatura e caminho do executável do candidato absorvido ficam guardados."""
        from app.services.anomaly_service import Candidate, persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, Candidate(anomaly_type="beaconing", severity="medium",
                                           responsible="chrome.exe"))
        a = persist_candidate(db, m, Candidate(
            anomaly_type="beaconing", severity="high", responsible="svch0st.exe",
            details={"destino": "198.51.100.7:443", "intervalo_segundos": 60},
        ))
        occurrence_log = a.affected_metrics["ocorrencias"]
        assert any(o.get("detalhe", {}).get("destino") == "198.51.100.7:443" for o in occurrence_log)
        assert any(o["programa"] == "svch0st.exe" for o in occurrence_log)

    def test_invalid_name_not_listed(self, client, machine, db):
        """Agentes antigos ainda mandam '?' como nome de processo."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(program="alfa.exe"))
        a = persist_candidate(db, m, _cand(program="?"))
        assert a.affected_metrics["programas"] == ["alfa.exe"]

    def test_escalation_flag_does_not_leak_to_screen(self, client, machine, db):
        """'Dados da leitura' mostra o que não for objeto: um booleano interno viraria uma linha na tela."""
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES + 2):
            a = persist_candidate(db, m, _cand(program=f"p{i}.exe"))
        assert not any(k.startswith("_") and not isinstance(v, (dict, list))
                       for k, v in a.affected_metrics.items())
        assert a.severity == "high"


class TestTwentyProgramsBecomeOneAlert:
    """`detect_new_suspicious_process` devolve o primeiro que casa: um desconhecido por coleta virava um aviso por coleta."""

    def test_one_alert_with_counter_instead_of_twenty_rows(self, client, machine, db, monkeypatch):
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.models.process_baseline import ProcessBaseline
        from app.services import ml_service
        from app.services.anomaly_service import process_metric

        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (False, None))

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        start = utcnow() - timedelta(hours=8)

        # Máquina formada: 100 leituras e mais de 6 horas, senão tudo é novo
        for i in range(100):
            db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40,
                          timestamp=start + timedelta(minutes=4 * i)))
        # Algum programa já conhecido, senão o detector se cala por falta de base
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe",
                               is_known=True, seen_count=50))
        db.commit()

        now = utcnow()
        for i in range(20):
            ts = now + timedelta(seconds=10 * i)
            metric = Metric(machine_id=m.id, cpu_percent=55, mem_percent=45, timestamp=ts)
            db.add(metric)
            db.flush()
            db.add(ProcessSnapshot(
                metric_id=metric.id, name=f"desconhecido{i}.exe", cpu_percent=50.0,
                mem_percent=3.0, exe=f"C:\\Users\\x\\AppData\\Local\\Temp\\desconhecido{i}.exe",
                signed="unsigned", username="x"))
            db.commit()
            process_metric(metric, m, db, now=ts)

        alerts = db.query(Anomaly).filter(Anomaly.machine_id == m.id,
                                          Anomaly.anomaly_type == "unknown_process").all()
        assert len(alerts) == 1, f"esperava 1 aviso agregado, veio {len(alerts)}"
        assert alerts[0].occurrences == 20
        assert len(alerts[0].affected_metrics["programas"]) == 20


class TestScheduledRecheckIsNotOccurrence:
    """Previsão de disco e frota reconferem a mesma condição periodicamente; isso não é nova ocorrência."""

    def _scheduled_cand(self, severity="medium", origin="forecast", kind="disk_forecast"):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type=kind, severity=severity, source=origin, cooldown_minutes=24 * 60)

    def _notifications(self, db, anomaly_id):
        from app.models.notification import Notification
        return db.query(Notification).filter(Notification.anomaly_id == anomaly_id).count()

    def test_recheck_neither_counts_nor_escalates(self, client, machine, db):
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._scheduled_cand())
        before = self._notifications(db, a.id)
        for _ in range(ESCALATION_OCCURRENCES + 2):
            persist_candidate(db, m, self._scheduled_cand())
        db.refresh(a)
        assert a.occurrences == 1
        assert a.severity == "medium"
        assert self._notifications(db, a.id) == before
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1

    def test_applies_to_fleet_too(self, client, machine, db):
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._scheduled_cand(origin="fleet", kind="outbreak_suspected"))
        for _ in range(ESCALATION_OCCURRENCES + 2):
            persist_candidate(db, m, self._scheduled_cand(origin="fleet", kind="outbreak_suspected"))
        db.refresh(a)
        assert a.occurrences == 1 and a.severity == "medium"

    def test_more_severe_recheck_escalates_and_notifies(self, client, machine, db):
        """O disco que enchia em 5 dias agora enche em 1: isso a pessoa precisa saber."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._scheduled_cand("medium"))
        before = self._notifications(db, a.id)
        persist_candidate(db, m, self._scheduled_cand("high"))
        db.refresh(a)
        assert a.severity == "high"
        assert a.occurrences == 1
        assert self._notifications(db, a.id) > before


class TestRecheckPerCondition:
    """A reconferência só casa com o aviso da mesma condição (mesma peça, mesmo programa)."""

    def _hw(self, part, severity):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type="hardware_failure_risk", severity=severity, affected={"peca": part},
                         source="hardware", identity=part, cooldown_minutes=7 * 24 * 60)

    def test_different_part_is_another_alert(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        disk_alert = persist_candidate(db, m, self._hw("Disco", "medium"))
        battery_alert = persist_candidate(db, m, self._hw("Bateria", "high"))
        assert battery_alert is not None and battery_alert.id != disk_alert.id
        assert battery_alert.affected_metrics["peca"] == "Bateria"
        db.refresh(disk_alert)
        assert disk_alert.severity == "medium" and disk_alert.affected_metrics["peca"] == "Disco"

    def test_other_program_in_outbreak_is_another_alert(self, client, machine, db):
        from app.services.anomaly_service import Candidate, persist_candidate
        m = _machine(db, machine)

        def outbreak(program):
            return Candidate(anomaly_type="outbreak_suspected", severity="critical", responsible=program,
                             affected={"programa": program}, source="fleet", identity=f"chave-{program}",
                             cooldown_minutes=12 * 60)

        a = persist_candidate(db, m, outbreak("setup.exe"))
        b = persist_candidate(db, m, outbreak("payload.exe"))
        assert b is not None and b.id != a.id and b.responsible_process == "payload.exe"

    def test_same_part_stays_silenced(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, self._hw("Disco", "medium"))
        assert persist_candidate(db, m, self._hw("Disco", "medium")) is None

    def test_worsening_shows_new_numbers_and_redoes_explanation(self, client, machine, db, monkeypatch):
        from app.models.explanation import AIExplanation
        from app.services import explanation_queue
        from app.services.anomaly_service import Candidate, persist_candidate
        requests = []
        monkeypatch.setattr(explanation_queue, "request_explanation", lambda *a: requests.append(a) or True)
        m = _machine(db, machine)

        def forecast(sev, days):
            return Candidate(anomaly_type="disk_forecast", severity=sev, affected={"dias_ate_encher": days},
                             details={"sentence": f"enche em {days} dias"}, source="forecast",
                             cooldown_minutes=24 * 60)

        a = persist_candidate(db, m, forecast("medium", 5.0))
        ready = db.query(AIExplanation).filter(AIExplanation.anomaly_id == a.id).first()
        ready.summary, ready.possible_causes = "O disco enche em 5 dias.", ["algo"]
        db.commit()
        requests.clear()

        persist_candidate(db, m, forecast("high", 1.0))
        db.refresh(a)
        assert a.severity == "high"
        assert a.affected_metrics["dias_ate_encher"] == 1.0
        assert a.affected_metrics["_behavior"]["sentence"] == "enche em 1.0 dias"
        assert requests, "a explicação velha falava em 5 dias: tem que ser refeita"
        redone = db.query(AIExplanation).filter(AIExplanation.anomaly_id == a.id).first()
        assert redone.possible_causes == []
