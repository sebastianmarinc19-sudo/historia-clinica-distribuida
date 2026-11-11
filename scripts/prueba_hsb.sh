#!/usr/bin/env bash
# Pruebas del HSB: unitarias (normalizador, FHIR) e integración del bus contra un PostgreSQL REAL y destinos simulados.
#   bash scripts/prueba_hsb.sh            # todas
#   bash scripts/prueba_hsb.sh -k muerto  # las que coincidan
# Necesita solo Docker. Levanta un PostgreSQL desechable (en memoria, sin volumen) en una red propia y lo elimina al terminar.
set -euo pipefail
cd "$(dirname "$0")/.."

docker build -q -t hc-hsb:local hsb >/dev/null
red="hsb_prueba_$$"
pg="hsb_prueba_pg_$$"
trap 'docker rm -fv "$pg" >/dev/null 2>&1 || true; docker network rm "$red" >/dev/null 2>&1 || true' EXIT
docker network create "$red" >/dev/null
docker run -d --name "$pg" --network "$red" --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_USER=hsb -e POSTGRES_PASSWORD=hsb -e POSTGRES_DB=hsb postgres:16-alpine >/dev/null
docker run --rm --network "$red" -e HSB_DB_HOST="$pg" -e HSB_EJEMPLOS=/ejemplos -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$PWD/ejemplos":/ejemplos:ro -v "$PWD/hsb/tests":/app/tests:ro \
    hc-hsb:local python -m pytest -p no:cacheprovider -v "$@" tests
