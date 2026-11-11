#!/usr/bin/env bash
# Empaqueta los manifiestos de Kubernetes listos para aplicar en un clúster que tire la imagen de un registro
# (los de infra/k8s/ usan `hc-api:local` con imagePullPolicy Never, pensados para Minikube).
#
#   bash scripts/empaquetar_manifiestos.sh ghcr.io/usuario/repo/api@sha256:... [carpeta]     # por defecto ./dist
set -euo pipefail
cd "$(dirname "$0")/.."

imagen=${1:?uso: empaquetar_manifiestos.sh IMAGEN[@sha256:...] [carpeta]}
salida=${2:-dist}
rm -rf "$salida"
mkdir -p "$salida"

for s in sincelejo cartagena corozal; do
  kubectl kustomize --load-restrictor LoadRestrictionsNone "infra/k8s/overlays/$s" \
    | sed -e "s#image: hc-api:local#image: ${imagen}#" -e "s#imagePullPolicy: Never#imagePullPolicy: IfNotPresent#" \
    > "$salida/sede-$s.yaml"
done
cp infra/k8s/namespaces.yaml "$salida/00-namespaces.yaml"
cp infra/k8s/gateway/gateway.yaml "$salida/10-gateway.yaml"
cp infra/k8s/observabilidad/prometheus.yaml "$salida/20-observabilidad.yaml"

if grep -l "hc-api:local" "$salida"/*.yaml; then
  echo "ERROR: quedó una referencia a hc-api:local" >&2
  exit 1
fi

cat > "$salida/LEEME.txt" <<TXT
Manifiestos de la historia clínica distribuida (3 sedes + gateway + Prometheus).
Imagen de la API: ${imagen}

Antes de aplicar hay que crear lo que NO va en los manifiestos (claves y certificados):
  python3 scripts/credenciales.py        # claves de laboratorio y secreto de firma (credenciales/credenciales.json)
  python3 scripts/certificados.py        # CA de laboratorio y certificado del gateway (credenciales/)
  para s in sincelejo cartagena corozal: kubectl -n sede-\$s create secret generic hc-auth \\
      --from-literal=HC_JWT_SECRETO="\$(python3 scripts/credenciales.py --valor jwt)" \\
      --from-literal=HC_USUARIOS_B64="\$(python3 scripts/credenciales.py --valor usuarios_b64)"
  kubectl -n hc-gateway create secret tls gateway-tls --cert=credenciales/gateway.crt --key=credenciales/gateway.key
Luego, en orden:
  kubectl apply -f 00-namespaces.yaml        (y crear los secretos de arriba)
  kubectl apply -f sede-sincelejo.yaml -f sede-cartagena.yaml -f sede-corozal.yaml
  kubectl apply -f 10-gateway.yaml -f 20-observabilidad.yaml
Para un despliegue real use claves y certificados de su organización, no los de laboratorio.
TXT
echo "Manifiestos en $salida/ con la imagen $imagen"
