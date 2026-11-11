"""MPI contra las 3 sedes: solo el documento une solo; los datos parecidos (gemelos, homónimos) y el documento repetido con
datos contradictorios piden una decisión humana que se replica y que la más reciente revierte.

Cada prueba usa documentos nuevos y una fecha de nacimiento propia de la corrida, así que se pueden repetir sin limpiar.
"""
import time
import uuid
from datetime import date, timedelta

from hc_api import mpi
from test_integracion import c, esperar, paciente_json

T = int(time.time())
NAC = (date(1941, 1, 1) + timedelta(days=(T + 777) % 20000)).isoformat() + "T09:00:00"
DOC_A, DOC_B, DOC_C = f"MA{T}", f"MB{T}", f"MC{T}"
E = {}


def _registrar(sede, doc, nombre, segundo, fecha=NAC, apellido="Rios", sexo="M"):
    r = c(sede).post("/api/v2/pacientes", json=paciente_json(
        numero_documento=doc, primer_nombre="Juan", segundo_nombre=segundo, primer_apellido=apellido,
        segundo_apellido="Perez", fecha_hora_nacimiento=fecha, cod_sexo=sexo))
    assert r.status_code == 201, r.text
    return r.json()["paciente"]["id_paciente"]


def _esperar_en(sede, *docs):
    for d in docs:
        assert esperar(lambda d=d: c(sede).get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": d}).json()["total"] >= 1), \
            f"{d} no llegó a la sede {sede}"


def _revision(sede, doc, otro=None):
    pares = c(sede).get("/api/v2/mpi/revision", params={"cod_tipo_documento": "CC", "numero_documento": doc}).json()["pares"]
    return [p for p in pares if otro is None or {p["a"]["numero_documento"], p["b"]["numero_documento"]} == {doc, otro}]


def _decidir(sede, a, b, decision, motivo="prueba", usuario="medico"):
    return c(sede, usuario).post("/api/v2/mpi/decisiones", json={"id_paciente_a": a, "id_paciente_b": b, "decision": decision, "motivo": motivo})


def _ancla(*docs):
    return mpi.id_mpi_para("CC", min(docs, key=mpi._normalizar))


# ---------------------------------------------------------------- gemelos
def test_gemelos_con_documentos_distintos_no_se_unen_solos_y_quedan_para_revisar():
    E["a"] = _registrar(1, DOC_A, "Juan", "Pablo")
    E["b"] = _registrar(2, DOC_B, "Juan", "Pedro")           # mismo día, sexo y apellidos; otro segundo nombre
    _esperar_en(3, DOC_A, DOC_B)
    r = c(3).post(f"/api/v2/mpi/resolver/{E['a']}").json()
    assert r["resuelto"] is False and r["candidatos_pendientes"] >= 1
    par, = _revision(3, DOC_A, DOC_B)
    assert par["pendiente"] and par["motivo"] == "datos_similares" and par["decision"] is None
    h = c(3).get(f"/api/v2/historia-federada/{DOC_A}", params={"cod_tipo_documento": "CC"}).json()
    assert h["federado"] is False and h["revision_pendiente"] >= 1
    assert len(h["sedes"]) == 1                              # no mezcla la historia del hermano


def test_confirmar_misma_persona_se_replica_y_las_tres_sedes_obtienen_el_mismo_id():
    r = _decidir(3, E["a"], E["b"], "MISMA_PERSONA")
    assert r.status_code == 201, r.text
    assert r.json()["decision"]["decidido_por"] == "medico" and r.json()["decision"]["id_sede_origen"] == 3
    ids = {}
    for sede in (1, 2, 3):
        assert esperar(lambda s=sede: c(s).get("/api/v2/mpi/revision", params={"cod_tipo_documento": "CC", "numero_documento": DOC_A}).json()["pares"]
                       and not _revision(s, DOC_A, DOC_B)[0]["pendiente"]), f"la decisión no llegó a la sede {sede}"
        res = c(sede).post(f"/api/v2/mpi/resolver/{E['a']}").json()
        assert res["resuelto"] is True and res["miembros_totales"] == 2, (sede, res)
        ids[sede] = res["id_mpi"]
    assert len(set(ids.values())) == 1 and ids[1] == str(_ancla(DOC_A, DOC_B))        # determinista, sin coordinarse
    h = c(2).get(f"/api/v2/historia-federada/{DOC_A}", params={"cod_tipo_documento": "CC"}).json()
    assert h["federado"] and {s["id_paciente"] for s in h["sedes"]} == {E["a"], E["b"]}


def test_recalcular_desde_cero_da_la_misma_identidad():
    r = c(3, "admin").post("/api/v2/mpi/recalcular")
    assert r.status_code == 200 and r.json()["identidades"] >= 1
    h = c(3).get(f"/api/v2/historia-federada/{DOC_B}", params={"cod_tipo_documento": "CC"}).json()
    assert h["federado"] and h["id_mpi"] == str(_ancla(DOC_A, DOC_B))


def test_la_decision_mas_reciente_revierte_y_el_grupo_se_deshace_en_todas_las_sedes():
    time.sleep(1.2)                                          # distinta marca de tiempo que la decisión anterior
    r = _decidir(1, E["a"], E["b"], "PERSONAS_DISTINTAS", motivo="eran gemelos")
    assert r.status_code == 201, r.text
    for sede in (1, 2, 3):
        def deshecho(s=sede):
            par = _revision(s, DOC_A, DOC_B)
            return par and par[0]["decision"] and par[0]["decision"]["decision"] == "PERSONAS_DISTINTAS"
        assert esperar(deshecho), f"la reversión no llegó a la sede {sede}"
        res = c(sede).post(f"/api/v2/mpi/resolver/{E['a']}").json()
        assert res["resuelto"] is False and res["candidatos_pendientes"] == 0, (sede, res)
        assert c(sede).get(f"/api/v2/historia-federada/{DOC_B}", params={"cod_tipo_documento": "CC"}).json()["federado"] is False
    par, = _revision(2, DOC_A, DOC_B)
    assert par["decision"]["motivo"] == "eran gemelos" and par["decision"]["sede"] == "Sincelejo" and par["pendiente"] is False


# ------------------------------------------------- documento repetido por error
def test_mismo_documento_con_datos_contradictorios_es_conflicto_y_no_se_une():
    pa = _registrar(1, DOC_C, "Juan", None)
    pb = c(2).post("/api/v2/pacientes", json=paciente_json(
        numero_documento=DOC_C, primer_nombre="Marta", primer_apellido="Suarez", segundo_apellido="Lopez",
        fecha_hora_nacimiento="1975-06-20T08:00:00", cod_sexo="F"))
    assert pb.status_code == 201, pb.text
    E["c1"], E["c2"] = pa, pb.json()["paciente"]["id_paciente"]
    _esperar_en(3, DOC_C)
    assert esperar(lambda: c(3).get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC_C}).json()["total"] == 2)
    res = c(3).post(f"/api/v2/mpi/resolver/{E['c1']}").json()
    assert res["resuelto"] is False and res["candidatos_pendientes"] >= 1
    par, = _revision(3, DOC_C, DOC_C)          # el par del mismo documento (C1 también puede parecerse a A y B)
    assert par["motivo"] == "documento_con_datos_contradictorios" and par["pendiente"]


