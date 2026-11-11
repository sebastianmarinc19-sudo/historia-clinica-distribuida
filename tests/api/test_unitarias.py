"""Pruebas unitarias (sin base de datos ni HAPI FHIR)."""
import re
import uuid
from datetime import datetime

from hc_api import auditoria, campos57, config, fhir, mpi


def _paciente(**kw):
    base = dict(
        id_paciente=uuid.uuid4(), id_sede_origen=1, cod_tipo_documento="CC",
        numero_documento="1001234567", primer_nombre="Ana", segundo_nombre=None,
        primer_apellido="Torres", segundo_apellido="Pacheco",
        fecha_hora_nacimiento=datetime(1992, 4, 12, 10, 0), cod_sexo="F",
        cod_pais_residencia="COL", cod_municipio_residencia="70001",
        cod_etnia="06", oposicion_donacion=False,
    )
    base.update(kw)
    return base


# ----------------------------------------------------------------- MPI
from datetime import timezone   # noqa: E402

UMBRAL = 0.9


def _decision(a, b, decision, minuto=0, sede=1):
    x, y = mpi.par_canonico(a["id_paciente"], b["id_paciente"])
    return dict(id_decision=uuid.uuid4(), id_sede_origen=sede, id_paciente_a=x, id_paciente_b=y, decision=decision,
                decidido_por="medico", motivo=None, fecha_decision=datetime(2026, 11, 1, 10, minuto, tzinfo=timezone.utc))


def _otra_persona(**kw):
    base = dict(numero_documento="222", primer_nombre="Pedro", primer_apellido="Gomez", segundo_apellido="Ruiz",
                fecha_hora_nacimiento=datetime(1980, 1, 1), cod_sexo="M")
    base.update(kw)
    return _paciente(**base)


def test_score_documento_exacto_es_1():
    a = _paciente(id_sede_origen=1)
    b = _paciente(id_sede_origen=2, primer_nombre="ANA MARIA")
    assert mpi.calcular_score(a, b) == 1.0


def test_score_demografico_sin_documento_y_bajo_si_cambian_nombre_y_fecha():
    a = _paciente(numero_documento="111")
    assert mpi.calcular_score(a, _paciente(id_sede_origen=2, numero_documento="222")) == 1.0   # solo datos: idéntico
    assert mpi.calcular_score(a, _otra_persona(id_sede_origen=2)) < 0.5


def test_mismo_documento_con_datos_coherentes_se_une_solo():
    a, b = _paciente(id_sede_origen=1), _paciente(id_sede_origen=2, primer_nombre="ANA MARIA")
    g, = mpi.calcular_grupos([a, b], [], UMBRAL)
    assert g.id_mpi == mpi.id_mpi_para("CC", "1001234567") and len(g.miembros) == 2 and g.score == 1.0


def test_mismo_documento_con_otro_apellido_y_misma_fecha_se_une_cambio_de_apellido_o_error_de_digitacion():
    a, b = _paciente(id_sede_origen=1), _paciente(id_sede_origen=2, primer_apellido="Ruiz", segundo_apellido="Lopez")
    assert len(mpi.calcular_grupos([a, b], [], UMBRAL)) == 1


def test_gemelos_con_documentos_distintos_NO_se_unen_pero_quedan_como_candidatos():
    a = _paciente(numero_documento="111", primer_nombre="Juan", segundo_nombre="Pablo", primer_apellido="Rios", segundo_apellido="Perez")
    b = _paciente(id_sede_origen=2, numero_documento="222", primer_nombre="Juan", segundo_nombre="Pedro", primer_apellido="Rios", segundo_apellido="Perez")
    assert mpi.calcular_grupos([a, b], [], UMBRAL) == []
    r, = mpi.revisiones(a, [a, b], [], UMBRAL)
    assert r["pendiente"] and r["motivo"] == "datos_similares" and r["score"] >= UMBRAL


