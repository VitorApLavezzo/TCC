"""Está lento agora, por quê? O agente mede 20 s em alta resolução, regras simples apontam o
gargalo e a IA redige a resposta; sem IA, ela sai do próprio resumo."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.diagnostic import Diagnostic
from app.models.machine import Machine
from app.services import commands, jobs, llm

SECONDS = 20


def request(db: Session, machine: Machine, user_id: Optional[int]) -> Diagnostic:
    diag = Diagnostic(machine_id=machine.id, requested_by=user_id, status="collecting", requested_at=utcnow())
    db.add(diag)
    db.commit()
    db.refresh(diag)
    cmd = commands.create(db, machine, "burst_diagnostic", {"diagnostic_id": diag.id, "seconds": SECONDS, "interval": 1},
                          user_id=user_id)
    diag.command_id = cmd.id
    db.commit()
    return diag


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(samples: List[Dict[str, Any]], processes: List[Dict[str, Any]], machine: Machine) -> Dict[str, Any]:
    cpu = [float(s.get("cpu") or 0) for s in samples]
    mem = [float(s.get("mem") or 0) for s in samples]
    swap = [float(s.get("swap") or 0) for s in samples]
    disk_io = [float(s.get("disk_read") or 0) + float(s.get("disk_write") or 0) for s in samples]
    net = [float(s.get("net_sent") or 0) + float(s.get("net_recv") or 0) for s in samples]
    iowait = [float(s.get("iowait") or 0) for s in samples if s.get("iowait") is not None]

    summary = {
        "seconds": len(samples),
        "cpu_avg": round(_avg(cpu), 1),
        "cpu_max": round(max(cpu), 1) if cpu else 0,
        "mem_avg": round(_avg(mem), 1),
        "swap_growth": round((swap[-1] - swap[0]) if len(swap) > 1 else 0, 2),
        "disk_io_mb_s": round(_avg(disk_io) / 1024 / 1024, 2),
        "net_mb_s": round(_avg(net) / 1024 / 1024, 2),
        "iowait_avg": round(_avg(iowait), 1) if iowait else None,
    }

    bottlenecks = []
    if summary["cpu_avg"] >= 80:
        bottlenecks.append("cpu")
    if summary["mem_avg"] >= 90 or summary["swap_growth"] > 1:
        bottlenecks.append("memory")
    if summary["disk_io_mb_s"] >= 40 or (summary["iowait_avg"] or 0) >= 20:
        bottlenecks.append("disk")
    if summary["net_mb_s"] >= 8:
        bottlenecks.append("network")
    summary["bottlenecks"] = bottlenecks

    def top(key: str, n: int = 3):
        ranked = sorted(processes, key=lambda p: float(p.get(key) or 0), reverse=True)
        return [
            {"name": p.get("name"), "value": round(float(p.get(key) or 0), 1)}
            for p in ranked[:n] if float(p.get(key) or 0) > 0
        ]

    summary["top_cpu"] = top("cpu_avg")
    summary["top_mem"] = top("mem_percent")
    summary["top_disk"] = [
        {"name": p["name"], "value": round(p["value"] / 1024 / 1024, 2)} for p in top("io_bytes_s")
    ]
    culprit = None
    if "cpu" in bottlenecks and summary["top_cpu"]:
        culprit = summary["top_cpu"][0]["name"]
    elif "memory" in bottlenecks and summary["top_mem"]:
        culprit = summary["top_mem"][0]["name"]
    elif "disk" in bottlenecks and summary["top_disk"]:
        culprit = summary["top_disk"][0]["name"]
    summary["culprit"] = culprit
    return summary


def _fallback_answer(summary: Dict[str, Any]) -> Dict[str, Any]:
    b = summary["bottlenecks"]
    culprit = summary.get("culprit")
    if not b:
        return {
            "headline": "O computador não está sobrecarregado neste momento",
            "culprit": None,
            "explanation": (
                f"Nos últimos {summary['seconds']} segundos o processador ficou em média em {summary['cpu_avg']:.0f}% "
                f"e a memória em {summary['mem_avg']:.0f}%. Se algo parece lento, a causa provável está fora do "
                "computador: internet, o site ou um programa específico travado."
            ),
            "actions": [
                "Teste a velocidade da internet (ex: fast.com) para ver se a lentidão é da conexão",
                "Se for um programa específico, feche e abra de novo só ele",
            ],
        }
    names = {"cpu": "processador", "memory": "memória", "disk": "disco", "network": "rede"}
    parts = ", ".join(names[x] for x in b)
    return {
        "headline": f"Gargalo em {parts}" + (f", puxado por {culprit}" if culprit else ""),
        "culprit": culprit,
        "explanation": (
            f"Nos últimos {summary['seconds']} segundos: processador em média {summary['cpu_avg']:.0f}%, "
            f"memória {summary['mem_avg']:.0f}%, disco {summary['disk_io_mb_s']:.1f} MB/s e rede "
            f"{summary['net_mb_s']:.1f} MB/s."
        ),
        "actions": ([f"Feche ou reinicie {culprit} e veja se melhora"] if culprit else [])
                   + ["Feche programas que não está usando agora"],
    }


def receive_samples(db: Session, diagnostic: Diagnostic, samples: List[Dict], processes: List[Dict]):
    diagnostic.samples = {"samples": samples[:120], "processes": processes[:40]}
    diagnostic.status = "analyzing"
    db.commit()
    owner_id = db.query(Machine.owner_id).filter(Machine.id == diagnostic.machine_id).scalar()
    jobs.submit(analyze, diagnostic.id, owner_id=owner_id)


def analyze(db: Session, diagnostic_id: int):
    diag = db.query(Diagnostic).filter(Diagnostic.id == diagnostic_id).first()
    if not diag:
        return
    machine = db.query(Machine).filter(Machine.id == diag.machine_id).first()
    raw = diag.samples or {}
    summary = summarize(raw.get("samples") or [], raw.get("processes") or [], machine)
    diag.summary = summary

    prompt = f"""A pessoa clicou em "Está lento agora, por quê?" no painel de monitoramento do computador {machine.name} ({machine.os_pretty or machine.os_type}).
O sistema mediu {summary['seconds']} segundos, uma leitura por segundo:

RESUMO MEDIDO: {summary}

Responda APENAS com JSON válido:
{{"headline":"uma frase curta com a resposta","culprit":"nome do programa culpado ou null","explanation":"2 a 3 frases em português simples comparando os números","actions":["passo 1","passo 2"]}}

REGRAS: use só os números do RESUMO; se "bottlenecks" estiver vazio, diga que o computador não está sobrecarregado e que a lentidão provavelmente vem da internet, do site ou de um programa específico; passos práticos para este sistema operacional."""

    def parse(text: str):
        data = llm.extract_json(text)
        if not isinstance(data, dict) or not data.get("headline"):
            raise ValueError("resposta sem headline")
        data["actions"] = [str(a) for a in (data.get("actions") or [])][:4]
        return data

    result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=parse)
    diag.answer = result.value if result.ok else _fallback_answer(summary)
    diag.model_used = result.provider if result.ok else "análise local"
    diag.status = "done"
    diag.completed_at = utcnow()
    db.commit()
