"""El bus de extremo a extremo con PostgreSQL real: idempotencia, rechazo con motivo, reintentos con retroceso, mensajes muertos,
recuperación tras una caída del bus y entrega en dos pasos (HAPI y luego el nodo) sin duplicar."""
import os
import pathlib
import threading
import time

from hc_hsb import bus, db

EJEMPLOS = pathlib.Path(os.getenv("HSB_EJEMPLOS", pathlib.Path(__file__).resolve().parents[2] / "ejemplos"))


def ejemplo(nombre: str) -> str:
    return (EJEMPLOS / nombre).read_bytes().decode("utf-8")


def eventos(id_mensaje):
    return [(e["estado"], e["intento"]) for e in db.consultar("SELECT estado, intento FROM evento_mensaje WHERE id_mensaje = %s ORDER BY id_evento", (id_mensaje,))]


def esperar_pendientes(max_s=3.0):
    limite = time.time() + max_s
    while time.time() < limite:
        bus.procesar_pendientes()
        if not db.consultar("SELECT 1 FROM mensaje_bus WHERE estado IN ('reintentando','transformado')"):
            return
        time.sleep(0.03)


# ------------------------------------------------------------------------------------------ contrato de los ejemplos
def test_adt_valido_de_la_sede_2_se_entrega_a_hapi_y_al_nodo(destinos_falsos):
    hapi, sedes = destinos_falsos
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert r["estado"] == "entregado" and r["sede"] == 2 and r["documento"] == "1007"
    assert set(hapi.recursos) >= {"Patient/pac-1007", "Encounter/enc-2-V-S2-0101"} and any(k.startswith("Condition/") for k in hapi.recursos)
    (clave, paciente), = sedes.pacientes.items()
    assert clave[0] == 2 and paciente["numero_documento"] == "1007" and paciente["cod_sexo"] == "F"
    assert len(sedes.encuentros) == 1 and list(sedes.diagnosticos.values())[0][0]["cod_cie10"] == "J45.9"
    assert [e for e, _ in eventos(r["id_mensaje"])] == ["recibido", "validado", "transformado", "hapi_ok", "nodo_ok", "entregado"]


def test_oru_de_la_sede_1_entrega_la_observacion_loinc(destinos_falsos):
    hapi, sedes = destinos_falsos
    r = bus.procesar_hl7(ejemplo("02_oru_r01_laboratorio_sede1.hl7"))
    assert r["estado"] == "entregado" and r["sede"] == 1
    obs, = sedes.observaciones.values()
    assert (obs["cod_loinc"], obs["valor_numerico"], obs["cod_unidad"], obs["sede"]) == ("718-7", 13.8, "g/dL", 1)
    assert hapi.recursos[[k for k in hapi.recursos if k.startswith("Observation/")][0]]["valueQuantity"]["value"] == 13.8


def test_mensaje_invalido_se_rechaza_con_3_motivos_y_queda_registrado_no_se_pierde(destinos_falsos):
    hapi, sedes = destinos_falsos
    r = bus.procesar_hl7(ejemplo("03_adt_a01_invalido.hl7"))
    assert r["estado"] == "rechazado" and len(r["motivos"]) == 3
    fila = bus.detalle(r["id_mensaje"])
    assert fila["estado"] == "rechazado" and fila["motivos"] == r["motivos"] and "ABC123" in fila["contenido"]
    assert hapi.llamadas == 0 and sedes.llamadas == 0            # no se transformó ni se entregó nada
    assert [e for e, _ in eventos(r["id_mensaje"])] == ["recibido", "rechazado"]


def test_csv_de_la_sede_3_entrega_3_y_rechaza_2(destinos_falsos):
    hapi, sedes = destinos_falsos
    r = bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 3)
    assert r["filas"] == 5 and r["por_estado"] == {"entregado": 3, "rechazado": 2}
    por_doc = {x["documento"]: x for x in r["resultados"]}
    assert [d for d, x in por_doc.items() if x["estado"] == "entregado"] == ["1008", "1009", "1010"]
    assert any("sin mapeo" in m for m in por_doc["1011"]["motivos"]) and any("longitud" in m for m in por_doc["12"]["motivos"])
    assert {k[2] for k in sedes.pacientes} == {"1008", "1009", "1010"} and len(sedes.triages) == 2     # 1009 no trae triage
    assert {c["cod_cie10"] for dx in sedes.diagnosticos.values() for c in dx} == {"A09", "I10", "J45.9"}


