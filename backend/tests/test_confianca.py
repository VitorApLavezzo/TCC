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
