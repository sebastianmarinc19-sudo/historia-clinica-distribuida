#!/usr/bin/env bash
# Pruebas de replicación y tolerancia a fallos entre las 3 sedes.
# Requiere el entorno arriba:
#   docker compose -f docker-compose.yml up -d
#
# Escenarios:
#   T1  propagación: una escritura en cada sede llega a las otras dos
#   T2  cadena clínica (encuentro, diagnóstico, medicamento) replicada
#   T3  actualización (fhir_patient_id) replicada
#   T4  sin errores de aplicación ni bucles de replicación
#   T5  AISLAMIENTO de Corozal: las otras dos siguen, Corozal sigue con
#       lo suyo, y al reconectar todas convergen
#   T6  CAÍDA de Cartagena (contenedor detenido): las otras dos siguen y
#       Cartagena se pone al día al volver
#
# Sale con código != 0 si alguna prueba falla. Los datos de prueba llevan
# el prefijo T<epoch> en el número de documento y quedan en las bases
# (docker compose -f docker-compose.yml down -v las borra).
set -uo pipefail

NODOS=(sincelejo cartagena corozal)
RID=$(date +%s)
FALLOS=0
ELAPSED=0
LIMITE=${LIMITE_CONVERGENCIA:-60}
AISLAMIENTO_S=${AISLAMIENTO_S:-15}

q() { docker exec -i "pg_$1" psql -U admin -d historia_clinica -Atq -v ON_ERROR_STOP=1 -c "$2"; }

ok()    { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fallo() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FALLOS=$((FALLOS + 1)); }
check() { if "${@:2}" >/dev/null 2>&1; then ok "$1"; else fallo "$1"; fi; }

# esperar <timeout_s> <comando...>: reintenta hasta que el comando tenga éxito.
# Deja el tiempo tardado en ELAPSED (segundos).
esperar() {
  local limite=$1; shift
  local t0 t1
  t0=$(date +%s.%N)
  while true; do
    if "$@" >/dev/null 2>&1; then
      t1=$(date +%s.%N)
      ELAPSED=$(awk -v a="$t1" -v b="$t0" 'BEGIN{printf "%.1f", a-b}')
      return 0
    fi
    t1=$(date +%s.%N)
    if awk -v a="$t1" -v b="$t0" -v l="$limite" 'BEGIN{exit !(a-b>l)}'; then
      ELAPSED=$limite
      return 1
    fi
    sleep 0.3
  done
}

insertar_paciente() { # nodo id_sede documento
  q "$1" "INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
            primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia)
          VALUES ($2, 'CC', '$3', 'Test', 'Replica', '1990-01-01', 'F', 'COL')" >/dev/null
}

cuenta() { q "$1" "SELECT count(*) FROM paciente WHERE numero_documento LIKE 'T${RID}%'"; }

# Todos los nodos listados tienen exactamente N pacientes de prueba.
cuentan() { # N nodo...
  local n=$1; shift
  local nodo
  for nodo in "$@"; do [ "$(cuenta "$nodo")" = "$n" ] || return 1; done
}

# Huella del estado de prueba: pacientes + encuentros + hijos.
huella() {
  q "$1" "SELECT md5(
      coalesce((SELECT string_agg(id_paciente::text || numero_documento || coalesce(fhir_patient_id,''), ',' ORDER BY id_paciente)
                  FROM paciente WHERE numero_documento LIKE 'T${RID}%'), '') ||
      coalesce((SELECT string_agg(e.id_encuentro::text, ',' ORDER BY e.id_encuentro)
                  FROM encuentro e JOIN paciente p USING (id_paciente)
                 WHERE p.numero_documento LIKE 'T${RID}%'), '') ||
      (SELECT count(*) FROM diagnostico_encuentro)::text ||
      (SELECT count(*) FROM medicamento_prescrito)::text)"
}

misma_huella() {
  local a b c
  a=$(huella "$1"); b=$(huella "$2"); c=$(huella "$3")
  [ -n "$a" ] && [ "$a" = "$b" ] && [ "$b" = "$c" ]
}

echo "== Pruebas de replicación entre sedes (corrida $RID) =="

