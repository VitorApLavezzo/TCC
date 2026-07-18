"""
Migration: adiciona novas colunas e tabelas.
Execute: python migrate.py
"""
from app.database import engine, Base
from app.models import *  # garante que todos os modelos sejam importados
from sqlalchemy import text

# Cria tabelas novas que não existem (process_baselines)
Base.metadata.create_all(bind=engine)

# Adiciona colunas novas na tabela metrics (se não existirem)
alterations = [
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS cpu_freq_current FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS cpu_freq_max FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS cpu_count_logical INTEGER",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS cpu_count_physical INTEGER",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS swap_used FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS swap_percent FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS swap_total FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS disk_partitions JSON",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS gpu_metrics JSON",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS temperatures JSON",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS battery_percent FLOAT",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS battery_plugged BOOLEAN",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS battery_secs_left FLOAT",
    # ProcessSnapshot novos campos
    "ALTER TABLE processes ADD COLUMN IF NOT EXISTS ppid INTEGER",
    "ALTER TABLE processes ADD COLUMN IF NOT EXISTS create_time FLOAT",
    "ALTER TABLE processes ADD COLUMN IF NOT EXISTS cmdline TEXT",
]

with engine.connect() as conn:
    for sql in alterations:
        print(f"  {sql[:60]}...")
        conn.execute(text(sql))
    conn.commit()

print("\nMigration concluida com sucesso!")
