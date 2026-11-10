"""Avaliação do modelo em si: ele acrescenta alguma coisa às regras?

Retenção temporal (treina no início do histórico, mede no fim com anomalias
injetadas) contra um limiar fixo de três desvios e contra o One-Class SVM,
sensibilidade por injeção graduada de uma medida só e ablação por camada.
O corte é temporal de propósito: separar ao acaso deixaria leituras do mesmo
minuto dos dois lados e inflaria o resultado.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import tz_offset_minutes
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import ml_service
from app.services.forecasting import br

# Mínimo para o corte fazer sentido: menos do que isso e o teste é anedota
MIN_SAMPLES = 200
TEST_RATIO = 0.3

# Diferença de área sob a curva abaixo da qual dois detectores empatam
AUC_MARGIN = 0.05

# Em desvios-padrão do treino. O 3 é onde o limiar fixo começa a enxergar por
# construção; o que interessa é o que cada modelo percebe abaixo dele.
SENSITIVITY_LEVELS = (1, 2, 3, 5)

# Área sob a curva a partir da qual um detector "percebe" um desvio
DETECTABLE_AUC = 0.9

SENSITIVITY_DETECTORS = ("isolation_forest", "one_class_svm", "sigma_baseline")

# Com 1000 negativos e 8000 positivos por nível, o erro padrão da área sob a
# curva fica abaixo de 0,01 (Hanley e McNeil, 1982); mais só custa tempo num endpoint síncrono.
SENSITIVITY_MAX_BASE = 1000


def _hyperparameters() -> Dict[str, Dict[str, Any]]:
    """Hiperparâmetros dos dois algoritmos, reportados para a metodologia ser reproduzível.

    `nu` tem o papel do `contamination`: nenhum ganha só por esperar mais anomalias,
    e nenhum é ajustado olhando o teste.
    """
    return {
        "isolation_forest": {
            "n_estimators": 300,
            "contamination": settings.ISOLATION_FOREST_CONTAMINATION,
        },
        "one_class_svm": ml_service.svm_params(),
    }


# Medidas que uma anomalia mexe. As cíclicas (hora, dia) não são perturbadas: a
# anomalia injetada acontece no mesmo instante da leitura original.
PERTURBABLE = {
    "cpu_percent": ("multiplicar", 3.2, 100.0),
    "mem_percent": ("somar", 32.0, 100.0),
    "swap_percent": ("somar", 25.0, 100.0),
    "net_bytes_sent": ("multiplicar", 9.0, None),
    "net_bytes_recv": ("multiplicar", 7.0, None),
    "net_connections": ("multiplicar", 6.0, None),
    "load_avg_1": ("multiplicar", 4.0, None),
    "process_count": ("multiplicar", 1.8, None),
}


def _inject(X: np.ndarray, rng: np.random.Generator, keys: Optional[List[str]] = None) -> np.ndarray:
    """Cria positivos a partir de leituras reais, exagerando o que uma anomalia exagera."""
    keys = ml_service.FEATURE_KEYS if keys is None else keys
    Y = X.copy()
    for key, (mode, factor, cap) in PERTURBABLE.items():
        if key not in keys:
            continue
        col = keys.index(key)
        # Ruído por amostra: sem ele, todos os positivos ficariam alinhados
        # num ponto só e a curva ROC sairia otimista demais.
        scale = factor * rng.uniform(0.7, 1.3, size=Y.shape[0])
        if mode == "multiplicar":
            Y[:, col] = Y[:, col] * scale
        else:
            Y[:, col] = Y[:, col] + scale
        if cap is not None:
            Y[:, col] = np.minimum(Y[:, col], cap)
    return Y


def _perturbable_columns(keys: Optional[List[str]] = None) -> List[int]:
    """Colunas de `keys` que a injeção graduada pode deslocar — nunca hora nem dia."""
    keys = ml_service.FEATURE_KEYS if keys is None else keys
    return [i for i, k in enumerate(keys) if k in PERTURBABLE]


def _inject_single(X: np.ndarray, col: int, k: float, sigma: np.ndarray,
                   keys: Optional[List[str]] = None) -> np.ndarray:
    """Uma medida só, deslocada para cima em `k` desvios-padrão do treino.

    Sem ruído por amostra: cada positivo já parte de uma leitura real diferente,
    e um deslocamento exato é o que dá sentido a "k desvios".
    """
    Y = X.copy()
    Y[:, col] = Y[:, col] + k * sigma[col]
    keys = ml_service.FEATURE_KEYS if keys is None else keys
    cap = PERTURBABLE[keys[col]][2]
    if cap is not None:
        Y[:, col] = np.minimum(Y[:, col], cap)
    return Y


def _sigma_baseline(train: np.ndarray, test: np.ndarray) -> np.ndarray:
    """Detector ingênuo (limiar fixo): maior desvio padronizado entre as métricas da leitura."""
    mean = train.mean(axis=0)
    std = train.std(axis=0)
    std[std < 1e-9] = 1e-9
    return np.max(np.abs((test - mean) / std), axis=1)


def holdout(db: Session, machine: Machine, test_ratio: float = TEST_RATIO,
            seed: int = 42) -> Dict[str, Any]:
    """Treina na primeira parte do histórico e mede na parte final."""
    offset = tz_offset_minutes(machine)
    metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine.id)
        .order_by(Metric.timestamp.asc())
        .limit(settings.TRAINING_WINDOW * 2)
        .all()
    )
    if len(metrics) < MIN_SAMPLES:
        return {"ready": False,
                "reason": f"São precisas ao menos {MIN_SAMPLES} leituras; esta máquina tem {len(metrics)}."}

    # Os atributos que o treino desta máquina escolheria, decididos só com a
    # parte de treino — a de teste não pode influir no que o modelo enxerga
    split = int(len(metrics) * (1 - test_ratio))
    keys = ml_service.available_features(metrics[:split])
    fill = ml_service.training_fill(metrics[:split], keys)
    X = np.array([ml_service._metric_to_vector(m, offset, keys, fill) for m in metrics], dtype=float)
    X_train, X_test = X[:split], X[split:]
    if len(X_test) < 30:
        return {"ready": False, "reason": "A parte de teste ficou pequena demais para medir."}

    rng = np.random.default_rng(seed)
    X_anom = _inject(X_test, rng, keys)
    y = np.concatenate([np.zeros(len(X_test)), np.ones(len(X_anom))])

    params = _hyperparameters()
    scaler = StandardScaler().fit(X_train)
    model = IsolationForest(
        **params["isolation_forest"],
        random_state=seed,
        n_jobs=-1,
    ).fit(scaler.transform(X_train))
    # Núcleo RBF é sensível à escala: recebe o mesmo padronizador do Isolation
    # Forest, ajustado só no treino.
    svm = OneClassSVM(**params["one_class_svm"]).fit(scaler.transform(X_train))

    # decision_function: quanto menor, mais fora do padrão. Invertido, vira
    # "nota de anomalia", que é o que a curva ROC espera.
    evaluated = scaler.transform(np.vstack([X_test, X_anom]))
    scores_model = -model.decision_function(evaluated)
    scores_svm = -svm.decision_function(evaluated)
    scores_sigma = _sigma_baseline(X_train, np.vstack([X_test, X_anom]))

    auc_model = float(roc_auc_score(y, scores_model))
    auc_svm = float(roc_auc_score(y, scores_svm))
    auc_sigma = float(roc_auc_score(y, scores_sigma))
    point = _operating_point(model, scaler, X_train, X_test, X_anom)
    sensitivity = _sensitivity(model, svm, scaler, X_train, X_test, keys)

    return {
        "ready": True,
        "machine_id": machine.id,
        "samples_total": len(X),
        "samples_train": len(X_train),
        "samples_test": len(X_test),
        "samples_injected": len(X_anom),
        "features": keys,
        "auc_model": round(auc_model, 4),
        "auc_ocsvm": round(auc_svm, 4),
        "auc_sigma_baseline": round(auc_sigma, 4),
        "gain": round(auc_model - auc_sigma, 4),
        "operating_point": point,
        "roc": _curve(y, scores_model),
        "roc_ocsvm": _curve(y, scores_svm),
        "roc_baseline": _curve(y, scores_sigma),
        "verdict": _verdict(auc_model, auc_sigma),
        # Os dois algoritmos empatam sempre na injeção de oito medidas; é na
        # graduada que podem se diferenciar, então o veredito sai dela.
        "algorithm_verdict": _algorithm_verdict(sensitivity["rows"]),
        "sensitivity": sensitivity,
        "sensitivity_verdict": _sensitivity_verdict(sensitivity),
        "params": params,
    }


def _sensitivity_base(X_test: np.ndarray) -> np.ndarray:
    """Até `SENSITIVITY_MAX_BASE` leituras, espaçadas pelo período de teste
    inteiro: as primeiras N concentrariam a amostra numa faixa do dia."""
    if len(X_test) <= SENSITIVITY_MAX_BASE:
        return X_test
    indices = np.linspace(0, len(X_test) - 1, SENSITIVITY_MAX_BASE).round().astype(int)
    return X_test[indices]


def _sensitivity(model, svm, scaler, X_train: np.ndarray, X_test: np.ndarray,
                 keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Área sob a curva de cada detector, por intensidade de desvio.

    Os negativos são as leituras de teste como vieram; os positivos, as mesmas
    leituras com uma medida deslocada — uma cópia para cada medida perturbável.
    O desvio-padrão é o do treino, o mesmo que o padronizador dos modelos e o
    limiar fixo usam: "k desvios" significa a mesma coisa para os três.
    """
    sigma = X_train.std(axis=0)
    keys = ml_service.FEATURE_KEYS if keys is None else keys
    columns = [c for c in _perturbable_columns(keys) if sigma[c] > 1e-9]
    X_test = _sensitivity_base(X_test)
    normal_scaled = scaler.transform(X_test)
    normal_scores = {
        "isolation_forest": -model.decision_function(normal_scaled),
        "one_class_svm": -svm.decision_function(normal_scaled),
        "sigma_baseline": _sigma_baseline(X_train, X_test),
    }

    rows = []
    for k in SENSITIVITY_LEVELS:
        anomalous = np.vstack([_inject_single(X_test, c, k, sigma, keys) for c in columns])
        anomalous_scaled = scaler.transform(anomalous)
        anomalous_scores = {
            "isolation_forest": -model.decision_function(anomalous_scaled),
            "one_class_svm": -svm.decision_function(anomalous_scaled),
            "sigma_baseline": _sigma_baseline(X_train, anomalous),
        }
        y = np.concatenate([np.zeros(len(X_test)), np.ones(len(anomalous))])
        row: Dict[str, Any] = {"sigma": k}
        for detector in SENSITIVITY_DETECTORS:
            scores = np.concatenate([normal_scores[detector], anomalous_scores[detector]])
            row[detector] = round(float(roc_auc_score(y, scores)), 4)
        rows.append(row)

    return {
        "levels": list(SENSITIVITY_LEVELS),
        "features": [keys[c] for c in columns],
        "rows": rows,
        "smallest_detectable": {
            d: _smallest_detectable([(l["sigma"], l[d]) for l in rows]) for d in SENSITIVITY_DETECTORS
        },
    }


