#!/bin/sh
# Crea (o reutiliza) las credenciales de laboratorio y los certificados TLS, y deja a cada servicio solo lo que necesita:
#
#   credenciales/credenciales.json, ca.key, ca.crt, gateway.*   para el operador (ignorados por git; las claves en claro y la clave de la CA)
#   credenciales/runtime/api       jwt, usuarios_b64              sedes (HC_JWT_SECRETO_FILE, HC_USUARIOS_B64_FILE)
#   credenciales/runtime/hsb       jwt, clave_hsb, hsb_db         bus de integración
#   credenciales/runtime/pg_hsb    hsb_db                         base del bus (POSTGRES_PASSWORD_FILE)
#   credenciales/runtime/gateway   gateway.crt, gateway.key       nginx
#
# Es idempotente: si ya existen no se tocan (para claves nuevas: borrar credenciales/ o `python3 scripts/credenciales.py --rotar`).
# Las sedes nunca montan la clave de la CA ni las claves en claro del personal.
set -eu
cd /app

python3 scripts/credenciales.py >/dev/null
if [ -n "${GATEWAY_IP_EXTRA:-}" ]; then python3 scripts/certificados.py --ip "$GATEWAY_IP_EXTRA" >/dev/null; else python3 scripts/certificados.py >/dev/null; fi

R=credenciales/runtime
mkdir -p "$R/api" "$R/hsb" "$R/pg_hsb" "$R/gateway"
valor() { python3 scripts/credenciales.py --valor "$1" | tr -d '\n'; }
escribir() { printf '%s' "$2" > "$1"; chmod 600 "$1"; }
escribir "$R/api/jwt" "$(valor jwt)"
escribir "$R/api/usuarios_b64" "$(valor usuarios_b64)"
escribir "$R/hsb/jwt" "$(valor jwt)"
escribir "$R/hsb/clave_hsb" "$(valor clave_hsb)"
escribir "$R/hsb/hsb_db" "$(valor hsb_db)"
escribir "$R/pg_hsb/hsb_db" "$(valor hsb_db)"
cp credenciales/gateway.crt credenciales/gateway.key "$R/gateway/"
chmod 600 "$R/gateway/gateway.key"

# Los archivos quedan a nombre de quien creó la carpeta en el equipo (no de root), para poder leerlos y borrarlos sin sudo.
DUENO=$(stat -c '%u:%g' /app/credenciales)
chown -R "$DUENO" /app/credenciales
echo "Credenciales y certificados listos en credenciales/ (las claves en claro: credenciales/credenciales.json; la CA: credenciales/ca.crt)."
