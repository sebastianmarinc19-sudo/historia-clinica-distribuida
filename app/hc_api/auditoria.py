"""Auditoría encadenada por hash (trazabilidad de quién consultó o modificó datos de pacientes).

Tabla `evento_auditoria` propia de cada sede: NO se replica (cada sede responde por los accesos que recibió). Cada evento guarda
`hash = SHA-256(hash_previo + contenido canónico)`, de modo que modificar, borrar, insertar o reordenar un evento rompe la cadena
desde ese punto y `verificar()` lo señala. Las escrituras exitosas devuelven al cliente el «sello» (secuencia y hash) de su evento.

Qué protege y qué no: detecta alteraciones hechas sin recalcular la cadena (un UPDATE o DELETE a mano, una fila insertada). Un
administrador de la base que recalcule todos los hashes desde el punto alterado no se detecta con la sola cadena: haría falta anclar
la cabeza de la cadena fuera de la sede (otra sede, un registro externo). La tabla es de solo anexar para la aplicación (un
disparador rechaza UPDATE, DELETE y TRUNCATE), pero quien tenga permisos de DDL puede desactivarlo. No guarda el cuerpo de las peticiones.
"""
import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Iterable, Optional

from . import config, db

logger = logging.getLogger("hc_api.auditoria")

# Clave del candado de la base que serializa los anexos entre las réplicas de la API de una misma sede.
_CANDADO_CADENA = 7_101_001
_creada = False
_candado_creacion = threading.Lock()


def hash_genesis(id_sede: int) -> str:
    """«hash previo» del primer evento: distinto por sede, para que una cadena no se pueda trasplantar a otra."""
    return hashlib.sha256(f"historia-clinica-distribuida/auditoria/sede-{id_sede}".encode()).hexdigest()


def instante_iso(instante: datetime) -> str:
    """Forma textual estable del instante (UTC, microsegundos) que entra en el hash."""
    return instante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def contenido_canonico(e: dict) -> str:
    """Los campos que protege el hash, en un orden fijo y con serialización determinista."""
    return json.dumps([e["seq"], instante_iso(e["instante"]), e["id_sede"], e.get("usuario"), e.get("rol"), e["metodo"],
                       e["ruta"], e.get("documento"), e["estado"], e.get("ip")],
                      ensure_ascii=False, separators=(",", ":"))


def calcular_hash(hash_previo: str, e: dict) -> str:
    return hashlib.sha256((hash_previo + contenido_canonico(e)).encode()).hexdigest()


def verificar_cadena(eventos: Iterable[dict], id_sede: int, desde: Optional[tuple[int, str]] = None) -> dict:
    """Recorre los eventos en orden de secuencia y devuelve el primer punto en que la cadena no cuadra.

    `desde` = (seq, hash) del último evento ya verificado, para continuar un recorrido por tramos.
    Detecta: contenido alterado, hash alterado, evento borrado o insertado en medio (salto de secuencia o de hash previo)
    y cadena que no empieza en el génesis de la sede.
    """
    esperado_seq, esperado_previo = (desde[0] + 1, desde[1]) if desde else (1, hash_genesis(id_sede))
    total, ultimo = 0, desde
    for e in eventos:
        if e["seq"] != esperado_seq:
            return {"ok": False, "verificados": total, "primer_fallo": {"seq": e["seq"], "motivo": (
                f"salto de secuencia: se esperaba {esperado_seq} y hay {e['seq']} (evento borrado o insertado)")}, "ultimo": ultimo}
        if e["hash_previo"] != esperado_previo:
            return {"ok": False, "verificados": total, "primer_fallo": {"seq": e["seq"], "motivo": (
                "el hash previo no es el hash del evento anterior (cadena rota)")}, "ultimo": ultimo}
        if calcular_hash(e["hash_previo"], e) != e["hash"]:
            return {"ok": False, "verificados": total, "primer_fallo": {"seq": e["seq"], "motivo": (
                "el contenido del evento no corresponde a su hash (evento alterado)")}, "ultimo": ultimo}
        total += 1
        esperado_seq, esperado_previo = e["seq"] + 1, e["hash"]
        ultimo = (e["seq"], e["hash"])
    return {"ok": True, "verificados": total, "primer_fallo": None, "ultimo": ultimo}


