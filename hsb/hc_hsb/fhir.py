"""Transforma el canónico a un Bundle FHIR R4 de tipo `transaction` con PUT e ids deterministas.

Como cada recurso tiene un id que sale del contenido del mensaje (pac-<documento>, enc-<sede>-<visita>…), enviar el mismo
Bundle dos veces actualiza los mismos recursos en vez de crear otros: reenviar es seguro. Las referencias son relativas
(`Patient/pac-1007`) y todas apuntan a recursos que están dentro del mismo Bundle.
"""
import re

SISTEMA_CIE10 = "http://hl7.org/fhir/sid/icd-10"
SISTEMA_LOINC = "http://loinc.org"
SISTEMA_UCUM = "http://unitsofmeasure.org"
SISTEMA_DOCUMENTO = "https://hc.local/sid/documento"
SISTEMA_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
CLASES = {"E": ("EMER", "emergency"), "O": ("AMB", "ambulatory"), "I": ("IMP", "inpatient encounter")}
GENEROS = {"M": "male", "F": "female", "O": "other"}
ZONA_HORARIA = "-05:00"    # America/Bogota, sin horario de verano: los sistemas legados no informan la zona y FHIR la exige si la fecha tiene hora


def _fecha_hora(iso):
    """Una fecha con hora y sin zona (`2026-11-07T10:15:00`) recibe la de Colombia; una sola fecha o una con zona se dejan igual."""
    if iso and "T" in iso and not re.search(r"(Z|[+-]\d{2}:\d{2})$", iso):
        return iso + ZONA_HORARIA
    return iso


def _id(texto: str) -> str:
    """Los ids FHIR admiten letras, dígitos, '-' y '.' (máximo 64)."""
    return re.sub(r"[^A-Za-z0-9.-]", "-", str(texto))[:64]


def id_paciente(documento: str) -> str:
    return _id(f"pac-{documento}")


def id_encuentro(sede: int, visita: str) -> str:
    return _id(f"enc-{sede}-{visita}")


def _entrada(recurso: dict) -> dict:
    ref = f"{recurso['resourceType']}/{recurso['id']}"
    return {"fullUrl": ref, "resource": recurso, "request": {"method": "PUT", "url": ref}}


def construir_bundle(c: dict) -> dict:
    p, e = c["paciente"], c["encuentro"]
    pac_id, enc_id = id_paciente(p["documento"]), id_encuentro(c["sede"], e["visita"])
    entradas = []

    nombres = [x for x in (p.get("primer_nombre"), p.get("segundo_nombre")) if x]
    apellido = " ".join(x for x in (p.get("primer_apellido"), p.get("segundo_apellido")) if x)
    entradas.append(_entrada({
        "resourceType": "Patient", "id": pac_id,
        "identifier": [{"system": SISTEMA_DOCUMENTO, "value": p["documento"]}],
        "name": [{"family": apellido, "given": nombres}],
        "gender": GENEROS.get(p["sexo"], "unknown"), "birthDate": p["nacimiento"]}))

    participante = []
    medico = e.get("medico")
    if medico:
        med_id = _id(f"med-{medico['codigo']}")
        practitioner = {"resourceType": "Practitioner", "id": med_id, "identifier": [{"value": medico["codigo"]}]}
        if medico.get("apellido") or medico.get("nombre"):
            practitioner["name"] = [{"family": medico.get("apellido") or "", "given": [medico["nombre"]] if medico.get("nombre") else []}]
        entradas.append(_entrada(practitioner))
        participante = [{"individual": {"reference": f"Practitioner/{med_id}"}}]

    codigo_clase, texto_clase = CLASES.get(e["clase"], CLASES["O"])
    encounter = {"resourceType": "Encounter", "id": enc_id, "status": "in-progress",
                 "class": {"system": SISTEMA_ACT, "code": codigo_clase, "display": texto_clase},
                 "subject": {"reference": f"Patient/{pac_id}"}, "period": {"start": _fecha_hora(e["inicio"])}}
    if participante:
        encounter["participant"] = participante
    entradas.append(_entrada(encounter))

    for dx in c.get("diagnosticos", []):
        entradas.append(_entrada({
            "resourceType": "Condition", "id": _id(f"cond-{c['sede']}-{e['visita']}-{dx['cie10']}"),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
            "code": {"coding": [{"system": SISTEMA_CIE10, "code": dx["cie10"], "display": dx.get("texto") or dx["cie10"]}],
                     "text": dx.get("dx_local") or dx.get("texto") or dx["cie10"]},
            "subject": {"reference": f"Patient/{pac_id}"}, "encounter": {"reference": f"Encounter/{enc_id}"},
            "recordedDate": _fecha_hora(dx["fecha"])}))

    for ob in c.get("observaciones", []):
        recurso = {
            "resourceType": "Observation", "id": _id(f"obs-{c['clave']}-{ob['n']}"), "status": "final",
            "code": {"coding": [{"system": SISTEMA_LOINC, "code": ob["loinc"], "display": ob.get("texto") or ob["loinc"]}]},
            "subject": {"reference": f"Patient/{pac_id}"}, "encounter": {"reference": f"Encounter/{enc_id}"},
            "effectiveDateTime": _fecha_hora(ob["fecha"])}
        if ob.get("valor") is not None:
            recurso["valueQuantity"] = {"value": ob["valor"], "unit": ob["unidad"], "system": SISTEMA_UCUM, "code": ob["unidad"]}
        else:
            recurso["valueString"] = ob["valor_texto"]
        entradas.append(_entrada(recurso))

    return {"resourceType": "Bundle", "type": "transaction", "entry": entradas}


def conceptmap(filas: list[dict]) -> dict:
    """ConceptMap simple: diagnóstico local -> CIE-10 (lo que usa el normalizador para el CSV legado)."""
    return {
        "resourceType": "ConceptMap", "id": "dx-local-a-cie10", "status": "active",
        "name": "DiagnosticoLocalACie10", "title": "Diagnóstico local del sistema legado a CIE-10",
        "sourceUri": "https://hc.local/ValueSet/dx-local", "targetUri": SISTEMA_CIE10,
        "group": [{"source": "https://hc.local/CodeSystem/dx-local", "target": SISTEMA_CIE10,
                   "element": [{"code": f["dx_local"], "display": f["dx_local"],
                                "target": [{"code": f["cie10"], "display": f["descripcion"], "equivalence": "equivalent"}]} for f in filas]}]}
