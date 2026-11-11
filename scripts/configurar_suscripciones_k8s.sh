#!/bin/sh
# Crea las suscripciones de ESTA sede hacia las demás (malla completa).
# Cada sede corre su propia copia de este Job en su namespace.
# Idempotente: si la suscripción ya existe no hace nada.
#
# Variables: LOCAL_NAME, PEERS ("cartagena:pg.sede-cartagena.svc.cluster.local ..."),
#            PGPASSWORD (admin), REPLICATION_PASSWORD, POSTGRES_USER, POSTGRES_DB.
set -eu

DB="${POSTGRES_DB:-historia_clinica}"
ADMIN="${POSTGRES_USER:-admin}"

until pg_isready -q -h pg-local -U "$ADMIN" -d "$DB"; do sleep 2; done

for par in $PEERS; do
  nombre="${par%%:*}"
  host="${par#*:}"
  # La sede par puede tardar en estar lista; no se continúa sin ella.
  until pg_isready -q -h "$host" -U "$ADMIN" -d "$DB"; do
    echo "esperando a $host..."; sleep 3
  done

  psql -h pg-local -U "$ADMIN" -d "$DB" -v ON_ERROR_STOP=1 \
       -v sub="sub_${LOCAL_NAME}_desde_${nombre}" \
       -v conn="host=${host} port=5432 dbname=${DB} user=replicator password=${REPLICATION_PASSWORD} connect_timeout=5" \
       <<'SQL'
SELECT format(
    'CREATE SUBSCRIPTION %I CONNECTION %L PUBLICATION pub_sede
       WITH (origin = none, copy_data = false)',
    :'sub', :'conn')
 WHERE NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = :'sub')
\gexec
SQL
  echo "OK  ${LOCAL_NAME} <- ${nombre}"
done

echo "Suscripciones de ${LOCAL_NAME} configuradas."
