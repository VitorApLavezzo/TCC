"""Confiança do detector: evidência fraca rebaixa a severidade, não some."""
import pytest


class TestApplyConfidence:
    def test_evidencia_fraca_desce_um_nivel(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("medium", 0.25) == "low"
        assert apply_confidence("critical", 0.1) == "high"

    def test_evidencia_forte_nao_mexe(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("medium", 0.9) == "medium"

    def test_no_limite_nao_rebaixa(self):
        """0,5 é forte o bastante: a comparação é >=, não >."""
        from app.services.anomaly_service import WEAK_CONFIDENCE, apply_confidence
        assert apply_confidence("medium", WEAK_CONFIDENCE) == "medium"

    def test_sem_confianca_calculada_nunca_rebaixa(self):
        """None é 'não aplicável', não 'zero' — protege ransomware_canary e cia."""
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("critical", None) == "critical"

    def test_piso_em_low(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("low", 0.0) == "low"


class TestConfiancaNoBanco:
    def test_candidato_fraco_grava_confianca_e_rebaixa(self, client, machine, db):
        from app.models.anomaly import Anomaly
        from app.models.machine import Machine
        from app.services.anomaly_service import Candidate, apply_confidence, persist_candidate

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        a = persist_candidate(db, m, Candidate(
            anomaly_type="malware_pattern",
            severity=apply_confidence("medium", 0.25),
            confidence=0.25,
        ))
        assert a is not None
        assert a.severity == "low"
        assert a.confidence == 0.25
        assert a.occurrences == 1
        assert db.query(Anomaly).filter(Anomaly.id == a.id).first() is not None


class TestConfiancaDoModelo:
    def test_nota_encostada_no_limite_tem_confianca_baixa(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.20, -0.20) == 0.0

    def test_nota_muito_abaixo_tem_confianca_cheia(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.60, -0.20) == 1.0

    def test_metade_do_caminho(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.30, -0.20) == pytest.approx(0.5)

    def test_sem_limite_util_devolve_none(self):
        """Modelo degenerado (histórico sem variação) não dá régua: sem régua,
        não se rebaixa nada — e não se divide por zero."""
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.3, 0.0) is None
        assert confidence_from_score(-0.3, None) is None
        assert confidence_from_score(None, -0.2) is None

    def test_limite_de_maquina_sem_modelo_e_none(self):
        from app.services.ml_service import alert_threshold
        assert alert_threshold(999_999) is None


class TestConfirmacaoDeDuasLeituras:
    def _cenario(self, db, machine, monkeypatch, nota_anterior, cpu_atual):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services import ml_service

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        anterior = Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=nota_anterior)
        db.add(anterior)
        db.commit()
        atual = Metric(machine_id=m.id, cpu_percent=cpu_atual, mem_percent=40)
        db.add(atual)
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.5))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        return m, atual

    def _avisos_do_modelo(self, db, m):
        from app.models.anomaly import Anomaly
        return db.query(Anomaly).filter(Anomaly.machine_id == m.id, Anomaly.source == "ml").count()

    def test_leitura_anterior_levemente_negativa_nao_confirma(self, db, machine, monkeypatch):
        """-0,01 está do lado de fora da fronteira de contaminação, por onde
        passam ~3% das leituras normais. Isso não é 'duas seguidas fora do
        padrão' — é ruído com sinal trocado."""
        from app.services.anomaly_service import process_metric
        m, atual = self._cenario(db, machine, monkeypatch, -0.01, 20)
        process_metric(atual, m, db)
        assert self._avisos_do_modelo(db, m) == 0

    def test_leitura_anterior_abaixo_da_metade_confirma(self, db, machine, monkeypatch):
        """Limite -0,2 com fator 0,5: confirma abaixo de -0,1."""
        from app.services.anomaly_service import process_metric
        m, atual = self._cenario(db, machine, monkeypatch, -0.15, 97)
        process_metric(atual, m, db)
        assert self._avisos_do_modelo(db, m) == 1


