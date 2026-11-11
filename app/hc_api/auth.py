"""Autenticación y autorización por rol, sin servicio central.

Diseño (coherente con el resto del sistema: nada que sea punto único de falla):
  - Tokens JWT HS256 firmados con un secreto compartido por las tres sedes. Cualquier sede
    puede validar un token emitido por otra, y una sede aislada sigue autenticando.
  - Los usuarios del personal se definen por configuración (hash PBKDF2-HMAC-SHA256, nunca la
    clave). El paciente entra con su documento y su fecha de nacimiento, verificados contra
    la copia local de los pacientes, y recibe un token con alcance a SU documento.
  - Cinco roles: admisionista, medico, paciente, reportero y administrador (este último puede
    usar todas las funciones de personal; sirve para automatizar pruebas y operación).

Límites que se asumen (ver el documento): sin OAuth 2.0 / OpenID Connect ni proveedor de
identidad externo; los tokens no se pueden revocar antes de vencer; el tráfico es HTTP (sin
TLS) en el entorno de laboratorio, así que el token viaja sin cifrar.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import HTTPException, Request

from . import config

# hsb: cuenta de servicio del bus de integración (escribe en la sede por la API, nunca en la base).
# sistema_sede: la cuenta con la que un sistema legado de sede envía mensajes al bus (el bus la valida; la API no la usa).
ROLES = ("admisionista", "medico", "paciente", "reportero", "administrador", "hsb", "sistema_sede")
ITERACIONES = 200_000          # PBKDF2-HMAC-SHA256


class TokenInvalido(Exception):
    """El token no se puede aceptar (mal formado, firma incorrecta o vencido)."""


# ------------------------------------------------------------------ claves
def hash_clave(clave: str, sal: Optional[bytes] = None, iteraciones: int = ITERACIONES) -> str:
    sal = sal or secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, iteraciones)
    return f"pbkdf2_sha256${iteraciones}${_b64(sal)}${_b64(derivada)}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        esquema, iteraciones, sal, esperado = almacenado.split("$")
        if esquema != "pbkdf2_sha256":
            return False
        derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), _unb64(sal), int(iteraciones))
        return hmac.compare_digest(_b64(derivada), esperado)
    except Exception:
        return False


# ------------------------------------------------------------------ tokens
def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _unb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firmar(cuerpo: str, secreto: str) -> str:
    return _b64(hmac.new(secreto.encode(), cuerpo.encode(), hashlib.sha256).digest())


def emitir_token(sub: str, rol: str, secreto: str, ttl_segundos: int, ahora: Optional[float] = None, **extra) -> str:
    ahora = int(ahora if ahora is not None else time.time())
    cabecera = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    carga = _b64(json.dumps({"sub": sub, "rol": rol, "iat": ahora, "exp": ahora + ttl_segundos, **extra},
                            separators=(",", ":"), ensure_ascii=False).encode())
    return f"{cabecera}.{carga}.{_firmar(f'{cabecera}.{carga}', secreto)}"


def leer_token(token: str, secreto: str, ahora: Optional[float] = None) -> dict:
    try:
        cabecera, carga, firma = token.split(".")
        if json.loads(_unb64(cabecera)).get("alg") != "HS256":       # evita «alg: none» y similares
            raise TokenInvalido("Algoritmo no admitido")
    except TokenInvalido:
        raise
    except Exception as e:
        raise TokenInvalido("Token mal formado") from e
    if not hmac.compare_digest(firma, _firmar(f"{cabecera}.{carga}", secreto)):
        raise TokenInvalido("Firma incorrecta")
    try:
        datos = json.loads(_unb64(carga))
    except Exception as e:
        raise TokenInvalido("Token mal formado") from e
    if datos.get("exp", 0) <= (ahora if ahora is not None else time.time()):
        raise TokenInvalido("La sesión venció; inicie sesión de nuevo")
    if datos.get("rol") not in ROLES:
        raise TokenInvalido("Rol desconocido")
    return datos


# ------------------------------------------------------------------ usuario y dependencias
@dataclass
class Usuario:
    sub: str
    rol: str
    nombre: str = ""
    cod_tipo_documento: Optional[str] = None       # solo el rol paciente
    numero_documento: Optional[str] = None

    @property
    def es_paciente(self) -> bool:
        return self.rol == "paciente"

    def es_su_documento(self, tipo: Optional[str], numero: str) -> bool:
        return (self.es_paciente and self.numero_documento == numero
                and (tipo is None or self.cod_tipo_documento == tipo))


def requiere(*roles: str) -> Callable[[Request], Usuario]:
    """Dependencia de FastAPI: exige sesión y que el rol esté entre `roles` (el administrador pasa siempre)."""
    def dependencia(request: Request) -> Usuario:
        if not config.AUTH_ACTIVA:
            usuario = Usuario("sin-autenticacion", "administrador", "Autenticación desactivada")
            request.state.usuario = usuario
            return usuario
        encabezado = request.headers.get("Authorization", "")
        if not encabezado.startswith("Bearer "):
            raise HTTPException(401, "Se requiere iniciar sesión", headers={"WWW-Authenticate": "Bearer"})
        try:
            datos = leer_token(encabezado[7:], config.JWT_SECRETO)
        except TokenInvalido as e:
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"}) from e
        usuario = Usuario(datos["sub"], datos["rol"], datos.get("nombre", ""),
                          datos.get("tipo"), datos.get("doc"))
        request.state.usuario = usuario
        if roles and usuario.rol not in roles and usuario.rol != "administrador":
            raise HTTPException(403, f"El rol «{usuario.rol}» no puede usar esta función")
        return usuario
    return dependencia


# ------------------------------------------------------------------ limitación de intentos
_fallos: dict[str, list[float]] = {}
MAX_FALLOS = 8
VENTANA_S = 300


def demasiados_fallos(clave: str, ahora: Optional[float] = None) -> bool:
    ahora = ahora if ahora is not None else time.time()
    recientes = [t for t in _fallos.get(clave, []) if ahora - t < VENTANA_S]
    _fallos[clave] = recientes
    return len(recientes) >= MAX_FALLOS


def registrar_fallo(clave: str, ahora: Optional[float] = None) -> None:
    _fallos.setdefault(clave, []).append(ahora if ahora is not None else time.time())
