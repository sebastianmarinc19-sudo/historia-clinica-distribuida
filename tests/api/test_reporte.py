"""Reporte de historia clínica por paciente (vista del Reportero/auditor), estado de la plataforma y lo que ve cada rol.

El paciente ve en su vista quién consultó su reporte; el sello SHA-256 del reporte cambia si cambian los datos.
"""
import time
from datetime import date, timedelta

import httpx

from test_integracion import URL, c, esperar

T = int(time.time())
DOC = f"RP{T}"
NAC = date(1975, 1, 1) + timedelta(days=T % 9000)
E = {}


def _crear_paciente_con_encuentro():
    cuerpo = dict(cod_tipo_documento="CC", numero_documento=DOC, primer_nombre="Reporte", primer_apellido="Auditoria",
                  fecha_hora_nacimiento=NAC.isoformat() + "T08:00:00", cod_sexo="F", cod_pais_nacionalidad="COL", cod_pais_residencia="COL",
                  cod_municipio_residencia="70001", cod_etnia="06", cod_zona_territorial="1")
    assert c(1, "admision").post("/api/v2/pacientes", json=cuerpo).status_code == 201
    pid = c(1, "admision").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).json()["pacientes"][0]["id_paciente"]
    r = c(1, "admision").post("/api/v2/encuentros", json={
        "id_paciente": pid, "fecha_hora_inicio": "2026-11-07T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    assert r.status_code == 201, r.text
    E["enc"] = r.json()["encuentro"]["id_encuentro"]
    d = c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/diagnosticos",
                            json={"cod_cie10": "I10", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-07"})
    assert d.status_code == 201, d.text


def _reporte(sede=1, rol="reportero", doc=DOC):
    return c(sede, rol).get(f"/api/v2/reporte-hc/{doc}", params={"cod_tipo_documento": "CC"})


def test_el_auditor_obtiene_el_reporte_de_otro_paciente_agrupado_por_sede():
    _crear_paciente_con_encuentro()
    r = _reporte()
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["encontrado"] and d["documento"] == DOC and [s["id_sede"] for s in d["contenido"]["sedes"]] == [1, 2, 3]
    sincelejo = d["contenido"]["sedes"][0]
    assert sincelejo["paciente"]["primer_nombre"] == "Reporte" and len(sincelejo["encuentros"]) == 1
    assert sincelejo["encuentros"][0]["diagnosticos"][0]["cie10"] == "I10"
    assert d["contenido"]["sedes"][1]["paciente"] is None            # Cartagena aún no tiene registros propios del paciente
    cob = sincelejo["cobertura"]
    assert cob["total"] == 57 and cob["resumen"]["completo"] >= 1 and cob["faltantes"] and all(f["estado"] != "completo" for f in cob["faltantes"])
    assert len(d["sello_sha256"]) == 64 and d["fuente"].startswith("réplica local")


def test_el_reporte_lo_ven_tambien_las_otras_sedes_desde_su_copia():
    assert esperar(lambda: _reporte(sede=3).status_code == 200)
    d = _reporte(sede=3).json()
    assert d["sede_que_responde"] == 3 and d["contenido"]["sedes"][0]["encuentros"], "Corozal debe ver el encuentro de Sincelejo en su copia"
    assert {e["id_sede"]: e["estado"] for e in d["estado_sedes"]}[3] == "en_linea"


def test_el_sello_es_el_mismo_con_los_mismos_datos_y_cambia_si_cambian():
    esperar(lambda: _reporte(sede=2).json()["sello_sha256"] == _reporte().json()["sello_sha256"])
    antes = _reporte().json()["sello_sha256"]
    assert _reporte(sede=2).json()["sello_sha256"] == antes
    assert c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/diagnosticos",
                               json={"cod_cie10": "J45.9", "cod_tipo_diagnostico": "CO", "fecha_diagnostico": "2026-11-07"}).status_code == 201
    assert _reporte().json()["sello_sha256"] != antes


def test_documento_inexistente_da_404_y_el_reporte_es_del_auditor_el_medico_y_el_propio_paciente():
    assert _reporte(doc="NOEXISTE" + str(T)).status_code == 404
    assert _reporte(rol="medico").status_code == 200                       # el médico lo genera de cualquier paciente
    for rol in ("admision", "hsb", "sede"):
        assert _reporte(rol=rol).status_code == 403, rol
    assert httpx.get(URL[1] + f"/api/v2/reporte-hc/{DOC}", timeout=10).status_code == 401


def test_el_paciente_genera_su_reporte_y_no_el_de_otro():
    r = httpx.post(URL[1] + "/api/v2/auth/paciente", json={"cod_tipo_documento": "CC", "numero_documento": DOC, "fecha_nacimiento": NAC.isoformat()}, timeout=30)
    assert r.status_code == 200, r.text
    cab = {"Authorization": "Bearer " + r.json()["token"]}
    propio = httpx.get(URL[1] + f"/api/v2/reporte-hc/{DOC}", params={"cod_tipo_documento": "CC"}, headers=cab, timeout=30)
    assert propio.status_code == 200 and propio.json()["documento"] == DOC
    ajeno = httpx.get(URL[1] + "/api/v2/reporte-hc/9999999", params={"cod_tipo_documento": "CC"}, headers=cab, timeout=30)
    assert ajeno.status_code == 403
    assert httpx.get(URL[1] + "/api/v2/estado-plataforma", headers=cab, timeout=30).status_code == 403    # el tablero de estado no es del paciente


def test_el_reportero_descarga_el_bundle_de_un_encuentro_migrado_y_el_admisionista_no():
    assert c(1, "admision").get(f"/api/v2/bundles/{E['enc']}").status_code == 403
    r = c(1, "reportero").get(f"/api/v2/bundles/{E['enc']}")
    assert r.status_code in (200, 404), r.text          # 404 si el encuentro aún no se migró a FHIR (HAPI aparte)


def test_el_reporte_queda_registrado_y_el_paciente_lo_ve_en_sus_accesos():
    r = httpx.post(URL[1] + "/api/v2/auth/paciente", json={"cod_tipo_documento": "CC", "numero_documento": DOC, "fecha_nacimiento": NAC.isoformat()}, timeout=30)
    assert r.status_code == 200, r.text
    cab = {"Authorization": "Bearer " + r.json()["token"]}
    vistos = esperar(lambda: [a for a in httpx.get(URL[1] + "/api/v2/auditoria/mis-accesos", headers=cab, timeout=30).json()["accesos"]
                              if a["usuario"] == "reportero" and "reporte-hc" in a["ruta"]], timeout=10)
    assert vistos, "el paciente debe ver que el reportero consultó su reporte"


def test_estado_de_la_plataforma_para_medico_y_reportero_pero_no_para_admision():
    for rol in ("medico", "reportero"):
        r = c(1, rol).get("/api/v2/estado-plataforma")
        assert r.status_code == 200, (rol, r.text)
        d = r.json()
        assert [s["id_sede"] for s in d["sedes"]] == [1, 2, 3] and d["base_de_datos"] == "ok"
        assert d["auditoria"]["ok"] is True and d["hapi_fhir"] in ("ok", "no_disponible")
        assert {s["id_sede"]: s["estado"] for s in d["sedes"]}[1] == "en_linea"
    assert c(1, "admision").get("/api/v2/estado-plataforma").status_code == 403
