"""Benchmark de detecção: quanto o sistema acerta e quanto ele incomoda à toa.

Os cenários passam pelo mesmo `process_metric` da coleta real, alimentado por
leituras fabricadas. Famílias: ataque (deve gerar o aviso esperado), normal
(programa legítimo que parece problema) e real (leituras gravadas de uso normal).
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

# Mesma severidade mínima padrão das preferências de notificação: abaixo dela o
# aviso fica no painel e não vira mensagem.
NOTIFYING = ("medium", "high", "critical")


def _record(result: "ScenarioResult", anomalies) -> None:
    """Registra o que um passo produziu, separando o que interromperia."""
    for anomaly in anomalies:
        if anomaly.anomaly_type not in result.detected:
            result.detected.append(anomaly.anomaly_type)
        if anomaly.severity in NOTIFYING and anomaly.anomaly_type not in result.notified:
            result.notified.append(anomaly.anomaly_type)


@dataclass
class ScenarioResult:
    name: str
    label: str
    family: str
    # Só em cenário de ataque
    expected: Optional[str]
    detected: List[str] = field(default_factory=list)
    # Subconjunto de `detected` que chegaria à pessoa (severidade em NOTIFYING)
    notified: List[str] = field(default_factory=list)
    steps: int = 0
    # Só em cenário real: um cenário sintético não tem duração no mundo
    hours: Optional[float] = None
    error: Optional[str] = None

    @property
    def alerts_per_hour(self) -> Optional[float]:
        """Avisos por hora: o veredito binário trata igual quem avisa uma ou cem vezes por dia."""
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


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """None quando a razão não existe, nunca 0.0: sem ataques, revocação não é "zero por cento"."""
    if denominator == 0:
        return None
    return numerator / denominator


def confusion(results: List[ScenarioResult]) -> Dict[str, Any]:
    """Matriz de confusão e as métricas derivadas dela."""
    counted = [r for r in results if not r.error]
    attacks = [r for r in counted if r.family == ATTACK]
    quiet = [r for r in counted if r.family in QUIET_FAMILIES]

    tp = sum(1 for r in attacks if r.expected in r.detected)
    fn = len(attacks) - tp
    fp = sum(1 for r in quiet if r.detected)
    tn = len(quiet) - fp
    fp_notified = sum(1 for r in quiet if r.notified)
    # Ataque com qualquer aviso, mesmo com outro nome: separa "não percebeu nada"
    # de "percebeu e chamou de outra coisa"
    seen = sum(1 for r in attacks if r.detected)

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
        "seen": seen,
        "false_negatives": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_positives_notified": fp_notified,
        "false_positive_rate_notified": _ratio(fp_notified, len(quiet)),
        "scenarios": len(counted),
        "errors": sum(1 for r in results if r.error),
    }


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


FAMILY_LABEL = {ATTACK: "ataque", NORMAL: "normal sintético", REAL: "normal real"}


def to_markdown(result: BenchmarkResult) -> str:
    m = result.metrics
    lines = [
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
        f"| Ataques percebidos (qualquer aviso) | {m.get('seen', 0)} de {m['true_positives'] + m['false_negatives']} "
        f"| ataques com algum aviso, mesmo com outro nome |",
        f"| Taxa de alarme falso (qualquer aviso) | {_pct(m['false_positive_rate'])} | das situações normais, quantas geraram algum aviso |",
        f"| Taxa de alarme falso (que interrompe) | {_pct(m.get('false_positive_rate_notified'))} | das situações normais, quantas geraram aviso que chega à pessoa |",
        "",
        "## Cenário a cenário",
        "",
        "| Cenário | Família | Esperado | Detectado | Veredito |",
        "|---|---|---|---|---|",
    ]
    for r in result.scenarios:
        detected = ", ".join(r.detected) if r.detected else "nada"
        if r.alerts_per_hour is not None:
            detected += f" ({r.alerts_per_hour:.2f} avisos/h em {r.hours:.1f}h)"
        lines.append(
            f"| {r.label} | {FAMILY_LABEL.get(r.family, r.family)} | {r.expected or 'nenhum aviso'} "
            f"| {detected} | {r.verdict} |"
        )
    if m["errors"]:
        lines += ["", f"> {m['errors']} cenário(s) falharam por erro de execução e ficaram fora das métricas."]
    return "\n".join(lines) + "\n"


def to_csv(result: BenchmarkResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["cenario", "rotulo", "familia", "esperado", "detectado", "notificados",
                "horas", "avisos_por_hora", "veredito"])
    for r in result.scenarios:
        # Tipos separados por ponto e vírgula: a vírgula é o separador de coluna
        w.writerow([r.name, r.label, r.family, r.expected or "", "; ".join(r.detected),
                    "; ".join(r.notified), f"{r.hours:.2f}" if r.hours else "",
                    f"{r.alerts_per_hour:.3f}" if r.alerts_per_hour is not None else "", r.verdict])
    return buf.getvalue()


# O portão do aprendizado exige 100 leituras E 6 horas de relógio: sem passar
# por ele, metade dos detectores fica calada por construção.
WARMUP_STEPS = 110
WARMUP_HOURS = 6.5
INTERVAL = 30  # segundos virtuais entre leituras da fase de cenário

# Os cenários herdam o ruído aleatório da demonstração: sem semente fixa a mesma
# rodada dá números diferentes. A semente também depende do nome do cenário.
SEED = 20260919


def _antivirus_scan(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Varredura completa: privilégio, processador alto e rede, os três indícios circunstanciais."""
    metric["cpu_percent"] = 72 + (k % 3)
    metric["disk_read_bytes"] = 9e7
    metric["net_bytes_recv"] = 4e6
    procs.append({"name": "avp.exe", "cpu_percent": 68.0, "mem_percent": 5.0,
                  "exe": "C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                  "signed": "signed", "publisher": "Kaspersky Lab JSC",
                  "username": "SYSTEM", "cmdline": "avp.exe -scan"})


