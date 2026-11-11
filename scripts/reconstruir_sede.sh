#!/usr/bin/env bash
# Reconstruye una sede que perdió su disco (base vacía) a partir de sus PARES.
#
#   bash scripts/reconstruir_sede.sh <sede>        sede: sincelejo | cartagena | corozal
#
# Precondición: el pod pg-0 de la sede ya arrancó con una base NUEVA (el StatefulSet ejecuta
# solo el esquema, las semillas y la publicación). El script aborta si la sede ya tiene
# pacientes (FORZAR=1 para continuar de todos modos).
#
# Por qué funciona: cada sede guarda una copia de las filas de las demás, así que las filas de
# la sede perdida se recuperan de sus pares. Pasos (el orden evita huecos y duplicados):
#   1. Detiene la API de la sede (no debe recibir escrituras mientras se reconstruye).
#   2. En cada par: elimina la suscripción rota hacia la sede y el slot huérfano de la sede.
#   3. En la sede: crea las suscripciones hacia los pares (copy_data = false). Desde este
#      instante cada par le envía lo que cambie.
#   4. Copia las filas existentes desde cada par con pg_dump --data-only
#      --on-conflict-do-nothing (sin claves foráneas ni disparadores: session_replication_role
#      = replica). Lo que ya llegó por la suscripción no se duplica.
#   5. En cada par: crea de nuevo la suscripción hacia la sede.
#   6. Verifica que la sede igualó a sus pares y vuelve a levantar la API.
#
# Límites (ver el documento): se pierde lo que la sede escribió y aún no había replicado al
# caer (el RPO); la base fhir_db de HAPI (no se replica) queda vacía: el RDA sigue disponible
# en composicion_bundle.bundle_json y se puede regenerar con POST /migracion/encuentro/{id};
# la identidad federada (derivada) se recalcula sola al consultar.
set -euo pipefail

SEDE="${1:?uso: reconstruir_sede.sh <sincelejo|cartagena|corozal>}"
SEDES=(sincelejo cartagena corozal)
TABLAS=(profesional_salud paciente encuentro triage egreso diagnostico_encuentro tecnologia_encuentro
        medicamento_prescrito entrega_tecnologia observacion antecedente_salud exposicion_riesgo composicion_bundle)
DESTINO="sede-$SEDE"
PARES=()
for s in "${SEDES[@]}"; do [ "$s" != "$SEDE" ] && PARES+=("$s"); done
[ "${#PARES[@]}" -eq 2 ] || { echo "Sede desconocida: $SEDE" >&2; exit 2; }

pg() { local ns="$1"; shift; kubectl -n "$ns" exec -i pg-0 -- psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -Atq "$@"; }
INICIO=$(date +%s)
paso() { printf '\n[%3ss] %s\n' "$(( $(date +%s) - INICIO ))" "$*"; }

CLAVE=$(kubectl -n "$DESTINO" get secret hc-secretos -o jsonpath='{.data.REPLICATION_PASSWORD}' | base64 -d)

crear_suscripcion() {   # <ns_donde_se_crea> <nombre> <host_publicador>
  pg "$1" -v sub="$2" \
     -v conn="host=$3 port=5432 dbname=historia_clinica user=replicator password=${CLAVE} connect_timeout=5" <<'SQL'
SELECT format('CREATE SUBSCRIPTION %I CONNECTION %L PUBLICATION pub_sede WITH (origin = none, copy_data = false)', :'sub', :'conn')
 WHERE NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = :'sub')
\gexec
SQL
}

paso "Comprobando que la base de $SEDE está vacía"
N=$(pg "$DESTINO" -c "SELECT count(*) FROM paciente")
if [ "$N" != "0" ] && [ "${FORZAR:-0}" != "1" ]; then
  echo "La sede $SEDE tiene $N pacientes: no parece haber perdido su disco. Abortando (FORZAR=1 para continuar)." >&2
  exit 2
fi

paso "1. Deteniendo la API de $SEDE"
kubectl -n "$DESTINO" scale deployment/api --replicas=0 >/dev/null
kubectl -n "$DESTINO" wait --for=delete pod -l app=api --timeout=120s >/dev/null 2>&1 || true

paso "2. Limpiando en los pares la suscripción rota y el slot huérfano"
for p in "${PARES[@]}"; do
  pg "sede-$p" <<SQL
