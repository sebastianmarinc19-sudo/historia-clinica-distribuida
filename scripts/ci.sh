#!/usr/bin/env bash
# Chequeos de calidad que corre el CI (.github/workflows/ci.yml). Se ejecutan igual en local: solo necesitan Docker
# (y kubectl para `manifiestos`). Cada paso usa contenedores, así el resultado no depende de lo instalado en la máquina.
#
#   bash scripts/ci.sh              # todos los pasos
#   bash scripts/ci.sh lint sql     # solo algunos
#
# Pasos: lint (ruff + shellcheck) · respaldos (retención) · hsb (normalizador, FHIR y bus con PostgreSQL real) · unitarias · sql (29 pruebas de restricciones en un Postgres limpio)
#        manifiestos (kustomize + kubeconform) · secretos (gitleaks sobre todo el historial + archivos sensibles versionados)
set -euo pipefail
cd "$(dirname "$0")/.."

RUFF=0.8.6
PG=postgres:16-alpine

lint() {
  echo "== lint: ruff (errores de sintaxis y pyflakes) =="
  docker run --rm -v "$PWD":/w -w /w python:3.11-slim sh -c \
    "pip install -q ruff==$RUFF 2>&1 | tail -0; ruff check --no-cache --select E9,F app hsb scripts tests docs"
  echo "== lint: shellcheck =="
  # shellcheck disable=SC2046
  docker run --rm -v "$PWD":/mnt -w /mnt koalaman/shellcheck:stable --severity=warning $(ls scripts/*.sh db/*.sh infra/backup/*.sh fhir/*.sh tests/coleccion/*.sh)
}

respaldos() {
  echo "== respaldos: lógica de retención =="
  docker run --rm -v "$PWD/infra/backup":/b alpine sh /b/probar_retencion.sh
}

hsb() {
  echo "== HSB: unitarias e integración (PostgreSQL real, destinos simulados) =="
  bash scripts/prueba_hsb.sh -q
}

unitarias() {
  echo "== pruebas unitarias de la API =="
  docker build -q -t hc-api:local app >/dev/null
  docker run --rm -e HC_JWT_SECRETO=ci -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD/app":/app -v "$PWD/tests/api":/app/tests -w /app hc-api:local \
    python -m pytest -q -p no:cacheprovider tests/test_unitarias.py
}

sql() {
  echo "== pruebas SQL de restricciones (Postgres limpio) =="
  local nombre="ci_pg_$$"
  # --tmpfs en lugar de un volumen anónimo: la imagen de postgres declara VOLUME y, sin esto, cada corrida deja ~50 MB huérfanos
  docker run -d --name "$nombre" --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=ci -e POSTGRES_DB=historia_clinica "$PG" >/dev/null
  trap 'docker rm -fv "$nombre" >/dev/null 2>&1 || true' RETURN
  for _ in $(seq 1 30); do
    docker exec "$nombre" pg_isready -h 127.0.0.1 -U postgres -d historia_clinica >/dev/null 2>&1 && break
    sleep 1
  done
  sleep 2
  for f in db/01_esquema_57_campos.sql db/02_semillas_catalogos.sql db/tests/test_restricciones.sql; do
    docker exec -i "$nombre" psql -U postgres -d historia_clinica -v ON_ERROR_STOP=1 -q < "$f" | grep -E "NOTICE|ERROR" || true
  done
}

manifiestos() {
  echo "== manifiestos de Kubernetes (kustomize + kubeconform) =="
  command -v kubectl >/dev/null || { echo "falta kubectl"; return 1; }
  local d; d=$(mktemp -d)
  for s in sincelejo cartagena corozal; do
    kubectl kustomize --load-restrictor LoadRestrictionsNone "infra/k8s/overlays/$s" > "$d/$s.yaml"
  done
  cp infra/k8s/namespaces.yaml infra/k8s/gateway/gateway.yaml infra/k8s/observabilidad/prometheus.yaml infra/k8s/hsb/hsb.yaml "$d/"
  docker run --rm -v "$d":/m ghcr.io/yannh/kubeconform:latest -strict -summary -kubernetes-version 1.30.0 /m
  rm -rf "$d"
}

secretos() {
  echo "== secretos: archivos sensibles versionados =="
  if git ls-files | grep -E '(^|/)\.env$|(^|/)credenciales/|\.(key|pem)$' | grep -v -E '^credenciales/LEEME\.md$'; then
    echo "ERROR: hay claves o certificados versionados"; return 1
  fi
  echo "ninguno"
  echo "== secretos: gitleaks sobre el historial =="
  docker run --rm -v "$PWD":/repo zricethezav/gitleaks:latest detect --source /repo --no-banner --redact
}

pasos=("$@")
[ ${#pasos[@]} -eq 0 ] && pasos=(lint respaldos hsb unitarias sql manifiestos secretos)
for p in "${pasos[@]}"; do
  case "$p" in
    lint|respaldos|hsb|unitarias|sql|manifiestos|secretos) "$p" ;;
    *) echo "paso desconocido: $p (lint respaldos hsb unitarias sql manifiestos secretos)"; exit 2 ;;
  esac
done
echo
echo "CI local: todo en orden (${pasos[*]})"