def _smallest_detectable(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """Menor desvio em que o detector chega a `DETECTABLE_AUC`, ou None."""
    for k, auc in pairs:
        if auc >= DETECTABLE_AUC:
            return k
    return None


def _operating_point(model, scaler, X_train, X_test, X_anom) -> Dict[str, Any]:
    """Precisão e revocação no limiar que o sistema usa de verdade (o percentil configurado)."""
    train_scores = model.decision_function(scaler.transform(X_train))
    threshold = min(float(np.percentile(train_scores, settings.ML_ALERT_PERCENTILE)), 0.0)
    normal = model.decision_function(scaler.transform(X_test))
    anomalous = model.decision_function(scaler.transform(X_anom))

    tp = int(np.sum(anomalous < threshold))
    fn = int(len(anomalous) - tp)
    fp = int(np.sum(normal < threshold))
    tn = int(len(normal) - fp)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "threshold": round(threshold, 4),
        "percentile": settings.ML_ALERT_PERCENTILE,
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "false_positive_rate": round(fp / len(normal), 4) if len(normal) else None,
    }


def _curve(y: np.ndarray, scores: np.ndarray, points: int = 40) -> List[Dict[str, float]]:
    """Curva ROC reduzida a poucos pontos — o suficiente para o gráfico."""
    fpr, tpr, _ = roc_curve(y, scores)
    if len(fpr) <= points:
        indices = range(len(fpr))
    else:
        indices = np.linspace(0, len(fpr) - 1, points).astype(int)
    return [{"fpr": round(float(fpr[i]), 4), "tpr": round(float(tpr[i]), 4)} for i in indices]