class TestCulpado:
    def _com_processos(self, db, machine):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        metric = Metric(machine_id=m.id, cpu_percent=50, mem_percent=50)
        db.add(metric)
        db.flush()
        db.add(ProcessSnapshot(metric_id=metric.id, name="chrome.exe", cpu_percent=80.0, mem_percent=5.0))
        db.add(ProcessSnapshot(metric_id=metric.id, name="postgres.exe", cpu_percent=2.0, mem_percent=70.0))
        db.commit()
        return metric

    def test_desvio_de_disco_nao_acusa_ninguem(self, db, machine):
        """ProcessSnapshot não guarda E/S por processo. Acusar o maior de CPU
        por um desvio de disco é pior que ficar calado."""
        from app.services.anomaly_service import _find_top_process
        metric = self._com_processos(db, machine)
        assert _find_top_process(metric, db, "disk_activity") is None
        assert _find_top_process(metric, db, "network_spike") is None

    def test_desvio_de_cpu_acusa_o_maior_de_cpu(self, db, machine):
        from app.services.anomaly_service import _find_top_process
        metric = self._com_processos(db, machine)
        assert _find_top_process(metric, db, "high_cpu").name == "chrome.exe"

    def test_desvio_de_memoria_acusa_o_maior_de_memoria(self, db, machine):
        from app.services.anomaly_service import _find_top_process
        metric = self._com_processos(db, machine)
        assert _find_top_process(metric, db, "high_memory").name == "postgres.exe"


class TestCandidatoDoModelo:
    def _rodar(self, db, machine, monkeypatch, nota):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services import ml_service
        from app.services.anomaly_service import process_metric

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=-0.15))
        db.commit()
        atual = Metric(machine_id=m.id, cpu_percent=97, mem_percent=40)
        db.add(atual)
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, nota))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        return process_metric(atual, m, db)

    def test_desvio_que_encostou_no_limite_e_rebaixado(self, db, machine, monkeypatch):
        """Nota -0,21 contra limite -0,2: mal passou. CPU 97 daria 'high'."""
        a = self._rodar(db, machine, monkeypatch, -0.21)
        assert a is not None and a.anomaly_type == "high_cpu"
        assert a.confidence is not None and a.confidence < 0.5
        assert a.severity == "medium"

    def test_desvio_que_estourou_o_limite_mantem_a_gravidade(self, db, machine, monkeypatch):
        a = self._rodar(db, machine, monkeypatch, -0.9)
        assert a is not None and a.anomaly_type == "high_cpu"
        assert a.confidence == 1.0
        assert a.severity == "high"


class TestReputacaoSobreviveAoCulpadoAusente:
    """Não acusar ninguém num desvio de disco é correto. Mas a reputação do
    executável que está trabalhando continua sendo informação: é dela que sai
    o rebaixamento de uma varredura de antivírus, da rodada anterior de falsos
    positivos. Separar "quem culpar" de "em quem confiar" é o que mantém as
    duas coisas de pé ao mesmo tempo."""

    def test_varredura_de_antivirus_em_desvio_de_disco_continua_rebaixada(
            self, client, machine, db, monkeypatch):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import ml_service
        from app.services.anomaly_service import process_metric

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=-0.15))
        db.commit()
        atual = Metric(machine_id=m.id, cpu_percent=72, mem_percent=40, disk_read_bytes=9e7)
        db.add(atual)
        db.flush()
        db.add(ProcessSnapshot(
            metric_id=atual.id, name="avp.exe", cpu_percent=68.0, mem_percent=5.0,
            exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
            signed="signed", publisher="Kaspersky Lab JSC", username="SYSTEM"))
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.9))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        monkeypatch.setattr(ml_service, "classify_anomaly", lambda *a, **k: {
            "anomaly_type": "disk_activity", "severity": "medium", "affected_metrics": {}})

        a = process_metric(atual, m, db)
        assert a is not None and a.anomaly_type == "disk_activity"
        # Desvio de disco não nomeia culpado...
        assert a.responsible_process is None
        # ...mas o antivírus reconhecido continua segurando o aviso no painel
        assert a.severity == "low"


class TestSinalFracoNaApi:
    """A tela não pode repetir o corte de confiança por conta própria: se a
    constante for ajustada no servidor, a etiqueta passa a mentir. Quem decide
    é o servidor, e manda a resposta pronta."""

    def _saida(self, **campos):
        from app.schemas.anomaly import AnomalyOut
        from datetime import datetime, timezone
        base = dict(id=1, machine_id=1, metric_id=None, detected_at=datetime.now(timezone.utc),
                    anomaly_type="malware_pattern", severity="low", anomaly_score=None,
                    affected_metrics={}, responsible_process=None, is_resolved=False,
                    resolved_at=None, explanation=None)
        base.update(campos)
        return AnomalyOut(**base)

    def test_confianca_fraca_marca_sinal_fraco(self):
        assert self._saida(confidence=0.25).weak_signal is True

    def test_confianca_forte_nao_marca(self):
        assert self._saida(confidence=0.9).weak_signal is False

    def test_sem_confianca_nao_marca(self):
        """Arquivo-isca e comando suspeito não têm confiança calculada: não são
        sinal fraco, são evidência que não depende de histórico."""
        assert self._saida(confidence=None).weak_signal is False