def test_homonimos_identicos_con_documentos_distintos_tampoco_se_unen_solos():
    a, b = _paciente(numero_documento="111"), _paciente(id_sede_origen=2, numero_documento="222")   # mismo nombre, fecha y sexo
    assert mpi.calcular_grupos([a, b], [], UMBRAL) == []
    assert [r["pendiente"] for r in mpi.revisiones(a, [b], [], UMBRAL)] == [True]


def test_personas_distintas_sin_parecido_no_generan_ni_candidatos():
    a = _paciente(numero_documento="111")
    assert mpi.revisiones(a, [_otra_persona(id_sede_origen=2)], [], UMBRAL) == []


def test_mismo_documento_con_otra_fecha_y_otro_nombre_es_conflicto_y_no_se_une():
    a = _paciente()
    b = _otra_persona(id_sede_origen=2, numero_documento=a["numero_documento"])
    assert mpi.evaluar_par(a, b, UMBRAL)["clase"] == "conflicto"
    assert mpi.calcular_grupos([a, b], [], UMBRAL) == []
    r, = mpi.revisiones(a, [b], [], UMBRAL)
    assert r["pendiente"] and r["motivo"] == "documento_con_datos_contradictorios"


def test_una_decision_misma_persona_une_documentos_distintos():
    a, b = _paciente(numero_documento="111"), _paciente(id_sede_origen=2, numero_documento="222")
    g, = mpi.calcular_grupos([a, b], [_decision(a, b, mpi.MISMA_PERSONA)], UMBRAL)
    assert {m["id_sede_origen"] for m in g.miembros} == {1, 2}
    assert g.id_mpi == mpi.id_mpi_para("CC", "111")        # ancla: el menor documento
    assert not mpi.revisiones(a, [b], [_decision(a, b, mpi.MISMA_PERSONA)], UMBRAL)[0]["pendiente"]


def test_una_decision_personas_distintas_separa_incluso_un_mismo_documento():
    a, b = _paciente(id_sede_origen=1), _paciente(id_sede_origen=2)
    assert len(mpi.calcular_grupos([a, b], [], UMBRAL)) == 1
    assert mpi.calcular_grupos([a, b], [_decision(a, b, mpi.PERSONAS_DISTINTAS)], UMBRAL) == []


def test_la_decision_mas_reciente_gana_y_es_igual_en_cualquier_orden():
    a, b = _paciente(numero_documento="111"), _paciente(id_sede_origen=2, numero_documento="222")
    junta = _decision(a, b, mpi.MISMA_PERSONA, minuto=1)
    separa = _decision(a, b, mpi.PERSONAS_DISTINTAS, minuto=2)
    for orden in ([junta, separa], [separa, junta]):
        assert mpi.calcular_grupos([a, b], orden, UMBRAL) == []
    # empate de fecha entre dos sedes: gana la de mayor id de sede, igual en todas
    x, y = _decision(a, b, mpi.MISMA_PERSONA, sede=2), _decision(a, b, mpi.PERSONAS_DISTINTAS, sede=3)
    assert mpi.calcular_grupos([a, b], [x, y], UMBRAL) == mpi.calcular_grupos([a, b], [y, x], UMBRAL) == []


def test_no_hay_cadenas_por_similitud():
    a = _paciente(numero_documento="111")
    b = _paciente(id_sede_origen=2, numero_documento="222")          # similar a a
    c = _paciente(id_sede_origen=3, numero_documento="333")          # similar a b
    assert mpi.calcular_grupos([a, b, c], [], UMBRAL) == []


def test_documento_mas_decision_forma_un_grupo_de_tres_y_el_id_es_determinista():
    a = _paciente(id_sede_origen=1, numero_documento="111")
    b = _paciente(id_sede_origen=2, numero_documento="111")
    c = _paciente(id_sede_origen=3, numero_documento="222")
    d = _decision(b, c, mpi.MISMA_PERSONA)
    esperados = None
    for orden in ([a, b, c], [c, b, a], [b, c, a]):
        g, = mpi.calcular_grupos(orden, [d], UMBRAL)
        assert len(g.miembros) == 3
        esperados = esperados or (g.id_mpi, [m["id_paciente"] for m in g.miembros])
        assert (g.id_mpi, [m["id_paciente"] for m in g.miembros]) == esperados
    assert esperados[0] == mpi.id_mpi_para("CC", "111")


