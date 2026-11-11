"""Capa HTTP del bus: puertas de entrada, códigos de respuesta, autenticación por rol, estado, salud y métricas."""
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

from conftest import token
from hc_hsb import bus, config
from hc_hsb.main import app

EJEMPLOS = pathlib.Path(os.getenv("HSB_EJEMPLOS", pathlib.Path(__file__).resolve().parents[2] / "ejemplos"))


def leer(nombre: str) -> bytes:
    return (EJEMPLOS / nombre).read_bytes()


@pytest.fixture
def cliente(monkeypatch, destinos_falsos):
    monkeypatch.setattr(config, "SONDEO_S", 3600)       # el sondeo de fondo no interfiere con lo que se comprueba aquí
    with TestClient(app) as c:
        yield c


def de(rol: str) -> dict:
    return {"Authorization": f"Bearer {token(rol)}"}


# ------------------------------------------------------------------------------------ puertas de entrada
def test_post_hl7_valido_responde_200_entregado(cliente):
    r = cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    assert r.status_code == 200 and r.json()["estado"] == "entregado" and r.json()["sede"] == 2


def test_reenviar_responde_200_duplicado(cliente):
    cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    r = cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    assert r.status_code == 200 and r.json()["estado"] == "duplicado"


def test_post_hl7_invalido_responde_422_con_los_motivos(cliente):
    r = cliente.post("/hsb/hl7", content=leer("03_adt_a01_invalido.hl7"), headers=de("sistema_sede"))
    assert r.status_code == 422 and r.json()["estado"] == "rechazado" and len(r.json()["motivos"]) == 3


def test_post_hl7_con_el_destino_caido_responde_202_reintentando(cliente, destinos_falsos):
    destinos_falsos[0].arriba = False
    r = cliente.post("/hsb/hl7", content=leer("02_oru_r01_laboratorio_sede1.hl7"), headers=de("sistema_sede"))
    assert r.status_code == 202 and r.json()["estado"] == "reintentando"


def test_post_csv_devuelve_un_resultado_por_fila(cliente):
    r = cliente.post("/hsb/csv?sede=3", content=leer("04_sede3_legado.csv"), headers=de("sistema_sede"))
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["filas"] == 5 and cuerpo["por_estado"] == {"entregado": 3, "rechazado": 2}
    assert [x["fila"] for x in cuerpo["resultados"]] == [2, 3, 4, 5, 6]


def test_csv_con_sede_invalida_o_sin_columnas_responde_422(cliente):
    assert cliente.post("/hsb/csv?sede=7", content=b"a;b\n", headers=de("sistema_sede")).status_code == 422
    assert cliente.post("/hsb/csv?sede=1", content=b"a;b\n1;2\n", headers=de("sistema_sede")).status_code == 422
    assert cliente.post("/hsb/csv", content=b"x", headers=de("sistema_sede")).status_code == 422       # falta ?sede=


def test_acepta_hl7_con_saltos_de_linea_lf_como_los_que_deja_curl_o_un_editor(cliente):
    lf = leer("01_adt_a01_valido_sede2.hl7").replace(b"\r", b"\n")
    assert cliente.post("/hsb/hl7", content=lf, headers=de("sistema_sede")).json()["estado"] == "entregado"


# ------------------------------------------------------------------------------------ seguridad
def test_sin_token_responde_401_y_con_token_malo_tambien(cliente):
    assert cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7")).status_code == 401
    assert cliente.post("/hsb/hl7", content=b"x", headers={"Authorization": "Bearer basura"}).status_code == 401
    assert cliente.post("/hsb/hl7", content=b"x", headers={"Authorization": f"Bearer {token('sistema_sede', secreto='otro')}"}).status_code == 401
    assert cliente.post("/hsb/hl7", content=b"x", headers={"Authorization": f"Bearer {token('sistema_sede', vence_en=-5)}"}).status_code == 401


@pytest.mark.parametrize("rol", ["medico", "admisionista", "reportero", "paciente"])
def test_solo_un_sistema_de_sede_puede_enviar_mensajes(cliente, rol):
    assert cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de(rol)).status_code == 403
    assert cliente.post("/hsb/csv?sede=3", content=leer("04_sede3_legado.csv"), headers=de(rol)).status_code == 403


