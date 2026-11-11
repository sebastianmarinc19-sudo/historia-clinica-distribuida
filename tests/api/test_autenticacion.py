"""Autenticación y control de acceso por rol contra las 3 sedes en ejecución.

Comprueba: rutas protegidas sin sesión (401), matriz de roles (403), un token que vale en las 3 sedes,
alcance del paciente a su propio documento, tokens manipulados o vencidos y el registro local de accesos.
Usa las claves de laboratorio (HC_CREDENCIALES o credenciales/credenciales.json); para el token vencido necesita
además HC_JWT_SECRETO (se omite si no está).
"""
import base64
import json
import os
import time
import uuid
from datetime import date, timedelta

import httpx
import pytest

import sesion
from test_integracion import URL, buscar_en, esperar, paciente_json

DOC = f"AU{int(time.time())}"
NAC = date(1950, 1, 1) + timedelta(days=int(time.time()) % 15000)
OTRO = f"AO{int(time.time())}"
E = {}


def con(sede: int, usuario: str | None = None, token: str | None = None) -> httpx.Client:
    cab = {}
    if usuario:
        cab["Authorization"] = "Bearer " + sesion.token(URL[1], usuario)
    if token:
        cab["Authorization"] = "Bearer " + token
    return httpx.Client(base_url=URL[sede], timeout=30, headers=cab)


def _paciente(doc, nombre):
    return paciente_json(numero_documento=doc, primer_nombre=nombre, primer_apellido="Auth" + doc[-4:],
                         fecha_hora_nacimiento=NAC.isoformat() + "T08:00:00")


# ------------------------------------------------------------------ sin sesión
RUTAS_PROTEGIDAS = [
    ("GET", "/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=1"),
    ("GET", f"/api/v2/pacientes/{uuid.uuid4()}"),
    ("GET", f"/api/v2/encuentros/{uuid.uuid4()}"),
    ("GET", "/api/v2/historia-federada/1"),
    ("GET", "/api/v2/cobertura"),
    ("GET", "/api/v2/replicacion"),
    ("GET", "/api/v2/auditoria/57-campos"),
    ("GET", "/api/v2/auditoria/accesos"),
    ("GET", "/api/v2/auth/yo"),
    ("POST", "/api/v2/pacientes"),
    ("POST", "/api/v2/profesionales"),
]
PUBLICAS = ["/api/health", "/api/health/live", "/metrics", "/api/v2/sede", "/api/v2/catalogos/tipo_documento", "/vistas/index.html"]


def test_las_rutas_clinicas_exigen_sesion_en_cada_sede():
    for sede in (1, 2, 3):
        for metodo, ruta in RUTAS_PROTEGIDAS:
            r = con(sede).request(metodo, ruta, json={} if metodo == "POST" else None)
            assert r.status_code == 401, f"sede {sede} {metodo} {ruta}: {r.status_code}"
            assert r.headers.get("www-authenticate") == "Bearer"


def test_salud_catalogos_vistas_y_metricas_siguen_publicos():
    for sede in (1, 2, 3):
        for ruta in PUBLICAS:
            assert con(sede).get(ruta).status_code == 200, f"sede {sede} {ruta}"


def test_clave_incorrecta_o_usuario_inexistente_da_401_sin_distinguir():
    mal = con(1).post("/api/v2/auth/login", json={"usuario": "medico", "clave": "no-es"})
    nadie = con(1).post("/api/v2/auth/login", json={"usuario": "nadie", "clave": "no-es"})
    assert mal.status_code == nadie.status_code == 401
    assert mal.json() == nadie.json()


# -------------------------------------------------------------- tokens
def test_un_token_emitido_por_una_sede_vale_en_las_otras_dos():
    token = sesion.iniciar(URL[1], "medico", sesion.credenciales()["medico"]["clave"])
    for sede in (1, 2, 3):
        r = con(sede, token=token).get("/api/v2/auth/yo")
        assert r.status_code == 200 and r.json()["rol"] == "medico", f"sede {sede}"


def _forjar(carga: dict, cabecera=None, firma="x") -> str:
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64(cabecera or {'alg': 'HS256', 'typ': 'JWT'})}.{b64(carga)}.{firma}"


def test_tokens_manipulados_se_rechazan():
    ok = sesion.token(URL[1], "medico")
    cab, carga, firma = ok.split(".")
    relleno = "=" * (-len(carga) % 4)
    datos = json.loads(base64.urlsafe_b64decode(carga + relleno))
    datos["rol"] = "administrador"                      # sube de rol conservando la firma original
    escalado = f"{cab}.{base64.urlsafe_b64encode(json.dumps(datos).encode()).rstrip(b'=').decode()}.{firma}"
    sin_firma_valida = _forjar({"sub": "x", "rol": "administrador", "exp": int(time.time()) + 600})
    sin_alg = _forjar({"sub": "x", "rol": "administrador", "exp": int(time.time()) + 600}, cabecera={"alg": "none", "typ": "JWT"}, firma="")
    for malo in (escalado, sin_firma_valida, sin_alg, "basura", ""):
        r = con(1, token=malo).get("/api/v2/cobertura")
        assert r.status_code == 401, malo[:30]


