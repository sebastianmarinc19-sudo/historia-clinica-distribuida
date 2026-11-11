"""TLS del gateway: certificado firmado por la CA de laboratorio, solo TLS 1.2+, HTTP solo redirige y la IP de origen
que ve la API no se puede falsificar con una cabecera enviada por el cliente.

Variables: API_GATEWAY (https://…), API_GATEWAY_HTTP (http://… del mismo gateway) y HC_CA (ruta de la CA).
"""
import os
import socket
import ssl
import time
from urllib.parse import urlparse

import httpx
import pytest

import sesion
from test_integracion import GATEWAY, auth, esperar

GATEWAY_HTTP = os.getenv("API_GATEWAY_HTTP", "http://hc_gateway")
HOST, PUERTO = urlparse(GATEWAY).hostname, urlparse(GATEWAY).port or 443


def test_el_gateway_sirve_https_con_un_certificado_de_la_ca_de_laboratorio():
    r = httpx.get(f"{GATEWAY}/api/health", verify=sesion.verificar(), timeout=30)
    assert r.status_code == 200 and r.json()["db"] == "ok"


def test_sin_la_ca_el_certificado_se_rechaza():
    with pytest.raises(httpx.ConnectError) as e:
        httpx.get(f"{GATEWAY}/api/health", verify=True, timeout=30)       # almacén del sistema: no contiene la CA de laboratorio
    assert "CERTIFICATE_VERIFY_FAILED" in str(e.value)


def test_http_solo_redirige_a_https_y_no_entrega_datos():
    r = httpx.get(f"{GATEWAY_HTTP}/api/v2/sede", follow_redirects=False, timeout=30)
    assert r.status_code == 308 and r.headers["location"].startswith("https://")
    assert "sede_local" not in r.text
    # un POST con claves tampoco llega a la API por HTTP
    r = httpx.post(f"{GATEWAY_HTTP}/api/v2/auth/login", json={"usuario": "x", "clave": "y"}, follow_redirects=False, timeout=30)
    assert r.status_code == 308
    assert httpx.get(f"{GATEWAY_HTTP}/healthz", timeout=30).status_code == 200      # la sonda de salud sigue en HTTP


def test_cabeceras_de_seguridad():
    r = httpx.get(f"{GATEWAY}/vistas/index.html", verify=sesion.verificar(), timeout=30)
    assert "max-age" in r.headers["strict-transport-security"]
    assert r.headers["x-content-type-options"] == "nosniff"


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")     # se usan a propósito TLS 1.0/1.1 para comprobar que se rechazan


def _handshake(minima, maxima):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(sesion.ca())
    ctx.minimum_version, ctx.maximum_version = minima, maxima
    ctx.set_ciphers("ALL:@SECLEVEL=0")
    with socket.create_connection((HOST, PUERTO), timeout=10) as s, ctx.wrap_socket(s, server_hostname=HOST) as t:
        return t.version()


def test_acepta_tls_12_y_13():
    assert _handshake(ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2) == "TLSv1.2"
    assert _handshake(ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3) == "TLSv1.3"


def test_rechaza_tls_antiguo():
    try:
        ctx_ok = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx_ok.minimum_version = ssl.TLSVersion.TLSv1
        ctx_ok.maximum_version = ssl.TLSVersion.TLSv1_1
    except (ValueError, ssl.SSLError):
        pytest.skip("esta biblioteca TLS del cliente ya no habla TLS 1.0/1.1")
    with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
        _handshake(ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1)


def test_login_y_consulta_por_el_gateway_https():
    c = httpx.Client(base_url=GATEWAY, verify=sesion.verificar(), timeout=30)
    cred = sesion.credenciales()["medico"]
    t = c.post("/sede/1/api/v2/auth/login", json={"usuario": "medico", "clave": cred["clave"]})
    assert t.status_code == 200
    r = c.get("/sede/2/api/v2/auth/yo", headers={"Authorization": "Bearer " + t.json()["token"]})
    assert r.status_code == 200 and r.json()["rol"] == "medico"


def test_la_ip_de_origen_no_se_puede_falsificar_con_x_forwarded_for():
    marca = f"spoof{int(time.time())}"
    c = httpx.Client(base_url=GATEWAY, verify=sesion.verificar(), timeout=30)
    c.post("/sede/1/api/v2/auth/login", json={"usuario": marca, "clave": "x"}, headers={"X-Forwarded-For": "203.0.113.77"})
    def leer():          # el registro se escribe en segundo plano
        filas = httpx.get(f"{GATEWAY}/sede/1/api/v2/auditoria/accesos", params={"limite": 200}, headers=auth("reportero"),
                          verify=sesion.verificar(), timeout=30).json()["accesos"]
        return [f for f in filas if f["usuario"] == marca]
    propias = esperar(leer, timeout=10)
    assert propias, "el intento fallido no quedó registrado"
    assert all(f["ip"] != "203.0.113.77" for f in propias), "la API tomó la IP que envió el cliente"
