"""
Detector de padrões comportamentais avançados.
Vai além de thresholds — analisa tendências, novos processos, padrões suspeitos.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.process_baseline import ProcessBaseline


# Processos do sistema operacional considerados seguros (whitelist básica)
SYSTEM_PROCESSES_WINDOWS = {
    "system", "system idle process", "svchost.exe", "lsass.exe", "winlogon.exe",
    "explorer.exe", "csrss.exe", "smss.exe", "wininit.exe", "services.exe",
    "spoolsv.exe", "taskhostw.exe", "runtimebroker.exe", "searchindexer.exe",
    "dwm.exe", "ntoskrnl.exe", "audiodg.exe", "conhost.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "dllhost.exe", "msiexec.exe", "registry",
    "memory compression", "secure system",
}

def _is_system_process(name: str) -> bool:
    return (name or "").lower() in SYSTEM_PROCESSES_WINDOWS | SYSTEM_PROCESSES_LINUX

SYSTEM_PROCESSES_LINUX = {
    "systemd", "kthreadd", "ksoftirqd", "migration", "watchdog", "cpuhp",
    "kdevtmpfs", "netns", "rcu_gp", "rcu_par_gp", "kworker", "init",
    "bash", "sh", "sshd", "cron", "rsyslog", "dbus-daemon", "NetworkManager",
}

# Indicadores de malware por nome de processo (heurística)
SUSPICIOUS_NAMES = {
    "cryptominer", "xmrig", "minerd", "cgminer", "bfgminer",
    "mimikatz", "powershell_ise", "mshta", "wscript", "cscript",
    "regsvr32", "rundll32", "certutil", "bitsadmin",
}


class BehaviorAnalysis:
    def __init__(self):
        self.anomaly_type: Optional[str] = None
        self.severity: str = "low"
        self.affected_metrics: Dict[str, Any] = {}
        self.responsible_process: Optional[str] = None
        self.behavior_details: Dict[str, Any] = {}
        self.confidence: float = 0.0

    @property
    def is_anomaly(self) -> bool:
        return self.anomaly_type is not None


def analyze_behavior(metric: Metric, db: Session) -> Optional[BehaviorAnalysis]:
    """
    Executa todos os detectores comportamentais em sequência.
    Retorna o resultado mais grave encontrado.
    """
    processes = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .all()
    )

    history = (
        db.query(Metric)
        .filter(Metric.machine_id == metric.machine_id)
        .order_by(Metric.timestamp.desc())
        .limit(30)
        .all()
    )

    detectors = [
        detect_memory_leak,
        detect_cpu_loop,
        detect_ddos_indicators,
        detect_new_suspicious_process,
        detect_malware_pattern,
        detect_resource_abuse,
        detect_behavioral_change,
    ]

    results = []
    for detector in detectors:
        try:
            result = detector(metric, processes, history, db)
            if result and result.is_anomaly:
                results.append(result)
        except Exception as e:
            print(f"Detector {detector.__name__} error: {e}")

    if not results:
        return None

    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return max(results, key=lambda r: severity_order.get(r.severity, 0))


def detect_memory_leak(metric: Metric, processes: List[ProcessSnapshot],
                       history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta processo com crescimento monotônico de memória ao longo do tempo.
    Sinal clássico de memory leak.
    """
    if len(history) < 10:
        return None

    # Busca snapshots de processos das últimas coletas
    recent_metric_ids = [m.id for m in history[:15]]
    recent_procs = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id.in_(recent_metric_ids))
        .all()
    )

    # Agrupa por nome do processo
    proc_mem_history: Dict[str, List[float]] = {}
    for snap in recent_procs:
        if snap.name and snap.mem_percent:
            proc_mem_history.setdefault(snap.name, []).append(snap.mem_percent)

    for proc_name, mem_series in proc_mem_history.items():
        if len(mem_series) < 8:
            continue

        # Verifica crescimento monotônico nos últimos 8 pontos
        last_8 = mem_series[-8:]
        increases = sum(1 for i in range(1, len(last_8)) if last_8[i] > last_8[i - 1])

        if increases >= 7 and last_8[-1] > 5.0:  # >87.5% crescendo E usando >5% RAM
            growth = last_8[-1] - last_8[0]
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "memory_leak"
            analysis.severity = "high" if last_8[-1] > 20 else "medium"
            analysis.responsible_process = proc_name
            analysis.confidence = increases / (len(last_8) - 1)
            analysis.affected_metrics = {
                "mem_percent_atual": round(last_8[-1], 2),
                "mem_percent_inicial": round(last_8[0], 2),
                "crescimento_percent": round(growth, 2),
            }
            analysis.behavior_details = {
                "type": "memory_leak",
                "process": proc_name,
                "series": [round(v, 2) for v in last_8],
                "growth_rate": round(growth / len(last_8), 3),
                "consecutive_increases": increases,
            }
            return analysis

    return None


