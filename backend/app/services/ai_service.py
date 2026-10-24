"""
Explicações de avisos em linguagem natural.

O que mudou em relação à primeira versão:

- Fatos citáveis: o prompt entrega à IA uma lista de fatos medidos com chave
  (`[[ram_agora]]`), e ela deve citar a chave ao lado de cada número. Cada
  número do texto é conferido contra os dados; se a IA inventou valores, a
  resposta é rejeitada e o próximo provedor é tentado.
- Nível de linguagem (leigo, intermediário, técnico), escolhido por pessoa, e
  versões extras sob demanda sem perder a original.
- Passos para a versão do sistema (Windows 10 e 11 têm menus diferentes).
- Contrafactual: "se você fechar X, a memória cai para cerca de Y%",
  calculado a partir dos processos da leitura, não imaginado pela IA.
- Memória: avisos parecidos anteriores e a causa que a pessoa registrou.
- Auditoria: texto enviado, resposta crua, tentativas e destino dos dados.
"""
import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS, COUNTERFACTUAL_TYPES, SEVERITY_LABELS
from app.core.metric_utils import cpu_temperature
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.incident import Incident
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.services import knowledge, llm
from app.services.preferences import LANGUAGE_LEVELS, get_preferences

# Mantidos para quem importava daqui
_call_ollama = llm._call_ollama
_call_cloud_llm = llm._call_cloud_llm
_call_claude_cli = llm._call_claude_cli
_extract_json = llm.extract_json

LEVEL_AUDIENCE = {
    "leigo": "pessoas SEM conhecimento técnico (donas de casa, estudantes, idosos)",
    "intermediario": (
        "pessoas que usam computador todo dia e conhecem termos como memória RAM, processo, "
        "Gerenciador de Tarefas e antivírus, mas não trabalham com TI"
    ),
    "tecnico": "profissionais de TI e de suporte técnico",
}

LEVEL_RULES = {
    "leigo": """- Português do Brasil, simples, direto, como se explicasse para um amigo leigo
- summary: UMA frase dizendo o que está acontecendo e o efeito prático. Ex: "O programa Chrome está usando quase toda a memória, o que pode deixar o computador lento"
- Todo termo técnico deve vir com explicação entre parênteses. Ex: "conexões de rede (quantidade de comunicações abertas com a internet)"
- recommendations: 3 a 4 passos práticos em ordem (do mais fácil ao mais avançado), cada um dizendo EXATAMENTE onde clicar ou o que digitar""",
    "intermediario": """- Português do Brasil, direto e objetivo, sem explicar termos comuns (RAM, processo, disco, rede, inicialização)
- summary: UMA frase com o problema e o programa envolvido
- recommendations: 3 a 4 passos em ordem, citando os caminhos de menu deste sistema e, quando ajudar, um comando simples""",
    "tecnico": """- Português do Brasil, linguagem técnica precisa (PID, RSS, load average, linha de comando, hash, handles)
- summary: UMA frase técnica com o diagnóstico mais provável
- recommendations: 3 a 5 passos com comandos exatos para este sistema (PowerShell no Windows; bash no Linux), começando por como coletar evidências antes de agir""",
}


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------

def os_guidance(machine: Machine) -> str:
    os_type = (machine.os_type or "").lower()
    pretty = machine.os_pretty or f"{machine.os_type or ''} {machine.os_version or ''}".strip() or "desconhecido"
    info = machine.system_info if isinstance(machine.system_info, dict) else {}
    if "windows" in os_type:
        if "11" in pretty.split("(")[0]:
            return (
                f"SISTEMA: {pretty}. No Windows 11: o Gerenciador de Tarefas abre com Ctrl+Shift+Esc e a lista fica "
                "em 'Processos' (menu lateral à esquerda); programas que iniciam com o Windows ficam em "
                "Configurações > Aplicativos > Inicialização; espaço em disco em Configurações > Sistema > "
                "Armazenamento; o antivírus é 'Segurança do Windows' no menu Iniciar."
            )
        return (
            f"SISTEMA: {pretty}. No Windows 10: o Gerenciador de Tarefas abre com Ctrl+Shift+Esc (clique em "
            "'Mais detalhes' se aparecer a versão resumida); programas que iniciam com o Windows ficam na aba "
            "'Inicializar' do Gerenciador; espaço em disco em Configurações > Sistema > Armazenamento; o antivírus "
            "é 'Segurança do Windows' no menu Iniciar."
        )
    if "linux" in os_type:
        desktop = (info.get("desktop") or "").lower()
        if "kde" in desktop or "plasma" in desktop:
            monitor = "o Monitor do Sistema do KDE (plasma-systemmonitor)"
        elif desktop:
            monitor = "o Monitor do Sistema (gnome-system-monitor)"
        else:
            monitor = "o comando 'top' ou 'htop' no terminal (servidor sem interface gráfica)"
        return (
            f"SISTEMA: {pretty}. No Linux: para ver programas use {monitor}; espaço em disco com 'df -h'; "
            "encerrar programa com 'kill PID'; registros do sistema com 'journalctl -xe'. NÃO cite Gerenciador "
            "de Tarefas nem menus do Windows."
        )
    if "darwin" in os_type or "mac" in os_type:
        return f"SISTEMA: {pretty}. No macOS: use o Monitor de Atividade (Aplicativos > Utilitários)."
    return f"SISTEMA: {pretty}."


