# credenciales/

Esta carpeta se llena sola la primera vez que se corre `docker compose up` (servicio `init`). **Nada de lo que genera se versiona** (`.gitignore`):

| Archivo | Qué es |
|---|---|
| `credenciales.json` | Claves **en claro** del personal de laboratorio y secreto de firma de los tokens (también: `python3 scripts/credenciales.py`) |
| `ca.crt` | Certificado de la CA de laboratorio: es lo que confían los clientes (`curl --cacert credenciales/ca.crt`, pruebas, importar en el navegador) |
| `ca.key` | Clave privada de la CA. Solo para firmar; ningún contenedor de las sedes la monta |
| `gateway.crt`, `gateway.key` | Certificado y clave del gateway |
| `runtime/` | Lo que monta cada servicio, y solo lo suyo: `api/`, `hsb/`, `pg_hsb/`, `gateway/` |

Para claves nuevas: `docker compose down -v`, borrar esta carpeta (menos este archivo) y volver a correr `docker compose up -d --build`.
