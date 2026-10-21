"""
Avaliação em dado real: o resultado do TCC.

Cruza o que a pessoa marcou que estava fazendo (`activity_labels`) com o que o
sistema avisou. Duas leituras do mesmo dado:

- **ao vivo** (`live`): os avisos que de fato nasceram durante as sessões, e
  se interromperam — pelo status da notificação, não pela gravidade;
- **reprodução** (`replay`): as mesmas leituras gravadas passam de novo pelo
  pipeline numa máquina efêmera, com o contexto ligado e desligado e camada
  por camada. É a resposta, com dado real, para "o ML separa jogo de
  minerador?" e "o que cada parte acrescenta?".

Sessão benigna (jogo, trabalho pesado, uso normal) é negativa: aviso que
interrompe nela é alarme falso. Sessão de teste atômico é positiva, e só conta
como acerto com a evidência certa — aviso sobre outro programa no mesmo
horário não é ter visto o minerador.

Os rótulos ficam só aqui e no cadastro: a detecção nunca os lê (há um teste
que garante), senão a medida mediria a própria resposta.
"""
from datetime import timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.notification import Notification
from app.services import activity_labels

# Como reconhecer o acerto de cada teste atômico
EVIDENCE: Dict[str, Dict[str, str]] = {
    "teste_minerador": {"process": "svc_update.exe"},
    "teste_minerador_em_uso": {"process": "svc_update.exe"},
    "teste_disfarce": {"type": "process_masquerading"},
    "teste_isca": {"type": "ransomware_canary"},
    "teste_periodico": {"type": "beaconing"},
}

# Status de notificação que chegam (ou vão chegar) à pessoa. `held` vai no
# resumo diário e `suppressed` só fica no painel: não interrompem.
INTERRUPTING = {"sent", "grouped", "pending"}

# Sessão esquecida aberta não vira uma sessão de dias
MAX_SESSION_HOURS = 6

# Configurações da reprodução: (contexto ligado?, camada)
REPLAY_CONFIGS = {
    "contexto_ligado": (True, "ambas"),
    "contexto_desligado": (False, "ambas"),
    "regras": (True, "regras"),
    "ml": (True, "ml"),
}

REPLAY_LABELS = {
    "contexto_ligado": "Sistema completo, com contexto de uso",
    "contexto_desligado": "Sistema completo, sem contexto de uso",
    "regras": "Só detectores por regra",
    "ml": "Só Isolation Forest",
}


def _ratio(num: int, den: int) -> Optional[float]:
    return num / den if den else None


def sessions(db: Session, machine_id: int, start, end) -> List[Dict[str, Any]]:
    """As sessões rotuladas do período, com o fim já decidido.

    Marcar um rótulo novo fecha o anterior; a sessão que ficou aberta termina
    agora ou em MAX_SESSION_HOURS, o que vier antes.
    """
    agora = utcnow()
    out = []
    for s in activity_labels.sessions(db, machine_id, aware(start), aware(end)):
        if s.label not in activity_labels.LABELS:
            continue
        inicio = aware(s.started_at)
        fim = aware(s.ended_at) if s.ended_at else agora
        fim = min(fim, inicio + timedelta(hours=MAX_SESSION_HOURS))
        if fim <= inicio:
            continue
        out.append({
            "id": s.id, "label": s.label, "name": activity_labels.LABELS[s.label],
            "start": inicio, "end": fim, "hours": (fim - inicio).total_seconds() / 3600,
            "benign": s.label in activity_labels.BENIGN,
        })
    return out


def _live_anomalies(db: Session, machine_id: int, start, end) -> List[Dict[str, Any]]:
    """Avisos que cruzam o período, cada um com os instantes em que interrompeu."""
    rows = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine_id, Anomaly.detected_at <= end)
        .all()
    )
    avisos = []
    for a in rows:
        detectado = aware(a.detected_at)
        ultimo = aware(a.last_seen_at) or detectado
        if detectado is None or ultimo < start:
            continue
        interrupcoes = [
            aware(n.created_at)
            for n in db.query(Notification).filter(Notification.anomaly_id == a.id, Notification.kind == "anomaly",
                                                   Notification.status.in_(INTERRUPTING)).all()
            if n.created_at is not None
        ]
        avisos.append({
            "type": a.anomaly_type, "severity": a.severity, "responsible": a.responsible_process,
            "programas": list((a.affected_metrics or {}).get("programas") or []),
            "detected_at": detectado, "last_seen_at": ultimo, "interrupted_at": interrupcoes,
        })
    return avisos


def _matches(aviso: Dict[str, Any], evidencia: Dict[str, str]) -> bool:
    if "type" in evidencia:
        return aviso["type"] == evidencia["type"]
    alvo = evidencia["process"].lower()
    nomes = [aviso.get("responsible") or ""] + list(aviso.get("programas") or [])
    return any((n or "").lower() == alvo for n in nomes)


def _within(t, sessao) -> bool:
    return t is not None and sessao["start"] <= t < sessao["end"]


