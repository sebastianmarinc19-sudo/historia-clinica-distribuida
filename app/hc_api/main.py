"""API v2 de la historia clínica distribuida (una instancia por sede).

Regla de sede dueña (single-writer): cada fila clínica la escribe solo la
sede que la creó; las demás sedes reciben una copia por replicación
lógica y la consultan localmente. Un POST sobre un registro de otra sede
se rechaza con 409 e indica qué sede es la dueña. Esto evita conflictos
de escritura sin coordinación entre sedes.

Las lecturas (búsqueda, historia federada, cobertura, auditoría) salen de
la copia local, así que siguen funcionando aunque las otras sedes estén
caídas o aisladas.
"""
import logging
import os
import time
import uuid
from typing import Optional

import psycopg2
import psycopg2.errors as pgerr
import psycopg2.extras
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder as _json
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST

from . import anclaje, auditevent, auditoria, auth, campos57, config, db, metricas, mpi, reporte
from .fhir import (FhirClient, FhirError, FhirNoDisponible, construir_rda, construir_transaccion,
                   id_fhir, id_paciente_fhir, id_rda, patient_resource)
from .auth import Usuario, requiere
from .models import (AntecedenteIn, DiagnosticoIn, EgresoIn, EncuentroIn,
                     EntregaIn, ExposicionIn, LoginIn, MpiDecisionIn, ObservacionIn, PacienteIn,
                     PacienteLoginIn, ProfesionalIn, TecnologiaIn, TriageIn)

logger = logging.getLogger("hc_api")

if config.AUTH_ACTIVA and not config.JWT_SECRETO:
    raise RuntimeError("HC_JWT_SECRETO es obligatorio con la autenticación activa: genere las credenciales "
                       "con scripts/credenciales.py (o use HC_AUTH_ACTIVA=false solo para depurar)")

app = FastAPI(title="Historia clínica distribuida - API v2", version="2.0.0")


@app.on_event("startup")
def _arrancar_anclaje() -> None:
    anclaje.iniciar()      # cada sede publica la cabeza de su auditoría en las otras dos (no hace nada sin HC_PARES)


@app.middleware("http")
async def _medir(request: Request, call_next):
    """Registra cada petición para las métricas (ruta como plantilla, sin IDs)."""
    inicio = time.perf_counter()
    estado = 500
    try:
        respuesta = await call_next(request)
        estado = respuesta.status_code
        return respuesta
    finally:
        ruta = getattr(request.scope.get("route"), "path", "desconocida")
        if ruta != "/metrics":
            metricas.registrar_peticion(request.method, ruta, estado, time.perf_counter() - inicio)


@app.get("/metrics", include_in_schema=False)
def exportar_metricas():
    return Response(metricas.exportar(), media_type=CONTENT_TYPE_LATEST)
fhir_cliente = FhirClient(config.FHIR_BASE_URL, config.FHIR_TIMEOUT)
fhir_sonda = FhirClient(config.FHIR_BASE_URL, 2.0)     # para /api/health (respuesta rápida)


# ------------------------------------------------------------------ errores
class SedeNoPropietaria(Exception):
    def __init__(self, id_sede_duena: int):
        self.id_sede_duena = id_sede_duena


@app.exception_handler(SedeNoPropietaria)
def _sede_no_propietaria(_: Request, exc: SedeNoPropietaria):
    try:
        fila = db.uno("SELECT nombre_ciudad FROM sede WHERE id_sede = %s", (exc.id_sede_duena,))
        nombre = fila["nombre_ciudad"] if fila else None
    except Exception:
        nombre = None
    return JSONResponse(status_code=409, content={
        "error": "sede_no_propietaria",
        "sede_local": config.SEDE_ID,
        "sede_propietaria": exc.id_sede_duena,
        "sede_propietaria_nombre": nombre,
        "mensaje": f"Este registro pertenece a la sede {exc.id_sede_duena}; "
                   f"solo esa sede puede modificarlo. Esta sede lo ve como réplica de solo lectura.",
    })


@app.exception_handler(db.SedeSaturada)
def _sede_saturada(_: Request, exc: db.SedeSaturada):
    return JSONResponse(status_code=503, headers={"Retry-After": "1"}, content={
        "error": "sede_saturada", "sede": config.SEDE_ID,
        "mensaje": "Demasiadas peticiones simultáneas para esta sede; reintente."})


@app.exception_handler(psycopg2.Error)
def _error_base(_: Request, exc: psycopg2.Error):
    restriccion = getattr(getattr(exc, "diag", None), "constraint_name", None)
    detalle = getattr(getattr(exc, "diag", None), "message_detail", None)
    if isinstance(exc, pgerr.UniqueViolation):
        return JSONResponse(status_code=409, content={
            "error": "duplicado", "restriccion": restriccion, "detalle": detalle})
    if isinstance(exc, pgerr.ForeignKeyViolation):
        return JSONResponse(status_code=422, content={
            "error": "codigo_o_referencia_invalida", "restriccion": restriccion, "detalle": detalle})
    if isinstance(exc, (pgerr.CheckViolation, pgerr.NotNullViolation, pgerr.InvalidTextRepresentation,
                        pgerr.StringDataRightTruncation, pgerr.NumericValueOutOfRange)):
        return JSONResponse(status_code=422, content={
            "error": "dato_invalido", "restriccion": restriccion,
            "detalle": detalle or str(exc).splitlines()[0]})
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return JSONResponse(status_code=503, content={
            "error": "base_no_disponible", "sede": config.SEDE_ID,
            "mensaje": "La base de datos de esta sede no responde."})
    logger.error("Error de base de datos no esperado: %s: %s", type(exc).__name__, exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "error_base_de_datos", "detalle": str(exc).splitlines()[0]})


@app.exception_handler(FhirNoDisponible)
def _fhir_no_disponible(_: Request, exc: FhirNoDisponible):
    return JSONResponse(status_code=503, content={
        "error": "fhir_no_disponible", "sede": config.SEDE_ID, "detalle": str(exc),
        "mensaje": "El HAPI FHIR de esta sede no responde; el registro clínico sigue operando."})


@app.exception_handler(FhirError)
def _fhir_error(_: Request, exc: FhirError):
    return JSONResponse(status_code=502, content={
        "error": "fhir_rechazo", "estado_hapi": exc.estado, "detalle": exc.detalle[:500]})


# ---------------------------------------------------------------- utilidades
def _insertar(conn, tabla: str, valores: dict) -> dict:
    columnas = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    return db.uno(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas}) RETURNING *",
                  tuple(valores.values()), conn)


