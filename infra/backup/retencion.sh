#!/bin/sh
# Retención de los respaldos de una sede (se carga con `.` desde respaldar.sh y desde probar_retencion.sh).
#
#   aplicar_retencion DIRECTORIO N MESES
#
# Conserva los N respaldos más recientes y, de los más antiguos, el más reciente de cada mes (hasta MESES meses).
# El resto se borra junto con su suma SHA-256. Los nombres son respaldo_<sede>_AAAAMMDDTHHMMSSZ.tar.age, así que ordenar
# por nombre es ordenar por fecha. No toca nada que no tenga ese patrón.
aplicar_retencion() {
  _dir=$1; _n=$2; _meses=$3
  ls -1 "$_dir"/respaldo_*.tar.age 2>/dev/null | sort -r | awk -v n="$_n" -v meses="$_meses" '
    { i++
      k = split($0, p, "_"); mes = substr(p[k], 1, 6)             # AAAAMM del nombre
      if (i <= n)                                  { print "conservar " $0; next }
      if (!(mes in visto) && usados < meses)       { visto[mes] = 1; usados++; print "conservar " $0; next }
      print "borrar " $0 }' | {
    _borrados=0; _quedan=0
    while read -r accion archivo; do
      if [ "$accion" = "borrar" ]; then rm -f "$archivo" "$archivo.sha256"; _borrados=$((_borrados + 1)); else _quedan=$((_quedan + 1)); fi
    done
    echo "retencion conservados=$_quedan borrados=$_borrados"
  }
}