@pytest.mark.skipif(not os.getenv("HC_JWT_SECRETO"), reason="necesita HC_JWT_SECRETO para firmar un token vencido")
def test_token_vencido_se_rechaza():
    from hc_api import auth
    vencido = auth.emitir_token("medico", "medico", os.environ["HC_JWT_SECRETO"], 60, ahora=time.time() - 3600)
    assert con(1, token=vencido).get("/api/v2/auth/yo").status_code == 401
    vigente = auth.emitir_token("medico", "medico", os.environ["HC_JWT_SECRETO"], 60)
    assert con(1, token=vigente).get("/api/v2/auth/yo").status_code == 200


# -------------------------------------------------------- matriz de roles
def _diag():
    return {"cod_cie10": "J00", "cod_tipo_diagnostico": "RE", "fecha_diagnostico": date.today().isoformat()}


# (usuario, método, ruta, cuerpo, ¿permitido?). Permitido = pasa el control de rol (después puede ser 404/409/422).
def _matriz():
    enc = str(uuid.uuid4())
    return [
        ("admision", "POST", "/api/v2/pacientes", _paciente(f"MX{int(time.time())}", "Matriz"), True),
        ("medico", "POST", "/api/v2/pacientes", _paciente(f"MY{int(time.time())}", "Matriz"), False),
        ("reportero", "POST", "/api/v2/pacientes", _paciente(f"MZ{int(time.time())}", "Matriz"), False),
        ("admision", "POST", f"/api/v2/encuentros/{enc}/diagnosticos", _diag(), False),
        ("reportero", "POST", f"/api/v2/encuentros/{enc}/diagnosticos", _diag(), False),
        ("medico", "POST", f"/api/v2/encuentros/{enc}/diagnosticos", _diag(), True),
        ("admision", "POST", f"/api/v2/migracion/encuentro/{enc}", None, False),
        ("reportero", "POST", f"/api/v2/migracion/encuentro/{enc}", None, False),
        ("admision", "POST", f"/api/v2/mpi/resolver/{enc}", None, False),
        ("reportero", "POST", f"/api/v2/migracion/paciente/{enc}", None, False),
        ("medico", "GET", "/api/v2/cobertura", None, False),
        ("admision", "GET", "/api/v2/cobertura", None, False),
        ("reportero", "GET", "/api/v2/cobertura", None, True),
        ("admision", "GET", "/api/v2/auditoria/57-campos", None, False),
        ("reportero", "GET", "/api/v2/auditoria/57-campos", None, True),
        ("medico", "GET", "/api/v2/auditoria/accesos", None, False),
        ("reportero", "GET", "/api/v2/auditoria/accesos", None, True),
        ("reportero", "GET", "/api/v2/replicacion", None, True),
        ("admision", "GET", "/api/v2/replicacion", None, False),
        ("reportero", "GET", "/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=1", None, False),
        ("admision", "GET", "/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=1", None, True),
        ("medico", "GET", "/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento=1", None, True),
        ("admision", "GET", "/api/v2/historia-federada/1", None, False),     # la historia clínica es del médico y del paciente
        ("medico", "GET", "/api/v2/historia-federada/1", None, True),
        ("admin", "GET", "/api/v2/cobertura", None, True),
        ("admin", "POST", "/api/v2/profesionales", {"cod_tipo_documento": "CC", "numero_documento": f"AD{int(time.time())}", "nombres": "A", "apellidos": "B"}, True),
    ]


def test_matriz_de_roles():
    fallos = []
    for usuario, metodo, ruta, cuerpo, permitido in _matriz():
        r = con(1, usuario).request(metodo, ruta, json=cuerpo)
        if permitido and r.status_code in (401, 403):
            fallos.append(f"{usuario} debía poder {metodo} {ruta}: {r.status_code}")
        if not permitido and r.status_code != 403:
            fallos.append(f"{usuario} no debía poder {metodo} {ruta}: {r.status_code}")
    assert not fallos, "\n".join(fallos)


