#!/bin/sh
# Respaldo programado de UNA sede (lo corre el CronJob `respaldo` de su namespace; también `scripts/respaldos.sh ahora`).
#
#  1. Vuelca historia_clinica y fhir_db (si existe) con pg_dump -Fc y los roles con pg_dumpall --roles-only.
#  2. Comprueba que cada volcado se pueda leer (pg_restore -l) y anota sumas SHA-256 y conteos en manifest.json.
#  3. Empaqueta y CIFRA con una clave PÚBLICA (age): el clúster nunca tiene la clave privada, así que quien robe el volumen
#     o la copia remota no puede leer los datos. Sin la clave privada (credenciales/respaldo.key) no hay restauración.
#  4. Si hay RESPALDO_REMOTO (rclone), sube la copia fuera del clúster y falla si la subida falla.
#  5. Aplica la retención local y deja ultimo.json y una línea final "RESPALDO_OK ..." en el registro.
# Cualquier error termina con código != 0: el Job queda en Failed y se ve en `scripts/respaldos.sh estado`.
set -eu
. /usr/local/bin/retencion.sh

SEDE="${LOCAL_NAME:?falta LOCAL_NAME (sede-config)}"
export PGHOST="${PGHOST:-pg-local}" PGUSER="${PGUSER:-admin}"
: "${PGPASSWORD:?falta PGPASSWORD}"; export PGPASSWORD
DESTINO="${DESTINO:-/respaldos}"
RETENCION="${RESPALDO_RETENCION:-14}"
MESES="${RESPALDO_MESES:-6}"
export HOME="${HOME:-/tmp}"

if [ -z "${RESPALDO_RECIPIENT:-}" ]; then
  echo "ERROR: falta la clave pública de cifrado (Secret hc-respaldo). Ejecute: bash scripts/respaldos.sh claves" >&2
  exit 2
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
DIR="$DESTINO/$SEDE"
TMP="$DIR/.tmp-$TS"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

for _ in $(seq 1 30); do pg_isready -q && break; sleep 2; done
pg_isready -q || { echo "ERROR: la base de la sede no responde" >&2; exit 3; }

contar() {
  psql -d historia_clinica -Atq -F ' ' -c "SELECT (SELECT count(*) FROM paciente), (SELECT count(*) FROM encuentro),
         (SELECT count(*) FROM diagnostico_encuentro), (SELECT count(*) FROM composicion_bundle),
         (SELECT count(*) FROM mpi_decision)"
}
ANTES=$(contar)

BASES="historia_clinica"
if [ "$(psql -d postgres -Atq -c "SELECT 1 FROM pg_database WHERE datname = 'fhir_db'")" = "1" ]; then BASES="$BASES fhir_db"; fi
for bd in $BASES; do
  pg_dump -d "$bd" -Fc --no-subscriptions -f "$TMP/$bd.dump"
  pg_restore -l "$TMP/$bd.dump" > /dev/null          # si el volcado se cortó, esto falla
done
pg_dumpall --roles-only -f "$TMP/roles.sql"          # incluye el rol de réplica (con su hash); va cifrado
DESPUES=$(contar)

{
  printf '{\n  "sede": "%s",\n  "fecha_utc": "%s",\n  "postgres": "%s",\n' "$SEDE" "$TS" "$(psql -Atq -d postgres -c 'SHOW server_version')"
  printf '  "conteos_antes": "%s",\n  "conteos_despues": "%s",\n  "orden_conteos": "pacientes encuentros diagnosticos rda decisiones_mpi",\n' "$ANTES" "$DESPUES"
  printf '  "archivos": {\n'
  primero=1
  for f in "$TMP"/*; do
    n=$(basename "$f"); [ "$n" = "manifest.json" ] && continue
    [ "$primero" = 1 ] || printf ',\n'
    printf '    "%s": {"bytes": %s, "sha256": "%s"}' "$n" "$(wc -c < "$f")" "$(sha256sum "$f" | cut -d' ' -f1)"
    primero=0
  done
  printf '\n  }\n}\n'
} > "$TMP/manifest.json"

ARCHIVO="$DIR/respaldo_${SEDE}_${TS}.tar.age"
tar cf - -C "$TMP" . | age -r "$RESPALDO_RECIPIENT" -o "$ARCHIVO.parcial"
[ -s "$ARCHIVO.parcial" ] || { echo "ERROR: el archivo cifrado quedó vacío" >&2; exit 4; }
mv "$ARCHIVO.parcial" "$ARCHIVO"
SHA=$(sha256sum "$ARCHIVO" | cut -d' ' -f1)
echo "$SHA  $(basename "$ARCHIVO")" > "$ARCHIVO.sha256"
BYTES=$(wc -c < "$ARCHIVO")

REMOTO=no
if [ -n "${RESPALDO_REMOTO:-}" ]; then
  rclone copyto "$ARCHIVO" "$RESPALDO_REMOTO/$SEDE/$(basename "$ARCHIVO")" --checksum
  rclone copyto "$ARCHIVO.sha256" "$RESPALDO_REMOTO/$SEDE/$(basename "$ARCHIVO").sha256" --checksum
  REMOTO=si
fi

RESUMEN=$(aplicar_retencion "$DIR" "$RETENCION" "$MESES")
printf '{"sede":"%s","fecha_utc":"%s","archivo":"%s","bytes":%s,"sha256":"%s","fuera_del_cluster":"%s"}\n' \
  "$SEDE" "$TS" "$(basename "$ARCHIVO")" "$BYTES" "$SHA" "$REMOTO" > "$DIR/ultimo.json"

echo "RESPALDO_OK sede=$SEDE archivo=$(basename "$ARCHIVO") bytes=$BYTES sha256=$SHA fuera_del_cluster=$REMOTO bases=\"$BASES\" $RESUMEN"
