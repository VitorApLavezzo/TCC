from pydantic import BaseModel
from typing import Optional, List, Any
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


class GPUData(BaseModel):
    id: int
    name: str
    load_percent: Optional[float] = None
    mem_used_mb: Optional[float] = None
    mem_total_mb: Optional[float] = None
    mem_percent: Optional[float] = None
    temperature: Optional[float] = None
    driver: Optional[str] = None


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

    process_count: int
    processes: Optional[List[ProcessData]] = []


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
    disk_read_bytes: Optional[float]
    disk_write_bytes: Optional[float]
    disk_partitions: Optional[Any]
    uptime_seconds: Optional[float]
    load_avg_1: Optional[float]
    load_avg_5: Optional[float]
    load_avg_15: Optional[float]
    temperatures: Optional[Any]
    battery_secs_left: Optional[float]
    battery_cycle_count: Optional[int]

    class Config:
        from_attributes = True
