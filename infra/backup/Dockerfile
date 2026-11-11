# Imagen del respaldo programado de cada sede: clientes de PostgreSQL 16 + age (cifrado) + rclone (copia fuera del clúster).
# La construye scripts/k8s_desplegar.sh y la carga en Minikube (hc-backup:local), igual que la imagen de la API.
FROM postgres:16-alpine
RUN apk add --no-cache age rclone
COPY respaldar.sh retencion.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/respaldar.sh