def test_el_puntaje_del_grupo_es_el_del_vinculo_mas_debil():
    a = _paciente(id_sede_origen=1, numero_documento="111")
    b = _paciente(id_sede_origen=2, numero_documento="111")
    c = _otra_persona(id_sede_origen=3)
    g, = mpi.calcular_grupos([a, b, c], [_decision(b, c, mpi.MISMA_PERSONA)], UMBRAL)
    assert g.score == mpi.score_demografico(b, c) < 0.5 and {v["origen"] for v in g.vinculos} == {"documento", "manual"}


# ---------------------------------------------------------------- FHIR
def _datos_rda():
    pac = _paciente()
    enc = dict(id_encuentro=uuid.uuid4(), id_paciente=pac["id_paciente"], id_sede=1,
               fecha_hora_inicio=datetime(2026, 3, 15, 8, 30),
               fecha_hora_fin=datetime(2026, 3, 15, 9, 30),
               cod_via_ingreso="01", cod_causa_atencion="01")
    tec_med = dict(id_tecnologia_encuentro=uuid.uuid4(), cod_tecnologia="19938",
                   fecha_prescripcion=datetime(2026, 3, 15, 8, 45),
                   tecnologia_descripcion="Acetaminofén 500 mg",
                   medicamento=dict(cod_medicamento="19938", dosis_prescrita=500,
                                    cod_unidad_dosis="mg", cod_via_administracion="01",
                                    duracion_tratamiento=5, cod_unidad_duracion="d",
                                    frecuencia_valor=8, cod_unidad_frecuencia="h",
                                    medicamento_descripcion="Acetaminofén"))
    tec_proc = dict(id_tecnologia_encuentro=uuid.uuid4(), cod_tecnologia="890201",
                    fecha_prescripcion=datetime(2026, 3, 15, 8, 40),
                    tecnologia_descripcion="Consulta", medicamento=None)
    diag = dict(id_diagnostico=uuid.uuid4(), cod_cie10="J00", cod_tipo_diagnostico="IN",
                fecha_diagnostico=datetime(2026, 3, 15).date(), cie10_descripcion="Rinofaringitis")
    obs = dict(id_observacion=uuid.uuid4(), cod_loinc="8310-5", valor_numerico=38.5,
               valor_texto=None, cod_unidad="C", fecha_hora_medicion=datetime(2026, 3, 15, 9, 10),
               loinc_descripcion="Temperatura corporal")
    return dict(sede={"nombre_ciudad": "Sincelejo"}, paciente=pac, encuentro=enc,
                prestador="700010000001", diagnosticos=[diag],
                tecnologias=[tec_med, tec_proc], observaciones=[obs])


def test_rda_es_bundle_document_con_composition_primero():
    b = fhir.construir_rda(_datos_rda())
    assert b["resourceType"] == "Bundle" and b["type"] == "document"
    tipos = [e["resource"]["resourceType"] for e in b["entry"]]
    assert tipos[0] == "Composition"
    assert sorted(tipos[1:]) == sorted(
        ["Patient", "Encounter", "Condition", "MedicationRequest", "Procedure", "Observation"])


def test_rda_referencias_apuntan_a_entradas_del_bundle():
    b = fhir.construir_rda(_datos_rda())
    urls = {e["fullUrl"] for e in b["entry"]}
    texto = str(b)
    refs = set(re.findall(r"urn:uuid:[0-9a-f-]{36}", texto))
    assert refs <= urls


def test_observacion_usa_ucum_para_celsius():
    b = fhir.construir_rda(_datos_rda())
    obs = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation")
    assert obs["valueQuantity"]["code"] == "Cel" and obs["valueQuantity"]["value"] == 38.5


def test_las_fechas_con_hora_del_rda_llevan_zona_horaria():
    """`$validate` de HAPI exige zona horaria cuando la fecha tiene hora (las columnas TIMESTAMP no la guardan)."""
    b = fhir.construir_rda(_datos_rda())
    enc = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Encounter")
    obs = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation")
    assert enc["period"]["start"].endswith("-05:00") and obs["effectiveDateTime"].endswith("-05:00")
    assert fhir._iso(datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)).endswith("+00:00")        # una fecha que ya trae zona no se cambia


