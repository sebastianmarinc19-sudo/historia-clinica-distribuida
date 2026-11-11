#!/usr/bin/env python3
"""Escenario de trazabilidad: llena los 57 campos de la Resolución 866 y verifica 57/57.

Registra UN paciente y UN encuentro **sintéticos** con todos los datos que el modelo
captura (identificación, contacto con el servicio, tecnologías en salud y resultados),
a través de la API v2 de una sede. Después pide la auditoría (CU-15) restringida a ese
lote, primero a la sede que escribió y luego a las demás, que la leen de su réplica.

Los valores NO pretenden coherencia clínica (por ejemplo, el encuentro tiene a la vez
causa básica de muerte, remisión, incapacidad y licencia de maternidad): el objetivo es
que cada campo tenga un dato para comprobar su trazabilidad de punta a punta.

Uso:
    python3 tests/api/escenario_57_campos.py http://IP:30101 http://IP:30102 http://IP:30103
    (la primera URL es la sede que escribe; las demás solo leen). Solo biblioteca estándar.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sesion  # noqa: E402


def http(metodo, url, cuerpo=None, timeout=60):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo, headers={"Content-Type": "application/json", **sesion.cabecera(url)})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=sesion.contexto()) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def _ok(paso, respuesta, esperados=(200, 201)):
    estado, cuerpo = respuesta
    if estado not in esperados:
        raise RuntimeError(f"{paso}: HTTP {estado} {json.dumps(cuerpo, ensure_ascii=False)[:300]}")
    return cuerpo


def registrar_caso(url, marca=None):
    """Registra el caso completo en la sede de `url`. Devuelve (lote, id_sede, id_encuentro)."""
    marca = marca or str(int(time.time()))
    doc = f"DEMO57{marca}"[:20]                       # el lote auditado es este documento
    sede = _ok("sede", http("GET", f"{url}/api/v2/sede"))["sede_local"]

    _ok("paciente", http("POST", f"{url}/api/v2/pacientes", {
        "cod_tipo_documento": "CC", "numero_documento": doc,                                  # 2, 3
        "primer_nombre": "Valeria", "segundo_nombre": "Isabel",                               # 6, 7
        "primer_apellido": "Demostracion", "segundo_apellido": "Cincuentaisiete",             # 4, 5
        "fecha_hora_nacimiento": "1990-05-15T06:45:00", "cod_sexo": "F",                      # 8, 9
        "cod_identidad_genero": "02", "cod_pais_nacionalidad": "COL",                         # 10, 1
        "oposicion_donacion": False, "tiene_voluntad_anticipada": True,                       # 12, 13
        "cod_categoria_discapacidad": "01",                                                   # 14
        "cod_pais_residencia": "COL", "cod_municipio_residencia": "70001",                    # 15, 16
        "cod_etnia": "01", "cod_comunidad_etnica": "0101", "cod_zona_territorial": "1"}))     # 17, 18, 19
    paciente = _ok("buscar paciente", http("GET", f"{url}/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento={doc}"))["pacientes"][0]

    prof = _ok("profesional", http("POST", f"{url}/api/v2/profesionales", {
        "cod_tipo_documento": "CC", "numero_documento": f"P{marca}"[:20], "nombres": "Camila", "apellidos": "Restrepo"}))["profesional"]

    enc = _ok("encuentro", http("POST", f"{url}/api/v2/encuentros", {
        "id_paciente": paciente["id_paciente"], "fecha_hora_inicio": "2026-05-10T08:00:00",   # 22
        "cod_modalidad": "01", "cod_grupo_servicio": "05", "cod_entorno": "01",               # 23, 24, 25
        "cod_via_ingreso": "01", "cod_causa_atencion": "01",                                  # 26, 27
        "cod_ocupacion": "221000", "cod_entidad_responsable": "EPS001"}))["encuentro"]        # 11, 20 (21 = sede)
    base = f"{url}/api/v2/encuentros/{enc['id_encuentro']}"

    _ok("triage", http("POST", f"{base}/triage", {"fecha_hora_triage": "2026-05-10T08:05:00", "cod_triage": 2}))   # 28, 29
    for cie, rol in (("J00", "IN"), ("J18.9", "EP"), ("R50.9", "RE"), ("E11.9", "CO"), ("I10", "CM")):             # 30, 44, 45, 47, 49
        _ok(f"diagnóstico {rol}", http("POST", f"{base}/diagnosticos", {"cod_cie10": cie, "cod_tipo_diagnostico": rol, "fecha_diagnostico": "2026-05-10"}))
    tec = _ok("tecnología", http("POST", f"{base}/tecnologias", {                                                  # 31, 32, 34
        "cod_tecnologia": "19938", "cod_finalidad": "02", "fecha_prescripcion": "2026-05-10T08:30:00",
        "medicamento": {"cod_medicamento": "19938", "dosis_prescrita": 500, "cod_unidad_dosis": "mg",             # 33, 35
                        "cod_via_administracion": "01", "duracion_tratamiento": 5, "cod_unidad_duracion": "d",     # 36, 37
                        "frecuencia_valor": 8, "cod_unidad_frecuencia": "h"}}))["tecnologia"]                      # 38
    _ok("entrega", http("POST", f"{base}/entregas", {                                                              # 39 a 43
        "id_tecnologia_encuentro": tec["id_tecnologia_encuentro"], "id_profesional": prof["id_profesional"],
        "fecha_entrega": "2026-05-10T09:00:00", "dosis_administrada": 500, "dosis_entregada": 500,
        "cod_unidad_dosis": "mg", "unidades_entregadas": 2}))
    _ok("observación", http("POST", f"{base}/observaciones", {                                                     # 46
        "cod_loinc": "8310-5", "valor_numerico": 38.5, "cod_unidad": "C", "fecha_hora_medicion": "2026-05-10T09:10:00"}))
    _ok("antecedente", http("POST", f"{base}/antecedentes", {"cod_cie10": "I10", "descripcion": "Hipertensión diagnosticada hace 3 años"}))   # 54
    _ok("exposición", http("POST", f"{base}/exposiciones", {"cod_factor_riesgo": "004"}))                          # 55
    _ok("egreso", http("POST", f"{base}/egreso", {                                                                 # 48, 50, 51, 52, 53, 56, 57
        "fecha_hora_fin": "2026-05-10T10:00:00", "cod_condicion_egreso": "03", "cod_prestador_referencia": "130010000001",
        "id_profesional_egreso": prof["id_profesional"], "dias_incapacidad": 5, "dias_licencia_maternidad": 84}))
    return doc, sede, enc["id_encuentro"]


def auditar(url, id_sede, lote):
    estado, cuerpo = http("GET", f"{url}/api/v2/auditoria/57-campos?id_sede={id_sede}&lote={lote}")
    if estado != 200:
        return None
    s = cuerpo["sedes"][0]
    return {"resumen": s["resumen"], "pendientes": [c["campo"] for c in s["campos"] if c["estado"] != "completo"]}


def ejecutar(url_escritura, urls_lectura=(), espera_s=45, marca=None):
    lote, sede, id_encuentro = registrar_caso(url_escritura, marca)
    resultados = {}
    for url in (url_escritura, *urls_lectura):
        limite = time.time() + espera_s
        r = auditar(url, sede, lote)
        while (r is None or r["resumen"]["completo"] != 57) and time.time() < limite:
            time.sleep(0.5)
            r = auditar(url, sede, lote)
        resultados[url] = r
    return {"lote": lote, "id_sede": sede, "id_encuentro": id_encuentro, "resultados": resultados,
            "completos_en_todas": all(r and r["resumen"]["completo"] == 57 for r in resultados.values())}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    informe = ejecutar(sys.argv[1], sys.argv[2:])
    print(f"Lote auditado: {informe['lote']} (sede {informe['id_sede']})")
    for url, r in informe["resultados"].items():
        print(f"  {url}: {r['resumen'] if r else 'sin respuesta'}" + (f" · incompletos: {r['pendientes']}" if r and r["pendientes"] else ""))
    sys.exit(0 if informe["completos_en_todas"] else 1)
