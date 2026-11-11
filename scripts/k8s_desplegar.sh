#!/usr/bin/env bash
# Despliega las 3 sedes, el gateway y Prometheus en Minikube.
#   minikube start --driver=docker --memory=2800 --cpus=3
#   bash scripts/k8s_desplegar.sh
#
# Resultado:
#   gateway     https://$(minikube ip):30443   (http :30100 solo redirige)
#   API sedes   http://$(minikube ip):30101 | 30102 | 30103
#   Prometheus  http://$(minikube ip):30090
set -euo pipefail
cd "$(dirname "$0")/.."

SEDES=(sincelejo cartagena corozal)

echo "== Imagen de la API =="
docker build -q -t hc-api:local app >/dev/null
minikube image rm docker.io/library/hc-api:local >/dev/null 2>&1 || true     # si no se quita, `image load` deja la imagen vieja
minikube image load hc-api:local
docker build -q -t hc-hsb:local hsb >/dev/null
minikube image rm docker.io/library/hc-hsb:local >/dev/null 2>&1 || true
minikube image load hc-hsb:local
docker build -q -t hc-backup:local infra/backup >/dev/null
minikube image rm docker.io/library/hc-backup:local >/dev/null 2>&1 || true
minikube image load hc-backup:local

echo "== Namespaces =="
kubectl apply -f infra/k8s/namespaces.yaml

echo "== Credenciales de laboratorio (secreto de firma y usuarios; iguales en las 3 sedes) =="
python3 scripts/credenciales.py >/dev/null            # crea credenciales/credenciales.json si no existe
JWT=$(python3 scripts/credenciales.py --valor jwt)
USUARIOS=$(python3 scripts/credenciales.py --valor usuarios_b64)
for s in "${SEDES[@]}"; do
  kubectl -n "sede-$s" create secret generic hc-auth --from-literal=HC_JWT_SECRETO="$JWT" \
      --from-literal=HC_USUARIOS_B64="$USUARIOS" --dry-run=client -o yaml | kubectl apply -f -
done
echo "(las claves están en credenciales/credenciales.json; no se publican)"

echo "== Clave de cifrado de los respaldos (la pública va a cada sede; la privada queda en credenciales/)"
bash scripts/respaldos.sh claves

echo "== Certificado TLS del gateway (CA de laboratorio) =="
python3 scripts/certificados.py >/dev/null
kubectl -n hc-gateway create secret tls gateway-tls --cert=credenciales/gateway.crt --key=credenciales/gateway.key \
    --dry-run=client -o yaml | kubectl apply -f -
echo "(CA para los clientes: credenciales/ca.crt)"

echo "== Sedes =="
for s in "${SEDES[@]}"; do
  kubectl kustomize --load-restrictor LoadRestrictionsNone "infra/k8s/overlays/$s" | kubectl apply -f -
done
# La imagen es `hc-api:local` con imagePullPolicy Never y los Secret llegan como variables: `apply` no cambia el Deployment, así que sin
# este reinicio los pods seguirían con el código y las claves anteriores.
for s in "${SEDES[@]}"; do kubectl -n "sede-$s" rollout restart deployment/api >/dev/null; done

echo "== Bus de integración (HSB): secretos, base propia y 2 réplicas =="
kubectl -n hc-hsb create secret generic hsb-secretos --from-literal=POSTGRES_PASSWORD="$(python3 scripts/credenciales.py --valor hsb_db)" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hc-hsb create secret generic hsb-auth --from-literal=HC_JWT_SECRETO="$JWT" \
    --from-literal=HSB_CLAVE="$(python3 scripts/credenciales.py --valor clave_hsb)" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/k8s/hsb/hsb.yaml
kubectl -n hc-hsb rollout restart deployment/hsb >/dev/null          # misma razón: imagen `hc-hsb:local` y claves por variables

echo "== Gateway y observabilidad =="
kubectl apply -f infra/k8s/gateway/gateway.yaml
kubectl -n hc-gateway rollout restart deployment/gateway >/dev/null     # nginx solo lee su configuración al arrancar
kubectl apply -f infra/k8s/observabilidad/prometheus.yaml
kubectl -n observabilidad rollout restart deployment/prometheus >/dev/null   # Prometheus solo lee su configuración al arrancar

echo "== Esperando a que todo esté listo =="
for s in "${SEDES[@]}"; do
  kubectl -n "sede-$s" rollout status statefulset/pg --timeout=300s
  kubectl -n "sede-$s" rollout status deployment/api --timeout=300s
  kubectl -n "sede-$s" wait --for=condition=complete job/replicacion-setup --timeout=300s
done
kubectl -n hc-hsb rollout status statefulset/pg-hsb --timeout=180s
kubectl -n hc-hsb rollout status deployment/hsb --timeout=180s
kubectl -n hc-gateway rollout status deployment/gateway --timeout=120s
kubectl -n observabilidad rollout status deployment/prometheus --timeout=180s

IP=$(minikube ip)
echo
echo "Listo. Gateway: https://$IP:30443 (CA: credenciales/ca.crt)   Prometheus: http://$IP:30090"
echo "APIs: http://$IP:30101 (Sincelejo)  :30102 (Cartagena)  :30103 (Corozal)"
echo "HAPI FHIR de Sincelejo arranca aparte (~6 min en frío): kubectl -n sede-sincelejo get pods -w"