def _paciente(conn, id_paciente: uuid.UUID) -> dict:
    p = db.uno("SELECT * FROM paciente WHERE id_paciente = %s", (id_paciente,), conn)
    if p is None:
        raise HTTPException(404, "Paciente no encontrado")
    return p


def _paciente_propio(conn, id_paciente: uuid.UUID) -> dict:
    p = _paciente(conn, id_paciente)
    if p["id_sede_origen"] != config.SEDE_ID:
        raise SedeNoPropietaria(p["id_sede_origen"])
    return p


def _encuentro(conn, id_encuentro: uuid.UUID) -> dict:
    e = db.uno("SELECT * FROM encuentro WHERE id_encuentro = %s", (id_encuentro,), conn)
    if e is None:
        raise HTTPException(404, "Encuentro no encontrado")
    return e


def _encuentro_propio(conn, id_encuentro: uuid.UUID) -> dict:
    e = _encuentro(conn, id_encuentro)
    if e["id_sede"] != config.SEDE_ID:
        raise SedeNoPropietaria(e["id_sede"])
    return e


def _exigir_dueno(usuario: Usuario, paciente: dict) -> None:
    """El rol paciente solo puede ver datos de su propio documento."""
    if usuario.es_paciente and not usuario.es_su_documento(paciente["cod_tipo_documento"], paciente["numero_documento"]):
        raise HTTPException(403, "Solo puede consultar su propia información")


def _exigir_dueno_de_encuentro(conn, usuario: Usuario, enc: dict) -> None:
    if usuario.es_paciente:
        _exigir_dueno(usuario, _paciente(conn, enc["id_paciente"]))


def _datos_hijos(conn, id_encuentro: uuid.UUID) -> dict:
    diagnosticos = db.consultar(
        """SELECT d.*, c.descripcion AS cie10_descripcion
             FROM diagnostico_encuentro d JOIN cie10 c USING (cod_cie10)
            WHERE d.id_encuentro = %s ORDER BY d.fecha_diagnostico, d.cod_tipo_diagnostico""",
        (id_encuentro,), conn)
    tecnologias = db.consultar(
        """SELECT te.*, ts.descripcion AS tecnologia_descripcion, ts.tipo AS tecnologia_tipo
             FROM tecnologia_encuentro te JOIN tecnologia_salud ts USING (cod_tecnologia)
            WHERE te.id_encuentro = %s ORDER BY te.fecha_prescripcion""", (id_encuentro,), conn)
    for t in tecnologias:
        t["medicamento"] = db.uno(
            """SELECT m.*, md.descripcion AS medicamento_descripcion
                 FROM medicamento_prescrito m JOIN medicamento md USING (cod_medicamento)
                WHERE m.id_tecnologia_encuentro = %s""", (t["id_tecnologia_encuentro"],), conn)
        t["entregas"] = db.consultar(
            "SELECT * FROM entrega_tecnologia WHERE id_tecnologia_encuentro = %s ORDER BY fecha_entrega",
            (t["id_tecnologia_encuentro"],), conn)
    observaciones = db.consultar(
        """SELECT o.*, l.descripcion AS loinc_descripcion
             FROM observacion o JOIN loinc l USING (cod_loinc)
            WHERE o.id_encuentro = %s ORDER BY o.fecha_hora_medicion""", (id_encuentro,), conn)
    return {"diagnosticos": diagnosticos, "tecnologias": tecnologias, "observaciones": observaciones}


# -------------------------------------------------------------------- salud
@app.get("/api/health/live")
def health_live():
    """Liveness: el proceso responde (no depende de la base ni de FHIR)."""
    return {"status": "ok"}


@app.get("/api/health")
def health():
    """Readiness: la sede puede atender si su base responde. FHIR es opcional."""
    db_ok = db.base_disponible()
    try:
        fhir = {"estado": "ok", **fhir_sonda.estado()}
    except (FhirNoDisponible, FhirError) as e:
        fhir = {"estado": "no_disponible", "detalle": str(e)}
    nombre = None
    if db_ok:
        fila = db.uno("SELECT nombre_ciudad FROM sede WHERE id_sede = %s", (config.SEDE_ID,))
        nombre = fila["nombre_ciudad"] if fila else None
    cuerpo = {"status": "ok" if db_ok else "no_disponible",
              "sede": {"id": config.SEDE_ID, "nombre": nombre},
              "db": "ok" if db_ok else "no_disponible", "fhir": fhir}
    return JSONResponse(status_code=200 if db_ok else 503, content=cuerpo)


@app.get("/api/v2/sede")
def sede():
    return {"sede_local": config.SEDE_ID,
            "sedes": db.consultar("SELECT * FROM sede ORDER BY id_sede")}


# Catálogos del modelo de 57 campos (lista blanca: el nombre se interpola en la consulta).
CATALOGOS = (
    "pais", "departamento", "municipio", "tipo_documento", "sexo_biologico", "identidad_genero",
    "ocupacion", "categoria_discapacidad", "etnia", "comunidad_etnica", "zona_territorial",
    "entidad_responsable", "prestador", "modalidad_atencion", "grupo_servicio", "entorno_atencion",
    "via_ingreso", "causa_atencion", "clasificacion_triage", "tecnologia_salud", "finalidad_tecnologia",
    "medicamento", "via_administracion", "unidad_medida", "condicion_egreso", "cie10",
    "tipo_diagnostico", "loinc", "factor_riesgo",
)


@app.get("/api/v2/catalogos")
def listar_catalogos():
    return {"catalogos": list(CATALOGOS)}


@app.get("/api/v2/catalogos/{nombre}")
def obtener_catalogo(nombre: str):
    """Filas de un catálogo como {codigo, descripcion, ...extras} (alimenta los formularios)."""
    if nombre not in CATALOGOS:
        raise HTTPException(404, "Catálogo desconocido")
    filas = db.consultar(f"SELECT * FROM {nombre}")
    if not filas:
        return {"catalogo": nombre, "items": []}
    pk = next(iter(filas[0]))
    items = [{"codigo": f[pk], "descripcion": f.get("descripcion") or f.get("nombre"),
              **{k: v for k, v in f.items() if k not in (pk, "descripcion", "nombre")}} for f in filas]
    return {"catalogo": nombre, "items": sorted(items, key=lambda i: str(i["codigo"]))}


@app.get("/api/v2/replicacion")
def estado_replicacion(usuario: Usuario = Depends(requiere("reportero"))):
    """Estado de las suscripciones (observabilidad de la replicación)."""
    filas = db.consultar(
        """SELECT s.subname, s.subenabled AS habilitada, st.pid IS NOT NULL AS activa,
                  st.last_msg_receipt_time AS ultimo_mensaje,
                  round(extract(epoch FROM (now() - st.last_msg_receipt_time))::numeric, 1) AS segundos_sin_mensaje
             FROM pg_subscription s
             LEFT JOIN pg_stat_subscription st ON st.subid = s.oid
            ORDER BY s.subname""")
    return {"sede": config.SEDE_ID, "suscripciones": filas}


