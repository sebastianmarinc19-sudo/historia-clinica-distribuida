"""Bundle FHIR transaction: ids deterministas, referencias internas y recursos esperados (sin servidor)."""
import json
import os
import pathlib

from hc_hsb import fhir, normalizador as nz

EJEMPLOS = pathlib.Path(os.getenv("HSB_EJEMPLOS", pathlib.Path(__file__).resolve().parents[2] / "ejemplos"))


def bundle(nombre):
    n = nz.normalizar_hl7((EJEMPLOS / nombre).read_bytes().decode())
    assert n.canonico, n.motivos
    return fhir.construir_bundle(n.canonico)


def por_tipo(b):
    salida = {}
    for e in b["entry"]:
        salida.setdefault(e["resource"]["resourceType"], []).append(e["resource"])
    return salida


def test_adt_produce_patient_practitioner_encounter_y_condition_cie10():
    b = bundle("01_adt_a01_valido_sede2.hl7")
    assert b["resourceType"] == "Bundle" and b["type"] == "transaction"
    r = por_tipo(b)
    assert set(r) == {"Patient", "Practitioner", "Encounter", "Condition"}
    assert r["Patient"][0]["id"] == "pac-1007" and r["Patient"][0]["gender"] == "female" and r["Patient"][0]["birthDate"] == "1990-02-14"
    assert r["Patient"][0]["name"] == [{"family": "Rojas", "given": ["Andrea"]}]
    assert r["Encounter"][0]["id"] == "enc-2-V-S2-0101" and r["Encounter"][0]["class"]["code"] == "AMB"
    cond = r["Condition"][0]["code"]["coding"][0]
    assert (cond["system"], cond["code"]) == ("http://hl7.org/fhir/sid/icd-10", "J45.9")


def test_oru_produce_observation_loinc_con_valor_y_unidad_ucum():
    r = por_tipo(bundle("02_oru_r01_laboratorio_sede1.hl7"))
    obs, = r["Observation"]
    assert obs["code"]["coding"][0] == {"system": "http://loinc.org", "code": "718-7", "display": "Hemoglobina"}
    assert obs["valueQuantity"] == {"value": 13.8, "unit": "g/dL", "system": "http://unitsofmeasure.org", "code": "g/dL"}
    assert r["Patient"][0]["id"] == "pac-1001" and "Condition" not in r


def test_todas_las_entradas_son_put_con_la_misma_url_que_su_id():
    for e in bundle("01_adt_a01_valido_sede2.hl7")["entry"]:
        recurso = e["resource"]
        assert e["request"] == {"method": "PUT", "url": f"{recurso['resourceType']}/{recurso['id']}"}


def test_las_referencias_apuntan_a_recursos_que_estan_dentro_del_bundle():
    b = bundle("01_adt_a01_valido_sede2.hl7")
    presentes = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in b["entry"]}
    referencias = [m for m in _referencias(b)]
    assert referencias and all(r in presentes for r in referencias), (referencias, presentes)


def _referencias(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference":
                yield v
            else:
                yield from _referencias(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _referencias(x)


def test_el_mismo_mensaje_produce_siempre_el_mismo_bundle_reenviar_no_crea_otros_recursos():
    a, b = bundle("01_adt_a01_valido_sede2.hl7"), bundle("01_adt_a01_valido_sede2.hl7")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    ids = [e["resource"]["id"] for e in a["entry"]]
    assert len(ids) == len(set(ids))


def test_los_ids_son_validos_para_fhir():
    for e in bundle("01_adt_a01_valido_sede2.hl7")["entry"] + bundle("02_oru_r01_laboratorio_sede1.hl7")["entry"]:
        assert 0 < len(e["resource"]["id"]) <= 64 and all(c.isalnum() or c in "-." for c in e["resource"]["id"])


def test_conceptmap_lista_cada_diagnostico_local():
    cm = fhir.conceptmap([{"dx_local": "ASMA", "cie10": "J45.9", "descripcion": "Asma"}])
    assert cm["resourceType"] == "ConceptMap" and cm["group"][0]["element"][0]["target"][0]["code"] == "J45.9"


def test_toda_fecha_con_hora_lleva_zona_horaria_porque_fhir_la_exige():
    """`$validate` de HAPI rechazó «si una fecha tiene hora, debe tener zona horaria»: el HSB agrega la de Colombia (UTC-05:00)."""
    r = por_tipo(bundle("01_adt_a01_valido_sede2.hl7"))
    assert r["Encounter"][0]["period"]["start"].endswith("-05:00")
    assert fhir._fecha_hora("2026-11-07T10:15:00") == "2026-11-07T10:15:00-05:00"
    assert fhir._fecha_hora("2026-11-07") == "2026-11-07"                                   # una fecha sin hora se deja igual
    assert fhir._fecha_hora("2026-11-07T10:15:00Z") == "2026-11-07T10:15:00Z"               # con zona, no se toca
    assert fhir._fecha_hora("2026-11-07T10:15:00+01:00") == "2026-11-07T10:15:00+01:00"
    o = por_tipo(bundle("02_oru_r01_laboratorio_sede1.hl7"))["Observation"][0]
    assert "T" not in o["effectiveDateTime"] or o["effectiveDateTime"].endswith("-05:00")
