#!/usr/bin/env bash
# Copia de seguridad lógica de una sede (Kubernetes): historia_clinica y fhir_db con pg_dump.
#
#   bash scripts/respaldo_sede.sh <sede> [directorio]        sede: sincelejo | cartagena | corozal
#   bash scripts/respaldo_sede.sh cartagena respaldos
#
# Deja por cada base un archivo `<sede>_<base>_<fecha>.dump` (formato personalizado) y su
# suma SHA-256, y comprueba que `pg_restore -l` puede leerlo.
#
# Para qué sirve (y para qué no):
#   - La réplica lógica entre sedes cubre la PÉRDIDA DE UNA SEDE (se reconstruye desde sus
#     pares: scripts/reconstruir_sede.sh), pero también replica los errores lógicos: un
#     DELETE o UPDATE equivocado llega a las tres sedes. Contra eso sirven estas copias.
#   - Es una copia puntual y manual; no hay programación, cifrado ni almacenamiento externo.
#
# Restaurar una base en un PostgreSQL vacío (ejemplo):
#   kubectl -n sede-X exec -i pg-0 -- pg_restore -U admin -d historia_clinica --no-owner --no-subscriptions --clean --if-exists < archivo.dump
set -euo pipefail

SEDE="${1:?uso: respaldo_sede.sh <sincelejo|cartagena|corozal> [directorio]}"
DESTINO="${2:-respaldos}"
NS="sede-$SEDE"
FECHA=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DESTINO"

for BD in historia_clinica fhir_db; do
  ARCHIVO="$DESTINO/${SEDE}_${BD}_${FECHA}.dump"
  kubectl -n "$NS" exec pg-0 -- pg_dump -U admin -d "$BD" -Fc > "$ARCHIVO"
  # El archivo debe ser legible por pg_restore (si el volcado se cortó, esto falla).
  ELEMENTOS=$(kubectl -n "$NS" exec -i pg-0 -- pg_restore -l < "$ARCHIVO" | grep -c '^[0-9]' || true)
  (cd "$DESTINO" && sha256sum "$(basename "$ARCHIVO")" > "$(basename "$ARCHIVO").sha256")
  printf '%-45s %8s bytes  %s elementos\n' "$ARCHIVO" "$(stat -c %s "$ARCHIVO")" "$ELEMENTOS"
done
echo "Respaldo de $SEDE listo en $DESTINO/"
