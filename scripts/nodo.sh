#!/usr/bin/env bash
# Apaga, enciende o consulta una sede completa (base de datos, API y HAPI FHIR) para la demostración de «una sede cae y la vista sigue».
#
#   bash scripts/nodo.sh apagar 2             # Docker Compose (por defecto): apaga Cartagena
#   bash scripts/nodo.sh encender 2
#   bash scripts/nodo.sh estado
#   bash scripts/nodo.sh apagar 3 k8s         # Kubernetes/Minikube
#
# Mientras una sede está apagada, las otras dos siguen sirviendo su historia (la copia local) y la vista la marca como «no responde».
# No hay un botón en la aplicación a propósito: apagar contenedores desde la API exigiría darle el socket de Docker, que equivale a root en el equipo.
set -euo pipefail
cd "$(dirname "$0")/.."

ACCION=${1:-estado}; N=${2:-}; MODO=${3:-compose}
nombre() { case "$1" in 1) echo sincelejo ;; 2) echo cartagena ;; 3) echo corozal ;; *) echo "sede inválida: $1 (1, 2 o 3)" >&2; exit 2 ;; esac; }
if [ "$ACCION" != estado ]; then S=$(nombre "$N"); fi
case "$MODO" in
  compose)
    apagar()  { docker stop "api_$S" "pg_$S" >/dev/null; docker stop "hapi_$S" >/dev/null 2>&1 || true; }
    encender(){ docker start "pg_$S" >/dev/null; docker start "api_$S" >/dev/null; docker start "hapi_$S" >/dev/null 2>&1 || true; }
    estado()  { docker ps -a --format '{{.Names}} {{.Status}}' | grep -E '^(pg|api|hapi)_(sincelejo|cartagena|corozal) ' | sort; } ;;
  k8s)
    # El HAPI solo corre en las sedes que lo tengan activo (por defecto, Sincelejo: no caben tres): al apagar se anota cuántas réplicas tenía y al encender se restauran.
    apagar()  { prev=$(kubectl -n "sede-$S" get deploy/hapi -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)
                [ "${prev:-0}" -gt 0 ] && kubectl -n "sede-$S" annotate deploy/hapi --overwrite hc/replicas-previas="$prev" >/dev/null 2>&1 || true
                kubectl -n "sede-$S" scale deploy/api --replicas=0 >/dev/null; kubectl -n "sede-$S" scale sts/pg --replicas=0 >/dev/null
                kubectl -n "sede-$S" scale deploy/hapi --replicas=0 >/dev/null 2>&1 || true; }
    encender(){ prev=$(kubectl -n "sede-$S" get deploy/hapi -o jsonpath='{.metadata.annotations.hc/replicas-previas}' 2>/dev/null || true)
                kubectl -n "sede-$S" scale sts/pg --replicas=1 >/dev/null; kubectl -n "sede-$S" scale deploy/api --replicas=2 >/dev/null
                kubectl -n "sede-$S" scale deploy/hapi --replicas="${prev:-0}" >/dev/null 2>&1 || true; }
    estado()  { for s in sincelejo cartagena corozal; do echo "sede-$s: $(kubectl -n "sede-$s" get pods --no-headers 2>/dev/null | grep -E '^(api|pg|hapi)' | awk '{print $1" "$3}' | tr '\n' ' ')"; done; } ;;
  *) echo "modo desconocido: $MODO (compose|k8s)"; exit 2 ;;
esac
case "$ACCION" in
  apagar)   apagar;   echo "Sede $N ($S) apagada. Las otras dos siguen sirviendo su historia." ;;
  encender) encender; echo "Sede $N ($S) encendida: se pone al día sola con la réplica." ;;
  estado)   estado ;;
  *) echo "uso: $0 apagar|encender|estado [1|2|3] [compose|k8s]"; exit 2 ;;
esac
