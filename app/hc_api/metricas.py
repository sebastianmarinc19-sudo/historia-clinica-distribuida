"""Métricas Prometheus de la sede (SLI para los SLO y para los experimentos SRE).

Series:
  hc_http_requests_total{sede,metodo,ruta,estado}      peticiones por ruta (plantilla, sin IDs)
  hc_http_request_duration_seconds{sede,ruta}          latencia (histograma)
  hc_db_up{sede}                                       1 si la base de la sede responde
  hc_fhir_up{sede}                                     1 si el HAPI FHIR de la sede responde
  hc_subscription_active{sede,suscripcion}             proceso de aplicación de réplica vivo
  hc_subscription_last_msg_age_seconds{sede,suscripcion}
  hc_replication_slot_lag_bytes{sede,slot}             WAL pendiente de enviar a cada par (≈ RPO)
  hc_replication_slot_active{sede,slot}                el par está conectado
  hc_auditoria_cadena_ok{sede}                         1 si la cadena de hash de la auditoría cuadra (última verificación)
  hc_auditoria_eventos{sede}                           eventos verificados en la última verificación

El retraso de réplica en bytes es la métrica clave de RPO: es lo que se
perdería si la sede dueña perdiera su disco en ese instante.
"""
import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from . import anclaje, config, db
from .fhir import FhirClient, FhirError, FhirNoDisponible

SEDE = str(config.SEDE_ID)

registro = CollectorRegistry()

PETICIONES = Counter("hc_http_requests_total", "Peticiones HTTP", ["sede", "metodo", "ruta", "estado"],
                     registry=registro)
LATENCIA = Histogram("hc_http_request_duration_seconds", "Latencia HTTP", ["sede", "ruta"],
                     buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30), registry=registro)
DB_UP = Gauge("hc_db_up", "La base de la sede responde", ["sede"], registry=registro)
FHIR_UP = Gauge("hc_fhir_up", "El HAPI FHIR de la sede responde", ["sede"], registry=registro)
SUSC_ACTIVA = Gauge("hc_subscription_active", "Suscripción de réplica activa", ["sede", "suscripcion"],
                    registry=registro)
SUSC_EDAD = Gauge("hc_subscription_last_msg_age_seconds", "Segundos desde el último mensaje de réplica",
                  ["sede", "suscripcion"], registry=registro)
SLOT_LAG = Gauge("hc_replication_slot_lag_bytes", "WAL pendiente de enviar a un par", ["sede", "slot"],
                 registry=registro)
SLOT_ACTIVO = Gauge("hc_replication_slot_active", "Par conectado al slot", ["sede", "slot"], registry=registro)

AUD_OK = Gauge("hc_auditoria_cadena_ok", "La cadena de hash de la auditoría cuadra", ["sede"], registry=registro)
AUD_EVENTOS = Gauge("hc_auditoria_eventos", "Eventos de auditoría verificados", ["sede"], registry=registro)
AUD_ANCLA = Gauge("hc_auditoria_ancla_ok", "Anclaje de la cabeza en las otras sedes: 1 coincide, 0 discrepancia, -1 sin confirmar", ["sede"], registry=registro)
_cache_aud = {"t": 0.0}
_VERIFICAR_CADA_S = 60

_sonda_fhir = FhirClient(config.FHIR_BASE_URL, 1.5)
_cache_fhir = {"t": 0.0, "ok": 0}


def registrar_peticion(metodo: str, ruta: str, estado: int, segundos: float) -> None:
    PETICIONES.labels(SEDE, metodo, ruta, str(estado)).inc()
    LATENCIA.labels(SEDE, ruta).observe(segundos)


def registrar_verificacion(resultado: dict) -> None:
    AUD_OK.labels(SEDE).set(1 if resultado["ok"] else 0)
    AUD_EVENTOS.labels(SEDE).set(resultado["verificados"])
    ancla = (resultado.get("anclaje") or {}).get("ok")
    AUD_ANCLA.labels(SEDE).set(-1 if ancla is None else (1 if ancla else 0))
    _cache_aud["t"] = time.time()


def _verificar_auditoria() -> None:
    """Verifica la cadena como mucho una vez por minuto (el recorrido es lineal en el número de eventos)."""
    if time.time() - _cache_aud["t"] < _VERIFICAR_CADA_S:
        return
    _cache_aud["t"] = time.time()
    try:
        registrar_verificacion(anclaje.verificar_completo(cache_s=15))
    except Exception:       # noqa: BLE001  (sin base no hay verificación: la serie conserva el último valor)
        pass


def _fhir_ok() -> int:
    # Cachea 5 s: Prometheus raspa seguido y no hay que cargar al HAPI.
    ahora = time.time()
    if ahora - _cache_fhir["t"] > 5:
        try:
            _sonda_fhir.estado()
            _cache_fhir["ok"] = 1
        except (FhirNoDisponible, FhirError):
            _cache_fhir["ok"] = 0
        _cache_fhir["t"] = ahora
    return _cache_fhir["ok"]


def _actualizar_gauges() -> None:
    SLOT_LAG.clear(); SLOT_ACTIVO.clear(); SUSC_ACTIVA.clear(); SUSC_EDAD.clear()
    FHIR_UP.labels(SEDE).set(_fhir_ok())
    try:
        with db.conexion() as conn:
            for s in db.consultar(
                    """SELECT s.subname, st.pid IS NOT NULL AS activa,
                              coalesce(extract(epoch FROM (now() - st.last_msg_receipt_time)), -1) AS edad
                         FROM pg_subscription s LEFT JOIN pg_stat_subscription st ON st.subid = s.oid""", conn=conn):
                SUSC_ACTIVA.labels(SEDE, s["subname"]).set(1 if s["activa"] else 0)
                SUSC_EDAD.labels(SEDE, s["subname"]).set(float(s["edad"]))
            for r in db.consultar(
                    """SELECT slot_name, active,
                              coalesce(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn), 0) AS lag
                         FROM pg_replication_slots WHERE slot_type = 'logical'""", conn=conn):
                SLOT_LAG.labels(SEDE, r["slot_name"]).set(float(r["lag"]))
                SLOT_ACTIVO.labels(SEDE, r["slot_name"]).set(1 if r["active"] else 0)
        DB_UP.labels(SEDE).set(1)
        _verificar_auditoria()
    except Exception:
        DB_UP.labels(SEDE).set(0)


def exportar() -> bytes:
    _actualizar_gauges()
    return generate_latest(registro)
