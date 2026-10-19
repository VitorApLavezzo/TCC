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

3. **Escolha do algoritmo**. A proposta do trabalho cita dois algoritmos —
   Isolation Forest (Liu, Ting e Zhou, 2008) e One-Class SVM (Schölkopf et
   al., 2001) — e o sistema usa um. A mesma retenção temporal mede os dois
   nos mesmos dados, para a escolha se apoiar num número desta máquina e não
   só na literatura.

4. **Sensibilidade** (injeção graduada). A injeção original empurra oito
   medidas ao mesmo tempo: é um cenário real (um minerador mexe em CPU, rede
   e carga juntos), mas fácil demais — todos os detectores, inclusive o
   limiar de 3 desvios, chegam a área ~1,0 e a comparação não diferencia
   nada. Aqui a anomalia é uma medida só, deslocada em k desvios-padrão do
   treino, e a pergunta vira "a partir de quão sutil cada detector percebe".

O corte temporal é deliberado: separar treino e teste ao acaso deixaria
leituras do mesmo minuto dos dois lados e inflaria o resultado.
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

# Diferença de área sob a curva abaixo da qual dois detectores empatam.
MARGEM_AUC = 0.05

# Intensidades da injeção graduada, em desvios-padrão do treino. O 3 está na
# lista de propósito: é onde o limiar fixo começa a enxergar por construção, e
# o que interessa é o que cada modelo percebe abaixo dele.
SENSITIVITY_LEVELS = (1, 2, 3, 5)

# Área sob a curva a partir da qual se diz que um detector "percebe" um desvio.
DETECTABLE_AUC = 0.9

SENSITIVITY_DETECTORS = ("isolation_forest", "one_class_svm", "sigma_baseline")

# Leituras-base da varredura. Com 1000 negativos e 8000 positivos por nível
# (uma cópia por medida perturbável), o erro padrão da área sob a curva fica
# abaixo de 0,01 (Hanley e McNeil, 1982) — oito vezes menor que a margem de
# empate. Mais que isso só custava tempo: com o histórico cheio eram 96 mil
# linhas pontuadas e 8 s num endpoint síncrono.
SENSITIVITY_MAX_BASE = 1000


def _parametros() -> Dict[str, Dict[str, Any]]:
    """Hiperparâmetros dos dois algoritmos comparados — e reportados na
    resposta, porque a metodologia precisa deles para ser reproduzível.

    Os dois partem da mesma suposição sobre a fração de anomalias: `nu` do
    One-Class SVM é o limite superior dessa fração, o mesmo papel do
    `contamination` do Isolation Forest. Sem isso um deles poderia ganhar só
    por esperar mais anomalias que o outro. Nenhum dos dois é ajustado olhando
    o teste — ajustar só o SVM seria vazamento e tornaria a comparação
    desonesta.
    """
    return {
        "isolation_forest": {
            "n_estimators": 300,
            "contamination": settings.ISOLATION_FOREST_CONTAMINATION,
        },
        "one_class_svm": {
            "kernel": "rbf",
            "gamma": "scale",
            "nu": settings.ISOLATION_FOREST_CONTAMINATION,
        },
    }


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


def _perturbable_columns() -> List[int]:
    """Colunas que a injeção graduada pode deslocar — nunca hora nem dia."""
    return [ml_service.FEATURE_KEYS.index(k) for k in PERTURBABLE if k in ml_service.FEATURE_KEYS]


