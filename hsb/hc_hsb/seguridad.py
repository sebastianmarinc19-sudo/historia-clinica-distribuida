"""Autenticación de la entrada del bus: tokens JWT HS256 que emite la API de las sedes (mismo secreto de firma).

Roles del bus:  sistema_sede -> envía mensajes · admisionista / medico / reportero -> consultan el estado · administrador -> todo (incluye reencolar).
Un acceso sin sesión devuelve 401 y uno con un rol que no corresponde devuelve 403; ambos se registran en el log.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import config

logger = logging.getLogger("hc_hsb.seguridad")


@dataclass
class Usuario:
    sub: str
    rol: str


class TokenInvalido(Exception):
    pass


def _b64d(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def leer_token(token: str, secreto: str, ahora: float | None = None) -> dict:
    try:
        cab, carga, firma = token.split(".")
        if json.loads(_b64d(cab)).get("alg") != "HS256":
            raise TokenInvalido("algoritmo no permitido")
        esperada = hmac.new(secreto.encode(), f"{cab}.{carga}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(esperada, _b64d(firma)):
            raise TokenInvalido("firma inválida")
        datos = json.loads(_b64d(carga))
    except TokenInvalido:
        raise
    except Exception as e:      # noqa: BLE001
        raise TokenInvalido("token mal formado") from e
    if datos.get("exp", 0) < (ahora if ahora is not None else time.time()):
        raise TokenInvalido("token vencido")
    if not datos.get("sub") or not datos.get("rol"):
        raise TokenInvalido("token sin sujeto o rol")
    return datos


def requiere(*roles: str):
    """Dependencia de FastAPI: exige sesión y que el rol esté entre `roles` (el administrador pasa siempre)."""
    def dependencia(request: Request) -> Usuario:
        if not config.AUTH_ACTIVA:
            return Usuario("sin-autenticacion", "administrador")
        encabezado = request.headers.get("Authorization", "")
        if not encabezado.startswith("Bearer "):
            logger.warning(json.dumps({"evento": "acceso_denegado", "estado": 401, "ruta": request.url.path, "motivo": "sin sesión"}))
            raise HTTPException(401, "Se requiere iniciar sesión", headers={"WWW-Authenticate": "Bearer"})
        try:
            datos = leer_token(encabezado[7:], config.JWT_SECRETO)
        except TokenInvalido as e:
            logger.warning(json.dumps({"evento": "acceso_denegado", "estado": 401, "ruta": request.url.path, "motivo": str(e)}))
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"}) from e
        usuario = Usuario(datos["sub"], datos["rol"])
        if roles and usuario.rol not in roles and usuario.rol != "administrador":
            logger.warning(json.dumps({"evento": "acceso_denegado", "estado": 403, "ruta": request.url.path, "usuario": usuario.sub,
                                       "rol": usuario.rol, "requiere": list(roles)}))
            raise HTTPException(403, f"El rol «{usuario.rol}» no puede usar esta función")
        return usuario
    return dependencia
