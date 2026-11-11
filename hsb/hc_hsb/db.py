"""Acceso a la base del bus (pool simple) y arranque del esquema."""
import csv
import pathlib
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from . import config

psycopg2.extras.register_uuid()
_pool: Optional[ThreadedConnectionPool] = None
_candado = threading.Lock()
AQUI = pathlib.Path(__file__).resolve().parent
DATOS = AQUI.parent / "datos"


def _pool_actual() -> ThreadedConnectionPool:
    global _pool
    with _candado:
        if _pool is None:
            _pool = ThreadedConnectionPool(1, 12, host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                                           user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=3,
                                           keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=3,
                                           tcp_user_timeout=10000)
        return _pool


@contextmanager
def conexion() -> Iterator:
    pool = _pool_actual()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        try:
            pool.putconn(conn, close=bool(conn.closed))
        except Exception:      # noqa: BLE001  (pool ya cerrado)
            pass


def consultar(sql: str, params: Any = None, conn=None) -> list[dict]:
    if conn is not None:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()] if cur.description else []
    with conexion() as c:
        return consultar(sql, params, c)


def uno(sql: str, params: Any = None, conn=None) -> Optional[dict]:
    filas = consultar(sql, params, conn)
    return filas[0] if filas else None


def ejecutar(sql: str, params: Any = None, conn=None) -> int:
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    with conexion() as c:
        return ejecutar(sql, params, c)


def iniciar() -> None:
    """Crea el esquema (idempotente) y siembra la tabla de terminología desde datos/ref_terminologia.csv."""
    with conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7011)")           # varias réplicas arrancando a la vez
            cur.execute((AQUI / "esquema.sql").read_text(encoding="utf-8"))
        with open(DATOS / "ref_terminologia.csv", encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f, delimiter=";"):
                ejecutar("INSERT INTO ref_terminologia VALUES (%s, %s, %s) ON CONFLICT (dx_local) DO NOTHING",
                         (fila["dx_local"].strip(), fila["cie10"].strip(), fila["descripcion"].strip()), conn)


def disponible() -> bool:
    try:
        consultar("SELECT 1")
        return True
    except Exception:      # noqa: BLE001
        return False