# --------------------------------------------------------------------------------------------- base de datos
def _asegurar_tabla(conn) -> None:
    global _creada
    if _creada:
        return
    with _candado_creacion:
        if _creada:
            return
        db.ejecutar("SELECT pg_advisory_xact_lock(%s)", (_CANDADO_CADENA,), conn)
        db.ejecutar("""CREATE TABLE IF NOT EXISTS evento_auditoria (
                           seq BIGINT PRIMARY KEY, instante TIMESTAMPTZ NOT NULL, id_sede INT NOT NULL,
                           usuario TEXT, rol TEXT, metodo TEXT NOT NULL, ruta TEXT NOT NULL, documento TEXT,
                           estado INT NOT NULL, ip TEXT,
                           hash_previo CHAR(64) NOT NULL, hash CHAR(64) NOT NULL UNIQUE)""", conn=conn)
        db.ejecutar("""CREATE OR REPLACE FUNCTION evento_auditoria_solo_anexar() RETURNS trigger LANGUAGE plpgsql AS $$
                       BEGIN RAISE EXCEPTION 'evento_auditoria es de solo anexar (no admite % )', TG_OP; END $$""", conn=conn)
        db.ejecutar("""DO $$ BEGIN
                           IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'evento_auditoria_inmutable') THEN
                             CREATE TRIGGER evento_auditoria_inmutable BEFORE UPDATE OR DELETE ON evento_auditoria
                               FOR EACH ROW EXECUTE FUNCTION evento_auditoria_solo_anexar();
                             CREATE TRIGGER evento_auditoria_sin_truncate BEFORE TRUNCATE ON evento_auditoria
                               FOR EACH STATEMENT EXECUTE FUNCTION evento_auditoria_solo_anexar();
                           END IF; END $$""", conn=conn)
        _creada = True


def anexar(usuario: Optional[str], rol: Optional[str], metodo: str, ruta: str, documento: Optional[str],
           estado: int, ip: Optional[str]) -> Optional[dict]:
    """Agrega un evento a la cadena y devuelve su sello. Nunca propaga errores: auditar no debe tumbar la petición."""
    try:
        with db.conexion() as conn:
            _asegurar_tabla(conn)
            # El candado de transacción serializa a todas las réplicas: dos anexos simultáneos no pueden leer la misma cabeza.
            db.ejecutar("SELECT pg_advisory_xact_lock(%s)", (_CANDADO_CADENA,), conn)
            cabeza = db.uno("SELECT seq, hash FROM evento_auditoria ORDER BY seq DESC LIMIT 1", conn=conn)
            e = {"seq": (cabeza["seq"] + 1) if cabeza else 1, "instante": datetime.now(timezone.utc), "id_sede": config.SEDE_ID,
                 "usuario": usuario, "rol": rol, "metodo": metodo, "ruta": ruta, "documento": documento, "estado": estado, "ip": ip}
            e["hash_previo"] = cabeza["hash"] if cabeza else hash_genesis(config.SEDE_ID)
            e["hash"] = calcular_hash(e["hash_previo"], e)
            db.ejecutar("""INSERT INTO evento_auditoria (seq, instante, id_sede, usuario, rol, metodo, ruta, documento, estado, ip, hash_previo, hash)
                           VALUES (%(seq)s, %(instante)s, %(id_sede)s, %(usuario)s, %(rol)s, %(metodo)s, %(ruta)s, %(documento)s, %(estado)s,
                                   %(ip)s, %(hash_previo)s, %(hash)s)""", e, conn)
            return {"seq": e["seq"], "hash": e["hash"]}
    except Exception as ex:           # noqa: BLE001
        logger.warning("No se pudo anexar el evento de auditoría: %s", ex)
        return None


