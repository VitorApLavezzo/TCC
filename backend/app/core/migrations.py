"""
Atualização automática do esquema do banco.

O projeto não usa Alembic: as tabelas nascem do `create_all` no primeiro start.
Só que `create_all` cria tabelas novas e ignora colunas novas em tabelas que já
existem — toda funcionalidade que acrescentava um campo exigia rodar
`migrate.py` à mão, e quem esquecia via o backend quebrar com "column does not
exist" logo na primeira leitura.

Aqui a diferença entre os modelos e o banco real é calculada na subida:
colunas e índices que faltam são criados. Só adiciona — nunca remove nem muda
tipo —, então é seguro repetir a cada start.
"""
from typing import List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ClauseElement


def _default_sql(column, dialect) -> str:
    default = column.server_default
    if default is None:
        return ""
    arg = default.arg
    if isinstance(arg, str):
        return " DEFAULT '{}'".format(arg.replace("'", "''"))
    if isinstance(arg, ClauseElement):
        return f" DEFAULT {arg.compile(dialect=dialect, compile_kwargs={'literal_binds': True})}"
    return ""


def upgrade_schema(engine: Engine) -> List[str]:
    from app.database import Base
    import app.models  # noqa: F401 — registra todos os modelos no metadata

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    applied: List[str] = []

    for table in Base.metadata.sorted_tables:
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            ddl = (
                f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(column.name)} "
                f"{column.type.compile(dialect=engine.dialect)}{_default_sql(column, engine.dialect)}"
            )
            # Uma transação por coluna: no PostgreSQL um erro aborta a transação
            # inteira, e uma coluna problemática não pode impedir as outras.
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(ddl)
            except Exception as e:
                print(f"[Migrations] Falha ao aplicar '{ddl}': {e}")

        existing_idx = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if not index.name or index.name in existing_idx:
                continue
            try:
                with engine.begin() as conn:
                    index.create(bind=conn, checkfirst=True)
                applied.append(f"CREATE INDEX {index.name}")
            except Exception as e:
                print(f"[Migrations] Falha ao criar índice {index.name}: {e}")

    for stmt in applied:
        print(f"[Migrations] {stmt}")
    return applied
