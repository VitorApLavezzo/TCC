"""
Benchmark de detecção: quanto o sistema acerta e quanto ele incomoda à toa.

A avaliação que já existia (`evaluation.py`) mede a qualidade do **texto** que
explica um problema. Esta mede a função central: encontrar o problema — e, tão
importante quanto, ficar calado quando não há nenhum.

Os cenários passam pelo MESMO `process_metric` da coleta real. Não é uma
simulação paralela do detector: é o detector, alimentado por leituras
fabricadas de forma controlada.

Três famílias de cenário:

- **ataque**  — deve gerar um aviso de tipo conhecido (verdade-fundamental)
- **normal**  — programa legítimo que *parece* problema; não deve gerar nada
- **real**    — leituras gravadas de uma máquina em uso; não devem gerar nada

Ataque sintético é inevitável num trabalho acadêmico: não se infecta uma
máquina de verdade. Já o lado que mais pesa na crítica — o falso positivo —
também é medido em dado real, onde o gabarito não foi escrito por quem está
sendo avaliado.
"""
import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ATTACK = "attack"
NORMAL = "normal"
REAL = "real"

# Famílias em que o gabarito é "não deve avisar nada"
QUIET_FAMILIES = (NORMAL, REAL)

# Severidade a partir da qual um aviso interrompe a pessoa. É a mesma
# severidade mínima padrão das preferências de notificação: abaixo dela o
# aviso fica registrado no painel e não vira mensagem.
NOTIFYING = ("medium", "high", "critical")


def _record(resultado: "ScenarioResult", anomalies) -> None:
    """Registra o que um passo produziu, separando o que interromperia."""
    for anomaly in anomalies:
        if anomaly.anomaly_type not in resultado.detected:
            resultado.detected.append(anomaly.anomaly_type)
        if anomaly.severity in NOTIFYING and anomaly.anomaly_type not in resultado.notified:
            resultado.notified.append(anomaly.anomaly_type)


@dataclass
class ScenarioResult:
    name: str
    label: str
    family: str
    # Tipo de aviso esperado (só em cenário de ataque)
    expected: Optional[str]
    # Tipos de aviso que o sistema de fato gerou
    detected: List[str] = field(default_factory=list)
    # Subconjunto de `detected` que chegaria à pessoa: severidade igual ou
    # acima da mínima padrão. Um aviso `low` fica no painel e não interrompe.
    notified: List[str] = field(default_factory=list)
    steps: int = 0
    # Horas de observação que a janela medida cobriu. Só existe em cenário
    # real: um cenário sintético não tem duração no mundo.
    hours: Optional[float] = None
    error: Optional[str] = None

    @property
    def alerts_per_hour(self) -> Optional[float]:
        """Avisos por hora — o número proporcional à observação.

        O veredito binário trata igual um sistema que avisa uma vez por dia e
        outro que avisa cem vezes. Para dado real, essa diferença é a coisa
        mais importante que existe.
        """
        if not self.hours:
            return None
        return len(self.detected) / self.hours

    @property
    def verdict(self) -> str:
        if self.error:
            return "erro"
        if self.family == ATTACK:
            return "acerto" if self.expected in self.detected else "escapou"
        return "falso positivo" if self.detected else "acerto"

    @property
    def ok(self) -> bool:
        return self.verdict == "acerto"


@dataclass
class BenchmarkResult:
    scenarios: List[ScenarioResult]
    metrics: Dict[str, Any]
    duration_ms: int = 0


def _ratio(numerador: int, denominador: int) -> Optional[float]:
    """None quando a razão não existe — e nunca 0.0 no lugar dela.

    Num conjunto sem nenhum ataque, revocação não é "zero por cento": é uma
    pergunta que não foi feita. Zero numa tabela de TCC lê-se como "não
    detectou nada", que é uma afirmação diferente e falsa.
    """
    if denominador == 0:
        return None
    return numerador / denominador


