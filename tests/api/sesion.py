"""Inicio de sesión para pruebas y scripts (solo biblioteca estándar).

Las claves de laboratorio salen de la variable HC_CREDENCIALES (JSON con las de `scripts/credenciales.py
--valor usuarios_claro`) o, si no está, de credenciales/credenciales.json. El token que emite una sede vale
en las otras dos (misma clave de firma), así que se pide una sola vez por usuario.
"""
import json
import os
import ssl
import urllib.request

_RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_tokens: dict = {}


def ca() -> str:
    """Ruta de la CA de laboratorio que confía el cliente (HC_CA o credenciales/ca.crt)."""
    return os.getenv("HC_CA") or os.path.join(_RAIZ, "credenciales", "ca.crt")


def contexto() -> ssl.SSLContext:
    """Contexto TLS para urllib: verifica el certificado del gateway contra la CA de laboratorio."""
    return ssl.create_default_context(cafile=ca())


def verificar():
    """Valor `verify=` para httpx."""
    return ca()


def credenciales() -> dict:
    crudo = os.getenv("HC_CREDENCIALES")
    if crudo:
        return json.loads(crudo)
    with open(os.path.join(_RAIZ, "credenciales", "credenciales.json"), encoding="utf-8") as f:
        return json.load(f)["usuarios"]


def _base(url: str) -> str:
    return url.split("/api/v2")[0]


def iniciar(base: str, usuario: str, clave: str) -> str:
    req = urllib.request.Request(base + "/api/v2/auth/login", method="POST",
                                 data=json.dumps({"usuario": usuario, "clave": clave}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20, context=contexto()) as r:
        return json.loads(r.read())["token"]


def token(base: str, usuario: str = "admin") -> str:
    if usuario not in _tokens:
        _tokens[usuario] = iniciar(_base(base), usuario, credenciales()[usuario]["clave"])
    return _tokens[usuario]


def cabecera(url: str, usuario: str = "admin") -> dict:
    """Cabecera Authorization para una URL de la API v2; vacía para lo demás (Prometheus, salud) o si la sede no responde."""
    if "/api/v2/" not in url or "/api/v2/auth/" in url:
        return {}
    try:
        return {"Authorization": "Bearer " + token(url, usuario)}
    except Exception:
        return {}
