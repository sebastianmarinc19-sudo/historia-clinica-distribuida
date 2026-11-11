#!/usr/bin/env bash
# Aplica un archivo SQL de db/migraciones/ a las 3 sedes YA desplegadas (los catálogos no se replican, así que hay que aplicarlo en cada una).
#   bash scripts/migrar_sql.sh k8s db/migraciones/003_catalogos_hsb.sql
#   bash scripts/migrar_sql.sh compose db/migraciones/003_catalogos_hsb.sql
# El archivo debe ser idempotente. Para la migración del MPI (que además toca la réplica) use scripts/migrar_mpi_decision.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

modo=${1:?uso: migrar_sql.sh k8s|compose archivo.sql}
archivo=${2:?uso: migrar_sql.sh k8s|compose archivo.sql}
[ -f "$archivo" ] || { echo "No existe $archivo" >&2; exit 2; }

for s in sincelejo cartagena corozal; do
  case "$modo" in
    k8s)     kubectl -n "sede-$s" exec -i pg-0 -- psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -q < "$archivo" ;;
    compose) docker exec -i "pg_$s" psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -q < "$archivo" ;;
    *) echo "modo desconocido: $modo" >&2; exit 2 ;;
  esac
  echo "  $s: ok"
done
