#!/usr/bin/env bash
# Prueba de alteración de la auditoría encadenada por hash, de punta a punta sobre una sede real.
#
#   bash scripts/prueba_auditoria.sh            # Docker Compose (gateway https://localhost:8443), sede 1
#   bash scripts/prueba_auditoria.sh k8s        # Kubernetes/Minikube (gateway https://IP:30443), sede 1
#
# Guion: se hace una escritura y se guarda su sello · la cadena verifica · se ALTERA un evento a mano en la base (UPDATE como
# superusuario, desactivando el disparador de solo anexar) · el verificador señala exactamente ese evento · se restaura el valor ·
# la cadena vuelve a verificar. Luego lo mismo con un evento BORRADO (salto de secuencia). Después los dos ataques que la cadena sola NO ve y
# el ANCLAJE en las otras sedes sí: reescribir toda la cadena con hashes recalculados y borrar los últimos eventos. Deja la cadena como estaba.
# Entra con las cuentas de laboratorio (credenciales/, no se imprimen). Solo para laboratorio: toca la base de la sede 1.
set -euo pipefail
cd "$(dirname "$0")/.."

MODO=${1:-compose}
case "$MODO" in
  compose) G="https://localhost:8443"; METRICAS="http://localhost:8101/metrics"; EN_API() { docker exec -i api_sincelejo python - "$@"; }; SQL() { docker exec -i pg_sincelejo psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -qtA; } ;;
  k8s)     METRICAS=""; G="https://$(minikube ip):30443"; EN_API() { kubectl -n sede-sincelejo exec -i deploy/api -- python - "$@"; }; SQL() { kubectl -n sede-sincelejo exec -i pg-0 -- psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -qtA; } ;;
  *) echo "uso: $0 [compose|k8s]"; exit 2 ;;
esac
CA=credenciales/ca.crt
FALLOS=0
paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
mal() { printf '  \033[31mFALLA\033[0m %s\n' "$*"; FALLOS=$((FALLOS + 1)); }
clave() { python3 -c "import json,sys;print(json.load(open('credenciales/credenciales.json'))['usuarios'][sys.argv[1]]['clave'])" "$1"; }
json() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
token() { curl -s --cacert "$CA" -X POST -H 'content-type: application/json' -d "{\"usuario\":\"$1\",\"clave\":\"$(clave "$1")\"}" "$G/sede/1/api/v2/auth/login" | json "d['token']"; }
TA=$(token admision); TR=$(token reportero)
verificar() { curl -s --cacert "$CA" -H "Authorization: Bearer $TR" "$G/sede/1/api/v2/auditoria/verificar"; }
# Modifica la tabla saltándose el disparador de solo anexar (lo que haría alguien con acceso de superusuario a la base).
alterar() { { echo "SET session_replication_role = replica;"; cat; } | SQL >/dev/null; }

