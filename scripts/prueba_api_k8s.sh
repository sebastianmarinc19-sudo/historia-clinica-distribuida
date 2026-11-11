#!/usr/bin/env bash
# Corre las pruebas unitarias y de integración de la API contra el despliegue en Minikube.
#   bash scripts/k8s_desplegar.sh        # una vez
#   bash scripts/prueba_api_k8s.sh
#
# Usa la imagen hc-api:local con ./app montado, dentro de la red `minikube`
# para alcanzar los NodePort de las sedes y del gateway.
set -euo pipefail
cd "$(dirname "$0")/.."

IP=$(minikube ip)
python3 scripts/credenciales.py >/dev/null
python3 scripts/certificados.py >/dev/null
docker run --rm --network minikube \
    -v "$PWD/app":/app -v "$PWD/tests/api":/app/tests -w /app -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$PWD/credenciales/ca.crt":/ca.crt:ro -e HC_CA=/ca.crt \
    -e HC_CREDENCIALES="$(python3 scripts/credenciales.py --valor usuarios_claro)" \
    -e HC_JWT_SECRETO="$(python3 scripts/credenciales.py --valor jwt)" \
    -e API_SINCELEJO="http://$IP:30101" -e API_CARTAGENA="http://$IP:30102" \
    -e API_COROZAL="http://$IP:30103" -e API_GATEWAY="https://$IP:30443" -e API_GATEWAY_HTTP="http://$IP:30100" \
    hc-api:local python -m pytest -v -p no:cacheprovider tests "$@"