def _baseline(db: Session, machine_id: int, before) -> Optional[Dict[str, float]]:
    """Comportamento normal: últimas 24h, sem os 15 minutos do próprio problema."""
    end = aware(before) - timedelta(minutes=15)
    rows = (
        db.query(Metric.cpu_percent, Metric.mem_percent, Metric.net_connections, Metric.disk_percent)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= end - timedelta(hours=24), Metric.timestamp < end)
        .all()
    )
    if len(rows) < 10:
        rows = (
            db.query(Metric.cpu_percent, Metric.mem_percent, Metric.net_connections, Metric.disk_percent)
            .filter(Metric.machine_id == machine_id)
            .order_by(Metric.timestamp.desc())
            .limit(10)
            .all()
        )
    if not rows:
        return None

    def avg(i):
        values = [r[i] or 0 for r in rows]
        return sum(values) / len(values)

    return {"cpu": avg(0), "mem": avg(1), "conns": avg(2), "disk": avg(3), "readings": len(rows)}


def _grouped_processes(db: Session, metric: Optional[Metric]) -> List[Dict[str, Any]]:
    if metric is None:
        return []
    snaps = db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id == metric.id).all()
    groups: Dict[str, Dict[str, Any]] = {}
    for p in snaps:
        if not p.name:
            continue
        g = groups.setdefault(p.name, {"name": p.name, "cpu": 0.0, "mem": 0.0, "rss": 0.0, "instances": 0,
                                       "exe": p.exe, "username": p.username, "cmdline": p.cmdline})
        g["cpu"] += p.cpu_percent or 0
        g["mem"] += p.mem_percent or 0
        g["rss"] += p.mem_rss or 0
        g["instances"] += 1
    return sorted(groups.values(), key=lambda g: (g["cpu"], g["mem"]), reverse=True)