# ---------------------------------------------------------------- T0
echo "T0  Malla de replicación"
# Tras una corrida anterior (T5/T6) un par puede tardar unos segundos en
# reconectar: se espera a que los procesos de aplicación estén arriba.
workers_activos() { [ "$(q "$1" "SELECT count(*) FROM pg_stat_subscription WHERE pid IS NOT NULL AND subname IS NOT NULL")" = 2 ]; }
for n in "${NODOS[@]}"; do
  subs=$(q "$n" "SELECT count(*) FROM pg_subscription WHERE subenabled")
  if [ "$subs" = 2 ] && esperar 30 workers_activos "$n"; then
    ok "pg_$n: 2 suscripciones con proceso de aplicación activo"
  else
    fallo "pg_$n: suscripciones=$subs, procesos de aplicación activos incompletos tras 30s"
  fi
done

# ---------------------------------------------------------------- T1
echo "T1  Propagación de escrituras (una por sede)"
DOC1="T${RID}1"; DOC2="T${RID}2"; DOC3="T${RID}3"
insertar_paciente sincelejo 1 "$DOC1"
insertar_paciente cartagena 2 "$DOC2"
insertar_paciente corozal   3 "$DOC3"
if esperar "$LIMITE" cuentan 3 "${NODOS[@]}"; then
  ok "las 3 sedes ven los 3 pacientes (${ELAPSED}s)"
else
  fallo "no convergieron los 3 pacientes en ${LIMITE}s (cuentas: $(cuenta sincelejo)/$(cuenta cartagena)/$(cuenta corozal))"
fi

# ---------------------------------------------------------------- T2
echo "T2  Cadena clínica replicada"
PAC=$(q sincelejo "SELECT id_paciente FROM paciente WHERE numero_documento = '$DOC1'")
ENC=$(q sincelejo "SELECT gen_random_uuid()")
TEC=$(q sincelejo "SELECT gen_random_uuid()")
q sincelejo "
  INSERT INTO encuentro (id_encuentro, id_paciente, id_sede, fecha_hora_inicio, cod_modalidad,
                         cod_grupo_servicio, cod_entorno, cod_via_ingreso, cod_causa_atencion,
                         cod_entidad_responsable)
  VALUES ('$ENC', '$PAC', 1, now(), '01', '01', '01', '01', '01', 'EPS001');
  INSERT INTO diagnostico_encuentro (id_encuentro, cod_cie10, cod_tipo_diagnostico, fecha_diagnostico)
  VALUES ('$ENC', 'J00', 'IN', current_date);
  INSERT INTO tecnologia_encuentro VALUES ('$TEC', '$ENC', '19938', '02', now());
  INSERT INTO medicamento_prescrito VALUES ('$TEC', '19938', 500, 'mg', '01', 5, 'd', 8, 'h');" >/dev/null
chain_en() {
  [ "$(q "$1" "SELECT count(*) FROM encuentro WHERE id_encuentro = '$ENC'")" = 1 ] &&
  [ "$(q "$1" "SELECT count(*) FROM diagnostico_encuentro WHERE id_encuentro = '$ENC'")" = 1 ] &&
  [ "$(q "$1" "SELECT count(*) FROM medicamento_prescrito WHERE id_tecnologia_encuentro = '$TEC'")" = 1 ]
}
for n in cartagena corozal; do
  if esperar "$LIMITE" chain_en "$n"; then ok "pg_$n recibió encuentro, diagnóstico y medicamento (${ELAPSED}s)"
  else fallo "pg_$n no recibió la cadena clínica en ${LIMITE}s"; fi
done

# ---------------------------------------------------------------- T3
echo "T3  Actualización replicada (migración FHIR en la sede dueña)"
q sincelejo "UPDATE paciente SET fhir_patient_id = 'FHIR-$RID' WHERE numero_documento = '$DOC1'" >/dev/null
fhir_en() { [ "$(q "$1" "SELECT fhir_patient_id FROM paciente WHERE numero_documento = '$DOC1'")" = "FHIR-$RID" ]; }
for n in cartagena corozal; do
  if esperar "$LIMITE" fhir_en "$n"; then ok "pg_$n ve fhir_patient_id actualizado (${ELAPSED}s)"
  else fallo "pg_$n no recibió la actualización"; fi
done