def _por_tipo(b):
    salida = {}
    for e in b["entry"]:
        salida.setdefault(e["resource"]["resourceType"], []).append(e["resource"])
    return salida


def test_la_transaccion_usa_put_con_ids_deterministas_y_recursos_propios():
    datos = _datos_rda()
    b = fhir.construir_transaccion(datos)
    assert b["type"] == "transaction"
    tipos = sorted(e["resource"]["resourceType"] for e in b["entry"])
    assert tipos == sorted(["Patient", "Encounter", "Condition", "MedicationRequest", "Procedure", "Observation"])    # sin Composition
    r = _por_tipo(b)
    assert r["Patient"][0]["id"] == "pac-" + datos["paciente"]["numero_documento"]                                    # el mismo id que usa el bus
    assert r["Encounter"][0]["id"] == f"enc-1-{datos['encuentro']['id_encuentro']}"
    assert r["Condition"][0]["id"] == f"cond-{datos['diagnosticos'][0]['id_diagnostico']}"
    assert r["Observation"][0]["id"] == f"obs-{datos['observaciones'][0]['id_observacion']}"
    for e in b["entry"]:
        ref = f"{e['resource']['resourceType']}/{e['resource']['id']}"
        assert e["request"] == {"method": "PUT", "url": ref} and e["fullUrl"] == ref
        assert len(e["resource"]["id"]) <= 64


def test_la_transaccion_solo_tiene_referencias_relativas_a_recursos_del_mismo_bundle():
    b = fhir.construir_transaccion(_datos_rda())
    assert "urn:uuid" not in str(b)
    internas = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in b["entry"]}
    refs = set(re.findall(r"(?:Patient|Encounter)/[A-Za-z0-9.-]+", str(b))) - internas
    assert not refs, f"referencias a recursos que no están en el Bundle: {refs}"
    cond = _por_tipo(b)["Condition"][0]
    assert cond["subject"]["reference"].startswith("Patient/pac-") and cond["encounter"]["reference"].startswith("Encounter/enc-1-")


def test_migrar_dos_veces_produce_exactamente_los_mismos_ids():
    datos = _datos_rda()
    ids = lambda b: [(e["resource"]["resourceType"], e["resource"]["id"]) for e in b["entry"]]       # noqa: E731
    assert ids(fhir.construir_transaccion(datos)) == ids(fhir.construir_transaccion(datos))
    assert fhir.id_rda(datos["encuentro"]["id_encuentro"]) == fhir.id_rda(datos["encuentro"]["id_encuentro"]) and fhir.id_rda("x").startswith("rda-")
    assert fhir.id_fhir("a b/c" + "x" * 80).startswith("a-b-c") and len(fhir.id_fhir("x" * 100)) == 64


def test_patient_incluye_hora_de_nacimiento_y_genero():
    p = fhir.patient_resource(_paciente())
    assert p["gender"] == "female" and p["birthDate"] == "1992-04-12"
    assert p["_birthDate"]["extension"][0]["valueDateTime"].startswith("1992-04-12T10:00")


# ------------------------------------------------------------ 57 campos
def test_57_campos_numerados_sin_huecos():
    assert [c.n for c in campos57.CAMPOS] == list(range(1, 58))


def test_cada_campo_hijo_tiene_origen_y_las_consultas_se_arman():
    for c in campos57.CAMPOS:
        sql = campos57.sql_cobertura(c)
        assert sql.count("%s") == len(campos57.parametros_cobertura(c, 1))


def test_las_consultas_con_lote_llevan_el_patron_de_prefijo():
    for c in campos57.CAMPOS:
        sql = campos57.sql_cobertura(c, con_lote=True)
        params = campos57.parametros_cobertura(c, 1, "DEMO57")
        assert sql.count("%s") == len(params), c.n
        assert "LIKE %s" in sql
    assert campos57.patron_lote("A_B%") == "A\\_B\\%%"      # comodines escapados + prefijo


