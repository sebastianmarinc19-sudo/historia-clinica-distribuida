"""Pruebas de integración contra las 3 sedes en ejecución.

Se ejecutan dentro de la red de compose (ver scripts/prueba_api.sh).
Cada prueba usa un documento nuevo, así que se pueden repetir sin limpiar.
Recorre los casos de uso CU-01 a CU-15 y comprueba la regla de sede dueña,
la replicación y la convergencia del MPI entre sedes.
"""
import os
import time
from datetime import date, timedelta

import httpx
import pytest

import sesion

URL = {
    1: os.getenv("API_SINCELEJO", "http://api_sincelejo:8001"),
    2: os.getenv("API_CARTAGENA", "http://api_cartagena:8001"),
    3: os.getenv("API_COROZAL", "http://api_corozal:8001"),
}
GATEWAY = os.getenv("API_GATEWAY", "https://hc_gateway")          # HTTPS; certificado firmado por la CA de laboratorio
ESPERA_REPLICA = float(os.getenv("ESPERA_REPLICA", "30"))
ESPERA_FHIR = float(os.getenv("ESPERA_FHIR", "480"))   # arranque en frío de 3 HAPI en una máquina con poca RAM

DOC = f"IT{int(time.time())}"          # documento único por corrida
E = {}                                  # estado compartido entre pruebas (orden de archivo)


def auth(usuario: str = "admin") -> dict:
    """Cabecera con el token del usuario (el administrador entra a todas las rutas; un token vale en las 3 sedes)."""
    return {"Authorization": "Bearer " + sesion.token(URL[1], usuario)}


def c(sede: int, usuario: str = "admin") -> httpx.Client:
    return httpx.Client(base_url=URL[sede], timeout=30, headers=auth(usuario))


def esperar(condicion, timeout=ESPERA_REPLICA, paso=0.4):
    limite = time.time() + timeout
    while True:
        valor = condicion()
        if valor:
            return valor
        if time.time() > limite:
            return None
        time.sleep(paso)


# Fecha de nacimiento única por corrida: con los pesos del MPI (0,6 nombre +
# 0,3 fecha + 0,1 sexo), dos personas distintas con el mismo nombre, fecha y
# sexo se unirían. Así las corridas anteriores no contaminan esta.
NACIMIENTO = (date(1940, 1, 1) + timedelta(days=int(time.time()) % 20000)).isoformat() + "T10:00:00"


def paciente_json(**kw):
    base = dict(cod_tipo_documento="CC", numero_documento=DOC, primer_nombre="Ana",
                primer_apellido="Torres", segundo_apellido="Pacheco",
                fecha_hora_nacimiento=NACIMIENTO, cod_sexo="F",
                cod_pais_nacionalidad="COL", cod_pais_residencia="COL",
                cod_municipio_residencia="70001", cod_etnia="06", cod_zona_territorial="1")
    base.update(kw)
    return base


def buscar_en(sede: int, doc=DOC):
    r = c(sede).get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": doc})
    return r.json()["pacientes"] if r.status_code == 200 else []


# ------------------------------------------------------------------ salud
def test_las_tres_sedes_estan_sanas():
    for sede in (1, 2, 3):
        r = c(sede).get("/api/health")
        assert r.status_code == 200, r.text
        assert r.json()["db"] == "ok" and r.json()["sede"]["id"] == sede


def test_replicacion_activa_en_cada_sede():
    for sede in (1, 2, 3):
        susc = c(sede).get("/api/v2/replicacion").json()["suscripciones"]
        assert len(susc) == 2 and all(s["habilitada"] for s in susc)


# ------------------------------------------------------------ CU-01 / réplica
def test_cu01_registrar_paciente_en_sincelejo():
    r = c(1).post("/api/v2/pacientes", json=paciente_json())
    assert r.status_code == 201, r.text
    E["pac1"] = r.json()["paciente"]["id_paciente"]
    assert r.json()["paciente"]["id_sede_origen"] == 1
    assert r.json()["paciente"]["fhir_patient_id"] is None


def test_cu01_registrar_de_nuevo_actualiza():
    r = c(1).post("/api/v2/pacientes", json=paciente_json(segundo_nombre="Maria"))
    assert r.status_code == 200 and r.json()["accion"] == "actualizado"
    assert r.json()["paciente"]["id_paciente"] == E["pac1"]


