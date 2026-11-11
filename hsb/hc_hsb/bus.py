"""Núcleo del bus: recepción, idempotencia, entrega con reintentos y cola de mensajes muertos.

Estados de un mensaje:  recibido -> validado -> transformado -> entregado
                                  \\-> rechazado (inválido, o el destino lo rechazó)
                        transformado -> reintentando (falla transitoria) -> entregado | muerto (se agotaron los intentos)
Todo el estado vive en la base del bus. Por eso el bus se puede reiniciar o replicar sin perder mensajes ni dejar pasar un duplicado, y un
mensaje que quedó a medias (el bus murió entre HAPI y el nodo) lo retoma el sondeo pasado RECUPERACION_S.
"""
import hashlib
import json
import logging
import threading
import time
from typing import Optional

from psycopg2.extras import Json

from . import config, csvlegado, db, destinos, fhir, metricas
from . import normalizador as nz

logger = logging.getLogger("hc_hsb")
HAPI = destinos.ClienteHapi()
SEDE = destinos.ClienteSede()


def log(evento: str, **campos) -> None:
    logger.info(json.dumps({"evento": evento, **campos}, ensure_ascii=False, default=str))


def _evento(conn, id_mensaje, estado: str, intento: int = 0, detalle: Optional[str] = None) -> None:
    db.ejecutar("INSERT INTO evento_mensaje (id_mensaje, estado, intento, detalle) VALUES (%s, %s, %s, %s)",
                (id_mensaje, estado, intento, detalle), conn)


def espera(intento: int) -> float:
    """Espera antes del siguiente intento: BASE * 2^(n-1), con tope (1, 2, 4, 8… s)."""
    return min(config.BACKOFF_BASE_S * 2 ** (intento - 1), config.BACKOFF_MAX_S)


# --------------------------------------------------------------------------------------- recepción
def terminologia() -> dict:
    filas = db.consultar("SELECT dx_local, cie10, descripcion FROM ref_terminologia")
    return {nz.clave_terminologia(f["dx_local"]): f for f in filas}


def _resumen(fila: dict) -> dict:
    salida = {"id_mensaje": str(fila["id_mensaje"]), "estado": fila["estado"], "clave": fila["clave"], "formato": fila["formato"],
              "tipo": fila["tipo"], "sede": fila["sede"], "documento": fila["documento"], "intentos": fila["intentos"]}
    if fila["motivos"]:
        salida["motivos"] = fila["motivos"]
    if fila["ultimo_error"] and fila["estado"] in ("reintentando", "muerto"):
        salida["ultimo_error"] = fila["ultimo_error"]
    return salida