# ---------------------------------------------------- CU-01 pacientes (admisión)
@app.post("/api/v2/pacientes")
def registrar_paciente(data: PacienteIn, usuario: Usuario = Depends(requiere("admisionista", "hsb"))):
    if data.id_sede_origen not in (None, config.SEDE_ID):
        raise SedeNoPropietaria(data.id_sede_origen)
    valores = data.model_dump(exclude={"id_sede_origen"})
    with db.conexion() as conn:
        existente = db.uno(
            """SELECT id_paciente FROM paciente
                WHERE id_sede_origen = %s AND cod_tipo_documento = %s AND numero_documento = %s""",
            (config.SEDE_ID, data.cod_tipo_documento, data.numero_documento), conn)
        if existente:
            # solo se actualiza lo que el cliente envió: un sistema que manda datos mínimos (el bus) no borra el resto
            cambios = data.model_dump(exclude={"id_sede_origen"}, exclude_unset=True)
            asignaciones = ", ".join(f"{c} = %s" for c in cambios)
            fila = db.uno(f"UPDATE paciente SET {asignaciones} WHERE id_paciente = %s RETURNING *",
                          (*cambios.values(), existente["id_paciente"]), conn)
            return {"success": True, "accion": "actualizado", "paciente": fila}
        fila = _insertar(conn, "paciente", {"id_sede_origen": config.SEDE_ID, **valores})
    return JSONResponse(status_code=201, content=_json({"success": True, "accion": "creado", "paciente": fila}))


@app.get("/api/v2/pacientes/buscar")
def buscar_pacientes(cod_tipo_documento: Optional[str] = None, numero_documento: Optional[str] = None,
                     nombre: Optional[str] = Query(default=None, min_length=2),
                     usuario: Usuario = Depends(requiere("admisionista", "medico", "paciente"))):
    if usuario.es_paciente and (nombre or not numero_documento
                                or not usuario.es_su_documento(cod_tipo_documento, numero_documento)):
        raise HTTPException(403, "Solo puede consultar su propio documento")
    if not numero_documento and not nombre:
        raise HTTPException(422, "Indique numero_documento (con cod_tipo_documento) o nombre")
    condiciones, params = [], []
    if numero_documento:
        condiciones.append("p.numero_documento = %s")
        params.append(numero_documento)
        if cod_tipo_documento:
            condiciones.append("p.cod_tipo_documento = %s")
            params.append(cod_tipo_documento)
    if nombre:
        condiciones.append("(p.primer_nombre || ' ' || coalesce(p.segundo_nombre, '') || ' ' || "
                           "p.primer_apellido || ' ' || coalesce(p.segundo_apellido, '')) ILIKE %s")
        params.append(f"%{nombre}%")
    filas = db.consultar(
        f"""SELECT p.*, s.nombre_ciudad AS _sede_nombre, p.id_sede_origen AS _id_sede
              FROM paciente p JOIN sede s ON s.id_sede = p.id_sede_origen
             WHERE {' AND '.join(condiciones)}
             ORDER BY p.id_sede_origen, p.primer_apellido LIMIT 100""", tuple(params))
    return {"total": len(filas), "fuente": f"réplica local de la sede {config.SEDE_ID}", "pacientes": filas}


@app.get("/api/v2/pacientes/{id_paciente}")
def obtener_paciente(id_paciente: uuid.UUID, usuario: Usuario = Depends(requiere("admisionista", "medico", "paciente"))):
    with db.conexion() as conn:
        p = _paciente(conn, id_paciente)
        _exigir_dueno(usuario, p)
        return p


# ------------------------------------------------------------- profesionales
@app.post("/api/v2/profesionales")
def crear_profesional(data: ProfesionalIn, usuario: Usuario = Depends(requiere("medico", "hsb"))):
    with db.conexion() as conn:
        fila = db.uno(
            """INSERT INTO profesional_salud (id_sede_origen, cod_tipo_documento, numero_documento, nombres, apellidos)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id_sede_origen, cod_tipo_documento, numero_documento)
               DO UPDATE SET nombres = EXCLUDED.nombres, apellidos = EXCLUDED.apellidos
               RETURNING *""",
            (config.SEDE_ID, data.cod_tipo_documento, data.numero_documento, data.nombres, data.apellidos), conn)
    return {"success": True, "profesional": fila,
            "mensaje": "Registrado en esta sede; se replica automáticamente a las demás."}


@app.get("/api/v2/profesionales")
def listar_profesionales(q: Optional[str] = None, usuario: Usuario = Depends(requiere("medico"))):
    filtro = "WHERE (nombres || ' ' || apellidos) ILIKE %s OR numero_documento = %s" if q else ""
    params = (f"%{q}%", q) if q else ()
    filas = db.consultar(f"SELECT * FROM profesional_salud {filtro} ORDER BY apellidos, nombres LIMIT 200", params)
    return {"total": len(filas), "profesionales": filas}


# ---------------------------------------------- CU-02..CU-09 (registro clínico)
@app.post("/api/v2/encuentros")
def abrir_encuentro(data: EncuentroIn, usuario: Usuario = Depends(requiere("admisionista", "hsb"))):
    if data.id_sede not in (None, config.SEDE_ID):
        raise SedeNoPropietaria(data.id_sede)
    valores = data.model_dump(exclude={"id_sede", "id_encuentro"})
    with db.conexion() as conn:
        _paciente_propio(conn, data.id_paciente)
        if data.id_encuentro is not None:       # idempotente: el mismo id devuelve el encuentro ya creado
            existente = db.uno("SELECT * FROM encuentro WHERE id_encuentro = %s", (data.id_encuentro,), conn)
            if existente is not None:
                if existente["id_paciente"] != data.id_paciente or existente["id_sede"] != config.SEDE_ID:
                    raise HTTPException(409, "Ese id de encuentro ya existe para otro paciente")
                return {"success": True, "accion": "existente", "encuentro": existente}
            valores["id_encuentro"] = data.id_encuentro
        fila = _insertar(conn, "encuentro", {**valores, "id_sede": config.SEDE_ID})
    return JSONResponse(status_code=201, content=_json({"success": True, "accion": "creado", "encuentro": fila}))


