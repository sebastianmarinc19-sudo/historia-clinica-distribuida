"""Acceso a la base de la sede (pool de conexiones y utilidades)."""
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pgpool
from psycopg2.pool import ThreadedConnectionPool

from . import config

psycopg2.extras.register_uuid()

_pool: Optional[ThreadedConnectionPool] = None

# Contrapresión: el pool de psycopg2 falla con PoolError si se agota. Con este
# semáforo las peticiones esperan una conexión libre (hasta DB_POOL_ESPERA s)
# y, si la sede está saturada, se responde 503 en vez de 500.
_cupo = threading.BoundedSemaphore(config.DB_POOL_MAX)


class SedeSaturada(Exception):
    """No hubo conexión libre a la base de la sede dentro del tiempo de espera."""


_candado_pool = threading.Lock()


def _obtener_pool() -> ThreadedConnectionPool:
    global _pool
    with _candado_pool:
        if _pool is None:
            _pool = ThreadedConnectionPool(
                1, config.DB_POOL_MAX,
                host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                user=config.DB_USER, password=config.DB_PASSWORD,
                connect_timeout=config.DB_CONNECT_TIMEOUT,
                # Detecta en ~11 s una conexión rota por una partición de red. Los keepalives solo actúan con la
                # conexión ociosa; con una consulta enviada y sin confirmar (la red se cortó a mitad) hace falta
                # tcp_user_timeout, si no el sistema espera ~15 min de retransmisiones y la petición queda colgada.
                keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=3,
                tcp_user_timeout=10000,
                options="-c statement_timeout=30000",
            )
        return _pool


def _cerrar(pool_viejo: ThreadedConnectionPool) -> None:
    try:
        pool_viejo.closeall()
    except Exception:          # noqa: BLE001  (ya cerrado, o una conexión en uso que termina por su cuenta)
        pass


def _reiniciar_pool(defectuoso: Optional[ThreadedConnectionPool] = None) -> None:
    """Descarta el pool para reconectar en la siguiente petición.

    Solo reinicia si `defectuoso` sigue siendo el pool actual (si otro hilo ya lo cambió no se tira el nuevo).
    El cierre va en un hilo aparte: `closeall()` retiene el candado del pool y se bloquea al cerrar una conexión
    que otro hilo tiene en plena consulta; si se hiciera aquí, todas las peticiones quedarían esperando ese candado.
    """
    global _pool
    with _candado_pool:
        if defectuoso is not None and _pool is not defectuoso:
            return
        viejo, _pool = _pool, None
    if viejo is not None:
        threading.Thread(target=_cerrar, args=(viejo,), daemon=True, name="cierre-pool").start()


def _deshacer(conn) -> None:
    """Rollback que no falla si la conexión ya está rota (así el error original llega intacto)."""
    try:
        if not conn.closed:
            conn.rollback()
    except psycopg2.Error:
        pass


@contextmanager
def conexion() -> Iterator["psycopg2.extensions.connection"]:
    """Entrega una conexión con commit/rollback automático.

    Si la base de la sede no responde se descarta el pool para reconectar
    en la siguiente petición (la sede puede reiniciarse sin reiniciar la API).
    """
    if not _cupo.acquire(timeout=config.DB_POOL_ESPERA):
        raise SedeSaturada()
    try:
        pool = None
        try:
            pool = _obtener_pool()
            conn = pool.getconn()
        except psycopg2.OperationalError:
            _reiniciar_pool(pool)
            raise
        except pgpool.PoolError as e:         # pool cerrado por una reconexión simultánea: la base no está disponible
            raise psycopg2.OperationalError(str(e)) from e
        try:
            yield conn
            conn.commit()
        except psycopg2.OperationalError:
            _deshacer(conn)
            _reiniciar_pool(pool)
            raise
        except Exception:
            _deshacer(conn)
            raise
        finally:
            try:
                if not conn.closed:
                    pool.putconn(conn)
            except pgpool.PoolError:          # el pool se reinició mientras esta petición estaba en vuelo
                conn.close()
    finally:
        _cupo.release()


def consultar(sql: str, params: Any = None, conn=None) -> list[dict]:
    if conn is not None:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
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


def base_disponible() -> bool:
    try:
        consultar("SELECT 1")
        return True
    except Exception:
        return False
