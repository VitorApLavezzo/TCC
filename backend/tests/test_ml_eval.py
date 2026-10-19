"""Comparação de algoritmos: o Isolation Forest se justifica?

A proposta do trabalho cita dois algoritmos — Isolation Forest e One-Class
SVM — e o sistema usa um. Sem comparar os dois nos mesmos dados, a escolha só
se apoia na literatura. Estes testes guardam que a comparação existe e é
justa: mesma divisão treino/teste, mesmo padronizador, mesmas anomalias
injetadas, mesma suposição sobre a fração de anomalias.
"""
from datetime import timedelta

import numpy as np
import pytest

from app.core.security import get_password_hash
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User


def _maquina_com_historico(db, n=300, seed=7):
    u = User(email="ml@t.com", username="ml", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token="tk-ml", owner_id=u.id)
    db.add(m)
    db.flush()
    rng = np.random.default_rng(seed)
    inicio = utcnow() - timedelta(hours=n * 0.5 / 60)
    for i in range(n):
        db.add(Metric(
            machine_id=m.id, timestamp=inicio + timedelta(seconds=30 * i),
            cpu_percent=float(np.clip(rng.normal(20, 5), 1, 100)),
            mem_percent=float(np.clip(rng.normal(45, 4), 1, 100)),
            disk_percent=58.0, swap_percent=float(np.clip(rng.normal(8, 1), 0, 100)),
            net_bytes_sent=float(abs(rng.normal(5e4, 1e4))),
            net_bytes_recv=float(abs(rng.normal(2e5, 4e4))),
            net_connections=int(abs(rng.normal(50, 8))),
            disk_read_bytes=float(abs(rng.normal(5e4, 1e4))),
            disk_write_bytes=float(abs(rng.normal(5e4, 1e4))),
            load_avg_1=float(abs(rng.normal(1.0, 0.2))),
            process_count=int(abs(rng.normal(190, 8))),
        ))
    db.commit()
    return m


class TestComparacaoDeAlgoritmos:
    def test_one_class_svm_e_medido_nos_mesmos_dados(self, db):
        from app.services import ml_eval
        r = ml_eval.holdout(db, _maquina_com_historico(db))
        assert r["ready"] is True
        assert 0.0 <= r["auc_ocsvm"] <= 1.0
        assert len(r["roc_ocsvm"]) > 1
        # A curva é do mesmo conjunto: começa em (0,0) e termina em (1,1)
        assert r["roc_ocsvm"][0] == {"fpr": 0.0, "tpr": 0.0}
        assert r["roc_ocsvm"][-1] == {"fpr": 1.0, "tpr": 1.0}

    def test_os_dois_partem_da_mesma_suposicao_de_contaminacao(self, db):
        """Sem isso o SVM poderia ganhar ou perder só por esperar mais ou
        menos anomalias que o Isolation Forest."""
        from app.config import settings
        from app.services import ml_eval
        r = ml_eval.holdout(db, _maquina_com_historico(db))
        p = r["params"]
        assert p["one_class_svm"]["nu"] == settings.ISOLATION_FOREST_CONTAMINATION
        assert p["isolation_forest"]["contamination"] == settings.ISOLATION_FOREST_CONTAMINATION

    def test_parametros_reportados_para_a_metodologia(self, db):
        from app.services import ml_eval
        p = ml_eval.holdout(db, _maquina_com_historico(db))["params"]
        assert p["one_class_svm"]["kernel"] == "rbf"
        assert p["one_class_svm"]["gamma"] == "scale"
        assert p["isolation_forest"]["n_estimators"] == 300

    def test_o_painel_atual_continua_recebendo_o_que_ja_usava(self, db):
        from app.services import ml_eval
        r = ml_eval.holdout(db, _maquina_com_historico(db))
        for chave in ("auc_model", "auc_sigma_baseline", "gain", "roc", "roc_baseline",
                      "operating_point", "verdict", "samples_train", "samples_test"):
            assert chave in r

    def test_resultado_e_reproduzivel(self, db):
        """Número de TCC precisa sair igual quando a banca pedir para rodar de novo."""
        from app.services import ml_eval
        m = _maquina_com_historico(db)
        a, b = ml_eval.holdout(db, m), ml_eval.holdout(db, m)
        assert a["auc_ocsvm"] == b["auc_ocsvm"]
        assert a["auc_model"] == b["auc_model"]


class TestVereditoDoAlgoritmo:
    def test_isolation_forest_vence(self):
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(0.95, 0.85)
        assert "Isolation Forest" in frase and "supera" in frase

    def test_one_class_svm_vence(self):
        """Se o outro ganhou, a frase diz isso — sem inventar desculpa."""
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(0.80, 0.92)
        assert "One-Class SVM" in frase and "melhor" in frase

    def test_empate_dentro_da_margem(self):
        from app.services.ml_eval import _algorithm_verdict
        assert "empataram" in _algorithm_verdict(0.90, 0.88)

    def test_os_dois_ruins(self):
        from app.services.ml_eval import _algorithm_verdict
        assert "nenhum dos dois" in _algorithm_verdict(0.60, 0.65).lower()


class TestNumerosEmPortugues:
    """As frases aparecem na tela de Pesquisa e vão parar no texto do TCC:
    "0.05" num parágrafo em português, ao lado de "0,70", é erro visível."""

    def test_veredito_do_algoritmo_usa_virgula(self):
        from app.services.ml_eval import _algorithm_verdict
        for frase in (_algorithm_verdict(0.95, 0.85), _algorithm_verdict(0.80, 0.92),
                      _algorithm_verdict(0.90, 0.88)):
            assert "0." not in frase, frase

    def test_veredito_contra_o_limiar_usa_virgula(self):
        from app.services.ml_eval import _verdict
        assert "0." not in _verdict(0.95, 0.80)
