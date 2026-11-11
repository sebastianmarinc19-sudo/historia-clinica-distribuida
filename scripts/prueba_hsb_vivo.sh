#!/usr/bin/env bash
# Guion en vivo del HSB sobre Kubernetes con los archivos de ejemplo del parcial (ejemplos/, sin modificar):
#   contrato · duplicado · HAPI apagado con reintentos y entrega sin duplicar · mensaje muerto y reencolado.
#
#   bash scripts/prueba_hsb_vivo.sh              # todo el guion (~5 min: HAPI arranca en frío dos veces)
#   bash scripts/prueba_hsb_vivo.sh --reiniciar  # además vacía la cola del bus antes de empezar (solo laboratorio)
#   bash scripts/prueba_hsb_vivo.sh --sin-caida  # solo contrato y duplicado (rápido)
#   bash scripts/prueba_hsb_vivo.sh --hapi-real  # «apagar HAPI» parando su pod (la JVM arranca en frío: con poca RAM tarda 2 a 3 min)
#                                                # por defecto se le quita el acceso al servicio (sin endpoints): el bus ve lo mismo, y es repetible
#
# Entra por el gateway HTTPS con la cuenta del sistema legado (`sede`, rol sistema_sede); las claves salen de credenciales/ (no se imprimen).
set -euo pipefail
cd "$(dirname "$0")/.."

REINICIAR=0; CAIDA=1; REAL=0
for a in "$@"; do case "$a" in --reiniciar) REINICIAR=1 ;; --sin-caida) CAIDA=0 ;; --hapi-real) REAL=1 ;; *) echo "opción desconocida: $a"; exit 2 ;; esac; done

IP=$(minikube ip); G="https://$IP:30443"; CA=credenciales/ca.crt
FALLOS=0
paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
mal() { printf '  \033[31mFALLA\033[0m %s\n' "$*"; FALLOS=$((FALLOS + 1)); }
clave() { python3 -c "import json,sys;print(json.load(open('credenciales/credenciales.json'))['usuarios'][sys.argv[1]]['clave'])" "$1"; }
token() { curl -s --cacert "$CA" -X POST -H 'content-type: application/json' -d "{\"usuario\":\"$1\",\"clave\":\"$(clave "$1")\"}" "$G/api/v2/auth/login" \
            | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])"; }
json() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
TS=$(token sede); TM=$(token medico); TA=$(token admin)
enviar_hl7() { curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @- "$G/hsb/hl7"; }          # stdin -> respuesta JSON
variante() { sed "s/MSG-0002/$1/" ejemplos/02_oru_r01_laboratorio_sede1.hl7; }                                  # ORU con otro id de mensaje
estado() { curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes/$1" | json "d['estado']" 2>/dev/null || echo "?"; }      # "?" si el bus responde un 5xx (p. ej. reiniciándose)
esperar_estado() {  # id, estado esperado, segundos
  local limite=$((SECONDS + $3))
  while [ $SECONDS -lt $limite ]; do [ "$(estado "$1")" = "$2" ] && return 0; sleep 3; done
  return 1
}
n_obs_nodo() {      # observaciones con LOINC 718-7 del paciente 1001 en la sede 1
  local eid; eid=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/sede/1/api/v2/historia-federada/1001?cod_tipo_documento=CC" \
      | json "d['encuentros'][0]['id_encuentro']")
  curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/sede/1/api/v2/encuentros/$eid" | json "sum(1 for o in d['observaciones'] if o['cod_loinc']=='718-7')"
}
eventos() { curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes/$1" \
              | json "'\n'.join('     %s  intento %s  %s %s' % (e['fecha'][11:19], e['intento'], e['estado'], ('· '+e['detalle'][:70]) if e['detalle'] else '') for e in d['eventos'])"; }
hapi_apagar() { if [ $REAL -eq 1 ]; then kubectl -n sede-sincelejo scale deploy/hapi --replicas=0 >/dev/null
                else kubectl -n sede-sincelejo patch svc hapi -p '{"spec":{"selector":{"app":"hapi-apagado"}}}' >/dev/null; fi; sleep 3; }
hapi_encender() { if [ $REAL -eq 1 ]; then kubectl -n sede-sincelejo scale deploy/hapi --replicas=1 >/dev/null
                  else kubectl -n sede-sincelejo patch svc hapi -p '{"spec":{"selector":{"app":"hapi"}}}' >/dev/null; fi; }
restaurar() { kubectl -n hc-hsb set env deploy/hsb HSB_MAX_INTENTOS=12 HSB_BACKOFF_MAX_S- >/dev/null 2>&1 || true
              kubectl -n sede-sincelejo scale deploy/hapi --replicas=1 >/dev/null 2>&1 || true
              kubectl -n sede-sincelejo patch svc hapi -p '{"spec":{"selector":{"app":"hapi"}}}' >/dev/null 2>&1 || true; }
trap restaurar EXIT
restaurar; kubectl -n hc-hsb rollout status deploy/hsb --timeout=120s >/dev/null      # arranca siempre desde la configuración de referencia
esperar_cola() {  # espera a que no queden mensajes en reintento (lo entrega el sondeo del bus)
  local limite=$((SECONDS + $1))
  while [ $SECONDS -lt $limite ]; do
    [ "$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/resumen" | json "d['por_estado']['reintentando']" 2>/dev/null || echo 9)" = 0 ] && return 0; sleep 3
  done; return 1; }

if [ $REINICIAR -eq 1 ]; then
  paso "Vaciar la cola del bus (solo laboratorio)"
  kubectl -n hc-hsb exec pg-hsb-0 -- psql -U hsb -d hsb -qc "TRUNCATE mensaje_bus CASCADE" && ok "cola vacía"
fi

paso "1. Contrato de los ejemplos"
# Si HAPI tarda en responder (primera transacción tras un rato inactivo, equipo con poca RAM) el mensaje queda «reintentando» y el bus lo entrega solo.
verificar_entrega() {  # etiqueta, respuesta JSON
  local id est; est=$(echo "$2" | json "d['estado']"); id=$(echo "$2" | json "d['id_mensaje']")
  if [ "$est" = entregado ]; then ok "$1: entregado"
  elif [ "$est" = reintentando ] && esperar_estado "$id" entregado 300; then ok "$1: entregado tras reintentar (HAPI tardó en responder)"
  else mal "$1: $2"; fi; }
R=$(enviar_hl7 < ejemplos/01_adt_a01_valido_sede2.hl7); verificar_entrega "01 ADT válido (sede 2)" "$R"
R=$(enviar_hl7 < ejemplos/02_oru_r01_laboratorio_sede1.hl7); verificar_entrega "02 ORU (sede 1)" "$R"
R=$(enviar_hl7 < ejemplos/03_adt_a01_invalido.hl7)
[ "$(echo "$R" | json "d['estado'], len(d['motivos'])")" = "rechazado 3" ] && ok "03 inválido: rechazado con 3 motivos" || mal "03: $R"
echo "$R" | json "'\n'.join('       - '+m for m in d['motivos'])"
R=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TS" --data-binary @ejemplos/04_sede3_legado.csv "$G/hsb/csv?sede=3")
esperar_cola 120 || true
N=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes?sede=3&estado=entregado" | json "d['total']")
[ "$(echo "$R" | json "d['por_estado'].get('rechazado')")" = 2 ] && [ "$N" = 3 ] && ok "04 CSV (sede 3): 3 entregados y 2 rechazados" || mal "04: rechazados/entregados inesperados ($N entregados): $R"

paso "2. Idempotencia: reenviar el mismo mensaje"
R=$(enviar_hl7 < ejemplos/01_adt_a01_valido_sede2.hl7); [ "$(echo "$R" | json "d['estado']")" = duplicado ] && ok "01 reenviado: duplicado" || mal "01 reenviado: $R"
N=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/sede/2/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=1007" | json "d['total']")
[ "$N" = 1 ] && ok "el paciente 1007 existe una sola vez en la sede 2" || mal "paciente 1007 repetido: $N"

if [ $CAIDA -eq 1 ]; then
  paso "3. HAPI apagado durante el envío: reintentos y entrega sin duplicar"
  OBS0=$(n_obs_nodo)
  hapi_apagar
  ID1="MSG-V$(date +%H%M%S)"
  R=$(variante "$ID1" | enviar_hl7); ID=$(echo "$R" | json "d['id_mensaje']")
  [ "$(echo "$R" | json "d['estado']")" = reintentando ] && ok "con HAPI apagado el mensaje queda reintentando ($(echo "$R" | json "d['ultimo_error']"))" || mal "esperaba reintentando: $R"
  echo "     encendiendo HAPI…"; hapi_encender
  if esperar_estado "$ID" entregado 360; then ok "tras volver HAPI el mensaje terminó entregado"; else mal "no se entregó: $(estado "$ID")"; fi
  echo "     bitácora del mensaje:"; eventos "$ID"
  [ "$(n_obs_nodo)" = $((OBS0 + 1)) ] && ok "una sola observación nueva en el nodo (sin duplicar)" || mal "observaciones: antes $OBS0, ahora $(n_obs_nodo)"
  echo "     log del bus:"; kubectl -n hc-hsb logs -l app=hsb --tail=-1 2>/dev/null | grep "$ID1" | grep -E '"(reintentando|entregado)"' | cut -c1-170 | sed 's/^/     /' | head -6

  paso "4. Se agotan los intentos: mensaje muerto y reencolado"
  kubectl -n hc-hsb set env deploy/hsb HSB_MAX_INTENTOS=3 HSB_BACKOFF_MAX_S=2 >/dev/null; kubectl -n hc-hsb rollout status deploy/hsb --timeout=120s >/dev/null
  hapi_apagar
  ID2="MSG-M$(date +%H%M%S)"
  R=$(variante "$ID2" | enviar_hl7); ID=$(echo "$R" | json "d['id_mensaje']")
  if esperar_estado "$ID" muerto 60; then ok "agotados los intentos el mensaje quedó muerto ($(curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/mensajes/$ID" | json "d['intentos']") intentos)"; else mal "no llegó a muerto: $(estado "$ID")"; fi
  echo "     bitácora del mensaje:"; eventos "$ID"
  kubectl -n hc-hsb set env deploy/hsb HSB_MAX_INTENTOS=12 HSB_BACKOFF_MAX_S- >/dev/null; kubectl -n hc-hsb rollout status deploy/hsb --timeout=120s >/dev/null
  hapi_encender
  echo "     HAPI de vuelta… reencolando el mensaje muerto"
  curl -s --cacert "$CA" -H "Authorization: Bearer $TA" -X POST "$G/hsb/mensajes/$ID/reencolar" >/dev/null
  if esperar_estado "$ID" entregado 360; then ok "reencolado: el mensaje muerto terminó entregado"; else mal "reencolado no entregó: $(estado "$ID")"; fi
fi

paso "Resumen del bus"
curl -s --cacert "$CA" -H "Authorization: Bearer $TM" "$G/hsb/resumen" | json "d"
[ $FALLOS -eq 0 ] && { printf '\n\033[32mGuion del HSB: todo en orden\033[0m\n'; } || { printf '\n\033[31m%s fallo(s)\033[0m\n' "$FALLOS"; exit 1; }
