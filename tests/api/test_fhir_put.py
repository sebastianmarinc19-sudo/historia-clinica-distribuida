"""Migración a FHIR con PUT e ids deterministas: migrar dos veces el mismo encuentro no duplica nada en HAPI.

Necesita el HAPI de Sincelejo (se omite si no responde). Los recursos propios (Patient, Encounter, Condition, Observation) se crean con
`PUT` en un Bundle `transaction` y el RDA con `PUT Bundle/rda-<encuentro>`; el id sale de los datos, no lo asigna HAPI.
"""
import time

import httpx
import pytest

from test_integracion import c, paciente_json

T = int(time.time())
DOC = f"PF{T}"
E = {}


def _hapi_ok():
    r = c(1, "medico").get("/api/health")
    return r.status_code in (200, 503) and r.json().get("fhir", {}).get("estado") == "ok"


@pytest.fixture(scope="module", autouse=True)
def _requiere_hapi():
    if not _hapi_ok():
        pytest.skip("el HAPI FHIR de Sincelejo no responde")


def test_preparacion_encuentro_con_diagnostico_y_observacion():
    assert c(1, "admision").post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC)).status_code == 201
    E["pac"] = c(1, "admision").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).json()["pacientes"][0]["id_paciente"]
    r = c(1, "admision").post("/api/v2/encuentros", json={
        "id_paciente": E["pac"], "fecha_hora_inicio": "2026-11-07T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    assert r.status_code == 201, r.text
    E["enc"] = r.json()["encuentro"]["id_encuentro"]
    base = f"/api/v2/encuentros/{E['enc']}"
    assert c(1, "medico").post(f"{base}/diagnosticos", json={"cod_cie10": "J00", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-07"}).status_code == 201
    assert c(1, "medico").post(f"{base}/observaciones", json={"cod_loinc": "8310-5", "valor_numerico": 38.5, "cod_unidad": "C",
                                                              "fecha_hora_medicion": "2026-11-07T09:10:00"}).status_code == 201


def _migrar():
    """HAPI con poca memoria tarda en la primera creación y en la primera actualización tras arrancar (la API espera hasta 45 s y responde 503):
    se reintenta, porque la operación es idempotente. Un error distinto de 503 sí falla la prueba."""
    m = c(1, "medico")
    cliente = httpx.Client(base_url=str(m.base_url), headers=dict(m.headers), timeout=120)
    for intento in range(3):
        r = cliente.post(f"/api/v2/migracion/encuentro/{E['enc']}")
        if r.status_code != 503:
            break
    assert r.status_code == 200, r.text
    return r.json()


def test_la_migracion_crea_recursos_propios_con_ids_deterministas():
    m = _migrar()
    assert m["fhir_bundle_id"] == f"rda-{E['enc']}"
    urls = m["recursos_propios_en_hapi"]
    assert f"Patient/pac-{DOC}" in urls and f"Encounter/enc-1-{E['enc']}" in urls
    assert sum(u.startswith("Condition/") for u in urls) == 1 and sum(u.startswith("Observation/") for u in urls) == 1
    E["bundle_id"] = m["fhir_bundle_id"]


def test_migrar_otra_vez_no_duplica_en_hapi_ni_cambia_los_ids():
    m = _migrar()
    assert m["fhir_bundle_id"] == E["bundle_id"]                                      # el mismo Bundle, no otro nuevo
    b = c(1, "medico").get(f"/api/v2/bundles/{E['enc']}", params={"verificar_hapi": "true"}).json()
    assert b["fhir_bundle_id"] == E["bundle_id"] and b["hapi"]["estado"] == "ok" and b["hapi"]["type"] == "document"
    assert b["hapi"]["recursos_propios"] == {"encuentro": 1, "condiciones": 1, "observaciones": 1}


def test_el_paciente_queda_con_el_id_que_usa_el_bus():
    p = c(1, "medico").get(f"/api/v2/pacientes/{E['pac']}").json()
    assert (p.get("paciente") or p)["fhir_patient_id"] == f"pac-{DOC}"
    r = c(1, "medico").post(f"/api/v2/migracion/paciente/{E['pac']}")
    assert r.status_code == 200 and r.json()["ya_migrado"] is True and r.json()["fhir_patient_id"] == f"pac-{DOC}"
