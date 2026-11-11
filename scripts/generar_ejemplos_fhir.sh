#!/usr/bin/env bash
# Regenera los Bundles de ejemplo de fhir/ con el MISMO código que usa el sistema (no se escriben a mano):
#   fhir/ejemplos/01_adt_a01_transaction.json   mensaje HL7 ADT^A01 del parcial -> Bundle `transaction` del HSB (PUT con ids deterministas)
#   fhir/ejemplos/02_oru_r01_transaction.json   mensaje HL7 ORU^R01 (hemoglobina 13,8 g/dL, LOINC 718-7)
#   fhir/ejemplos/04_csv_sede3_transaction.json primera fila válida del CSV legado de la sede 3 (diagnóstico local -> CIE-10)
#   fhir/ejemplos/dx_local_conceptmap.json      ConceptMap diagnóstico local -> CIE-10
#   fhir/ejemplos/rda_document.json             RDA (Bundle `document`) de un encuentro sintético, como lo genera la API
#   fhir/ejemplos/rda_transaction.json          los mismos recursos como recursos PROPIOS de HAPI (Bundle `transaction`, PUT con ids deterministas)
# Solo necesita Docker (usa las imágenes hc-hsb:local y hc-api:local, que construye si faltan).
set -euo pipefail
cd "$(dirname "$0")/.."
docker image inspect hc-hsb:local >/dev/null 2>&1 || docker build -q -t hc-hsb:local hsb >/dev/null
docker image inspect hc-api:local >/dev/null 2>&1 || docker build -q -t hc-api:local app >/dev/null
mkdir -p fhir/ejemplos

docker run -i --rm -u "$(id -u):$(id -g)" -v "$PWD/ejemplos":/ejemplos:ro -v "$PWD/hsb/datos":/app/datos:ro -v "$PWD/fhir/ejemplos":/out -w /app hc-hsb:local python - <<'PY'
import csv, json
from hc_hsb import csvlegado, fhir, normalizador as nz

def guardar(nombre, datos):
    with open(f"/out/{nombre}", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2); f.write("\n")

for archivo, salida in (("01_adt_a01_valido_sede2.hl7", "01_adt_a01_transaction.json"), ("02_oru_r01_laboratorio_sede1.hl7", "02_oru_r01_transaction.json")):
    n = nz.normalizar_hl7(open(f"/ejemplos/{archivo}", encoding="utf-8").read())
    assert n.canonico is not None, n.motivos
    guardar(salida, fhir.construir_bundle(n.canonico))

filas = list(csv.DictReader(open("/app/datos/ref_terminologia.csv", encoding="utf-8"), delimiter=";"))
tabla = {nz.clave_terminologia(f["dx_local"]): f for f in filas}
guardar("dx_local_conceptmap.json", fhir.conceptmap(filas))
for numero, fila in csvlegado.leer(open("/ejemplos/04_sede3_legado.csv", encoding="utf-8").read()):
    n = nz.normalizar_fila_csv(3, numero, fila, tabla)
    if n.canonico is not None:
        guardar("04_csv_sede3_transaction.json", fhir.construir_bundle(n.canonico))
        break
PY

docker run -i --rm -u "$(id -u):$(id -g)" -v "$PWD/app":/app -v "$PWD/tests/api":/app/tests -v "$PWD/fhir/ejemplos":/out -e PYTHONDONTWRITEBYTECODE=1 -w /app hc-api:local python - <<'PY'
import json, sys
sys.path.insert(0, "/app/tests")
from hc_api import fhir
from test_unitarias import _datos_rda
datos = _datos_rda()
for nombre, bundle in (("rda_document.json", fhir.construir_rda(datos)), ("rda_transaction.json", fhir.construir_transaccion(datos))):
    with open("/out/" + nombre, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2); f.write("\n")
PY
ls -1 fhir/ejemplos
