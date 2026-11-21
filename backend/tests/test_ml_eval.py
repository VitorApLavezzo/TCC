"""Comparação Isolation Forest × One-Class SVM: mesma divisão treino/teste, mesmo
padronizador, mesmas anomalias injetadas e mesma fração de contaminação."""
from datetime import timedelta

import numpy as np
import pytest

from app.core.security import get_password_hash
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User


def _machine_with_history(db, n=300, seed=7):
    u = User(email="ml@t.com", username="ml", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token="tk-ml", owner_id=u.id)
    db.add(m)
    db.flush()
    rng = np.random.default_rng(seed)
    start = utcnow() - timedelta(hours=n * 0.5 / 60)
    for i in range(n):
        db.add(Metric(
            machine_id=m.id, timestamp=start + timedelta(seconds=30 * i),
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


class TestAlgorithmComparison:
    def test_one_class_svm_measured_on_same_data(self, db):
        from app.services import ml_eval
        r = ml_eval.holdout(db, _machine_with_history(db))
        assert r["ready"] is True
        assert 0.0 <= r["auc_ocsvm"] <= 1.0
        assert len(r["roc_ocsvm"]) > 1
        # A curva é do mesmo conjunto: começa em (0,0) e termina em (1,1)
        assert r["roc_ocsvm"][0] == {"fpr": 0.0, "tpr": 0.0}
        assert r["roc_ocsvm"][-1] == {"fpr": 1.0, "tpr": 1.0}

    def test_both_share_contamination_assumption(self, db):
        """Senão o SVM ganharia ou perderia só por esperar mais ou menos anomalias."""
        from app.config import settings
        from app.services import ml_eval
        r = ml_eval.holdout(db, _machine_with_history(db))
        p = r["params"]
        assert p["one_class_svm"]["nu"] == settings.ISOLATION_FOREST_CONTAMINATION
        assert p["isolation_forest"]["contamination"] == settings.ISOLATION_FOREST_CONTAMINATION

    def test_parameters_reported_for_methodology(self, db):
        from app.services import ml_eval
        p = ml_eval.holdout(db, _machine_with_history(db))["params"]
        assert p["one_class_svm"]["kernel"] == "rbf"
        assert p["one_class_svm"]["gamma"] == "scale"
        assert p["isolation_forest"]["n_estimators"] == 300

    def test_panel_still_gets_existing_fields(self, db):
        from app.services import ml_eval
        r = ml_eval.holdout(db, _machine_with_history(db))
        for key in ("auc_model", "auc_sigma_baseline", "gain", "roc", "roc_baseline",
                      "operating_point", "verdict", "samples_train", "samples_test"):
            assert key in r

    def test_result_is_reproducible(self, db):
        """Número de TCC precisa sair igual quando a banca pedir para rodar de novo."""
        from app.services import ml_eval
        m = _machine_with_history(db)
        a, b = ml_eval.holdout(db, m), ml_eval.holdout(db, m)
        assert a["auc_ocsvm"] == b["auc_ocsvm"]
        assert a["auc_model"] == b["auc_model"]


def _levels(*pairs):
    """[(isolation, svm), ...] para k = 1, 2, 3, 5."""
    return [{"sigma": k, "isolation_forest": a, "one_class_svm": b, "sigma_baseline": 0.5}
            for k, (a, b) in zip((1, 2, 3, 5), pairs)]


class TestAlgorithmVerdict:
    def test_isolation_forest_wins(self):
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.80, 0.70), (0.90, 0.80), (0.95, 0.94), (0.99, 0.99)))
        assert "Isolation Forest" in sentence and "supera" in sentence

    def test_one_class_svm_wins(self):
        """Se o outro ganhou, a frase diz isso — sem inventar desculpa."""
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.70, 0.71), (0.75, 0.85), (0.80, 0.92), (0.90, 0.99)))
        assert "One-Class SVM" in sentence and "melhor" in sentence

    def test_tie_at_all_levels(self):
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.80, 0.79), (0.85, 0.86), (0.90, 0.88), (0.95, 0.96)))
        assert "empataram" in sentence

    def test_both_poor(self):
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.50, 0.52), (0.55, 0.58), (0.60, 0.62), (0.65, 0.68)))
        assert "nenhum dos dois" in sentence.lower()

    def test_crossover_is_not_a_tie(self):
        """IF melhor nos desvios sutis e SVM nos fortes não é empate, ainda que a média empate."""
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.59, 0.53), (0.70, 0.69), (0.78, 0.84), (0.84, 0.95)))
        assert "empataram" not in sentence
        assert "complementam" in sentence
        assert "1 desvio-padrão" in sentence and "3 e 5 desvios-padrão" in sentence


class TestPortugueseNumbers:
    """As frases vão para a tela de Pesquisa e para o texto do TCC: decimal com vírgula."""

    def test_algorithm_verdict_uses_comma(self):
        from app.services.ml_eval import _algorithm_verdict
        sentence = _algorithm_verdict(_levels((0.80, 0.79), (0.85, 0.86), (0.90, 0.88), (0.95, 0.96)))
        assert "0." not in sentence, sentence

    def test_threshold_verdict_uses_comma(self):
        from app.services.ml_eval import _verdict
        assert "0." not in _verdict(0.95, 0.80)


