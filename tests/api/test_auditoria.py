"""Auditoría encadenada por hash: sello en las escrituras, verificador y acceso del paciente a su propio registro.

La alteración de la cadena en la base (UPDATE a mano) no se puede hacer por la API: la prueba de punta a punta está en
scripts/prueba_auditoria.sh. Aquí se comprueba lo que sí ve un cliente.
"""
import re
import time
from datetime import date, timedelta

import httpx

from test_integracion import URL, c, esperar, paciente_json

T = int(time.time())
DOC = f"AD{T}"
NAC = date(1960, 1, 1) + timedelta(days=T % 15000)
E = {}
SELLO = re.compile(r"^\d+:[0-9a-f]{64}$")


def _verificar(rol="reportero", sede=1):
    r = c(sede, rol).get("/api/v2/auditoria/verificar")
    assert r.status_code == 200, r.text
    return r.json()


def test_una_escritura_exitosa_devuelve_el_sello_de_su_evento():
    r = c(1, "admision").post("/api/v2/pacientes", json=paciente_json(
        numero_documento=DOC, fecha_hora_nacimiento=NAC.isoformat() + "T08:00:00"))
    assert r.status_code == 201, r.text
    sello = r.headers.get("x-sello-auditoria", "")
    assert SELLO.match(sello), sello
    E["seq"], E["hash"] = sello.split(":")


def test_las_lecturas_y_los_rechazos_no_llevan_sello_porque_se_anexan_en_segundo_plano():
    assert "x-sello-auditoria" not in c(1, "medico").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).headers
    r = c(1, "reportero").post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC + "r"))
    assert r.status_code == 403 and "x-sello-auditoria" not in r.headers


def test_el_evento_sellado_aparece_en_el_registro_con_el_mismo_hash():
    filas = esperar(lambda: [f for f in c(1, "reportero").get("/api/v2/auditoria/accesos", params={"limite": 500}).json()["accesos"]
                             if str(f["seq"]) == E["seq"]], timeout=10)
    assert filas and filas[0]["hash"] == E["hash"] and filas[0]["metodo"] == "POST" and filas[0]["estado"] == 201
    assert filas[0]["usuario"] == "admision" and filas[0]["documento"] in (None, DOC) and len(filas[0]["hash_previo"]) == 64


def _escribir_en(sede):
    r = c(sede, "admision").post("/api/v2/pacientes", json=paciente_json(numero_documento=f"{DOC}s{sede}"))
    assert r.status_code in (200, 201), r.text
    return r.headers.get("x-sello-auditoria")


def test_la_cadena_de_cada_sede_se_verifica_y_su_cabeza_incluye_el_sello():
    for sede in (1, 2, 3):
        _escribir_en(sede)
        v = _verificar(sede=sede)
        assert v["ok"] is True and v["primer_fallo"] is None and v["verificados"] >= 1 and v["sede"] == sede, v
    v = _verificar()
    assert v["cabeza"]["seq"] >= int(E["seq"])


def test_cada_sede_lleva_su_propia_cadena_y_no_se_replica():
    _escribir_en(1), _escribir_en(2)
    ref = _verificar(sede=1)["cabeza"]
    otra = _verificar(sede=2)["cabeza"]
    assert ref["hash"] != otra["hash"]


def test_los_sellos_son_consecutivos_y_encadenados_bajo_escrituras_concurrentes():
    import concurrent.futures as cf
    def escribir(i):
        r = c(1, "admision").post("/api/v2/pacientes", json=paciente_json(numero_documento=f"{DOC}c{i}"))
        assert r.status_code == 201, r.text
        return int(r.headers["x-sello-auditoria"].split(":")[0])
    with cf.ThreadPoolExecutor(8) as ex:
        seqs = list(ex.map(escribir, range(16)))
    assert len(set(seqs)) == 16                      # ninguna secuencia repetida aunque las réplicas escriban a la vez
    assert _verificar()["ok"] is True


def test_roles_del_verificador():
    for rol, esperado in (("reportero", 200), ("medico", 200), ("admision", 403)):
        assert c(1, rol).get("/api/v2/auditoria/verificar").status_code == esperado, rol
    assert httpx.get(URL[1] + "/api/v2/auditoria/verificar", timeout=10).status_code == 401


