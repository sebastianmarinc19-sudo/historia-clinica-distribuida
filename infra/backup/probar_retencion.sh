#!/bin/sh
# Prueba la retención con archivos de mentira (no necesita PostgreSQL ni age). Corre con busybox/sh:
#   docker run --rm -v "$PWD/infra/backup":/b alpine sh /b/probar_retencion.sh
# Las condiciones llegan como texto y se evalúan con eval: por eso shellcheck cree que `salida` y `quedan` no se usan.
# shellcheck disable=SC2034
set -eu
# shellcheck source=infra/backup/retencion.sh
. "$(dirname "$0")/retencion.sh"

d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
crear() { : > "$d/respaldo_sincelejo_$1T020000Z.tar.age"; : > "$d/respaldo_sincelejo_$1T020000Z.tar.age.sha256"; }

for dia in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20; do crear "202611$dia"; done   # 20 diarios en noviembre
for f in 20261029 20261015 20261001 20260930 20260915 20260831 20260715 20260301; do crear "$f"; done  # antiguos
: > "$d/otro_archivo.txt"                                                                              # ajeno: no se toca

salida=$(aplicar_retencion "$d" 14 3)
contar() { find "$d" -name 'respaldo_*.tar.age' | wc -l; }
quedan=$(contar)

fallos=0
verificar() { if ! eval "$2"; then echo "FALLA: $1"; fallos=$((fallos + 1)); else echo "ok: $1"; fi; }
existe() { [ -e "$d/respaldo_sincelejo_$1T020000Z.tar.age" ]; }

verificar "se conservan los 14 más recientes (20 al 07 de noviembre)" 'existe 20261120 && existe 20261107'
verificar "el más reciente de cada uno de los 3 meses anteriores al corte (nov 06, oct 29, sep 30)" 'existe 20261106 && existe 20261029 && existe 20260930'
verificar "se borran los demás de un mes ya representado" '! existe 20261105 && ! existe 20261101 && ! existe 20261015 && ! existe 20260915'
verificar "se borran los meses fuera del límite de 3" '! existe 20260831 && ! existe 20260715 && ! existe 20260301'
verificar "total conservado = 17" '[ "$quedan" -eq 17 ]'
verificar "la suma .sha256 se borra con su archivo" '[ ! -e "$d/respaldo_sincelejo_20261105T020000Z.tar.age.sha256" ] && [ -e "$d/respaldo_sincelejo_20261120T020000Z.tar.age.sha256" ]'
verificar "no toca archivos ajenos" '[ -e "$d/otro_archivo.txt" ]'
verificar "informa lo que hizo" '[ "$salida" = "retencion conservados=17 borrados=11" ]'

# idempotente: una segunda pasada no borra nada más
aplicar_retencion "$d" 14 3 >/dev/null
verificar "idempotente" '[ "$(contar)" -eq 17 ]'

[ "$fallos" -eq 0 ] && echo "Retención: todo en orden" || { echo "Retención: $fallos fallo(s)"; exit 1; }
