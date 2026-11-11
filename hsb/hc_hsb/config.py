"""Configuración del HSB (todo por variables de entorno; nada de secretos en el código)."""
import os


def secreto(nombre: str, defecto: str = "") -> str:
    """Valor de una variable de entorno o, si existe `<NOMBRE>_FILE`, el contenido de ese archivo (convención de Docker secrets)."""
    ruta = os.getenv(nombre + "_FILE")
    if ruta:
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv(nombre, defecto)


def _mapa(texto: str) -> dict[int, str]:
    """'1=http://a,2=http://b' -> {1: 'http://a', 2: 'http://b'}"""
    salida = {}
    for par in filter(None, (p.strip() for p in texto.split(","))):
        clave, _, valor = par.partition("=")
        salida[int(clave)] = valor.strip().rstrip("/")
    return salida


SEDES = (1, 2, 3)

# Base propia del bus (cola, idempotencia, bitácora de estados, terminología)
DB_HOST = os.getenv("HSB_DB_HOST", "pg-hsb")
DB_PORT = int(os.getenv("HSB_DB_PORT", "5432"))
DB_NAME = os.getenv("HSB_DB_NAME", "hsb")
DB_USER = os.getenv("HSB_DB_USER", "hsb")
DB_PASSWORD = secreto("HSB_DB_PASSWORD")

# Destinos. FHIR: un HAPI por sede (HSB_FHIR_URLS="1=…,2=…,3=…") o uno solo para todas (HSB_FHIR_URL).
FHIR_URLS = _mapa(os.getenv("HSB_FHIR_URLS", ""))
FHIR_URL_DEFECTO = os.getenv("HSB_FHIR_URL", "").rstrip("/")
# API v2 de cada sede: el bus escribe por la API (regla de sede dueña, permisos, auditoría), nunca en las bases
API_URLS = _mapa(os.getenv("HSB_API_URLS", ""))
USUARIO_SERVICIO = os.getenv("HSB_USUARIO", "hsb")
CLAVE_SERVICIO = secreto("HSB_CLAVE")

# Seguridad de la entrada del bus (mismo secreto de firma que la API)
JWT_SECRETO = secreto("HC_JWT_SECRETO")
AUTH_ACTIVA = os.getenv("HSB_AUTH_ACTIVA", "true").lower() not in ("0", "false", "no")

# Reintentos: espera BASE * 2^(n-1) (1, 2, 4, 8… s) con tope; al llegar a MAX_INTENTOS el mensaje pasa a «muerto».
# Con los valores por defecto un HAPI que tarda ~90 s en volver (arranque en frío) alcanza a recuperarse.
MAX_INTENTOS = int(os.getenv("HSB_MAX_INTENTOS", "8"))
BACKOFF_BASE_S = float(os.getenv("HSB_BACKOFF_BASE_S", "1"))
BACKOFF_MAX_S = float(os.getenv("HSB_BACKOFF_MAX_S", "30"))
TIMEOUT_S = float(os.getenv("HSB_TIMEOUT_S", "10"))                # por llamada HTTP
# Tope de TODO un intento (HAPI + las llamadas a la sede): un destino a medias no deja colgado al emisor más que el gateway (60 s)
PLAZO_INTENTO_S = float(os.getenv("HSB_PLAZO_INTENTO_S", "25"))
# En un CSV, pasado este tiempo las filas restantes no se entregan en la petición: se encolan y las entrega el sondeo
PRESUPUESTO_S = float(os.getenv("HSB_PRESUPUESTO_S", "15"))
# Un mensaje que quedó a medias (el bus murió entre HAPI y el nodo) se retoma pasado este tiempo
RECUPERACION_S = float(os.getenv("HSB_RECUPERACION_S", "60"))
SONDEO_S = float(os.getenv("HSB_SONDEO_S", "0.5"))

# Valores por defecto al crear el encuentro en la sede cuando el mensaje no los trae
TIPO_DOCUMENTO = os.getenv("HSB_TIPO_DOCUMENTO", "CC")
ENTIDAD_RESPONSABLE = os.getenv("HSB_ENTIDAD_RESPONSABLE", "PART")
PAIS_RESIDENCIA = os.getenv("HSB_PAIS_RESIDENCIA", "COL")


def url_fhir(sede: int) -> str:
    return FHIR_URLS.get(sede) or FHIR_URL_DEFECTO


def url_api(sede: int) -> str:
    return API_URLS.get(sede, "")