def _verdict(auc_model: float, auc_sigma: float) -> str:
    diff = auc_model - auc_sigma
    if auc_model < 0.7:
        return ("O modelo separa mal as leituras injetadas das normais nesta máquina "
                "(área sob a curva abaixo de 0,70). Aqui, quem está sustentando a detecção são as regras.")
    if diff >= AUC_MARGIN:
        return (f"O modelo supera o limiar fixo de três desvios por {br(diff, 2)} de área sob a curva: "
                "aprender o normal desta máquina rende mais do que um limite igual para todas.")
    if diff <= -AUC_MARGIN:
        return ("Nesta máquina o limiar fixo foi melhor que o modelo — sinal de que o histórico "
                "ainda é curto ou muito uniforme para o modelo ter o que aprender.")
    return ("Modelo e limiar fixo empataram dentro da margem. O ganho do modelo aparece em máquinas "
            "com rotina marcada, não em uso uniforme.")


def _levels_text(ks: List[float]) -> str:
    """[1] -> "1 desvio-padrão"; [3, 5] -> "3 e 5 desvios-padrão"."""
    names = [br(k, 0) if float(k).is_integer() else br(k, 1) for k in ks]
    text = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
    return f"{text} desvio-padrão" if ks == [1] else f"{text} desvios-padrão"