def _inject_single(X: np.ndarray, col: int, k: float, sigma: np.ndarray) -> np.ndarray:
    """Uma medida só, deslocada para cima em `k` desvios-padrão do treino.

    Sem ruído por amostra, ao contrário de `_inject`: os positivos já variam
    porque cada um parte de uma leitura real diferente, e um deslocamento
    exato é o que dá sentido a "k desvios".
    """
    Y = X.copy()
    Y[:, col] = Y[:, col] + k * sigma[col]
    teto = PERTURBABLE[ml_service.FEATURE_KEYS[col]][2]
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

    params = _parametros()
    scaler = StandardScaler().fit(X_train)
    modelo = IsolationForest(
        **params["isolation_forest"],
        random_state=seed,
        n_jobs=-1,
    ).fit(scaler.transform(X_train))
    # Núcleo RBF é sensível à escala: recebe o mesmo padronizador do Isolation
    # Forest, ajustado só no treino.
    svm = OneClassSVM(**params["one_class_svm"]).fit(scaler.transform(X_train))

    # decision_function: quanto menor, mais fora do padrão. Invertido, vira
    # "nota de anomalia", que é o que a curva ROC espera.
    avaliado = scaler.transform(np.vstack([X_test, X_anom]))
    scores_modelo = -modelo.decision_function(avaliado)
    scores_svm = -svm.decision_function(avaliado)
    scores_sigma = _sigma_baseline(X_train, np.vstack([X_test, X_anom]))

    auc_modelo = float(roc_auc_score(y, scores_modelo))
    auc_svm = float(roc_auc_score(y, scores_svm))
    auc_sigma = float(roc_auc_score(y, scores_sigma))
    ponto = _operating_point(modelo, scaler, X_train, X_test, X_anom)
    sensibilidade = _sensitivity(modelo, svm, scaler, X_train, X_test)

    return {
        "ready": True,
        "machine_id": machine.id,
        "samples_total": len(X),
        "samples_train": len(X_train),
        "samples_test": len(X_test),
        "samples_injected": len(X_anom),
        "auc_model": round(auc_modelo, 4),
        "auc_ocsvm": round(auc_svm, 4),
        "auc_sigma_baseline": round(auc_sigma, 4),
        "gain": round(auc_modelo - auc_sigma, 4),
        "operating_point": ponto,
        "roc": _curve(y, scores_modelo),
        "roc_ocsvm": _curve(y, scores_svm),
        "roc_baseline": _curve(y, scores_sigma),
        "verdict": _verdict(auc_modelo, auc_sigma),
        # Os dois algoritmos empatam sempre na injeção de oito medidas; é na
        # graduada que podem se diferenciar, então o veredito sai dela.
        "algorithm_verdict": _algorithm_verdict(sensibilidade["rows"]),
        "sensitivity": sensibilidade,
        "sensitivity_verdict": _sensitivity_verdict(sensibilidade),
        "params": params,
    }


def _sensitivity_base(X_test: np.ndarray) -> np.ndarray:
    """Até `SENSITIVITY_MAX_BASE` leituras, espaçadas pelo período de teste
    inteiro: as primeiras N concentrariam a amostra numa faixa do dia."""
    if len(X_test) <= SENSITIVITY_MAX_BASE:
        return X_test
    indices = np.linspace(0, len(X_test) - 1, SENSITIVITY_MAX_BASE).round().astype(int)
    return X_test[indices]


def _sensitivity(modelo, svm, scaler, X_train: np.ndarray, X_test: np.ndarray) -> Dict[str, Any]:
    """Área sob a curva de cada detector, por intensidade de desvio.

    Os negativos são as leituras de teste como vieram; os positivos, as mesmas
    leituras com uma medida deslocada — uma cópia para cada medida perturbável.
    O desvio-padrão é o do treino, o mesmo que o padronizador dos modelos e o
    limiar fixo usam: "k desvios" significa a mesma coisa para os três.
    """
    sigma = X_train.std(axis=0)
    colunas = [c for c in _perturbable_columns() if sigma[c] > 1e-9]
    X_test = _sensitivity_base(X_test)
    normal_avaliado = scaler.transform(X_test)
    notas_normais = {
        "isolation_forest": -modelo.decision_function(normal_avaliado),
        "one_class_svm": -svm.decision_function(normal_avaliado),
        "sigma_baseline": _sigma_baseline(X_train, X_test),
    }

    linhas = []
    for k in SENSITIVITY_LEVELS:
        anomalas = np.vstack([_inject_single(X_test, c, k, sigma) for c in colunas])
        anomalas_avaliadas = scaler.transform(anomalas)
        notas_anomalas = {
            "isolation_forest": -modelo.decision_function(anomalas_avaliadas),
            "one_class_svm": -svm.decision_function(anomalas_avaliadas),
            "sigma_baseline": _sigma_baseline(X_train, anomalas),
        }
        y = np.concatenate([np.zeros(len(X_test)), np.ones(len(anomalas))])
        linha: Dict[str, Any] = {"sigma": k}
        for detector in SENSITIVITY_DETECTORS:
            notas = np.concatenate([notas_normais[detector], notas_anomalas[detector]])
            linha[detector] = round(float(roc_auc_score(y, notas)), 4)
        linhas.append(linha)

    return {
        "levels": list(SENSITIVITY_LEVELS),
        "features": [ml_service.FEATURE_KEYS[c] for c in colunas],
        "rows": linhas,
        "smallest_detectable": {
            d: _smallest_detectable([(l["sigma"], l[d]) for l in linhas]) for d in SENSITIVITY_DETECTORS
        },
    }