def test_estado_de_cobertura():
    assert campos57.estado(0, 0) == "pendiente"
    assert campos57.estado(0, 5) == "pendiente"
    assert campos57.estado(3, 5) == "parcial"
    assert campos57.estado(5, 5) == "completo"


# ------------------------------------------------------------ autenticación
def test_la_clave_se_guarda_con_hash_y_se_verifica():
    from hc_api import auth
    h = auth.hash_clave("clave-correcta", iteraciones=1000)
    assert "clave-correcta" not in h and h.startswith("pbkdf2_sha256$1000$")
    assert auth.verificar_clave("clave-correcta", h)
    assert not auth.verificar_clave("otra", h)
    assert not auth.verificar_clave("clave-correcta", "formato-roto")
    assert auth.hash_clave("x", iteraciones=1000) != auth.hash_clave("x", iteraciones=1000)   # sal distinta


def test_token_firmado_se_acepta_y_se_rechaza_si_se_altera_o_vence():
    import pytest
    from hc_api import auth
    t = auth.emitir_token("ana", "medico", "secreto", 60, ahora=1000, nombre="Ana")
    d = auth.leer_token(t, "secreto", ahora=1030)
    assert d["sub"] == "ana" and d["rol"] == "medico" and d["nombre"] == "Ana"
    with pytest.raises(auth.TokenInvalido):                           # vencido
        auth.leer_token(t, "secreto", ahora=1061)
    with pytest.raises(auth.TokenInvalido):                           # otro secreto
        auth.leer_token(t, "distinto", ahora=1030)
    cab, carga, firma = t.split(".")
    admin = auth._b64(auth._unb64(carga).replace(b"medico", b"administrador"))
    with pytest.raises(auth.TokenInvalido):                           # carga alterada con la firma vieja
        auth.leer_token(f"{cab}.{admin}.{firma}", "secreto", ahora=1030)
    sin_alg = auth._b64(b'{"alg":"none","typ":"JWT"}')
    with pytest.raises(auth.TokenInvalido):                           # «alg: none»
        auth.leer_token(f"{sin_alg}.{carga}.", "secreto", ahora=1030)
    with pytest.raises(auth.TokenInvalido):
        auth.leer_token("no-es-un-token", "secreto")


