"""
Avaliação do modelo em si: ele acrescenta alguma coisa às regras?

O benchmark de detecção mede o sistema inteiro — regras e modelo juntos,
pelo caminho real. Isso responde "o produto funciona?", mas deixa em aberto a
pergunta que uma banca faz sobre a parte de aprendizado de máquina: o
Isolation Forest está puxando peso, ou as sete heurísticas já faziam tudo?

Aqui ficam as duas medições que respondem isso:

1. **Validação por retenção temporal** (holdout). O modelo é treinado com a
   primeira parte do histórico da máquina e avaliado na parte final, que ele
   nunca viu. Como não existe rótulo de falha em dado real de uso normal, os
   positivos são anomalias injetadas nas leituras de teste — a mesma técnica
   dos cenários do benchmark, aplicada a dado real. A comparação é contra um
   detector de limiar fixo (três desvios-padrão), que é o que um sistema de
   monitoramento comum faz. Se a área sob a curva do modelo não superar a do
   limiar fixo, o modelo não se justifica.

2. **Ablação**: os mesmos cenários do benchmark rodados três vezes — só
   regras, só modelo, os dois — para mostrar o que cada camada contribui.

O corte temporal é deliberado: separar treino e teste ao acaso deixaria
leituras do mesmo minuto dos dois lados e inflaria o resultado.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import tz_offset_minutes
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import ml_service

# Mínimo para o corte fazer sentido: menos do que isso e o teste é anedota
MIN_SAMPLES = 200
TEST_RATIO = 0.3

# Índices, dentro do vetor de atributos, das medidas que uma anomalia mexe.
# As cíclicas (hora, dia) não são perturbadas: a anomalia injetada acontece
# no mesmo instante da leitura original.
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


def _inject(X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Cria positivos a partir de leituras reais, exagerando o que uma anomalia exagera."""
    Y = X.copy()
    for chave, (modo, fator, teto) in PERTURBABLE.items():
        if chave not in ml_service.FEATURE_KEYS:
            continue
        col = ml_service.FEATURE_KEYS.index(chave)
        # Ruído por amostra: sem ele, todos os positivos ficariam alinhados
        # num ponto só e a curva ROC sairia otimista demais.
        escala = fator * rng.uniform(0.7, 1.3, size=Y.shape[0])
        if modo == "multiplicar":
            Y[:, col] = Y[:, col] * escala
        else:
            Y[:, col] = Y[:, col] + escala
        if teto is not None:
            Y[:, col] = np.minimum(Y[:, col], teto)
    return Y


def _sigma_baseline(train: np.ndarray, test: np.ndarray) -> np.ndarray:
    """Detector ingênuo: maior desvio padronizado entre as métricas da leitura.

    É o equivalente ao alarme por limiar fixo de um Zabbix ou de um Netdata
    configurado no olho, e serve como piso de comparação.
    """
    media = train.mean(axis=0)
    desvio = train.std(axis=0)
    desvio[desvio < 1e-9] = 1e-9
    return np.max(np.abs((test - media) / desvio), axis=1)


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

    X = np.array([ml_service._metric_to_vector(m, offset) for m in metrics], dtype=float)
    corte = int(len(X) * (1 - test_ratio))
    X_train, X_test = X[:corte], X[corte:]
    if len(X_test) < 30:
        return {"ready": False, "reason": "A parte de teste ficou pequena demais para medir."}

    rng = np.random.default_rng(seed)
    X_anom = _inject(X_test, rng)
    y = np.concatenate([np.zeros(len(X_test)), np.ones(len(X_anom))])

    scaler = StandardScaler().fit(X_train)
    modelo = IsolationForest(
        n_estimators=300,
        contamination=settings.ISOLATION_FOREST_CONTAMINATION,
        random_state=seed,
        n_jobs=-1,
    ).fit(scaler.transform(X_train))

    # decision_function: quanto menor, mais fora do padrão. Invertido, vira
    # "nota de anomalia", que é o que a curva ROC espera.
    scores_modelo = -modelo.decision_function(scaler.transform(np.vstack([X_test, X_anom])))
    scores_sigma = _sigma_baseline(X_train, np.vstack([X_test, X_anom]))

    auc_modelo = float(roc_auc_score(y, scores_modelo))
    auc_sigma = float(roc_auc_score(y, scores_sigma))
    ponto = _operating_point(modelo, scaler, X_train, X_test, X_anom)

    return {
        "ready": True,
        "machine_id": machine.id,
        "samples_total": len(X),
        "samples_train": len(X_train),
        "samples_test": len(X_test),
        "samples_injected": len(X_anom),
        "auc_model": round(auc_modelo, 4),
        "auc_sigma_baseline": round(auc_sigma, 4),
        "gain": round(auc_modelo - auc_sigma, 4),
        "operating_point": ponto,
        "roc": _curve(y, scores_modelo),
        "roc_baseline": _curve(y, scores_sigma),
        "verdict": _verdict(auc_modelo, auc_sigma),
    }


