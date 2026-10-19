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


def _niveis(*pares):
    """[(isolation, svm), ...] para k = 1, 2, 3, 5."""
    return [{"sigma": k, "isolation_forest": a, "one_class_svm": b, "sigma_baseline": 0.5}
            for k, (a, b) in zip((1, 2, 3, 5), pares)]


class TestVereditoDoAlgoritmo:
    def test_isolation_forest_vence(self):
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.80, 0.70), (0.90, 0.80), (0.95, 0.94), (0.99, 0.99)))
        assert "Isolation Forest" in frase and "supera" in frase

    def test_one_class_svm_vence(self):
        """Se o outro ganhou, a frase diz isso — sem inventar desculpa."""
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.70, 0.71), (0.75, 0.85), (0.80, 0.92), (0.90, 0.99)))
        assert "One-Class SVM" in frase and "melhor" in frase

    def test_empate_em_todos_os_niveis(self):
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.80, 0.79), (0.85, 0.86), (0.90, 0.88), (0.95, 0.96)))
        assert "empataram" in frase

    def test_os_dois_ruins(self):
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.50, 0.52), (0.55, 0.58), (0.60, 0.62), (0.65, 0.68)))
        assert "nenhum dos dois" in frase.lower()

    def test_cruzamento_nao_vira_empate(self):
        """O erro que a média escondia: o Isolation Forest melhor nos desvios
        sutis, o SVM nos fortes, e a média dos níveis dizendo "empataram —
        a escolha não muda a detecção". Muda, em sentidos opostos."""
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.59, 0.53), (0.70, 0.69), (0.78, 0.84), (0.84, 0.95)))
        assert "empataram" not in frase
        assert "complementam" in frase
        assert "1 desvio-padrão" in frase and "3 e 5 desvios-padrão" in frase


class TestNumerosEmPortugues:
    """As frases aparecem na tela de Pesquisa e vão parar no texto do TCC:
    "0.05" num parágrafo em português, ao lado de "0,70", é erro visível."""

    def test_veredito_do_algoritmo_usa_virgula(self):
        from app.services.ml_eval import _algorithm_verdict
        frase = _algorithm_verdict(_niveis((0.80, 0.79), (0.85, 0.86), (0.90, 0.88), (0.95, 0.96)))
        assert "0." not in frase, frase

    def test_veredito_contra_o_limiar_usa_virgula(self):
        from app.services.ml_eval import _verdict
        assert "0." not in _verdict(0.95, 0.80)


class TestInjecaoGraduada:
    """A injeção antiga empurrava oito medidas ao mesmo tempo: qualquer
    detector, inclusive o limiar de 3 desvios, chegava a área ~1,0 e a
    comparação não diferenciava nada. Aqui a anomalia é uma medida só,
    deslocada em k desvios-padrão do treino — e a pergunta vira "a partir de
    quão sutil cada detector percebe"."""

    def _base(self):
        from app.services import ml_service
        rng = np.random.default_rng(0)
        X = rng.normal(50, 5, size=(40, len(ml_service.FEATURE_KEYS)))
        sigma = X.std(axis=0)
        return X, sigma

    def test_mexe_em_uma_medida_so(self):
        from app.services import ml_eval, ml_service
        X, sigma = self._base()
        col = ml_service.FEATURE_KEYS.index("net_connections")
        Y = ml_eval._inject_single(X, col, 2.0, sigma)
        mudou = np.where(np.any(Y != X, axis=0))[0]
        assert list(mudou) == [col]
        assert np.allclose(Y[:, col] - X[:, col], 2.0 * sigma[col])

    def test_respeita_o_teto_da_medida(self):
        """CPU e memória não passam de 100%."""
        from app.services import ml_eval, ml_service
        X, sigma = self._base()
        col = ml_service.FEATURE_KEYS.index("cpu_percent")
        X[:, col] = 99.0
        assert ml_eval._inject_single(X, col, 5.0, sigma)[:, col].max() <= 100.0

    def test_horario_nunca_e_perturbado(self):
        """A anomalia acontece no mesmo instante da leitura original."""
        from app.services import ml_eval, ml_service
        perturbadas = {ml_service.FEATURE_KEYS[c] for c in ml_eval._perturbable_columns()}
        assert not perturbadas & {"hour_sin", "hour_cos", "dow_sin", "dow_cos"}

    def test_menor_desvio_percebido(self):
        from app.services.ml_eval import _smallest_detectable
        assert _smallest_detectable([(1, 0.6), (2, 0.93), (3, 0.99), (5, 1.0)]) == 2
        assert _smallest_detectable([(1, 0.6), (2, 0.7), (3, 0.8), (5, 0.85)]) is None

    def test_holdout_mede_os_tres_em_cada_nivel(self, db):
        from app.services import ml_eval
        s = ml_eval.holdout(db, _maquina_com_historico(db))["sensitivity"]
        assert [r["sigma"] for r in s["rows"]] == list(ml_eval.SENSITIVITY_LEVELS)
        for r in s["rows"]:
            for detector in ("isolation_forest", "one_class_svm", "sigma_baseline"):
                assert 0.0 <= r[detector] <= 1.0
        assert set(s["smallest_detectable"]) == {"isolation_forest", "one_class_svm", "sigma_baseline"}

    def test_desvio_maior_e_mais_facil_de_perceber(self, db):
        """Sanidade do método: se 5 desvios não fossem mais fáceis que 1, a
        injeção estaria medindo outra coisa."""
        from app.services import ml_eval
        rows = ml_eval.holdout(db, _maquina_com_historico(db))["sensitivity"]["rows"]
        for detector in ("isolation_forest", "one_class_svm", "sigma_baseline"):
            assert rows[-1][detector] >= rows[0][detector] - 0.01

    def test_veredito_do_algoritmo_vem_da_medicao_graduada(self, db):
        """É onde os algoritmos podem se diferenciar; na injeção de oito
        medidas os dois empatam sempre."""
        from app.services import ml_eval
        r = ml_eval.holdout(db, _maquina_com_historico(db))
        assert r["algorithm_verdict"] == ml_eval._algorithm_verdict(r["sensitivity"]["rows"])

    def test_graduada_e_reproduzivel(self, db):
        from app.services import ml_eval
        m = _maquina_com_historico(db)
        assert ml_eval.holdout(db, m)["sensitivity"] == ml_eval.holdout(db, m)["sensitivity"]


class TestBaseDaVarredura:
    """A varredura pontua níveis × medidas × leituras. Com o histórico cheio
    eram 96 mil linhas e 8 s num endpoint síncrono — sem ganho de precisão:
    com 1000 leituras-base o erro padrão da área já fica abaixo de 0,01."""

    def test_limita_o_numero_de_leituras_base(self):
        from app.services import ml_eval
        X = np.arange(3000 * 2, dtype=float).reshape(3000, 2)
        assert len(ml_eval._sensitivity_base(X)) == ml_eval.SENSITIVITY_MAX_BASE

    def test_espalha_pelo_periodo_inteiro(self):
        """As primeiras N leituras concentrariam a amostra numa faixa do dia."""
        from app.services import ml_eval
        X = np.arange(3000, dtype=float).reshape(3000, 1)
        base = ml_eval._sensitivity_base(X)
        assert base[0, 0] == 0 and base[-1, 0] == 2999

    def test_historico_pequeno_usa_tudo(self):
        from app.services import ml_eval
        X = np.ones((90, 3))
        assert len(ml_eval._sensitivity_base(X)) == 90
