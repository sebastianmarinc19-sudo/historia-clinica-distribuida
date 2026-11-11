#!/usr/bin/env python3
"""Genera la colección de Postman (v2.1) y su entorno a partir de los archivos de ejemplo del parcial (ejemplos/), para que no se desincronicen.

    python3 tests/coleccion/generar_coleccion.py

Escribe tests/coleccion/historia_clinica.postman_collection.json y hc_local.postman_environment.json. Solo biblioteca estándar.
Las claves NO van en los archivos: el entorno las deja vacías (se copian de credenciales/credenciales.json o `python3 scripts/credenciales.py`).
"""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
EJ = lambda n: open(os.path.join(RAIZ, "ejemplos", n), encoding="utf-8").read()
BASE = "{{base_url}}"


def tests(*lineas):
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": list(lineas)}}]


def pedir(nombre, metodo, ruta, rol=None, cuerpo=None, tipo="application/json", pruebas=None, descripcion=None):
    cab = []
    if rol:
        cab.append({"key": "Authorization", "value": "Bearer {{token_%s}}" % rol})
    if cuerpo is not None:
        cab.append({"key": "Content-Type", "value": tipo})
    r = {"name": nombre, "request": {"method": metodo, "header": cab, "url": {"raw": BASE + ruta, "host": ["{{base_url}}"], "path": [p for p in ruta.split("?")[0].split("/") if p],
                                                                              "query": [{"key": k, "value": v} for k, v in (q.split("=") for q in ruta.split("?")[1].split("&"))] if "?" in ruta else []}}}
    if cuerpo is not None:
        r["request"]["body"] = {"mode": "raw", "raw": cuerpo}
    if descripcion:
        r["request"]["description"] = descripcion
    if pruebas:
        r["event"] = tests(*pruebas)
    return r


def login(rol, usuario_var, clave_var):
    return pedir(f"Iniciar sesión ({rol})", "POST", "/sede/1/api/v2/auth/login", cuerpo=json.dumps({"usuario": "{{%s}}" % usuario_var, "clave": "{{%s}}" % clave_var}),
                 pruebas=["pm.test('200 con token', () => pm.response.to.have.status(200));",
                          f"pm.collectionVariables.set('token_{rol}', pm.response.json().token);"],
                 descripcion="El token sirve en las tres sedes (misma clave de firma). Las claves salen de credenciales/credenciales.json.")


def estado(*validos):
    return [f"pm.test('estado {'/'.join(validos)}', () => pm.expect({list(validos)}).to.include(pm.response.json().estado));"]


