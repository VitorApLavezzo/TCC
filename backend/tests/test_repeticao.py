"""Repetição vira um aviso com contador, não vinte linhas iguais."""


def _machine(db, machine):
    from app.models.machine import Machine
    return db.query(Machine).filter(Machine.id == machine["id"]).first()


def _cand(tipo="unknown_process", severidade="medium", programa=None, confianca=0.6):
    from app.services.anomaly_service import Candidate
    return Candidate(anomaly_type=tipo, severity=severidade, responsible=programa, confidence=confianca)


class TestAgregacao:
    def test_dois_programas_diferentes_viram_um_aviso(self, client, machine, db):
        """Era isto que produzia 20 linhas de 'Processo Desconhecido': o
        detector devolve o primeiro que casa, e na coleta seguinte casa outro."""
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a1 = persist_candidate(db, m, _cand(programa="alfa.exe"))
        a2 = persist_candidate(db, m, _cand(programa="beta.exe"))

        assert a2 is not None and a2.id == a1.id
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1
        assert a1.occurrences == 2
        assert set(a1.affected_metrics["programas"]) == {"alfa.exe", "beta.exe"}

    def test_programa_nulo_nao_entra_na_lista(self, client, machine, db):
        """Tipos do modelo não nomeiam programa: a lista não pode ganhar None."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(tipo="disk_activity", programa=None))
        a = persist_candidate(db, m, _cand(tipo="disk_activity", programa=None))
        assert a.occurrences == 2
        assert a.affected_metrics.get("programas", []) == []

    def test_severidade_do_conjunto_e_a_maior(self, client, machine, db):
        """Um crítico entrando na agregação puxa para cima, não se dilui."""
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(severidade="low", programa="alfa.exe"))
        a = persist_candidate(db, m, _cand(severidade="critical", programa="beta.exe"))
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1
        assert a.severity == "critical"

    def test_depois_de_resolvido_o_proximo_comeca_do_um(self, client, machine, db):
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a1 = persist_candidate(db, m, _cand(programa="alfa.exe"))
        a1.is_resolved = True
        a1.resolved_at = utcnow()
        db.commit()

        a2 = persist_candidate(db, m, _cand(programa="beta.exe"))
        assert a2.id != a1.id
        assert a2.occurrences == 1
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 2


class TestEscalada:
    def test_sobe_de_nivel_ao_cruzar_o_limiar(self, client, machine, db):
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES):
            a = persist_candidate(db, m, _cand(programa=f"p{i}.exe"))
        assert a.occurrences == ESCALATION_OCCURRENCES
        assert a.severity == "high"  # medium promovido uma vez

    def test_escala_uma_vez_so(self, client, machine, db):
        """A 11ª, 12ª e 20ª ocorrência não podem promover de novo."""
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES + 10):
            a = persist_candidate(db, m, _cand(programa=f"p{i}.exe"))
        assert a.severity == "high"
