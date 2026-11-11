#!/usr/bin/env bash
# Agrega la tabla mpi_decision (decisiones humanas del MPI) a sedes YA desplegadas y la pone a replicar.
#   bash scripts/migrar_mpi_decision.sh k8s        # Minikube: pods pg-0 de los 3 namespaces
#   bash scripts/migrar_mpi_decision.sh compose    # Docker Compose: contenedores pg_<sede>
# Idempotente. Fase 1 en las tres sedes y solo después la fase 2 (refrescar suscripciones): si una suscripción
# se refresca antes de que la tabla exista en el publicador de otra sede, la réplica queda en error.
set -euo pipefail
cd "$(dirname "$0")/.."

modo=${1:?uso: migrar_mpi_decision.sh k8s|compose}
SEDES=(sincelejo cartagena corozal)

psql_sede() {   # psql_sede SEDE < archivo.sql
  local s=$1
  case "$modo" in
    k8s)     kubectl -n "sede-$s" exec -i pg-0 -- psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -q ;;
    compose) docker exec -i "pg_$s" psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -q ;;
    *) echo "modo desconocido: $modo" >&2; exit 2 ;;
  esac
}

echo "== Fase 1: tabla y publicación en las 3 sedes =="
for s in "${SEDES[@]}"; do psql_sede "$s" < db/migraciones/001_mpi_decision.sql && echo "  $s: ok"; done
echo "== Fase 2: refrescar las suscripciones =="
for s in "${SEDES[@]}"; do psql_sede "$s" < db/migraciones/002_refrescar_suscripciones.sql >/dev/null && echo "  $s: ok"; done
echo "Listo. Compruebe con la prueba de integración tests/test_mpi.py."
