"""Reporte de historia clínica por paciente y estado de la plataforma (vista del Reportero/auditor).

El reporte sale de la réplica local de la sede que responde: agrupa lo que cada sede dueña registró del paciente, calcula la cobertura de
los 57 campos por sede y marca qué sedes no responden (su copia puede estar desactualizada). Los porcentajes van como texto para que el sello se pueda recalcular en el navegador. Lleva un sello SHA-256 del contenido clínico
(sin la hora de generación ni el estado de las sedes, que cambian solos), de modo que dos reportes con los mismos datos tienen el mismo sello
y cualquier cambio en los datos lo cambia.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from . import campos57, config, db

# Cuando el par cae, el proceso de réplica se reinicia cada pocos segundos y figura «activo»; además PostgreSQL le pone como «último mensaje»
# su propia hora de arranque, así que ni el pid ni la hora bastan. Un proceso que de verdad se conectó ya tiene received_lsn; el que no
# logra conectarse lo deja nulo. Además, un par cuya réplica no recibe nada desde hace más de esto se considera sin respuesta: los pares
# mandan latidos cada wal_sender_timeout/2 (5 s con la configuración de las sedes), así que 25 s dejan holgura sin esconder una caída.
UMBRAL_SIN_MENSAJE_S = 25.0


def sello_contenido(contenido: dict) -> str:
    """SHA-256 de la serialización canónica (claves ordenadas, sin espacios, fechas en ISO)."""
    crudo = json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_json)
    return hashlib.sha256(crudo.encode()).hexdigest()


def _json(valor):
    if isinstance(valor, (datetime,)):
        return valor.isoformat()
    return str(valor)


def estado_sedes(conn) -> list[dict]:
    """Estado de cada sede visto desde esta: la local está en línea; cada par se infiere de su suscripción de réplica."""
    sedes = db.consultar("SELECT id_sede, nombre_ciudad FROM sede ORDER BY id_sede", conn=conn)
    local = next((s["nombre_ciudad"].lower() for s in sedes if s["id_sede"] == config.SEDE_ID), "")
    susc = {s["subname"]: s for s in db.consultar(
        """SELECT s.subname, s.subenabled AS habilitada, st.pid IS NOT NULL AND st.received_lsn IS NOT NULL AS activa,
                  round(extract(epoch FROM (now() - st.last_msg_receipt_time))::numeric, 1) AS segundos_sin_mensaje
             FROM pg_subscription s LEFT JOIN pg_stat_subscription st ON st.subid = s.oid""", conn=conn)}
    resultado = []
    for s in sedes:
        if s["id_sede"] == config.SEDE_ID:
            resultado.append({"id_sede": s["id_sede"], "sede": s["nombre_ciudad"], "estado": "en_linea", "detalle": "esta sede"})
            continue
        sub = susc.get(f"sub_{local}_desde_{s['nombre_ciudad'].lower()}")
        if sub is None:
            resultado.append({"id_sede": s["id_sede"], "sede": s["nombre_ciudad"], "estado": "desconocido", "detalle": "sin suscripción de réplica"})
        elif sub["activa"] and (sub["segundos_sin_mensaje"] is None or float(sub["segundos_sin_mensaje"]) <= UMBRAL_SIN_MENSAJE_S):
            resultado.append({"id_sede": s["id_sede"], "sede": s["nombre_ciudad"], "estado": "en_linea",
                              "detalle": "réplica activa", "segundos_sin_mensaje": sub["segundos_sin_mensaje"]})
        else:
            resultado.append({"id_sede": s["id_sede"], "sede": s["nombre_ciudad"], "estado": "no_responde",
                              "detalle": "la sede no responde: se muestra la última copia replicada",
                              "segundos_sin_mensaje": sub["segundos_sin_mensaje"]})
    return resultado


def _cobertura_paciente(conn, id_sede: int, documento: str) -> dict:
    campos = []
    for c in campos57.CAMPOS:
        r = db.uno(campos57.sql_cobertura(c, True), campos57.parametros_cobertura(c, id_sede, documento, exacto=True), conn)
        cub, esp = r["cubiertos"], r["esperados"]
        campos.append({"campo": c.n, "nombre": c.nombre, "tabla": c.tabla,
                       "porcentaje": f"{100 * cub / esp:.1f}" if esp else "0.0", "estado": campos57.estado(cub, esp)})
    resumen = {e: sum(1 for x in campos if x["estado"] == e) for e in ("completo", "parcial", "pendiente")}
    return {"resumen": resumen, "total": len(campos),
            "faltantes": [x for x in campos if x["estado"] != "completo"]}


def generar(conn, tipo_documento: str, documento: str) -> Optional[dict]:
    pacientes = db.consultar(
        """SELECT p.id_paciente, p.id_sede_origen, p.cod_tipo_documento, p.numero_documento, p.primer_nombre, p.segundo_nombre,
                  p.primer_apellido, p.segundo_apellido, p.fecha_hora_nacimiento, p.cod_sexo, p.fhir_patient_id
             FROM paciente p WHERE p.cod_tipo_documento = %s AND p.numero_documento = %s ORDER BY p.id_sede_origen""",
        (tipo_documento, documento), conn)
    if not pacientes:
        return None
    ids = [p["id_paciente"] for p in pacientes]
    encuentros = db.consultar(
        """SELECT e.id_encuentro, e.id_paciente, e.id_sede, e.fecha_hora_inicio, e.fecha_hora_fin, e.estado_migracion, b.fhir_bundle_id
             FROM encuentro e LEFT JOIN composicion_bundle b ON b.id_encuentro = e.id_encuentro
            WHERE e.id_paciente = ANY(%s) ORDER BY e.fecha_hora_inicio""", (ids,), conn)
    eids = [e["id_encuentro"] for e in encuentros]
    diag = db.consultar(
        """SELECT d.id_encuentro, d.cod_cie10, c.descripcion, d.cod_tipo_diagnostico, d.fecha_diagnostico
             FROM diagnostico_encuentro d JOIN cie10 c USING (cod_cie10) WHERE d.id_encuentro = ANY(%s)
            ORDER BY d.fecha_diagnostico, d.cod_tipo_diagnostico""", (eids,), conn) if eids else []
    obs = {r["id_encuentro"]: r["n"] for r in db.consultar(
        "SELECT id_encuentro, count(*) AS n FROM observacion WHERE id_encuentro = ANY(%s) GROUP BY id_encuentro", (eids,), conn)} if eids else {}
    tec = {r["id_encuentro"]: r["n"] for r in db.consultar(
        "SELECT id_encuentro, count(*) AS n FROM tecnologia_encuentro WHERE id_encuentro = ANY(%s) GROUP BY id_encuentro", (eids,), conn)} if eids else {}
    por_encuentro: dict = {}
    for d in diag:
        por_encuentro.setdefault(d["id_encuentro"], []).append(
            {"cie10": d["cod_cie10"], "descripcion": d["descripcion"], "tipo": d["cod_tipo_diagnostico"], "fecha": d["fecha_diagnostico"]})

    estado = {s["id_sede"]: s for s in estado_sedes(conn)}
    sedes = []
    for s in db.consultar("SELECT id_sede, nombre_ciudad FROM sede ORDER BY id_sede", conn=conn):
        propios = [p for p in pacientes if p["id_sede_origen"] == s["id_sede"]]
        enc_sede = [e for e in encuentros if e["id_sede"] == s["id_sede"]]
        sede = {"id_sede": s["id_sede"], "sede": s["nombre_ciudad"], "paciente": None, "encuentros": [], "cobertura": None}
        if propios:
            p = propios[0]
            sede["paciente"] = {k: p[k] for k in ("primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
                                                  "fecha_hora_nacimiento", "cod_sexo", "fhir_patient_id")}
            sede["cobertura"] = _cobertura_paciente(conn, s["id_sede"], documento)
        for e in enc_sede:
            sede["encuentros"].append({
                "id_encuentro": e["id_encuentro"], "inicio": e["fecha_hora_inicio"], "fin": e["fecha_hora_fin"],
                "estado_migracion": e["estado_migracion"], "fhir_bundle_id": e["fhir_bundle_id"],
                "diagnosticos": por_encuentro.get(e["id_encuentro"], []),
                "n_tecnologias": tec.get(e["id_encuentro"], 0), "n_observaciones": obs.get(e["id_encuentro"], 0)})
        sedes.append(sede)

    contenido = {"tipo_documento": tipo_documento, "documento": documento, "sedes": sedes}
    estados = list(estado.values())
    sin_respuesta = [e["sede"] for e in estados if e["estado"] != "en_linea"]
    return {"encontrado": True, "documento": documento, "tipo_documento": tipo_documento,
            "generado_en": datetime.now(timezone.utc).isoformat(), "sede_que_responde": config.SEDE_ID,
            "fuente": f"réplica local de la sede {config.SEDE_ID}",
            "estado_sedes": estados, "completo": not sin_respuesta,
            "aviso": (None if not sin_respuesta else
                      f"Sin respuesta de: {', '.join(sin_respuesta)}. Se muestra su última copia replicada; el reporte puede no incluir lo más reciente."),
            "contenido": contenido, "sello_sha256": sello_contenido(contenido)}
