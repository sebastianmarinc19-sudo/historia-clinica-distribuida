"""Anclaje de la cabeza de la auditoría en las otras sedes.

La cadena de hash de una sede (auditoria.py) detecta alteraciones que no recalculan los hashes, pero un administrador de la base de esa
sede puede reescribir toda la cadena de forma consistente o borrar sus últimos eventos. Para cubrirlo, cada sede publica su cabeza
(secuencia y hash del último evento) en las otras dos, que la guardan en su propia base (`ancla_auditoria`, de solo anexar, no
replicada). El hash de un evento depende de todos los anteriores, así que el hash anclado en la secuencia N compromete el historial
completo hasta N:
  * si la sede reescribe cualquier evento anterior a N, su hash en N ya no coincide con el anclado -> «reescrita»;
  * si borra eventos y su cadena queda por debajo de N -> «truncada»;
  * si intenta anclar otro hash para una secuencia ya anclada, el par responde 409 y lo registra -> «conflicto».
`comprobar()` consulta a los pares qué tienen anclado de esta sede y lo compara con la cadena local. Un par que no responde no cuenta
como fallo (la sede caída no debe tumbar la verificación); solo una discrepancia lo es.

Límites: lo ocurrido después del último anclaje (hasta ~ANCLA_INTERVALO_S segundos) no está cubierto; las sedes comparten la clave JWT del
laboratorio, así que una sede comprometida podría firmar como otra (con claves por sede se cerraría); y si las dos sedes pares fueran
comprometidas a la vez no habría con qué comparar. Si una sede pierde el disco, su cadena nueva empieza en 1 y los pares la señalan como
«truncada»: es la alarma correcta (se perdió el historial de auditoría), no un fallo del mecanismo.
"""
import logging
import re
import threading
import time
from typing import Optional

import httpx

from . import auditoria, auth, config, db

logger = logging.getLogger("hc_api.anclaje")

_CANDADO_DDL = 7_101_002
_creada = False
_candado_creacion = threading.Lock()
HEX64 = re.compile(r"^[0-9a-f]{64}$")
_enviado: dict[int, int] = {}         # par -> última secuencia anclada con éxito en él


def _asegurar_tabla(conn) -> None:
    global _creada
    if _creada:
        return
    with _candado_creacion:
        if _creada:
            return
        db.ejecutar("SELECT pg_advisory_xact_lock(%s)", (_CANDADO_DDL,), conn)
        db.ejecutar("""CREATE TABLE IF NOT EXISTS ancla_auditoria (
                           id_sede_origen INT NOT NULL, seq BIGINT NOT NULL, hash CHAR(64) NOT NULL,
                           recibido_en TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (id_sede_origen, seq))""", conn=conn)
        db.ejecutar("""CREATE OR REPLACE FUNCTION ancla_auditoria_solo_anexar() RETURNS trigger LANGUAGE plpgsql AS $$
                       BEGIN RAISE EXCEPTION 'ancla_auditoria es de solo anexar (no admite % )', TG_OP; END $$""", conn=conn)
        db.ejecutar("""DO $$ BEGIN
                           IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ancla_auditoria_inmutable') THEN
                             CREATE TRIGGER ancla_auditoria_inmutable BEFORE UPDATE OR DELETE ON ancla_auditoria
                               FOR EACH ROW EXECUTE FUNCTION ancla_auditoria_solo_anexar();
                             CREATE TRIGGER ancla_auditoria_sin_truncate BEFORE TRUNCATE ON ancla_auditoria
                               FOR EACH STATEMENT EXECUTE FUNCTION ancla_auditoria_solo_anexar();
                           END IF; END $$""", conn=conn)
        _creada = True