class TestGradedInjection:
    """A anomalia é uma medida só, deslocada em k desvios-padrão do treino."""

    def _base(self):
        from app.services import ml_service
        rng = np.random.default_rng(0)
        X = rng.normal(50, 5, size=(40, len(ml_service.FEATURE_KEYS)))
        sigma = X.std(axis=0)
        return X, sigma

    def test_changes_single_feature(self):
        from app.services import ml_eval, ml_service
        X, sigma = self._base()
        col = ml_service.FEATURE_KEYS.index("net_connections")
        Y = ml_eval._inject_single(X, col, 2.0, sigma)
        changed = np.where(np.any(Y != X, axis=0))[0]
        assert list(changed) == [col]
        assert np.allclose(Y[:, col] - X[:, col], 2.0 * sigma[col])

    def test_respects_feature_ceiling(self):
        """CPU e memória não passam de 100%."""
        from app.services import ml_eval, ml_service
        X, sigma = self._base()
        col = ml_service.FEATURE_KEYS.index("cpu_percent")
        X[:, col] = 99.0
        assert ml_eval._inject_single(X, col, 5.0, sigma)[:, col].max() <= 100.0

    def test_time_of_day_never_perturbed(self):
        """A anomalia acontece no mesmo instante da leitura original."""
        from app.services import ml_eval, ml_service
        perturbed = {ml_service.FEATURE_KEYS[c] for c in ml_eval._perturbable_columns()}
        assert not perturbed & {"hour_sin", "hour_cos", "dow_sin", "dow_cos"}

    def test_smallest_detectable_deviation(self):
        from app.services.ml_eval import _smallest_detectable
        assert _smallest_detectable([(1, 0.6), (2, 0.93), (3, 0.99), (5, 1.0)]) == 2
        assert _smallest_detectable([(1, 0.6), (2, 0.7), (3, 0.8), (5, 0.85)]) is None

    def test_holdout_measures_all_three_per_level(self, db):
        from app.services import ml_eval
        s = ml_eval.holdout(db, _machine_with_history(db))["sensitivity"]
        assert [r["sigma"] for r in s["rows"]] == list(ml_eval.SENSITIVITY_LEVELS)
        for r in s["rows"]:
            for detector in ("isolation_forest", "one_class_svm", "sigma_baseline"):
                assert 0.0 <= r[detector] <= 1.0
        assert set(s["smallest_detectable"]) == {"isolation_forest", "one_class_svm", "sigma_baseline"}

    def test_larger_deviation_is_easier_to_detect(self, db):
        """Sanidade do método: 5 desvios precisam ser mais fáceis de perceber que 1."""
        from app.services import ml_eval
        rows = ml_eval.holdout(db, _machine_with_history(db))["sensitivity"]["rows"]
        for detector in ("isolation_forest", "one_class_svm", "sigma_baseline"):
            assert rows[-1][detector] >= rows[0][detector] - 0.01

    def test_algorithm_verdict_comes_from_graded_measurement(self, db):
        """Na injeção de oito medidas os dois empatam sempre."""
        from app.services import ml_eval
        r = ml_eval.holdout(db, _machine_with_history(db))
        assert r["algorithm_verdict"] == ml_eval._algorithm_verdict(r["sensitivity"]["rows"])

    def test_graded_is_reproducible(self, db):
        from app.services import ml_eval
        m = _machine_with_history(db)
        assert ml_eval.holdout(db, m)["sensitivity"] == ml_eval.holdout(db, m)["sensitivity"]


class TestSweepBase:
    """Com 1000 leituras-base o erro padrão da área já fica abaixo de 0,01; mais só deixa o endpoint lento."""

    def test_limits_number_of_base_readings(self):
        from app.services import ml_eval
        X = np.arange(3000 * 2, dtype=float).reshape(3000, 2)
        assert len(ml_eval._sensitivity_base(X)) == ml_eval.SENSITIVITY_MAX_BASE

    def test_spreads_over_whole_period(self):
        """As primeiras N leituras concentrariam a amostra numa faixa do dia."""
        from app.services import ml_eval
        X = np.arange(3000, dtype=float).reshape(3000, 1)
        base = ml_eval._sensitivity_base(X)
        assert base[0, 0] == 0 and base[-1, 0] == 2999

    def test_small_history_uses_everything(self):
        from app.services import ml_eval
        X = np.ones((90, 3))
        assert len(ml_eval._sensitivity_base(X)) == 90


def _untimed(ml_service):
    return [k for k in ml_service.BASE_FEATURE_KEYS if k not in ml_service.TIME_FEATURE_MIN_DAYS]


class TestMachineFeatures:
    """A avaliação mede o modelo que a máquina teria, com os atributos que ela tem."""

    def test_without_context_measures_17(self, db):
        from app.services import ml_eval, ml_service
        m = _machine_with_history(db)
        # Duas horas e meia de histórico: horário e dia da semana ainda ficam fora
        assert ml_eval.holdout(db, m)["features"] == _untimed(ml_service)

    def test_with_context_measures_what_training_would_choose(self, db):
        from app.services import ml_eval, ml_service
        m = _machine_with_history(db)
        rng = np.random.default_rng(3)
        for met in db.query(Metric).filter(Metric.machine_id == m.id).all():
            met.top_proc_cpu = float(rng.normal(15, 3))
            met.top_proc_known = 1
            met.cpu_std_10m = float(rng.normal(6, 1))
        db.commit()
        r = ml_eval.holdout(db, m)
        assert r["features"] == _untimed(ml_service) + ["top_proc_cpu", "top_proc_known", "cpu_std_10m"]
        assert r["ready"] and 0.0 <= r["auc_model"] <= 1.0

    def test_perturbable_columns_index_used_list(self):
        from app.services import ml_eval
        keys = ["top_proc_cpu", "hour_sin", "cpu_percent", "net_connections"]
        assert ml_eval._perturbable_columns(keys) == [2, 3]

    def test_ceiling_comes_from_used_list(self):
        from app.services import ml_eval
        keys = ["top_proc_cpu", "cpu_percent"]
        X = np.full((10, 2), 99.0)
        sigma = np.ones(2)
        assert ml_eval._inject_single(X, 1, 5.0, sigma, keys)[:, 1].max() <= 100.0
