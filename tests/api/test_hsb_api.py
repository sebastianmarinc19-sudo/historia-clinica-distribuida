"""Lo que el bus (HSB) necesita de la API de la sede: cuenta de servicio con permisos mínimos y escrituras idempotentes.

Un reintento del bus, o un mensaje reenviado, no puede crear un segundo encuentro, diagnóstico, triage u observación, y un mensaje con
datos mínimos no puede borrar lo que la sede ya tenía del paciente.
"""
import time
import uuid

from test_integracion import c, paciente_json

T = int(time.time())
DOC = f"HS{T}"
E = {}


def _hsb(sede=1):
    return c(sede, "hsb")


# ---------------------------------------------------------------- permisos mínimos de la cuenta de servicio
def test_la_cuenta_hsb_puede_escribir_lo_que_el_bus_entrega():
    r = _hsb().post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC))
    assert r.status_code == 201, r.text
    E["pac"] = r.json()["paciente"]["id_paciente"]


def test_la_cuenta_hsb_no_puede_leer_historias_ni_reportes_ni_el_mpi_ni_decidir_nada():
    pid = E["pac"]
    s = _hsb()
    assert s.get(f"/api/v2/historia-federada/{DOC}").status_code == 403
    assert s.get(f"/api/v2/pacientes/{pid}").status_code == 403
    assert s.get("/api/v2/cobertura").status_code == 403
    assert s.get("/api/v2/auditoria/accesos").status_code == 403
    assert s.post(f"/api/v2/mpi/resolver/{pid}").status_code == 403
    assert s.get("/api/v2/mpi/revision", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).status_code == 403
    assert s.post(f"/api/v2/migracion/paciente/{pid}").status_code == 403      # migrar a FHIR es del médico


def test_los_demas_roles_no_obtienen_permisos_nuevos_con_este_cambio():
    assert c(1, "reportero").post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC + "x")).status_code == 403


# ---------------------------------------------------------------- idempotencia de las escrituras
def _encuentro(id_enc):
    return {"id_encuentro": id_enc, "id_paciente": E["pac"], "fecha_hora_inicio": "2026-11-07T10:15:00", "cod_modalidad": "01",
            "cod_grupo_servicio": "01", "cod_entorno": "01", "cod_via_ingreso": "02", "cod_causa_atencion": "01", "cod_entidad_responsable": "PART"}


def test_abrir_el_mismo_encuentro_dos_veces_devuelve_el_existente():
    E["enc"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hsb-prueba-{T}"))
    primero = _hsb().post("/api/v2/encuentros", json=_encuentro(E["enc"]))
    segundo = _hsb().post("/api/v2/encuentros", json=_encuentro(E["enc"]))
    assert primero.status_code == 201 and primero.json()["accion"] == "creado" and primero.json()["encuentro"]["id_encuentro"] == E["enc"]
    assert segundo.status_code == 200 and segundo.json()["accion"] == "existente"


def test_un_id_de_encuentro_ya_usado_por_otro_paciente_es_un_conflicto():
    otro = _hsb().post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC + "o")).json()["paciente"]["id_paciente"]
    r = _hsb().post("/api/v2/encuentros", json={**_encuentro(E["enc"]), "id_paciente": otro})
    assert r.status_code == 409


def test_sin_id_el_encuentro_sigue_siendo_nuevo_cada_vez_como_antes():
    cuerpo = {k: v for k, v in _encuentro("x").items() if k != "id_encuentro"}
    a, b = c(1, "admision").post("/api/v2/encuentros", json=cuerpo), c(1, "admision").post("/api/v2/encuentros", json=cuerpo)
    assert a.status_code == b.status_code == 201 and a.json()["encuentro"]["id_encuentro"] != b.json()["encuentro"]["id_encuentro"]


def test_el_mismo_diagnostico_y_el_mismo_triage_dos_veces_devuelven_200_existente():
    base = f"/api/v2/encuentros/{E['enc']}"
    dx = {"cod_cie10": "J00", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-07"}
    assert _hsb().post(f"{base}/diagnosticos", json=dx).status_code == 201
    r = _hsb().post(f"{base}/diagnosticos", json=dx)
    assert r.status_code == 200 and r.json()["accion"] == "existente"
    tri = {"fecha_hora_triage": "2026-11-07T10:20:00", "cod_triage": 3}
    assert _hsb().post(f"{base}/triage", json=tri).status_code == 201
    assert _hsb().post(f"{base}/triage", json=tri).json()["accion"] == "existente"


def test_un_diagnostico_de_ingreso_distinto_o_un_triage_distinto_siguen_siendo_conflicto():
    base = f"/api/v2/encuentros/{E['enc']}"
    assert _hsb().post(f"{base}/diagnosticos", json={"cod_cie10": "I10", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-07"}).status_code == 409
    assert _hsb().post(f"{base}/triage", json={"fecha_hora_triage": "2026-11-07T10:20:00", "cod_triage": 5}).status_code in (409, 422)


def test_la_misma_observacion_con_el_mismo_id_no_se_duplica():
    base = f"/api/v2/encuentros/{E['enc']}/observaciones"
    id_obs = str(uuid.uuid5(uuid.NAMESPACE_URL, f"obs-{T}"))
    cuerpo = {"id_observacion": id_obs, "cod_loinc": "8310-5", "valor_numerico": 38.5, "cod_unidad": "C", "fecha_hora_medicion": "2026-11-07T10:30:00"}
    assert _hsb().post(base, json=cuerpo).status_code == 201
    r = _hsb().post(base, json=cuerpo)
    assert r.status_code == 200 and r.json()["accion"] == "existente"
    detalle = c(1, "medico").get(f"/api/v2/encuentros/{E['enc']}").json()
    assert len(detalle["observaciones"]) == 1


def test_un_codigo_fuera_del_catalogo_se_rechaza_con_422():
    r = _hsb().post(f"/api/v2/encuentros/{E['enc']}/diagnosticos", json={"cod_cie10": "Z99.9", "cod_tipo_diagnostico": "RE", "fecha_diagnostico": "2026-11-07"})
    assert r.status_code == 422


# ---------------------------------------------------------------- actualización parcial del paciente
def test_un_mensaje_con_datos_minimos_no_borra_lo_que_la_sede_ya_tenia():
    completo = paciente_json(numero_documento=DOC + "m", cod_etnia="06", cod_zona_territorial="1", cod_municipio_residencia="70001")
    assert c(1, "admision").post("/api/v2/pacientes", json=completo).status_code == 201
    minimo = {"cod_tipo_documento": "CC", "numero_documento": DOC + "m", "primer_nombre": "Ana", "primer_apellido": "Torres",
              "fecha_hora_nacimiento": completo["fecha_hora_nacimiento"], "cod_sexo": "F", "cod_pais_residencia": "COL"}
    r = _hsb().post("/api/v2/pacientes", json=minimo)
    assert r.status_code == 200 and r.json()["accion"] == "actualizado"
    p = r.json()["paciente"]
    assert p["cod_etnia"] == "06" and p["cod_zona_territorial"] == "1" and p["cod_municipio_residencia"] == "70001"