# ------------------------------------------------------------------------------- lado receptor (el par que guarda el ancla)
def guardar(id_origen: int, seq: int, hash_: str) -> str:
    """Guarda el ancla recibida. Devuelve «nueva», «repetida» o «conflicto» (otro hash ya anclado para esa secuencia)."""
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        previa = db.uno("SELECT hash FROM ancla_auditoria WHERE id_sede_origen = %s AND seq = %s", (id_origen, seq), conn)
        if previa:
            return "repetida" if previa["hash"].strip() == hash_ else "conflicto"
        db.ejecutar("INSERT INTO ancla_auditoria (id_sede_origen, seq, hash) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (id_origen, seq, hash_), conn)
        return "nueva"


def listar(id_origen: int, limite: int = 20) -> list[dict]:
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        filas = db.consultar("""SELECT seq, hash, recibido_en FROM ancla_auditoria WHERE id_sede_origen = %s
                                ORDER BY seq DESC LIMIT %s""", (id_origen, limite), conn)
    for f in filas:
        f["hash"] = f["hash"].strip()
        f["recibido_en"] = auditoria.instante_iso(f["recibido_en"])
    return filas


# ------------------------------------------------------------------------------- lado emisor (la sede que ancla su cabeza)
def _token() -> str:
    return auth.emitir_token(f"sede-{config.SEDE_ID}", "sistema_sede", config.JWT_SECRETO, 60)


def _cabeza_local() -> Optional[dict]:
    with db.conexion() as conn:
        auditoria._asegurar_tabla(conn)       # noqa: SLF001  (misma base: la tabla se crea una vez)
        return db.uno("SELECT seq, hash FROM evento_auditoria ORDER BY seq DESC LIMIT 1", conn=conn)


def publicar_cabeza() -> dict:
    """Envía la cabeza actual a cada par al que aún no se la envió. Devuelve {par: código HTTP o None si no respondió}."""
    cabeza = _cabeza_local()
    if not cabeza or not config.PARES:
        return {}
    cuerpo = {"id_sede": config.SEDE_ID, "seq": int(cabeza["seq"]), "hash": cabeza["hash"].strip()}
    cab = {"Authorization": "Bearer " + _token()}
    resultado: dict = {}
    with httpx.Client(timeout=config.ANCLA_TIMEOUT_S) as cliente:
        for par, base in sorted(config.PARES.items()):
            if _enviado.get(par) == cuerpo["seq"]:
                continue
            try:
                r = cliente.post(f"{base}/api/v2/auditoria/anclas", json=cuerpo, headers=cab)
            except httpx.HTTPError:
                resultado[par] = None                  # el par está caído: se reintenta en el próximo ciclo
                continue
            resultado[par] = r.status_code
            if r.status_code in (200, 201):
                _enviado[par] = cuerpo["seq"]
            elif r.status_code == 409:
                _enviado[par] = cuerpo["seq"]
                logger.error("ALERTA: la sede %s ya tiene anclado OTRO hash para el evento %s de esta sede: el historial se reescribió", par, cuerpo["seq"])
            else:
                logger.warning("La sede %s no aceptó el ancla (%s): %s", par, r.status_code, r.text[:120])
    return resultado


def iniciar() -> None:
    """Arranca el hilo que ancla la cabeza cada ANCLA_INTERVALO_S segundos (si hay pares configurados)."""
    if not config.PARES or config.ANCLA_INTERVALO_S <= 0:
        return

    def bucle() -> None:
        time.sleep(3)
        while True:
            try:
                publicar_cabeza()
            except Exception as e:      # noqa: BLE001  (sin base o sin pares no hay anclaje; se reintenta)
                logger.warning("No se pudo anclar la cabeza de la auditoría: %s", e)
            time.sleep(config.ANCLA_INTERVALO_S)

    threading.Thread(target=bucle, daemon=True, name="anclaje").start()


# ------------------------------------------------------------------------------- comprobación contra los pares
def evaluar_anclas(anclas: list[dict], hashes_locales: dict, cabeza_seq: int, nombre_par: str) -> Optional[str]:
    """Compara las anclas de un par (de la más reciente a la más antigua) con la cadena local. Devuelve el motivo del fallo o None."""
    for a in anclas:
        if a["seq"] > cabeza_seq:
            return (f"cadena truncada: {nombre_par} tiene anclada la cabeza {a['seq']} y la cadena local solo llega a "
                    f"{cabeza_seq if cabeza_seq else 'ningún evento'} (eventos borrados)")
        if hashes_locales.get(a["seq"]) != a["hash"]:
            return f"historial reescrito: el hash del evento {a['seq']} no coincide con el que tiene anclado {nombre_par}"
    return None


def comprobar(limite: int = 20) -> dict:
    """Pregunta a cada par qué tiene anclado de esta sede y lo compara con la cadena local."""
    with db.conexion() as conn:
        _asegurar_tabla(conn)
        auditoria._asegurar_tabla(conn)       # noqa: SLF001
        nombres = {f["id_sede"]: f["nombre_ciudad"] for f in db.consultar("SELECT id_sede, nombre_ciudad FROM sede", conn=conn)}
        cab = db.uno("SELECT seq FROM evento_auditoria ORDER BY seq DESC LIMIT 1", conn=conn)
    cabeza_seq = int(cab["seq"]) if cab else 0
    pares: list[dict] = []
    cab_http = {"Authorization": "Bearer " + _token()}
    with httpx.Client(timeout=config.ANCLA_TIMEOUT_S) as cliente:
        for par, base in sorted(config.PARES.items()):
            nombre = nombres.get(par, f"sede {par}")
            item: dict = {"id_sede": par, "sede": nombre}
            try:
                r = cliente.get(f"{base}/api/v2/auditoria/anclas/{config.SEDE_ID}", params={"limite": limite}, headers=cab_http)
            except httpx.HTTPError:
                pares.append({**item, "estado": "no_responde", "anclas": 0})
                continue
            if r.status_code != 200:
                pares.append({**item, "estado": "no_responde", "anclas": 0, "detalle": f"HTTP {r.status_code}"})
                continue
            anclas = r.json().get("anclas", [])
            if not anclas:
                pares.append({**item, "estado": "sin_anclas", "anclas": 0})
                continue
            with db.conexion() as conn:
                filas = db.consultar("SELECT seq, hash FROM evento_auditoria WHERE seq = ANY(%s)", ([a["seq"] for a in anclas],), conn)
            locales = {int(f["seq"]): f["hash"].strip() for f in filas}
            motivo = evaluar_anclas(anclas, locales, cabeza_seq, nombre)
            pares.append({**item, "estado": "discrepancia" if motivo else "ok", "anclas": len(anclas),
                          "ultima": {"seq": anclas[0]["seq"], "hash": anclas[0]["hash"]}, **({"detalle": motivo} if motivo else {})})
    if any(p["estado"] == "discrepancia" for p in pares):
        ok: Optional[bool] = False
    elif any(p["estado"] == "ok" for p in pares):
        ok = True
    else:
        ok = None                                    # ningún par pudo confirmar (caídos o aún sin anclas)
    return {"ok": ok, "pares": pares}


_cache: dict = {"t": 0.0, "valor": None}


def verificar_completo(cache_s: float = 0.0) -> dict:
    """Verificación local de la cadena más la comprobación contra los pares. `ok` es falso si cualquiera de las dos falla."""
    if cache_s and _cache["valor"] and time.time() - _cache["t"] < cache_s:
        return _cache["valor"]
    r = auditoria.verificar()
    r["cadena_local_ok"] = r["ok"]
    try:
        r["anclaje"] = comprobar() if config.PARES else {"ok": None, "pares": []}
    except Exception as e:                           # noqa: BLE001  (sin pares alcanzables no se afirma nada)
        logger.warning("No se pudo comprobar el anclaje: %s", e)
        r["anclaje"] = {"ok": None, "pares": [], "error": str(e)[:120]}
    if r["anclaje"]["ok"] is False:
        r["ok"] = False
        if not r["primer_fallo"]:
            r["primer_fallo"] = {"seq": None, "motivo": next(p["detalle"] for p in r["anclaje"]["pares"] if p["estado"] == "discrepancia")}
    _cache.update(t=time.time(), valor=r)
    return r