def counterfactual(anomaly: Anomaly, metric: Optional[Metric], groups: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Quanto a máquina aliviaria se o programa responsável fosse fechado.

    Só aparece quando o aviso é sobre memória ou processador e quando existe
    um programa responsável de verdade. Antes, qualquer aviso sem responsável
    caía no maior consumidor de memória da máquina: um aviso de possível
    ataque pela rede sugeria fechar o navegador para liberar 2 GB, o que não
    tem relação nenhuma com tráfego e ensina a pessoa a ignorar o cartão.
    """
    if metric is None or not groups:
        return None
    if anomaly.anomaly_type not in COUNTERFACTUAL_TYPES:
        return None
    if not anomaly.responsible_process:
        return None
    target = next((g for g in groups if g["name"] == anomaly.responsible_process), None)
    if target is None:
        return None

    cores = metric.cpu_count_logical or 1
    # cpu_percent de processo soma núcleos (100% = um núcleo cheio);
    # o do sistema é a média entre núcleos
    cpu_share = target["cpu"] / cores
    mem_now = metric.mem_percent or 0
    cpu_now = metric.cpu_percent or 0
    mem_after = max(mem_now - target["mem"], 0)
    cpu_after = max(cpu_now - cpu_share, 0)
    if target["mem"] < 3 and cpu_share < 5:
        return None

    parts = []
    if target["mem"] >= 3:
        parts.append(f"a memória deve cair de {mem_now:.0f}% para cerca de {mem_after:.0f}%")
    if cpu_share >= 5:
        parts.append(f"o processador de {cpu_now:.0f}% para cerca de {cpu_after:.0f}%")
    instances = target["instances"]
    name = target["name"]
    who = f"{name} ({instances} janelas/processos)" if instances > 1 else name
    return {
        "process": name,
        "instances": instances,
        "mem_now": round(mem_now, 1),
        "mem_after": round(mem_after, 1),
        "mem_freed_gb": round(target["rss"] / 1024 ** 3, 2),
        "cpu_now": round(cpu_now, 1),
        "cpu_after": round(cpu_after, 1),
        "sentence": f"Se você fechar {who}, " + " e ".join(parts) + ".",
    }


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


_TRUST_PHRASES = {
    0: "sem assinatura reconhecida nem reputação",
    1: "comum (assinado ou visto em outros computadores)",
    2: "confiável (assinado e instalado no lugar certo)",
    3: "um programa de segurança reconhecido",
}


def usage_context(metric: Optional[Metric]) -> Optional[str]:
    """O contexto de uso da leitura em linguagem de leigo, ou None sem contexto.

    Sem números de propósito: a verificação confere cada número da resposta
    contra os fatos, e os minutos parado já vão como fato (`parado_min`).
    """
    if metric is None:
        return None
    partes = []
    idle = metric.user_idle_seconds
    if idle is not None:
        partes.append("alguém estava usando o computador naquele momento" if idle < 120
                      else "ninguém mexia no teclado nem no mouse havia alguns minutos")
    if metric.top_proc_user_driven == 1:
        partes.append("o programa mais pesado era o que estava na tela (ou foi aberto por ele)")
    elif metric.top_proc_user_driven == 0:
        partes.append("o programa mais pesado não era o que estava na tela: rodava em segundo plano")
    sobre = []
    if metric.top_proc_trust in _TRUST_PHRASES:
        sobre.append(_TRUST_PHRASES[metric.top_proc_trust])
    if metric.top_proc_known == 1:
        sobre.append("já conhecido neste computador")
    elif metric.top_proc_known == 0:
        sobre.append("nunca visto antes neste computador")
    if sobre:
        partes.append("esse programa é " + ", ".join(sobre))
    return "; ".join(partes) + "." if partes else None


def build_context(db: Session, anomaly: Anomaly, metric: Optional[Metric], machine: Machine) -> Dict[str, Any]:
    if metric is None:
        metric = (
            db.query(Metric).filter(Metric.machine_id == machine.id).order_by(Metric.timestamp.desc()).first()
        )
    facts: Dict[str, Dict[str, Any]] = {}

    def fact(key: str, label: str, value, unit: str = ""):
        n = _num(value)
        if n is None:
            return
        facts[key] = {"label": label, "value": round(n, 1), "unit": unit}

    if metric is not None:
        fact("cpu_agora", "Processador agora", metric.cpu_percent, "%")
        fact("ram_agora", "Memória agora", metric.mem_percent, "%")
        fact("disco_agora", "Disco ocupado agora", metric.disk_percent, "%")
        fact("swap_agora", "Memória virtual agora", metric.swap_percent, "%")
        fact("conexoes_agora", "Conexões de rede agora", metric.net_connections)
        fact("temp_agora", "Temperatura do processador agora", cpu_temperature(metric), "°C")
        if metric.disk_free:
            fact("disco_livre_gb", "Espaço livre no disco", metric.disk_free / 1024 ** 3, "GB")
        if metric.user_idle_seconds is not None:
            fact("parado_min", "Minutos sem teclado e mouse", metric.user_idle_seconds / 60, "min")

    baseline = _baseline(db, machine.id, anomaly.detected_at or utcnow())
    if baseline:
        fact("cpu_normal", "Processador normal deste computador", baseline["cpu"], "%")
        fact("ram_normal", "Memória normal deste computador", baseline["mem"], "%")
        fact("conexoes_normal", "Conexões de rede normais", baseline["conns"])

    groups = _grouped_processes(db, metric)
    for i, g in enumerate(groups[:5], 1):
        fact(f"prog{i}_cpu", f"{g['name']}: processador", g["cpu"], "%")
        fact(f"prog{i}_ram", f"{g['name']}: memória", g["mem"], "%")

    affected = dict(anomaly.affected_metrics or {})
    details = affected.pop("_behavior", None) or {}
    for k, v in affected.items():
        if _num(v) is not None:
            fact(f"det_{k}", k.replace("_", " "), v)

    cf = counterfactual(anomaly, metric, groups)
    if cf:
        fact("se_fechar_ram", f"Memória se fechar {cf['process']}", cf["mem_after"], "%")
        fact("se_fechar_cpu", f"Processador se fechar {cf['process']}", cf["cpu_after"], "%")
        fact("liberaria_gb", f"Memória liberada ao fechar {cf['process']}", cf["mem_freed_gb"], "GB")

    for c in (details.get("contributions") or details.get("ml_contributions") or [])[:4]:
        fact(f"peso_{c['group']}", f"Peso de '{c['label']}' no desvio", c["percent"], "%")

    similar = knowledge.similar_anomalies(db, anomaly)
    if similar["count"]:
        fact("vezes_antes", "Vezes que isso já aconteceu neste computador", similar["count"])
    causes = knowledge.past_causes(db, machine.id, anomaly.anomaly_type, anomaly.responsible_process)

    chain = None
    if anomaly.incident_id:
        incident = db.query(Incident).filter(Incident.id == anomaly.incident_id).first()
        if incident and incident.chain and len(incident.chain.get("nodes", [])) > 1:
            chain = incident.chain

    return {
        "metric": metric,
        "facts": facts,
        "details": details,
        "affected": affected,
        "groups": groups,
        "counterfactual": cf,
        "similar": similar,
        "past_causes": causes,
        "chain": chain,
        "baseline": baseline,
        "usage": usage_context(metric),
    }


# ---------------------------------------------------------------------------
# Verificação dos números
# ---------------------------------------------------------------------------

CITATION_RE = re.compile(r"\[\[([a-z0-9_]+)\]\]")
CLAIM_RE = re.compile(
    r"(?<![\w.,])(\d{1,4}(?:[.,]\d+)?)\s*(%|°\s?c\b|graus|min(?:utos)?\b|conex(?:ões|oes|ão|ao)\b|vezes\b|gb\b|mb\b)",
    re.IGNORECASE,
)


def strip_citations(text):
    if not isinstance(text, str):
        return text
    return re.sub(r"\s?\[\[[a-z0-9_]+\]\]", "", text)


def sanitize_explanation(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Tira os marcadores [[chave]] de citação de tudo que vai para o frontend
    (summary, detailed_explanation, causas, recomendações, justificativa de
    severidade — inclusive dentro de `variants`), sem tocar o que fica gravado
    no banco. Ponto único: todo lugar que devolve uma explicação passa por
    aqui antes de responder."""
    if not data:
        return data
    out = dict(data)
    for key in ("summary", "detailed_explanation", "severity_justification"):
        if key in out:
            out[key] = strip_citations(out[key])
    for key in ("possible_causes", "recommendations"):
        if isinstance(out.get(key), list):
            out[key] = [strip_citations(v) for v in out[key]]
    if isinstance(out.get("variants"), dict):
        out["variants"] = {level: sanitize_explanation(v) for level, v in out["variants"].items()}
    return out


def _matches(value: float, target: float) -> bool:
    return abs(value - target) <= max(1.0, abs(target) * 0.06)


def verify_numbers(fields: Dict[str, Any], facts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Confere cada número com unidade no texto contra os fatos medidos.

    Um número vale se bate com o fato citado logo depois dele ou, sem citação,
    com qualquer fato. "N vezes" também vale se for a razão entre dois fatos
    ("3 vezes o normal").
    """
    values = [f["value"] for f in facts.values()]
    ratios = [a / b for a in values for b in values if b not in (0, 0.0) and a != b]
    texts: List[str] = []
    for key in ("summary", "detailed_explanation", "severity_justification"):
        if isinstance(fields.get(key), str):
            texts.append(fields[key])
    for key in ("possible_causes", "recommendations"):
        texts.extend(t for t in fields.get(key) or [] if isinstance(t, str))

    claims = 0
    verified = 0
    unverified: List[str] = []
    citations = 0
    invalid: List[str] = []
    for text in texts:
        for key in CITATION_RE.findall(text):
            citations += 1
            if key not in facts:
                invalid.append(key)
        for m in CLAIM_RE.finditer(text):
            raw, unit = m.group(1), m.group(2).lower()
            value = float(raw.replace(",", "."))
            claims += 1
            tail = text[m.end():m.end() + 20]
            cited = CITATION_RE.search(tail)
            ok = False
            if cited and cited.group(1) in facts and tail.find("[[") <= 3:
                ok = _matches(value, facts[cited.group(1)]["value"])
            else:
                ok = any(_matches(value, v) for v in values)
                if not ok and unit.startswith("vezes"):
                    ok = any(abs(value - r) <= max(0.5, r * 0.15) for r in ratios)
            if ok:
                verified += 1
            else:
                unverified.append(text[max(0, m.start() - 30):m.end() + 5].strip())

    passed = (len(unverified) <= 1 and (claims == 0 or len(unverified) / claims <= 0.25)) and len(invalid) <= 1
    return {
        "claims": claims,
        "verified": verified,
        "unverified": unverified[:10],
        "citations": citations,
        "invalid_citations": invalid[:10],
        "passed": passed,
    }


class UnverifiedAnswer(ValueError):
    def __init__(self, fields, verification):
        super().__init__(f"{len(verification['unverified'])} número(s) sem respaldo nos dados")
        self.fields = fields
        self.verification = verification


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("resposta sem summary")

    def as_list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    return {
        "summary": data["summary"].strip(),
        "detailed_explanation": str(data.get("detailed_explanation") or "").strip() or None,
        "possible_causes": as_list(data.get("possible_causes"))[:5],
        "recommendations": as_list(data.get("recommendations"))[:6],
        "severity_justification": str(data.get("severity_justification") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(anomaly: Anomaly, machine: Machine, ctx: Dict[str, Any], level: str) -> str:
    type_label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    severity = SEVERITY_LABELS.get(anomaly.severity, anomaly.severity)
    fact_lines = "\n".join(
        f"- [[{k}]] {f['label']}: {f['value']:g}{(' ' + f['unit']) if f['unit'] not in ('%', '') else f['unit']}"
        for k, f in ctx["facts"].items()
    ) or "- (nenhum número disponível)"
    details = json.dumps(ctx["details"] or ctx["affected"] or {}, ensure_ascii=False, default=str)[:1500]

    extra = []
    if ctx["chain"]:
        extra.append(f"CADEIA OBSERVADA NESTE COMPUTADOR: {ctx['chain']['narrative']}")
    if ctx["similar"]["sentence"]:
        extra.append(f"HISTÓRICO: {ctx['similar']['sentence']}")
    for c in ctx["past_causes"]:
        vezes = "1 vez" if c["count"] == 1 else f"{c['count']} vezes"
        extra.append(f"CAUSA REGISTRADA PELA PESSOA EM AVISOS PARECIDOS ({vezes}): \"{c['cause']}\"")
    if ctx["counterfactual"]:
        extra.append(f"CÁLCULO DO SISTEMA: {ctx['counterfactual']['sentence']}")
    if ctx.get("usage"):
        extra.append(f"CONTEXTO DE USO: {ctx['usage']}")

    return f"""Você explica problemas de computador para {LEVEL_AUDIENCE[level]}. Um sistema de monitoramento detectou algo anormal neste computador:

PROBLEMA DETECTADO: {type_label} | Gravidade: {severity}
COMPUTADOR: {machine.name}
PROGRAMA ENVOLVIDO: {anomaly.responsible_process or "não identificado"}
{os_guidance(machine)}

FATOS MEDIDOS (cada um com sua chave):
{fact_lines}

DETALHES TÉCNICOS: {details}
{chr(10).join(extra)}

Responda APENAS com JSON válido neste formato:
{{"summary":"...","detailed_explanation":"...","possible_causes":["...","...","..."],"recommendations":["...","...","..."],"severity_justification":"..."}}

REGRAS DE ESCRITA (siga TODAS):
{LEVEL_RULES[level]}
- detailed_explanation: 2 parágrafos curtos. Primeiro: o que foi detectado e o que a pessoa pode sentir na prática (lentidão, travamento, risco). Segundo: por que isso é ANORMAL para ESTE computador, comparando com o comportamento normal dele
- possible_causes: exatamente 3, da MAIS provável para a MENOS provável, começando com "Mais provável:", "Possível:" e "Menos provável:". Causas concretas do dia a dia, não genéricas
- Se houver CAUSA REGISTRADA PELA PESSOA, ela é a "Mais provável" e o texto deve dizer "Da última vez, ..."
- Se houver HISTÓRICO, mencione-o no segundo parágrafo
- Os passos devem ser deste SISTEMA específico descrito acima
- NUNCA invente números. Use só os FATOS MEDIDOS e escreva a chave entre colchetes duplos logo depois de cada número, ex: "a memória está em 91% [[ram_agora]]". Sem fato para algo, descreva sem número
- severity_justification: 1 frase dizendo o nível de urgência em linguagem cotidiana. Ex: "Gravidade alta: vale resolver ainda hoje, pois o computador pode travar" """


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------

def _owner_level(db: Session, machine: Machine) -> str:
    from app.models.user import User
    owner = db.query(User).filter(User.id == machine.owner_id).first()
    level = get_preferences(owner).get("language_level") if owner else "leigo"
    return level if level in LANGUAGE_LEVELS else "leigo"


def generate_explanation(anomaly: Anomaly, metric: Optional[Metric], machine: Machine, db: Session,
                         level: Optional[str] = None) -> Dict[str, Any]:
    level = level if level in LANGUAGE_LEVELS else _owner_level(db, machine)
    ctx = build_context(db, anomaly, metric, machine)
    prompt = build_prompt(anomaly, machine, ctx, level)
    rejected: List[Tuple[Dict[str, Any], Dict[str, Any], str]] = []

    def parse(raw: str):
        fields = _normalize(llm.extract_json(raw))
        verification = verify_numbers(fields, ctx["facts"])
        if not verification["passed"]:
            rejected.append((fields, verification, raw))
            raise UnverifiedAnswer(fields, verification)
        return fields, verification

    result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=parse)

    if result.ok:
        fields, verification = result.value
        data = {**fields, "model_used": result.provider, "verification": verification, "raw_response": result.text}
    elif rejected:
        # Nenhum provedor passou na checagem: fica a resposta com menos números
        # sem respaldo, marcada — o painel mostra quais números não conferem.
        fields, verification, raw = min(rejected, key=lambda r: len(r[1]["unverified"]))
        failed = [a for a in result.attempts if not a.ok]
        data = {**fields, "model_used": failed[-1].provider if failed else None, "verification": verification,
                "raw_response": raw}
    else:
        data = _generate_fallback_explanation(anomaly, ctx["metric"], machine, ctx)

    data.update({
        "language_level": level,
        "evidence": ctx["facts"],
        "counterfactual": ctx["counterfactual"],
        "prompt_text": result.prompt_sent if result.attempts else None,
        "provider_attempts": result.attempts_json(),
        "data_destination": result.destination if result.ok else ("none" if not result.attempts else
                                                                   _destination_of(result, data.get("model_used"))),
        "duration_ms": result.duration_ms,
    })
    return data


def _destination_of(result: "llm.LLMResult", provider: Optional[str]) -> str:
    for a in result.attempts:
        if a.provider == provider:
            return a.destination
    return "none"


def apply_explanation(expl: AIExplanation, data: Dict[str, Any]):
    for key in (
        "summary", "detailed_explanation", "possible_causes", "recommendations", "severity_justification",
        "model_used", "language_level", "evidence", "verification", "counterfactual", "prompt_text",
        "raw_response", "provider_attempts", "data_destination", "duration_ms",
    ):
        if key in data:
            setattr(expl, key, data[key])
    expl.summary = expl.summary or ""
    expl.generated_at = utcnow()


def generate_variant(db: Session, anomaly: Anomaly, level: str) -> Dict[str, Any]:
    """Versão da explicação em outro nível de linguagem, guardada sem trocar a principal."""
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first() if anomaly.metric_id else None
    data = generate_explanation(anomaly, metric, machine, db, level=level)
    variant = {k: data.get(k) for k in (
        "summary", "detailed_explanation", "possible_causes", "recommendations", "severity_justification",
        "model_used", "verification", "data_destination",
    )}
    variant["generated_at"] = utcnow().isoformat()
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly.id).first()
    if expl:
        variants = dict(expl.variants or {})
        variants[level] = variant
        expl.variants = variants
        db.commit()
    return variant


# ---------------------------------------------------------------------------
# Análise local (sem IA)
# ---------------------------------------------------------------------------

CAUSES_MAP = {
    "background_load": [
        "Programa pesado rodando em segundo plano, sem ser a janela que você está usando",
        "Minerador de criptomoedas ou outro programa indesejado usando o processador escondido",
        "Tarefa agendada, atualização ou backup rodando sozinha",
        "Programa que você fechou mas continuou trabalhando por trás",
    ],
    "high_cpu": [
        "Processo intensivo em execução (compilação, renderização, encoding de vídeo)",
        "Malware ou minerador de criptomoedas consumindo CPU em background",
        "Atualização do sistema operacional ou antivírus rodando em segundo plano",
        "Aplicação com bug ou travada em loop de processamento",
    ],
    "high_memory": [
        "Muitas aplicações abertas simultaneamente esgotando a RAM disponível",
        "Vazamento de memória em alguma aplicação que não libera o que alocou",
        "Cache do sistema crescendo sem ser liberado",
        "Aplicação carregando arquivos muito grandes na memória",
    ],
    "memory_leak": [
        "Aplicação com bug no gerenciamento de memória — aloca mas nunca libera",
        "Plugin, extensão ou biblioteca de terceiros com vazamento",
        "Serviço em background que acumula dados na RAM ao longo do tempo",
        "Framework ou runtime com vazamento em versão desatualizada",
    ],
    "cpu_loop": [
        "Aplicação travada em um laço infinito sem condição de saída",
        "Thread bloqueada esperando por um recurso que nunca será liberado (deadlock)",
        "Bug de lógica que impede a conclusão de uma operação",
        "Processo consumindo 100% de um núcleo de CPU continuamente",
    ],
    "ddos_indicator": [
        "Ataque de negação de serviço (DDoS) direcionado a esta máquina ou rede",
        "Flood de conexões TCP/UDP por bot ou script malicioso",
        "Amplification attack usando esta máquina como vetor ou alvo",
        "Varredura de portas agressiva por scanner externo",
    ],
    "unknown_process": [
        "Software instalado recentemente que ainda não estava no histórico desta máquina",
        "Script ou executável rodando pela primeira vez após uma atualização",
        "Processo iniciado por outro software sem conhecimento do usuário",
        "Possível software não autorizado instalado no sistema",
    ],
    "suspicious_process": [
        "Ferramenta de mineração de criptomoedas (cryptominer) detectada pelo nome",
        "Ferramenta de ataque ou exploit conhecida em execução",
        "Malware que usa nomes de processos conhecidos da lista de ameaças",
        "Software instalado por terceiros sem consentimento explícito",
    ],
    "malware_pattern": [
        "Malware ou ransomware em execução — combinação de comportamentos suspeitos detectada",
        "Processo executando a partir de pasta temporária (técnica comum de evasão)",
        "Processo sem linha de comando visível consumindo CPU e rede simultaneamente",
        "Processo privilegiado com comportamento anômalo indicando possível comprometimento",
    ],
    "resource_abuse": [
        "Aplicação com comportamento diferente do normal — possível bug ou atualização problemática",
        "Plugin ou extensão instalada recentemente alterando o desempenho da aplicação",
        "Arquivo corrupto sendo processado repetidamente pela aplicação",
        "Configuração alterada que aumentou a carga de trabalho da aplicação",
    ],
    "behavioral_change": [
        "Novo software instalado alterando o padrão de uso de recursos do sistema",
        "Atualização do sistema operacional ou de drivers modificando o comportamento",
        "Mudança no padrão de uso do usuário (novas tarefas, mais abas abertas, etc.)",
        "Evento externo como sincronização de nuvem, backup automático ou indexação",
    ],
    "disk_full": [
        "Logs de sistema ou de aplicações acumulados sem rotação ou limpeza",
        "Arquivos temporários e de cache ocupando espaço crescente",
        "Downloads, backups locais ou snapshots consumindo o espaço disponível",
        "Banco de dados ou arquivo de log crescendo sem limite configurado",
    ],
    "disk_forecast": [
        "Downloads, vídeos ou fotos acumulando no ritmo das últimas semanas",
        "Arquivos temporários, cache ou lixeira crescendo sem limpeza",
        "Backup local ou sincronização de nuvem guardando cópias no disco",
    ],
    "network_spike": [
        "Download ou upload de arquivo grande em andamento",
        "Sincronização de serviço de nuvem (OneDrive, Google Drive, Dropbox)",
        "Atualização de sistema ou aplicação baixando pacotes grandes",
        "Possível exfiltração de dados ou tráfego malicioso",
    ],
    "resource_exhaustion": [
        "Múltiplas aplicações pesadas abertas simultaneamente esgotando CPU e RAM",
        "Processo sem controle consumindo todos os recursos disponíveis",
        "Sistema subdimensionado para a carga de trabalho atual",
    ],
    "thermal_throttling": [
        "Poeira acumulada no ventilador e nas saídas de ar, dificultando a refrigeração",
        "Computador apoiado em superfície macia (cama, sofá) tapando a entrada de ar",
        "Pasta térmica do processador ressecada depois de anos de uso",
    ],
    "cooling_degradation": [
        "Poeira acumulando no ventilador ao longo das últimas semanas",
        "Ventilador perdendo rotação por desgaste",
        "Ambiente mais quente ou computador em local com pouca ventilação",
    ],
    "unexpected_shutdown": [
        "Queda ou oscilação de energia elétrica",
        "Superaquecimento, que faz o computador se desligar para se proteger",
        "Falha de driver ou de hardware causando tela azul ou travamento",
    ],
    "disk_health": [
        "Desgaste natural do disco depois de muitas horas de uso",
        "Setores defeituosos surgindo — sinal de que o disco pode falhar",
        "Superaquecimento ou impacto físico no disco",
    ],
    "hardware_errors": [
        "Memória RAM com defeito ou mal encaixada",
        "Processador ou placa-mãe registrando falhas corrigidas",
        "Driver de hardware desatualizado gerando erros",
    ],
    "process_masquerading": [
        "Vírus usando o nome de um arquivo do Windows para passar despercebido",
        "Programa malicioso instalado numa pasta de usuário imitando o sistema",
        "Programa legítimo mal instalado com nome parecido (raro)",
    ],
    "suspicious_parent": [
        "Documento com macro maliciosa abrindo ferramentas do sistema",
        "Anexo de e-mail executando código ao ser aberto",
        "Automação legítima de escritório chamando scripts (raro)",
    ],
    "suspicious_command": [
        "Script malicioso tentando baixar ou esconder código",
        "Ataque em andamento usando ferramentas do próprio Windows",
        "Script administrativo legítimo com parâmetros incomuns",
    ],
    "ransomware_canary": [
        "Programa de sequestro de dados (ransomware) criptografando arquivos",
        "Programa apagando ou renomeando arquivos em massa",
        "Alguém abriu e modificou os arquivos-isca manualmente (raro)",
    ],
    "beaconing": [
        "Programa malicioso se comunicando com o servidor de quem o controla",
        "Programa legítimo verificando atualizações em intervalos fixos",
        "Extensão de navegador ou aplicativo em segundo plano enviando dados",
    ],
    "outbreak_suspected": [
        "Vírus se espalhando pela rede entre os computadores",
        "Programa instalado em massa por atualização ou pela TI",
        "Mesmo anexo ou download aberto em vários computadores",
    ],
}

RECS_MAP = {
    "background_load": [
        "Confira se você abriu esse programa ou se ele faz parte de algo que você instalou",
        "Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc), clique com o botão direito no processo e escolha 'Abrir local do arquivo'",
        "Se não reconhecer o programa, encerre-o e execute um antivírus atualizado",
        "Se for uma tarefa legítima (renderização, backup), marque o aviso como normal",
    ],
    "high_cpu": [
        "Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc) e identifique o processo com maior CPU",
        "Encerre o processo suspeito se não for essencial",
        "Execute um antivírus atualizado para descartar malware",
        "Reinicie o computador se o problema persistir após encerrar o processo",
    ],
    "high_memory": [
        "Feche abas e aplicações desnecessárias para liberar RAM",
        "Reinicie o navegador ou aplicação com maior consumo de memória",
        "Verifique se há processo com crescimento contínuo de memória",
        "Considere adicionar mais RAM se o problema for recorrente com uso normal",
    ],
    "memory_leak": [
        "Reinicie imediatamente a aplicação identificada com crescimento contínuo de memória",
        "Verifique se há atualização disponível para a aplicação — bugs de leak costumam ser corrigidos",
        "Reporte o comportamento ao desenvolvedor ou suporte da aplicação",
    ],
    "cpu_loop": [
        "Force o encerramento do processo travado no Gerenciador de Tarefas",
        "Reinicie a aplicação e evite a operação que causou o travamento",
        "Atualize a aplicação — loops infinitos frequentemente são bugs conhecidos",
    ],
    "ddos_indicator": [
        "Verifique as conexões ativas com: netstat -an | findstr ESTABLISHED",
        "Contate seu provedor de internet para ativar proteção anti-DDoS",
        "Configure o firewall para bloquear IPs com excesso de conexões",
    ],
    "unknown_process": [
        "Pesquise o nome do processo na internet para verificar se é legítimo",
        "Verifique o caminho completo do executável no Gerenciador de Tarefas",
        "Execute um escaneamento completo com antivírus atualizado",
        "Se não reconhecer o processo, encerre-o e monitore se reaparece",
    ],
    "suspicious_process": [
        "Encerre o processo imediatamente e quarentene o arquivo executável",
        "Execute uma varredura completa com antivírus e anti-malware (Malwarebytes)",
        "Verifique programas instalados recentemente e remova os desconhecidos",
    ],
    "malware_pattern": [
        "Desconecte a máquina da rede imediatamente para conter possível propagação",
        "Execute varredura com antivírus em modo seguro (Safe Mode)",
        "Verifique e altere senhas de contas acessadas nesta máquina",
    ],
    "resource_abuse": [
        "Reinicie a aplicação identificada para restaurar o comportamento normal",
        "Verifique se houve atualização recente da aplicação que possa ter introduzido um bug",
        "Desative plugins ou extensões recentemente instalados na aplicação",
    ],
    "behavioral_change": [
        "Verifique o que mudou no sistema recentemente (instalações, atualizações, novos arquivos)",
        "Revise processos em execução em busca de algo novo ou desconhecido",
        "Monitore as métricas nas próximas horas para avaliar se é comportamento temporário",
    ],
    "disk_full": [
        "Abra Configurações > Sistema > Armazenamento e use a limpeza recomendada",
        "Remova arquivos temporários: %TEMP% no Windows",
        "Mova arquivos grandes para HD externo ou armazenamento em nuvem",
    ],
    "disk_forecast": [
        "Veja quais pastas mais cresceram em Configurações > Sistema > Armazenamento",
        "Esvazie a Lixeira e a pasta Downloads",
        "Mova fotos e vídeos antigos para um HD externo ou para a nuvem",
    ],
    "network_spike": [
        "Verifique qual processo está gerando tráfego no Monitor de Recursos (aba Rede)",
        "Pause sincronizações de nuvem temporariamente para confirmar a causa",
        "Execute um antivírus se nenhuma causa legítima for identificada",
    ],
    "resource_exhaustion": [
        "Feche todas as aplicações não essenciais",
        "Reinicie o computador para liberar todos os recursos",
        "Avalie upgrade de hardware (mais RAM, SSD) se o problema for frequente",
    ],
    "thermal_throttling": [
        "Coloque o computador numa superfície dura e com as saídas de ar livres",
        "Limpe a poeira das saídas de ar com um pincel ou ar comprimido, com o computador desligado",
        "Se continuar, leve a uma assistência para trocar a pasta térmica",
    ],
    "cooling_degradation": [
        "Limpe as saídas de ar e o ventilador com o computador desligado",
        "Verifique se o ventilador gira sem ruído estranho",
        "Use uma base com ventilação se for notebook",
    ],
    "unexpected_shutdown": [
        "Confira se o cabo de energia e a tomada estão firmes; considere um nobreak",
        "Verifique se o computador estava muito quente antes de desligar",
        "Veja o Visualizador de Eventos (Logs do Windows > Sistema) procurando 'Kernel-Power'",
    ],
    "disk_health": [
        "Faça AGORA uma cópia de segurança dos arquivos importantes",
        "Verifique a saúde do disco com CrystalDiskInfo (Windows) ou 'smartctl -a' (Linux)",
        "Planeje a troca do disco antes que ele falhe",
    ],
    "hardware_errors": [
        "Execute o Diagnóstico de Memória do Windows (mdsched no menu Iniciar)",
        "Atualize a BIOS e os drivers do fabricante",
        "Se os erros continuarem, leve a uma assistência técnica",
    ],
    "process_masquerading": [
        "Não encerre ainda: anote o caminho do arquivo mostrado no aviso",
        "Execute a verificação completa da Segurança do Windows (ou Malwarebytes)",
        "Se confirmado, isole o computador da rede e troque as senhas usadas nele",
    ],
    "suspicious_parent": [
        "Feche o documento que abriu o programa e não habilite macros",
        "Execute uma verificação completa de antivírus",
        "Apague o anexo ou arquivo de origem e avise a pessoa que o enviou",
    ],
    "suspicious_command": [
        "Encerre o programa que está executando o comando",
        "Execute uma verificação completa de antivírus",
        "Se não reconhecer o comando, isole o computador da rede e procure suporte",
    ],
    "ransomware_canary": [
        "Desligue a internet do computador IMEDIATAMENTE (ou use 'Isolar da rede' no painel)",
        "Não pague resgate e não reinicie antes de procurar ajuda",
        "Desconecte HDs externos e pendrives para protegê-los",
        "Procure suporte técnico e restaure os arquivos a partir de um backup",
    ],
    "beaconing": [
        "Verifique se reconhece o programa indicado no aviso",
        "Execute uma verificação completa de antivírus",
        "Se não reconhecer, encerre o programa e isole o computador da rede",
    ],
    "outbreak_suspected": [
        "Isole da rede os computadores afetados",
        "Verifique com a TI se houve instalação em massa recente",
        "Execute antivírus em todos os computadores listados",
    ],
}

# Troca de ferramentas do Windows pelas equivalentes no Linux
_LINUX_TERMS = [
    ("Gerenciador de Tarefas (Ctrl+Shift+Esc)", "Monitor do Sistema (ou o comando 'top' no terminal)"),
    ("Gerenciador de Tarefas", "Monitor do Sistema"),
    ("Monitor de Recursos (aba Rede)", "comando 'nethogs' ou 'ss -tp' no terminal"),
    ("netstat -an | findstr ESTABLISHED", "ss -tan state established"),
    ("Configurações > Sistema > Armazenamento", "o Analisador de Uso de Disco (ou 'du -sh ~/*' no terminal)"),
    ("%TEMP% no Windows", "/tmp e ~/.cache"),
    ("Segurança do Windows", "ClamAV (clamscan)"),
    ("Diagnóstico de Memória do Windows (mdsched no menu Iniciar)", "memtest86+ na inicialização"),
    ("Visualizador de Eventos (Logs do Windows > Sistema) procurando 'Kernel-Power'", "'journalctl -b -1 -e' (registros do boot anterior)"),
    ("CrystalDiskInfo (Windows) ou 'smartctl -a' (Linux)", "'sudo smartctl -a /dev/sda'"),
]


def _adapt_for_os(texts: List[str], machine: Machine) -> List[str]:
    if "linux" not in (machine.os_type or "").lower():
        return texts
    out = []
    for t in texts:
        for win, lin in _LINUX_TERMS:
            t = t.replace(win, lin)
        out.append(t)
    return out


def _generate_fallback_explanation(anomaly: Anomaly, metric: Optional[Metric], machine: Optional[Machine] = None,
                                   ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    type_label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    ctx = ctx or {}

    generic_causes = [
        "Comportamento fora do padrão histórico desta máquina detectado pelo modelo de ML",
        "Combinação incomum de métricas (CPU, memória, rede) em relação ao baseline",
        "Processo ou tarefa executando de forma diferente do habitual",
    ]
    generic_recs = [
        "Verifique os processos em execução no Gerenciador de Tarefas ou com 'top'",
        "Compare as métricas atuais com o histórico no dashboard",
        "Monitore a máquina nas próximas horas para ver se o comportamento persiste",
    ]
    causes = list(CAUSES_MAP.get(anomaly.anomaly_type, generic_causes))
    recs = list(RECS_MAP.get(anomaly.anomaly_type, generic_recs))

    past = ctx.get("past_causes") or []
    if past:
        causes.insert(0, f"Da última vez, você registrou: {past[0]['cause']}")
    if machine is not None:
        causes = _adapt_for_os(causes, machine)
        recs = _adapt_for_os(recs, machine)
    cf = ctx.get("counterfactual")
    if cf:
        recs.insert(0, cf["sentence"])

    process_text = f" O programa {anomaly.responsible_process} parece ser o responsável." if anomaly.responsible_process else ""
    sev_label = SEVERITY_LABELS.get(anomaly.severity, anomaly.severity)

    reading = ""
    if metric is not None:
        reading = (
            f" No momento da detecção: CPU {(metric.cpu_percent or 0):.0f}%, "
            f"Memória {(metric.mem_percent or 0):.0f}%, Disco {(metric.disk_percent or 0):.0f}%."
        )
    history = ctx.get("similar", {}).get("sentence") if ctx.get("similar") else None
    chain = ctx.get("chain")

    detailed = (
        "O sistema identificou um comportamento fora do padrão normal desta máquina. "
        "A análise combina o modelo Isolation Forest — treinado com o histórico desta máquina específica — "
        f"e detectores de padrões comportamentais.{reading}"
    )
    if chain:
        detailed += f"\n\nOs sinais observados se encadeiam assim: {chain['narrative']}."
    if history:
        detailed += f"\n\n{history}"

    return {
        # O rótulo já é uma frase ("Programa desconhecido detectado"): somar
        # "detectado com severidade" repetia a palavra e trazia jargão.
        "summary": f"{type_label}, com gravidade {sev_label.lower()}.{process_text}",
        "detailed_explanation": detailed,
        "possible_causes": causes[:5],
        "recommendations": recs[:5],
        "severity_justification": f"Gravidade {sev_label.lower()}: definida pelos valores medidos e pelo quanto eles se afastam do normal deste computador.",
        "model_used": "análise local",
        "verification": None,
    }