# ------------------------------------------------------------- paciente
def test_paciente_entra_con_documento_y_fecha_de_nacimiento_y_solo_ve_lo_suyo():
    a = con(1, "admision")
    assert a.post("/api/v2/pacientes", json=_paciente(DOC, "Propia")).status_code == 201
    r = a.post("/api/v2/pacientes", json=_paciente(OTRO, "Ajeno"))
    assert r.status_code == 201
    E["ajeno"] = r.json()["paciente"]["id_paciente"]

    cuerpo = {"cod_tipo_documento": "CC", "numero_documento": DOC, "fecha_nacimiento": NAC.isoformat()}
    for malo in ({**cuerpo, "fecha_nacimiento": (NAC + timedelta(days=1)).isoformat()}, {**cuerpo, "numero_documento": "000"}):
        assert con(1).post("/api/v2/auth/paciente", json=malo).status_code == 401
    resp = con(1).post("/api/v2/auth/paciente", json=cuerpo)
    assert resp.status_code == 200 and resp.json()["usuario"]["rol"] == "paciente"
    E["token"] = resp.json()["token"]
    assert resp.json()["expira_en_s"] <= 3600

    p = con(1, token=E["token"])
    propios = p.get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC})
    assert propios.status_code == 200 and propios.json()["total"] >= 1
    assert p.get("/api/v2/historia-federada/" + DOC, params={"cod_tipo_documento": "CC"}).status_code == 200
    yo = p.get("/api/v2/auth/yo").json()
    assert yo["numero_documento"] == DOC and yo["rol"] == "paciente"


def test_paciente_no_puede_ver_a_otros_ni_buscar_por_nombre_ni_escribir():
    p = con(1, token=E["token"])
    assert p.get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": OTRO}).status_code == 403
    assert p.get("/api/v2/pacientes/buscar", params={"nombre": "Ajeno"}).status_code == 403
    assert p.get(f"/api/v2/pacientes/{E['ajeno']}").status_code == 403
    assert p.get("/api/v2/historia-federada/" + OTRO, params={"cod_tipo_documento": "CC"}).status_code == 403
    assert p.post("/api/v2/pacientes", json=_paciente(f"PX{int(time.time())}", "Escribe")).status_code == 403
    for ruta in ("/api/v2/cobertura", "/api/v2/replicacion", "/api/v2/auditoria/57-campos", "/api/v2/auditoria/accesos"):
        assert p.get(ruta).status_code == 403, ruta


def test_el_token_del_paciente_sirve_en_otra_sede_con_la_misma_limitacion():
    assert esperar(lambda: buscar_en(2, DOC)), "el paciente no se replicó a Cartagena"
    p = con(2, token=E["token"])
    assert p.get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": DOC}).status_code == 200
    assert p.get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": OTRO}).status_code == 403


# --------------------------------------------------------- limitación y registro
def test_intentos_fallidos_repetidos_se_bloquean_con_429():
    usuario = f"intruso{int(time.time())}"
    estados = [con(1).post("/api/v2/auth/login", json={"usuario": usuario, "clave": "x"}).status_code for _ in range(24)]
    assert estados[0] == 401 and 429 in estados, estados      # el contador es por réplica de la API: hacen falta hasta 8 por pod


def test_el_registro_de_accesos_guarda_exitos_y_rechazos_con_el_usuario():
    marca = f"reg{int(time.time())}"
    con(1, "medico").get("/api/v2/pacientes/buscar", params={"cod_tipo_documento": "CC", "numero_documento": marca})
    con(1, "reportero").post("/api/v2/pacientes", json=_paciente(f"RG{int(time.time())}", "Rechazo"))
    # un ingreso fallido deja huella con el usuario intentado
    con(1).post("/api/v2/auth/login", json={"usuario": marca, "clave": "mal"})
    def leer():
        return con(1, "reportero").get("/api/v2/auditoria/accesos", params={"limite": 500}).json()["accesos"]
    # el registro se escribe en segundo plano: puede tardar un instante en aparecer
    filas = esperar(lambda: (f := leer()) and any(x["usuario"] == marca and x["estado"] == 401 for x in f) and f, timeout=10) or leer()
    vistos = {(f["usuario"], f["rol"], f["estado"]) for f in filas}
    assert ("medico", "medico", 200) in vistos or ("medico", "medico", 404) in vistos
    assert ("reportero", "reportero", 403) in vistos
    assert all(f["instante"].endswith(("+00:00", "Z")) or "+" in f["instante"][10:] for f in filas), "el instante debe llevar zona horaria"
    assert any(f["usuario"] == marca and f["estado"] == 401 for f in filas), "falta el ingreso fallido"
    assert any(f["documento"] == marca for f in filas), "falta el documento consultado"
    solo = con(1, "reportero").get("/api/v2/auditoria/accesos", params={"solo_fallos": "true", "limite": 200}).json()["accesos"]
    assert solo and all(f["estado"] >= 400 for f in solo)
