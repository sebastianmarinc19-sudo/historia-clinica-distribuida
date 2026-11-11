"""Configuración por variables de entorno (una instancia por sede)."""
import os


def secreto(nombre: str, defecto: str = "") -> str:
    """Valor de una variable de entorno o, si existe `<NOMBRE>_FILE`, el contenido de ese archivo (convención de Docker secrets)."""
    ruta = os.getenv(nombre + "_FILE")
    if ruta:
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv(nombre, defecto)


SEDE_ID = int(os.getenv("SEDE_ID", "1"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "historia_clinica")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "3"))
# Conexiones simultáneas por réplica de la API y espera máxima por una libre.
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "15"))
DB_POOL_ESPERA = float(os.getenv("DB_POOL_ESPERA", "10"))

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")
FHIR_TIMEOUT = float(os.getenv("FHIR_TIMEOUT", "30"))

# ----- Anclaje de la cabeza de la auditoría en las otras sedes (ver anclaje.py).
# HC_PARES = "1=http://api_sincelejo:8001,2=http://api_cartagena:8001,3=http://api_corozal:8001" (la propia sede se descarta sola).
def _cargar_pares() -> dict:
    pares = {}
    for trozo in os.getenv("HC_PARES", "").split(","):
        if "=" in trozo:
            sede, url = trozo.split("=", 1)
            if int(sede) != SEDE_ID:
                pares[int(sede)] = url.strip().rstrip("/")
    return pares


PARES = _cargar_pares()
ANCLA_INTERVALO_S = float(os.getenv("HC_ANCLA_INTERVALO_S", "10"))
ANCLA_TIMEOUT_S = float(os.getenv("HC_ANCLA_TIMEOUT_S", "1.5"))

# Umbral de coincidencia del MPI (Laboratorio N.º 5 / CU-11).
MPI_UMBRAL = float(os.getenv("MPI_UMBRAL", "0.9"))

# ----- Autenticación (ver auth.py). Con HC_AUTH_ACTIVA=false se desactiva (solo para depurar).
AUTH_ACTIVA = os.getenv("HC_AUTH_ACTIVA", "true").lower() not in ("0", "false", "no")
JWT_SECRETO = secreto("HC_JWT_SECRETO")
TOKEN_PERSONAL_S = int(float(os.getenv("HC_TOKEN_HORAS", "8")) * 3600)
TOKEN_PACIENTE_S = int(float(os.getenv("HC_TOKEN_PACIENTE_MIN", "30")) * 60)


def _cargar_usuarios() -> dict:
    """Usuarios del personal: JSON en base64 {usuario: {hash, rol, nombre}} (generado por scripts/credenciales.py)."""
    import base64
    import json
    crudo = secreto("HC_USUARIOS_B64")
    if not crudo:
        return {}
    return json.loads(base64.b64decode(crudo).decode("utf-8"))


USUARIOS = _cargar_usuarios()
