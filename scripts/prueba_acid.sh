#!/usr/bin/env bash
# Evidencia ACID sobre la base de la sede 1 y sus réplicas, con SQL real (antes / error a la mitad / después):
#
#   bash scripts/prueba_acid.sh            # Docker Compose
#   bash scripts/prueba_acid.sh k8s        # Kubernetes/Minikube
#
#   A  atomicidad    una transacción de varias tablas que falla a la mitad no deja nada, ni aquí ni en las réplicas; una confirmada llega completa
#   C  consistencia  una clave foránea, un CHECK y una restricción única inválidos son rechazados por la base y no cambian nada
#   I  aislamiento   una sesión no ve lo que otra no ha confirmado; una inserción repetida espera a la otra y falla con la restricción única
#   D  durabilidad   lo confirmado sobrevive a un SIGKILL de la base; lo no confirmado desaparece; las réplicas se ponen al día
#
# La parte por HTTP (egreso y prescripción atómicos, réplica sin escrituras a medias, concurrencia) está en tests/api/test_acid.py.
# Solo laboratorio: crea pacientes de prueba en la sede 1 y reinicia a la fuerza su PostgreSQL.
set -euo pipefail
cd "$(dirname "$0")/.."

MODO=${1:-compose}
case "$MODO" in
  compose)
    psql_en() { docker exec -i "pg_$1" psql -U admin -d historia_clinica -qtA "${@:2}"; }
    matar() { docker kill pg_sincelejo >/dev/null; sleep 1; docker start pg_sincelejo >/dev/null 2>&1 || true; } ;;
  k8s)
    psql_en() { kubectl -n "sede-$1" exec -i pg-0 -- psql -U admin -d historia_clinica -qtA "${@:2}"; }
    matar() { kubectl -n sede-sincelejo delete pod pg-0 --grace-period=0 --force >/dev/null 2>&1; } ;;
  *) echo "uso: $0 [compose|k8s]"; exit 2 ;;
esac
FALLOS=0
paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
mal() { printf '  \033[31mFALLA\033[0m %s\n' "$*"; FALLOS=$((FALLOS + 1)); }
S1() { psql_en sincelejo "$@"; }
contar() {   # sede, documento -> "pacientes|encuentros"
  psql_en "$1" -c "SELECT (SELECT count(*) FROM paciente WHERE numero_documento = '$2') || '|' || (SELECT count(*) FROM encuentro e JOIN paciente p USING (id_paciente) WHERE p.numero_documento = '$2')" 2>/dev/null | tr -d '[:space:]'; }
esperar_igual() {   # sede, documento, esperado: espera a que la réplica llegue a ese estado
  for _ in $(seq 1 30); do [ "$(contar "$1" "$2")" = "$3" ] && return 0; sleep 1; done; return 1; }
