#!/usr/bin/env bash
# Prueba que una copia de seguridad se puede RESTAURAR: la carga en una base temporal de la
# misma sede, compara los conteos con la base original y elimina la temporal.
#
#   bash scripts/probar_respaldo.sh <sede> [archivo.dump]     (por defecto, el respaldo más reciente)
#
# Nota: el volcado incluye las suscripciones de réplica; se restaura con --no-subscriptions
# para no recrearlas (sin su slot no sirven y impiden borrar la base).
set -euo pipefail

SEDE="${1:?uso: probar_respaldo.sh <sede> [archivo.dump]}"
ARCHIVO="${2:-$(ls -t respaldos/${SEDE}_historia_clinica_*.dump | head -1)}"
NS="sede-$SEDE"
psql_pg() { kubectl -n "$NS" exec pg-0 -- psql -U admin "$@"; }

CONSULTA="select (select count(*) from paciente) || ' pacientes, ' ||
                 (select count(*) from encuentro) || ' encuentros, ' ||
                 (select count(*) from diagnostico_encuentro) || ' diagnósticos, ' ||
                 (select count(*) from composicion_bundle) || ' RDA'"

psql_pg -d postgres -Atc "DROP DATABASE IF EXISTS prueba_restauracion" >/dev/null
psql_pg -d postgres -Atc "CREATE DATABASE prueba_restauracion" >/dev/null
trap 'psql_pg -d postgres -Atc "DROP DATABASE IF EXISTS prueba_restauracion" >/dev/null 2>&1 || true' EXIT

kubectl -n "$NS" exec -i pg-0 -- pg_restore -U admin -d prueba_restauracion --no-owner --no-subscriptions < "$ARCHIVO"
ORIGINAL=$(psql_pg -d historia_clinica -Atc "$CONSULTA")
RESTAURADA=$(psql_pg -d prueba_restauracion -Atc "$CONSULTA")
echo "archivo   : $ARCHIVO"
echo "original  : $ORIGINAL"
echo "restaurada: $RESTAURADA"
if [ "$ORIGINAL" = "$RESTAURADA" ]; then
  echo "OK: la copia se restauró completa."
else
  echo "AVISO: los conteos difieren (la sede pudo recibir datos nuevos después de la copia)."
  exit 1
fi
