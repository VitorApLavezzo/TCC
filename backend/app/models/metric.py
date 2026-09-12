from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, JSON, Boolean, String, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, false
from app.database import Base


class Metric(Base):
    __tablename__ = "metrics"
    # Quase toda consulta é "leituras desta máquina, por tempo"
    __table_args__ = (Index("ix_metrics_machine_timestamp", "machine_id", "timestamp"),)

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # CPU
    cpu_percent = Column(Float)
    cpu_per_core = Column(JSON)
    cpu_freq_current = Column(Float)
    cpu_freq_max = Column(Float)
    cpu_count_logical = Column(Integer)
    cpu_count_physical = Column(Integer)

    # Memória
    mem_used = Column(Float)
    mem_available = Column(Float)
    mem_percent = Column(Float)
    mem_total = Column(Float)

    # Swap
    swap_used = Column(Float)
    swap_percent = Column(Float)
    swap_total = Column(Float)

    # Disco
    disk_used = Column(Float)
    disk_free = Column(Float)
    disk_percent = Column(Float)
    disk_read_bytes = Column(Float)
    disk_write_bytes = Column(Float)
    disk_partitions = Column(JSON)

    # Rede
    net_bytes_sent = Column(Float)
    net_bytes_recv = Column(Float)
    net_connections = Column(Integer)

    # Sistema
    uptime_seconds = Column(Float)
    load_avg_1 = Column(Float)
    load_avg_5 = Column(Float)
    load_avg_15 = Column(Float)
    boot_time = Column(Float)  # epoch do último boot — muda quando o computador reinicia
    user_idle_seconds = Column(Float)  # tempo sem teclado/mouse, quando o sistema informa

    # GPU
    gpu_metrics = Column(JSON)

    # Temperatura
    temperatures = Column(JSON)

    # Bateria
    battery_percent = Column(Float)
    battery_plugged = Column(Boolean)
    battery_secs_left = Column(Float)
    battery_health_percent = Column(Float)  # capacidade máxima atual vs. de fábrica
    battery_cycle_count = Column(Integer)

    # Energia: medida (bateria descarregando, sensor da GPU) ou estimada por modelo
    power_watts = Column(Float)
    power_source = Column(String)

    process_count = Column(Integer)

    # Espaçamento real até a leitura anterior (a coleta é adaptativa)
    interval_seconds = Column(Float)
    # Nota do Isolation Forest para esta leitura (None antes do modelo existir)
    ml_score = Column(Float)
    # Leitura feita em "modo atividade pesada": não entra no treino
    excluded_from_training = Column(Boolean, default=False, server_default=false())

    machine = relationship("Machine", back_populates="metrics")
    processes = relationship("ProcessSnapshot", back_populates="metric", cascade="all, delete-orphan")
