#!/usr/bin/env bash
# Operación de los respaldos programados de las 3 sedes (Kubernetes). Ver infra/backup/respaldar.sh y infra/k8s/base/respaldo.yaml.
#
#   bash scripts/respaldos.sh claves              # crea la clave de cifrado (age) y deja la PÚBLICA en cada sede
#   bash scripts/respaldos.sh ahora [sede...]     # respaldo manual ahora (por defecto, las 3 sedes)
#   bash scripts/respaldos.sh estado              # último respaldo exitoso de cada sede; sale con 1 si alguno está vencido
#   bash scripts/respaldos.sh traer [destino]     # copia los respaldos FUERA del clúster (por defecto respaldos/cluster/) y comprueba sus sumas
#   bash scripts/respaldos.sh verificar [archivo] # descifra y RESTAURA en un PostgreSQL desechable y compara los conteos
#
# La clave PRIVADA queda en credenciales/respaldo.key (ignorada por git). Guárdela también fuera de este equipo y del
# repositorio (gestor de contraseñas): sin ella los respaldos no se pueden leer, y con ella cualquiera los lee.
set -euo pipefail
cd "$(dirname "$0")/.."

SEDES=(sincelejo cartagena corozal)
IMG=hc-backup:local
CLAVE=credenciales/respaldo.key
MAX_HORAS=${RESPALDO_MAX_HORAS:-30}      # un respaldo diario debe tener menos de ~26 h; 30 deja margen

imagen() {
  docker image inspect "$IMG" >/dev/null 2>&1 || docker build -q -t "$IMG" infra/backup >/dev/null
}

claves() {
  imagen
  mkdir -p credenciales
  if [ ! -f "$CLAVE" ]; then
    docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/credenciales":/k "$IMG" age-keygen -o /k/respaldo.key 2>/dev/null
    chmod 600 "$CLAVE"
    echo "Clave de cifrado creada en $CLAVE (guárdela también fuera de este equipo)."
  fi
  local publica
  publica=$(docker run --rm -v "$PWD/credenciales":/k:ro "$IMG" age-keygen -y /k/respaldo.key)
  echo "$publica" > credenciales/respaldo.pub
  for s in "${SEDES[@]}"; do
    kubectl -n "sede-$s" create secret generic hc-respaldo --from-literal=RESPALDO_RECIPIENT="$publica" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done
  echo "Clave pública instalada en las 3 sedes: $publica"
}