def _smallest_detectable(pares: List[Tuple[float, float]]) -> Optional[float]:
    """Menor desvio em que o detector chega a `DETECTABLE_AUC`, ou None."""
    for k, auc in pares:
        if auc >= DETECTABLE_AUC:
            return k
    return None


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
    if diferenca >= MARGEM_AUC:
        return (f"O modelo supera o limiar fixo de três desvios por {br(diferenca, 2)} de área sob a curva: "
                "aprender o normal desta máquina rende mais do que um limite igual para todas.")
    if diferenca <= -MARGEM_AUC:
        return ("Nesta máquina o limiar fixo foi melhor que o modelo — sinal de que o histórico "
                "ainda é curto ou muito uniforme para o modelo ter o que aprender.")
    return ("Modelo e limiar fixo empataram dentro da margem. O ganho do modelo aparece em máquinas "
            "com rotina marcada, não em uso uniforme.")


def _niveis(ks: List[float]) -> str:
    """[1] -> "1 desvio-padrão"; [3, 5] -> "3 e 5 desvios-padrão"."""
    nomes = [br(k, 0) if float(k).is_integer() else br(k, 1) for k in ks]
    texto = nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]
    return f"{texto} desvio-padrão" if ks == [1] else f"{texto} desvios-padrão"


def _algorithm_verdict(linhas: List[Dict[str, Any]]) -> str:
    """Qual dos dois algoritmos da proposta separou melhor, nível a nível.

    A primeira versão comparava a média dos níveis, e a média escondia o
    resultado mais interessante: os dois podem se cruzar — um melhor nos
    desvios sutis, o outro nos fortes. Num histórico sintético com rotina, o
    Isolation Forest ganhava em 1 desvio e o One-Class SVM em 3 e 5, e a média
    os empatava dizendo que "a escolha não muda a detecção". Mudava, em
    sentidos opostos.

    Se o One-Class SVM ganhar, a frase diz isso e para aí: inventar uma razão
    para ter ficado com o Isolation Forest mesmo assim seria pior que o
    resultado desfavorável. Na medição de custo feita para esta comparação, o
    SVM com `nu` = 0,03 foi até mais rápido — custo não serve de desculpa.
    """
    melhor_isolation = [l["sigma"] for l in linhas
                        if l["isolation_forest"] - l["one_class_svm"] >= MARGEM_AUC]
    melhor_svm = [l["sigma"] for l in linhas
                  if l["one_class_svm"] - l["isolation_forest"] >= MARGEM_AUC]

    if max(max(l["isolation_forest"], l["one_class_svm"]) for l in linhas) < 0.7:
        return ("Nenhum dos dois algoritmos separa bem as leituras desviadas das normais nesta "
                "máquina (área sob a curva abaixo de 0,70 em todos os níveis).")
    if melhor_isolation and melhor_svm:
        return (f"Os dois se complementam nesta máquina: o Isolation Forest separa melhor os desvios "
                f"de {_niveis(melhor_isolation)}, e o One-Class SVM, os de {_niveis(melhor_svm)}.")
    if melhor_isolation:
        return (f"O Isolation Forest supera o One-Class SVM nos desvios de {_niveis(melhor_isolation)} "
                "e não perde em nenhum nível: a escolha do algoritmo se sustenta nos dados, não só "
                "na literatura.")
    if melhor_svm:
        return (f"Nesta máquina o One-Class SVM separou melhor que o Isolation Forest nos desvios de "
                f"{_niveis(melhor_svm)}, sem perder em nenhum nível.")
    return (f"Isolation Forest e One-Class SVM empataram em todos os níveis, dentro da margem de "
            f"{br(MARGEM_AUC, 2)}: nesta máquina a escolha entre os dois não muda a detecção.")


_NOMES = {
    "isolation_forest": "o Isolation Forest",
    "one_class_svm": "o One-Class SVM",
    "sigma_baseline": "o limiar fixo",
}


def _sensitivity_verdict(sensibilidade: Dict[str, Any]) -> str:
    """Quão sutil é o menor desvio que cada detector percebe, numa frase."""
    maior = SENSITIVITY_LEVELS[-1]
    partes = []
    for detector in SENSITIVITY_DETECTORS:
        k = sensibilidade["smallest_detectable"][detector]
        if k is None:
            partes.append(f"{_NOMES[detector]} não chega a perceber nem com {maior}")
        else:
            partes.append(f"{_NOMES[detector]} a partir de {k}")
    return ("Desviando uma medida só, " + ", ".join(partes[:-1]) + " e " + partes[-1]
            + f" desvios-padrão (área sob a curva ≥ {br(DETECTABLE_AUC, 1)}).")


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