def recibir(norm: nz.Normalizado, contenido: str, entregar_ahora: bool = True) -> dict:
    """Registra un mensaje ya normalizado (idempotente por clave) y, si es válido, intenta entregarlo.
    Con `entregar_ahora=False` (se agotó el presupuesto de tiempo de la petición) queda en cola y lo entrega el sondeo."""
    hash_c = hashlib.sha256(contenido.encode()).hexdigest()
    clave = norm.clave or f"sha256:{hash_c}"
    bundle = fhir.construir_bundle(norm.canonico) if norm.canonico else None
    estado = "transformado" if norm.canonico else "rechazado"
    metricas.RECIBIDOS.labels(norm.formato).inc()
    campos = (norm.formato, norm.tipo or None, norm.sede, norm.documento or None, estado, contenido, Json(norm.motivos),
              Json(norm.canonico) if norm.canonico else None, Json(bundle) if bundle else None)
    with db.conexion() as conn:
        fila = db.uno("""INSERT INTO mensaje_bus (clave, hash_contenido, formato, tipo, sede, documento, estado, contenido, motivos, canonico, bundle)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (clave) DO NOTHING RETURNING id_mensaje""", (clave, hash_c, *campos), conn)
        if fila is None:                                   # ya existe un mensaje con esa clave
            previo = db.uno("SELECT * FROM mensaje_bus WHERE clave = %s FOR UPDATE", (clave,), conn)
            if previo["estado"] == "rechazado" and previo["hash_contenido"] != hash_c:
                # el emisor corrigió el mensaje y lo reenvió con el mismo id: se procesa de nuevo
                db.ejecutar("""UPDATE mensaje_bus SET hash_contenido=%s, formato=%s, tipo=%s, sede=%s, documento=%s, estado=%s, contenido=%s,
                                      motivos=%s, canonico=%s, bundle=%s, intentos=0, hapi_ok=FALSE, nodo_ok=FALSE, ultimo_error=NULL,
                                      actualizado_en=now(), recibido_en=now() WHERE id_mensaje=%s""",
                            (hash_c, *campos, previo["id_mensaje"]), conn)
                id_mensaje = previo["id_mensaje"]
                _evento(conn, id_mensaje, "recibido", detalle="reenvío corregido de un mensaje rechazado")
            else:
                db.ejecutar("UPDATE mensaje_bus SET duplicados = duplicados + 1, actualizado_en = now() WHERE id_mensaje = %s",
                            (previo["id_mensaje"],), conn)
                _evento(conn, previo["id_mensaje"], "duplicado", detalle=f"reenvío; el mensaje original está {previo['estado']}")
                metricas.DUPLICADOS.inc()
                log("duplicado", id=str(previo["id_mensaje"]), clave=clave, estado_original=previo["estado"])
                return {"estado": "duplicado", "id_mensaje": str(previo["id_mensaje"]), "clave": clave, "estado_original": previo["estado"]}
        else:
            id_mensaje = fila["id_mensaje"]
            _evento(conn, id_mensaje, "recibido")
        if norm.canonico:
            _evento(conn, id_mensaje, "validado")
            _evento(conn, id_mensaje, "transformado", detalle="Bundle FHIR transaction")
        else:
            _evento(conn, id_mensaje, "rechazado", detalle="; ".join(norm.motivos))
    log("recibido", id=str(id_mensaje), clave=clave, estado=estado, formato=norm.formato, sede=norm.sede)
    if not norm.canonico:
        log("rechazado", id=str(id_mensaje), clave=clave, motivos=norm.motivos)
        return {"estado": "rechazado", "id_mensaje": str(id_mensaje), "clave": clave, "motivos": norm.motivos}
    if not entregar_ahora:
        with db.conexion() as conn:
            fila = db.uno("""UPDATE mensaje_bus SET estado = 'reintentando', proximo_intento = now(), actualizado_en = now()
                              WHERE id_mensaje = %s RETURNING *""", (id_mensaje,), conn)
            _evento(conn, id_mensaje, "reintentando", 0, "en cola: la petición agotó su presupuesto de tiempo; lo entrega el sondeo")
        log("en_cola", id=str(id_mensaje), clave=clave)
        return {**_resumen(fila), "en_cola": True}
    return entregar(id_mensaje)


def procesar_hl7(texto: str) -> dict:
    return recibir(nz.normalizar_hl7(texto), texto)


def procesar_csv(texto: str, sede: int) -> dict:
    filas = csvlegado.leer(texto)
    tabla = terminologia()
    resultados = []
    inicio = time.monotonic()
    for numero, fila in filas:
        contenido = ";".join(fila.get(c, "") for c in csvlegado.COLUMNAS)
        r = recibir(nz.normalizar_fila_csv(sede, numero, fila, tabla), contenido,
                    entregar_ahora=(time.monotonic() - inicio) < config.PRESUPUESTO_S)
        resultados.append({"fila": numero, "documento": fila.get("documento"), **r})
    cuenta = {}
    for r in resultados:
        cuenta[r["estado"]] = cuenta.get(r["estado"], 0) + 1
    return {"sede": sede, "filas": len(resultados), "por_estado": cuenta, "resultados": resultados}


