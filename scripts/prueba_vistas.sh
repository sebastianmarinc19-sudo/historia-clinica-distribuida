#!/usr/bin/env bash
# Prueba ligera de las vistas nuevas (jsdom en un contenedor node, sin Chromium): reporte de HC del Reportero con su sello, accesos del paciente,
# tabla de mensajes del bus del Admisionista y estado de la plataforma del Médico y del Reportero, contra el gateway HTTPS.
#
#   bash scripts/prueba_vistas.sh            # Kubernetes/Minikube (https://IP:30443)
#   bash scripts/prueba_vistas.sh compose    # Docker Compose (https://localhost:8443)
#
# Crea un paciente de prueba con un encuentro y un diagnóstico, abre sesiones con las cuentas de laboratorio (credenciales/, no se imprimen;
# llegan al contenedor por un archivo temporal 0600 que se borra al terminar) y comprueba lo que pinta cada vista. El E2E completo de las
# cuatro vistas en Chromium es scripts/prueba_e2e.sh (imagen de ~2 GB).
set -euo pipefail
cd "$(dirname "$0")/.."

MODO=${1:-k8s}
case "$MODO" in
  k8s)     BASE="https://$(minikube ip):30443"; RED=(--network minikube) ;;
  compose) BASE="https://localhost:8443"; RED=(--network host) ;;
  *) echo "uso: $0 [k8s|compose]"; exit 2 ;;
esac
python3 scripts/credenciales.py >/dev/null
ENV=$(mktemp); trap 'rm -f "$ENV"' EXIT; chmod 600 "$ENV"
python3 - "$BASE" "$ENV" <<'PY'
import json, ssl, sys, time, urllib.request
base, salida = sys.argv[1], sys.argv[2]
cred = json.load(open("credenciales/credenciales.json"))["usuarios"]
ctx = ssl.create_default_context(cafile="credenciales/ca.crt")
g = f"{base}/sede/1/api/v2"
def pedir(ruta, datos=None, tok=None, metodo=None):
    cab = {"content-type": "application/json"}
    if tok: cab["Authorization"] = "Bearer " + tok
    r = urllib.request.Request(g + ruta, data=json.dumps(datos).encode() if datos is not None else None, headers=cab, method=metodo)
    return json.load(urllib.request.urlopen(r, context=ctx))
def login(u): return pedir("/auth/login", {"usuario": u, "clave": cred[u]["clave"]})["token"]
tok = {u: login(u) for u in ("admision", "medico", "reportero")}
doc, nac = f"VW{int(time.time())}", "1985-03-12"
pedir("/pacientes", {"cod_tipo_documento": "CC", "numero_documento": doc, "primer_nombre": "Vista", "primer_apellido": "Prueba", "fecha_hora_nacimiento": nac + "T08:00:00",
                     "cod_sexo": "M", "cod_pais_nacionalidad": "COL", "cod_pais_residencia": "COL", "cod_municipio_residencia": "70001", "cod_etnia": "06", "cod_zona_territorial": "1"}, tok["admision"])
pid = pedir(f"/pacientes/buscar?cod_tipo_documento=CC&numero_documento={doc}", tok=tok["admision"])["pacientes"][0]["id_paciente"]
enc = pedir("/encuentros", {"id_paciente": pid, "fecha_hora_inicio": "2026-11-07T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01", "cod_entorno": "01",
                            "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"}, tok["admision"])["encuentro"]["id_encuentro"]
pedir(f"/encuentros/{enc}/diagnosticos", {"cod_cie10": "I10", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-07"}, tok["medico"])
paciente = pedir("/auth/paciente", {"cod_tipo_documento": "CC", "numero_documento": doc, "fecha_nacimiento": nac})["token"]
pedir(f"/reporte-hc/{doc}?cod_tipo_documento=CC", tok=tok["reportero"])          # deja un acceso del reportero visible para el paciente
with open(salida, "w") as f:
    for k, v in {"TOK_REPORTERO": tok["reportero"], "TOK_ADMISION": tok["admision"], "TOK_MEDICO": tok["medico"], "TOK_PACIENTE": paciente, "DOC": doc, "BASE": base}.items():
        f.write(f"{k}={v}\n")
PY
docker run --rm "${RED[@]}" --env-file "$ENV" -e NODE_EXTRA_CA_CERTS=/ca.crt -v "$PWD/credenciales/ca.crt":/ca.crt:ro \
    -v "$PWD/tests/e2e/vistas_jsdom.mjs":/s/vistas.mjs:ro -v "$PWD/app/hc_api/static":/static:ro -w /work node:20-alpine \
    sh -c 'mkdir -p /work && cd /work && cp /s/vistas.mjs . && npm i --no-audit --no-fund --silent jsdom >/dev/null 2>&1 && node vistas.mjs'