LISTO() { for _ in $(seq 1 90); do S1 -c "SELECT 1" >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
T=$(date +%s)
NUEVO_PACIENTE="INSERT INTO paciente (id_paciente, id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre, primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia)"
ENCUENTRO="INSERT INTO encuentro (id_paciente, id_sede, fecha_hora_inicio, fecha_hora_fin, cod_modalidad, cod_grupo_servicio, cod_entorno, cod_via_ingreso, cod_causa_atencion, cod_entidad_responsable)"

paso "A. Atomicidad: paciente + 2 encuentros, el tercer INSERT viola el CHECK (fin anterior al inicio)"
DOC="ACID$T"
echo "  ANTES      sede 1: $(contar sincelejo $DOC)  sede 2: $(contar cartagena $DOC)  sede 3: $(contar corozal $DOC)   (pacientes|encuentros)"
SALIDA=$(S1 -v ON_ERROR_STOP=1 2>&1 <<SQL || true
BEGIN;
SELECT gen_random_uuid() AS pid \gset
$NUEVO_PACIENTE VALUES (:'pid', 1, 'CC', '$DOC', 'Acid', 'Atomica', '1990-01-01', 'F', 'COL');
$ENCUENTRO VALUES (:'pid', 1, '2026-11-07 08:00', NULL, '01','01','01','01','01','EPS001');
$ENCUENTRO VALUES (:'pid', 1, '2026-11-07 09:00', NULL, '01','01','01','01','01','EPS001');
$ENCUENTRO VALUES (:'pid', 1, '2026-11-07 10:00', '2026-11-07 06:00', '01','01','01','01','01','EPS001');
COMMIT;
SQL
)
echo "  A LA MITAD $(echo "$SALIDA" | grep -m1 ERROR | cut -c1-120)"
sleep 4
echo "  DESPUÉS    sede 1: $(contar sincelejo $DOC)  sede 2: $(contar cartagena $DOC)  sede 3: $(contar corozal $DOC)"
[[ "$SALIDA" == *"ERROR"* ]] && [ "$(contar sincelejo $DOC)" = "0|0" ] && [ "$(contar cartagena $DOC)" = "0|0" ] && [ "$(contar corozal $DOC)" = "0|0" ] \
  && ok "la transacción fallida no dejó nada: ni el paciente ni los dos encuentros que sí se habían insertado, en ninguna sede" || mal "quedaron filas de la transacción fallida"
S1 -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
BEGIN;
SELECT gen_random_uuid() AS pid \gset
$NUEVO_PACIENTE VALUES (:'pid', 1, 'CC', '$DOC', 'Acid', 'Atomica', '1990-01-01', 'F', 'COL');
$ENCUENTRO VALUES (:'pid', 1, '2026-11-07 08:00', NULL, '01','01','01','01','01','EPS001');
$ENCUENTRO VALUES (:'pid', 1, '2026-11-07 09:00', NULL, '01','01','01','01','01','EPS001');
COMMIT;
SQL
for sede in cartagena corozal; do
  esperar_igual "$sede" "$DOC" "1|2" && ok "la misma transacción sin el error se confirma y llega completa a $sede (1 paciente, 2 encuentros)" || mal "$sede no recibió la transacción confirmada completa: $(contar "$sede" "$DOC")"
done

paso "C. Consistencia: la base rechaza lo inválido y no cambia nada"
for caso in "FK|$ENCUENTRO VALUES (gen_random_uuid(), 1, now(), NULL, '01','01','01','01','01','EPS001')|violates foreign key" \
            "CHECK|$ENCUENTRO VALUES ((SELECT id_paciente FROM paciente WHERE numero_documento = '$DOC'), 1, '2026-11-07 10:00', '2026-11-07 06:00', '01','01','01','01','01','EPS001')|violates check constraint" \
            "UNICA|$NUEVO_PACIENTE VALUES (gen_random_uuid(), 1, 'CC', '$DOC', 'Otro', 'Duplicado', '1990-01-01', 'F', 'COL')|duplicate key"; do
  IFS='|' read -r nombre sentencia esperado <<<"$caso"
  r=$(S1 -v ON_ERROR_STOP=1 -c "$sentencia" 2>&1 || true)
  [[ "$r" == *"$esperado"* ]] && ok "$nombre: rechazado por la base ($(echo "$r" | grep -m1 ERROR | cut -c8-80))" || mal "$nombre: no fue rechazado: $r"
done
[ "$(contar sincelejo $DOC)" = "1|2" ] && ok "los tres intentos no cambiaron nada (sigue 1|2)" || mal "cambió el contenido: $(contar sincelejo $DOC)"

paso "I. Aislamiento: una sesión no ve lo no confirmado y la otra espera"
DOC2="ISO$T"
( S1 -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
BEGIN;
$NUEVO_PACIENTE VALUES (gen_random_uuid(), 1, 'CC', '$DOC2', 'Iso', 'Lada', '1990-01-01', 'F', 'COL');
SELECT pg_sleep(7);
COMMIT;
SQL
) &
sleep 2
echo "  sesión B, con la A sin confirmar: pacientes visibles = $(contar sincelejo $DOC2 | cut -d'|' -f1)"
[ "$(contar sincelejo $DOC2 | cut -d'|' -f1)" = "0" ] && ok "B no ve la fila no confirmada de A (sin lecturas sucias)" || mal "B vio una fila no confirmada"
INICIO=$SECONDS
R=$(S1 -v ON_ERROR_STOP=1 -c "$NUEVO_PACIENTE VALUES (gen_random_uuid(), 1, 'CC', '$DOC2', 'Iso', 'Lada', '1990-01-01', 'F', 'COL')" 2>&1 || true)
ESPERA=$((SECONDS - INICIO))
wait
[[ "$R" == *"duplicate key"* ]] && [ "$ESPERA" -ge 3 ] && ok "la inserción repetida de B esperó a que A terminara (${ESPERA} s) y luego falló con la restricción única" || mal "B no esperó o no falló como se esperaba (${ESPERA} s): $R"
[ "$(contar sincelejo $DOC2 | cut -d'|' -f1)" = "1" ] && ok "al confirmar A, la fila existe una sola vez" || mal "la fila no quedó una sola vez"

paso "D. Durabilidad: SIGKILL de la base con una transacción confirmada y otra sin confirmar"
DOC3="DUR$T"; DOC4="NOC$T"
S1 -v ON_ERROR_STOP=1 -c "$NUEVO_PACIENTE VALUES (gen_random_uuid(), 1, 'CC', '$DOC3', 'Dur', 'Able', '1990-01-01', 'F', 'COL')" >/dev/null
( S1 -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
BEGIN;
$NUEVO_PACIENTE VALUES (gen_random_uuid(), 1, 'CC', '$DOC4', 'No', 'Confirmado', '1990-01-01', 'F', 'COL');
SELECT pg_sleep(60);
SQL
) &
sleep 2
echo "  ANTES      confirmado ($DOC3): $(contar sincelejo $DOC3 | cut -d'|' -f1)   sin confirmar ($DOC4) visto desde otra sesión: $(contar sincelejo $DOC4 | cut -d'|' -f1)"
matar
wait || true
LISTO && ok "la base volvió tras el SIGKILL" || mal "la base no volvió"
echo "  DESPUÉS    confirmado ($DOC3): $(contar sincelejo $DOC3 | cut -d'|' -f1)   sin confirmar ($DOC4): $(contar sincelejo $DOC4 | cut -d'|' -f1)"
[ "$(contar sincelejo $DOC3 | cut -d'|' -f1)" = "1" ] && ok "lo confirmado sobrevivió" || mal "se perdió lo confirmado"
[ "$(contar sincelejo $DOC4 | cut -d'|' -f1)" = "0" ] && ok "lo no confirmado desapareció (la transacción se deshizo en la recuperación)" || mal "quedó lo no confirmado"
esperar_igual cartagena "$DOC3" "1|0" && ok "las réplicas se pusieron al día con lo confirmado (cartagena)" || mal "cartagena no recibió lo confirmado: $(contar cartagena "$DOC3")"
[ "$(contar cartagena $DOC4 | cut -d'|' -f1)" = "0" ] && ok "lo que no se confirmó nunca llegó a la réplica" || mal "la réplica tiene lo no confirmado"

printf '\n'
[ "$FALLOS" -eq 0 ] && echo "ACID: todo en orden" || { echo "ACID: $FALLOS fallo(s)"; exit 1; }
