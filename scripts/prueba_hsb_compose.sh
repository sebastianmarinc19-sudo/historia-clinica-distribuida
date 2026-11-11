#!/usr/bin/env bash
# Contrato del HSB en Docker Compose (gateway https://localhost:8443): los 4 ejemplos del parcial y el reenvío duplicado.
# La caída de HAPI con reintentos y mensajes muertos se prueba con scripts/prueba_hsb_vivo.sh (Kubernetes) y con scripts/prueba_hsb.sh (integración).
set -euo pipefail
cd "$(dirname "$0")/.."
G="https://localhost:8443"; CA=credenciales/ca.crt
FALLOS=0
ok() { printf '  OK    %s\n' "$*"; }
mal() { printf '  FALLA %s\n' "$*"; FALLOS=$((FALLOS + 1)); }
clave() { python3 -c "import json,sys;print(json.load(open('credenciales/credenciales.json'))['usuarios'][sys.argv[1]]['clave'])" "$1"; }
json() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
token() { curl -s --cacert "$CA" -X POST -H 'content-type: application/json' -d "{\"usuario\":\"$1\",\"clave\":\"$(clave "$1")\"}" "$G/api/v2/auth/login" | json "d['token']"; }
TS=$(token sede); TM=$(token medico)
# Prueba de laboratorio repetible: se vacía la cola del bus (si no, los mensajes de la corrida anterior responderían «duplicado»)
docker exec pg_hsb psql -U hsb -d hsb -qc "TRUNCATE mensaje_bus CASCADE" >/dev/null 2>&1
hl7() { curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @"$1" "$G/hsb/hl7"; }
esperar_entregado() {  # id: HAPI puede tardar en responder la primera vez; el bus lo entrega solo
  for _ in $(seq 1 90); do
    [ "$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes/$1" | json "d['estado']" 2>/dev/null)" = entregado ] && return 0; sleep 3
  done; return 1; }

for f in 01_adt_a01_valido_sede2 02_oru_r01_laboratorio_sede1; do
  R=$(hl7 "ejemplos/$f.hl7")
  est=$(echo "$R" | json "d['estado']")
  if [ "$est" = entregado ] || { [ "$est" = reintentando ] && esperar_entregado "$(echo "$R" | json "d['id_mensaje']")"; }; then ok "$f: entregado"; else mal "$f: $R"; fi
done
R=$(hl7 ejemplos/03_adt_a01_invalido.hl7)
[ "$(echo "$R" | json "d['estado'], len(d['motivos'])")" = "rechazado 3" ] && ok "03_adt_a01_invalido: rechazado con 3 motivos" || mal "03: $R"
R=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @ejemplos/04_sede3_legado.csv "$G/hsb/csv?sede=3")
[ "$(echo "$R" | json "d['por_estado'].get('rechazado')")" = 2 ] && ok "04_sede3_legado.csv: 2 rechazadas (3 entregadas o en cola)" || mal "04: $R"
R=$(hl7 ejemplos/01_adt_a01_valido_sede2.hl7)
[ "$(echo "$R" | json "d['estado']")" = duplicado ] && ok "reenvío de 01: duplicado" || mal "reenvío: $R"
# Una sede cae: el mensaje espera en la cola del bus y, al volver la sede, se entrega sin duplicar
echo "-- sede 3 caída: el mensaje espera y se entrega al volver"
ID="MSG-S3-$(date +%H%M%S)"
docker stop api_corozal >/dev/null
R=$(sed -e "s/SEDE2/SEDE3/g" -e "s/MSG-0001/$ID/g" -e "s/1007/2007/g" -e "s/V-S2-0101/V-S3-$ID/g" ejemplos/01_adt_a01_valido_sede2.hl7 | curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @- "$G/hsb/hl7")
IDM=$(echo "$R" | json "d['id_mensaje']")
[ "$(echo "$R" | json "d['estado']")" = reintentando ] && ok "con la sede 3 caída el mensaje queda reintentando" || mal "esperaba reintentando: $R"
docker start api_corozal >/dev/null
esperar_entregado "$IDM" && ok "al volver la sede 3 el mensaje se entregó" || mal "no se entregó: $(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes/$IDM" | json "d['estado']")"
N=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/sede/3/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=2007" | json "sum(1 for p in d['pacientes'] if p['_id_sede'] == 3)" 2>/dev/null || echo "?")
[ "$N" = 1 ] && ok "el paciente 2007 existe una sola vez en la sede 3" || mal "paciente 2007: $N registros"
[ $FALLOS -eq 0 ] && echo "HSB en Compose: contrato en orden" || { echo "$FALLOS fallo(s)"; exit 1; }