def _algorithm_verdict(rows: List[Dict[str, Any]]) -> str:
    """Qual dos dois algoritmos separou melhor, nível a nível.

    Não pela média: os dois podem se cruzar (um melhor nos desvios sutis, o outro
    nos fortes). Se o One-Class SVM ganhar, a frase diz isso, sem desculpas.
    """
    isolation_wins = [l["sigma"] for l in rows
                      if l["isolation_forest"] - l["one_class_svm"] >= AUC_MARGIN]
    svm_wins = [l["sigma"] for l in rows
                if l["one_class_svm"] - l["isolation_forest"] >= AUC_MARGIN]

    if max(max(l["isolation_forest"], l["one_class_svm"]) for l in rows) < 0.7:
        return ("Nenhum dos dois algoritmos separa bem as leituras desviadas das normais nesta "
                "máquina (área sob a curva abaixo de 0,70 em todos os níveis).")
    if isolation_wins and svm_wins:
        return (f"Os dois se complementam nesta máquina: o Isolation Forest separa melhor os desvios "
                f"de {_levels_text(isolation_wins)}, e o One-Class SVM, os de {_levels_text(svm_wins)}.")
    if isolation_wins:
        return (f"O Isolation Forest supera o One-Class SVM nos desvios de {_levels_text(isolation_wins)} "
                "e não perde em nenhum nível: a escolha do algoritmo se sustenta nos dados, não só "
                "na literatura.")
    if svm_wins:
        return (f"Nesta máquina o One-Class SVM separou melhor que o Isolation Forest nos desvios de "
                f"{_levels_text(svm_wins)}, sem perder em nenhum nível.")
    return (f"Isolation Forest e One-Class SVM empataram em todos os níveis, dentro da margem de "
            f"{br(AUC_MARGIN, 2)}: nesta máquina a escolha entre os dois não muda a detecção.")


