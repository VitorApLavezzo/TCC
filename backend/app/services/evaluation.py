"""IA-juíza que pontua explicações em quatro eixos (1 a 5). Sempre que possível é outro
provedor: um modelo julgando o próprio texto puxa a nota para cima."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import ai_service, llm

AXES = ["clareza", "precisao", "acionabilidade", "sem_alarmismo"]


def _judge_prompt(anomaly: Anomaly, expl_like: Dict[str, Any], verification: Optional[Dict]) -> str:
    label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    check = ""
    if verification:
        check = (f"\nCHECAGEM AUTOMÁTICA DE NÚMEROS: {verification.get('verified')} de {verification.get('claims')} "
                 f"números conferem com os dados; sem respaldo: {verification.get('unverified')}.")
    return f"""Você avalia a QUALIDADE de uma explicação automática de problema de computador escrita para pessoas leigas.

PROBLEMA: {label}
EXPLICAÇÃO AVALIADA:
- Resumo: {expl_like.get('summary')}
- Detalhe: {expl_like.get('detailed_explanation')}
- Causas: {expl_like.get('possible_causes')}
- Passos: {expl_like.get('recommendations')}{check}

Dê nota de 1 (péssimo) a 5 (excelente) em cada eixo e uma justificativa curta. Responda só com JSON:
{{"clareza":n,"precisao":n,"acionabilidade":n,"sem_alarmismo":n,"comentario":"1 frase"}}
Critérios: clareza = uma pessoa sem conhecimento técnico entende; precisao = coerência com os dados e a checagem; acionabilidade = os passos são concretos e executáveis; sem_alarmismo = assusta o proporcional, nem mais nem menos."""


def _parse_scores(raw: str) -> Dict[str, Any]:
    data = llm.extract_json(raw)
    scores = {}
    for axis in AXES:
        v = data.get(axis)
        if not isinstance(v, (int, float)) or not (1 <= v <= 5):
            raise ValueError(f"nota inválida em {axis}")
        scores[axis] = round(float(v), 1)
    scores["media"] = round(sum(scores[a] for a in AXES) / len(AXES), 2)
    scores["comentario"] = str(data.get("comentario") or "")[:300]
    return scores


def judge(db: Session, anomaly_id: int) -> Optional[Dict[str, Any]]:
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    if not anomaly or not expl or not expl.possible_causes:
        return None
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    expl_like = {
        "summary": ai_service.strip_citations(expl.summary, expl.evidence),
        "detailed_explanation": ai_service.strip_citations(expl.detailed_explanation, expl.evidence),
        "possible_causes": [ai_service.strip_citations(c, expl.evidence) for c in expl.possible_causes or []],
        "recommendations": [ai_service.strip_citations(r, expl.evidence) for r in expl.recommendations or []],
    }
    prompt = _judge_prompt(anomaly, expl_like, expl.verification)
    # Juíza diferente de quem escreveu, quando possível
    result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=_parse_scores,
                          exclude=[expl.model_used] if expl.model_used else ())
    if not result.ok:
        result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=_parse_scores)
    if result.ok:
        expl.judge_scores = result.value
        expl.judge_model = result.provider
        db.commit()
        return result.value
    return None


def compare_providers(db: Session, anomaly_id: int) -> Dict[str, Any]:
    """Gera a explicação com cada provedor disponível e junta as notas da juíza."""
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first() if anomaly.metric_id else None
    providers = llm.provider_chain(llm.privacy_of(machine))

    results: List[Dict[str, Any]] = []
    for provider in providers:
        others = [p.name for p in providers if p.name != provider.name]
        data = ai_service.generate_explanation(anomaly, metric, machine, db)  # usa a cadeia normal p/ contexto
        # Regenera forçando este provedor: exclui todos os outros
        forced = ai_service.build_context(db, anomaly, metric, machine)
        prompt = ai_service.build_prompt(anomaly, machine, forced, data.get("language_level", "leigo"))

        def parse(raw: str):
            fields = ai_service._normalize(llm.extract_json(raw))
            verification = ai_service.verify_numbers(fields, forced["facts"])
            return fields, verification

        r = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=parse, exclude=others)
        if not r.ok:
            results.append({"provider": provider.name, "ok": False})
            continue
        fields, verification = r.value
        scores = None
        jr = llm.complete(_judge_prompt(anomaly, fields, verification), privacy=llm.privacy_of(machine),
                          parse=_parse_scores, exclude=[provider.name])
        if jr.ok:
            scores = {**jr.value, "judge": jr.provider}
        results.append({
            "provider": provider.name,
            "destination": provider.destination,
            "ok": True,
            "duration_ms": r.duration_ms,
            "verification": verification,
            "scores": scores,
            "explanation": fields,
        })
    return {"anomaly_id": anomaly_id, "results": results}