# --------------------------------------------------------------------------------------- entrega
def entregar(id_mensaje) -> dict:
    """Un intento de entrega: primero HAPI y después el nodo de la sede (ambos idempotentes). Registra el resultado y reprograma si falla."""
    fila = db.uno("SELECT * FROM mensaje_bus WHERE id_mensaje = %s", (id_mensaje,))
    if fila is None or fila["estado"] in ("entregado", "rechazado", "muerto"):
        return _resumen(fila) if fila else {"estado": "inexistente"}
    intento = fila["intentos"] + 1
    plazo = time.monotonic() + config.PLAZO_INTENTO_S
    try:
        if not fila["hapi_ok"]:
            HAPI.enviar(fila["sede"], fila["bundle"], plazo)
            with db.conexion() as conn:
                db.ejecutar("UPDATE mensaje_bus SET hapi_ok = TRUE, actualizado_en = now() WHERE id_mensaje = %s", (id_mensaje,), conn)
                _evento(conn, id_mensaje, "hapi_ok", intento, "Bundle aceptado por HAPI")
            metricas.ENTREGAS.labels("hapi").inc()
        if not fila["nodo_ok"]:
            acciones = SEDE.entregar(fila["canonico"], plazo)
            with db.conexion() as conn:
                db.ejecutar("UPDATE mensaje_bus SET nodo_ok = TRUE, actualizado_en = now() WHERE id_mensaje = %s", (id_mensaje,), conn)
                _evento(conn, id_mensaje, "nodo_ok", intento, json.dumps(acciones, ensure_ascii=False))
            metricas.ENTREGAS.labels("nodo").inc()
        with db.conexion() as conn:
            actualizada = db.uno("""UPDATE mensaje_bus SET estado = 'entregado', intentos = %s, entregado_en = now(), actualizado_en = now(),
                                           proximo_intento = NULL, ultimo_error = NULL WHERE id_mensaje = %s RETURNING *""", (intento, id_mensaje), conn)
            _evento(conn, id_mensaje, "entregado", intento)
        metricas.LATENCIA.observe((actualizada["entregado_en"] - actualizada["recibido_en"]).total_seconds())
        log("entregado", id=str(id_mensaje), clave=fila["clave"], intento=intento)
        return _resumen(actualizada)
    except destinos.Transitorio as e:
        return _fallo_transitorio(fila, intento, str(e))
    except destinos.Rechazo as e:
        with db.conexion() as conn:
            actualizada = db.uno("""UPDATE mensaje_bus SET estado = 'rechazado', intentos = %s, actualizado_en = now(), proximo_intento = NULL,
                                           motivos = motivos || %s::jsonb, ultimo_error = %s WHERE id_mensaje = %s RETURNING *""",
                                 (intento, Json([str(e)]), str(e), id_mensaje), conn)
            _evento(conn, id_mensaje, "rechazado", intento, str(e))
        log("rechazado_por_destino", id=str(id_mensaje), clave=fila["clave"], motivo=str(e))
        return _resumen(actualizada)


def _fallo_transitorio(fila: dict, intento: int, error: str) -> dict:
    muerto = intento >= config.MAX_INTENTOS
    estado = "muerto" if muerto else "reintentando"
    pausa = 0 if muerto else espera(intento)
    with db.conexion() as conn:
        actualizada = db.uno("""UPDATE mensaje_bus SET estado = %s, intentos = %s, ultimo_error = %s, actualizado_en = now(),
                                       proximo_intento = CASE WHEN %s THEN NULL ELSE now() + make_interval(secs => %s) END
                                 WHERE id_mensaje = %s RETURNING *""", (estado, intento, error, muerto, pausa, fila["id_mensaje"]), conn)
        _evento(conn, fila["id_mensaje"], estado, intento, error + ("" if muerto else f" · próximo intento en {pausa:g} s"))
    metricas.REINTENTOS.inc()
    log("muerto" if muerto else "reintentando", id=str(fila["id_mensaje"]), clave=fila["clave"], intento=intento,
        maximo=config.MAX_INTENTOS, espera_s=pausa, error=error)
    return _resumen(actualizada)