ahora() {
  local sedes=("$@"); [ ${#sedes[@]} -eq 0 ] && sedes=("${SEDES[@]}")
  local fallo=0 ts; ts=$(date +%H%M%S)
  for s in "${sedes[@]}"; do
    local job="respaldo-manual-$ts"
    kubectl -n "sede-$s" create job "$job" --from=cronjob/respaldo >/dev/null
    if kubectl -n "sede-$s" wait --for=condition=complete "job/$job" --timeout=300s >/dev/null 2>&1; then
      kubectl -n "sede-$s" logs "job/$job" | grep RESPALDO_OK | sed "s/^/  /"
    else
      echo "  $s: FALLÓ el respaldo"; kubectl -n "sede-$s" logs "job/$job" --tail=20 | sed "s/^/    /" || true; fallo=1
    fi
  done
  return $fallo
}

estado() {
  local mal=0 ahora_s; ahora_s=$(date +%s)
  printf '%-11s %-19s %-9s %s\n' SEDE ÚLTIMO_ÉXITO EDAD ÚLTIMO_RESPALDO
  for s in "${SEDES[@]}"; do
    local ultimo horas="-" detalle="" marca="OK"
    ultimo=$(kubectl -n "sede-$s" get cronjob respaldo -o jsonpath='{.status.lastSuccessfulTime}' 2>/dev/null || true)
    if [ -z "$ultimo" ]; then
      marca="NUNCA"; mal=1
    else
      local t; t=$(date -d "$ultimo" +%s)
      horas=$(( (ahora_s - t) / 3600 ))h
      [ $(( (ahora_s - t) / 3600 )) -ge "$MAX_HORAS" ] && { marca="VENCIDO"; mal=1; }
      detalle=$(kubectl -n "sede-$s" logs -l app=respaldo --tail=-1 2>/dev/null | grep RESPALDO_OK | tail -1 | sed -E 's/.*archivo=([^ ]+) bytes=([0-9]+).*fuera_del_cluster=([a-z]+).*/\1 (\2 bytes, fuera del clúster: \3)/')
    fi
    printf '%-11s %-19s %-9s %s %s\n' "$s" "${ultimo:-nunca}" "$horas" "$marca" "$detalle"
  done
  return $mal
}

traer() {
  local destino=${1:-respaldos/cluster}
  imagen
  for s in "${SEDES[@]}"; do
    local ns="sede-$s" pod="respaldos-lector"
    mkdir -p "$destino/$s"
    kubectl -n "$ns" delete pod "$pod" --ignore-not-found >/dev/null
    kubectl -n "$ns" run "$pod" --image="$IMG" --image-pull-policy=Never --restart=Never --overrides='{
      "spec": {"securityContext": {"fsGroup": 70},
        "volumes": [{"name": "r", "persistentVolumeClaim": {"claimName": "respaldos"}}],
        "containers": [{"name": "respaldos-lector", "image": "'"$IMG"'", "imagePullPolicy": "Never", "command": ["sleep", "300"],
                        "volumeMounts": [{"name": "r", "mountPath": "/respaldos"}]}]}}' >/dev/null
    kubectl -n "$ns" wait --for=condition=Ready "pod/$pod" --timeout=120s >/dev/null
    kubectl -n "$ns" exec "$pod" -- tar cf - -C "/respaldos/$s" --exclude='.tmp-*' . | tar xf - -C "$destino/$s"
    kubectl -n "$ns" delete pod "$pod" --wait=false >/dev/null
    local n; n=$(find "$destino/$s" -name 'respaldo_*.tar.age' | wc -l)
    (cd "$destino/$s" && sha256sum -c --quiet ./*.sha256) && echo "  $s: $n respaldos copiados a $destino/$s y sumas SHA-256 correctas"
  done
}

verificar() {
  local archivo=${1:-}
  [ -n "$archivo" ] || archivo=$(find respaldos/cluster -name 'respaldo_*.tar.age' 2>/dev/null | sort | tail -1)
  [ -n "$archivo" ] && [ -f "$archivo" ] || { echo "No hay respaldo para verificar (use 'traer' primero o pase la ruta)"; exit 2; }
  [ -f "$CLAVE" ] || { echo "Falta la clave privada $CLAVE"; exit 2; }
  archivo=$(realpath "$archivo")      # acepta ruta relativa o absoluta (Docker necesita la absoluta)
  imagen
  local trabajo contenedor="respaldo_verif_$$"
  trabajo=$(mktemp -d)
  trap 'docker rm -f "$contenedor" >/dev/null 2>&1 || true; rm -rf "$trabajo"' RETURN
  echo "Respaldo: $archivo"

  docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/$CLAVE":/clave:ro -v "$archivo":/in:ro -v "$trabajo":/out "$IMG" \
    sh -c 'age -d -i /clave /in | tar xf - -C /out'
  chmod -R a+rX "$trabajo"
  echo "  descifrado correcto"

  local f
  for f in "$trabajo"/*.dump "$trabajo"/roles.sql; do
    local n sha esperado; n=$(basename "$f")
    sha=$(sha256sum "$f" | cut -d' ' -f1)
    esperado=$(grep -A0 "\"$n\"" "$trabajo/manifest.json" | sed -E 's/.*"sha256": "([0-9a-f]+)".*/\1/')
    [ "$sha" = "$esperado" ] || { echo "  FALLA: la suma de $n no coincide con el manifiesto"; return 1; }
  done
  echo "  sumas SHA-256 de los volcados coinciden con el manifiesto"

  docker run -d --name "$contenedor" -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=verif -e POSTGRES_DB=postgres \
    -v "$trabajo":/respaldo:ro --tmpfs /var/lib/postgresql/data postgres:16-alpine >/dev/null
  for _ in $(seq 1 40); do docker exec "$contenedor" pg_isready -q -h 127.0.0.1 -U admin 2>/dev/null && break; sleep 1; done
  sleep 2
  psql_v() { docker exec -i "$contenedor" psql -h 127.0.0.1 -U admin -v ON_ERROR_STOP=1 -Atq "$@"; }

  # roles: 'admin' ya existe en el contenedor desechable (ese error se ignora); el rol de réplica debe quedar creado
  docker exec -i "$contenedor" psql -h 127.0.0.1 -U admin -d postgres -q -f /respaldo/roles.sql >/dev/null 2>&1 || true
  [ "$(psql_v -d postgres -c "SELECT count(*) FROM pg_roles WHERE rolname = 'replicator'")" = "1" ] \
    || { echo "  FALLA: roles.sql no recreó el rol replicator"; return 1; }
  echo "  roles restaurados (incluido replicator)"

  local bd
  for bd in $(cd "$trabajo" && ls ./*.dump | sed 's#^\./##; s#\.dump$##'); do
    psql_v -d postgres -c "CREATE DATABASE $bd" >/dev/null
    docker exec "$contenedor" pg_restore -h 127.0.0.1 -U admin -d "$bd" --no-owner --no-subscriptions --exit-on-error "/respaldo/$bd.dump"
    echo "  base $bd restaurada sin errores"
  done

  local actual antes despues
  actual=$(psql_v -d historia_clinica -F ' ' -c "SELECT (SELECT count(*) FROM paciente), (SELECT count(*) FROM encuentro),
            (SELECT count(*) FROM diagnostico_encuentro), (SELECT count(*) FROM composicion_bundle), (SELECT count(*) FROM mpi_decision)")
  antes=$(sed -nE 's/.*"conteos_antes": "([^"]+)".*/\1/p' "$trabajo/manifest.json")
  despues=$(sed -nE 's/.*"conteos_despues": "([^"]+)".*/\1/p' "$trabajo/manifest.json")
  python3 - "$actual" "$antes" "$despues" <<'PY'
import sys
act, ant, des = ([int(x) for x in a.split()] for a in sys.argv[1:4])
nombres = "pacientes encuentros diagnósticos RDA decisiones_MPI".split()
malo = False
for n, a, lo, hi in zip(nombres, act, ant, des):
    ok = lo <= a <= hi        # la réplica sigue escribiendo mientras se vuelca: el valor debe estar entre el antes y el después
    malo |= not ok
    print(f"  {n:<15} restaurados={a:<6} manifiesto: {lo}..{hi}  {'OK' if ok else 'FALLA'}")
sys.exit(1 if malo else 0)
PY
  echo "Verificación de restauración: CORRECTA"
}

orden=${1:-}
[ $# -gt 0 ] && shift
case "$orden" in
  claves) claves ;;
  ahora) ahora "$@" ;;
  estado) estado ;;
  traer) traer "$@" ;;
  verificar) verificar "$@" ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
