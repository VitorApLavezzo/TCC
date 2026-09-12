from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class InventorySnapshot(Base):
    """Último inventário conhecido de uma máquina, por tipo.

    Tipos: "programs" (instalados), "os" (versão e build), "hotfixes"
    (atualizações do Windows), "drivers", "disk_health" (SMART) e
    "hardware_errors". Guardamos só o mais recente de cada tipo: o histórico
    útil são as diferenças, que viram `ChangeEvent`.
    """
    __tablename__ = "inventory_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    collected_at = Column(DateTime(timezone=True), server_default=func.now())
    items = Column(JSON)
    digest = Column(String)


class ChangeEvent(Base):
    """Algo que mudou no computador: programa instalado, atualização, driver novo.

    `impact` é preenchido dias depois, comparando o comportamento antes e
    depois — é o que permite dizer "desde a atualização de terça...".
    """
    __tablename__ = "change_events"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    # installed | removed | updated | os_update | hotfix | driver_update | agent_update
    kind = Column(String, nullable=False)
    name = Column(String, nullable=False)
    version_from = Column(String)
    version_to = Column(String)
    details = Column(JSON)
    impact = Column(JSON)
    impact_evaluated_at = Column(DateTime(timezone=True))