def test_un_sistema_de_sede_no_lee_el_estado_ni_reencola_el_personal_si_lee_el_estado(cliente):
    assert cliente.get("/hsb/mensajes", headers=de("sistema_sede")).status_code == 403
    for rol in ("admisionista", "medico", "reportero", "administrador"):
        assert cliente.get("/hsb/mensajes", headers=de(rol)).status_code == 200, rol
    assert cliente.get("/hsb/mensajes", headers=de("paciente")).status_code == 403
    assert cliente.post("/hsb/mensajes/00000000-0000-0000-0000-000000000000/reencolar", headers=de("medico")).status_code == 403


def test_el_administrador_pasa_en_todo(cliente):
    assert cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("administrador")).status_code == 200


# ------------------------------------------------------------------------------------ estado, reencolado, terminología
def test_listar_filtrar_y_ver_el_detalle_con_su_bitacora(cliente):
    cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    cliente.post("/hsb/hl7", content=leer("03_adt_a01_invalido.hl7"), headers=de("sistema_sede"))
    todos = cliente.get("/hsb/mensajes", headers=de("admisionista")).json()
    assert todos["total"] == 2
    rech = cliente.get("/hsb/mensajes?estado=rechazado", headers=de("admisionista")).json()["mensajes"]
    assert [m["estado"] for m in rech] == ["rechazado"]
    det = cliente.get(f"/hsb/mensajes/{rech[0]['id_mensaje']}", headers=de("admisionista")).json()
    assert [e["estado"] for e in det["eventos"]] == ["recibido", "rechazado"]
    assert cliente.get("/hsb/mensajes/00000000-0000-0000-0000-000000000000", headers=de("medico")).status_code == 404


def test_reencolar_solo_funciona_con_mensajes_muertos(cliente, destinos_falsos):
    hapi, _ = destinos_falsos
    hapi.arriba = False
    r = cliente.post("/hsb/hl7", content=leer("02_oru_r01_laboratorio_sede1.hl7"), headers=de("sistema_sede")).json()
    assert cliente.post(f"/hsb/mensajes/{r['id_mensaje']}/reencolar", headers=de("administrador")).status_code == 409
    for _ in range(10):
        bus.procesar_pendientes()
        if bus.detalle(r["id_mensaje"])["estado"] == "muerto":
            break
        import time
        time.sleep(0.06)
    assert bus.detalle(r["id_mensaje"])["estado"] == "muerto"
    assert cliente.post(f"/hsb/mensajes/{r['id_mensaje']}/reencolar", headers=de("administrador")).status_code == 200
    hapi.arriba = True
    bus.procesar_pendientes()
    assert bus.detalle(r["id_mensaje"])["estado"] == "entregado"


def test_terminologia_y_conceptmap(cliente):
    t = cliente.get("/hsb/terminologia", headers=de("medico")).json()
    assert t["total"] == 8 and {"dx_local": "ASMA", "cie10": "J45.9", "descripcion": "Asma"} in t["mapeos"]
    cm = cliente.get("/hsb/terminologia/conceptmap", headers=de("sistema_sede")).json()
    assert cm["resourceType"] == "ConceptMap" and len(cm["group"][0]["element"]) == 8


# ------------------------------------------------------------------------------------ salud y métricas
def test_health_es_publico_y_reporta_la_base_y_los_destinos(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200 and r.json()["db"] == "ok" and set(r.json()["dependencias"]) == {"fhir", "api"}
    assert cliente.get("/health/live").json() == {"status": "ok"}


def test_metrics_expone_mensajes_por_estado_latencia_fallidos_y_duplicados(cliente):
    cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7"), headers=de("sistema_sede"))
    cliente.post("/hsb/hl7", content=leer("03_adt_a01_invalido.hl7"), headers=de("sistema_sede"))
    texto = cliente.get("/metrics").text
    assert 'hsb_mensajes{estado="entregado"} 1.0' in texto and 'hsb_mensajes{estado="rechazado"} 1.0' in texto
    for serie in ("hsb_mensajes_ultimo_minuto 2.0", "hsb_duplicados_detectados 1.0", "hsb_porcentaje_fallidos 50.0",
                  "hsb_latencia_media_segundos", "hsb_latencia_extremo_a_extremo_segundos_bucket", "hsb_reintentos_total",
                  'hsb_mensajes_recibidos_total{formato="HL7"}'):
        assert serie in texto, serie


def test_sin_autenticacion_activa_el_bus_no_pide_token(cliente, monkeypatch):
    """Útil para depurar con curl (HSB_AUTH_ACTIVA=false); en el despliegue viene activa."""
    monkeypatch.setattr(config, "AUTH_ACTIVA", False)
    assert cliente.post("/hsb/hl7", content=leer("01_adt_a01_valido_sede2.hl7")).status_code == 200
