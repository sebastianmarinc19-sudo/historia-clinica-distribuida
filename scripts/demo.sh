#!/usr/bin/env bash
# Guion único de la demostración (la lista de verificación de la guía del parcial), con curl y los archivos de ejemplo sin modificar.
#
#   docker compose down -v && docker compose up -d --build     # desde cero
#   bash scripts/demo.sh                                       # paso a paso: Enter para continuar
#   bash scripts/demo.sh --sin-pausas                          # de corrido (lo usa el CI)
#   bash scripts/demo.sh k8s                                   # contra Minikube (https://IP:30443)
#   bash scripts/demo.sh --reiniciar                           # antes vacía la cola del bus (solo laboratorio): sin esto, repetir la demo responde «duplicado»
#
# Pasos: 1 un HL7 ADT y un HL7 ORU llegan como FHIR · 2 un mensaje inválido se rechaza con sus motivos · 3 un CSV legado (3 entregadas y 2 rechazadas)
#        4 reenviar un mensaje no crea duplicados · 5 Reporte de HC de un paciente con registros en las 3 sedes · 6 apagar una sede no detiene la vista
#        unificada y la marca como no disponible · 7 el verificador detecta una fila de auditoría alterada, borrada, la cadena reescrita entera y su cabeza truncada.
# Las claves salen de credenciales/ y no se imprimen. Los datos son sintéticos.
set -euo pipefail
cd "$(dirname "$0")/.."

PAUSAS=1; MODO=compose; REINICIAR=0
for a in "$@"; do case "$a" in --sin-pausas) PAUSAS=0 ;; --reiniciar) REINICIAR=1 ;; k8s|compose) MODO=$a ;; *) echo "opción desconocida: $a"; exit 2 ;; esac; done
if [ "$MODO" = k8s ]; then G="https://$(minikube ip):30443"; else G="https://localhost:8443"; fi
CA=credenciales/ca.crt
python3 scripts/credenciales.py >/dev/null
FALLOS=0
paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; if [ "$PAUSAS" -eq 1 ]; then read -r -p "   [Enter para ejecutar] " _; fi; }
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
mal() { printf '  \033[31mFALLA\033[0m %s\n' "$*"; FALLOS=$((FALLOS + 1)); }
clave() { python3 -c "import json,sys;print(json.load(open('credenciales/credenciales.json'))['usuarios'][sys.argv[1]]['clave'])" "$1"; }
json() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
token() { curl -s --cacert "$CA" -X POST -H 'content-type: application/json' -d "{\"usuario\":\"$1\",\"clave\":\"$(clave "$1")\"}" "$G/sede/1/api/v2/auth/login" | json "d['token']"; }
get() { curl -s --cacert "$CA" -H "Authorization: Bearer $1" "$G$2"; }       # token, ruta
esperar_estado() {  # token, id, estado, segundos: el HAPI puede tardar en responder la primera vez
  local limite=$((SECONDS + $4))
  while [ $SECONDS -lt $limite ]; do [ "$(get "$1" "/hsb/mensajes/$2" | json "d['estado']" 2>/dev/null)" = "$3" ] && return 0; sleep 3; done; return 1; }

if [ "$REINICIAR" -eq 1 ]; then
  if [ "$MODO" = k8s ]; then kubectl -n hc-hsb exec pg-hsb-0 -- psql -U hsb -d hsb -qc "TRUNCATE mensaje_bus CASCADE" >/dev/null
  else docker exec pg_hsb psql -U hsb -d hsb -qc "TRUNCATE mensaje_bus CASCADE" >/dev/null; fi
fi
paso "0. El sistema responde (gateway, sedes y bus)"
curl -s --cacert "$CA" "$G/health" | grep -q ok && ok "gateway: /health" || mal "el gateway no responde"
TS=$(token sede); TM=$(token medico); TR=$(token auditor)
for s in 1 2 3; do [ "$(curl -s --cacert "$CA" -o /dev/null -w '%{http_code}' "$G/sede/$s/api/health/live")" = 200 ] && ok "sede $s: /api/health/live" || mal "la sede $s no responde"; done
[ "$(curl -s --cacert "$CA" -o /dev/null -w '%{http_code}' "$G/hsb/health")" = 200 ] && ok "bus: /hsb/health" || mal "el bus no responde"

hl7() { curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @"$1" "$G/hsb/hl7"; }
paso "1. Un mensaje HL7 v2 ADT y uno ORU llegan como FHIR (al HAPI y a la API de la sede)"
for f in 01_adt_a01_valido_sede2 02_oru_r01_laboratorio_sede1; do
  r=$(hl7 ejemplos/$f.hl7); id=$(echo "$r" | json "d.get('id_mensaje','')"); e=$(echo "$r" | json "d['estado']")
  if [ "$e" != entregado ] && [ -n "$id" ]; then esperar_estado "$TM" "$id" entregado 240 && e=entregado; fi
  [ "$e" = entregado ] && ok "$f: entregado (Patient, Encounter y Condition u Observation, en la sede que corresponde)" || mal "$f: $e"
done

