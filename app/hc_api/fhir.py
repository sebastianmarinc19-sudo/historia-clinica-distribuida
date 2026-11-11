"""Constructores de recursos FHIR R4 y cliente del HAPI FHIR de la sede.

Los recursos se arman como diccionarios JSON a partir de las filas del
modelo de 57 campos. El RDA (Reporte de Detalle de Atención) es un
Bundle de tipo `document` cuyo primer recurso es la Composition.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

BASE_ID = "https://hc.uajs.edu.co/fhir/id"
BASE_EXT = "https://hc.uajs.edu.co/fhir/StructureDefinition"
UCUM = "http://unitsofmeasure.org"
NS_COMPOSITION = uuid.UUID("0b8f6a3e-2c41-4d7a-8e55-9a1d3c7f5b10")

_GENERO = {"F": "female", "M": "male", "I": "other"}
# Códigos UCUM cuando difieren del código interno del catálogo.
_UCUM = {"C": "Cel"}
_UNIDADES_PERIODO = {"s", "min", "h", "d", "wk", "mo", "a"}


ZONA_HORARIA = "-05:00"    # America/Bogota, sin horario de verano: las columnas son TIMESTAMP sin zona y FHIR la exige si la fecha tiene hora


def _iso(valor) -> Optional[str]:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.isoformat() + (ZONA_HORARIA if valor.tzinfo is None else "")
    return str(valor)


def _ref(recurso: dict) -> dict:
    return {"reference": f"urn:uuid:{recurso['id']}"}


def patient_resource(p: dict) -> dict:
    recurso: dict[str, Any] = {
        "resourceType": "Patient",
        "id": str(p["id_paciente"]),
        "identifier": [{
            "system": f"{BASE_ID}/{p['cod_tipo_documento'].lower()}",
            "value": p["numero_documento"],
        }],
        "name": [{
            "use": "official",
            "family": " ".join(x for x in (p["primer_apellido"], p.get("segundo_apellido")) if x),
            "given": [x for x in (p["primer_nombre"], p.get("segundo_nombre")) if x],
        }],
        "gender": _GENERO.get(p["cod_sexo"], "unknown"),
        "birthDate": p["fecha_hora_nacimiento"].date().isoformat(),
        "_birthDate": {"extension": [{
            "url": "http://hl7.org/fhir/StructureDefinition/patient-birthTime",
            "valueDateTime": _iso(p["fecha_hora_nacimiento"]),
        }]},
        "address": [{k: v for k, v in {
            "use": "home",
            "city": p.get("cod_municipio_residencia"),
            "country": p["cod_pais_residencia"],
        }.items() if v}],
    }
    extensiones = []
    if p.get("cod_etnia"):
        extensiones.append({"url": f"{BASE_EXT}/etnia", "valueCode": p["cod_etnia"]})
    extensiones.append({"url": f"{BASE_EXT}/oposicion-donacion",
                        "valueBoolean": bool(p.get("oposicion_donacion"))})
    recurso["extension"] = extensiones
    return recurso


def encounter_resource(e: dict, paciente: dict, prestador: Optional[str]) -> dict:
    urgencias = e["cod_via_ingreso"] == "01"
    recurso: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": str(e["id_encuentro"]),
        "status": "finished" if e.get("fecha_hora_fin") else "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": "EMER" if urgencias else "AMB"},
        "subject": _ref(patient_resource(paciente)),
        "period": {"start": _iso(e["fecha_hora_inicio"])},
        "reasonCode": [{"coding": [{"system": f"{BASE_ID}/causa-atencion",
                                    "code": e["cod_causa_atencion"]}]}],
    }
    if e.get("fecha_hora_fin"):
        recurso["period"]["end"] = _iso(e["fecha_hora_fin"])
    if prestador:
        recurso["serviceProvider"] = {"identifier": {"system": f"{BASE_ID}/prestador", "value": prestador}}
    return recurso


def condition_resource(d: dict, paciente: dict, encuentro: dict) -> dict:
    return {
        "resourceType": "Condition",
        "id": str(d["id_diagnostico"]),
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "encounter-diagnosis"}]}],
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10",
                             "code": d["cod_cie10"], "display": d.get("cie10_descripcion")}]},
        "subject": _ref(patient_resource(paciente)),
        "encounter": _ref(encuentro),
        "recordedDate": _iso(d["fecha_diagnostico"]),
        "extension": [{"url": f"{BASE_EXT}/rol-diagnostico", "valueCode": d["cod_tipo_diagnostico"]}],
    }


def _cantidad(valor, unidad: str) -> dict:
    return {"value": float(valor), "unit": unidad, "system": UCUM, "code": _UCUM.get(unidad, unidad)}


def medication_request_resource(t: dict, m: dict, paciente: dict, encuentro: dict) -> dict:
    dosis = {"doseAndRate": [{"doseQuantity": _cantidad(m["dosis_prescrita"], m["cod_unidad_dosis"])}],
             "route": {"coding": [{"system": f"{BASE_ID}/via-administracion",
                                   "code": m["cod_via_administracion"]}]}}
    if m["cod_unidad_frecuencia"] in _UNIDADES_PERIODO and m["frecuencia_valor"] > 0:
        dosis["timing"] = {"repeat": {"frequency": 1, "period": m["frecuencia_valor"],
                                      "periodUnit": m["cod_unidad_frecuencia"]}}
    return {
        "resourceType": "MedicationRequest",
        "id": str(t["id_tecnologia_encuentro"]),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{
            "system": f"{BASE_ID}/cum", "code": m["cod_medicamento"],
            "display": m.get("medicamento_descripcion")}]},
        "subject": _ref(patient_resource(paciente)),
        "encounter": _ref(encuentro),
        "authoredOn": _iso(t["fecha_prescripcion"]),
        "dosageInstruction": [dosis],
        "dispenseRequest": {"expectedSupplyDuration": _cantidad(
            m["duracion_tratamiento"], m["cod_unidad_duracion"])},
    }


def procedure_resource(t: dict, paciente: dict, encuentro: dict) -> dict:
    return {
        "resourceType": "Procedure",
        "id": str(t["id_tecnologia_encuentro"]),
        "status": "completed",
        "code": {"coding": [{"system": f"{BASE_ID}/tecnologia-salud",
                             "code": t["cod_tecnologia"], "display": t.get("tecnologia_descripcion")}]},
        "subject": _ref(patient_resource(paciente)),
        "encounter": _ref(encuentro),
        "performedDateTime": _iso(t["fecha_prescripcion"]),
    }


def observation_resource(o: dict, paciente: dict, encuentro: dict) -> dict:
    recurso: dict[str, Any] = {
        "resourceType": "Observation",
        "id": str(o["id_observacion"]),
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": o["cod_loinc"],
                             "display": o.get("loinc_descripcion")}]},
        "subject": _ref(patient_resource(paciente)),
        "encounter": _ref(encuentro),
        "effectiveDateTime": _iso(o["fecha_hora_medicion"]),
    }
    if o.get("valor_numerico") is not None:
        recurso["valueQuantity"] = _cantidad(o["valor_numerico"], o["cod_unidad"])
    else:
        recurso["valueString"] = o["valor_texto"]
    return recurso


def _entrada(recurso: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{recurso['id']}", "resource": recurso}


def construir_rda(datos: dict) -> dict:
    """Arma el Bundle `document` (RDA) de un encuentro.

    datos: sede, paciente, encuentro, prestador, diagnosticos (con
    cie10_descripcion), tecnologias (con tecnologia_descripcion y, si es
    medicamento, medicamento: fila de medicamento_prescrito), observaciones.
    """
    pac, enc = datos["paciente"], datos["encuentro"]
    patient = patient_resource(pac)
    encounter = encounter_resource(enc, pac, datos.get("prestador"))

    condiciones = [condition_resource(d, pac, encounter) for d in datos["diagnosticos"]]
    medicaciones, procedimientos = [], []
    for t in datos["tecnologias"]:
        if t.get("medicamento"):
            medicaciones.append(medication_request_resource(t, t["medicamento"], pac, encounter))
        else:
            procedimientos.append(procedure_resource(t, pac, encounter))
    observaciones = [observation_resource(o, pac, encounter) for o in datos["observaciones"]]

    secciones = []
    for titulo, lista in (("Diagnósticos", condiciones), ("Medicación", medicaciones),
                          ("Procedimientos", procedimientos), ("Resultados", observaciones)):
        if lista:
            secciones.append({"title": titulo, "entry": [_ref(r) for r in lista]})

    composition = {
        "resourceType": "Composition",
        "id": str(uuid.uuid5(NS_COMPOSITION, str(enc["id_encuentro"]))),
        "status": "final",
        "type": {"coding": [{"system": "http://loinc.org", "code": "34133-9",
                             "display": "Summarization of episode note"}]},
        "subject": _ref(patient),
        "encounter": _ref(encounter),
        "date": _iso(enc.get("fecha_hora_fin") or enc["fecha_hora_inicio"]),
        "author": [{"display": f"Sede {datos['sede']['nombre_ciudad']}"}],
        "title": "Reporte de Detalle de Atención (RDA)",
        "section": secciones,
    }

    recursos = [composition, patient, encounter, *condiciones, *medicaciones,
                *procedimientos, *observaciones]
    return {
        "resourceType": "Bundle",
        "type": "document",
        "identifier": {"system": f"{BASE_ID}/rda", "value": str(enc["id_encuentro"])},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": [_entrada(r) for r in recursos],
    }


# --------------------------------------------------------------------------------------------- ids deterministas y PUT
# Cada recurso tiene un id que sale de los datos (no lo asigna HAPI): migrar dos veces el mismo encuentro actualiza los mismos recursos en
# vez de crear otros. El Patient usa el mismo id que el bus de integración (`pac-<documento>`), así que un paciente que llega por HL7 y
# por la API es un solo Patient en HAPI.
def id_fhir(texto: str) -> str:
    """Los ids FHIR admiten letras, dígitos, '-' y '.' (máximo 64)."""
    return re.sub(r"[^A-Za-z0-9.-]", "-", str(texto))[:64]


def id_paciente_fhir(paciente: dict) -> str:
    return id_fhir(f"pac-{paciente['numero_documento']}")


def id_rda(id_encuentro) -> str:
    return id_fhir(f"rda-{id_encuentro}")


_PREFIJO_ID = {"Condition": "cond", "MedicationRequest": "med", "Procedure": "proc", "Observation": "obs"}


def construir_transaccion(datos: dict) -> dict:
    """Los mismos recursos del RDA como recursos PROPIOS de HAPI: un Bundle `transaction` con `PUT` e ids deterministas.

    A diferencia del RDA (`document`, referencias `urn:uuid`), aquí las referencias son relativas (`Patient/pac-1007`) y todas apuntan a
    recursos del mismo Bundle. La Composition no va: solo existe dentro del documento.
    """
    recursos = [e["resource"] for e in construir_rda(datos)["entry"] if e["resource"]["resourceType"] != "Composition"]
    destino: dict[str, tuple[str, str]] = {}
    for r in recursos:
        tipo, viejo = r["resourceType"], r["id"]
        if tipo == "Patient":
            nuevo = id_paciente_fhir(datos["paciente"])
        elif tipo == "Encounter":
            nuevo = id_fhir(f"enc-{datos['encuentro']['id_sede']}-{viejo}")
        else:
            nuevo = id_fhir(f"{_PREFIJO_ID[tipo]}-{viejo}")
        destino[f"urn:uuid:{viejo}"] = (tipo, nuevo)

    def reescribir(x):
        if isinstance(x, dict):
            return {k: reescribir(v) for k, v in x.items()}
        if isinstance(x, list):
            return [reescribir(v) for v in x]
        if isinstance(x, str) and x in destino:
            tipo, nuevo = destino[x]
            return f"{tipo}/{nuevo}"
        return x

    entradas = []
    for r in recursos:
        tipo, nuevo = destino[f"urn:uuid:{r['id']}"]
        r = reescribir(r)
        r["id"] = nuevo
        ref = f"{tipo}/{nuevo}"
        entradas.append({"fullUrl": ref, "resource": r, "request": {"method": "PUT", "url": ref}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entradas}


class FhirNoDisponible(Exception):
    """HAPI FHIR no responde (caído, reiniciando o sin red)."""


class FhirError(Exception):
    """HAPI FHIR respondió con un error HTTP."""

    def __init__(self, estado: int, detalle: str):
        super().__init__(f"HAPI FHIR respondió {estado}: {detalle[:300]}")
        self.estado = estado
        self.detalle = detalle


class FhirClient:
    def __init__(self, base_url: str, timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _peticion(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.request(metodo, f"{self.base_url}{ruta}", **kw)
        except httpx.HTTPError as e:
            raise FhirNoDisponible(str(e) or e.__class__.__name__) from e
        if r.status_code >= 400:
            if r.status_code in (502, 503, 504):
                raise FhirNoDisponible(f"HTTP {r.status_code}")
            raise FhirError(r.status_code, r.text)
        return r

    def estado(self) -> dict:
        r = self._peticion("GET", "/metadata", params={"_summary": "true"},
                           headers={"Accept": "application/fhir+json"})
        cuerpo = r.json()
        return {"fhir_version": cuerpo.get("fhirVersion"),
                "software": (cuerpo.get("software") or {}).get("name")}

    def crear(self, recurso: dict) -> dict:
        # HAPI rechaza un POST (create) con `id` en el cuerpo: lo asigna el servidor.
        recurso = {k: v for k, v in recurso.items() if k != "id"}
        r = self._peticion("POST", f"/{recurso['resourceType']}", json=recurso,
                           headers={"Content-Type": "application/fhir+json",
                                    "Accept": "application/fhir+json"})
        return r.json()

    def guardar(self, recurso: dict) -> dict:
        """PUT de un recurso con id propio: crea o actualiza el mismo recurso (idempotente)."""
        r = self._peticion("PUT", f"/{recurso['resourceType']}/{recurso['id']}", json=recurso,
                           headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"})
        return r.json()

    def transaccion(self, bundle: dict) -> dict:
        """Envía un Bundle `transaction` (todo o nada). Devuelve la respuesta de HAPI."""
        r = self._peticion("POST", "", json=bundle,
                           headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"})
        return r.json()

    def total(self, tipo: str, **parametros) -> int:
        """Cuántos recursos de ese tipo cumplen la búsqueda (sin traerlos)."""
        r = self._peticion("GET", f"/{tipo}", params={"_summary": "count", **parametros}, headers={"Accept": "application/fhir+json"})
        return int(r.json().get("total", 0))

    def leer(self, tipo: str, id_: str) -> dict:
        return self._peticion("GET", f"/{tipo}/{id_}",
                              headers={"Accept": "application/fhir+json"}).json()