DO \$\$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'sub_${p}_desde_${SEDE}') THEN
    EXECUTE 'ALTER SUBSCRIPTION sub_${p}_desde_${SEDE} DISABLE';
    EXECUTE 'ALTER SUBSCRIPTION sub_${p}_desde_${SEDE} SET (slot_name = NONE)';
    EXECUTE 'DROP SUBSCRIPTION sub_${p}_desde_${SEDE}';
  END IF;
END \$\$;
SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots
 WHERE slot_name = 'sub_${SEDE}_desde_${p}' AND NOT active;
SQL
  echo "   $p: limpio"
done

paso "3. Creando en $SEDE las suscripciones hacia sus pares"
for p in "${PARES[@]}"; do
  crear_suscripcion "$DESTINO" "sub_${SEDE}_desde_${p}" "pg.sede-${p}.svc.cluster.local"
  echo "   $SEDE <- $p"
done

paso "4. Copiando las filas existentes desde los pares"
ARGS=(); for t in "${TABLAS[@]}"; do ARGS+=(-t "$t"); done
for p in "${PARES[@]}"; do
  { echo "SET session_replication_role = replica;"
    kubectl -n "sede-$p" exec pg-0 -- pg_dump -U admin -d historia_clinica --data-only --column-inserts \
        --on-conflict-do-nothing --no-owner "${ARGS[@]}"
  } | kubectl -n "$DESTINO" exec -i pg-0 -- psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 -q -o /dev/null
  echo "   copiado desde $p"
done

paso "5. Recreando en los pares la suscripción hacia $SEDE"
for p in "${PARES[@]}"; do
  crear_suscripcion "sede-$p" "sub_${p}_desde_${SEDE}" "pg.sede-${SEDE}.svc.cluster.local"
  echo "   $p <- $SEDE"
done

paso "6. Verificando que $SEDE igualó a sus pares"
huella() {   # <ns> <corte> : conteos y huella de lo creado ANTES del corte (mismo instante en las tres sedes)
  pg "$1" -v corte="$2" <<'SQL'
WITH p AS (SELECT id_paciente FROM paciente WHERE creado_en < :'corte'::timestamp)
SELECT (SELECT count(*) FROM p) || '/' ||
       (SELECT count(*) FROM encuentro WHERE id_paciente IN (SELECT id_paciente FROM p)) || '/' ||
       (SELECT count(*) FROM diagnostico_encuentro d JOIN encuentro e USING (id_encuentro)
         WHERE e.id_paciente IN (SELECT id_paciente FROM p)) || '/' ||
       (SELECT count(*) FROM composicion_bundle b JOIN encuentro e USING (id_encuentro)
         WHERE e.id_paciente IN (SELECT id_paciente FROM p)) || '/' ||
       md5(coalesce((SELECT string_agg(id_paciente::text, ',' ORDER BY id_paciente) FROM p), ''));
SQL
}
IGUAL=0
for _ in $(seq 1 60); do
  # Corte fijo (5 s atrás) compartido por las tres consultas: con escrituras en curso, una ventana
  # que se mueve entre consulta y consulta nunca daría la misma huella en las tres sedes.
  CORTE=$(pg "$DESTINO" -c "SELECT (now() - interval '5 seconds')::timestamp::text")
  H0=$(huella "$DESTINO" "$CORTE"); IGUAL=1
  for p in "${PARES[@]}"; do [ "$(huella "sede-$p" "$CORTE")" = "$H0" ] || IGUAL=0; done
  [ "$IGUAL" = 1 ] && break
  sleep 1
done
echo "   $SEDE: $(huella "$DESTINO" "$CORTE" | cut -d/ -f1-4 | tr '/' ' ') (pacientes encuentros diagnósticos RDA; creados antes de $CORTE)"
for p in "${PARES[@]}"; do echo "   $p: $(huella "sede-$p" "$CORTE" | cut -d/ -f1-4 | tr '/' ' ')"; done

paso "Levantando de nuevo la API de $SEDE"
kubectl -n "$DESTINO" scale deployment/api --replicas=2 >/dev/null
kubectl -n "$DESTINO" rollout status deployment/api --timeout=180s >/dev/null

if [ "$IGUAL" = 1 ]; then
  paso "LISTO: $SEDE reconstruida y sincronizada con sus pares."
else
  paso "ATENCIÓN: $SEDE no igualó a sus pares en 60 s; revise las suscripciones." >&2
  exit 1
fi