paso "2. Un mensaje inválido se rechaza con sus motivos y no escribe nada"
r=$(hl7 ejemplos/03_adt_a01_invalido.hl7)
[ "$(echo "$r" | json "d['estado']")" = rechazado ] && ok "03_adt_a01_invalido: rechazado" || mal "el inválido no fue rechazado: $r"
echo "$r" | json "'\n'.join('     - ' + m for m in d.get('motivos', []))"

paso "3. Un CSV legado de la sede 3: filas válidas se entregan y las inválidas se rechazan"
r=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @ejemplos/04_sede3_legado.csv "$G/hsb/csv?sede=3")
echo "$r" | json "'     filas: %s · por estado: %s' % (d['filas'], d['por_estado'])"
[ "$(echo "$r" | json "d['por_estado'].get('rechazado', 0)")" -ge 2 ] && ok "las filas inválidas se rechazaron" || mal "esperaba 2 filas rechazadas"

paso "4. Reenviar un mensaje no crea duplicados"
r=$(hl7 ejemplos/01_adt_a01_valido_sede2.hl7)
[ "$(echo "$r" | json "d['estado']")" = duplicado ] && ok "reenvío de 01: duplicado (no se crea otro paciente ni otro encuentro)" || mal "el reenvío no fue duplicado: $r"
get "$TM" /hsb/resumen | json "'     bus: %s mensajes · %s duplicados detectados · %s %% fallidos' % (d['total'], d['duplicados_detectados'], d['porcentaje_fallidos'])"

paso "5. El Reporte de HC se genera para un paciente con registros en las 3 sedes (7000001, datos sintéticos)"
if [ "$MODO" = k8s ]; then python3 scripts/datos_demo.py --k8s >/dev/null; else python3 scripts/datos_demo.py >/dev/null; fi
r=$(get "$TR" "/sede/1/api/v2/reporte-hc/7000001?cod_tipo_documento=CC")
echo "$r" | json "'\n'.join('     %s: %s encuentro(s) · %s de %s campos completos' % (s['sede'], len(s['encuentros']), (s['cobertura'] or {}).get('resumen', {}).get('completo', '-'), (s['cobertura'] or {}).get('total', '-')) for s in d['contenido']['sedes'])"
[ "$(echo "$r" | json "sum(1 for s in d['contenido']['sedes'] if s['encuentros'])")" = 3 ] && ok "tiene encuentros en las tres sedes" || mal "no tiene encuentros en las tres sedes"
echo "$r" | json "'     sello SHA-256: ' + d['sello_sha256']"

paso "6. Se apaga una sede (Cartagena): la vista unificada sigue y la marca como no disponible"
bash scripts/nodo.sh apagar 2 "$MODO" >/dev/null
for _ in $(seq 1 20); do   # la sede aparece como no disponible cuando su réplica deja de responder (segundos)
  r=$(get "$TR" "/sede/1/api/v2/estado-plataforma")
  [ "$(echo "$r" | json "[s['estado'] for s in d['sedes'] if s['id_sede'] == 2][0]")" = no_responde ] && break
  sleep 3
done
echo "$r" | json "'     ' + ' · '.join('%s: %s' % (s['sede'], s['estado']) for s in d['sedes'])"
[ "$(echo "$r" | json "[s['estado'] for s in d['sedes'] if s['id_sede'] == 2][0]")" = no_responde ] && ok "Cartagena aparece como «no responde»" || mal "Cartagena no aparece como no disponible"
h=$(get "$TM" "/sede/1/api/v2/historia-federada/7000001?cod_tipo_documento=CC")
[ "$(echo "$h" | json "d.get('total_encuentros', 0)")" -ge 3 ] && ok "la historia unificada de 7000001 sigue respondiendo con sus 3 encuentros (desde la copia local)" || mal "la historia unificada no respondió completa"
r=$(get "$TR" "/sede/1/api/v2/reporte-hc/7000001?cod_tipo_documento=CC")
echo "$r" | json "'     aviso del reporte: ' + str(d['aviso'])"
[ "$(echo "$r" | json "d['completo']")" = False ] && ok "el Reporte de HC advierte que Cartagena no respondió y usa su última copia" || mal "el Reporte de HC no advirtió de la sede caída"
bash scripts/nodo.sh encender 2 "$MODO" >/dev/null
echo "     (Cartagena encendida: se pone al día sola)"

paso "7. El verificador de integridad detecta una fila de auditoría alterada"
if bash scripts/prueba_auditoria.sh "$MODO" >/tmp/demo_auditoria.log 2>&1; then ok "alterar, borrar, reescribir toda la cadena y truncar su cabeza se detecta (los dos últimos por el anclaje en otras sedes), y la cadena se restaura"; else mal "la prueba de alteración falló (véase /tmp/demo_auditoria.log)"; fi
grep -E "detectado" /tmp/demo_auditoria.log | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^/     /'

printf '\n'
[ "$FALLOS" -eq 0 ] && echo "Demostración: todo en orden" || { echo "Demostración: $FALLOS paso(s) con fallo"; exit 1; }