def _operating_point(modelo, scaler, X_train, X_test, X_anom) -> Dict[str, Any]:
    """Precisão e revocação no limiar que o sistema usa de verdade.

    A área sob a curva resume todos os limiares possíveis; este é o número
    que descreve o comportamento real, com o percentil configurado.
    """
    notas_treino = modelo.decision_function(scaler.transform(X_train))
    limite = min(float(np.percentile(notas_treino, settings.ML_ALERT_PERCENTILE)), 0.0)
    normais = modelo.decision_function(scaler.transform(X_test))
    anomalos = modelo.decision_function(scaler.transform(X_anom))

    tp = int(np.sum(anomalos < limite))
    fn = int(len(anomalos) - tp)
    fp = int(np.sum(normais < limite))
    tn = int(len(normais) - fp)
    precisao = tp / (tp + fp) if (tp + fp) else None
    revocacao = tp / (tp + fn) if (tp + fn) else None
    return {
        "threshold": round(limite, 4),
        "percentile": settings.ML_ALERT_PERCENTILE,
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "precision": round(precisao, 4) if precisao is not None else None,
        "recall": round(revocacao, 4) if revocacao is not None else None,
        "false_positive_rate": round(fp / len(normais), 4) if len(normais) else None,
    }


def _curve(y: np.ndarray, scores: np.ndarray, pontos: int = 40) -> List[Dict[str, float]]:
    """Curva ROC reduzida a poucos pontos — o suficiente para o gráfico."""
    fpr, tpr, _ = roc_curve(y, scores)
    if len(fpr) <= pontos:
        indices = range(len(fpr))
    else:
        indices = np.linspace(0, len(fpr) - 1, pontos).astype(int)
    return [{"fpr": round(float(fpr[i]), 4), "tpr": round(float(tpr[i]), 4)} for i in indices]


def _verdict(auc_modelo: float, auc_sigma: float) -> str:
    diferenca = auc_modelo - auc_sigma
    if auc_modelo < 0.7:
        return ("O modelo separa mal as leituras injetadas das normais nesta máquina "
                "(área sob a curva abaixo de 0,70). Aqui, quem está sustentando a detecção são as regras.")
    if diferenca >= 0.05:
        return (f"O modelo supera o limiar fixo de três desvios por {diferenca:.02f} de área sob a curva: "
                "aprender o normal desta máquina rende mais do que um limite igual para todas.")
    if diferenca <= -0.05:
        return ("Nesta máquina o limiar fixo foi melhor que o modelo — sinal de que o histórico "
                "ainda é curto ou muito uniforme para o modelo ter o que aprender.")
    return ("Modelo e limiar fixo empataram dentro da margem. O ganho do modelo aparece em máquinas "
            "com rotina marcada, não em uso uniforme.")


LAYER_LABELS = {
    "regras": "Só detectores por regra",
    "ml": "Só Isolation Forest",
    "ambas": "As duas camadas (sistema completo)",
}


def ablation(db: Session, owner_id: int, names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Roda os cenários do benchmark uma vez por camada de detecção.

    É a resposta em número para "o modelo acrescenta alguma coisa?": se a
    linha "as duas" empata com "só regras", o modelo não está contribuindo.
    """
    from app.services import anomaly_service, benchmark

    anterior = anomaly_service.detection_layer()
    linhas = []
    try:
        for camada in ("regras", "ml", "ambas"):
            anomaly_service.set_detection_layer(camada)
            resultado = benchmark.run(db, owner_id, names)
            metrics = resultado.metrics
            linhas.append({
                "layer": camada,
                "label": LAYER_LABELS[camada],
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "true_positives": metrics.get("true_positives"),
                "false_negatives": metrics.get("false_negatives"),
                "false_positives": metrics.get("false_positives"),
                "scenarios": len(resultado.scenarios),
                "detected_types": sorted({t for s in resultado.scenarios for t in s.detected}),
            })
    finally:
        # Deixar o servidor com meia detecção ligada por causa de um erro aqui
        # seria muito pior que o erro.
        anomaly_service.set_detection_layer(anterior)

    return {"rows": linhas, "sentence": _ablation_sentence(linhas)}


def _ablation_sentence(linhas: List[Dict[str, Any]]) -> str:
    por_camada = {linha["layer"]: linha for linha in linhas}
    regras = por_camada.get("regras", {})
    ambas = por_camada.get("ambas", {})
    ml = por_camada.get("ml", {})
    if not regras or not ambas:
        return "Não foi possível comparar as camadas."

    tp_regras = regras.get("true_positives") or 0
    tp_ambas = ambas.get("true_positives") or 0
    tp_ml = ml.get("true_positives") or 0
    if tp_ambas > tp_regras:
        return (f"As regras sozinhas encontraram {tp_regras} dos ataques; com o modelo, "
                f"{tp_ambas}. O Isolation Forest sozinho encontrou {tp_ml} — "
                "as duas camadas pegam coisas diferentes, e é por isso que o sistema usa as duas.")
    if tp_ml == 0:
        return (f"Nestes cenários, as regras respondem por toda a detecção ({tp_regras} ataques) e o "
                "modelo não encontrou nenhum sozinho. O papel dele aqui é outro: cobrir o desvio "
                "que ninguém escreveu como regra.")
    return (f"As duas camadas encontram {tp_ambas} ataques, as regras sozinhas {tp_regras} e o modelo "
            f"sozinho {tp_ml}: há sobreposição grande entre elas nestes cenários.")
