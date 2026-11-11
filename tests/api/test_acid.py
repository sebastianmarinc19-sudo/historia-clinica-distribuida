"""Evidencia ACID sobre la API y la réplica: antes / error a la mitad / después.

A (atomicidad): una operación que escribe en dos tablas y falla en la segunda no deja nada de la primera.
   - prescribir una tecnología con medicamento: la fila de `tecnologia_encuentro` se inserta primero y el disparador rechaza el medicamento;
   - registrar el egreso: se inserta `egreso` y después el UPDATE de `encuentro.fecha_hora_fin` viola el CHECK (fin anterior al inicio).
C (consistencia): el rechazo lo hace la base (disparador y CHECK), no el código de la API.
I (aislamiento): ocho peticiones simultáneas por el diagnóstico de ingreso de un encuentro: se crea exactamente uno, el resto es idempotente (200) o conflicto (409).
Réplica: lo que se deshizo nunca llega a las otras sedes, y lo confirmado llega completo (egreso y cierre del encuentro juntos).
La durabilidad (matar la base y volver) y el aislamiento entre sesiones de SQL están en scripts/prueba_acid.sh.
"""
import concurrent.futures as cf
import time

from test_integracion import c, esperar, paciente_json

T = int(time.time())
DOC = f"AC{T}"
E = {}
MEDICAMENTO = {"cod_medicamento": "19938", "dosis_prescrita": 1, "cod_unidad_dosis": "mg", "cod_via_administracion": "01",
               "duracion_tratamiento": 1, "cod_unidad_duracion": "d", "frecuencia_valor": 8, "cod_unidad_frecuencia": "h"}


def _detalle(sede=1):
    r = c(sede, "medico").get(f"/api/v2/encuentros/{E['enc']}")
    return r.json() if r.status_code == 200 else None


def test_preparacion_paciente_encuentro_y_profesional():
    assert c(1, "admision").post("/api/v2/pacientes", json=paciente_json(numero_documento=DOC)).status_code == 201
    pid = c(1, "admision").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).json()["pacientes"][0]["id_paciente"]
    r = c(1, "admision").post("/api/v2/encuentros", json={
        "id_paciente": pid, "fecha_hora_inicio": "2026-11-07T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    assert r.status_code == 201, r.text
    E["enc"] = r.json()["encuentro"]["id_encuentro"]
    p = c(1, "admin").post("/api/v2/profesionales", json={"cod_tipo_documento": "CC", "numero_documento": f"P{DOC}", "nombres": "Acid", "apellidos": "Prueba"})
    assert p.status_code == 200, p.text
    E["prof"] = p.json()["profesional"]["id_profesional"]


# ------------------------------------------------------------------------------------------------ atomicidad
def test_atomicidad_prescripcion_con_error_a_la_mitad_no_deja_la_tecnologia_huerfana():
    antes = _detalle()
    assert antes["tecnologias"] == []                                                       # ANTES
    r = c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/tecnologias", json={
        "cod_tecnologia": "890201", "cod_finalidad": "01", "fecha_prescripcion": "2026-11-07T08:40:00", "medicamento": MEDICAMENTO})
    assert r.status_code == 422 and r.json()["error"] == "dato_invalido", r.text            # A LA MITAD: la 2.ª inserción falla (disparador)
    despues = _detalle()
    assert despues["tecnologias"] == [], "quedó la fila de tecnologia_encuentro de la transacción fallida"   # DESPUÉS: nada
    ok = c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/tecnologias", json={
        "cod_tecnologia": "19938", "cod_finalidad": "02", "fecha_prescripcion": "2026-11-07T08:40:00", "medicamento": MEDICAMENTO})
    assert ok.status_code == 201 and ok.json()["medicamento"] is not None                  # con datos correctos se confirman las dos filas juntas
    tecs = _detalle()["tecnologias"]
    assert len(tecs) == 1 and tecs[0]["medicamento"] is not None


