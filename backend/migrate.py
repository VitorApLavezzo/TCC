"""
Migração manual (opcional).

O backend agora atualiza o esquema sozinho na subida (`app.core.migrations.
upgrade_schema`, chamado no lifespan): colunas e índices novos são criados
automaticamente. Este script continua existindo para rodar a mesma migração
à mão, sem subir a API — útil ao depurar.

Execute: python migrate.py
"""
from app.core.migrations import upgrade_schema
from app.database import engine

applied = upgrade_schema(engine)
print(f"\nMigração concluída: {len(applied)} alteração(ões) aplicada(s).")