# ------------------------------------------------------------------------------------------ idempotencia
def test_reenviar_el_mismo_mensaje_responde_duplicado_y_no_crea_otro_paciente(destinos_falsos):
    hapi, sedes = destinos_falsos
    primero = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    segundo = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert primero["estado"] == "entregado" and segundo["estado"] == "duplicado" and segundo["id_mensaje"] == primero["id_mensaje"]
    assert segundo["estado_original"] == "entregado"
    assert len(sedes.pacientes) == 1 and len(sedes.encuentros) == 1 and hapi.llamadas == 1
    assert db.uno("SELECT count(*) AS n, max(duplicados) AS d FROM mensaje_bus") == {"n": 1, "d": 1}


def test_la_idempotencia_sobrevive_al_reinicio_del_bus_porque_vive_en_la_base(destinos_falsos):
    _, sedes = destinos_falsos
    bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    db._pool.closeall()                                            # «el bus se reinicia»: se pierde todo lo que estaba en memoria
    db._pool = None
    assert bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))["estado"] == "duplicado"
    assert len(sedes.pacientes) == 1


def test_reenviar_el_csv_completo_marca_las_5_filas_como_duplicadas(destinos_falsos):
    _, sedes = destinos_falsos
    bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 3)
    r = bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 3)
    assert r["por_estado"] == {"duplicado": 5} and len(sedes.pacientes) == 3


def test_el_mismo_contenido_en_otra_sede_no_es_duplicado(destinos_falsos):
    bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 3)
    assert bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 2)["por_estado"] == {"entregado": 3, "rechazado": 2}


