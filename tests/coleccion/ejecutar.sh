#!/usr/bin/env bash
# Corre la colección de Postman con newman (en un contenedor) contra el gateway, sin instalar nada:
#
#   bash tests/coleccion/ejecutar.sh            # Docker Compose (https://localhost:8443)
#   bash tests/coleccion/ejecutar.sh k8s        # Minikube (https://IP:30443)
#
# Las claves salen de credenciales/ y llegan al contenedor en un entorno temporal 0600 que se borra al terminar (no se imprimen).
# Antes: python3 scripts/datos_demo.py [--k8s] (la colección consulta al paciente sintético 7000001).
set -euo pipefail
cd "$(dirname "$0")/../.."
MODO=${1:-compose}
case "$MODO" in
  compose) BASE="https://localhost:8443"; RED=(--network host) ;;
  k8s)     BASE="https://$(minikube ip):30443"; RED=(--network minikube) ;;
  *) echo "uso: $0 [compose|k8s]"; exit 2 ;;
esac
python3 scripts/credenciales.py >/dev/null
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; chmod 700 "$T"
python3 - "$T" "$BASE" <<'PY'
import json, sys
d, base = sys.argv[1], sys.argv[2]
cred = json.load(open("credenciales/credenciales.json"))["usuarios"]
e = json.load(open("tests/coleccion/hc_local.postman_environment.json"))
for v in e["values"]:
    if v["key"] == "base_url":
        v["value"] = base
    for rol in ("sede", "medico", "auditor", "admision"):
        if v["key"] == f"clave_{rol}":
            v["value"] = cred[rol]["clave"]
json.dump(e, open(d + "/env.json", "w"))
PY
docker run --rm "${RED[@]}" -v "$T":/e:ro -v "$PWD/tests/coleccion":/c:ro -v "$PWD/credenciales/ca.crt":/ca.crt:ro postman/newman:alpine \
    run /c/historia_clinica.postman_collection.json -e /e/env.json --ssl-extra-ca-certs /ca.crt --reporters cli --color off
