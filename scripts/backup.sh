#!/bin/sh
# Cópia periódica do banco para ./backups.
#
# Os dados de coleta do TCC já sumiram uma vez sem cópia nenhuma. Este laço faz
# um pg_dump a cada BACKUP_INTERVAL_HOURS e apaga os mais velhos que
# BACKUP_KEEP_DAYS. O dump vai primeiro para um arquivo temporário e só ganha o
# nome final se terminou: um dump interrompido nunca se passa por válido.
#
# Restaurar (apaga e recria as tabelas do banco atual):
#   gunzip -c backups/anomaly_db-AAAAMMDD-HHMMSS.sql.gz \
#     | docker compose exec -T db psql -U postgres -d anomaly_db
set -eu

intervalo=$(( ${BACKUP_INTERVAL_HOURS:-6} * 3600 ))
guardar=${BACKUP_KEEP_DAYS:-14}

while true; do
    nome="/backups/${PGDATABASE}-$(date -u +%Y%m%d-%H%M%S).sql.gz"
    if pg_dump --no-owner --clean --if-exists > /tmp/dump.sql; then
        gzip -c /tmp/dump.sql > "$nome.tmp"
        mv "$nome.tmp" "$nome"
        echo "[backup] $(date -u '+%F %T') ok: $nome ($(du -h "$nome" | cut -f1))"
    else
        echo "[backup] $(date -u '+%F %T') FALHOU: pg_dump retornou erro" >&2
    fi
    rm -f /tmp/dump.sql
    find /backups -name "${PGDATABASE}-*.sql.gz" -mtime +"$guardar" -delete
    sleep "$intervalo"
done
