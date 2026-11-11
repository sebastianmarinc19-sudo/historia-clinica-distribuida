"""Convierte un mensaje HL7 v2 o una fila CSV legada a un formato canónico y lo VALIDA, con motivos claros.

Un mensaje inválido no se pierde en silencio: devuelve la lista de motivos y el bus lo registra como «rechazado».
El canónico es un dict con valores JSON (fechas en ISO) para guardarlo tal cual en la base del bus y reintentar sin releer el mensaje.

Decisiones documentadas:
  * HL7: el diagnóstico (DG1-3) debe venir como CIE-10. Un código local (sistema «L») no se traduce: se rechaza con
    «sin mapeo a CIE-10». La tabla ref_terminologia traduce solo el TEXTO LIBRE del CSV legado (dx_local).
  * PID-3 trae el documento; el tipo de documento por defecto es CC (la autoridad «HIS» no es un tipo de documento).
  * Sexo HL7 «O» (otro) se entrega a la sede como «I» (intersexual), el único valor no binario de su catálogo.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from . import config, csvlegado
from . import hl7 as h

RE_DOCUMENTO = re.compile(r"^\d{4,15}$")
RE_CIE10 = re.compile(r"^[A-TV-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")
RE_LOINC = re.compile(r"^\d{1,5}-\d$")
SEXOS = ("M", "F", "O")


@dataclass
class Normalizado:
    """Resultado de normalizar un mensaje: el canónico (si es válido) o los motivos de rechazo."""
    formato: str
    tipo: str = ""
    clave: str = ""
    sede: Optional[int] = None
    documento: str = ""
    canonico: Optional[dict] = None
    motivos: list[str] = field(default_factory=list)


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def clave_terminologia(texto: str) -> str:
    return " ".join(_sin_tildes(texto).upper().split())


def _validar_persona(documento: str, nombre_ok: bool, sexo: str, nacimiento: Optional[date], motivos: list[str]) -> None:
    if not documento:
        motivos.append("documento ausente")
    elif not documento.isdigit():
        motivos.append(f"documento no numérico («{documento}»): debe tener solo dígitos")
    elif not RE_DOCUMENTO.match(documento):
        motivos.append(f"documento con longitud inválida ({len(documento)} dígitos): debe tener entre 4 y 15")
    if not nombre_ok:
        motivos.append("nombre vacío o sin apellido")
    if sexo not in SEXOS:
        motivos.append(f"sexo no válido («{sexo}»): debe ser M, F u O")
    if nacimiento is None:
        motivos.append("fecha de nacimiento ausente o inválida")
    elif nacimiento > date.today():
        motivos.append("fecha de nacimiento en el futuro")


def partir_nombre(nombre_completo: str) -> dict:
    """«Nombre [Nombre2] Apellido [Apellido2]» -> partes. 2 palabras: nombre y apellido; 3: nombre y dos apellidos; 4 o más: dos nombres."""
    t = nombre_completo.split()
    if len(t) < 2:
        return {}
    if len(t) == 2:
        return {"primer_nombre": t[0], "primer_apellido": t[1]}
    if len(t) == 3:
        return {"primer_nombre": t[0], "primer_apellido": t[1], "segundo_apellido": t[2]}
    return {"primer_nombre": t[0], "segundo_nombre": t[1], "primer_apellido": t[2], "segundo_apellido": " ".join(t[3:])}


def _sede_de_msh4(texto: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*$", texto or "")
    return int(m.group(1)) if m else None


def _paciente(documento, partes, nacimiento, sexo) -> dict:
    if isinstance(nacimiento, datetime):
        nacimiento = nacimiento.date()
    return {"documento": documento, "tipo_documento": config.TIPO_DOCUMENTO, "nacimiento": nacimiento.isoformat() if nacimiento else None,
            "sexo": sexo, **{k: partes.get(k) for k in ("primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido")}}


# ------------------------------------------------------------------------------------------------ HL7 v2
def normalizar_hl7(texto: str) -> Normalizado:
    n = Normalizado(formato="HL7")
    try:
        m = h.parsear(texto)
    except h.ErrorHL7 as e:
        n.motivos.append(str(e))
        return n
    msh, pid, pv1 = m.primero("MSH"), m.primero("PID"), m.primero("PV1")
    n.tipo = h.campo(msh, 9)
    n.clave = h.campo(msh, 10)
    n.sede = _sede_de_msh4(h.campo(msh, 4))
    n.documento = h.campo(pid, 3, 1)
    motivos = n.motivos

    if n.tipo not in ("ADT^A01", "ORU^R01"):
        motivos.append(f"tipo de mensaje no soportado («{n.tipo}»): solo ADT^A01 y ORU^R01")
    if not n.clave:
        motivos.append("MSH-10 (id del mensaje) ausente: no hay clave de idempotencia")
    if n.sede not in config.SEDES:
        motivos.append(f"sede no válida en MSH-4 («{h.campo(msh, 4)}»): debe ser la sede 1, 2 o 3")
    if pid is None:
        motivos.append("falta el segmento PID")
        return n

    apellido, nombre = h.campo(pid, 5, 1), h.campo(pid, 5, 2)
    partes = partir_nombre(f"{nombre} {apellido}".strip()) if nombre and apellido else {}
    if partes and h.campo(pid, 5, 3):
        partes["segundo_nombre"] = h.campo(pid, 5, 3)
    fnac = h.fecha_hl7(h.campo(pid, 7))
    sexo = h.campo(pid, 8).upper()
    _validar_persona(n.documento, bool(partes), sexo, fnac.date() if fnac else None, motivos)

    inicio = h.fecha_hl7(h.campo(pv1, 44)) or h.fecha_hl7(h.campo(msh, 7))
    if inicio is None:
        motivos.append("fecha del encuentro ausente o inválida (PV1-44 / MSH-7)")
    clase = h.campo(pv1, 2).upper() or "O"
    if clase not in ("E", "O", "I"):
        motivos.append(f"clase de paciente PV1-2 no válida («{clase}»): debe ser E, O o I")
    visita = h.campo(pv1, 19) or n.clave
    medico = None
    if h.campo(pv1, 7, 1):
        medico = {"codigo": h.campo(pv1, 7, 1), "apellido": h.campo(pv1, 7, 2), "nombre": h.campo(pv1, 7, 3)}

    diagnosticos, observaciones = [], []
    for dg in m.todos("DG1"):
        codigo, texto_dx = h.campo(dg, 3, 1), h.campo(dg, 3, 2)
        if RE_CIE10.match(codigo.upper()):
            fdx = h.fecha_hl7(h.campo(dg, 5))
            tipo_dx = {"A": "IN", "F": "EP"}.get(h.campo(dg, 6).upper(), "RE")
            if tipo_dx != "RE" and any(d["tipo"] == tipo_dx for d in diagnosticos):
                tipo_dx = "RE"          # la sede admite un solo diagnóstico de ingreso y uno de egreso por atención
            diagnosticos.append({"cie10": codigo.upper(), "texto": texto_dx, "tipo": tipo_dx,
                                 "fecha": (fdx or inicio or datetime.now()).date().isoformat()})
        else:
            motivos.append(f"diagnóstico «{codigo}» sin mapeo a CIE-10 (DG1-3 debe traer un código CIE-10)")
    if n.tipo == "ORU^R01":
        obxs = m.todos("OBX")
        if not obxs:
            motivos.append("ORU^R01 sin segmentos OBX")
        for i, obx in enumerate(obxs, start=1):
            loinc, texto_obs = h.campo(obx, 3, 1), h.campo(obx, 3, 2)
            if not RE_LOINC.match(loinc):
                motivos.append(f"OBX-{i}: código de la prueba «{loinc}» no es un LOINC válido")
                continue
            tipo_valor, bruto, unidad = h.campo(obx, 2).upper(), h.campo(obx, 5), h.campo(obx, 6, 1)
            fecha_obs = h.fecha_hl7(h.campo(obx, 14)) or h.fecha_hl7(h.campo(m.primero("OBR"), 7)) or inicio or datetime.now()
            if tipo_valor == "NM":
                try:
                    valor = float(bruto.replace(",", "."))
                except ValueError:
                    motivos.append(f"OBX-{i}: valor «{bruto}» no es numérico (tipo NM)")
                    continue
                if not unidad:
                    motivos.append(f"OBX-{i}: falta la unidad (OBX-6) para un valor numérico")
                    continue
                observaciones.append({"loinc": loinc, "texto": texto_obs, "valor": valor, "valor_texto": None, "unidad": unidad,
                                      "fecha": fecha_obs.isoformat(timespec="seconds"), "n": i})
            elif tipo_valor in ("ST", "TX") and bruto:
                observaciones.append({"loinc": loinc, "texto": texto_obs, "valor": None, "valor_texto": bruto, "unidad": None,
                                      "fecha": fecha_obs.isoformat(timespec="seconds"), "n": i})
            else:
                motivos.append(f"OBX-{i}: tipo de valor «{tipo_valor}» no soportado (NM, ST o TX con valor)")

    if not motivos and n.sede and inicio:
        n.canonico = {"formato": "HL7", "tipo": n.tipo, "clave": n.clave, "sede": n.sede, "documento": n.documento,
                      "paciente": _paciente(n.documento, partes, fnac, sexo),
                      "encuentro": {"visita": visita, "clase": clase, "inicio": inicio.isoformat(timespec="seconds"),
                                    "medico": medico, "triage": None},
                      "diagnosticos": diagnosticos, "observaciones": observaciones}
    return n


# ------------------------------------------------------------------------------------------------ CSV legado
def normalizar_fila_csv(sede: int, numero_fila: int, fila: dict, terminologia: dict[str, dict]) -> Normalizado:
    """`terminologia`: {clave_terminologia(dx_local): {"cie10":…, "descripcion":…}}"""
    n = Normalizado(formato="CSV", tipo="CSV", sede=sede, clave=csvlegado.hash_fila(sede, fila), documento=fila.get("documento", ""))
    motivos = n.motivos
    if sede not in config.SEDES:
        motivos.append(f"sede no válida ({sede}): debe ser 1, 2 o 3")
    partes = partir_nombre(fila.get("nombre", ""))
    sexo = (fila.get("sexo") or "").upper()
    try:
        fnac = datetime.strptime(fila.get("nacimiento", ""), "%Y-%m-%d").date()
    except ValueError:
        fnac = None
    _validar_persona(n.documento, bool(partes), sexo, fnac, motivos)

    try:
        inicio = datetime.fromisoformat(fila.get("fecha", ""))
    except ValueError:
        inicio = None
        motivos.append(f"fecha de la atención inválida («{fila.get('fecha', '')}»): use AAAA-MM-DDTHH:MM")

    diagnosticos = []
    dx_local = fila.get("dx_local", "")
    if dx_local:
        mapeado = terminologia.get(clave_terminologia(dx_local))
        if mapeado is None:
            motivos.append(f"diagnóstico «{dx_local}» sin mapeo a CIE-10 (no está en ref_terminologia)")
        else:
            diagnosticos.append({"cie10": mapeado["cie10"], "texto": mapeado["descripcion"], "tipo": "IN",
                                 "fecha": (inicio or datetime.now()).date().isoformat(), "dx_local": dx_local})
    else:
        motivos.append("diagnóstico (dx_local) vacío")

    triage = None
    if fila.get("triage"):
        if fila["triage"].isdigit() and 1 <= int(fila["triage"]) <= 5:
            triage = int(fila["triage"])
        else:
            motivos.append(f"triage inválido («{fila['triage']}»): debe ser 1 a 5")

    if not motivos:
        medico = {"codigo": fila["profesional"], "apellido": "", "nombre": ""} if fila.get("profesional") else None
        n.canonico = {"formato": "CSV", "tipo": "CSV", "clave": n.clave, "sede": sede, "documento": n.documento, "fila": numero_fila,
                      "paciente": _paciente(n.documento, partes, fnac, sexo),
                      "encuentro": {"visita": n.clave[:16], "clase": "E" if triage else "O", "inicio": inicio.isoformat(timespec="seconds"),
                                    "medico": medico, "triage": triage},
                      "diagnosticos": diagnosticos, "observaciones": []}
    return n
