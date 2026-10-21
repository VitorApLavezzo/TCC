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
    # "O modelo viu": ataque com qualquer aviso, mesmo com outro nome. Separa
    # "não percebeu nada" de "percebeu e chamou de outra coisa".
    viu = sum(1 for r in ataques if r.detected)

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
        "seen": viu,
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


# Pids dos programas que os cenários põem para rodar
PID_JOGO, PID_STEAM, PID_COMPILADOR, PID_MINERADOR = 5200, 5100, 7300, 6600


def _na_tela(metric: Dict, pid: int, name: str) -> None:
    """A pessoa está usando o computador, com este programa na janela da frente."""
    metric["foreground_pid"] = pid
    metric["foreground_name"] = name
    metric["user_idle_seconds"] = 2.0


def _jogo_pesado(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 88 + (k % 4)
    metric["mem_percent"] = 74.0
    metric["gpu_metrics"] = [{"name": "GPU", "load_percent": 97, "memory_percent": 88, "temperature": 74}]
    procs.append({"name": "jogo.exe", "cpu_percent": 82.0, "mem_percent": 22.0,
                  "exe": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Jogo\\jogo.exe",
                  "signed": "signed", "publisher": "Estudio de Jogos SA", "username": "vitor",
                  "pid": PID_JOGO, "ancestors": [PID_STEAM, 1500, 700]})
    _na_tela(metric, PID_JOGO, "jogo.exe")


def _jogo_sem_assinatura(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O caso relatado: jogo fora da Steam, sem assinatura, já jogado antes."""
    metric["cpu_percent"] = 88 + (k % 4)
    metric["mem_percent"] = 70.0
    metric["gpu_metrics"] = [{"name": "GPU", "load_percent": 95, "memory_percent": 80, "temperature": 72}]
    procs.append({"name": "jogo.exe", "cpu_percent": 80.0, "mem_percent": 20.0,
                  "exe": "D:\\Games\\Jogo\\jogo.exe", "signed": "unsigned", "username": "vitor",
                  "cmdline": "jogo.exe", "pid": PID_JOGO, "ancestors": [1500, 700]})
    _na_tela(metric, PID_JOGO, "jogo.exe")


def _compilacao_do_editor(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O compilador não é a janela: é filho do editor que está na frente."""
    metric["cpu_percent"] = 95.0
    metric["load_avg_1"] = 9.0
    procs.append({"name": "cl.exe", "cpu_percent": 90.0, "mem_percent": 12.0,
                  "exe": "C:\\Program Files\\Microsoft Visual Studio\\VC\\bin\\cl.exe",
                  "signed": "signed", "publisher": "Microsoft Corporation", "username": "vitor",
                  "pid": PID_COMPILADOR, "ancestors": [7200, 3100, 1500, 700]})
    _na_tela(metric, 3100, "Code.exe")


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
    # Iniciado no login (filho do explorer); a pessoa está no navegador
    procs.append({"name": "xmrig.exe", "cpu_percent": 95.0, "mem_percent": 8.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Roaming\\xmrig.exe", "signed": "unsigned",
                  "username": "vitor", "cmdline": "xmrig.exe -o pool.exemplo:3333",
                  "pid": PID_MINERADOR, "ancestors": [1500, 700]})


def _minerador_com_pessoa_navegando(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O teste atômico: minerador renomeado, sem nome de minerador, com a pessoa usando o Chrome."""
    metric["cpu_percent"] = 96.0
    procs.append({"name": "svc_update.exe", "cpu_percent": 92.0, "mem_percent": 4.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Local\\svc_update\\svc_update.exe",
                  "signed": "unsigned", "username": "vitor", "cmdline": "svc_update.exe --bench=1M",
                  "pid": PID_MINERADOR, "ancestors": [1500, 700]})


def _minerador_no_rundll32(k: int, metric: Dict, procs: List[Dict]) -> None:
    """O minerador dentro de um binário assinado da Microsoft: a técnica clássica."""
    metric["cpu_percent"] = 96.0
    procs.append({"name": "rundll32.exe", "cpu_percent": 92.0, "mem_percent": 3.0,
                  "exe": "C:\\Windows\\System32\\rundll32.exe", "signed": "signed",
                  "publisher": "Microsoft Windows", "username": "vitor",
                  "cmdline": "rundll32.exe C:\\Users\\vitor\\AppData\\Local\\Temp\\m.dll,Start",
                  "pid": PID_MINERADOR, "ancestors": [1500, 700]})


def _binario_de_temp(k: int, metric: Dict, procs: List[Dict]) -> None:
    metric["cpu_percent"] = 80.0
    metric["net_bytes_recv"] = 5e6
    procs.append({"name": "update_helper.exe", "cpu_percent": 76.0, "mem_percent": 5.0,
                  "exe": "C:\\Users\\vitor\\AppData\\Local\\Temp\\update_helper.exe",
                  "signed": "unsigned", "username": "vitor", "cmdline": "update_helper.exe"})


def _pico_isolado(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Uma única leitura fora do padrão no meio de leituras normais — o sintoma
    relatado: alarma e some na coleta seguinte.

    Os demais passos ficam intocados de propósito. A primeira versão deste
    cenário fixava a CPU em 22-24% nos passos normais, que é a borda superior
    do que o aquecimento ensinou (14 ± 9): o modelo achava estranha a leitura
    inteira, não o pico, e o cenário media outra coisa.
    """
    if k == 3:
        metric["cpu_percent"] = 96.0
        metric["net_bytes_sent"] = 4e6


def _instalacao_de_programas(k: int, metric: Dict, procs: List[Dict]) -> None:
    """Vários executáveis novos e legítimos em coletas seguidas, como numa
    instalação de software. Cada coleta traz um programa diferente — era isto
    que virava vinte linhas de "Processo Desconhecido"."""
    metric["cpu_percent"] = 45 + (k % 5)
    procs.append({
        "name": f"setup_app{k}.exe", "cpu_percent": 22.0, "mem_percent": 11.0,
        "exe": f"C:\\Program Files\\App{k}\\setup_app{k}.exe",
        "signed": "signed", "publisher": "Contoso Ltd", "username": "vitor",
        "cmdline": f"setup_app{k}.exe /quiet",
    })


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
    # Os quatro casos difíceis do contexto de uso: o mesmo processador cheio,
    # com e sem a pessoa conduzindo
    "jogo_sem_assinatura": {"label": "Jogo sem assinatura, já jogado antes, na tela", "family": NORMAL,
                            "expect": None, "steps": 8, "overlay": _jogo_sem_assinatura,
                            "known_processes": ["jogo.exe"]},
    "compilacao_do_editor": {"label": "Compilação aberta pelo editor que está na tela", "family": NORMAL,
                             "expect": None, "steps": 8, "overlay": _compilacao_do_editor,
                             "known_processes": ["cl.exe"]},
    "minerador_com_pessoa_navegando": {"label": "Minerador renomeado com a pessoa navegando", "family": ATTACK,
                                       "expect": "unknown_process", "steps": 6,
                                       "overlay": _minerador_com_pessoa_navegando},
    "minerador_no_rundll32": {"label": "Minerador dentro do rundll32 assinado", "family": ATTACK,
                              "expect": "background_load", "steps": 6, "overlay": _minerador_no_rundll32},
    "backup_noturno": {"label": "Backup em nuvem durante a madrugada", "family": NORMAL,
                       "expect": None, "steps": 8, "overlay": _backup_noturno},
    "compilacao": {"label": "Compilação de projeto usando todos os núcleos", "family": NORMAL,
                   "expect": None, "steps": 8, "overlay": _compilacao},
    "atualizacao_do_sistema": {"label": "Windows Update instalando atualizações", "family": NORMAL,
                               "expect": None, "steps": 8, "overlay": _atualizacao_do_sistema},
    "pico_isolado": {"label": "Pico isolado numa leitura só", "family": NORMAL,
                     "expect": None, "steps": 8, "overlay": _pico_isolado},
    "instalacao_de_programas": {"label": "Instalação de vários programas legítimos", "family": NORMAL,
                                "expect": None, "steps": 8, "overlay": _instalacao_de_programas},
}


def scenarios() -> Dict[str, Dict[str, Any]]:
    """Cenários próprios mais os da demonstração, que já são ataques com gabarito."""
    from app.services import demo
    todos = dict(_OWN_SCENARIOS)
    for nome, spec in demo.SCENARIOS.items():
        todos[nome] = {"label": spec["label"], "family": ATTACK, "expect": spec["expect"],
                       "steps": spec["attack"], "demo": nome, "interval": spec.get("interval", INTERVAL)}
    return todos


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

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

    criadas = []
    a = process_metric(metric, machine, db, process_starts=extra.get("process_starts") or [], now=ts)
    if a:
        criadas.append(a)
    # Eventos do agente (arquivo-isca, contato periódico) são evidência por
    # regra: na ablação "só Isolation Forest" eles inflavam a linha do modelo
    if detection_layer() != "ml":
        if extra.get("events"):
            criadas += agent_events.handle_events(db, machine, extra["events"], metric, ts)
        if extra.get("beacons"):
            criadas += agent_events.evaluate_beacons(db, machine, extra["beacons"], ts)
    if extra.get("reconferir") and detection_layer() == "ambas":
        # Em produção o agendador reconfere a previsão de disco a cada 15
        # minutos. O benchmark pulava esse caminho de código inteiro, e o
        # cenário de disco enchendo não tinha como ser detectado. Só no sistema
        # completo: a previsão não é regra nem Isolation Forest, e na ablação
        # ela inflava a linha "só Isolation Forest".
        from app.services import forecasting
        previsto = forecasting.check_machine(db, machine)
        if previsto is not None:
            criadas.append(previsto)
    return criadas


# Fuso das máquinas efêmeras do benchmark (o mesmo de Brasília).
BENCH_TZ_OFFSET = -180

# Dia da semana (0 = segunda) e hora local em que o relógio virtual termina.
RELOGIO_DIA, RELOGIO_HORA = 2, 15


def _relogio_virtual(now) -> "datetime":
    """A quarta-feira mais recente às 15h no fuso da máquina, em UTC.

    O modelo usa hora do dia e dia da semana como atributos. Com o relógio
    virtual ancorado em "agora", o mesmo código dava resultado diferente
    conforme a hora em que se rodava — às 23h40 e às 00h05 saíram listas
    diferentes de falsos positivos. Ancorado num dia e hora fixos, os
    atributos de horário são sempre os mesmos e o número se repete. Fica a
    no máximo 7 dias atrás: dentro da janela de 14 da previsão de disco.
    """
    from datetime import timedelta
    local = now + timedelta(minutes=BENCH_TZ_OFFSET)
    alvo = (local - timedelta(days=(local.weekday() - RELOGIO_DIA) % 7)).replace(
        hour=RELOGIO_HORA, minute=0, second=0, microsecond=0)
    if alvo > local:
        alvo -= timedelta(days=7)
    return alvo - timedelta(minutes=BENCH_TZ_OFFSET)


def run_scenario(db, name: str, owner_id: int, now=None) -> ScenarioResult:
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
        system_info={"form_factor": "desktop", "is_admin": True, "tz_offset_minutes": BENCH_TZ_OFFSET},
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    # O id guardado agora, e não lido do objeto lá no fim: um `rollback` no
    # meio do cenário expira a instância, e ler `machine.id` depois volta ao
    # banco — se a linha já não estiver lá, levanta ObjectDeletedError dentro
    # do próprio `finally`. Era isso que derrubava a rodada inteira e deixava
    # a máquina efêmera no painel. Mesma precaução que `sweep_orphans` toma.
    machine_id = machine.id

    # Estado do gerador guardado e devolvido: semear o módulo global é o que
    # funciona com o `random` que a demonstração usa, mas o processo inteiro
    # divide esse gerador e não pode sair alterado daqui.
    import random
    estado = random.getstate()
    random.seed(f"{SEED}:{name}")

    try:
        agora = _relogio_virtual(now or utcnow())
        intervalo = spec.get("interval", INTERVAL)
        fim_do_aquecimento = agora - timedelta(seconds=spec["steps"] * intervalo)
        passo = timedelta(hours=WARMUP_HOURS) / WARMUP_STEPS
        _seed_known(db, machine, spec.get("known_processes") or [])

        # Aquecimento: máquina em uso comum, para sair do aprendizado e formar
        # os baselines de processo como uma máquina real formaria
        for k in range(WARMUP_STEPS):
            ts = fim_do_aquecimento - timedelta(hours=WARMUP_HOURS) + passo * k
            _feed(db, machine, demo._base_metric(k), demo._normal_processes(), ts, {})

        # Só o que acontece daqui para frente é medido
        for k in range(spec["steps"]):
            ts = fim_do_aquecimento + timedelta(seconds=(k + 1) * intervalo)
            data = demo._base_metric(WARMUP_STEPS + k)
            procs = demo._normal_processes()
            if "demo" in spec:
                extra = demo._scenario_step(spec["demo"], "attack", k, data, procs)
            else:
                spec["overlay"](k, data, procs)
                extra = {}
            # A reconferência agendada roda para todo cenário, não só o de
            # disco: se um cenário normal fizesse a previsão disparar, seria
            # um falso positivo de verdade, e tem que aparecer na conta.
            extra["reconferir"] = True
            _record(resultado, _feed(db, machine, data, procs, ts, extra))
    except Exception as e:  # noqa: BLE001 — um cenário quebrado não derruba a rodada
        resultado.error = f"{type(e).__name__}: {e}"
        db.rollback()
    finally:
        random.setstate(estado)
        _drop_machine(db, machine_id)

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
    machine_id = machine.id  # ver o comentário em run_scenario

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
            # Nas leituras medidas, a mesma reconferência agendada dos cenários
            # sintéticos: dado real é o único lugar onde a previsão de disco
            # poderia dar falso positivo, e ele tem que aparecer na conta.
            criadas = _feed(db, machine, dados, procs, aware(leitura.timestamp),
                            {"reconferir": i >= WARMUP_STEPS})
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
        _drop_machine(db, machine_id)

    return resultado


# Teto de leituras de uma reprodução: duas semanas de coleta a cada 30 s, com
# folga. Acima disso a avaliação levaria horas.
REPLAY_LIMIT = 60000

_REPLAY_PROC_FIELDS = ("name", "pid", "ancestors", "cpu_percent", "mem_percent", "exe", "signed", "publisher",
                       "username", "cmdline", "sha256", "ppid", "parent_name")


def _replay_proc(snapshot) -> Dict[str, Any]:
    """Um processo gravado, pronto para ser reproduzido — com pid e pais, que é
    o que o contexto de uso precisa e o que só existe no momento da coleta."""
    return {k: getattr(snapshot, k, None) for k in _REPLAY_PROC_FIELDS}


def replay_window(db, source_machine_id: int, owner_id: int, start, end, warmup_hours: float = 6,
                  limit: int = REPLAY_LIMIT, meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Reproduz as leituras gravadas de [start - warmup, end] numa máquina efêmera.

    Devolve os avisos que a reprodução produziu e que cruzam [start, end]. O
    aquecimento existe para o modelo da máquina efêmera treinar antes da
    primeira sessão medida; a camada de detecção e a chave de contexto ativas
    nesta thread valem para a reprodução inteira — é assim que a avaliação
    compara contexto ligado × desligado e camada por camada.

    As colunas de contexto não são copiadas: o pipeline as recalcula a partir
    da janela ativa e dos pais gravados (ou deixa vazias, com o contexto
    desligado), como faria na chegada.
    """
    import secrets
    from datetime import timedelta
    from app.core.timeutil import aware
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot
    from app.services import context

    origem = db.query(Machine).filter(Machine.id == source_machine_id).first()
    if origem is None:
        return []
    start, end = aware(start), aware(end)
    leituras = (
        db.query(Metric)
        .filter(Metric.machine_id == source_machine_id,
                Metric.timestamp >= start - timedelta(hours=warmup_hours), Metric.timestamp <= end)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
        .all()
    )
    leituras.reverse()  # mais antiga primeiro: aquecer e depois medir
    if not leituras:
        if meta is not None:
            meta["truncated"], meta["covered_from"] = False, None
        return []

    # Estourou o teto: ficam as mais NOVAS (o fim da janela, com as sessões
    # mais recentes). Sinaliza o corte e até onde a reprodução cobre, para o
    # chamador não apresentar uma janela parcial como se fosse a inteira.
    if meta is not None:
        mais_antiga = aware(leituras[0].timestamp)
        cortou = bool(
            db.query(Metric.id).filter(
                Metric.machine_id == source_machine_id,
                Metric.timestamp >= start - timedelta(hours=warmup_hours),
                Metric.timestamp < leituras[0].timestamp,
            ).first()
        )
        meta["truncated"] = cortou
        meta["covered_from"] = mais_antiga if cortou else None

    fora = {"id", "machine_id", "timestamp", "ml_score", "excluded_from_training", *context.COLUMNS}
    campos = [c.name for c in Metric.__table__.columns if c.name not in fora]

    machine = Machine(
        name=f"{BENCH_PREFIX} Reprodução de {origem.name}", hostname=f"bench-replay-{secrets.token_hex(2)}",
        os_type=origem.os_type, os_version=origem.os_version, os_pretty=origem.os_pretty,
        agent_token=secrets.token_urlsafe(24), owner_id=owner_id, is_active=True,
        ai_privacy="no_ai", system_info=origem.system_info,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    machine_id = machine.id  # ver o comentário em run_scenario

    try:
        # Em blocos: carregar os processos de duas semanas de uma vez não cabe
        for i in range(0, len(leituras), 500):
            bloco = leituras[i:i + 500]
            snaps: Dict[int, List[Any]] = {}
            for p in db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_([m.id for m in bloco])).all():
                snaps.setdefault(p.metric_id, []).append(_replay_proc(p))
            for leitura in bloco:
                ts = aware(leitura.timestamp)
                _feed(db, machine, {c: getattr(leitura, c) for c in campos}, snaps.get(leitura.id, []), ts,
                      {"reconferir": ts >= start})

        avisos = []
        for a in db.query(Anomaly).filter(Anomaly.machine_id == machine_id).all():
            detectado = aware(a.detected_at)
            ultimo = aware(a.last_seen_at) or detectado
            if detectado is None or detectado > end or ultimo < start:
                continue
            avisos.append({
                "type": a.anomaly_type,
                "severity": a.severity,
                "responsible": a.responsible_process,
                "programas": list((a.affected_metrics or {}).get("programas") or []),
                "detected_at": detectado,
                "last_seen_at": ultimo,
                "user_driven": bool(a.user_driven),
                # O mesmo corte do benchmark: abaixo de `medium`, ou durante o
                # aprendizado, o aviso fica no painel e não interrompe
                "notifies": a.severity in NOTIFYING and not a.during_learning,
            })
        return avisos
    finally:
        _drop_machine(db, machine_id)


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
