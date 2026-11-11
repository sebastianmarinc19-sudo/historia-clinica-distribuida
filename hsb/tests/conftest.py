"""Fixtures de integración: PostgreSQL REAL para el bus y destinos (HAPI y 3 APIs de sede) simulados con httpx.MockTransport.

Los destinos falsos respetan el contrato de la API real (ids idempotentes -> «existente», 422 si el código no está en el catálogo,
409 si el rol de diagnóstico ya está ocupado por otro) y se pueden «apagar» para probar reintentos, mensajes muertos y recuperación.
"""
import base64
import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

os.environ.setdefault("HSB_DB_HOST", "127.0.0.1")
os.environ.setdefault("HSB_DB_USER", "hsb")
os.environ.setdefault("HSB_DB_PASSWORD", "hsb")
os.environ.setdefault("HSB_DB_NAME", "hsb")
os.environ.setdefault("HC_JWT_SECRETO", "secreto-de-prueba")
os.environ.setdefault("HSB_FHIR_URL", "http://hapi.test/fhir")
os.environ.setdefault("HSB_API_URLS", "1=http://api1.test,2=http://api2.test,3=http://api3.test")
os.environ.setdefault("HSB_USUARIO", "hsb")
os.environ.setdefault("HSB_CLAVE", "clave-hsb")

from hc_hsb import bus, config, db, destinos  # noqa: E402

CIE10 = {"A09", "I10", "E11.9", "J45.9", "N39.0", "M54.5", "J18.9", "R51"}
LOINC = {"718-7", "8310-5"}


class HapiFalso:
    def __init__(self):
        self.arriba = True
        self.demora_s = 0.0                      # simula un HAPI a medias: responde, pero lento
        self.llamadas = 0
        self.conflictos = 0                      # cuántas respuestas 409 (conflicto de versión) dar antes de aceptar
        self.recursos: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.llamadas += 1
        if self.demora_s:
            time.sleep(self.demora_s)
        if not self.arriba:
            raise httpx.ConnectError("HAPI apagado", request=request)
        if self.conflictos:
            self.conflictos -= 1
            return httpx.Response(409, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "diagnostics": "HAPI-0550: version constraint failure"}]})
        bundle = json.loads(request.content)
        for e in bundle["entry"]:
            assert e["request"]["method"] == "PUT"
            self.recursos[e["request"]["url"]] = e["resource"]       # PUT: mismo id = mismo recurso, nunca uno nuevo
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})