def procesar_pendientes(limite: int = 10) -> int:
    """Toma (con SKIP LOCKED, así varias réplicas no se pisan) los mensajes que ya toca reintentar y los que quedaron a medias."""
    with db.conexion() as conn:
        ids = db.consultar(
            """UPDATE mensaje_bus SET actualizado_en = now(),
                      proximo_intento = CASE WHEN estado = 'reintentando' THEN now() + make_interval(secs => %s) ELSE proximo_intento END
                WHERE id_mensaje IN (
                    SELECT id_mensaje FROM mensaje_bus
                     WHERE (estado = 'reintentando' AND proximo_intento <= now())
                        OR (estado IN ('recibido', 'validado', 'transformado') AND actualizado_en < now() - make_interval(secs => %s))
                     ORDER BY actualizado_en LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING id_mensaje""", (config.RECUPERACION_S, config.RECUPERACION_S, limite), conn)
    for r in ids:
        entregar(r["id_mensaje"])
    return len(ids)


def reencolar(id_mensaje) -> Optional[dict]:
    """Devuelve un mensaje muerto a la cola con los contadores en cero (cuando el destino ya se recuperó)."""
    with db.conexion() as conn:
        fila = db.uno("""UPDATE mensaje_bus SET estado = 'reintentando', intentos = 0, proximo_intento = now(), ultimo_error = NULL,
                                actualizado_en = now() WHERE id_mensaje = %s AND estado = 'muerto' RETURNING *""", (id_mensaje,), conn)
        if fila:
            _evento(conn, id_mensaje, "reencolado", 0, "reencolado por un operador")
    if fila:
        log("reencolado", id=str(id_mensaje), clave=fila["clave"])
    return fila


# --------------------------------------------------------------------------------------- consulta
def listar(estado: Optional[str] = None, sede: Optional[int] = None, limite: int = 50) -> list[dict]:
    filtros, params = [], []
    if estado:
        filtros.append("estado = %s"); params.append(estado)
    if sede:
        filtros.append("sede = %s"); params.append(sede)
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    filas = db.consultar(f"""SELECT id_mensaje, clave, formato, tipo, sede, documento, estado, intentos, motivos, ultimo_error, duplicados,
                                    recibido_en, entregado_en FROM mensaje_bus {donde} ORDER BY recibido_en DESC LIMIT %s""", (*params, limite))
    return filas


def detalle(id_mensaje) -> Optional[dict]:
    fila = db.uno("SELECT * FROM mensaje_bus WHERE id_mensaje = %s", (id_mensaje,))
    if fila is None:
        return None
    fila["eventos"] = db.consultar("SELECT fecha, estado, intento, detalle FROM evento_mensaje WHERE id_mensaje = %s ORDER BY id_evento", (id_mensaje,))
    return fila


def resumen() -> dict:
    conteos = {r["estado"]: r["n"] for r in db.consultar("SELECT estado, count(*) AS n FROM mensaje_bus GROUP BY estado")}
    extra = db.uno("""SELECT count(*) FILTER (WHERE recibido_en > now() - interval '1 minute') AS ultimo_minuto,
                             coalesce(sum(duplicados), 0) AS duplicados,
                             avg(extract(epoch FROM entregado_en - recibido_en)) FILTER (WHERE estado = 'entregado') AS latencia_media_s
                        FROM mensaje_bus""")
    total = sum(conteos.values())
    fallidos = conteos.get("rechazado", 0) + conteos.get("muerto", 0)
    return {"total": total, "por_estado": {e: conteos.get(e, 0) for e in metricas.ESTADOS}, "ultimo_minuto": extra["ultimo_minuto"],
            "duplicados_detectados": int(extra["duplicados"]), "latencia_media_s": round(float(extra["latencia_media_s"] or 0), 4),
            "porcentaje_fallidos": round(100 * fallidos / total, 2) if total else 0.0}


# --------------------------------------------------------------------------------------- sondeo
_parar = threading.Event()


def _sondear() -> None:
    while not _parar.is_set():
        try:
            if procesar_pendientes() == 0:
                _parar.wait(config.SONDEO_S)
        except Exception as e:      # noqa: BLE001  (la base puede estar reiniciando: se vuelve a intentar)
            logger.warning(json.dumps({"evento": "sondeo_fallo", "error": str(e)[:200]}))
            _parar.wait(2)


def iniciar_sondeo() -> threading.Thread:
    _parar.clear()
    hilo = threading.Thread(target=_sondear, name="sondeo-hsb", daemon=True)
    hilo.start()
    return hilo


def detener_sondeo() -> None:
    _parar.set()

