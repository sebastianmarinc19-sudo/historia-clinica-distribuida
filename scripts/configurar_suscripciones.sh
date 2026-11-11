#!/bin/sh
# Crea las suscripciones cruzadas entre las tres sedes (malla completa).
# Idempotente: si la suscripción ya existe no hace nada.
#
# origin = none  -> una sede no re-publica lo que recibió de otra (evita
#                   bucles sin necesidad de filtros por fila).
# copy_data=false-> al arrancar, las tablas de núcleo están vacías.
#
# Variables: PGPASSWORD (admin) y REPLICATION_PASSWORD (rol replicator).
set -eu

NODOS="sincelejo cartagena corozal"
DB="${POSTGRES_DB:-historia_clinica}"
ADMIN="${POSTGRES_USER:-admin}"

for local in $NODOS; do
  # Espera a que el nodo local acepte conexiones TCP.
  until pg_isready -q -h "pg_$local" -U "$ADMIN" -d "$DB"; do sleep 1; done

  for peer in $NODOS; do
    [ "$local" = "$peer" ] && continue

    psql -h "pg_$local" -U "$ADMIN" -d "$DB" -v ON_ERROR_STOP=1 \
         -v sub="sub_${local}_desde_${peer}" \
         -v conn="host=pg_${peer} port=5432 dbname=${DB} user=replicator password=${REPLICATION_PASSWORD} connect_timeout=5" \
         <<'SQL'
SELECT format(
    'CREATE SUBSCRIPTION %I CONNECTION %L PUBLICATION pub_sede
       WITH (origin = none, copy_data = false)',
    :'sub', :'conn')
 WHERE NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = :'sub')
\gexec
SQL
    echo "OK  pg_${local} <- pg_${peer}"
  done
done

echo "Suscripciones configuradas (malla completa de 3 sedes)."