def test_token_es_un_jwt_hs256_estandar():
    import base64, hashlib, hmac, json
    from hc_api import auth
    t = auth.emitir_token("u", "reportero", "s3", 10, ahora=5)
    cab, carga, firma = t.split(".")
    assert json.loads(auth._unb64(cab)) == {"alg": "HS256", "typ": "JWT"}
    esperado = base64.urlsafe_b64encode(hmac.new(b"s3", f"{cab}.{carga}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert firma == esperado


def test_limite_de_intentos_fallidos():
    from hc_api import auth
    auth._fallos.clear()
    for i in range(auth.MAX_FALLOS):
        assert not auth.demasiados_fallos("ip:doc", ahora=100 + i)
        auth.registrar_fallo("ip:doc", ahora=100 + i)
    assert auth.demasiados_fallos("ip:doc", ahora=110)
    assert not auth.demasiados_fallos("ip:doc", ahora=100 + auth.VENTANA_S + 60)      # la ventana expira
    assert not auth.demasiados_fallos("otra-ip:doc", ahora=110)


def test_el_paciente_solo_es_dueno_de_su_documento():
    from hc_api.auth import Usuario
    u = Usuario("CC:1", "paciente", cod_tipo_documento="CC", numero_documento="1")
    assert u.es_su_documento("CC", "1") and u.es_su_documento(None, "1")
    assert not u.es_su_documento("CC", "2") and not u.es_su_documento("TI", "1")
    assert not Usuario("m", "medico").es_su_documento("CC", "1")


def test_reiniciar_el_pool_no_se_bloquea_con_una_conexion_colgada():
    """Regresión: closeall() sobre una conexión en plena consulta bloqueaba el candado del pool y paralizaba la sede."""
    import threading
    import time

    from hc_api import db

    liberar = threading.Event()

    class PoolColgado:
        def closeall(self):
            liberar.wait(10)          # simula conn.close() esperando una consulta que no termina

    colgado = PoolColgado()
    db._pool = colgado
    t0 = time.time()
    db._reiniciar_pool(colgado)
    try:
        assert time.time() - t0 < 1, "reiniciar el pool esperó al cierre de la conexión colgada"
        assert db._pool is None
        nuevo = object()
        db._pool = nuevo
        db._reiniciar_pool(colgado)    # otro hilo ya lo cambió: no debe tirar el pool nuevo
        assert db._pool is nuevo
    finally:
        liberar.set()
        db._pool = None


# ----------------------------------------------------------------- auditoría encadenada por hash
def _cadena(n=6, sede=1):
    eventos, previo = [], auditoria.hash_genesis(sede)
    for i in range(1, n + 1):
        e = dict(seq=i, instante=datetime(2026, 11, 8, 10, 0, i, 123456, tzinfo=timezone.utc), id_sede=sede,
                 usuario="medico" if i % 2 else "admision", rol="medico", metodo="POST", ruta="/api/v2/pacientes",
                 documento=f"100{i}", estado=201, ip="10.0.0.1", hash_previo=previo)
        e["hash"] = auditoria.calcular_hash(previo, e)
        eventos.append(e)
        previo = e["hash"]
    return eventos


def test_una_cadena_integra_se_verifica():
    r = auditoria.verificar_cadena(_cadena(), 1)
    assert r["ok"] and r["verificados"] == 6 and r["ultimo"][0] == 6


def test_el_hash_depende_del_hash_previo_y_del_contenido():
    c = _cadena(3)
    assert len({e["hash"] for e in c}) == 3
    assert auditoria.hash_genesis(1) != auditoria.hash_genesis(2)
    otro = dict(c[1], estado=500)
    assert auditoria.calcular_hash(c[1]["hash_previo"], otro) != c[1]["hash"]


def test_alterar_un_evento_rompe_la_cadena_en_ese_evento():
    c = _cadena()
    c[3]["documento"] = "9999"
    r = auditoria.verificar_cadena(c, 1)
    assert not r["ok"] and r["primer_fallo"]["seq"] == 4 and "alterado" in r["primer_fallo"]["motivo"]


def test_alterar_el_resultado_de_un_acceso_rechazado_se_detecta():
    c = _cadena()
    c[2]["estado"] = 200
    assert auditoria.verificar_cadena(c, 1)["primer_fallo"]["seq"] == 3


def test_borrar_un_evento_se_detecta_por_el_salto_de_secuencia():
    c = _cadena()
    del c[2]
    r = auditoria.verificar_cadena(c, 1)
    assert not r["ok"] and r["primer_fallo"]["seq"] == 4 and "salto" in r["primer_fallo"]["motivo"]


def test_borrar_el_ultimo_evento_no_rompe_la_cadena_pero_cambia_la_cabeza():
    c = _cadena()
    completa = auditoria.verificar_cadena(c, 1)
    parcial = auditoria.verificar_cadena(c[:-1], 1)
    assert parcial["ok"] and parcial["ultimo"] != completa["ultimo"]      # por eso la cabeza se publica como sello y debe anclarse


def test_reordenar_o_insertar_eventos_se_detecta():
    c = _cadena()
    c[1], c[2] = c[2], c[1]
    assert not auditoria.verificar_cadena(c, 1)["ok"]
    c = _cadena()
    c.insert(3, dict(c[2]))
    assert not auditoria.verificar_cadena(c, 1)["ok"]


def test_recalcular_el_hash_de_un_evento_alterado_rompe_el_siguiente():
    c = _cadena()
    c[2]["usuario"] = "otro"
    c[2]["hash"] = auditoria.calcular_hash(c[2]["hash_previo"], c[2])      # quien alteró también recalcula ese hash
    r = auditoria.verificar_cadena(c, 1)
    assert not r["ok"] and r["primer_fallo"]["seq"] == 4


def test_una_cadena_de_otra_sede_no_cuadra():
    assert not auditoria.verificar_cadena(_cadena(sede=2), 1)["ok"]


def test_la_verificacion_por_tramos_equivale_a_la_completa():
    c = _cadena(8)
    primero = auditoria.verificar_cadena(c[:5], 1)
    segundo = auditoria.verificar_cadena(c[5:], 1, primero["ultimo"])
    assert primero["ok"] and segundo["ok"] and segundo["ultimo"][0] == 8


# ----------------------------------------------------------------- secretos por archivo
def test_el_secreto_se_lee_de_un_archivo_y_este_gana_a_la_variable(tmp_path, monkeypatch):
    f = tmp_path / "jwt"
    f.write_text("desde-archivo\n")
    monkeypatch.setenv("PRUEBA_SECRETO", "desde-variable")
    assert config.secreto("PRUEBA_SECRETO") == "desde-variable"
    monkeypatch.setenv("PRUEBA_SECRETO_FILE", str(f))
    assert config.secreto("PRUEBA_SECRETO") == "desde-archivo"        # sin el salto de línea final
    assert config.secreto("PRUEBA_OTRO", "defecto") == "defecto"


# ------------------------------------------------------------------ anclaje y AuditEvent (sin base de datos)
def test_evaluar_anclas_acepta_lo_coherente_y_detecta_reescritura_y_truncamiento():
    from hc_api import anclaje
    locales = {1: "a" * 64, 2: "b" * 64, 3: "c" * 64}
    ok = [{"seq": 3, "hash": "c" * 64}, {"seq": 2, "hash": "b" * 64}]
    assert anclaje.evaluar_anclas(ok, locales, 3, "Cartagena") is None
    assert anclaje.evaluar_anclas([{"seq": 2, "hash": "b" * 64}], locales, 3, "Cartagena") is None       # un ancla anterior a la cabeza
    assert "reescrito" in anclaje.evaluar_anclas([{"seq": 3, "hash": "d" * 64}], locales, 3, "Cartagena")
    assert "truncada" in anclaje.evaluar_anclas([{"seq": 5, "hash": "c" * 64}], locales, 3, "Cartagena")
    assert "ningún evento" in anclaje.evaluar_anclas([{"seq": 1, "hash": "a" * 64}], {}, 0, "Cartagena")


def test_auditevent_mapea_metodo_estado_agente_paciente_y_cadena():
    from hc_api import auditevent
    e = {"seq": 7, "instante": "2026-11-09T19:00:00.123456+00:00", "usuario": "medico", "rol": "medico", "metodo": "GET",
         "ruta": "/api/v2/historia-federada/{documento}", "documento": "7000001", "estado": 403, "ip": "10.0.0.5",
         "hash_previo": "1" * 64, "hash": "2" * 64}
    a = auditevent.a_auditevent(e, 1, "Sincelejo")
    assert a["resourceType"] == "AuditEvent" and a["id"] == "audit-1-7" and a["action"] == "R" and a["outcome"] == "4"
    assert a["subtype"][0]["code"] == "read" and a["agent"][0]["who"]["display"] == "medico" and a["agent"][0]["network"]["address"] == "10.0.0.5"
    assert a["entity"][0]["what"]["reference"] == "Patient/pac-7000001"
    assert {d["type"]: d["valueString"] for d in a["entity"][1]["detail"]} == {"seq": "7", "hash": "2" * 64, "hash_previo": "1" * 64}
    for metodo, accion in (("POST", "C"), ("PUT", "U"), ("DELETE", "D")):
        assert auditevent.a_auditevent({**e, "metodo": metodo, "estado": 201}, 1)["action"] == accion
    assert auditevent.a_auditevent({**e, "estado": 500}, 1)["outcome"] == "8" and auditevent.a_auditevent({**e, "estado": 200}, 1)["outcome"] == "0"
    sin_doc = auditevent.a_auditevent({**e, "documento": None, "usuario": None, "rol": None, "ip": None}, 2)
    assert len(sin_doc["entity"]) == 1 and sin_doc["agent"][0]["who"]["display"] == "anónimo" and "role" not in sin_doc["agent"][0]
