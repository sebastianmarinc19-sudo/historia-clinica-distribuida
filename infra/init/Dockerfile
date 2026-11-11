# Servicio de inicialización de `docker compose up`: genera las claves y los certificados de laboratorio la primera vez.
FROM python:3.11-alpine
RUN apk add --no-cache openssl
COPY init.sh /init.sh
ENTRYPOINT ["sh", "/init.sh"]