col = {
    "info": {"name": "Historia clínica distribuida · pruebas", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
             "description": "Colección de pruebas con los mensajes de ejemplo del parcial (sin modificar), datos sintéticos. Importar también el entorno hc_local. "
                            "El gateway usa una CA de laboratorio (credenciales/ca.crt): agréguela en Ajustes > Certificados o desactive la verificación SSL solo para este entorno local. "
                            "Orden sugerido: 1) iniciar sesión, 2) bus, 3) consultas."},
    "variable": [{"key": "token_%s" % r, "value": ""} for r in ("sede", "medico", "auditor", "admision", "paciente")],
    "item": [
        {"name": "1. Sesión", "item": [login("sede", "usuario_sede", "clave_sede"), login("medico", "usuario_medico", "clave_medico"),
                                        login("auditor", "usuario_auditor", "clave_auditor"), login("admision", "usuario_admision", "clave_admision")]},
        {"name": "2. Bus de integración (HSB)", "item": [
            pedir("HL7 ADT^A01 válido (sede 2) → entregado", "POST", "/hsb/hl7", "sede", EJ("01_adt_a01_valido_sede2.hl7"), "text/plain",
                  estado("entregado", "reintentando", "duplicado"), "Resultado esperado: entregado (Patient 1007, Encounter y Condition CIE-10 J45.9 en la sede 2). Si el HAPI está en frío puede responder reintentando y entregarse solo."),
            pedir("HL7 ORU^R01 laboratorio (sede 1) → entregado", "POST", "/hsb/hl7", "sede", EJ("02_oru_r01_laboratorio_sede1.hl7"), "text/plain",
                  estado("entregado", "reintentando", "duplicado"), "Esperado: Observation LOINC 718-7 = 13,8 g/dL del paciente 1001 en la sede 1."),
            pedir("HL7 inválido → rechazado con 3 motivos", "POST", "/hsb/hl7", "sede", EJ("03_adt_a01_invalido.hl7"), "text/plain",
                  ["pm.test('422 rechazado (o 200 duplicado si ya se envió antes)', () => pm.expect([422, 200]).to.include(pm.response.code));",
                   "if (pm.response.code === 422) pm.test('3 motivos', () => pm.expect(pm.response.json().motivos.length).to.be.at.least(3));"],
                  "Esperado: 422 rechazado con 3 motivos (documento no numérico, sexo no válido, diagnóstico sin CIE-10). Repetirlo responde duplicado."),
            pedir("CSV legado de la sede 3 → 3 entregadas y 2 rechazadas", "POST", "/hsb/csv?sede=3", "sede", EJ("04_sede3_legado.csv"), "text/csv",
                  ["pm.test('200', () => pm.response.to.have.status(200));", "pm.test('5 filas', () => pm.expect(pm.response.json().filas).to.eql(5));"]),
            pedir("Reenviar el ADT → duplicado", "POST", "/hsb/hl7", "sede", EJ("01_adt_a01_valido_sede2.hl7"), "text/plain", estado("duplicado"),
                  "Reenviar el mismo mensaje (mismo MSH-10) no crea otro paciente ni otro encuentro."),
            pedir("Estado de los mensajes", "GET", "/hsb/mensajes?limite=20", "medico", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"]),
            pedir("Resumen del bus (métricas de negocio)", "GET", "/hsb/resumen", "medico", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"]),
            pedir("ConceptMap diagnóstico local → CIE-10", "GET", "/hsb/terminologia/conceptmap", "medico", pruebas=["pm.test('ConceptMap', () => pm.expect(pm.response.json().resourceType).to.eql('ConceptMap'));"]),
        ]},
        {"name": "3. Consultas y trazabilidad", "item": [
            pedir("Historia unificada de 7000001 (3 sedes)", "GET", "/sede/1/api/v2/historia-federada/7000001?cod_tipo_documento=CC", "medico",
                  pruebas=["pm.test('200', () => pm.response.to.have.status(200));"], descripcion="Datos sintéticos: python3 scripts/datos_demo.py"),
            pedir("Reporte de HC de 7000001 (auditor)", "GET", "/sede/1/api/v2/reporte-hc/7000001?cod_tipo_documento=CC", "auditor",
                  pruebas=["pm.test('200', () => pm.response.to.have.status(200));", "pm.test('sello SHA-256', () => pm.expect(pm.response.json().sello_sha256).to.have.length(64));"]),
            pedir("Estado de la plataforma", "GET", "/sede/1/api/v2/estado-plataforma", "auditor", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"]),
            pedir("Verificar la cadena de auditoría", "GET", "/sede/1/api/v2/auditoria/verificar", "auditor",
                  pruebas=["pm.test('cadena íntegra', () => pm.expect(pm.response.json().ok).to.eql(true));"], descripcion="Tras alterar una fila (scripts/prueba_auditoria.sh) devuelve ok=false y el primer evento alterado."),
            pedir("Acceso denegado: el admisionista no ve la historia", "GET", "/sede/1/api/v2/historia-federada/7000001?cod_tipo_documento=CC", "admision",
                  pruebas=["pm.test('403', () => pm.response.to.have.status(403));"]),
            pedir("Sin sesión: 401", "GET", "/sede/1/api/v2/historia-federada/7000001", None, pruebas=["pm.test('401', () => pm.response.to.have.status(401));"]),
        ]},
        {"name": "4. Salud y métricas", "item": [
            pedir("Gateway /health", "GET", "/health", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"]),
            pedir("Gateway /metrics (Prometheus)", "GET", "/metrics", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"], descripcion="En Docker Compose son las métricas del propio gateway (exportador de nginx); en Kubernetes lo atiende una sede cualquiera y Prometheus está en :30090."),
            pedir("Sede 1 /api/health", "GET", "/sede/1/api/health"), pedir("Sede 1 /metrics", "GET", "/sede/1/metrics"),
            pedir("Bus /hsb/health", "GET", "/hsb/health", pruebas=["pm.test('200', () => pm.response.to.have.status(200));"]), pedir("Bus /hsb/metrics", "GET", "/hsb/metrics"),
        ]},
    ],
}
entorno = {"name": "hc_local", "_postman_variable_scope": "environment", "values": [
    {"key": "base_url", "value": "https://localhost:8443", "enabled": True},
    {"key": "usuario_sede", "value": "sede", "enabled": True}, {"key": "usuario_medico", "value": "medico", "enabled": True},
    {"key": "usuario_auditor", "value": "auditor", "enabled": True}, {"key": "usuario_admision", "value": "admision", "enabled": True},
    {"key": "clave_sede", "value": "", "type": "secret", "enabled": True}, {"key": "clave_medico", "value": "", "type": "secret", "enabled": True},
    {"key": "clave_auditor", "value": "", "type": "secret", "enabled": True}, {"key": "clave_admision", "value": "", "type": "secret", "enabled": True}]}
for nombre, datos in (("historia_clinica.postman_collection.json", col), ("hc_local.postman_environment.json", entorno)):
    with open(os.path.join(AQUI, nombre), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
print("escritos:", ", ".join(sorted(n for n in os.listdir(AQUI) if n.endswith(".json"))))