PID_GAME, PID_STEAM, PID_COMPILER, PID_MINER = 5200, 5100, 7300, 6600


def _in_foreground(metric: Dict, pid: int, name: str) -> None:
    """A pessoa está usando o computador, com este programa na janela da frente."""
    metric["foreground_pid"] = pid
    metric["foreground_name"] = name
    metric["user_idle_seconds"] = 2.0


def _heavy_game(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 88 + (k % 4)
    metric["mem_percent"] = 74.0
    metric["gpu_metrics"] = [{"name": "GPU", "load_percent": 97, "memory_percent": 88, "temperature": 74}]
    procs.append({"name": "jogo.exe", "cpu_percent": 82.0, "mem_percent": 22.0,
                  "exe": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Jogo\\jogo.exe",
                  "signed": "signed", "publisher": "Estudio de Jogos SA", "username": "vitor",
                  "pid": PID_GAME, "ancestors": [PID_STEAM, 1500, 700]})
    _in_foreground(metric, PID_GAME, "jogo.exe")


def _unsigned_game(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O caso relatado: jogo fora da Steam, sem assinatura, já jogado antes."""
    metric["cpu_percent"] = 88 + (k % 4)
    metric["mem_percent"] = 70.0
    metric["gpu_metrics"] = [{"name": "GPU", "load_percent": 95, "memory_percent": 80, "temperature": 72}]
    procs.append({"name": "jogo.exe", "cpu_percent": 80.0, "mem_percent": 20.0,
                  "exe": "D:\\Games\\Jogo\\jogo.exe", "signed": "unsigned", "username": "vitor",
                  "cmdline": "jogo.exe", "pid": PID_GAME, "ancestors": [1500, 700]})
    _in_foreground(metric, PID_GAME, "jogo.exe")


def _editor_build(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O compilador não é a janela: é filho do editor que está na frente."""
    metric["cpu_percent"] = 95.0
    metric["load_avg_1"] = 9.0
    procs.append({"name": "cl.exe", "cpu_percent": 90.0, "mem_percent": 12.0,
                  "exe": "C:\\Program Files\\Microsoft Visual Studio\\VC\\bin\\cl.exe",
                  "signed": "signed", "publisher": "Microsoft Corporation", "username": "vitor",
                  "pid": PID_COMPILER, "ancestors": [7200, 3100, 1500, 700]})
    _in_foreground(metric, 3100, "Code.exe")


def _nightly_backup(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["disk_read_bytes"] = 1.2e8
    metric["disk_write_bytes"] = 1.1e8
    metric["net_bytes_sent"] = 6e6
    procs.append({"name": "backup.exe", "cpu_percent": 35.0, "mem_percent": 4.0,
                  "exe": "C:\\Program Files\\Acronis\\backup.exe", "signed": "signed",
                  "publisher": "Acronis International", "username": "SYSTEM"})


def _build(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 95.0
    metric["load_avg_1"] = 9.0
    procs.append({"name": "cl.exe", "cpu_percent": 90.0, "mem_percent": 12.0,
                  "exe": "C:\\Program Files\\Microsoft Visual Studio\\VC\\bin\\cl.exe",
                  "signed": "signed", "publisher": "Microsoft Corporation", "username": "vitor"})


def _system_update(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 60.0
    metric["net_bytes_recv"] = 8e6
    metric["disk_write_bytes"] = 7e7
    procs.append({"name": "TiWorker.exe", "cpu_percent": 55.0, "mem_percent": 6.0,
                  "exe": "C:\\Windows\\WinSxS\\TiWorker.exe", "signed": "signed",
                  "publisher": "Microsoft Windows", "username": "SYSTEM"})


def _miner(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 97.0
    metric["net_bytes_sent"] = 3e6
    # Iniciado no login (filho do explorer); a pessoa está no navegador
    procs.append({"name": "xmrig.exe", "cpu_percent": 95.0, "mem_percent": 8.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Roaming\\xmrig.exe", "signed": "unsigned",
                  "username": "vitor", "cmdline": "xmrig.exe -o pool.exemplo:3333",
                  "pid": PID_MINER, "ancestors": [1500, 700]})


def _miner_while_browsing(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O teste atômico: minerador renomeado, sem nome de minerador, com a pessoa usando o Chrome."""
    metric["cpu_percent"] = 96.0
    procs.append({"name": "svc_update.exe", "cpu_percent": 92.0, "mem_percent": 4.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Local\\svc_update\\svc_update.exe",
                  "signed": "unsigned", "username": "vitor", "cmdline": "svc_update.exe --bench=1M",
                  "pid": PID_MINER, "ancestors": [1500, 700]})


def _miner_in_rundll32(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O minerador dentro de um binário assinado da Microsoft: a técnica clássica."""
    metric["cpu_percent"] = 96.0
    procs.append({"name": "rundll32.exe", "cpu_percent": 92.0, "mem_percent": 3.0,
                  "exe": "C:\\Windows\\System32\\rundll32.exe", "signed": "signed",
                  "publisher": "Microsoft Windows", "username": "vitor",
                  "cmdline": "rundll32.exe C:\\Users\\vitor\\AppData\\Local\\Temp\\m.dll,Start",
                  "pid": PID_MINER, "ancestors": [1500, 700]})


def _temp_binary(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 80.0
    metric["net_bytes_recv"] = 5e6
    procs.append({"name": "update_helper.exe", "cpu_percent": 76.0, "mem_percent": 5.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Local\\Temp\\update_helper.exe",
                  "signed": "unsigned", "username": "vitor", "cmdline": "update_helper.exe"})


def _isolated_spike(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Uma única leitura fora do padrão no meio de leituras normais.

    Os demais passos ficam intocados de propósito: forçar a CPU neles fazia o
    modelo estranhar a leitura inteira, não o pico.
    """
    if k == 3:
        metric["cpu_percent"] = 96.0
        metric["net_bytes_sent"] = 4e6


def _program_installs(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Vários executáveis novos e legítimos em coletas seguidas, como numa instalação."""
    metric["cpu_percent"] = 45 + (k % 5)
    procs.append({
        "name": f"setup_app{k}.exe", "cpu_percent": 22.0, "mem_percent": 11.0,
        "exe": f"C:\\Program Files\\App{k}\\setup_app{k}.exe",
        "signed": "signed", "publisher": "Contoso Ltd", "username": "vitor",
        "cmdline": f"setup_app{k}.exe /quiet",
    })


# Os ataques da demonstração entram em `scenarios()`, por nome
_OWN_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "minerador": {"label": "Minerador de criptomoeda", "family": ATTACK,
                  "expect": "suspicious_process", "steps": 6, "overlay": _miner},
    "binario_de_temp": {"label": "Executável sem assinatura rodando da pasta Temp", "family": ATTACK,
                        "expect": "malware_pattern", "steps": 6, "overlay": _temp_binary},
    "antivirus_varrendo": {"label": "Antivírus fazendo varredura completa", "family": NORMAL,
                           "expect": None, "steps": 8, "overlay": _antivirus_scan},
    "jogo_pesado": {"label": "Jogo exigente em tela cheia", "family": NORMAL,
                    "expect": None, "steps": 8, "overlay": _heavy_game},
    # Os quatro casos difíceis do contexto de uso: o mesmo processador cheio,
    # com e sem a pessoa conduzindo
    "jogo_sem_assinatura": {"label": "Jogo sem assinatura, já jogado antes, na tela", "family": NORMAL,
                            "expect": None, "steps": 8, "overlay": _unsigned_game,
                            "known_processes": ["jogo.exe"]},
    "compilacao_do_editor": {"label": "Compilação aberta pelo editor que está na tela", "family": NORMAL,
                             "expect": None, "steps": 8, "overlay": _editor_build,
                             "known_processes": ["cl.exe"]},
    "minerador_com_pessoa_navegando": {"label": "Minerador renomeado com a pessoa navegando", "family": ATTACK,
                                       "expect": "unknown_process", "steps": 6,
                                       "overlay": _miner_while_browsing},
    "minerador_no_rundll32": {"label": "Minerador dentro do rundll32 assinado", "family": ATTACK,
                              "expect": "background_load", "steps": 6, "overlay": _miner_in_rundll32},
    "backup_noturno": {"label": "Backup em nuvem durante a madrugada", "family": NORMAL,
                       "expect": None, "steps": 8, "overlay": _nightly_backup},
    "compilacao": {"label": "Compilação de projeto usando todos os núcleos", "family": NORMAL,
                   "expect": None, "steps": 8, "overlay": _build},
    "atualizacao_do_sistema": {"label": "Windows Update instalando atualizações", "family": NORMAL,
                               "expect": None, "steps": 8, "overlay": _system_update},
    "pico_isolado": {"label": "Pico isolado numa leitura só", "family": NORMAL,
                     "expect": None, "steps": 8, "overlay": _isolated_spike},
    "instalacao_de_programas": {"label": "Instalação de vários programas legítimos", "family": NORMAL,
                                "expect": None, "steps": 8, "overlay": _program_installs},
}


def scenarios() -> Dict[str, Dict[str, Any]]:
    """Cenários próprios mais os da demonstração, que já são ataques com gabarito."""
    from app.services import demo
    all_scenarios = dict(_OWN_SCENARIOS)
    for name, spec in demo.SCENARIOS.items():
        all_scenarios[name] = {"label": spec["label"], "family": ATTACK, "expect": spec["expect"],
                               "steps": spec["attack"], "demo": name, "interval": spec.get("interval", INTERVAL)}
    return all_scenarios


def _seed_known(db, machine, names: List[str]) -> None:
    """Programas que a máquina já conhece antes do cenário — "já jogado antes"."""
    from app.models.process_baseline import ProcessBaseline
    for name in names:
        db.add(ProcessBaseline(machine_id=machine.id, process_name=name, seen_count=40, is_known=True,
                               avg_cpu=60.0, max_cpu=90.0, avg_mem_percent=15.0, max_mem_percent=25.0))
    db.commit()


def _snapshot_rows(metric_id: int, procs: List[Dict], now):
    from app.models.process import ProcessSnapshot
    for p in procs:
        yield ProcessSnapshot(
            metric_id=metric_id, timestamp=now, name=p["name"], pid=p.get("pid"), ancestors=p.get("ancestors"),
            cpu_percent=p.get("cpu_percent", 0), mem_percent=p.get("mem_percent", 0),
            mem_rss=p.get("mem_percent", 0) / 100 * 16 * 1024 ** 3, num_threads=8, status="running",
            username=p.get("username"), exe=p.get("exe"), signed=p.get("signed"),
            publisher=p.get("publisher"), cmdline=p.get("cmdline"), sha256=p.get("sha256"),
            ppid=p.get("ppid"), parent_name=p.get("parent_name"),
        )


def _feed(db, machine, data: Dict[str, Any], procs: List[Dict], ts, extra: Dict[str, Any]):
    """Uma leitura pelo caminho real. Devolve as anomalias criadas."""
    from app.models.metric import Metric
    from app.services import agent_events
    from app.services.anomaly_service import detection_layer, process_metric

    metric = Metric(machine_id=machine.id, timestamp=ts, **data)
    db.add(metric)
    db.flush()
    for row in _snapshot_rows(metric.id, procs, ts):
        db.add(row)
    machine.last_seen = ts
    db.commit()
    db.refresh(metric)

    created = []
    a = process_metric(metric, machine, db, process_starts=extra.get("process_starts") or [], now=ts)
    if a:
        created.append(a)
    # Eventos do agente são evidência por regra: na ablação "só Isolation Forest"
    # inflariam a linha do modelo
    if detection_layer() != "ml":
        if extra.get("events"):
            created += agent_events.handle_events(db, machine, extra["events"], metric, ts)
        if extra.get("beacons"):
            created += agent_events.evaluate_beacons(db, machine, extra["beacons"], ts)
    if extra.get("reconferir") and detection_layer() == "ambas":
        # Em produção o agendador reconfere a previsão de disco a cada 15 minutos.
        # Só no sistema completo: a previsão não é regra nem Isolation Forest.
        from app.services import forecasting
        forecast = forecasting.check_machine(db, machine)
        if forecast is not None:
            created.append(forecast)
    return created


# Fuso das máquinas efêmeras (Brasília)
BENCH_TZ_OFFSET = -180

# Dia da semana (0 = segunda) e hora local em que o relógio virtual termina
CLOCK_WEEKDAY, CLOCK_HOUR = 2, 15


def _virtual_clock(now) -> "datetime":
    """A quarta-feira mais recente às 15h no fuso da máquina, em UTC.

    O modelo usa hora e dia da semana como atributos: ancorar num horário fixo faz
    o número se repetir. No máximo 7 dias atrás, dentro da janela da previsão de disco.
    """
    from datetime import timedelta
    local = now + timedelta(minutes=BENCH_TZ_OFFSET)
    target = (local - timedelta(days=(local.weekday() - CLOCK_WEEKDAY) % 7)).replace(
        hour=CLOCK_HOUR, minute=0, second=0, microsecond=0)
    if target > local:
        target -= timedelta(days=7)
    return target - timedelta(minutes=BENCH_TZ_OFFSET)


def run_scenario(db, name: str, owner_id: int, now=None) -> ScenarioResult:
    """Roda um cenário numa máquina efêmera; só os avisos da janela do cenário contam."""
    import secrets
    from datetime import timedelta
    from app.core.timeutil import utcnow
    from app.models.machine import Machine
    from app.services import demo

    spec = scenarios().get(name)
    if spec is None:
        raise ValueError(f"Cenário desconhecido: {name}")

    result = ScenarioResult(name=name, label=spec["label"], family=spec["family"],
                            expected=spec["expect"], steps=spec["steps"])
    machine = Machine(
        name=f"[BENCH] {spec['label']}", hostname=f"bench-{name}-{secrets.token_hex(2)}",
        os_type="Windows", os_version="11", os_pretty="Windows 11 Pro (benchmark)",
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        # Sem IA: cada anomalia enfileiraria uma explicação que ninguém lê
        ai_privacy="no_ai",
        system_info={"form_factor": "desktop", "is_admin": True, "tz_offset_minutes": BENCH_TZ_OFFSET},
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    # Guardado agora: um `rollback` no meio expira a instância, e ler `machine.id`
    # no `finally` levantaria ObjectDeletedError se a linha já tiver sumido
    machine_id = machine.id

    # A demonstração usa o `random` global, que o processo inteiro divide:
    # o estado é restaurado no fim
    import random
    rng_state = random.getstate()
    random.seed(f"{SEED}:{name}")

    try:
        clock = _virtual_clock(now or utcnow())
        interval = spec.get("interval", INTERVAL)
        warmup_end = clock - timedelta(seconds=spec["steps"] * interval)
        step = timedelta(hours=WARMUP_HOURS) / WARMUP_STEPS
        _seed_known(db, machine, spec.get("known_processes") or [])

        # Aquecimento: uso comum, para sair do aprendizado e formar os baselines
        for k in range(WARMUP_STEPS):
            ts = warmup_end - timedelta(hours=WARMUP_HOURS) + step * k
            _feed(db, machine, demo._base_metric(k), demo._normal_processes(), ts, {})

        for k in range(spec["steps"]):
            ts = warmup_end + timedelta(seconds=(k + 1) * interval)
            data = demo._base_metric(WARMUP_STEPS + k)
            procs = demo._normal_processes()
            if "demo" in spec:
                extra = demo._scenario_step(spec["demo"], "attack", k, data, procs)
            else:
                spec["overlay"](k, data, procs)
                extra = {}
            # Em todo cenário: se a previsão disparar num normal, é falso positivo de verdade
            extra["reconferir"] = True
            _record(result, _feed(db, machine, data, procs, ts, extra))
    except Exception as e:  # noqa: BLE001 — um cenário quebrado não derruba a rodada
        result.error = f"{type(e).__name__}: {e}"
        db.rollback()
    finally:
        random.setstate(rng_state)
        _drop_machine(db, machine_id)

    return result


def _drop_machine(db, machine_id: int) -> None:
    from app.routers.machines import delete_machine_cascade
    try:
        delete_machine_cascade(machine_id, db)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"[Benchmark] Máquina efêmera {machine_id} não removida: {e}")


def run(db, owner_id: int, names: Optional[List[str]] = None) -> BenchmarkResult:
    import time
    start = time.monotonic()
    sweep_orphans(db, owner_id)
    targets = names or list(scenarios().keys())
    results = [run_scenario(db, name, owner_id) for name in targets]
    return BenchmarkResult(
        scenarios=results,
        metrics=confusion(results),
        duration_ms=int((time.monotonic() - start) * 1000),
    )


MIN_REAL_STEPS = 10
# Teto de leituras de um cenário real: uma janela larga viraria milhares de
# passagens pelo pipeline
REAL_LIMIT = 600


def run_real_scenario(db, source_machine_id: int, owner_id: int, minutes: int = 240,
                      limit: int = REAL_LIMIT) -> ScenarioResult:
    """Reproduz leituras gravadas de uma máquina em uso normal: todo aviso é falso positivo.

    Numa máquina efêmera: a original já tem histórico e modelo treinado, um estado
    que não dá para reconstruir depois.
    """
    import secrets
    from datetime import timedelta
    from app.core.timeutil import aware, utcnow
    from app.models.machine import Machine
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot

    source = db.query(Machine).filter(Machine.id == source_machine_id).first()
    result = ScenarioResult(
        name=f"real_{source_machine_id}",
        label=f"Uso real de {source.name if source else source_machine_id} ({minutes} min)",
        family=REAL, expected=None,
    )
    if source is None:
        result.error = "máquina de origem não encontrada"
        return result

    cutoff = utcnow() - timedelta(minutes=minutes)
    readings = (
        db.query(Metric)
        .filter(Metric.machine_id == source_machine_id, Metric.timestamp >= cutoff)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
        .all()
    )
    readings.reverse()  # mais antiga primeiro: o aquecimento vem antes da medição
    if len(readings) < WARMUP_STEPS + MIN_REAL_STEPS:
        # Sem leituras para aquecer E medir, não pode virar verdadeiro negativo de graça
        result.error = (f"leituras insuficientes: {len(readings)}, "
                        f"precisa de {WARMUP_STEPS + MIN_REAL_STEPS}")
        return result

    columns = [c.name for c in Metric.__table__.columns
               if c.name not in ("id", "machine_id", "timestamp", "ml_score", "excluded_from_training")]
    snaps_by_metric: Dict[int, List[Any]] = {}
    for p in db.query(ProcessSnapshot).filter(
            ProcessSnapshot.metric_id.in_([m.id for m in readings])).all():
        snaps_by_metric.setdefault(p.metric_id, []).append(p)

    machine = Machine(
        name=f"[BENCH] {result.label}", hostname=f"bench-real-{secrets.token_hex(2)}",
        os_type=source.os_type, os_version=source.os_version, os_pretty=source.os_pretty,
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        ai_privacy="no_ai", system_info=source.system_info,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    machine_id = machine.id  # ver o comentário em run_scenario

    measured_start = measured_end = None
    try:
        for i, reading in enumerate(readings):
            data = {c: getattr(reading, c) for c in columns}
            procs = [{"name": p.name, "cpu_percent": p.cpu_percent, "mem_percent": p.mem_percent,
                      "exe": p.exe, "signed": p.signed, "publisher": p.publisher,
                      "username": p.username, "cmdline": p.cmdline}
                     for p in snaps_by_metric.get(reading.id, [])]
            # `aware`: a coluna volta ingênua no SQLite e com fuso no PostgreSQL
            created = _feed(db, machine, data, procs, aware(reading.timestamp),
                            {"reconferir": i >= WARMUP_STEPS})
            if i >= WARMUP_STEPS:
                if result.steps == 0:
                    measured_start = aware(reading.timestamp)
                measured_end = aware(reading.timestamp)
                result.steps += 1
                _record(result, created)
        if result.steps:
            result.hours = (measured_end - measured_start).total_seconds() / 3600
    except Exception as e:  # noqa: BLE001
        result.error = f"{type(e).__name__}: {e}"
        db.rollback()
    finally:
        _drop_machine(db, machine_id)

    return result


# Duas semanas de coleta a cada 30 s, com folga; acima disso a avaliação levaria horas
REPLAY_LIMIT = 60000

_REPLAY_PROC_FIELDS = ("name", "pid", "ancestors", "cpu_percent", "mem_percent", "exe", "signed", "publisher",
                       "username", "cmdline", "sha256", "ppid", "parent_name")


def _replay_proc(snapshot) -> Dict[str, Any]:
    """Processo gravado para reprodução, com pid e pais, de que o contexto de uso precisa."""
    return {k: getattr(snapshot, k, None) for k in _REPLAY_PROC_FIELDS}


def replay_window(db, source_machine_id: int, owner_id: int, start, end, warmup_hours: float = 6,
                  limit: int = REPLAY_LIMIT, meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Reproduz as leituras gravadas de [start - warmup, end] numa máquina efêmera.

    Devolve os avisos que cruzam [start, end]. A camada de detecção e a chave de
    contexto ativas nesta thread valem para a reprodução inteira. As colunas de
    contexto não são copiadas: o pipeline as recalcula, como faria na chegada.
    """
    import secrets
    from datetime import timedelta
    from app.core.timeutil import aware
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot
    from app.services import context

    source = db.query(Machine).filter(Machine.id == source_machine_id).first()
    if source is None:
        return []
    start, end = aware(start), aware(end)
    readings = (
        db.query(Metric)
        .filter(Metric.machine_id == source_machine_id,
                Metric.timestamp >= start - timedelta(hours=warmup_hours), Metric.timestamp <= end)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
        .all()
    )
    readings.reverse()  # mais antiga primeiro: aquecer e depois medir
    if not readings:
        if meta is not None:
            meta["truncated"], meta["covered_from"] = False, None
        return []

    # Estourou o teto: ficam as mais novas. Sinaliza o corte para o chamador não
    # apresentar uma janela parcial como se fosse a inteira.
    if meta is not None:
        oldest = aware(readings[0].timestamp)
        truncated = bool(
            db.query(Metric.id).filter(
                Metric.machine_id == source_machine_id,
                Metric.timestamp >= start - timedelta(hours=warmup_hours),
                Metric.timestamp < readings[0].timestamp,
            ).first()
        )
        meta["truncated"] = truncated
        meta["covered_from"] = oldest if truncated else None

    excluded = {"id", "machine_id", "timestamp", "ml_score", "excluded_from_training", *context.COLUMNS}
    columns = [c.name for c in Metric.__table__.columns if c.name not in excluded]

    machine = Machine(
        name=f"{BENCH_PREFIX} Reprodução de {source.name}", hostname=f"bench-replay-{secrets.token_hex(2)}",
        os_type=source.os_type, os_version=source.os_version, os_pretty=source.os_pretty,
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        ai_privacy="no_ai", system_info=source.system_info,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    machine_id = machine.id  # ver o comentário em run_scenario

    try:
        # Em blocos: os processos de duas semanas não cabem de uma vez
        for i in range(0, len(readings), 500):
            chunk = readings[i:i + 500]
            snaps: Dict[int, List[Any]] = {}
            for p in db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_([m.id for m in chunk])).all():
                snaps.setdefault(p.metric_id, []).append(_replay_proc(p))
            for reading in chunk:
                ts = aware(reading.timestamp)
                _feed(db, machine, {c: getattr(reading, c) for c in columns}, snaps.get(reading.id, []), ts,
                      {"reconferir": ts >= start})

        alerts = []
        for a in db.query(Anomaly).filter(Anomaly.machine_id == machine_id).all():
            detected = aware(a.detected_at)
            last = aware(a.last_seen_at) or detected
            if detected is None or detected > end or last < start:
                continue
            alerts.append({
                "type": a.anomaly_type,
                "severity": a.severity,
                "responsible": a.responsible_process,
                "programas": list((a.affected_metrics or {}).get("programas") or []),
                "detected_at": detected,
                "last_seen_at": last,
                "user_driven": bool(a.user_driven),
                # Abaixo de `medium`, ou durante o aprendizado, o aviso não interrompe
                "notifies": a.severity in NOTIFYING and not a.during_learning,
            })
        return alerts
    finally:
        _drop_machine(db, machine_id)


BENCH_PREFIX = "[BENCH]"


def sweep_orphans(db, owner_id: int) -> int:
    """Remove máquinas efêmeras de uma rodada interrompida (SIGKILL pula o `finally`)."""
    from app.models.machine import Machine
    # Ids, não objetos: depois do delete, ler `m.id` levanta ObjectDeletedError
    ids = [
        row[0] for row in db.query(Machine.id)
        .filter(Machine.owner_id == owner_id, Machine.name.like(f"{BENCH_PREFIX}%"))
        .all()
    ]
    removed = 0
    for machine_id in ids:
        try:
            _drop_machine(db, machine_id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"[Benchmark] Órfã {machine_id} resistiu à remoção: {e}")
            continue
        # Conta o que saiu de verdade, não o que foi tentado
        if db.query(Machine.id).filter(Machine.id == machine_id).first() is None:
            removed += 1
    return removed