def score(sessoes: List[Dict[str, Any]], avisos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cada sessão contra os avisos, a matriz de confusão por sessão e os resumos."""
    linhas = []
    for s in sessoes:
        linha = {k: s[k] for k in ("id", "label", "name", "start", "end", "hours", "benign")}
        if s["benign"]:
            gerados = [a for a in avisos if _within(a["detected_at"], s)]
            interrupcoes = [a["type"] for a in avisos for t in a["interrupted_at"] if _within(t, s)]
            linha.update(generated=len(gerados), interruptions=len(interrupcoes),
                         interruption_types=sorted(set(interrupcoes)))
        else:
            evidencia = EVIDENCE.get(s["label"], {})
            achados = [a for a in avisos
                       if a["detected_at"] < s["end"] and a["last_seen_at"] >= s["start"] and _matches(a, evidencia)]
            primeiro = min((a["detected_at"] for a in achados), default=None)
            linha.update(
                detected=bool(achados),
                # Somado a um aviso aberto antes da sessão, não há como saber
                # quando o programa entrou nele
                seconds_to_detection=((primeiro - s["start"]).total_seconds()
                                      if primeiro is not None and primeiro >= s["start"] else None),
                interrupted=any(_within(t, s) for a in achados for t in a["interrupted_at"]),
            )
        linhas.append(linha)

    benignas = [l for l in linhas if l["benign"]]
    testes = [l for l in linhas if not l["benign"]]
    horas = sum(l["hours"] for l in benignas)
    interrupcoes = sum(l["interruptions"] for l in benignas)

    por_teste: Dict[str, Dict[str, Any]] = {}
    for l in testes:
        t = por_teste.setdefault(l["label"], {"name": l["name"], "sessions": 0, "detected": 0, "interrupted": 0,
                                              "_tempos": []})
        t["sessions"] += 1
        t["detected"] += int(l["detected"])
        t["interrupted"] += int(l["interrupted"])
        if l["seconds_to_detection"] is not None:
            t["_tempos"].append(l["seconds_to_detection"])
    for t in por_teste.values():
        tempos = t.pop("_tempos")
        t["median_seconds_to_detection"] = median(tempos) if tempos else None

    tp = sum(1 for l in testes if l["detected"])
    fn = len(testes) - tp
    fp = sum(1 for l in benignas if l["interruptions"])
    tn = len(benignas) - fp
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "sessions": linhas,
        "benign": {
            "sessions": len(benignas),
            "hours": horas,
            "interruptions": interrupcoes,
            "interruptions_per_hour": _ratio(interrupcoes, horas) if horas else None,
            "sessions_with_interruption": fp,
            "generated": sum(l["generated"] for l in benignas),
        },
        "tests": por_teste,
        "confusion": {
            "true_positives": tp, "false_negatives": fn, "false_positives": fp, "true_negatives": tn,
            # Sessão benigna com qualquer aviso, mesmo sem interromper
            "false_positives_generated": sum(1 for l in benignas if l["generated"]),
            "precision": precision, "recall": recall, "f1": f1,
            "interrupted_tests": sum(1 for l in testes if l["interrupted"]),
        },
    }


def live(db: Session, machine_id: int, start, end) -> Dict[str, Any]:
    """O que o sistema fez de verdade nas sessões rotuladas do período."""
    start, end = aware(start), aware(end)
    sessoes = sessions(db, machine_id, start, end)
    if not sessoes:
        return {**score([], []), "period": {"start": start, "end": end}}
    inicio = min(s["start"] for s in sessoes)
    fim = max(s["end"] for s in sessoes)
    return {**score(sessoes, _live_anomalies(db, machine_id, inicio, fim)), "period": {"start": start, "end": end}}


def replay(db: Session, machine_id: int, owner_id: int, start, end) -> Dict[str, Any]:
    """As leituras gravadas, reproduzidas com e sem contexto e camada por camada.

    A chave de contexto e a camada são da thread da reprodução: a coleta ao
    vivo não sente nada enquanto ela roda.
    """
    from app.services import anomaly_service, benchmark, context

    sessoes = sessions(db, machine_id, aware(start), aware(end))
    if not sessoes:
        return {"configs": {}, "sentence": "Nenhuma sessão marcada no período: não há o que reproduzir."}
    inicio = min(s["start"] for s in sessoes)
    fim = max(s["end"] for s in sessoes)

    configs = {}
    for nome, (contexto, camada) in REPLAY_CONFIGS.items():
        ctx_anterior = context.set_context_mode(contexto)
        camada_anterior = anomaly_service.set_detection_layer(camada)
        try:
            avisos = benchmark.replay_window(db, machine_id, owner_id, inicio, fim)
        finally:
            context.set_context_mode(ctx_anterior)
            anomaly_service.set_detection_layer(camada_anterior)
        normalizados = [{**a, "last_seen_at": a.get("last_seen_at") or a["detected_at"],
                         "interrupted_at": [a["detected_at"]] if a.get("notifies", True) else []}
                        for a in avisos]
        resultado = score(sessoes, normalizados)
        configs[nome] = {"label": REPLAY_LABELS[nome], "confusion": resultado["confusion"],
                         "benign": resultado["benign"], "tests": resultado["tests"]}
    return {"configs": configs, "sentence": _replay_sentence(configs)}


def _replay_sentence(configs: Dict[str, Any]) -> str:
    ligado, desligado = configs.get("contexto_ligado"), configs.get("contexto_desligado")
    if not ligado or not desligado:
        return "Não foi possível comparar com e sem contexto."
    i_on, i_off = ligado["benign"]["interruptions"], desligado["benign"]["interruptions"]
    tp_on, tp_off = ligado["confusion"]["true_positives"], desligado["confusion"]["true_positives"]
    frase = (f"Nas sessões de uso legítimo, o sistema sem contexto interromperia {i_off} vez(es); "
             f"com contexto, {i_on}. Nos testes, encontrou {tp_off} sem contexto e {tp_on} com.")
    ml = configs.get("ml")
    if ml:
        frase += f" Só o Isolation Forest encontrou {ml['confusion']['true_positives']}."
    return frase
