"""
Migração manual (opcional): roda `upgrade_schema`, que o backend já aplica na subida, sem subir a API.

Execute: python migrate.py
"""
from app.core.migrations import upgrade_schema
from app.database import engine

applied = upgrade_schema(engine)
print(f"\nMigração concluída: {len(applied)} alteração(ões) aplicada(s).")