def confusion(results: List[ScenarioResult]) -> Dict[str, Any]:
    """Matriz de confusão e as métricas derivadas dela."""
    considerados = [r for r in results if not r.error]
    ataques = [r for r in considerados if r.family == ATTACK]
    quietos = [r for r in considerados if r.family in QUIET_FAMILIES]

    tp = sum(1 for r in ataques if r.expected in r.detected)
    fn = len(ataques) - tp
    fp = sum(1 for r in quietos if r.detected)
    tn = len(quietos) - fp
    fp_notificado = sum(1 for r in quietos if r.notified)

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_positives_notified": fp_notificado,
        "false_positive_rate_notified": _ratio(fp_notificado, len(quietos)),
        "scenarios": len(considerados),
        "errors": sum(1 for r in results if r.error),
    }


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


FAMILY_LABEL = {ATTACK: "ataque", NORMAL: "normal sintético", REAL: "normal real"}


def to_markdown(result: BenchmarkResult) -> str:
    m = result.metrics
    linhas = [
        "# Benchmark de detecção",
        "",
        f"{m['scenarios']} cenários executados pelo mesmo caminho de ingestão da coleta real "
        f"em {result.duration_ms / 1000:.1f}s.",
        "",
        "## Matriz de confusão",
        "",
        "| | Sistema avisou | Sistema ficou calado |",
        "|---|---|---|",
        f"| **Havia problema** | {m['true_positives']} (acerto) | {m['false_negatives']} (escapou) |",
        f"| **Não havia problema** | {m['false_positives']} (alarme falso) | {m['true_negatives']} (acerto) |",
        "",
        "## Métricas",
        "",
        "| Métrica | Valor | Leitura |",
        "|---|---|---|",
        f"| Precisão | {_pct(m['precision'])} | dos avisos emitidos, quantos eram problema de verdade |",
        f"| Revocação | {_pct(m['recall'])} | dos problemas existentes, quantos foram encontrados |",
        f"| F1 | {_pct(m['f1'])} | equilíbrio entre as duas |",
        f"| Taxa de alarme falso (qualquer aviso) | {_pct(m['false_positive_rate'])} | das situações normais, quantas geraram algum aviso |",
        f"| Taxa de alarme falso (que interrompe) | {_pct(m.get('false_positive_rate_notified'))} | das situações normais, quantas geraram aviso que chega à pessoa |",
        "",
        "## Cenário a cenário",
        "",
        "| Cenário | Família | Esperado | Detectado | Veredito |",
        "|---|---|---|---|---|",
    ]
    for r in result.scenarios:
        detectado = ", ".join(r.detected) if r.detected else "nada"
        if r.alerts_per_hour is not None:
            detectado += f" ({r.alerts_per_hour:.2f} avisos/h em {r.hours:.1f}h)"
        linhas.append(
            f"| {r.label} | {FAMILY_LABEL.get(r.family, r.family)} | {r.expected or 'nenhum aviso'} "
            f"| {detectado} | {r.verdict} |"
        )
    if m["errors"]:
        linhas += ["", f"> {m['errors']} cenário(s) falharam por erro de execução e ficaram fora das métricas."]
    return "\n".join(linhas) + "\n"


def to_csv(result: BenchmarkResult) -> str:
    saida = io.StringIO()
    w = csv.writer(saida)
    w.writerow(["cenario", "rotulo", "familia", "esperado", "detectado", "notificados",
                "horas", "avisos_por_hora", "veredito"])
    for r in result.scenarios:
        # Tipos separados por ponto e vírgula: a vírgula é o separador de coluna
        w.writerow([r.name, r.label, r.family, r.expected or "", "; ".join(r.detected),
                    "; ".join(r.notified), f"{r.hours:.2f}" if r.hours else "",
                    f"{r.alerts_per_hour:.3f}" if r.alerts_per_hour is not None else "", r.verdict])
    return saida.getvalue()


# ---------------------------------------------------------------------------
# Cenários
# ---------------------------------------------------------------------------

# Aquecimento: o portão do aprendizado exige 100 leituras E 6 horas de relógio.
# Sem passar por ele, metade dos detectores fica calada por construção e o
# benchmark mediria um sistema mudo, não o que o usuário recebe.
WARMUP_STEPS = 110
WARMUP_HOURS = 6.5
INTERVAL = 30  # segundos virtuais entre leituras da fase de cenário