def test_cu01_codigo_fuera_de_catalogo_se_rechaza():
    r = c(1).post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC + "x", cod_sexo="Z"))
    assert r.status_code == 422 and r.json()["error"] == "codigo_o_referencia_invalida"


def test_paciente_se_replica_a_cartagena_y_corozal():
    for sede in (2, 3):
        fila = esperar(lambda s=sede: next((p for p in buscar_en(s) if p["_id_sede"] == 1), None))
        assert fila, f"el paciente no llegó a la sede {sede}"
        assert fila["id_paciente"] == E["pac1"]


def test_escribir_sobre_registro_de_otra_sede_da_409_con_la_dueña():
    r = c(2).post("/api/v2/encuentros", json={
        "id_paciente": E["pac1"], "fecha_hora_inicio": "2026-03-15T08:30:00", "cod_modalidad": "01",
        "cod_grupo_servicio": "01", "cod_entorno": "01", "cod_via_ingreso": "01",
        "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    assert r.status_code == 409
    cuerpo = r.json()
    assert cuerpo["error"] == "sede_no_propietaria" and cuerpo["sede_propietaria"] == 1
    assert cuerpo["sede_propietaria_nombre"] == "Sincelejo"


# --------------------------------------------------------------- CU-02..CU-09
def test_cu02_a_cu09_flujo_clinico_completo_en_sincelejo():
    s = c(1)
    prof = s.post("/api/v2/profesionales", json={
        "cod_tipo_documento": "CC", "numero_documento": f"P{DOC}", "nombres": "Camila", "apellidos": "Restrepo"})
    assert prof.status_code == 200, prof.text
    E["prof"] = prof.json()["profesional"]["id_profesional"]

    enc = s.post("/api/v2/encuentros", json={
        "id_paciente": E["pac1"], "fecha_hora_inicio": "2026-03-15T08:30:00", "cod_modalidad": "01",
        "cod_grupo_servicio": "01", "cod_entorno": "01", "cod_via_ingreso": "01",
        "cod_causa_atencion": "01", "cod_ocupacion": "231000", "cod_entidad_responsable": "EPS001"})
    assert enc.status_code == 201, enc.text
    E["enc"] = enc.json()["encuentro"]["id_encuentro"]
    assert enc.json()["encuentro"]["estado_migracion"] == "PENDIENTE"
    base = f"/api/v2/encuentros/{E['enc']}"

    assert s.post(f"{base}/triage", json={"fecha_hora_triage": "2026-03-15T08:35:00", "cod_triage": 3}).status_code == 201
    assert s.post(f"{base}/diagnosticos", json={"cod_cie10": "J00", "cod_tipo_diagnostico": "IN",
                                                 "fecha_diagnostico": "2026-03-15"}).status_code == 201

    med = s.post(f"{base}/tecnologias", json={
        "cod_tecnologia": "19938", "cod_finalidad": "02", "fecha_prescripcion": "2026-03-15T08:45:00",
        "medicamento": {"cod_medicamento": "19938", "dosis_prescrita": 500, "cod_unidad_dosis": "mg",
                        "cod_via_administracion": "01", "duracion_tratamiento": 5, "cod_unidad_duracion": "d",
                        "frecuencia_valor": 8, "cod_unidad_frecuencia": "h"}})
    assert med.status_code == 201, med.text
    E["tec_med"] = med.json()["tecnologia"]["id_tecnologia_encuentro"]

    proc = s.post(f"{base}/tecnologias", json={
        "cod_tecnologia": "890201", "cod_finalidad": "01", "fecha_prescripcion": "2026-03-15T08:40:00"})
    assert proc.status_code == 201, proc.text

    assert s.post(f"{base}/entregas", json={
        "id_tecnologia_encuentro": E["tec_med"], "id_profesional": E["prof"],
        "fecha_entrega": "2026-03-15T09:00:00", "dosis_administrada": 500, "cod_unidad_dosis": "mg",
        "unidades_entregadas": 1}).status_code == 201
    assert s.post(f"{base}/observaciones", json={
        "cod_loinc": "8310-5", "valor_numerico": 38.5, "cod_unidad": "C",
        "fecha_hora_medicion": "2026-03-15T09:10:00"}).status_code == 201
    assert s.post(f"{base}/antecedentes", json={
        "cod_cie10": "I10", "descripcion": "Hipertensión diagnosticada hace 3 años"}).status_code == 201
    assert s.post(f"{base}/exposiciones", json={"cod_factor_riesgo": "004"}).status_code == 201
    assert s.post(f"{base}/diagnosticos", json={"cod_cie10": "J00", "cod_tipo_diagnostico": "EP",
                                                 "fecha_diagnostico": "2026-03-15"}).status_code == 201
    egreso = s.post(f"{base}/egreso", json={
        "fecha_hora_fin": "2026-03-15T09:30:00", "cod_condicion_egreso": "01",
        "id_profesional_egreso": E["prof"], "dias_incapacidad": 0})
    assert egreso.status_code == 201, egreso.text

    det = s.get(base).json()
    assert det["fecha_hora_fin"].startswith("2026-03-15T09:30")
    assert len(det["diagnosticos"]) == 2 and len(det["tecnologias"]) == 2
    assert det["triage"]["cod_triage"] == 3 and det["egreso"]["cod_condicion_egreso"] == "01"
    assert any(t["medicamento"] for t in det["tecnologias"])


def test_reglas_del_modelo_se_hacen_cumplir_via_api():
    s, base = c(1), f"/api/v2/encuentros/{E['enc']}"
    # Un segundo diagnóstico de ingreso viola el índice único parcial.
    r = s.post(f"{base}/diagnosticos", json={"cod_cie10": "I10", "cod_tipo_diagnostico": "IN",
                                              "fecha_diagnostico": "2026-03-15"})
    assert r.status_code == 409 and r.json()["error"] == "duplicado"
    # CIE-10 fuera de catálogo.
    r = s.post(f"{base}/diagnosticos", json={"cod_cie10": "ZZZ99", "cod_tipo_diagnostico": "RE",
                                              "fecha_diagnostico": "2026-03-15"})
    assert r.status_code == 422
    # Valor numérico sin unidad.
    r = s.post(f"{base}/observaciones", json={"cod_loinc": "8310-5", "valor_numerico": 37,
                                               "fecha_hora_medicion": "2026-03-15T09:10:00"})
    assert r.status_code == 422
    # Medicamento sobre una tecnología que no es MEDICAMENTO.
    r = s.post(f"{base}/tecnologias", json={
        "cod_tecnologia": "890201", "cod_finalidad": "01", "fecha_prescripcion": "2026-03-15T08:40:00",
        "medicamento": {"cod_medicamento": "19938", "dosis_prescrita": 1, "cod_unidad_dosis": "mg",
                        "cod_via_administracion": "01", "duracion_tratamiento": 1, "cod_unidad_duracion": "d",
                        "frecuencia_valor": 8, "cod_unidad_frecuencia": "h"}})
    assert r.status_code == 422


def test_historia_clinica_llega_replicada_a_corozal():
    def detalle():
        r = c(3).get(f"/api/v2/encuentros/{E['enc']}")
        if r.status_code != 200:
            return None
        d = r.json()
        completo = len(d["diagnosticos"]) == 2 and len(d["tecnologias"]) == 2 and d["egreso"] and d["triage"]
        return d if completo else None
    d = esperar(detalle)
    assert d, "la historia clínica de Sincelejo no llegó completa a Corozal"
    assert d["es_replica"] is True and d["sede_nombre"] == "Sincelejo"
    assert any(t["medicamento"] and t["entregas"] for t in d["tecnologias"])


# ---------------------------------------------------------------- CU-11 / MPI
def test_cu11_mismo_documento_en_cartagena_y_mpi_converge_en_las_tres_sedes():
    r = c(2).post("/api/v2/pacientes", json=paciente_json(primer_nombre="ANA"))
    assert r.status_code == 201, r.text
    E["pac2"] = r.json()["paciente"]["id_paciente"]
    # Cada sede debe ver los dos registros antes de resolver.
    for sede in (1, 2, 3):
        assert esperar(lambda s=sede: len(buscar_en(s)) == 2), f"sede {sede} no ve los 2 registros"

    ids = {}
    for sede in (1, 2, 3):
        res = c(sede).post(f"/api/v2/mpi/resolver/{E['pac1']}")
        assert res.status_code == 200, res.text
        cuerpo = res.json()
        assert cuerpo["resuelto"] is True and cuerpo["miembros_totales"] == 2
        assert cuerpo["score"] == 1.0
        ids[sede] = cuerpo["id_mpi"]
    # Determinista: las tres sedes calcularon el mismo id_mpi sin coordinarse.
    assert len(set(ids.values())) == 1, ids
    E["mpi"] = ids[1]


# ---------------------------------------------------------------------- CU-13
def test_cu13_historia_federada_se_consulta_desde_otra_sede():
    r = c(3).get(f"/api/v2/historia-federada/{DOC}", params={"cod_tipo_documento": "CC"})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["encontrado"] and h["federado"] and h["id_mpi"] == E["mpi"]
    assert {s["id_sede"] for s in h["sedes"]} == {1, 2}
    assert h["total_encuentros"] >= 1
    enc = next(e for e in h["encuentros"] if e["id_encuentro"] == E["enc"])
    assert enc["es_replica"] is True and enc["sede_nombre"] == "Sincelejo"


# ------------------------------------------------------------- CU-10 / CU-12 FHIR
def _fhir_listo(sede: int) -> bool:
    r = c(sede).get("/api/health")
    return r.status_code == 200 and r.json()["fhir"]["estado"] == "ok"


def test_cu10_migrar_a_fhir_y_cu12_consultar_el_rda():
    if not esperar(lambda: _fhir_listo(1), timeout=ESPERA_FHIR, paso=3):
        pytest.skip("HAPI FHIR de Sincelejo no está listo")
    # Escribir en la sede equivocada se rechaza también para la migración
    # (primero debe haber llegado la réplica del encuentro a Cartagena).
    assert esperar(lambda: c(2).get(f"/api/v2/encuentros/{E['enc']}").status_code == 200), \
        "el encuentro no llegó a Cartagena"
    assert c(2).post(f"/api/v2/migracion/encuentro/{E['enc']}").status_code == 409

    r = c(1).post(f"/api/v2/migracion/paciente/{E['pac1']}")
    assert r.status_code == 200, r.text
    assert r.json()["fhir_patient_id"]
    r2 = c(1).post(f"/api/v2/migracion/paciente/{E['pac1']}")
    assert r2.json()["ya_migrado"] is True

    r = c(1).post(f"/api/v2/migracion/encuentro/{E['enc']}")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["estado_migracion"] == "MIGRADO" and m["fhir_bundle_id"]
    assert m["recursos_incluidos"] == {"diagnosticos": 2, "medicamentos": 1, "procedimientos": 1, "observaciones": 1}
    assert m["identidad_federada"]["id_mpi"] == E["mpi"]
    E["bundle_id"] = m["fhir_bundle_id"]

    # CU-12 en la sede dueña, verificando directamente contra su HAPI.
    b = c(1).get(f"/api/v2/bundles/{E['enc']}", params={"verificar_hapi": "true"}).json()
    assert b["hapi"]["estado"] == "ok" and b["hapi"]["type"] == "document"
    # Composition + Patient + Encounter + 2 diagnósticos + 1 medicamento + 1 procedimiento + 1 observación
    assert b["hapi"]["total_entradas"] == b["total_entradas"] == 8


def test_cu12_el_rda_se_consulta_desde_la_replica_de_corozal():
    def bundle():
        r = c(3).get(f"/api/v2/bundles/{E['enc']}", params={"completo": "true"})
        return r.json() if r.status_code == 200 else None
    b = esperar(bundle)
    assert b, "el RDA no llegó replicado a Corozal"
    assert b["es_replica"] is True and b["sede_origen"] == 1
    assert b["bundle"]["type"] == "document"
    assert b["bundle"]["entry"][0]["resource"]["resourceType"] == "Composition"


# ------------------------------------------------------------- CU-14 / CU-15
def test_cu14_cobertura_se_ve_desde_cualquier_sede():
    def migrado():
        sedes = c(3).get("/api/v2/cobertura").json()["sedes"]
        s1 = next(s for s in sedes if s["id_sede"] == 1)
        return s1 if s1["pacientes_migrados"] >= 1 and s1["encuentros_migrados"] >= 1 else None
    s1 = esperar(migrado)
    assert s1, "Corozal no ve la migración de Sincelejo"
    assert 0 < s1["porcentaje_pacientes"] <= 100


def test_cu15_auditoria_de_57_campos():
    # Se audita solo el lote de esta corrida (su documento): así el resultado no depende de otros datos de la sede.
    d = c(3).get("/api/v2/auditoria/57-campos", params={"id_sede": 1, "lote": DOC}).json()["sedes"][0]
    campos = {x["campo"]: x for x in d["campos"]}
    assert len(campos) == 57 and sum(d["resumen"].values()) == 57
    for n in (2, 3, 4, 6, 8, 9, 22, 23, 28, 29, 30, 31, 33, 40, 43, 46, 48, 54, 55, 56):
        assert campos[n]["estado"] != "pendiente", f"campo {n} debería tener datos"
    for n in (47, 49):                         # nunca registramos complicación ni muerte
        assert campos[n]["estado"] == "pendiente"


# ------------------------------------------------------------------- gateway
def test_gateway_lee_de_cualquier_sede_y_escribe_en_la_indicada():
    r = httpx.get(f"{GATEWAY}/api/v2/pacientes/buscar",
                  params={"cod_tipo_documento": "CC", "numero_documento": DOC}, timeout=30, headers=auth(), verify=sesion.verificar())
    assert r.status_code == 200 and r.json()["total"] == 2
    for sede in (1, 2, 3):
        r = httpx.post(f"{GATEWAY}/sede/{sede}/api/v2/profesionales", timeout=30, headers=auth(), verify=sesion.verificar(), json={
            "cod_tipo_documento": "CC", "numero_documento": f"G{sede}{DOC}", "nombres": "Via", "apellidos": "Gateway"})
        assert r.status_code == 200 and r.json()["profesional"]["id_sede_origen"] == sede


# --------------------------------------------------------- vistas y catálogos
VISTAS = ("index", "admision", "medico", "paciente", "reportes")


def test_las_cuatro_vistas_se_sirven_desde_cada_sede():
    for sede in (1, 2, 3):
        for v in VISTAS:
            r = c(sede).get(f"/vistas/{v}.html")
            assert r.status_code == 200 and "<title>" in r.text, f"{v} en sede {sede}"
        for recurso in ("estilo.css", "comun.js"):
            assert c(sede).get(f"/vistas/{recurso}").status_code == 200
        raiz = c(sede).get("/", follow_redirects=False)
        assert raiz.status_code in (302, 307) and raiz.headers["location"].endswith("vistas/index.html")


def test_las_vistas_no_dependen_de_recursos_externos():
    """Si la sede está aislada, las vistas deben seguir cargando: nada de CDN ni fuentes remotas."""
    for v in VISTAS:
        html = c(1).get(f"/vistas/{v}.html").text
        assert "http://" not in html and "https://" not in html, f"{v} referencia un recurso externo"
    for recurso in ("estilo.css", "comun.js"):
        texto = c(1).get(f"/vistas/{recurso}").text
        assert "https://" not in texto and "//cdn" not in texto


def test_vistas_detras_del_gateway_usan_rutas_relativas():
    for sede in (1, 2, 3):
        r = httpx.get(f"{GATEWAY}/sede/{sede}/vistas/medico.html", timeout=30, verify=sesion.verificar())
        assert r.status_code == 200
        assert "../api/v2" in httpx.get(f"{GATEWAY}/sede/{sede}/vistas/comun.js", timeout=30, verify=sesion.verificar()).text


def test_catalogos_alimentan_los_formularios():
    lista = c(1).get("/api/v2/catalogos").json()["catalogos"]
    assert len(lista) == 29
    for nombre in lista:
        r = c(2).get(f"/api/v2/catalogos/{nombre}")
        assert r.status_code == 200 and r.json()["items"], nombre
        item = r.json()["items"][0]
        assert "codigo" in item and "descripcion" in item
    tec = c(3).get("/api/v2/catalogos/tecnologia_salud").json()["items"]
    assert {t["tipo"] for t in tec} >= {"MEDICAMENTO", "PROCEDIMIENTO"}
    com = c(3).get("/api/v2/catalogos/comunidad_etnica").json()["items"]
    assert all("cod_etnia" in x for x in com)
    assert c(1).get("/api/v2/catalogos/paciente").status_code == 404      # solo la lista blanca


# ------------------------------------------- las 4 vistas verifican los CU
def test_flujo_de_las_cuatro_vistas_entre_sedes():
    """Lo que hace cada vista, por la API: admisión (CU-01..03) → médico (CU-04..13) → paciente → reportero."""
    doc = f"V4{int(time.time())}"
    nac = (date(1941, 1, 1) + timedelta(days=int(time.time() * 7) % 20000)).isoformat()
    # Admisionista, sede 2
    p = c(2).post("/api/v2/pacientes", json=paciente_json(numero_documento=doc, primer_nombre=f"Vista{doc}",
                                                         fecha_hora_nacimiento=nac + "T07:30:00"))
    assert p.status_code == 201
    pid = p.json()["paciente"]["id_paciente"]
    enc = c(2).post("/api/v2/encuentros", json={
        "id_paciente": pid, "fecha_hora_inicio": "2026-04-01T10:00:00", "cod_modalidad": "01", "cod_grupo_servicio": "05",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    assert enc.status_code == 201
    eid = enc.json()["encuentro"]["id_encuentro"]
    assert c(2).post(f"/api/v2/encuentros/{eid}/triage", json={"fecha_hora_triage": "2026-04-01T10:05:00", "cod_triage": 2}).status_code == 201
    # Médico, sede 2: diagnóstico y cierre
    prof = c(2).post("/api/v2/profesionales", json={"cod_tipo_documento": "CC", "numero_documento": f"M{doc}", "nombres": "Ana", "apellidos": "Medica"}).json()["profesional"]
    assert c(2).post(f"/api/v2/encuentros/{eid}/diagnosticos", json={"cod_cie10": "J18.9", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-04-01"}).status_code == 201
    assert c(2).post(f"/api/v2/encuentros/{eid}/egreso", json={"fecha_hora_fin": "2026-04-01T11:00:00", "cod_condicion_egreso": "01", "id_profesional_egreso": prof["id_profesional"]}).status_code == 201
    # Paciente, sede 3: ve su historia aunque la atendieron en la 2 (y verifica con su fecha de nacimiento)
    def historia_en_3():
        r = c(3).get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": doc})
        reg = r.json()["pacientes"] if r.status_code == 200 else []
        if not reg or reg[0]["fecha_hora_nacimiento"][:10] != nac:
            return None
        h = c(3).get(f"/api/v2/historia-federada/{doc}").json()
        return h if any(e["id_encuentro"] == eid and e["es_replica"] for e in h["encuentros"]) else None
    assert esperar(historia_en_3), "la sede 3 no muestra la historia atendida en la sede 2"
    # Reportero, sede 1: la auditoría de la sede 2 ya cuenta el nuevo encuentro y la cobertura lista las 3 sedes
    cob = c(1).get("/api/v2/cobertura").json()["sedes"]
    assert [s["id_sede"] for s in cob] == [1, 2, 3]
    assert esperar(lambda: next(s for s in c(1).get("/api/v2/cobertura").json()["sedes"] if s["id_sede"] == 2)["encuentros"] >= 1)


# ------------------------------------------- trazabilidad de los 57 campos
def test_trazabilidad_de_los_57_campos_en_la_sede_y_en_sus_replicas():
    """Un caso sintético llena los 57 campos: la auditoría da 57/57 en la sede dueña y en las réplicas."""
    from escenario_57_campos import ejecutar
    informe = ejecutar(URL[1], (URL[2], URL[3]), marca=f"T{int(time.time())}")
    for url, r in informe["resultados"].items():
        assert r is not None, f"{url} no respondió la auditoría"
        assert r["resumen"] == {"completo": 57, "parcial": 0, "pendiente": 0}, f"{url}: {r}"
    assert informe["completos_en_todas"]
