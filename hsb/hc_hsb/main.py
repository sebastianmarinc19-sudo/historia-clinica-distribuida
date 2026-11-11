"""HSB (Health Service Bus): puertas de entrada, estado de los mensajes, salud y métricas."""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import bus, config, csvlegado, db, fhir, metricas
from .seguridad import Usuario, requiere

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("hc_hsb.main")

if config.AUTH_ACTIVA and not config.JWT_SECRETO:
    raise RuntimeError("HC_JWT_SECRETO es obligatorio con la autenticación activa (HSB_AUTH_ACTIVA=false solo para depurar)")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    for _intento in range(60):                   # la base del bus puede tardar en estar lista
        try:
            db.iniciar()
            break
        except Exception as e:      # noqa: BLE001
            logger.warning("esperando la base del bus: %s", str(e)[:120])
            time.sleep(2)
    else:
        raise RuntimeError("la base del bus no respondió")
    metricas.registrar_colector()
    bus.iniciar_sondeo()
    yield
    bus.detener_sondeo()


app = FastAPI(title="HSB · bus de integración de salud", version="1.0", lifespan=ciclo_de_vida)

CODIGO_HTTP = {"entregado": 200, "duplicado": 200, "reintentando": 202, "muerto": 202, "rechazado": 422}


def _responder(resultado: dict) -> JSONResponse:
    return JSONResponse(status_code=CODIGO_HTTP.get(resultado["estado"], 200), content=jsonable_encoder(resultado))


async def _texto(request: Request) -> str:
    cuerpo = await request.body()
    try:
        return cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        return cuerpo.decode("latin-1")


# ----------------------------------------------------------------------------------- entrada de mensajes
@app.post("/hsb/hl7")
async def recibir_hl7(request: Request, usuario: Usuario = Depends(requiere("sistema_sede"))):
    """Un mensaje HL7 v2 en texto plano (ADT^A01 o ORU^R01). 200 entregado o duplicado · 202 en reintento · 422 rechazado con motivos."""
    texto = await _texto(request)
    return _responder(await run_in_threadpool(bus.procesar_hl7, texto))


@app.post("/hsb/csv")
async def recibir_csv(request: Request, sede: int = Query(..., description="Sede que envía el archivo (1 a 3)"),
                      usuario: Usuario = Depends(requiere("sistema_sede"))):
    """Un archivo CSV legado (separador «;»). Cada fila es un mensaje con su propio resultado."""
    if sede not in config.SEDES:
        raise HTTPException(422, "La sede debe ser 1, 2 o 3")
    texto = await _texto(request)
    try:
        resultado = await run_in_threadpool(bus.procesar_csv, texto, sede)
    except csvlegado.ErrorCSV as e:
        raise HTTPException(422, str(e)) from e
    return JSONResponse(content=jsonable_encoder(resultado))


# ----------------------------------------------------------------------------------- estado de los mensajes
CONSULTA = ("admisionista", "medico", "reportero")


@app.get("/hsb/mensajes")
def listar_mensajes(estado: Optional[str] = None, sede: Optional[int] = None, limite: int = Query(50, ge=1, le=500),
                    usuario: Usuario = Depends(requiere(*CONSULTA))):
    filas = bus.listar(estado, sede, limite)
    return {"total": len(filas), "mensajes": jsonable_encoder(filas)}


@app.get("/hsb/mensajes/{id_mensaje}")
def detalle_mensaje(id_mensaje: uuid.UUID, usuario: Usuario = Depends(requiere(*CONSULTA))):
    fila = bus.detalle(id_mensaje)
    if fila is None:
        raise HTTPException(404, "Mensaje no encontrado")
    return jsonable_encoder(fila)


@app.post("/hsb/mensajes/{id_mensaje}/reencolar")
def reencolar_mensaje(id_mensaje: uuid.UUID, usuario: Usuario = Depends(requiere("administrador"))):
    """Devuelve a la cola un mensaje «muerto» (cuando el destino ya se recuperó)."""
    fila = bus.reencolar(id_mensaje)
    if fila is None:
        raise HTTPException(409, "Solo se pueden reencolar mensajes en estado «muerto»")
    return {"estado": "reintentando", "id_mensaje": str(id_mensaje)}


@app.get("/hsb/resumen")
def resumen(usuario: Usuario = Depends(requiere(*CONSULTA))):
    return bus.resumen()


@app.get("/hsb/terminologia")
def terminologia(usuario: Usuario = Depends(requiere(*CONSULTA, "sistema_sede"))):
    filas = db.consultar("SELECT dx_local, cie10, descripcion FROM ref_terminologia ORDER BY dx_local")
    return {"total": len(filas), "mapeos": filas}


@app.get("/hsb/terminologia/conceptmap")
def conceptmap(usuario: Usuario = Depends(requiere(*CONSULTA, "sistema_sede"))):
    return fhir.conceptmap(db.consultar("SELECT dx_local, cie10, descripcion FROM ref_terminologia ORDER BY dx_local"))


# ----------------------------------------------------------------------------------- salud y métricas
_cache_dependencias: dict = {"hasta": 0.0, "valor": {}}


def _dependencias() -> dict:
    """Estado de HAPI y de la API de cada sede (se consulta como máximo cada 5 s)."""
    if time.time() < _cache_dependencias["hasta"]:
        return _cache_dependencias["valor"]
    valor: dict = {"fhir": {}, "api": {}}
    with httpx.Client(timeout=2.0) as c:
        for sede in config.SEDES:
            for clave, base, ruta in (("fhir", config.url_fhir(sede), "/metadata?_summary=true"), ("api", config.url_api(sede), "/api/health")):
                if not base:
                    valor[clave][str(sede)] = "sin configurar"
                    continue
                try:
                    valor[clave][str(sede)] = "ok" if c.get(base + ruta).status_code == 200 else "degradado"
                except httpx.HTTPError:
                    valor[clave][str(sede)] = "no disponible"
    _cache_dependencias.update(hasta=time.time() + 5, valor=valor)
    return valor


@app.get("/health/live")
def vivo():
    return {"status": "ok"}


@app.get("/health")
def salud():
    """Estado del bus y de sus dependencias. 503 solo si el bus no puede operar (sin su base); un destino caído se reporta como degradado
    porque el bus lo cubre con reintentos."""
    base_ok = db.disponible()
    dependencias = _dependencias() if base_ok else {}
    degradado = any(v not in ("ok", "sin configurar") for grupo in dependencias.values() for v in grupo.values())
    cuerpo = {"status": "no_disponible" if not base_ok else ("degradado" if degradado else "ok"),
              "db": "ok" if base_ok else "no_disponible", "dependencias": dependencias}
    return JSONResponse(status_code=200 if base_ok else 503, content=cuerpo)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
