from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime


class ProcessData(BaseModel):
    pid: int
    name: str
    cpu_percent: float
    mem_percent: float
    mem_rss: float
    num_threads: int
    status: str
    username: Optional[str] = None
    # Estes campos eram enviados pelo agente mas não estavam declarados aqui —
    # o Pydantic descartava em silêncio, e os indicadores de malware baseados
    # em linha de comando nunca tinham dado para avaliar.
    ppid: Optional[int] = None
    create_time: Optional[float] = None
    cmdline: Optional[str] = None
    exe: Optional[str] = None
    sha256: Optional[str] = None
    signed: Optional[str] = None
    publisher: Optional[str] = None
    parent_name: Optional[str] = None
    # Pids dos processos pais (até 8), só nos três de maior CPU
    ancestors: Optional[List[int]] = None


class ProcessStart(BaseModel):
    """Programa que começou a rodar desde a última coleta, mesmo sem consumir nada."""
    pid: int
    name: str
    ppid: Optional[int] = None
    parent_name: Optional[str] = None
    exe: Optional[str] = None
    cmdline: Optional[str] = None
    username: Optional[str] = None
    create_time: Optional[float] = None
    sha256: Optional[str] = None
    signed: Optional[str] = None
    publisher: Optional[str] = None


class AgentEvent(BaseModel):
    """Fato observado no computador que não é uma medida: arquivo-isca alterado,
    desligamento inesperado, erro de hardware."""
    type: str
    at: Optional[float] = None  # epoch
    details: Optional[Dict[str, Any]] = None


class BeaconCandidate(BaseModel):
    """Conexões repetidas a intervalos regulares para o mesmo destino."""
    process: str
    pid: Optional[int] = None
    exe: Optional[str] = None
    remote_ip: str
    remote_port: Optional[int] = None
    events: int
    median_interval: float
    jitter: float  # coeficiente de variação dos intervalos (0 = relógio)
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None


class GPUData(BaseModel):
    id: int
    name: str
    load_percent: Optional[float] = None
    mem_used_mb: Optional[float] = None
    mem_total_mb: Optional[float] = None
    mem_percent: Optional[float] = None
    temperature: Optional[float] = None
    driver: Optional[str] = None
    power_watts: Optional[float] = None


class MetricCreate(BaseModel):
    # CPU
    cpu_percent: float
    cpu_per_core: Optional[List[float]] = None
    cpu_freq_current: Optional[float] = None
    cpu_freq_max: Optional[float] = None
    cpu_count_logical: Optional[int] = None
    cpu_count_physical: Optional[int] = None

    # Memória
    mem_used: float
    mem_available: float
    mem_percent: float
    mem_total: float

    # Swap
    swap_used: Optional[float] = None
    swap_percent: Optional[float] = None
    swap_total: Optional[float] = None

    # Disco
    disk_used: float
    disk_free: float
    disk_percent: float
    disk_read_bytes: float
    disk_write_bytes: float
    disk_partitions: Optional[List[Any]] = None

    # Rede
    net_bytes_sent: float
    net_bytes_recv: float
    net_connections: int

    # Sistema
    uptime_seconds: float
    load_avg_1: Optional[float] = None
    load_avg_5: Optional[float] = None
    load_avg_15: Optional[float] = None
    boot_time: Optional[float] = None
    user_idle_seconds: Optional[float] = None
    # Programa na janela da frente (Windows); None sem janela ou em agente antigo
    foreground_pid: Optional[int] = None
    foreground_name: Optional[str] = None

    # GPU
    gpu_metrics: Optional[List[GPUData]] = None

    # Temperatura
    temperatures: Optional[Any] = None

    # Bateria
    battery_percent: Optional[float] = None
    battery_plugged: Optional[bool] = None
    battery_secs_left: Optional[float] = None
    battery_health_percent: Optional[float] = None
    battery_cycle_count: Optional[int] = None

    # Energia
    power_watts: Optional[float] = None
    power_source: Optional[str] = None

    process_count: int
    processes: Optional[List[ProcessData]] = []

    interval_seconds: Optional[float] = None
    agent_version: Optional[str] = None

    # Blocos enviados só quando mudam ou periodicamente
    system_info: Optional[Dict[str, Any]] = None
    inventory: Optional[Dict[str, Any]] = None
    events: Optional[List[AgentEvent]] = None
    beacons: Optional[List[BeaconCandidate]] = None
    process_starts: Optional[List[ProcessStart]] = None

    # Quando a leitura foi feita no computador (epoch). Só vem preenchido nas
    # leituras que ficaram guardadas no agente enquanto o servidor estava
    # inacessível: sem isso, uma hora de fila voltaria toda com o horário da
    # reconexão e inventaria um pico que nunca existiu.
    collected_at: Optional[float] = None


# Campos que não são colunas de Metric — tratados à parte na ingestão
INGEST_EXTRA_FIELDS = {
    "processes", "agent_version", "system_info", "inventory", "events", "beacons", "process_starts",
    "collected_at",
}


class MetricOut(BaseModel):
    id: int
    machine_id: int
    timestamp: datetime
    cpu_percent: Optional[float]
    mem_percent: Optional[float]
    disk_percent: Optional[float]
    net_bytes_sent: Optional[float]
    net_bytes_recv: Optional[float]
    net_connections: Optional[int]
    process_count: Optional[int]
    gpu_metrics: Optional[Any]
    battery_percent: Optional[float]
    battery_plugged: Optional[bool]
    battery_health_percent: Optional[float]
    swap_percent: Optional[float]
    disk_read_bytes: Optional[float] = None
    disk_write_bytes: Optional[float] = None
    temperatures: Optional[Any] = None
    power_watts: Optional[float] = None
    ml_score: Optional[float] = None
    excluded_from_training: Optional[bool] = None

    class Config:
        from_attributes = True


class MetricDetailed(MetricOut):
    cpu_per_core: Optional[Any]
    cpu_freq_current: Optional[float]
    cpu_freq_max: Optional[float]
    cpu_count_logical: Optional[int]
    cpu_count_physical: Optional[int]
    mem_used: Optional[float]
    mem_available: Optional[float]
    mem_total: Optional[float]
    swap_used: Optional[float]
    swap_total: Optional[float]
    disk_used: Optional[float]
    disk_free: Optional[float]
    disk_partitions: Optional[Any]
    uptime_seconds: Optional[float]
    load_avg_1: Optional[float]
    load_avg_5: Optional[float]
    load_avg_15: Optional[float]
    battery_secs_left: Optional[float]
    battery_cycle_count: Optional[int]
    boot_time: Optional[float] = None
    user_idle_seconds: Optional[float] = None
    power_source: Optional[str] = None
    interval_seconds: Optional[float] = None

    class Config:
        from_attributes = True
