#!/usr/bin/env bash
# Pruebas E2E de las 4 vistas en Chromium (Playwright) por el gateway HTTPS, contra Minikube o contra Docker Compose.
#   bash scripts/prueba_e2e.sh                 # Minikube, todas
#   bash scripts/prueba_e2e.sh -k paciente     # Minikube, las que coincidan
#   bash scripts/prueba_e2e.sh compose         # Docker Compose (https://localhost:8443); acepta -k como arriba
#
# Construye la imagen hc-e2e:local la primera vez (Playwright + Chromium, ~1 GB). Las capturas de las pruebas
# que fallan quedan en tests/e2e/salida/. Necesita HAPI de Sincelejo para la prueba de migración a FHIR (si no está, se omite).
set -euo pipefail
cd "$(dirname "$0")/.."

MODO=k8s; [ "${1:-}" = compose ] && { MODO=compose; shift; }
docker image inspect hc-e2e:local >/dev/null 2>&1 || docker build -t hc-e2e:local tests/e2e
python3 scripts/credenciales.py >/dev/null
python3 scripts/certificados.py >/dev/null
mkdir -p tests/e2e/salida
if [ "$MODO" = compose ]; then RED=(--network host); BASE="https://localhost:8443"
else RED=(--network minikube); BASE="https://$(minikube ip):30443"; fi
docker run --rm "${RED[@]}" --ipc=host \
    -v "$PWD/tests/e2e":/e2e -v "$PWD/tests/api/sesion.py":/e2e/sesion.py:ro \
    -v "$PWD/credenciales/ca.crt":/ca.crt:ro -e HC_CA=/ca.crt \
    -e HC_CREDENCIALES="$(python3 scripts/credenciales.py --valor usuarios_claro)" \
    -e E2E_BASE="$BASE" -e E2E_CAPTURAS -e PYTHONDONTWRITEBYTECODE=1 \
    hc-e2e:local python -m pytest -v -p no:cacheprovider "$@"