def detect_cpu_loop(metric: Metric, processes: List[ProcessSnapshot],
                    history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta processo em loop infinito: CPU alta sustentada em um único processo
    enquanto o resto do sistema está normal.
    """
    if not processes:
        return None

    # Ignora processos do sistema operacional
    user_procs = [p for p in processes if not _is_system_process(p.name or "")]
    top_cpu = sorted(user_procs, key=lambda p: p.cpu_percent or 0, reverse=True)
    if not top_cpu or (top_cpu[0].cpu_percent or 0) < 80:
        return None

    suspect = top_cpu[0]
    total_cpu = sum(p.cpu_percent or 0 for p in processes)
    dominance = (suspect.cpu_percent or 0) / total_cpu if total_cpu > 0 else 0

    # Verifica se este processo estava alto nas coletas anteriores também
    if len(history) >= 5:
        recent_ids = [m.id for m in history[1:6]]
        recent_snaps = (
            db.query(ProcessSnapshot)
            .filter(
                ProcessSnapshot.metric_id.in_(recent_ids),
                ProcessSnapshot.name == suspect.name,
            )
            .all()
        )
        sustained_high = sum(1 for s in recent_snaps if (s.cpu_percent or 0) > 70)

        if sustained_high >= 3 and dominance > 0.4:
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "cpu_loop"
            analysis.severity = "high" if (suspect.cpu_percent or 0) > 95 else "medium"
            analysis.responsible_process = suspect.name
            analysis.confidence = sustained_high / 5
            analysis.affected_metrics = {
                "cpu_processo": round(suspect.cpu_percent or 0, 1),
                "cpu_total": round(metric.cpu_percent or 0, 1),
                "dominancia_cpu": round(dominance * 100, 1),
                "coletas_sustentadas": sustained_high,
            }
            analysis.behavior_details = {
                "type": "cpu_loop",
                "process": suspect.name,
                "pid": suspect.pid,
                "cmdline": suspect.cmdline,
                "num_threads": suspect.num_threads,
                "sustained_collections": sustained_high,
            }
            return analysis

    return None


def detect_ddos_indicators(metric: Metric, processes: List[ProcessSnapshot],
                           history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta padrões de DDoS ou ataque de rede:
    - Pico abrupto de conexões
    - Volume de tráfego anormal
    - Combinação de alta rede + alta CPU
    """
    if len(history) < 5:
        return None

    avg_conn = sum(m.net_connections or 0 for m in history[1:]) / max(len(history) - 1, 1)
    avg_recv = sum(m.net_bytes_recv or 0 for m in history[1:]) / max(len(history) - 1, 1)
    current_conn = metric.net_connections or 0
    current_recv = metric.net_bytes_recv or 0

    conn_spike = current_conn > max(avg_conn * 5, 200) if avg_conn > 0 else current_conn > 500
    recv_spike = current_recv > avg_recv * 10 if avg_recv > 10000 else False
    high_cpu_net = (metric.cpu_percent or 0) > 70 and current_conn > 100

    if conn_spike or recv_spike or high_cpu_net:
        analysis = BehaviorAnalysis()
        analysis.anomaly_type = "ddos_indicator"
        analysis.severity = "critical" if conn_spike and recv_spike else "high"
        analysis.confidence = sum([conn_spike, recv_spike, high_cpu_net]) / 3
        analysis.affected_metrics = {
            "conexoes_atual": current_conn,
            "conexoes_media": round(avg_conn, 1),
            "multiplo_conexoes": round(current_conn / avg_conn, 1) if avg_conn > 0 else "N/A",
            "trafego_entrada_mb": round(current_recv / 1024 / 1024, 2),
        }
        analysis.behavior_details = {
            "type": "ddos_indicator",
            "connection_spike": conn_spike,
            "bandwidth_spike": recv_spike,
            "cpu_network_correlation": high_cpu_net,
            "avg_connections_baseline": round(avg_conn, 1),
        }
        return analysis

    return None


def detect_new_suspicious_process(metric: Metric, processes: List[ProcessSnapshot],
                                   history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta processos que nunca foram vistos nesta máquina antes
    e que estão consumindo recursos significativos.
    """
    known = {
        b.process_name
        for b in db.query(ProcessBaseline)
        .filter(ProcessBaseline.machine_id == metric.machine_id, ProcessBaseline.is_known == True)
        .all()
    }

    # Atualiza baseline com processos desta coleta
    _update_process_baseline(metric.machine_id, processes, db)

    if not known:
        return None  # Ainda aprendendo — sem baseline suficiente

    for proc in processes:
        if not proc.name or _is_system_process(proc.name):
            continue
        name_lower = proc.name.lower()

        is_unknown = proc.name not in known
        is_resource_heavy = (proc.cpu_percent or 0) > 15 or (proc.mem_percent or 0) > 10
        is_suspicious_name = any(s in name_lower for s in SUSPICIOUS_NAMES)

        if is_unknown and (is_resource_heavy or is_suspicious_name):
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "unknown_process" if not is_suspicious_name else "suspicious_process"
            analysis.severity = "critical" if is_suspicious_name else "medium"
            analysis.responsible_process = proc.name
            analysis.confidence = 0.9 if is_suspicious_name else 0.6
            analysis.affected_metrics = {
                "cpu_processo": round(proc.cpu_percent or 0, 1),
                "mem_processo": round(proc.mem_percent or 0, 1),
                "processo_novo": proc.name,
            }
            analysis.behavior_details = {
                "type": analysis.anomaly_type,
                "process": proc.name,
                "pid": proc.pid,
                "username": proc.username,
                "cmdline": proc.cmdline,
                "ppid": proc.ppid,
                "suspicious_name_match": is_suspicious_name,
                "first_time_seen": True,
            }
            return analysis

    return None


def detect_malware_pattern(metric: Metric, processes: List[ProcessSnapshot],
                            history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta padrão combinado típico de malware:
    - Processo desconhecido + CPU alta + atividade de rede anormal
    - Processo rodando como SYSTEM/root consumindo muitos recursos
    - Processo com nome genérico mas comportamento anormal
    """
    if len(history) < 3:
        return None

    avg_net = sum((m.net_bytes_sent or 0) + (m.net_bytes_recv or 0) for m in history[1:]) / max(len(history) - 1, 1)
    current_net = (metric.net_bytes_sent or 0) + (metric.net_bytes_recv or 0)
    net_spike = current_net > avg_net * 4 if avg_net > 1000 else False

    for proc in processes:
        if not proc.name or _is_system_process(proc.name):
            continue
        name_lower = proc.name.lower()

        proc_cpu = float(proc.cpu_percent or 0)
        cpu_high = proc_cpu > 30
        is_privileged = bool(proc.username and proc.username.lower() in ("system", "root", "nt authority\\system"))
        is_suspicious_name = any(s in name_lower for s in SUSPICIOUS_NAMES)
        has_no_cmdline = not proc.cmdline and proc_cpu > 20
        runs_from_temp = bool(proc.cmdline and any(
            p in proc.cmdline.lower() for p in ["\\temp\\", "/tmp/", "\\appdata\\local\\temp"]
        ))

        indicators = sum([
            int(cpu_high and net_spike),
            int(is_suspicious_name),
            int(has_no_cmdline),
            int(runs_from_temp),
            int(is_privileged and cpu_high),
        ])

        if indicators >= 2:
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "malware_pattern"
            analysis.severity = "critical" if indicators >= 3 else "high"
            analysis.responsible_process = proc.name
            analysis.confidence = min(indicators / 4, 1.0)
            analysis.affected_metrics = {
                "cpu_processo": round(proc.cpu_percent or 0, 1),
                "trafego_anormal": net_spike,
                "indicadores_detectados": indicators,
            }
            analysis.behavior_details = {
                "type": "malware_pattern",
                "process": proc.name,
                "pid": proc.pid,
                "username": proc.username,
                "cmdline": proc.cmdline,
                "indicators": {
                    "cpu_com_spike_rede": cpu_high and net_spike,
                    "nome_suspeito": is_suspicious_name,
                    "sem_cmdline": has_no_cmdline,
                    "executa_de_temp": runs_from_temp,
                    "privilegiado_com_cpu_alta": is_privileged and cpu_high,
                },
            }
            return analysis

    return None


def detect_resource_abuse(metric: Metric, processes: List[ProcessSnapshot],
                           history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta aplicação conhecida consumindo muito mais recursos que o normal.
    Diferente de 'CPU alta' genérico — compara com o histórico daquele processo específico.
    """
    baselines = {
        b.process_name: b
        for b in db.query(ProcessBaseline)
        .filter(ProcessBaseline.machine_id == metric.machine_id, ProcessBaseline.is_known == True)
        .all()
    }

    for proc in processes:
        if not proc.name or proc.name not in baselines:
            continue

        baseline = baselines[proc.name]
        if baseline.avg_cpu < 1.0:
            continue  # Processo normalmente ocioso, skip

        cpu_ratio = (proc.cpu_percent or 0) / baseline.avg_cpu if baseline.avg_cpu > 0 else 0
        mem_ratio = (proc.mem_percent or 0) / baseline.avg_mem_percent if baseline.avg_mem_percent > 0 else 0

        if cpu_ratio > 5 and (proc.cpu_percent or 0) > 20:
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "resource_abuse"
            analysis.severity = "high" if cpu_ratio > 10 else "medium"
            analysis.responsible_process = proc.name
            analysis.confidence = min((cpu_ratio - 5) / 10, 1.0)
            analysis.affected_metrics = {
                "cpu_atual": round(proc.cpu_percent or 0, 1),
                "cpu_media_historica": round(baseline.avg_cpu, 1),
                "multiplo_cpu": round(cpu_ratio, 1),
                "mem_atual": round(proc.mem_percent or 0, 2),
            }
            analysis.behavior_details = {
                "type": "resource_abuse",
                "process": proc.name,
                "pid": proc.pid,
                "cmdline": proc.cmdline,
                "cpu_ratio_vs_baseline": round(cpu_ratio, 2),
                "mem_ratio_vs_baseline": round(mem_ratio, 2),
                "baseline_avg_cpu": round(baseline.avg_cpu, 2),
                "baseline_max_cpu": round(baseline.max_cpu, 2),
            }
            return analysis

    return None


def detect_behavioral_change(metric: Metric, processes: List[ProcessSnapshot],
                              history: List[Metric], db: Session) -> Optional[BehaviorAnalysis]:
    """
    Detecta mudança brusca no comportamento geral da máquina.
    Compara janela recente vs janela anterior (change-point detection simples).
    """
    if len(history) < 16:
        return None

    recent = history[:8]
    previous = history[8:16]

    def avg(metrics, field):
        vals = [getattr(m, field) or 0 for m in metrics]
        return sum(vals) / len(vals) if vals else 0

    changes = {}
    for field, label, threshold in [
        ("cpu_percent", "CPU", 25),
        ("mem_percent", "Memória", 20),
        ("net_connections", "Conexões", 50),
        ("net_bytes_recv", "Tráfego rede", 500000),
    ]:
        avg_recent = avg(recent, field)
        avg_prev = avg(previous, field)
        if avg_prev > 0:
            delta = abs(avg_recent - avg_prev)
            pct_change = (delta / avg_prev) * 100
            if pct_change > threshold:
                changes[label] = {
                    "antes": round(avg_prev, 2),
                    "depois": round(avg_recent, 2),
                    "variacao_pct": round(pct_change, 1),
                }

    if len(changes) >= 2:
        analysis = BehaviorAnalysis()
        analysis.anomaly_type = "behavioral_change"
        analysis.severity = "high" if len(changes) >= 3 else "medium"
        analysis.confidence = min(len(changes) / 4, 1.0)
        analysis.affected_metrics = {k: v["variacao_pct"] for k, v in changes.items()}
        analysis.behavior_details = {
            "type": "behavioral_change",
            "changed_metrics": changes,
            "change_count": len(changes),
            "description": f"{len(changes)} métricas com variação brusca simultânea",
        }
        return analysis

    return None


def _update_process_baseline(machine_id: int, processes: List[ProcessSnapshot], db: Session):
    """Atualiza o baseline de processos conhecidos para a máquina."""
    for proc in processes:
        if not proc.name:
            continue
        baseline = db.query(ProcessBaseline).filter(
            ProcessBaseline.machine_id == machine_id,
            ProcessBaseline.process_name == proc.name,
        ).first()

        if baseline:
            n = baseline.seen_count
            baseline.avg_cpu = (baseline.avg_cpu * n + (proc.cpu_percent or 0)) / (n + 1)
            baseline.max_cpu = max(baseline.max_cpu, proc.cpu_percent or 0)
            baseline.avg_mem_percent = (baseline.avg_mem_percent * n + (proc.mem_percent or 0)) / (n + 1)
            baseline.max_mem_percent = max(baseline.max_mem_percent, proc.mem_percent or 0)
            baseline.seen_count += 1
            baseline.is_known = baseline.seen_count >= 5
        else:
            baseline = ProcessBaseline(
                machine_id=machine_id,
                process_name=proc.name,
                avg_cpu=proc.cpu_percent or 0,
                max_cpu=proc.cpu_percent or 0,
                avg_mem_percent=proc.mem_percent or 0,
                max_mem_percent=proc.mem_percent or 0,
                seen_count=1,
                is_known=False,
            )
            db.add(baseline)

    try:
        db.commit()
    except Exception:
        db.rollback()
