"""Métricas Prometheus del bus. Los contadores de proceso (reintentos, entregas) se reinician con el bus; el estado de los mensajes,
los duplicados detectados, la latencia y el porcentaje de fallidos salen de la BASE, así que sobreviven a reinicios y cuadran entre réplicas."""
from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily

from . import db

RECIBIDOS = Counter("hsb_mensajes_recibidos_total", "Mensajes recibidos por esta réplica del bus", ["formato"])
DUPLICADOS = Counter("hsb_duplicados_total", "Reenvíos detectados como duplicados por esta réplica")
REINTENTOS = Counter("hsb_reintentos_total", "Intentos de entrega que fallaron y se reprogramaron")
ENTREGAS = Counter("hsb_entregas_total", "Entregas exitosas a un destino", ["destino"])
LATENCIA = Histogram("hsb_latencia_extremo_a_extremo_segundos", "Desde que llega el mensaje hasta que queda entregado",
                     buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120))

ESTADOS = ("recibido", "validado", "transformado", "entregado", "rechazado", "reintentando", "muerto")


class ColectorBase:
    def collect(self):
        try:
            conteos = {r["estado"]: r["n"] for r in db.consultar("SELECT estado, count(*) AS n FROM mensaje_bus GROUP BY estado")}
            extra = db.uno("""SELECT count(*) FILTER (WHERE recibido_en > now() - interval '1 minute') AS ultimo_minuto,
                                     coalesce(sum(duplicados), 0) AS duplicados,
                                     coalesce(avg(extract(epoch FROM entregado_en - recibido_en))
                                              FILTER (WHERE estado = 'entregado'), 0) AS latencia_media
                                FROM mensaje_bus""")
        except Exception:      # noqa: BLE001  (base caída: no se publican estas series)
            return
        g = GaugeMetricFamily("hsb_mensajes", "Mensajes por estado (valor de la base)", labels=["estado"])
        for e in ESTADOS:
            g.add_metric([e], conteos.get(e, 0))
        yield g
        total = sum(conteos.values())
        fallidos = conteos.get("rechazado", 0) + conteos.get("muerto", 0)
        for nombre, ayuda, valor in (
                ("hsb_mensajes_ultimo_minuto", "Mensajes recibidos en el último minuto", extra["ultimo_minuto"]),
                ("hsb_duplicados_detectados", "Reenvíos detectados como duplicados (acumulado en la base)", extra["duplicados"]),
                ("hsb_latencia_media_segundos", "Latencia media de extremo a extremo de lo entregado", float(extra["latencia_media"])),
                ("hsb_porcentaje_fallidos", "Rechazados y muertos sobre el total de mensajes (%)", round(100 * fallidos / total, 2) if total else 0.0)):
            m = GaugeMetricFamily(nombre, ayuda)
            m.add_metric([], valor)
            yield m


_registrado = False


def registrar_colector() -> None:
    global _registrado
    if not _registrado:
        REGISTRY.register(ColectorBase())
        _registrado = True
