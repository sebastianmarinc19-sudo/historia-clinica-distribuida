#!/usr/bin/env python3
"""Genera las credenciales de LABORATORIO del personal y el secreto de firma de los tokens.

    python3 scripts/credenciales.py                 # crea (o reutiliza) credenciales/credenciales.json y las muestra
    python3 scripts/credenciales.py --rotar         # genera claves nuevas (invalida las sesiones vigentes)
    python3 scripts/credenciales.py --env           # además escribe .env para Docker Compose
    python3 scripts/credenciales.py --valor jwt     # imprime solo un valor: jwt | usuarios_b64 | usuarios_claro | clave_hsb | hsb_db

El archivo credenciales/credenciales.json contiene las claves EN CLARO (para entrar a las vistas y para
las pruebas): está en .gitignore y no debe publicarse. Las sedes solo reciben el secreto de firma y los
hashes PBKDF2 (variables HC_JWT_SECRETO y HC_USUARIOS_B64). Solo biblioteca estándar.

Las claves son aleatorias por instalación: no hay contraseñas por defecto en el repositorio.
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARCHIVO = os.path.join(RAIZ, "credenciales", "credenciales.json")
ITERACIONES = 200_000        # debe coincidir con hc_api.auth.ITERACIONES

USUARIOS = {                  # usuario -> (rol, nombre para mostrar)
    "admision": ("admisionista", "Admisionista de laboratorio"),
    "medico": ("medico", "Médico de laboratorio"),
    "reportero": ("reportero", "Reportero de laboratorio"),
    "auditor": ("reportero", "Auditor de laboratorio"),                    # el «auditor» de la guía del parcial: mismo rol que el reportero
    "admin": ("administrador", "Administrador de laboratorio"),
    "hsb": ("hsb", "Bus de integración (cuenta de servicio)"),            # el HSB escribe en las sedes con esta cuenta
    "sede": ("sistema_sede", "Sistema legado de sede (envía mensajes al HSB)"),
}


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${_b64(sal)}${_b64(derivada)}"


def generar() -> dict:
    claro = {u: {"rol": rol, "nombre": nombre, "clave": secrets.token_urlsafe(9)} for u, (rol, nombre) in USUARIOS.items()}
    return {"jwt_secreto": secrets.token_urlsafe(48), "usuarios": claro}


def cargar_o_crear(rotar: bool) -> dict:
    if os.path.exists(ARCHIVO) and not rotar:
        with open(ARCHIVO, encoding="utf-8") as f:
            datos = json.load(f)
        faltan = [u for u in USUARIOS if u not in datos["usuarios"]]
        if faltan:                    # usuarios nuevos del proyecto: se agregan sin cambiar las claves que ya existen
            for u in faltan:
                rol, nombre = USUARIOS[u]
                datos["usuarios"][u] = {"rol": rol, "nombre": nombre, "clave": secrets.token_urlsafe(9)}
            datos.pop("usuarios_b64", None)
            with open(ARCHIVO, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
        return datos
    datos = generar()
    os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.chmod(ARCHIVO, 0o600)
    return datos


def usuarios_b64(datos: dict) -> str:
    hashes = {u: {"hash": hash_clave(v["clave"]), "rol": v["rol"], "nombre": v["nombre"]} for u, v in datos["usuarios"].items()}
    return base64.b64encode(json.dumps(hashes, ensure_ascii=False).encode()).decode()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotar", action="store_true", help="genera claves nuevas")
    ap.add_argument("--env", action="store_true", help="escribe .env para docker compose")
    ap.add_argument("--valor", choices=["jwt", "usuarios_b64", "usuarios_claro", "clave_hsb", "hsb_db"], help="imprime solo ese valor")
    a = ap.parse_args()

    datos = cargar_o_crear(a.rotar)
    if a.valor:
        if a.valor == "jwt":
            print(datos["jwt_secreto"])
        elif a.valor == "usuarios_b64":
            # Los hashes llevan sal aleatoria: se fijan una vez en el archivo para que todas las sedes reciban lo mismo.
            if "usuarios_b64" not in datos:
                datos["usuarios_b64"] = usuarios_b64(datos)
                with open(ARCHIVO, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2)
            print(datos["usuarios_b64"])
        elif a.valor == "clave_hsb":
            print(datos["usuarios"]["hsb"]["clave"])
        elif a.valor == "hsb_db":           # contraseña de la base propia del bus
            if "hsb_db" not in datos:
                datos["hsb_db"] = secrets.token_urlsafe(18)
                with open(ARCHIVO, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2)
            print(datos["hsb_db"])
        else:
            print(json.dumps(datos["usuarios"], ensure_ascii=False))
        return 0

    if "usuarios_b64" not in datos or a.rotar:
        datos["usuarios_b64"] = usuarios_b64(datos)
        with open(ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    if a.env:
        ruta = os.path.join(RAIZ, ".env")
        with open(ruta, "w", encoding="utf-8") as f:
            if "hsb_db" not in datos:
                datos["hsb_db"] = secrets.token_urlsafe(18)
                with open(ARCHIVO, "w", encoding="utf-8") as g:
                    json.dump(datos, g, ensure_ascii=False, indent=2)
            f.write(f"HC_JWT_SECRETO={datos['jwt_secreto']}\nHC_USUARIOS_B64={datos['usuarios_b64']}\n"
                    f"HSB_CLAVE={datos['usuarios']['hsb']['clave']}\nHSB_DB_CLAVE={datos['hsb_db']}\n")
        os.chmod(ruta, 0o600)
        print(f"Escrito {ruta} (ignorado por git).")
    print(f"Credenciales de laboratorio en {os.path.relpath(ARCHIVO, RAIZ)} (no publicar):\n")
    print(f"  {'usuario':<11} {'rol':<14} clave")
    for u, v in datos["usuarios"].items():
        print(f"  {u:<11} {v['rol']:<14} {v['clave']}")
    print("\n  Pacientes: entran con su documento y fecha de nacimiento (no tienen cuenta).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
