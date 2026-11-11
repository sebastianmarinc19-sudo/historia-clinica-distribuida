#!/usr/bin/env bash
# Valida con el validador de HAPI (`Bundle/$validate`, R4) los Bundles de fhir/ejemplos y resume el OperationOutcome.
#
#   bash fhir/validar.sh                          # contra el HAPI de Sincelejo en Docker Compose (http://localhost:8081/fhir)
#   bash fhir/validar.sh http://IP:PUERTO/fhir    # otro HAPI
#   bash fhir/validar.sh --solo-errores           # imprime solo los errores (para CI)
#
# Sale con código 1 si algún Bundle tiene errores (`error` o `fatal`); las advertencias se cuentan pero no fallan.
# Ojo: el validador necesita memoria; con JAVA_TOOL_OPTIONS de 400 MB (docker-compose.yml) puede responder 500 u OOM en Bundles grandes.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="http://localhost:8081/fhir"; SOLO=0
for a in "$@"; do case "$a" in --solo-errores) SOLO=1 ;; http*) BASE="$a" ;; *) echo "opción desconocida: $a"; exit 2 ;; esac; done
FALLOS=0
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
for f in fhir/ejemplos/01_adt_a01_transaction.json fhir/ejemplos/02_oru_r01_transaction.json fhir/ejemplos/04_csv_sede3_transaction.json fhir/ejemplos/rda_document.json fhir/ejemplos/rda_transaction.json fhir/ejemplos/auditevent_bundle.json; do
  curl -s -m 180 -o "$TMP" -X POST -H 'Content-Type: application/fhir+json' --data-binary @"$f" "$BASE/Bundle/\$validate" || true
  python3 - "$f" "$SOLO" "$TMP" <<'PY' || FALLOS=$((FALLOS + 1))
import json, sys
archivo, solo, respuesta = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
try:
    oo = json.load(open(respuesta, encoding="utf-8"))
except ValueError:
    print(f"  FALLA {archivo}: el servidor no devolvió un OperationOutcome"); sys.exit(1)
if oo.get("resourceType") != "OperationOutcome":
    print(f"  FALLA {archivo}: respuesta inesperada ({oo.get('resourceType')})"); sys.exit(1)
issues = oo.get("issue", [])
cuenta = {}
for i in issues: cuenta[i["severity"]] = cuenta.get(i["severity"], 0) + 1
errores = cuenta.get("error", 0) + cuenta.get("fatal", 0)
if not solo or errores:
    print(f"  {'OK   ' if not errores else 'FALLA'} {archivo}: {cuenta or 'sin observaciones'}")
for i in issues:
    if i["severity"] in ("error", "fatal") or (not solo and i["severity"] == "warning"):
        print(f"      {i['severity']}: {i.get('diagnostics') or i.get('details', {}).get('text', '')} @ {', '.join(i.get('expression', []))[:90]}")
sys.exit(1 if errores else 0)
PY
done
[ "$FALLOS" -eq 0 ] && echo "Validación FHIR: sin errores" || { echo "Validación FHIR: $FALLOS Bundle(s) con errores"; exit 1; }
