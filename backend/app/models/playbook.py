from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func, true, false
from app.database import Base


class Playbook(Base):
    """Regra de automação com autonomia graduada.

    Até aqui toda ação dependia de alguém ver o aviso e clicar. Um playbook diz
    "quando isto acontecer de novo, faça aquilo" — mas nasce sempre no nível
    mais tímido: sugerir. Subir para confirmar ou para automático é decisão
    explícita do dono, e mesmo em automático existe teto diário, modo de ensaio
    e janela para desfazer.
    """
    __tablename__ = "playbooks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Nulo = vale para todas as máquinas da conta
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    name = Column(String, nullable=False)
    # Gatilho
    anomaly_type = Column(String, nullable=False, index=True)
    process_name = Column(String)            # opcional: só para este programa
    min_severity = Column(String, default="medium")

    # Ação
    action = Column(String, nullable=False)  # kill_process | clean_temp | stop_sync_client
    params = Column(JSON)

    # sugerir | confirmar | automatico
    autonomy = Column(String, nullable=False, default="sugerir")
    # Ensaio: registra o que faria, sem mandar o comando
    dry_run = Column(Boolean, default=False, server_default=false())
    enabled = Column(Boolean, default=True, server_default=true())

    cooldown_minutes = Column(Integer, default=60)
    daily_limit = Column(Integer)
    last_run_at = Column(DateTime(timezone=True))
    runs_total = Column(Integer, default=0)


class PlaybookRun(Base):
    """Cada disparo de um playbook, com o que foi feito e como desfazer."""
    __tablename__ = "playbook_runs"

    id = Column(Integer, primary_key=True, index=True)
    playbook_id = Column(Integer, ForeignKey("playbooks.id"), nullable=False, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True)
    command_id = Column(Integer, ForeignKey("agent_commands.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # ensaio | sugerido | aguardando | executado | recusado | desfeito | bloqueado
    status = Column(String, nullable=False, default="sugerido", index=True)
    autonomy = Column(String)
    detail = Column(Text)
    # Até quando dá para desfazer, e o comando inverso quando existe
    undo_until = Column(DateTime(timezone=True))
    undo_command = Column(String)
    undone_at = Column(DateTime(timezone=True))
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