def listar(limite: int = 100, solo_fallos: bool = False) -> list[dict]:
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        filtro = "WHERE estado >= 400" if solo_fallos else ""
        filas = db.consultar(f"SELECT * FROM evento_auditoria {filtro} ORDER BY seq DESC LIMIT %s", (limite,), conn)
    for f in filas:
        f["instante"] = instante_iso(f["instante"])
        f["id_acceso"] = f["seq"]
    return filas


def accesos_completos(documento: Optional[str] = None, limite: int = 50) -> list[dict]:
    """Eventos con todos sus campos y su cadena (del más reciente al más antiguo), opcionalmente solo los de un documento."""
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        if documento:
            filas = db.consultar("SELECT * FROM evento_auditoria WHERE documento = %s ORDER BY seq DESC LIMIT %s", (documento, limite), conn)
        else:
            filas = db.consultar("SELECT * FROM evento_auditoria ORDER BY seq DESC LIMIT %s", (limite,), conn)
    for f in filas:
        f["instante"] = instante_iso(f["instante"])
    return filas


def accesos_de_documento(documento: str, limite: int = 100) -> list[dict]:
    """Quién y cuándo tocó los datos de un paciente en esta sede (para que el propio paciente lo vea)."""
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        filas = db.consultar("""SELECT seq, instante, usuario, rol, metodo, ruta, estado FROM evento_auditoria
                                WHERE documento = %s ORDER BY seq DESC LIMIT %s""", (documento, limite), conn)
    for f in filas:
        f["instante"] = instante_iso(f["instante"])
    return filas


def verificar(tramo: int = 5000) -> dict:
    """Recorre toda la cadena de esta sede (por tramos, sin cargarla entera en memoria)."""
    with db.conexion() as conn:
        _asegurar_tabla(conn)
    desde, total = None, 0
    while True:
        with db.conexion() as conn:
            filas = db.consultar("SELECT * FROM evento_auditoria WHERE seq > %s ORDER BY seq LIMIT %s",
                                 (desde[0] if desde else 0, tramo), conn)
        if not filas:
            break
        r = verificar_cadena(filas, config.SEDE_ID, desde)
        total += r["verificados"]
        if not r["ok"]:
            return {"sede": config.SEDE_ID, "ok": False, "verificados": total, "primer_fallo": r["primer_fallo"],
                    "cabeza": None, "verificado_en": instante_iso(datetime.now(timezone.utc))}
        desde = r["ultimo"]
        if len(filas) < tramo:
            break
    return {"sede": config.SEDE_ID, "ok": True, "verificados": total, "primer_fallo": None,
            "cabeza": {"seq": desde[0], "hash": desde[1]} if desde else None,
            "verificado_en": instante_iso(datetime.now(timezone.utc))}


# La escritura de lecturas y rechazos va en segundo plano y por un único hilo: con la base caída cada intento puede tardar hasta el
# timeout de conexión y no debe retener la respuesta (el gateway reintenta en otra sede solo si la sede responde rápido). Un hilo
# conserva el orden de llegada. Cola acotada: si se llena porque la base no responde, los eventos se descartan de la tabla, pero
# quedan en el log del pod. Las escrituras exitosas NO pasan por aquí: se anexan antes de responder para devolver su sello.
_ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auditoria")
_MAX_PENDIENTES = 200
_pendientes = 0
_candado = threading.Lock()


def _terminada(_futuro) -> None:
    global _pendientes
    with _candado:
        _pendientes -= 1


def anexar_en_segundo_plano(usuario: Optional[str], rol: Optional[str], metodo: str, ruta: str,
                            documento: Optional[str], estado: int, ip: Optional[str]) -> None:
    global _pendientes
    logger.info("acceso usuario=%s rol=%s %s %s documento=%s estado=%s ip=%s", usuario, rol, metodo, ruta, documento, estado, ip)
    with _candado:
        if _pendientes >= _MAX_PENDIENTES:
            logger.warning("Cola de auditoría llena (base sin respuesta): se omite el evento")
            return
        _pendientes += 1
    _ejecutor.submit(anexar, usuario, rol, metodo, ruta, documento, estado, ip).add_done_callback(_terminada)