class SedesFalsas:
    def __init__(self):
        self.caidas: set[int] = set()
        self.rechazar_dx_catalogo = False
        self.pacientes: dict[tuple, dict] = {}
        self.encuentros: dict[str, dict] = {}
        self.diagnosticos: dict[str, list] = {}
        self.triages: dict[str, int] = {}
        self.observaciones: dict[str, dict] = {}
        self.llamadas = 0

    @staticmethod
    def sede(request) -> int:
        return int(request.url.host[3])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sede = self.sede(request)
        if sede in self.caidas:
            raise httpx.ConnectError("sede caída", request=request)
        self.llamadas += 1
        ruta, cuerpo = request.url.path, (json.loads(request.content) if request.content else {})
        if ruta == "/api/v2/auth/login":
            ok = cuerpo.get("clave") == "clave-hsb"
            return httpx.Response(200, json={"token": "t"}) if ok else httpx.Response(401, json={"detail": "mal"})
        if request.headers.get("Authorization") != "Bearer t":
            return httpx.Response(401, json={"detail": "sin sesión"})
        if ruta == "/api/v2/pacientes":
            clave = (sede, cuerpo["cod_tipo_documento"], cuerpo["numero_documento"])
            nuevo = clave not in self.pacientes
            self.pacientes.setdefault(clave, {"id_paciente": f"p-{sede}-{cuerpo['numero_documento']}"}).update(cuerpo)
            return httpx.Response(201 if nuevo else 200, json={"accion": "creado" if nuevo else "actualizado",
                                                               "paciente": {"id_paciente": self.pacientes[clave]["id_paciente"]}})
        if ruta == "/api/v2/encuentros":
            id_enc = cuerpo["id_encuentro"]
            existe = id_enc in self.encuentros
            self.encuentros.setdefault(id_enc, {**cuerpo, "sede": sede})
            return httpx.Response(200 if existe else 201, json={"accion": "existente" if existe else "creado", "encuentro": {"id_encuentro": id_enc}})
        partes = ruta.strip("/").split("/")                       # api v2 encuentros <id> <recurso>
        if len(partes) == 5 and partes[2] == "encuentros":
            id_enc, recurso = partes[3], partes[4]
            if id_enc not in self.encuentros:
                return httpx.Response(404, json={"detail": "Encuentro no encontrado"})
            if recurso == "diagnosticos":
                if self.rechazar_dx_catalogo or cuerpo["cod_cie10"] not in CIE10:
                    return httpx.Response(422, json={"error": "codigo_o_referencia_invalida", "restriccion": "diagnostico_encuentro_cod_cie10_fkey"})
                previos = self.diagnosticos.setdefault(id_enc, [])
                if any(d["cod_cie10"] == cuerpo["cod_cie10"] and d["cod_tipo_diagnostico"] == cuerpo["cod_tipo_diagnostico"] for d in previos):
                    return httpx.Response(200, json={"accion": "existente"})
                if cuerpo["cod_tipo_diagnostico"] == "IN" and any(d["cod_tipo_diagnostico"] == "IN" for d in previos):
                    return httpx.Response(409, json={"error": "duplicado", "restriccion": "uq_diagnostico_rol_unico"})
                previos.append(cuerpo)
                return httpx.Response(201, json={"accion": "creado"})
            if recurso == "triage":
                if self.triages.get(id_enc) == cuerpo["cod_triage"]:
                    return httpx.Response(200, json={"accion": "existente"})
                self.triages[id_enc] = cuerpo["cod_triage"]
                return httpx.Response(201, json={"accion": "creado"})
            if recurso == "observaciones":
                if cuerpo["cod_loinc"] not in LOINC:
                    return httpx.Response(422, json={"error": "codigo_o_referencia_invalida"})
                existe = cuerpo["id_observacion"] in self.observaciones
                self.observaciones[cuerpo["id_observacion"]] = {**cuerpo, "id_encuentro": id_enc, "sede": sede}
                return httpx.Response(200 if existe else 201, json={"accion": "existente" if existe else "creado"})
        return httpx.Response(404, json={"detail": f"ruta no simulada: {ruta}"})


@pytest.fixture(scope="session", autouse=True)
def base_del_bus():
    for _ in range(60):
        try:
            db.iniciar()
            return
        except Exception:      # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("no hay PostgreSQL para las pruebas del bus (HSB_DB_HOST)")


@pytest.fixture(autouse=True)
def limpio(monkeypatch):
    db.ejecutar("TRUNCATE mensaje_bus, evento_mensaje")
    monkeypatch.setattr(config, "BACKOFF_BASE_S", 0.02)
    monkeypatch.setattr(config, "BACKOFF_MAX_S", 0.05)
    monkeypatch.setattr(config, "MAX_INTENTOS", 4)
    yield


@pytest.fixture
def destinos_falsos(monkeypatch):
    hapi, sedes = HapiFalso(), SedesFalsas()
    monkeypatch.setattr(bus, "HAPI", destinos.ClienteHapi(httpx.MockTransport(hapi)))
    monkeypatch.setattr(bus, "SEDE", destinos.ClienteSede(httpx.MockTransport(sedes)))
    return hapi, sedes


def token(rol: str, sub: str = "prueba", vence_en: int = 600, secreto: str = "secreto-de-prueba") -> str:
    def b64(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    cuerpo = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': sub, 'rol': rol, 'exp': int(time.time()) + vence_en})}"
    firma = base64.urlsafe_b64encode(hmac.new(secreto.encode(), cuerpo.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{cuerpo}.{firma}"
