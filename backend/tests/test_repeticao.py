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


class TestJanelaUsaOTempoDaLeitura:
    def test_agrega_em_tempo_reproduzido(self, client, machine, db):
        """A demonstração e o benchmark reproduzem horas em segundos: a leitura
        é datada no passado. Se a janela usar o relógio da parede em vez da
        hora da leitura, ela nunca casa e nada agrega."""
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import persist_candidate

        m = _machine(db, machine)
        passado = utcnow() - timedelta(hours=6)

        a1 = persist_candidate(db, m, _cand(programa="alfa.exe"), now=passado)
        a2 = persist_candidate(db, m, _cand(programa="beta.exe"),
                               now=passado + timedelta(minutes=1))

        assert a2.id == a1.id
        assert a1.occurrences == 2
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1


class TestAgravamentoNaoPodeSerSilencioso:
    """O risco que a agregação cria: um achado grave entrando atrás de um
    aviso brando aberto do mesmo tipo. Se só o número da gravidade sobe e
    ninguém é avisado, a agregação escondeu uma ameaça."""

    def _notificacoes(self, db, anomaly_id):
        from app.models.notification import Notification
        return db.query(Notification).filter(Notification.anomaly_id == anomaly_id).count()

    def test_severidade_que_sobe_avisa(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)

        a = persist_candidate(db, m, _cand(tipo="beaconing", severidade="medium",
                                           programa="chrome.exe", confianca=None))
        antes = self._notificacoes(db, a.id)

        depois_a = persist_candidate(db, m, _cand(tipo="beaconing", severidade="high",
                                                  programa="svch0st.exe", confianca=None))
        assert depois_a.id == a.id and depois_a.severity == "high"
        assert self._notificacoes(db, a.id) > antes

    def test_severidade_que_nao_sobe_nao_avisa_de_novo(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, _cand(tipo="beaconing", severidade="high",
                                           programa="um.exe", confianca=None))
        antes = self._notificacoes(db, a.id)
        persist_candidate(db, m, _cand(tipo="beaconing", severidade="low",
                                       programa="dois.exe", confianca=None))
        assert self._notificacoes(db, a.id) == antes

    def test_evidencia_da_ocorrencia_absorvida_nao_se_perde(self, client, machine, db):
        """O destino do C2, a assinatura, o caminho do executável — tudo isso
        vinha no candidato absorvido e era descartado."""
        from app.services.anomaly_service import Candidate, persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, Candidate(anomaly_type="beaconing", severity="medium",
                                           responsible="chrome.exe"))
        a = persist_candidate(db, m, Candidate(
            anomaly_type="beaconing", severity="high", responsible="svch0st.exe",
            details={"destino": "198.51.100.7:443", "intervalo_segundos": 60},
        ))
        registro = a.affected_metrics["ocorrencias"]
        assert any(o.get("detalhe", {}).get("destino") == "198.51.100.7:443" for o in registro)
        assert any(o["programa"] == "svch0st.exe" for o in registro)

    def test_nome_invalido_nao_entra_na_lista(self, client, machine, db):
        """Agentes antigos ainda mandam '?' como nome de processo."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        persist_candidate(db, m, _cand(programa="alfa.exe"))
        a = persist_candidate(db, m, _cand(programa="?"))
        assert a.affected_metrics["programas"] == ["alfa.exe"]

    def test_marca_de_escalada_nao_vaza_para_a_tela(self, client, machine, db):
        """'Dados da leitura' mostra o que não for objeto: um booleano interno
        apareceria como uma linha ' escalado: true' para o usuário."""
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = None
        for i in range(ESCALATION_OCCURRENCES + 2):
            a = persist_candidate(db, m, _cand(programa=f"p{i}.exe"))
        assert not any(k.startswith("_") and not isinstance(v, (dict, list))
                       for k, v in a.affected_metrics.items())
        assert a.severity == "high"


class TestVinteProgramasViramUmAviso:
    """O sintoma relatado, pelo caminho real da coleta.

    `detect_new_suspicious_process` devolve o primeiro processo que casa e
    para. Com um programa desconhecido diferente por coleta, cada coleta
    produzia um aviso novo — vinte linhas de "Processo Desconhecido" em três
    minutos, todas iguais na tela.
    """

    def test_um_aviso_com_contador_em_vez_de_vinte_linhas(self, client, machine, db, monkeypatch):
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
        inicio = utcnow() - timedelta(hours=8)

        # Máquina formada: 100 leituras e mais de 6 horas, senão tudo é novo
        for i in range(100):
            db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40,
                          timestamp=inicio + timedelta(minutes=4 * i)))
        # Algum programa já conhecido, senão o detector se cala por falta de base
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe",
                               is_known=True, seen_count=50))
        db.commit()

        agora = utcnow()
        for i in range(20):
            ts = agora + timedelta(seconds=10 * i)
            metric = Metric(machine_id=m.id, cpu_percent=55, mem_percent=45, timestamp=ts)
            db.add(metric)
            db.flush()
            db.add(ProcessSnapshot(
                metric_id=metric.id, name=f"desconhecido{i}.exe", cpu_percent=50.0,
                mem_percent=3.0, exe=f"C:\\Users\\x\\AppData\\Local\\Temp\\desconhecido{i}.exe",
                signed="unsigned", username="x"))
            db.commit()
            process_metric(metric, m, db, now=ts)

        avisos = db.query(Anomaly).filter(Anomaly.machine_id == m.id,
                                          Anomaly.anomaly_type == "unknown_process").all()
        assert len(avisos) == 1, f"esperava 1 aviso agregado, veio {len(avisos)}"
        assert avisos[0].occurrences == 20
        assert len(avisos[0].affected_metrics["programas"]) == 20


class TestReavaliacaoAgendadaNaoEOcorrencia:
    """A previsão de disco reconfere a mesma condição a cada 15 minutos; a de
    frota, a cada 5. Contar cada reconferência como ocorrência fazia o aviso
    escalar e notificar de novo em horas, sem nada novo ter acontecido."""

    def _cand_agendado(self, severidade="medium", origem="forecast", tipo="disk_forecast"):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type=tipo, severity=severidade, source=origem, cooldown_minutes=24 * 60)

    def _notificacoes(self, db, anomaly_id):
        from app.models.notification import Notification
        return db.query(Notification).filter(Notification.anomaly_id == anomaly_id).count()

    def test_reconferencia_nao_conta_nem_escala(self, client, machine, db):
        from app.models.anomaly import Anomaly
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._cand_agendado())
        antes = self._notificacoes(db, a.id)
        for _ in range(ESCALATION_OCCURRENCES + 2):
            persist_candidate(db, m, self._cand_agendado())
        db.refresh(a)
        assert a.occurrences == 1
        assert a.severity == "medium"
        assert self._notificacoes(db, a.id) == antes
        assert db.query(Anomaly).filter(Anomaly.machine_id == m.id).count() == 1

    def test_vale_para_a_frota_tambem(self, client, machine, db):
        from app.services.anomaly_service import ESCALATION_OCCURRENCES, persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._cand_agendado(origem="fleet", tipo="outbreak_suspected"))
        for _ in range(ESCALATION_OCCURRENCES + 2):
            persist_candidate(db, m, self._cand_agendado(origem="fleet", tipo="outbreak_suspected"))
        db.refresh(a)
        assert a.occurrences == 1 and a.severity == "medium"

    def test_reconferencia_mais_grave_sobe_e_avisa(self, client, machine, db):
        """O disco que enchia em 5 dias agora enche em 1: isso a pessoa precisa saber."""
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        a = persist_candidate(db, m, self._cand_agendado("medium"))
        antes = self._notificacoes(db, a.id)
        persist_candidate(db, m, self._cand_agendado("high"))
        db.refresh(a)
        assert a.severity == "high"
        assert a.occurrences == 1
        assert self._notificacoes(db, a.id) > antes