_DETECTOR_NAMES = {
    "isolation_forest": "o Isolation Forest",
    "one_class_svm": "o One-Class SVM",
    "sigma_baseline": "o limiar fixo",
}


def _sensitivity_verdict(sensitivity: Dict[str, Any]) -> str:
    """Quão sutil é o menor desvio que cada detector percebe, numa frase."""
    largest = SENSITIVITY_LEVELS[-1]
    parts = []
    for detector in SENSITIVITY_DETECTORS:
        k = sensitivity["smallest_detectable"][detector]
        if k is None:
            parts.append(f"{_DETECTOR_NAMES[detector]} não chega a perceber nem com {largest}")
        else:
            parts.append(f"{_DETECTOR_NAMES[detector]} a partir de {k}")
    return ("Desviando uma medida só, " + ", ".join(parts[:-1]) + " e " + parts[-1]
            + f" desvios-padrão (área sob a curva ≥ {br(DETECTABLE_AUC, 1)}).")


LAYER_LABELS = {
    "regras": "Só detectores por regra",
    "ml": "Só Isolation Forest",
    "ambas": "As duas camadas (sistema completo)",
}


def ablation(db: Session, owner_id: int, names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Roda os cenários do benchmark uma vez por camada de detecção."""
    from app.services import anomaly_service, benchmark

    previous = anomaly_service.detection_layer()
    rows = []
    try:
        for layer in ("regras", "ml", "ambas"):
            anomaly_service.set_detection_layer(layer)
            result = benchmark.run(db, owner_id, names)
            metrics = result.metrics
            rows.append({
                "layer": layer,
                "label": LAYER_LABELS[layer],
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "true_positives": metrics.get("true_positives"),
                # Ataques com algum aviso, mesmo de outro tipo: "o modelo viu"
                "seen": metrics.get("seen"),
                "false_negatives": metrics.get("false_negatives"),
                "false_positives": metrics.get("false_positives"),
                "scenarios": len(result.scenarios),
                "detected_types": sorted({t for s in result.scenarios for t in s.detected}),
                "hits": sorted(s.name for s in result.scenarios
                               if s.family == benchmark.ATTACK and s.expected in s.detected),
            })
    finally:
        # Deixar o servidor com meia detecção por causa de um erro seria pior que o erro
        anomaly_service.set_detection_layer(previous)

    return {"rows": rows, "sentence": _ablation_sentence(rows)}


def _ablation_sentence(rows: List[Dict[str, Any]]) -> str:
    by_layer = {row["layer"]: row for row in rows}
    rules = by_layer.get("regras", {})
    both = by_layer.get("ambas", {})
    ml = by_layer.get("ml", {})
    if not rules or not both:
        return "Não foi possível comparar as camadas."

    tp_rules = rules.get("true_positives") or 0
    tp_both = both.get("true_positives") or 0
    tp_ml = ml.get("true_positives") or 0
    if tp_both > tp_rules:
        # O sistema completo também roda as previsões: nem todo acerto a mais é do modelo
        extra = set(both.get("hits") or []) - set(rules.get("hits") or [])
        from_model = len(extra & set(ml.get("hits") or []))
        from_rest = len(extra) - from_model
        return (f"As regras sozinhas encontraram {tp_rules} dos ataques, e o sistema completo, {tp_both}. "
                f"Dos acertos a mais, {from_model} {'também aparece' if from_model == 1 else 'também aparecem'} "
                f"com o Isolation Forest sozinho e {from_rest} {'vem' if from_rest == 1 else 'vêm'} de outra "
                f"parte do sistema, como a previsão de disco. O Isolation Forest sozinho encontrou {tp_ml}.")
    if tp_ml == 0:
        return (f"Nestes cenários, as regras respondem por toda a detecção ({tp_rules} ataques) e o "
                "modelo não encontrou nenhum sozinho. O papel dele aqui é outro: cobrir o desvio "
                "que ninguém escreveu como regra.")
    return (f"As duas camadas encontram {tp_both} ataques, as regras sozinhas {tp_rules} e o modelo "
            f"sozinho {tp_ml}: há sobreposição grande entre elas nestes cenários.")