paso "1. Una escritura devuelve su sello"
DOC="AUD$(date +%s)"
CUERPO=$(python3 - "$DOC" <<'EOF'
import json, sys
print(json.dumps({"cod_tipo_documento": "CC", "numero_documento": sys.argv[1], "primer_nombre": "Prueba", "primer_apellido": "Auditoria",
                  "fecha_hora_nacimiento": "1980-01-01T08:00:00", "cod_sexo": "F", "cod_pais_residencia": "COL",
                  "cod_municipio_residencia": "70001", "cod_etnia": "06", "oposicion_donacion": False}))
EOF
)
SELLO=$(curl -s --cacert "$CA" -D - -o /dev/null -X POST -H "Authorization: Bearer $TA" -H 'content-type: application/json' -d "$CUERPO" \
          "$G/sede/1/api/v2/pacientes" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-sello-auditoria"{print $2}')
if [[ "$SELLO" =~ ^[0-9]+:[0-9a-f]{64}$ ]]; then ok "sello recibido: evento ${SELLO%%:*}, hash ${SELLO#*:}"; else mal "la escritura no devolvió sello ($SELLO)"; fi
SEQ=${SELLO%%:*}

paso "2. La cadena íntegra verifica"
sleep 1
V=$(verificar)
[ "$(echo "$V" | json "d['ok']")" = True ] && ok "cadena íntegra: $(echo "$V" | json "d['verificados']") eventos, cabeza ≥ $SEQ" || mal "la cadena debía verificar: $V"

paso "3. Se altera el evento $SEQ en la base (el documento que consultó)"
ORIGINAL=$(echo "SELECT coalesce(usuario,'') FROM evento_auditoria WHERE seq = $SEQ;" | SQL)
echo "UPDATE evento_auditoria SET usuario = 'otra_persona' WHERE seq = $SEQ;" | alterar
V=$(verificar)
if [ "$(echo "$V" | json "d['ok']")" = False ] && [ "$(echo "$V" | json "d['primer_fallo']['seq']")" = "$SEQ" ]; then
  ok "detectado en el evento $SEQ: $(echo "$V" | json "d['primer_fallo']['motivo']")"
else mal "la alteración no se detectó en el evento $SEQ: $V"; fi
if [ -n "$METRICAS" ]; then
  M=$(curl -s "$METRICAS" | grep -E '^hc_auditoria_cadena_ok' || true)
  [[ "$M" == *" 0.0" ]] && ok "métrica de la sede: $M" || mal "la métrica debía quedar en 0: $M"
fi

paso "4. Se restaura el valor y la cadena vuelve a verificar"
echo "UPDATE evento_auditoria SET usuario = '$ORIGINAL' WHERE seq = $SEQ;" | alterar
[ "$(verificar | json "d['ok']")" = True ] && ok "cadena restaurada" || mal "la cadena no volvió a verificar tras restaurar"

paso "5. Un evento borrado se detecta por el salto de secuencia"
# se escribe otra vez para tener un evento posterior y se borra el del medio
curl -s --cacert "$CA" -o /dev/null -X POST -H "Authorization: Bearer $TA" -H 'content-type: application/json' -d "$CUERPO" "$G/sede/1/api/v2/pacientes"
sleep 1
FILA=$(echo "SELECT seq||'|'||instante::text||'|'||id_sede||'|'||coalesce(usuario,'')||'|'||coalesce(rol,'')||'|'||metodo||'|'||ruta||'|'||coalesce(documento,'')||'|'||estado||'|'||coalesce(ip,'')||'|'||hash_previo||'|'||hash FROM evento_auditoria WHERE seq = $SEQ;" | SQL)
echo "DELETE FROM evento_auditoria WHERE seq = $SEQ;" | alterar
V=$(verificar)
if [ "$(echo "$V" | json "d['ok']")" = False ] && [ "$(echo "$V" | json "d['primer_fallo']['seq']")" = "$((SEQ + 1))" ]; then
  ok "detectado: $(echo "$V" | json "d['primer_fallo']['motivo']")"
else mal "el borrado no se detectó: $V"; fi
IFS='|' read -r S I SE U R M RU DO ES IP HP H <<<"$FILA"
echo "INSERT INTO evento_auditoria (seq, instante, id_sede, usuario, rol, metodo, ruta, documento, estado, ip, hash_previo, hash)
      VALUES ($S, '$I', $SE, NULLIF('$U',''), NULLIF('$R',''), '$M', '$RU', NULLIF('$DO',''), $ES, NULLIF('$IP',''), '$HP', '$H');" | alterar
[ "$(verificar | json "d['ok']")" = True ] && ok "evento reinsertado: cadena restaurada" || mal "la cadena no volvió a verificar tras reinsertar"

paso "6. La aplicación no puede alterar la cadena con su propia cuenta de base"
SALIDA=$(echo "UPDATE evento_auditoria SET estado = 200 WHERE seq = $SEQ;" | SQL 2>&1 || true)
if [[ "$SALIDA" == *"solo anexar"* ]]; then
  ok "el disparador rechaza el UPDATE normal (hay que ser superusuario y desactivarlo para alterar)"
else mal "el UPDATE normal no fue rechazado por el disparador"; fi

paso "7. Reescribir TODA la cadena con hashes recalculados: la cadena sola no lo ve, el anclaje en las otras sedes sí"
# se espera a que las otras sedes tengan anclada una cabeza que cubra el evento $SEQ (el anclaje corre cada 10 s)
ANCLA=0
for _ in $(seq 1 30); do
  ANCLA=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TR" "$G/sede/2/api/v2/auditoria/anclas/1?limite=1" | json "(d['anclas'] or [{'seq': 0}])[0]['seq']" 2>/dev/null || echo 0)
  [ "$ANCLA" -ge "$SEQ" ] && break; sleep 2
done
[ "$ANCLA" -ge "$SEQ" ] && ok "la sede 2 tiene anclada la cabeza $ANCLA de la sede 1" || mal "la sede 2 no recibió el anclaje de la sede 1"
V=$(verificar)
[ "$(echo "$V" | json "d['anclaje']['ok']")" = True ] && ok "antes del ataque el anclaje coincide en las dos sedes pares" || mal "el anclaje debía coincidir antes del ataque: $V"
echo "CREATE TABLE evento_auditoria_respaldo AS SELECT * FROM evento_auditoria WHERE seq >= $SEQ;" | SQL >/dev/null
# El atacante cambia el evento $SEQ y recalcula todos los hashes siguientes con la misma función de la aplicación (necesita ser superusuario de la base).
EN_API "$SEQ" <<'PY'
import sys
from hc_api import auditoria, db
seq0 = int(sys.argv[1])
with db.conexion() as conn:
    db.ejecutar("SET session_replication_role = replica", conn=conn)
    previo = db.uno("SELECT hash FROM evento_auditoria WHERE seq = %s", (seq0 - 1,), conn)
    previo = previo["hash"].strip() if previo else auditoria.hash_genesis(1)
    for f in db.consultar("SELECT * FROM evento_auditoria WHERE seq >= %s ORDER BY seq", (seq0,), conn):
        if f["seq"] == seq0:
            f["usuario"] = "otra_persona"
        f["hash_previo"] = previo
        f["hash"] = auditoria.calcular_hash(previo, f)
        previo = f["hash"]
        db.ejecutar("UPDATE evento_auditoria SET usuario = %s, hash_previo = %s, hash = %s WHERE seq = %s", (f["usuario"], f["hash_previo"], f["hash"], f["seq"]), conn)
PY
V=$(verificar)
[ "$(echo "$V" | json "d['cadena_local_ok']")" = True ] && ok "la cadena local, recalculada, cuadra consigo misma (el límite que se conocía)" || mal "la cadena reescrita debía cuadrar localmente: $V"
if [ "$(echo "$V" | json "d['ok']")" = False ] && [ "$(echo "$V" | json "d['anclaje']['ok']")" = False ]; then
  ok "detectado por el anclaje: $(echo "$V" | json "[p['detalle'] for p in d['anclaje']['pares'] if p['estado'] == 'discrepancia'][0]")"
else mal "la reescritura completa no se detectó: $V"; fi
echo "UPDATE evento_auditoria e SET usuario = r.usuario, hash_previo = r.hash_previo, hash = r.hash FROM evento_auditoria_respaldo r WHERE e.seq = r.seq;" | alterar
echo "DROP TABLE evento_auditoria_respaldo;" | SQL >/dev/null
V=$(verificar)
[ "$(echo "$V" | json "d['ok']")" = True ] && ok "cadena original restaurada: cadena y anclaje vuelven a coincidir" || mal "no volvió a verificar tras restaurar: $V"

paso "8. Borrar los últimos eventos (truncar la cabeza): la cadena queda válida pero más corta que lo anclado"
ANCLA=$(curl -s --cacert "$CA" -H "Authorization: Bearer $TR" "$G/sede/2/api/v2/auditoria/anclas/1?limite=1" | json "d['anclas'][0]['seq']")
echo "CREATE TABLE evento_auditoria_respaldo AS SELECT * FROM evento_auditoria WHERE seq >= $ANCLA;" | SQL >/dev/null
echo "DELETE FROM evento_auditoria WHERE seq >= $ANCLA;" | alterar
V=$(verificar)
[ "$(echo "$V" | json "d['cadena_local_ok']")" = True ] && ok "la cadena truncada sigue siendo válida por sí sola" || mal "la cadena truncada debía cuadrar localmente: $V"
if [ "$(echo "$V" | json "d['ok']")" = False ] && echo "$V" | json "' '.join(p.get('detalle', '') for p in d['anclaje']['pares'])" | grep -q "truncada"; then
  ok "detectado por el anclaje: $(echo "$V" | json "[p['detalle'] for p in d['anclaje']['pares'] if p['estado'] == 'discrepancia'][0]")"
else mal "el truncamiento no se detectó: $V"; fi
echo "INSERT INTO evento_auditoria SELECT * FROM evento_auditoria_respaldo ORDER BY seq;" | alterar
echo "DROP TABLE evento_auditoria_respaldo;" | SQL >/dev/null
V=$(verificar)
[ "$(echo "$V" | json "d['ok']")" = True ] && ok "eventos devueltos: cadena y anclaje vuelven a coincidir" || mal "no volvió a verificar tras reinsertar: $V"

printf '\n'
[ "$FALLOS" -eq 0 ] && echo "Auditoría encadenada: todo en orden" || { echo "Auditoría encadenada: $FALLOS fallo(s)"; exit 1; }