# Os cenários herdam o ruído aleatório da demonstração (`random.uniform` no
# `_base_metric`). Sem semente fixa, a mesma rodada dá números diferentes —
# e um resultado de TCC que muda a cada execução não é resultado. A semente
# depende do nome do cenário, para que dois cenários não recebam a mesma
# sequência de ruído.
SEED = 20260919


def _antivirus_varrendo(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Varredura completa: privilégio, processador alto e rede — os três
    indícios circunstanciais que acusavam o antivírus antes da camada de
    confiança."""
    metric["cpu_percent"] = 72 + (k % 3)
    metric["disk_read_bytes"] = 9e7
    metric["net_bytes_recv"] = 4e6
    procs.append({"name": "avp.exe", "cpu_percent": 68.0, "mem_percent": 5.0,
                  "exe": "C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                  "signed": "signed", "publisher": "Kaspersky Lab JSC",
                  "username": "SYSTEM", "cmdline": "avp.exe -scan"})


def _jogo_pesado(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 88 + (k % 4)
    metric["mem_percent"] = 74.0
    metric["gpu_metrics"] = [{"name": "GPU", "load_percent": 97, "memory_percent": 88, "temperature": 74}]
    procs.append({"name": "jogo.exe", "cpu_percent": 82.0, "mem_percent": 22.0,
                  "exe": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Jogo\\jogo.exe",
                  "signed": "signed", "publisher": "Estudio de Jogos SA", "username": "vitor"})


def _backup_noturno(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["disk_read_bytes"] = 1.2e8
    metric["disk_write_bytes"] = 1.1e8
    metric["net_bytes_sent"] = 6e6
    procs.append({"name": "backup.exe", "cpu_percent": 35.0, "mem_percent": 4.0,
                  "exe": "C:\\Program Files\\Acronis\\backup.exe", "signed": "signed",
                  "publisher": "Acronis International", "username": "SYSTEM"})


def _compilacao(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 95.0
    metric["load_avg_1"] = 9.0
    procs.append({"name": "cl.exe", "cpu_percent": 90.0, "mem_percent": 12.0,
                  "exe": "C:\\Program Files\\Microsoft Visual Studio\\VC\\bin\\cl.exe",
                  "signed": "signed", "publisher": "Microsoft Corporation", "username": "vitor"})


def _atualizacao_do_sistema(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 60.0
    metric["net_bytes_recv"] = 8e6
    metric["disk_write_bytes"] = 7e7
    procs.append({"name": "TiWorker.exe", "cpu_percent": 55.0, "mem_percent": 6.0,
                  "exe": "C:\\Windows\\WinSxS\\TiWorker.exe", "signed": "signed",
                  "publisher": "Microsoft Windows", "username": "SYSTEM"})


def _minerador(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 97.0
    metric["net_bytes_sent"] = 3e6
    procs.append({"name": "xmrig.exe", "cpu_percent": 95.0, "mem_percent": 8.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Roaming\\xmrig.exe", "signed": "unsigned",
                  "username": "vitor", "cmdline": "xmrig.exe -o pool.exemplo:3333"})


def _binario_de_temp(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 80.0
    metric["net_bytes_recv"] = 5e6
    procs.append({"name": "update_helper.exe", "cpu_percent": 76.0, "mem_percent": 5.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Local\\Temp\\update_helper.exe",
                  "signed": "unsigned", "username": "vitor", "cmdline": "update_helper.exe"})


# Cenários próprios. Os de ataque que já existiam na demonstração entram logo
# abaixo, por nome, em vez de reescritos aqui.
_OWN_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "minerador": {"label": "Minerador de criptomoeda", "family": ATTACK,
                  "expect": "suspicious_process", "steps": 6, "overlay": _minerador},
    "binario_de_temp": {"label": "Executável sem assinatura rodando da pasta Temp", "family": ATTACK,
                        "expect": "malware_pattern", "steps": 6, "overlay": _binario_de_temp},
    "antivirus_varrendo": {"label": "Antivírus fazendo varredura completa", "family": NORMAL,
                           "expect": None, "steps": 8, "overlay": _antivirus_varrendo},
    "jogo_pesado": {"label": "Jogo exigente em tela cheia", "family": NORMAL,
                    "expect": None, "steps": 8, "overlay": _jogo_pesado},
    "backup_noturno": {"label": "Backup em nuvem durante a madrugada", "family": NORMAL,
                       "expect": None, "steps": 8, "overlay": _backup_noturno},
    "compilacao": {"label": "Compilação de projeto usando todos os núcleos", "family": NORMAL,
                   "expect": None, "steps": 8, "overlay": _compilacao},
    "atualizacao_do_sistema": {"label": "Windows Update instalando atualizações", "family": NORMAL,
                               "expect": None, "steps": 8, "overlay": _atualizacao_do_sistema},
}


def scenarios() -> Dict[str, Dict[str, Any]]:
    """Cenários próprios mais os da demonstração, que já são ataques com gabarito."""
    from app.services import demo
    todos = dict(_OWN_SCENARIOS)
    for nome, spec in demo.SCENARIOS.items():
        todos[nome] = {"label": spec["label"], "family": ATTACK, "expect": spec["expect"],
                       "steps": spec["attack"], "demo": nome}
    return todos


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def _snapshot_rows(metric_id: int, procs: List[Dict], now):
    from app.models.process import ProcessSnapshot
    for p in procs:
        yield ProcessSnapshot(
            metric_id=metric_id, timestamp=now, name=p["name"],
            cpu_percent=p.get("cpu_percent", 0), mem_percent=p.get("mem_percent", 0),
            mem_rss=p.get("mem_percent", 0) / 100 * 16 * 1024 ** 3, num_threads=8, status="running",
            username=p.get("username"), exe=p.get("exe"), signed=p.get("signed"),
            publisher=p.get("publisher"), cmdline=p.get("cmdline"),
        )


def _feed(db, machine, data: Dict[str, Any], procs: List[Dict], ts, extra: Dict[str, Any]):
    """Uma leitura pelo caminho real. Devolve as anomalias criadas."""
    from app.models.metric import Metric
    from app.services import agent_events
    from app.services.anomaly_service import process_metric

    metric = Metric(machine_id=machine.id, timestamp=ts, **data)
    db.add(metric)
    db.flush()
    for row in _snapshot_rows(metric.id, procs, ts):
        db.add(row)
    machine.last_seen = ts
    db.commit()
    db.refresh(metric)

    criadas = []
    a = process_metric(metric, machine, db, process_starts=extra.get("process_starts") or [], now=ts)
    if a:
        criadas.append(a)
    if extra.get("events"):
        criadas += agent_events.handle_events(db, machine, extra["events"], metric, ts)
    if extra.get("beacons"):
        criadas += agent_events.evaluate_beacons(db, machine, extra["beacons"], ts)
    return criadas


def run_scenario(db, name: str, owner_id: int) -> ScenarioResult:
    """Roda um cenário numa máquina efêmera e devolve o que o sistema detectou.

    A fase de aquecimento não entra na medição: ela existe para a máquina
    chegar ao cenário já conhecida, como estaria na vida real. Só os avisos da
    janela do cenário contam.
    """
    import secrets
    from datetime import timedelta
    from app.core.timeutil import utcnow
    from app.models.machine import Machine
    from app.services import demo

    spec = scenarios().get(name)
    if spec is None:
        raise ValueError(f"Cenário desconhecido: {name}")

    resultado = ScenarioResult(name=name, label=spec["label"], family=spec["family"],
                               expected=spec["expect"], steps=spec["steps"])
    machine = Machine(
        name=f"[BENCH] {spec['label']}", hostname=f"bench-{name}-{secrets.token_hex(2)}",
        os_type="Windows", os_version="11", os_pretty="Windows 11 Pro (benchmark)",
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        # Sem IA: cada anomalia criada enfileira uma explicação, e uma rodada
        # completa geraria dezenas de chamadas ao Ollama/Groq — tempo e custo
        # por um texto que ninguém vai ler, já que a máquina é apagada no fim.
        # O que o benchmark mede é a detecção, não a redação.
        ai_privacy="no_ai",
        system_info={"form_factor": "desktop", "is_admin": True, "tz_offset_minutes": -180},
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)

    # Estado do gerador guardado e devolvido: semear o módulo global é o que
    # funciona com o `random` que a demonstração usa, mas o processo inteiro
    # divide esse gerador e não pode sair alterado daqui.
    import random
    estado = random.getstate()
    random.seed(f"{SEED}:{name}")

    try:
        agora = utcnow()
        fim_do_aquecimento = agora - timedelta(seconds=spec["steps"] * INTERVAL)
        passo = timedelta(hours=WARMUP_HOURS) / WARMUP_STEPS

        # Aquecimento: máquina em uso comum, para sair do aprendizado e formar
        # os baselines de processo como uma máquina real formaria
        for k in range(WARMUP_STEPS):
            ts = fim_do_aquecimento - timedelta(hours=WARMUP_HOURS) + passo * k
            _feed(db, machine, demo._base_metric(k), demo._normal_processes(), ts, {})

        # Só o que acontece daqui para frente é medido
        for k in range(spec["steps"]):
            ts = fim_do_aquecimento + timedelta(seconds=(k + 1) * INTERVAL)
            data = demo._base_metric(WARMUP_STEPS + k)
            procs = demo._normal_processes()
            if "demo" in spec:
                extra = demo._scenario_step(spec["demo"], "attack", k, data, procs)
            else:
                spec["overlay"](k, data, procs)
                extra = {}
            _record(resultado, _feed(db, machine, data, procs, ts, extra))
    except Exception as e:  # noqa: BLE001 — um cenário quebrado não derruba a rodada
        resultado.error = f"{type(e).__name__}: {e}"
        db.rollback()
    finally:
        random.setstate(estado)
        _drop_machine(db, machine.id)

    return resultado


def _drop_machine(db, machine_id: int) -> None:
    from app.routers.machines import delete_machine_cascade
    try:
        delete_machine_cascade(machine_id, db)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"[Benchmark] Máquina efêmera {machine_id} não removida: {e}")


def run(db, owner_id: int, names: Optional[List[str]] = None) -> BenchmarkResult:
    import time
    inicio = time.monotonic()
    sweep_orphans(db, owner_id)
    alvos = names or list(scenarios().keys())
    resultados = [run_scenario(db, nome, owner_id) for nome in alvos]
    return BenchmarkResult(
        scenarios=resultados,
        metrics=confusion(resultados),
        duration_ms=int((time.monotonic() - inicio) * 1000),
    )


MIN_REAL_STEPS = 10
# Teto de leituras reproduzidas num cenário real. Sem ele, uma janela larga
# vira milhares de passagens pelo pipeline — a primeira rodada completa foi
# morta no meio, deixando a máquina efêmera para trás.
REAL_LIMIT = 600


def run_real_scenario(db, source_machine_id: int, owner_id: int, minutes: int = 240,
                      limit: int = REAL_LIMIT) -> ScenarioResult:
    """Reproduz leituras já gravadas de uma máquina de verdade.

    É o número mais forte do capítulo de resultados: aqui o gabarito não foi
    escrito por quem está sendo avaliado. A premissa é simples — a pessoa
    estava usando o computador normalmente, então todo aviso gerado nesta
    janela é um incômodo que ela não pediu.

    A janela é reproduzida numa máquina efêmera, não medida na original: a
    original já tem histórico, baselines e modelo treinado, e medir nela seria
    medir um estado que não dá para reconstruir depois.
    """
    import secrets
    from datetime import timedelta
    from app.core.timeutil import aware, utcnow
    from app.models.machine import Machine
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot

    origem = db.query(Machine).filter(Machine.id == source_machine_id).first()
    resultado = ScenarioResult(
        name=f"real_{source_machine_id}",
        label=f"Uso real de {origem.name if origem else source_machine_id} ({minutes} min)",
        family=REAL, expected=None,
    )
    if origem is None:
        resultado.error = "máquina de origem não encontrada"
        return resultado

    corte = utcnow() - timedelta(minutes=minutes)
    leituras = (
        db.query(Metric)
        .filter(Metric.machine_id == source_machine_id, Metric.timestamp >= corte)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
        .all()
    )
    leituras.reverse()  # mais antiga primeiro: o aquecimento vem antes da medição
    if len(leituras) < WARMUP_STEPS + MIN_REAL_STEPS:
        # Sem leituras para aquecer E medir, o cenário não pode virar um
        # verdadeiro negativo de graça: isso inflaria a taxa de acerto
        resultado.error = (f"leituras insuficientes: {len(leituras)}, "
                           f"precisa de {WARMUP_STEPS + MIN_REAL_STEPS}")
        return resultado

    campos = [c.name for c in Metric.__table__.columns
              if c.name not in ("id", "machine_id", "timestamp", "ml_score", "excluded_from_training")]
    snaps_por_metrica: Dict[int, List[Any]] = {}
    for p in db.query(ProcessSnapshot).filter(
            ProcessSnapshot.metric_id.in_([m.id for m in leituras])).all():
        snaps_por_metrica.setdefault(p.metric_id, []).append(p)

    machine = Machine(
        name=f"[BENCH] {resultado.label}", hostname=f"bench-real-{secrets.token_hex(2)}",
        os_type=origem.os_type, os_version=origem.os_version, os_pretty=origem.os_pretty,
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        ai_privacy="no_ai", system_info=origem.system_info,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)

    inicio_medido = fim_medido = None
    try:
        for i, leitura in enumerate(leituras):
            dados = {c: getattr(leitura, c) for c in campos}
            procs = [{"name": p.name, "cpu_percent": p.cpu_percent, "mem_percent": p.mem_percent,
                      "exe": p.exe, "signed": p.signed, "publisher": p.publisher,
                      "username": p.username, "cmdline": p.cmdline}
                     for p in snaps_por_metrica.get(leitura.id, [])]
            # `aware`: a coluna é DateTime(timezone=True) e volta ingênua no
            # SQLite, com fuso no PostgreSQL — sem normalizar, a comparação
            # dentro dos detectores estoura em um dos dois bancos
            criadas = _feed(db, machine, dados, procs, aware(leitura.timestamp), {})
            # As primeiras leituras são o aquecimento e não entram na medição
            if i >= WARMUP_STEPS:
                if resultado.steps == 0:
                    inicio_medido = aware(leitura.timestamp)
                fim_medido = aware(leitura.timestamp)
                resultado.steps += 1
                _record(resultado, criadas)
        if resultado.steps:
            resultado.hours = (fim_medido - inicio_medido).total_seconds() / 3600
    except Exception as e:  # noqa: BLE001
        resultado.error = f"{type(e).__name__}: {e}"
        db.rollback()
    finally:
        _drop_machine(db, machine.id)

    return resultado


BENCH_PREFIX = "[BENCH]"


def sweep_orphans(db, owner_id: int) -> int:
    """Remove máquinas efêmeras deixadas por uma rodada interrompida.

    O `finally` de `run_scenario` não roda quando o processo leva SIGKILL ou o
    contêiner reinicia no meio — e aí a máquina fica no painel com leituras
    fabricadas, indistinguível de uma real para quem olha a lista.
    """
    from app.models.machine import Machine
    # Ids, não objetos: depois do delete a instância fica inutilizável e
    # ler `m.id` levanta ObjectDeletedError
    ids = [
        row[0] for row in db.query(Machine.id)
        .filter(Machine.owner_id == owner_id, Machine.name.like(f"{BENCH_PREFIX}%"))
        .all()
    ]
    removidas = 0
    for machine_id in ids:
        try:
            _drop_machine(db, machine_id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"[Benchmark] Órfã {machine_id} resistiu à remoção: {e}")
            continue
        # Conta o que saiu de verdade, não o que foi tentado: a versão
        # anterior dizia ter limpado máquinas que continuavam no painel, e o
        # teste não pegava porque o SQLite não impõe chave estrangeira
        if db.query(Machine.id).filter(Machine.id == machine_id).first() is None:
            removidas += 1
    return removidas