def test_confirmar_que_son_distintas_resuelve_el_conflicto_sin_unirlas():
    r = _decidir(3, E["c1"], E["c2"], "PERSONAS_DISTINTAS", motivo="documento digitado dos veces")
    assert r.status_code == 201
    par, = _revision(3, DOC_C, DOC_C)          # el par del mismo documento (C1 también puede parecerse a A y B)
    assert par["pendiente"] is False
    res = c(3).post(f"/api/v2/mpi/resolver/{E['c1']}").json()
    assert res["resuelto"] is False                  # siguen separadas (C1 aún puede tener pendientes con otros registros parecidos)
    assert not any(p["pendiente"] and {p["a"]["id_paciente"], p["b"]["id_paciente"]} == {E["c1"], E["c2"]} for p in _revision(3, DOC_C))


# ------------------------------------------------------------------- permisos
def test_solo_el_medico_decide_y_consulta_la_revision():
    cuerpo = {"id_paciente_a": E["a"], "id_paciente_b": E["b"], "decision": "MISMA_PERSONA"}
    for usuario in ("admision", "reportero"):
        assert c(1, usuario).post("/api/v2/mpi/decisiones", json=cuerpo).status_code == 403, usuario
        assert c(1, usuario).get("/api/v2/mpi/revision", params={"cod_tipo_documento": "CC", "numero_documento": DOC_A}).status_code == 403
    assert c(1, "medico").post("/api/v2/mpi/recalcular").status_code == 403            # recalcular es de administración


def test_validaciones_de_la_decision():
    medico = c(1, "medico")
    assert medico.post("/api/v2/mpi/decisiones", json={"id_paciente_a": E["a"], "id_paciente_b": E["a"], "decision": "MISMA_PERSONA"}).status_code == 422
    assert medico.post("/api/v2/mpi/decisiones", json={"id_paciente_a": E["a"], "id_paciente_b": E["b"], "decision": "TAL_VEZ"}).status_code == 422
    assert medico.post("/api/v2/mpi/decisiones", json={"id_paciente_a": E["a"], "id_paciente_b": str(uuid.uuid4()), "decision": "MISMA_PERSONA"}).status_code == 404
    # el par (a, b) y el (b, a) son la misma decisión: se guarda en orden canónico
    r = medico.post("/api/v2/mpi/decisiones", json={"id_paciente_a": E["b"], "id_paciente_b": E["a"], "decision": "PERSONAS_DISTINTAS"})
    assert r.status_code == 201 and r.json()["decision"]["id_paciente_a"] < r.json()["decision"]["id_paciente_b"]


def test_el_paciente_no_ve_ni_decide_nada_del_mpi():
    from test_integracion import URL
    # token de paciente del registro A (documento y fecha de nacimiento del propio paciente)
    t = c(1).post("/api/v2/auth/paciente", json={"cod_tipo_documento": "CC", "numero_documento": DOC_A, "fecha_nacimiento": NAC[:10]})
    assert t.status_code == 200, t.text
    import httpx
    p = httpx.Client(base_url=URL[1], timeout=30, headers={"Authorization": "Bearer " + t.json()["token"]})
    assert p.get("/api/v2/mpi/revision", params={"cod_tipo_documento": "CC", "numero_documento": DOC_A}).status_code == 403
    assert p.post("/api/v2/mpi/decisiones", json={"id_paciente_a": E["a"], "id_paciente_b": E["b"], "decision": "MISMA_PERSONA"}).status_code == 403
    h = p.get(f"/api/v2/historia-federada/{DOC_A}", params={"cod_tipo_documento": "CC"}).json()
    assert h["revision_pendiente"] == 0