# ---------------------------------------------------------------- T4
echo "T4  Sin conflictos de datos ni bucles"
# Los contadores de pg_stat_subscription_stats también suman cortes de
# conexión (timeouts, par caído), que son esperables en T5/T6 de corridas
# anteriores. Lo que no debe aparecer nunca son conflictos de datos.
for n in "${NODOS[@]}"; do
  # Un conflicto de datos al aplicar la réplica deja el CONTEXT «processing remote data for replication
  # origin». Las violaciones de restricciones de las pruebas de la API (escrituras directas) no lo llevan.
  conflictos=$(docker logs "pg_$n" 2>&1 | grep -c 'processing remote data for replication origin' || true)
  check "pg_$n: 0 conflictos de datos en el log de replicación" test "$conflictos" = 0
  habilitadas=$(q "$n" "SELECT count(*) FROM pg_subscription WHERE subenabled")
  check "pg_$n: ninguna suscripción deshabilitada por error" test "$habilitadas" = 2
done
check "sin duplicados por bucle (3 pacientes en cada sede)" cuentan 3 "${NODOS[@]}"

# ---------------------------------------------------------------- T5
echo "T5  AISLAMIENTO de Corozal (sigue encendida, sin red)"
NET=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' pg_corozal)
docker network disconnect "$NET" pg_corozal
DOC4="T${RID}4"; DOC5="T${RID}5"; DOC6="T${RID}6"
check "Corozal aislada acepta escrituras locales" insertar_paciente corozal 3 "$DOC4"
insertar_paciente sincelejo 1 "$DOC5"
insertar_paciente cartagena 2 "$DOC6"
if esperar "$LIMITE" cuentan 5 sincelejo cartagena; then
  ok "Sincelejo y Cartagena siguen replicándose entre sí con Corozal fuera (${ELAPSED}s)"
else
  fallo "Sincelejo y Cartagena no convergieron sin Corozal"
fi
# Mantiene la partición más tiempo que wal_sender/receiver_timeout (10 s)
# para que los procesos de replicación detecten el corte y reintenten.
echo "    (aislada ${AISLAMIENTO_S}s para superar los timeouts de replicación...)"
sleep "$AISLAMIENTO_S"
check "Corozal aislada sigue leyendo sus datos (4 pacientes: 3 + el nuevo)" test "$(cuenta corozal)" = 4
check "Sincelejo NO ve el registro hecho en Corozal (hay partición real)" \
      test "$(q sincelejo "SELECT count(*) FROM paciente WHERE numero_documento = '$DOC4'")" = 0
check "Corozal NO ve los registros hechos en Sincelejo y Cartagena" \
      test "$(q corozal "SELECT count(*) FROM paciente WHERE numero_documento IN ('$DOC5','$DOC6')")" = 0
docker network connect "$NET" pg_corozal
if esperar "$LIMITE" cuentan 6 "${NODOS[@]}"; then
  ok "al reconectar, las 3 sedes convergen a 6 pacientes (${ELAPSED}s tras reconectar)"
else
  fallo "las sedes no convergieron tras reconectar Corozal en ${LIMITE}s ($(cuenta sincelejo)/$(cuenta cartagena)/$(cuenta corozal))"
fi
check "estado idéntico en las 3 sedes tras la reconexión" misma_huella sincelejo cartagena corozal

# ---------------------------------------------------------------- T6
echo "T6  CAÍDA de Cartagena (contenedor detenido)"
docker stop pg_cartagena >/dev/null
DOC7="T${RID}7"; DOC8="T${RID}8"
insertar_paciente sincelejo 1 "$DOC7"
insertar_paciente corozal   3 "$DOC8"
if esperar "$LIMITE" cuentan 8 sincelejo corozal; then
  ok "Sincelejo y Corozal siguen operando y replicándose con Cartagena caída (${ELAPSED}s)"
else
  fallo "Sincelejo y Corozal no convergieron con Cartagena caída"
fi
docker start pg_cartagena >/dev/null
if esperar "$LIMITE" cuentan 8 "${NODOS[@]}"; then
  ok "Cartagena se puso al día sola tras reiniciar (${ELAPSED}s)"
else
  fallo "Cartagena no se puso al día en ${LIMITE}s"
fi
check "estado idéntico en las 3 sedes tras la recuperación" misma_huella sincelejo cartagena corozal

echo
if [ "$FALLOS" -eq 0 ]; then
  printf '\033[32mTodas las pruebas pasaron.\033[0m\n'
else
  printf '\033[31m%d prueba(s) fallaron.\033[0m\n' "$FALLOS"
fi
exit "$FALLOS"