@app.get("/api/v2/encuentros/{id_encuentro}")
def detalle_encuentro(id_encuentro: uuid.UUID, usuario: Usuario = Depends(requiere("medico", "paciente"))):
    with db.conexion() as conn:
        enc = _encuentro(conn, id_encuentro)
        _exigir_dueno_de_encuentro(conn, usuario, enc)
        extra = {
            "sede_nombre": db.uno("SELECT nombre_ciudad FROM sede WHERE id_sede = %s", (enc["id_sede"],), conn)["nombre_ciudad"],
            "es_replica": enc["id_sede"] != config.SEDE_ID,
            "triage": db.uno("SELECT * FROM triage WHERE id_encuentro = %s", (id_encuentro,), conn),
            "egreso": db.uno("SELECT * FROM egreso WHERE id_encuentro = %s", (id_encuentro,), conn),
            "antecedentes": db.consultar("SELECT * FROM antecedente_salud WHERE id_encuentro = %s", (id_encuentro,), conn),
            "exposiciones": db.consultar("SELECT * FROM exposicion_riesgo WHERE id_encuentro = %s", (id_encuentro,), conn),
            "bundle": db.uno("SELECT id_bundle, fhir_bundle_id, fecha_generacion FROM composicion_bundle WHERE id_encuentro = %s",
                             (id_encuentro,), conn),
        }
        return {**enc, **extra, **_datos_hijos(conn, id_encuentro)}