def test_el_paciente_ve_quien_accedio_a_su_historia_y_solo_la_suya():
    cuerpo = {"cod_tipo_documento": "CC", "numero_documento": DOC, "fecha_nacimiento": NAC.isoformat()}
    r = httpx.post(URL[1] + "/api/v2/auth/paciente", json=cuerpo, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    c(1, "medico").get(f"/api/v2/historia-federada/{DOC}", params={"cod_tipo_documento": "CC"})
    mios = esperar(lambda: [a for a in httpx.get(URL[1] + "/api/v2/auditoria/mis-accesos", headers={"Authorization": "Bearer " + token}, timeout=30).json()["accesos"]
                            if a["usuario"] == "medico"], timeout=10)
    assert mios and mios[0]["rol"] == "medico"
    assert set(mios[0]) == {"seq", "instante", "usuario", "rol", "metodo", "ruta", "estado"}      # sin ip ni hash: lo que necesita ver el paciente
    ajeno = c(1, "medico").get("/api/v2/auditoria/mis-accesos")
    assert ajeno.status_code == 403                                                              # el personal usa el registro de la sede


# ------------------------------------------------------------------ anclaje de la cabeza en las otras sedes
def _anclas_de(sede_que_guarda, id_sede, rol="reportero"):
    r = c(sede_que_guarda, rol).get(f"/api/v2/auditoria/anclas/{id_sede}", params={"limite": 20})
    assert r.status_code == 200, r.text
    return r.json()["anclas"]


def test_cada_sede_ancla_su_cabeza_en_las_otras_dos_y_el_verificador_las_comprueba():
    _escribir_en(1)
    # el anclaje corre cada HC_ANCLA_INTERVALO_S (10 s) en segundo plano: se espera a que el par tenga anclas de la sede 1
    assert esperar(lambda: _anclas_de(2, 1) and _anclas_de(3, 1), timeout=40), "las sedes 2 y 3 no recibieron el anclaje de la sede 1"
    v = esperar(lambda: (lambda r: r if r["anclaje"]["ok"] is True else None)(_verificar(sede=1)), timeout=40)
    assert v, "el verificador no confirmó el anclaje"
    assert v["cadena_local_ok"] is True and v["ok"] is True
    estados = {p["id_sede"]: p["estado"] for p in v["anclaje"]["pares"]}
    assert estados == {2: "ok", 3: "ok"}, estados
    ancla = _anclas_de(2, 1)[0]                                       # lo anclado es un evento real de la cadena de la sede 1
    assert re.fullmatch(r"[0-9a-f]{64}", ancla["hash"]) and ancla["seq"] <= v["cabeza"]["seq"]


def test_recibir_un_ancla_exige_el_rol_de_sede_y_un_par_valido():
    ancla = _anclas_de(2, 1)[0]
    cuerpo = {"id_sede": 1, "seq": ancla["seq"], "hash": ancla["hash"]}
    assert c(2, "reportero").post("/api/v2/auditoria/anclas", json=cuerpo).status_code == 403          # solo el rol de sede
    assert c(2, "admision").post("/api/v2/auditoria/anclas", json=cuerpo).status_code == 403
    assert c(2, "sede").post("/api/v2/auditoria/anclas", json={**cuerpo, "id_sede": 2}).status_code == 422   # no es un par
    assert c(2, "sede").post("/api/v2/auditoria/anclas", json={**cuerpo, "id_sede": 9}).status_code == 422
    assert c(2, "sede").post("/api/v2/auditoria/anclas", json={**cuerpo, "hash": "xyz"}).status_code == 422
    assert c(2, "sede").post("/api/v2/auditoria/anclas", json=cuerpo).json()["estado"] == "repetida"


def test_anclar_otro_hash_para_una_secuencia_ya_anclada_es_409_y_no_se_guarda():
    ancla = _anclas_de(3, 1)[0]
    falso = ("0" if ancla["hash"][0] != "0" else "1") + ancla["hash"][1:]
    r = c(3, "sede").post("/api/v2/auditoria/anclas", json={"id_sede": 1, "seq": ancla["seq"], "hash": falso})
    assert r.status_code == 409, r.text
    assert _anclas_de(3, 1)[0]["hash"] == ancla["hash"]                  # el ancla original sigue intacta


def test_las_anclas_las_leen_el_reportero_y_el_medico_pero_no_el_paciente_ni_el_admisionista():
    assert c(2, "medico").get("/api/v2/auditoria/anclas/1").status_code == 200
    assert c(2, "admision").get("/api/v2/auditoria/anclas/1").status_code == 403


def test_el_anclaje_no_agrega_eventos_a_la_cadena_en_bucle():
    # si anclar se registrara en la auditoría, cada ancla recibida cambiaría la cabeza y generaría otra: la cadena crecería sin parar
    antes = _verificar(sede=2)["cabeza"]["seq"]
    time.sleep(25)                                                      # más de dos ciclos de anclaje
    assert _verificar(sede=2)["cabeza"]["seq"] - antes <= 3             # solo los accesos de la propia prueba


# ------------------------------------------------------------------ AuditEvent de FHIR
def test_la_auditoria_se_expone_como_bundle_de_auditevent_con_la_cadena():
    _escribir_en(1)
    r = c(1, "reportero").get("/api/v2/auditoria/fhir", params={"limite": 20})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/fhir+json")
    b = r.json()
    assert b["resourceType"] == "Bundle" and b["type"] == "searchset" and b["total"] == len(b["entry"]) > 0
    ev = b["entry"][0]["resource"]
    assert ev["resourceType"] == "AuditEvent" and ev["id"].startswith("audit-1-")
    assert ev["type"]["code"] == "rest" and ev["action"] in "CRUD" and ev["outcome"] in ("0", "4", "8")
    assert ev["agent"][0]["requestor"] is True and ev["source"]["site"] == "Sincelejo"
    cadena = [e for e in ev["entity"] if e["type"]["code"] == "4"][0]["detail"]
    assert {d["type"] for d in cadena} == {"seq", "hash", "hash_previo"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", d["valueString"]) for d in cadena if d["type"] != "seq")


def test_el_auditevent_del_paciente_lo_referencia_y_solo_lo_leen_reportero_y_medico():
    _escribir_en(1)
    c(1, "medico").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": f"{DOC}s1"})     # una consulta lleva el documento
    b = esperar(lambda: (lambda x: x if x["total"] >= 1 else None)(
        c(1, "reportero").get("/api/v2/auditoria/fhir", params={"documento": f"{DOC}s1", "limite": 10}).json()), timeout=10)
    assert b and b["total"] >= 1
    ref = [e["what"]["reference"] for x in b["entry"] for e in x["resource"]["entity"] if "reference" in e.get("what", {})]
    assert ref and all(r == f"Patient/pac-{DOC}s1" for r in ref)
    assert c(1, "medico").get("/api/v2/auditoria/fhir").status_code == 200
    assert c(1, "admision").get("/api/v2/auditoria/fhir").status_code == 403
