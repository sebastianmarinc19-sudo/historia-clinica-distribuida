#!/usr/bin/env bash
# Corre las pruebas de la API v2 dentro de la red de compose.
#   docker compose -f docker-compose.yml up -d --build
#   bash scripts/prueba_api.sh            # unitarias + integración
#   bash scripts/prueba_api.sh unit       # solo unitarias (no necesita las sedes)
#
# Usa la imagen hc-api:local (ya trae las dependencias) con ./app montado,
# así los cambios en tests/ se ven sin reconstruir la imagen.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVOS="tests/test_unitarias.py tests/test_integracion.py tests/test_autenticacion.py tests/test_mpi.py tests/test_hsb_api.py tests/test_auditoria.py tests/test_reporte.py tests/test_acid.py tests/test_fhir_put.py tests/test_tls.py"
[ "${1:-}" = "unit" ] && ARCHIVOS="tests/test_unitarias.py"

# Las claves de laboratorio (credenciales/, ignorado por git) viajan solo como variables de entorno del contenedor.
python3 scripts/credenciales.py >/dev/null
python3 scripts/certificados.py >/dev/null
docker run --rm --network hc-sedes_sedes_net \
    -v "$PWD/app":/app -v "$PWD/tests/api":/app/tests -w /app -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$PWD/credenciales/ca.crt":/ca.crt:ro -e HC_CA=/ca.crt \
    -e HC_CREDENCIALES="$(python3 scripts/credenciales.py --valor usuarios_claro)" \
    -e HC_JWT_SECRETO="$(python3 scripts/credenciales.py --valor jwt)" \
    hc-api:local python -m pytest -v -p no:cacheprovider $ARCHIVOS