@app.post("/api/v2/encuentros/{id_encuentro}/triage")
def registrar_triage(id_encuentro: uuid.UUID, data: TriageIn, usuario: Usuario = Depends(requiere("admisionista", "medico", "hsb"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        previo = db.uno("SELECT * FROM triage WHERE id_encuentro = %s", (id_encuentro,), conn)
        if previo is not None and previo["cod_triage"] == data.cod_triage:       # idempotente: mismo nivel = ya registrado
            return {"success": True, "accion": "existente", "triage": _json(previo)}
        fila = _insertar(conn, "triage", {"id_encuentro": id_encuentro, **data.model_dump()})
    return JSONResponse(status_code=201, content=_json({"success": True, "triage": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/diagnosticos")
def registrar_diagnostico(id_encuentro: uuid.UUID, data: DiagnosticoIn, usuario: Usuario = Depends(requiere("medico", "hsb"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        previo = db.uno("""SELECT * FROM diagnostico_encuentro
                            WHERE id_encuentro = %s AND cod_cie10 = %s AND cod_tipo_diagnostico = %s""",
                        (id_encuentro, data.cod_cie10, data.cod_tipo_diagnostico), conn)
        if previo is not None:                                                   # idempotente: el mismo diagnóstico ya está
            return {"success": True, "accion": "existente", "diagnostico": _json(previo)}
        fila = _insertar(conn, "diagnostico_encuentro", {"id_encuentro": id_encuentro, **data.model_dump()})
    return JSONResponse(status_code=201, content=_json({"success": True, "diagnostico": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/tecnologias")
def prescribir_tecnologia(id_encuentro: uuid.UUID, data: TecnologiaIn, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        tec = _insertar(conn, "tecnologia_encuentro", {
            "id_encuentro": id_encuentro, "cod_tecnologia": data.cod_tecnologia,
            "cod_finalidad": data.cod_finalidad, "fecha_prescripcion": data.fecha_prescripcion})
        med = None
        if data.medicamento:
            med = _insertar(conn, "medicamento_prescrito", {
                "id_tecnologia_encuentro": tec["id_tecnologia_encuentro"], **data.medicamento.model_dump()})
    return JSONResponse(status_code=201, content=_json({"success": True, "tecnologia": tec, "medicamento": med}))


@app.post("/api/v2/encuentros/{id_encuentro}/entregas")
def registrar_entrega(id_encuentro: uuid.UUID, data: EntregaIn, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        pertenece = db.uno(
            "SELECT 1 FROM tecnologia_encuentro WHERE id_tecnologia_encuentro = %s AND id_encuentro = %s",
            (data.id_tecnologia_encuentro, id_encuentro), conn)
        if not pertenece:
            raise HTTPException(422, "La tecnología no pertenece a este encuentro")
        fila = _insertar(conn, "entrega_tecnologia", data.model_dump())
    return JSONResponse(status_code=201, content=_json({"success": True, "entrega": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/observaciones")
def registrar_observacion(id_encuentro: uuid.UUID, data: ObservacionIn, usuario: Usuario = Depends(requiere("medico", "hsb"))):
    valores = data.model_dump()
    if valores.get("id_observacion") is None:
        valores.pop("id_observacion", None)
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        if "id_observacion" in valores:          # idempotente: el mismo id devuelve la observación ya registrada
            previa = db.uno("SELECT * FROM observacion WHERE id_observacion = %s", (valores["id_observacion"],), conn)
            if previa is not None:
                if previa["id_encuentro"] != id_encuentro:
                    raise HTTPException(409, "Ese id de observación ya existe en otro encuentro")
                return {"success": True, "accion": "existente", "observacion": _json(previa)}
        fila = _insertar(conn, "observacion", {"id_encuentro": id_encuentro, **valores})
    return JSONResponse(status_code=201, content=_json({"success": True, "observacion": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/antecedentes")
def registrar_antecedente(id_encuentro: uuid.UUID, data: AntecedenteIn, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        fila = _insertar(conn, "antecedente_salud", {"id_encuentro": id_encuentro, **data.model_dump()})
    return JSONResponse(status_code=201, content=_json({"success": True, "antecedente": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/exposiciones")
def registrar_exposicion(id_encuentro: uuid.UUID, data: ExposicionIn, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        fila = _insertar(conn, "exposicion_riesgo", {"id_encuentro": id_encuentro, **data.model_dump()})
    return JSONResponse(status_code=201, content=_json({"success": True, "exposicion": fila}))


@app.post("/api/v2/encuentros/{id_encuentro}/egreso")
def registrar_egreso(id_encuentro: uuid.UUID, data: EgresoIn, usuario: Usuario = Depends(requiere("medico"))):
    """Cierra el encuentro (campo 50) y registra el egreso (campos 48, 51–53, 56–57)."""
    with db.conexion() as conn:
        _encuentro_propio(conn, id_encuentro)
        valores = data.model_dump(exclude={"fecha_hora_fin"})
        fila = _insertar(conn, "egreso", {"id_encuentro": id_encuentro, **valores})
        db.ejecutar("UPDATE encuentro SET fecha_hora_fin = %s WHERE id_encuentro = %s",
                    (data.fecha_hora_fin, id_encuentro), conn)
    return JSONResponse(status_code=201, content=_json({"success": True, "egreso": fila}))


# --------------------------------------------------- CU-10 / CU-12 migración FHIR
def _migrar_paciente(p: dict) -> dict:
    """Crea o actualiza (PUT, id `pac-<documento>`) el Patient en el HAPI de la sede y guarda fhir_patient_id. Repetirlo no duplica."""
    esperado = id_paciente_fhir(p)
    recurso = patient_resource(p)
    recurso["id"] = esperado
    fhir_cliente.guardar(recurso)          # PUT con id determinista, fuera de transacción de base de datos
    with db.conexion() as conn:
        db.ejecutar("UPDATE paciente SET fhir_patient_id = %s WHERE id_paciente = %s", (esperado, p["id_paciente"]), conn)
    return {"ya_migrado": p.get("fhir_patient_id") == esperado, "fhir_patient_id": esperado}


@app.post("/api/v2/migracion/paciente/{id_paciente}")
def migrar_paciente(id_paciente: uuid.UUID, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        p = _paciente_propio(conn, id_paciente)
    return {"success": True, **_migrar_paciente(p)}


@app.post("/api/v2/migracion/encuentro/{id_encuentro}")
def migrar_encuentro(id_encuentro: uuid.UUID, usuario: Usuario = Depends(requiere("medico"))):
    """Genera el RDA (Bundle document), lo envía al HAPI de la sede y resuelve el MPI."""
    with db.conexion() as conn:
        enc = _encuentro_propio(conn, id_encuentro)
        pac = _paciente(conn, enc["id_paciente"])
        sede_fila = db.uno("SELECT * FROM sede WHERE id_sede = %s", (enc["id_sede"],), conn)
        hijos = _datos_hijos(conn, id_encuentro)

    datos = {"sede": sede_fila, "paciente": pac, "encuentro": enc, "prestador": sede_fila["cod_prestador"], **hijos}
    try:
        # 1) los recursos propios (Patient, Encounter, Condition, …) en una transacción de PUT con ids deterministas;
        # 2) el RDA (Bundle document) también con PUT, así que migrar otra vez el mismo encuentro actualiza lo mismo y no duplica.
        transaccion = construir_transaccion(datos)
        fhir_cliente.transaccion(transaccion)
        bundle = construir_rda(datos)
        bundle["id"] = id_rda(id_encuentro)
        respuesta = fhir_cliente.guardar(bundle)
    except (FhirNoDisponible, FhirError):
        with db.conexion() as conn:
            db.ejecutar("UPDATE encuentro SET estado_migracion = 'ERROR' WHERE id_encuentro = %s",
                        (id_encuentro,), conn)
        raise

    with db.conexion() as conn:
        db.ejecutar("UPDATE paciente SET fhir_patient_id = %s WHERE id_paciente = %s", (id_paciente_fhir(pac), pac["id_paciente"]), conn)
        fila = db.uno(
            """INSERT INTO composicion_bundle (id_encuentro, fhir_bundle_id, bundle_json)
               VALUES (%s, %s, %s)
               ON CONFLICT (id_encuentro) DO UPDATE
                  SET fhir_bundle_id = EXCLUDED.fhir_bundle_id,
                      bundle_json = EXCLUDED.bundle_json, fecha_generacion = now()
               RETURNING id_bundle, id_encuentro, fhir_bundle_id, fecha_generacion""",
            (id_encuentro, respuesta["id"], psycopg2.extras.Json(bundle)), conn)
        db.ejecutar("UPDATE encuentro SET estado_migracion = 'MIGRADO' WHERE id_encuentro = %s",
                    (id_encuentro,), conn)
        identidad = mpi.resolver_identidad(conn, enc["id_paciente"], config.MPI_UMBRAL)

    return {"success": True, "estado_migracion": "MIGRADO", "bundle": fila,
            "fhir_bundle_id": respuesta["id"],
            "recursos_propios_en_hapi": [e["request"]["url"] for e in transaccion["entry"]],
            "recursos_incluidos": {"diagnosticos": len(hijos["diagnosticos"]),
                                   "medicamentos": sum(1 for t in hijos["tecnologias"] if t["medicamento"]),
                                   "procedimientos": sum(1 for t in hijos["tecnologias"] if not t["medicamento"]),
                                   "observaciones": len(hijos["observaciones"])},
            "identidad_federada": identidad}


@app.get("/api/v2/bundles/{id_encuentro}")
def consultar_bundle(id_encuentro: uuid.UUID, completo: bool = False, verificar_hapi: bool = False,
                     usuario: Usuario = Depends(requiere("medico", "paciente", "reportero"))):
    """CU-12. Sirve el RDA desde la réplica local (aunque la sede dueña esté caída). El reportero (auditor) lo descarga desde el reporte de HC."""
    with db.conexion() as conn:
        enc = _encuentro(conn, id_encuentro)
        _exigir_dueno_de_encuentro(conn, usuario, enc)
        fila = db.uno("SELECT * FROM composicion_bundle WHERE id_encuentro = %s", (id_encuentro,), conn)
    if fila is None:
        raise HTTPException(404, "El encuentro no tiene RDA generado")
    bundle = fila.pop("bundle_json")
    respuesta = {**fila, "sede_origen": enc["id_sede"], "es_replica": enc["id_sede"] != config.SEDE_ID,
                 "total_entradas": len((bundle or {}).get("entry", []))}
    if completo:
        respuesta["bundle"] = bundle
    if verificar_hapi:
        if enc["id_sede"] != config.SEDE_ID:
            respuesta["hapi"] = {"estado": "omitido", "detalle": "El HAPI canónico es el de la sede dueña"}
        else:
            try:
                b = fhir_cliente.leer("Bundle", fila["fhir_bundle_id"])
                eid = id_fhir(f"enc-{enc['id_sede']}-{id_encuentro}")
                ref = f"Encounter/{eid}"
                respuesta["hapi"] = {"estado": "ok", "type": b.get("type"), "total_entradas": len(b.get("entry", [])),
                                     "recursos_propios": {"encuentro": fhir_cliente.total("Encounter", _id=eid),
                                                          "condiciones": fhir_cliente.total("Condition", encounter=ref),
                                                          "observaciones": fhir_cliente.total("Observation", encounter=ref)}}
            except (FhirNoDisponible, FhirError) as e:
                respuesta["hapi"] = {"estado": "no_disponible", "detalle": str(e)}
    return respuesta


# ------------------------------------------------------------- CU-11 / CU-13 MPI
@app.post("/api/v2/mpi/resolver/{id_paciente}")
def resolver_mpi(id_paciente: uuid.UUID, usuario: Usuario = Depends(requiere("medico"))):
    with db.conexion() as conn:
        try:
            resultado = mpi.resolver_identidad(conn, id_paciente, config.MPI_UMBRAL)
        except LookupError:
            raise HTTPException(404, "Paciente no encontrado")
    return resultado


@app.get("/api/v2/mpi/revision")
def revision_mpi(cod_tipo_documento: str, numero_documento: str, usuario: Usuario = Depends(requiere("medico"))):
    """Pares de registros que el MPI no resuelve solo (datos parecidos con documentos distintos, o un mismo
    documento con datos contradictorios), más las decisiones ya tomadas. Solo lectura de la réplica local."""
    with db.conexion() as conn:
        pares = mpi.revision_de_documento(conn, cod_tipo_documento, numero_documento, config.MPI_UMBRAL)
    return {"pares": pares, "pendientes": sum(1 for x in pares if x["pendiente"])}


@app.post("/api/v2/mpi/decisiones", status_code=201)
def decidir_mpi(data: MpiDecisionIn, usuario: Usuario = Depends(requiere("medico"))):
    """Una persona confirma que dos registros son la misma persona (o que son distintas). La decisión se replica a las
    tres sedes y manda sobre las reglas automáticas; para cada par vale la más reciente."""
    if data.id_paciente_a == data.id_paciente_b:
        raise HTTPException(422, "Los dos registros deben ser distintos")
    a, b = mpi.par_canonico(data.id_paciente_a, data.id_paciente_b)
    with db.conexion() as conn:
        existentes = {r["id_paciente"] for r in db.consultar(
            "SELECT id_paciente FROM paciente WHERE id_paciente = ANY(%s)", ([a, b],), conn)}
        if existentes != {a, b}:
            raise HTTPException(404, "Alguno de los registros no existe en esta sede (ni como réplica)")
        fila = db.uno(
            """INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por, motivo)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (config.SEDE_ID, a, b, data.decision, usuario.sub, data.motivo), conn)
        resultado = {str(x): mpi.resolver_identidad(conn, x, config.MPI_UMBRAL) for x in (a, b)}
    return {"decision": fila, "identidad": resultado}


@app.post("/api/v2/mpi/recalcular")
def recalcular_mpi(usuario: Usuario = Depends(requiere("administrador"))):
    """Reconstruye la identidad federada de esta sede desde cero con la regla vigente (tras cambiar la política)."""
    with db.conexion() as conn:
        return mpi.recalcular_todo(conn, config.MPI_UMBRAL)


@app.get("/api/v2/historia-federada/{documento}")
def historia_federada(documento: str, cod_tipo_documento: str = "CC", usuario: Usuario = Depends(requiere("medico", "paciente"))):
    """CU-13. Historia de un paciente en todas las sedes, desde la réplica local."""
    if usuario.es_paciente and not usuario.es_su_documento(cod_tipo_documento, documento):
        raise HTTPException(403, "Solo puede consultar su propia historia")
    with db.conexion() as conn:
        registros = db.consultar(
            "SELECT id_paciente FROM paciente WHERE cod_tipo_documento = %s AND numero_documento = %s",
            (cod_tipo_documento, documento), conn)
        if not registros:
            return {"encontrado": False, "federado": False}
        pendientes = 0
        for r in registros:
            pendientes = max(pendientes, mpi.resolver_identidad(conn, r["id_paciente"], config.MPI_UMBRAL)["candidatos_pendientes"])
        ids = [r["id_paciente"] for r in registros]
        miembros = db.consultar(
            """SELECT m.id_mpi, m.id_paciente, m.id_sede, s.nombre_ciudad AS sede_nombre
                 FROM identidad_federada_paciente m JOIN sede s ON s.id_sede = m.id_sede
                WHERE m.id_mpi IN (SELECT id_mpi FROM identidad_federada_paciente WHERE id_paciente = ANY(%s))
                ORDER BY m.id_sede""", (ids,), conn)
        if usuario.es_paciente:           # un puntaje aproximado podría haber unido a otra persona: solo se muestra lo suyo
            propios = {r["id_paciente"] for r in registros}
            miembros = [m for m in miembros if m["id_paciente"] in propios]
        federado = bool(miembros)
        if not federado:
            miembros = db.consultar(
                """SELECT NULL::uuid AS id_mpi, p.id_paciente, p.id_sede_origen AS id_sede, s.nombre_ciudad AS sede_nombre
                     FROM paciente p JOIN sede s ON s.id_sede = p.id_sede_origen
                    WHERE p.id_paciente = ANY(%s) ORDER BY p.id_sede_origen""", (ids,), conn)
        ids_miembros = [m["id_paciente"] for m in miembros]
        encuentros = db.consultar(
            """SELECT e.*, s.nombre_ciudad AS sede_nombre, b.fhir_bundle_id,
                      (e.id_sede <> %s) AS es_replica
                 FROM encuentro e JOIN sede s ON s.id_sede = e.id_sede
                 LEFT JOIN composicion_bundle b ON b.id_encuentro = e.id_encuentro
                WHERE e.id_paciente = ANY(%s) ORDER BY e.fecha_hora_inicio""",
            (config.SEDE_ID, ids_miembros), conn)
    return {"encontrado": True, "federado": federado,
            "id_mpi": miembros[0]["id_mpi"] if federado else None,
            "revision_pendiente": 0 if usuario.es_paciente else pendientes,    # el paciente no ve datos de otras personas
            "sedes": miembros, "total_encuentros": len(encuentros), "encuentros": encuentros,
            "fuente": f"réplica local de la sede {config.SEDE_ID}"}


# ------------------------------------------------------ CU-14 / CU-15 auditoría
@app.get("/api/v2/cobertura")
def cobertura(usuario: Usuario = Depends(requiere("reportero"))):
    """CU-14. Porcentaje de pacientes y encuentros migrados a FHIR, por sede."""
    filas = db.consultar(
        """SELECT s.id_sede, s.nombre_ciudad AS ciudad,
                  (SELECT count(*) FROM paciente p WHERE p.id_sede_origen = s.id_sede) AS pacientes,
                  (SELECT count(*) FROM paciente p WHERE p.id_sede_origen = s.id_sede
                      AND p.fhir_patient_id IS NOT NULL) AS pacientes_migrados,
                  (SELECT count(*) FROM encuentro e WHERE e.id_sede = s.id_sede) AS encuentros,
                  (SELECT count(*) FROM encuentro e WHERE e.id_sede = s.id_sede
                      AND e.estado_migracion = 'MIGRADO') AS encuentros_migrados
             FROM sede s ORDER BY s.id_sede""")
    for f in filas:
        f["porcentaje_pacientes"] = round(100 * f["pacientes_migrados"] / f["pacientes"], 1) if f["pacientes"] else 0.0
        f["porcentaje_encuentros"] = round(100 * f["encuentros_migrados"] / f["encuentros"], 1) if f["encuentros"] else 0.0
    return {"sede_que_responde": config.SEDE_ID, "sedes": filas}


@app.get("/api/v2/auditoria/57-campos")
def auditoria_57_campos(id_sede: Optional[int] = None,
                        lote: Optional[str] = Query(default=None, min_length=1, max_length=20,
                                                    description="Prefijo del documento: audita solo ese lote de pacientes"),
                     usuario: Usuario = Depends(requiere("reportero"))):
    """CU-15. Cobertura de los 57 campos por sede (usa la réplica local); `lote` filtra por prefijo de documento."""
    with db.conexion() as conn:
        sedes = db.consultar("SELECT id_sede, nombre_ciudad FROM sede ORDER BY id_sede", conn=conn)
        resultado = []
        for s in sedes:
            if id_sede is not None and s["id_sede"] != id_sede:
                continue
            campos = []
            for c in campos57.CAMPOS:
                r = db.uno(campos57.sql_cobertura(c, bool(lote)), campos57.parametros_cobertura(c, s["id_sede"], lote), conn)
                cub, esp = r["cubiertos"], r["esperados"]
                campos.append({"campo": c.n, "nombre": c.nombre, "tabla": c.tabla,
                               "porcentaje_cobertura": round(100 * cub / esp, 1) if esp else 0.0,
                               "estado": campos57.estado(cub, esp)})
            resumen = {e: sum(1 for x in campos if x["estado"] == e)
                       for e in ("completo", "parcial", "pendiente")}
            resultado.append({"id_sede": s["id_sede"], "sede": s["nombre_ciudad"],
                              "campos": campos, "resumen": resumen})
    return {"sede_que_responde": config.SEDE_ID, "lote": lote, "sedes": resultado}


@app.get("/api/v2/reporte-hc/{documento}")
def reporte_hc(documento: str, cod_tipo_documento: str = "CC", usuario: Usuario = Depends(requiere("reportero", "medico", "paciente"))):
    """Reporte de historia clínica de un paciente: por sede, con cobertura de los 57 campos, sedes sin respuesta y sello SHA-256.
    Lo genera el auditor (reportero) o el médico de cualquier paciente, y el paciente solo el suyo."""
    if usuario.es_paciente and not usuario.es_su_documento(cod_tipo_documento, documento):
        raise HTTPException(403, "Solo puede generar el reporte de su propia historia")
    with db.conexion() as conn:
        r = reporte.generar(conn, cod_tipo_documento, documento)
    if r is None:
        raise HTTPException(404, "No hay un paciente con ese documento en la réplica de esta sede")
    return r


@app.get("/api/v2/estado-plataforma")
def estado_plataforma(usuario: Usuario = Depends(requiere("reportero", "medico"))):
    """Estado de la plataforma visto desde esta sede: sedes, base de datos, HAPI FHIR y cadena de auditoría."""
    with db.conexion() as conn:
        sedes = reporte.estado_sedes(conn)
    try:
        fhir_sonda.estado()
        fhir_ok = True
    except (FhirNoDisponible, FhirError):
        fhir_ok = False
    cadena = anclaje.verificar_completo(cache_s=15)
    metricas.registrar_verificacion(cadena)
    return {"sede_que_responde": config.SEDE_ID, "sedes": sedes, "base_de_datos": "ok", "hapi_fhir": "ok" if fhir_ok else "no_disponible",
            "auditoria": {"ok": cadena["ok"], "verificados": cadena["verificados"], "primer_fallo": cadena["primer_fallo"],
                          "anclaje": cadena.get("anclaje")}}


# ------------------------------------------------------------------ autenticación
def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()


_CLAVE_FALSA = auth.hash_clave("sin-usuario")      # iguala el tiempo de respuesta cuando el usuario no existe


@app.post("/api/v2/auth/login")
def iniciar_sesion(data: LoginIn, request: Request):
    """Personal (admisionista, médico, reportero, administrador): usuario y clave -> token."""
    request.state.intento = data.usuario
    clave_ip = f"{_ip(request)}:{data.usuario}"
    if auth.demasiados_fallos(clave_ip):
        raise HTTPException(429, "Demasiados intentos fallidos; espere unos minutos")
    registro = config.USUARIOS.get(data.usuario)
    correcta = auth.verificar_clave(data.clave, registro["hash"] if registro else _CLAVE_FALSA)
    if not (registro and correcta):
        auth.registrar_fallo(clave_ip)
        time.sleep(0.4)
        raise HTTPException(401, "Usuario o clave incorrectos")
    token = auth.emitir_token(data.usuario, registro["rol"], config.JWT_SECRETO, config.TOKEN_PERSONAL_S,
                              nombre=registro.get("nombre", ""))
    return {"token": token, "tipo": "Bearer", "expira_en_s": config.TOKEN_PERSONAL_S,
            "usuario": {"usuario": data.usuario, "rol": registro["rol"], "nombre": registro.get("nombre", "")}}


@app.post("/api/v2/auth/paciente")
def iniciar_sesion_paciente(data: PacienteLoginIn, request: Request):
    """Paciente: documento y fecha de nacimiento, verificados contra la copia local -> token de alcance propio."""
    request.state.intento = f"{data.cod_tipo_documento}:{data.numero_documento}"
    clave_ip = f"{_ip(request)}:{data.numero_documento}"
    if auth.demasiados_fallos(clave_ip):
        raise HTTPException(429, "Demasiados intentos fallidos; espere unos minutos")
    fila = db.uno(
        """SELECT primer_nombre, primer_apellido FROM paciente
            WHERE cod_tipo_documento = %s AND numero_documento = %s AND fecha_hora_nacimiento::date = %s LIMIT 1""",
        (data.cod_tipo_documento, data.numero_documento, data.fecha_nacimiento))
    if fila is None:
        auth.registrar_fallo(clave_ip)
        time.sleep(0.4)
        raise HTTPException(401, "Los datos no coinciden con ningún registro")
    nombre = f"{fila['primer_nombre']} {fila['primer_apellido']}"
    token = auth.emitir_token(f"{data.cod_tipo_documento}:{data.numero_documento}", "paciente", config.JWT_SECRETO,
                              config.TOKEN_PACIENTE_S, nombre=nombre, tipo=data.cod_tipo_documento, doc=data.numero_documento)
    return {"token": token, "tipo": "Bearer", "expira_en_s": config.TOKEN_PACIENTE_S,
            "usuario": {"usuario": f"{data.cod_tipo_documento} {data.numero_documento}", "rol": "paciente", "nombre": nombre}}


@app.get("/api/v2/auth/yo")
def quien_soy(usuario: Usuario = Depends(requiere())):
    return {"usuario": usuario.sub, "rol": usuario.rol, "nombre": usuario.nombre,
            "cod_tipo_documento": usuario.cod_tipo_documento, "numero_documento": usuario.numero_documento}


@app.get("/api/v2/auditoria/accesos")
def auditoria_accesos(limite: int = Query(default=100, ge=1, le=1000), solo_fallos: bool = False,
                      usuario: Usuario = Depends(requiere("reportero"))):
    """Registro local de accesos de esta sede (quién consultó o modificó datos y con qué resultado), con el hash de cada evento."""
    return {"sede": config.SEDE_ID, "accesos": auditoria.listar(limite, solo_fallos)}


@app.get("/api/v2/auditoria/verificar")
def auditoria_verificar(usuario: Usuario = Depends(requiere("reportero", "medico"))):
    """Recorre la cadena de hash de esta sede (ok, cuántos eventos verificó, la cabeza y el primer evento alterado si lo hay) y la compara con
    lo que las otras sedes tienen anclado de ella (`anclaje`: ok, y por cada par ok, sin_anclas, no_responde o discrepancia)."""
    resultado = anclaje.verificar_completo()
    metricas.registrar_verificacion(resultado)
    return resultado


class AnclaEntrada(BaseModel):
    id_sede: int
    seq: int = Field(ge=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


@app.post("/api/v2/auditoria/anclas")
def auditoria_recibir_ancla(entrada: AnclaEntrada, usuario: Usuario = Depends(requiere("sistema_sede"))):
    """Una sede par ancla aquí la cabeza de su auditoría (secuencia y hash). Si ya hay OTRO hash anclado para esa secuencia es 409:
    la sede reescribió su historial."""
    if entrada.id_sede == config.SEDE_ID or entrada.id_sede not in config.PARES:
        raise HTTPException(422, "La sede de origen no es un par de esta sede")
    estado = anclaje.guardar(entrada.id_sede, entrada.seq, entrada.hash)
    if estado == "conflicto":
        logging.getLogger("hc_api.anclaje").error("ALERTA: la sede %s anclo un hash distinto para su evento %s", entrada.id_sede, entrada.seq)
        raise HTTPException(409, "Ya hay otro hash anclado para esa secuencia: el historial de auditoría de esa sede no es el anclado")
    return {"estado": estado, "sede_receptora": config.SEDE_ID}


@app.get("/api/v2/auditoria/anclas/{id_sede}")
def auditoria_consultar_anclas(id_sede: int, limite: int = Query(default=20, ge=1, le=500),
                               usuario: Usuario = Depends(requiere("sistema_sede", "reportero", "medico"))):
    """Las últimas anclas que esta sede guarda de la auditoría de otra (de la más reciente a la más antigua)."""
    return {"sede_que_ancla": config.SEDE_ID, "id_sede": id_sede, "anclas": anclaje.listar(id_sede, limite)}


@app.get("/api/v2/auditoria/fhir")
def auditoria_fhir(limite: int = Query(default=50, ge=1, le=500), documento: Optional[str] = None,
                   usuario: Usuario = Depends(requiere("reportero", "medico"))):
    """Los últimos eventos de la auditoría de esta sede como Bundle `searchset` de AuditEvent (FHIR R4), con la cadena de hash en cada uno."""
    eventos = auditoria.accesos_completos(documento, limite)
    with db.conexion() as conn:
        sede = db.uno("SELECT nombre_ciudad FROM sede WHERE id_sede = %s", (config.SEDE_ID,), conn)
    return JSONResponse(auditevent.bundle(eventos, config.SEDE_ID, sede["nombre_ciudad"] if sede else None,
                                          f"/api/v2/auditoria/fhir?limite={limite}" + (f"&documento={documento}" if documento else "")),
                        media_type="application/fhir+json")


@app.get("/api/v2/auditoria/mis-accesos")
def auditoria_mis_accesos(limite: int = Query(default=100, ge=1, le=500), usuario: Usuario = Depends(requiere("paciente"))):
    """El paciente ve quién y cuándo accedió a su historia en esta sede (solo su documento)."""
    return {"sede": config.SEDE_ID, "documento": usuario.numero_documento,
            "accesos": auditoria.accesos_de_documento(usuario.numero_documento, limite)}


# Las consultas agregadas y de referencia no se registran (no exponen datos de un paciente).
_SIN_REGISTRO = ("/api/v2/catalogos", "/api/v2/sede", "/api/v2/auditoria/57-campos", "/api/v2/cobertura",
                 "/api/v2/replicacion", "/api/v2/auditoria/accesos", "/api/v2/auditoria/verificar", "/api/v2/auditoria/anclas", "/api/v2/auditoria/fhir",
                 "/api/v2/estado-plataforma", "/api/v2/auth/yo")


_ESCRITURAS = ("POST", "PUT", "PATCH", "DELETE")


@app.middleware("http")
async def _auditar_acceso(request: Request, call_next):
    respuesta = await call_next(request)
    ruta = request.url.path
    if ruta.startswith("/api/v2/") and not ruta.startswith(_SIN_REGISTRO):
        u = getattr(request.state, "usuario", None)
        documento = (request.path_params.get("documento") or request.query_params.get("numero_documento")
                     or (u.numero_documento if u and u.es_paciente else None))
        plantilla = getattr(request.scope.get("route"), "path", ruta)
        datos = (u.sub if u else getattr(request.state, "intento", None), u.rol if u else None, request.method, plantilla,
                 documento, respuesta.status_code, _ip(request))
        if request.method in _ESCRITURAS and respuesta.status_code < 400 and not ruta.startswith("/api/v2/auth/"):
            # Una escritura exitosa se anexa antes de responder para devolver su sello (secuencia:hash del evento de auditoría).
            sello = await run_in_threadpool(auditoria.anexar, *datos)
            if sello:
                respuesta.headers["X-Sello-Auditoria"] = f"{sello['seq']}:{sello['hash']}"
        else:
            auditoria.anexar_en_segundo_plano(*datos)
    return respuesta


# ------------------------------------------------------------------ vistas web
# Las 4 vistas (Paciente, Médico, Admisionista, Reportero) son archivos estáticos
# sin dependencias externas: siguen funcionando aunque la sede esté aislada de Internet.
# Usan rutas relativas, así que sirven igual en /vistas/ y detrás del gateway en /sede/N/vistas/.
_VISTAS = os.path.join(os.path.dirname(__file__), "static")


@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("vistas/index.html")


app.mount("/vistas", StaticFiles(directory=_VISTAS, html=True), name="vistas")