def test_atomicidad_egreso_con_cierre_invalido_no_deja_el_egreso_ni_cierra_el_encuentro():
    antes = _detalle()
    assert antes["egreso"] is None and antes["fecha_hora_fin"] is None                      # ANTES: encuentro abierto
    malo = {"fecha_hora_fin": "2026-11-07T07:00:00", "cod_condicion_egreso": "01", "id_profesional_egreso": E["prof"], "dias_incapacidad": 0}
    r = c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/egreso", json=malo)
    assert r.status_code == 422, r.text                                                     # A LA MITAD: INSERT egreso hecho, UPDATE del encuentro viola el CHECK
    despues = _detalle()
    assert despues["egreso"] is None, "quedó el egreso de la transacción fallida"           # DESPUÉS: ni egreso ni cierre
    assert despues["fecha_hora_fin"] is None
    ok = c(1, "medico").post(f"/api/v2/encuentros/{E['enc']}/egreso", json={**malo, "fecha_hora_fin": "2026-11-07T09:30:00"})
    assert ok.status_code == 201, ok.text
    final = _detalle()
    assert final["egreso"] is not None and final["fecha_hora_fin"].startswith("2026-11-07T09:30")   # confirmadas las dos escrituras


# ------------------------------------------------------------------------------------------------ réplica
def test_lo_deshecho_no_llega_a_las_replicas_y_lo_confirmado_llega_completo():
    for sede in (2, 3):
        assert esperar(lambda: _detalle(sede) is not None and _detalle(sede)["egreso"] is not None, timeout=20), f"la sede {sede} no recibió el egreso"
        d = _detalle(sede)
        assert d["fecha_hora_fin"].startswith("2026-11-07T09:30")                          # el cierre llegó junto con el egreso
        assert len(d["tecnologias"]) == 1, "la tecnología de la transacción fallida llegó a la réplica"
        assert d["es_replica"] is True


def test_la_replica_nunca_muestra_el_egreso_sin_el_cierre_del_encuentro():
    """Segundo encuentro: se sondea la réplica sin parar mientras se confirma el egreso; las dos escrituras son una sola transacción."""
    pid = c(1, "admision").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).json()["pacientes"][0]["id_paciente"]
    enc = c(1, "admision").post("/api/v2/encuentros", json={
        "id_paciente": pid, "fecha_hora_inicio": "2026-11-08T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"}).json()["encuentro"]["id_encuentro"]
    assert esperar(lambda: c(2, "medico").get(f"/api/v2/encuentros/{enc}").status_code == 200, timeout=20)
    muestras, parar = [], False

    def sondear():
        while not parar:
            r = c(2, "medico").get(f"/api/v2/encuentros/{enc}")
            if r.status_code == 200:
                d = r.json()
                muestras.append((d["egreso"] is not None, d["fecha_hora_fin"] is not None))
            time.sleep(0.02)

    with cf.ThreadPoolExecutor(1) as ex:
        f = ex.submit(sondear)
        time.sleep(0.3)
        r = c(1, "medico").post(f"/api/v2/encuentros/{enc}/egreso", json={
            "fecha_hora_fin": "2026-11-08T09:30:00", "cod_condicion_egreso": "01", "id_profesional_egreso": E["prof"], "dias_incapacidad": 0})
        assert r.status_code == 201, r.text
        esperar(lambda: muestras and muestras[-1] == (True, True), timeout=20)
        time.sleep(0.3)
        parar = True
        f.result()
    assert (True, True) in muestras and (False, False) in muestras
    assert all(egreso == cierre for egreso, cierre in muestras), f"la réplica mostró una escritura a medias: {set(muestras)}"


# ------------------------------------------------------------------------------------------------ aislamiento
def test_aislamiento_ocho_peticiones_simultaneas_por_el_diagnostico_de_ingreso_dejan_uno_solo():
    pid = c(1, "admision").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).json()["pacientes"][0]["id_paciente"]
    enc = c(1, "admision").post("/api/v2/encuentros", json={
        "id_paciente": pid, "fecha_hora_inicio": "2026-11-09T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01",
        "cod_entorno": "01", "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"}).json()["encuentro"]["id_encuentro"]
    def pedir(i):
        return c(1, "medico").post(f"/api/v2/encuentros/{enc}/diagnosticos",
                                   json={"cod_cie10": ["I10", "J00", "J45.9", "N39.0"][i % 4], "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-09"}).status_code
    with cf.ThreadPoolExecutor(8) as ex:
        estados = sorted(ex.map(pedir, range(8)))
    # exactamente una creación; el mismo código repetido es idempotente (200) y otro código en conflicto con el índice único da 409; nunca un 5xx
    assert estados.count(201) == 1 and set(estados) <= {200, 201, 409}, estados
    d = c(1, "medico").get(f"/api/v2/encuentros/{enc}").json()
    assert len([x for x in d["diagnosticos"] if x["cod_tipo_diagnostico"] == "IN"]) == 1