def test_ocho_envios_simultaneos_del_mismo_mensaje_entregan_uno_y_los_otros_siete_son_duplicados(destinos_falsos):
    hapi, sedes = destinos_falsos
    resultados = []
    hilos = [threading.Thread(target=lambda: resultados.append(bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7")))) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    estados = sorted(r["estado"] for r in resultados)
    assert estados == ["duplicado"] * 7 + ["entregado"], estados
    assert len(sedes.pacientes) == 1 and len(sedes.encuentros) == 1 and db.uno("SELECT count(*) AS n FROM mensaje_bus")["n"] == 1


def test_un_mensaje_rechazado_corregido_y_reenviado_con_el_mismo_id_se_procesa(destinos_falsos):
    malo = ejemplo("01_adt_a01_valido_sede2.hl7").replace("|F\r", "|X\r")
    assert bus.procesar_hl7(malo)["estado"] == "rechazado"
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert r["estado"] == "entregado" and db.uno("SELECT count(*) AS n FROM mensaje_bus")["n"] == 1


# ------------------------------------------------------------------------------------------ fallos y recuperación
def test_si_hapi_esta_apagado_el_mensaje_se_reintenta_y_termina_entregado_sin_duplicarse(destinos_falsos):
    hapi, sedes = destinos_falsos
    hapi.arriba = False
    r = bus.procesar_hl7(ejemplo("02_oru_r01_laboratorio_sede1.hl7"))
    assert r["estado"] == "reintentando" and "HAPI no responde" in r["ultimo_error"] and r["intentos"] == 1
    assert sedes.llamadas == 0                                      # primero HAPI: si falla, el nodo no se toca
    hapi.arriba = True
    esperar_pendientes()
    fila = bus.detalle(r["id_mensaje"])
    assert fila["estado"] == "entregado" and fila["intentos"] >= 2
    assert len(sedes.observaciones) == 1 and len(sedes.pacientes) == 1                                # sin duplicados
    estados = [e for e, _ in eventos(r["id_mensaje"])]
    assert "reintentando" in estados and estados[-1] == "entregado" and estados.index("reintentando") < estados.index("entregado")


def test_un_conflicto_de_version_409_del_hapi_se_reintenta_y_no_se_rechaza(destinos_falsos):
    hapi, sedes = destinos_falsos
    hapi.conflictos = 2                                              # dos intentos chocan con una escritura en curso; el tercero pasa
    r = bus.procesar_hl7(ejemplo("02_oru_r01_laboratorio_sede1.hl7"))
    assert r["estado"] == "reintentando" and "409" in r["ultimo_error"] and "conflicto de versión" in r["ultimo_error"]
    esperar_pendientes()
    fila = bus.detalle(r["id_mensaje"])
    assert fila["estado"] == "entregado" and fila["intentos"] == 3
    assert len(sedes.observaciones) == 1 and len(sedes.pacientes) == 1                                # el reintento no duplica


def test_el_retroceso_es_exponencial_con_tope():
    from hc_hsb import config
    config.BACKOFF_BASE_S, config.BACKOFF_MAX_S = 1.0, 30.0
    assert [bus.espera(n) for n in range(1, 8)] == [1, 2, 4, 8, 16, 30, 30]


def test_si_se_agotan_los_intentos_el_mensaje_queda_muerto_y_se_puede_reencolar(destinos_falsos):
    hapi, sedes = destinos_falsos
    hapi.arriba = False
    r = bus.procesar_hl7(ejemplo("02_oru_r01_laboratorio_sede1.hl7"))
    esperar_pendientes()
    fila = bus.detalle(r["id_mensaje"])
    assert fila["estado"] == "muerto" and fila["intentos"] == 4 and fila["proximo_intento"] is None
    assert bus.procesar_pendientes() == 0                           # un muerto no se reintenta solo
    assert bus.reencolar(r["id_mensaje"]) is not None and bus.reencolar(r["id_mensaje"]) is None      # solo si está muerto
    hapi.arriba = True
    esperar_pendientes()
    assert bus.detalle(r["id_mensaje"])["estado"] == "entregado" and len(sedes.observaciones) == 1


def test_si_falla_el_nodo_despues_de_hapi_no_se_reenvia_a_hapi_al_reintentar(destinos_falsos):
    hapi, sedes = destinos_falsos
    sedes.caidas.add(2)
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    fila = bus.detalle(r["id_mensaje"])
    assert fila["estado"] == "reintentando" and fila["hapi_ok"] is True and fila["nodo_ok"] is False
    sedes.caidas.clear()
    esperar_pendientes()
    assert bus.detalle(r["id_mensaje"])["estado"] == "entregado" and hapi.llamadas == 1 and len(sedes.pacientes) == 1


def test_un_mensaje_que_quedo_a_medias_porque_el_bus_murio_se_retoma_sin_duplicar(destinos_falsos, monkeypatch):
    hapi, sedes = destinos_falsos
    with monkeypatch.context() as m:         # el bus muere justo después de guardar el mensaje (solo este reemplazo se deshace)
        m.setattr(bus, "entregar", lambda id_: {"estado": "transformado"})
        bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    id_mensaje = db.uno("SELECT id_mensaje FROM mensaje_bus")["id_mensaje"]
    assert db.uno("SELECT estado FROM mensaje_bus")["estado"] == "transformado" and hapi.llamadas == 0
    assert bus.procesar_pendientes() == 0                                              # aún no pasó el tiempo de recuperación
    db.ejecutar("UPDATE mensaje_bus SET actualizado_en = now() - interval '5 minutes'")
    assert bus.procesar_pendientes() == 1
    assert bus.detalle(id_mensaje)["estado"] == "entregado" and len(sedes.pacientes) == 1


def test_si_el_bus_murio_despues_de_hapi_y_antes_del_nodo_al_retomar_no_duplica(destinos_falsos):
    """La pregunta de autoevaluación de la guía: HAPI ya tiene el Bundle, el nodo no. Al reiniciar se completa el nodo; el PUT hace seguro cualquier reenvío."""
    hapi, sedes = destinos_falsos
    sedes.caidas.add(2)
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    sedes.caidas.clear()
    db.ejecutar("UPDATE mensaje_bus SET estado = 'transformado', proximo_intento = NULL, actualizado_en = now() - interval '5 minutes'")
    bus.procesar_pendientes()
    assert bus.detalle(r["id_mensaje"])["estado"] == "entregado" and len(hapi.recursos) == 4 and len(sedes.pacientes) == 1


def test_si_la_sede_rechaza_el_contenido_no_se_reintenta_y_queda_rechazado_con_el_motivo(destinos_falsos):
    hapi, sedes = destinos_falsos
    sedes.rechazar_dx_catalogo = True
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert r["estado"] == "rechazado" and r["intentos"] == 1 and any("422" in m and "sede 2" in m for m in r["motivos"])
    assert bus.procesar_pendientes() == 0


def test_la_cuenta_de_servicio_mal_configurada_no_rechaza_el_mensaje_queda_para_reintentar(destinos_falsos, monkeypatch):
    from hc_hsb import config
    monkeypatch.setattr(config, "CLAVE_SERVICIO", "incorrecta")
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert r["estado"] == "reintentando" and "cuenta del bus" in r["ultimo_error"]


def test_dos_diagnosticos_de_ingreso_en_un_adt_no_chocan_el_segundo_queda_relacionado(destinos_falsos):
    _, sedes = destinos_falsos
    msg = ejemplo("01_adt_a01_valido_sede2.hl7") + "\rDG1|2||I10^Hipertension^I10||20261107|A"
    assert bus.procesar_hl7(msg.replace("MSG-0001", "MSG-0009"))["estado"] == "entregado"
    tipos = sorted(d["cod_tipo_diagnostico"] for dx in sedes.diagnosticos.values() for d in dx)
    assert tipos == ["IN", "RE"]


# ------------------------------------------------------------------------------------------ consulta y métricas
def test_resumen_y_metricas_salen_de_la_base(destinos_falsos):
    hapi, _ = destinos_falsos
    bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    bus.procesar_hl7(ejemplo("03_adt_a01_invalido.hl7"))
    hapi.arriba = False
    bus.procesar_hl7(ejemplo("02_oru_r01_laboratorio_sede1.hl7"))
    r = bus.resumen()
    assert r["total"] == 3 and r["por_estado"]["entregado"] == 1 and r["por_estado"]["rechazado"] == 1 and r["por_estado"]["reintentando"] == 1
    assert r["duplicados_detectados"] == 1 and r["ultimo_minuto"] == 3 and r["porcentaje_fallidos"] == 33.33 and r["latencia_media_s"] > 0
    assert {m["estado"] for m in bus.listar()} == {"entregado", "rechazado", "reintentando"}
    assert [m["estado"] for m in bus.listar(estado="rechazado")] == ["rechazado"] and bus.listar(sede=3)[0]["estado"] == "rechazado"


# ------------------------------------------------------------------------------------------ plazos y presupuesto
def test_un_destino_muy_lento_no_cuelga_el_intento_mas_alla_del_plazo(destinos_falsos, monkeypatch):
    from hc_hsb import config
    hapi, sedes = destinos_falsos
    hapi.demora_s = 0.4
    monkeypatch.setattr(config, "PLAZO_INTENTO_S", 0.6)
    inicio = time.time()
    r = bus.procesar_hl7(ejemplo("01_adt_a01_valido_sede2.hl7"))
    assert r["estado"] == "reintentando"
    assert "tiempo de este intento" in r["ultimo_error"] or "HAPI" in r["ultimo_error"]
    assert time.time() - inicio < 3 and sedes.llamadas <= 1


def test_el_csv_que_agota_su_presupuesto_encola_las_filas_restantes_y_el_sondeo_las_entrega(destinos_falsos, monkeypatch):
    from hc_hsb import config
    _, sedes = destinos_falsos
    monkeypatch.setattr(config, "PRESUPUESTO_S", 0.0)               # ninguna fila se entrega dentro de la petición
    r = bus.procesar_csv(ejemplo("04_sede3_legado.csv"), 3)
    assert r["por_estado"] == {"reintentando": 3, "rechazado": 2} and all(x.get("en_cola") for x in r["resultados"] if x["estado"] == "reintentando")
    assert sedes.llamadas == 0                                      # nada se entregó en la petición
    esperar_pendientes()
    assert db.uno("SELECT count(*) AS n FROM mensaje_bus WHERE estado = 'entregado'")["n"] == 3 and len(sedes.pacientes) == 3
