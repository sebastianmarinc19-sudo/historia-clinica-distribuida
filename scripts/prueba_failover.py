#!/usr/bin/env python3
"""Prueba de tolerancia a fallos de punta a punta (API + réplica + gateway).

Requiere el entorno arriba (al menos pg/api/hapi de Sincelejo y pg/api de
Cartagena y Corozal) y el comando `docker` disponible:

    docker compose -f docker-compose.yml up -d
    python3 scripts/prueba_failover.py

Escenarios sobre Sincelejo (sede 1):
  B  CAÍDA: se detienen su API, su base y su HAPI. Cartagena y Corozal
     siguen sirviendo la historia de Sincelejo desde su réplica, aceptan
     escrituras propias y el gateway sigue respondiendo.
  C  RECUPERACIÓN: Sincelejo vuelve, se pone al día y escribe de inmediato.
  D  AISLAMIENTO: Sincelejo sigue encendida pero sin red hacia las otras
     sedes; atiende pacientes localmente y al reconectar todas convergen.

Solo usa la biblioteca estándar. Sale con código != 0 si algo falla.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "api"))
import sesion  # noqa: E402

S = {1: "http://localhost:8101", 2: "http://localhost:8102", 3: "http://localhost:8103"}
GW = "https://localhost:8443"
RED = "hc-sedes_sedes_net"
RED_AISLADA = "hc_aislada"
RID = int(time.time())
FALLOS = 0


# ------------------------------------------------------------------ utilidades
def http(metodo, url, cuerpo=None, timeout=45):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json", **sesion.cabecera(url)})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=sesion.contexto()) as r:
            return r.status, _cuerpo(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _cuerpo(e.read())
    except Exception as e:                     # sin conexión, timeout...
        return 0, {"error": str(e)}


def _cuerpo(b):
    try:
        return json.loads(b)
    except Exception:
        return {"texto": b.decode(errors="replace")[:200]}


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def esperar(cond, timeout=40, paso=0.5):
    """Devuelve los segundos que tardó en cumplirse, o None si venció el plazo."""
    t0 = time.time()
    while time.time() - t0 <= timeout:
        try:
            if cond():
                return round(time.time() - t0, 1)
        except Exception:
            pass
        time.sleep(paso)
    return None


def ok(msg):
    print(f"  \033[32mPASS\033[0m {msg}")


def fallo(msg):
    global FALLOS
    FALLOS += 1
    print(f"  \033[31mFAIL\033[0m {msg}")


def check(msg, condicion):
    (ok if condicion else fallo)(msg)
    return bool(condicion)


_contador = [0]


def nueva_persona():
    """Persona distinta por llamada: documento, nombre y fecha de nacimiento únicos."""
    _contador[0] += 1
    n = _contador[0]
    return {"cod_tipo_documento": "CC", "numero_documento": f"FO{RID}{n}",
            "primer_nombre": f"Persona{n}x{RID % 1000}", "primer_apellido": "Failover",
            "fecha_hora_nacimiento": (date(1930, 1, 1) + timedelta(days=(RID + 37 * n) % 25000)).isoformat() + "T08:00:00",
            "cod_sexo": "M", "cod_pais_residencia": "COL", "cod_municipio_residencia": "70001"}


def registrar(sede, persona=None, reintentos=1):
    persona = persona or nueva_persona()
    for _ in range(reintentos):
        st, cuerpo = http("POST", f"{S[sede]}/api/v2/pacientes", persona)
        if st in (200, 201):
            return persona, cuerpo["paciente"]["id_paciente"]
        time.sleep(2)
    return persona, None


def existe(sede, doc):
    st, c = http("GET", f"{S[sede]}/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento={doc}", timeout=15)
    return st == 200 and c["total"] >= 1


def abrir_encuentro(sede, id_paciente):
    st, c = http("POST", f"{S[sede]}/api/v2/encuentros", {
        "id_paciente": id_paciente, "fecha_hora_inicio": "2026-03-15T08:30:00", "cod_modalidad": "01",
        "cod_grupo_servicio": "01", "cod_entorno": "01", "cod_via_ingreso": "01",
        "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
    return c["encuentro"]["id_encuentro"] if st == 201 else None


def sede_sana(sede):
    st, c = http("GET", f"{S[sede]}/api/health", timeout=5)
    return st == 200 and c.get("db") == "ok"


def reiniciar_gateway():
    docker("restart", "hc_gateway")
    esperar(lambda: http("GET", f"{GW}/api/v2/sede", timeout=5)[0] == 200, 30)


# ------------------------------------------------------------------ preparación
print(f"== Prueba de failover (corrida {RID}) ==")
print("A   Preparación: historia clínica completa y migrada a FHIR en Sincelejo")
sanas = {s: sede_sana(s) for s in (1, 2, 3)}
if not all(sanas.values()):
    print(f"  Las tres sedes deben estar sanas antes de empezar: {sanas}")
    sys.exit(2)

persona_a, pac_a = registrar(1)
DOC_A = persona_a["numero_documento"]
st, prof = http("POST", f"{S[1]}/api/v2/profesionales", {
    "cod_tipo_documento": "CC", "numero_documento": f"P{DOC_A}", "nombres": "Medico", "apellidos": "Prueba"})
enc_a = abrir_encuentro(1, pac_a)
base = f"{S[1]}/api/v2/encuentros/{enc_a}"
http("POST", f"{base}/diagnosticos", {"cod_cie10": "J00", "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-03-15"})
http("POST", f"{base}/observaciones", {"cod_loinc": "8310-5", "valor_numerico": 38.5, "cod_unidad": "C",
                                       "fecha_hora_medicion": "2026-03-15T09:10:00"})
http("POST", f"{base}/egreso", {"fecha_hora_fin": "2026-03-15T09:30:00", "cod_condicion_egreso": "01",
                                "id_profesional_egreso": prof["profesional"]["id_profesional"]})
st, mig = http("POST", f"{S[1]}/api/v2/migracion/encuentro/{enc_a}", timeout=120)
check("RDA generado y migrado al HAPI de Sincelejo", st == 200 and mig.get("estado_migracion") == "MIGRADO")


def bundle_en(sede):
    st, c = http("GET", f"{S[sede]}/api/v2/bundles/{enc_a}?completo=true", timeout=15)
    return st == 200 and c["bundle"]["type"] == "document"


for s in (2, 3):
    t = esperar(lambda s=s: bundle_en(s))
    check(f"el RDA ya está replicado en la sede {s}" + (f" ({t}s)" if t is not None else ""), t is not None)

# ------------------------------------------------------------------ B. caída
print("B   CAÍDA de Sincelejo (API + base + HAPI detenidos)")
t_caida = time.time()
docker("stop", "api_sincelejo", "pg_sincelejo", "hapi_sincelejo")
check("Sincelejo ya no responde", not sede_sana(1))

for s in (2, 3):
    st, h = http("GET", f"{S[s]}/api/v2/historia-federada/{DOC_A}?cod_tipo_documento=CC")
    enc = next((e for e in h.get("encuentros", []) if e["id_encuentro"] == enc_a), None) if st == 200 else None
    check(f"la sede {s} sirve la historia de Sincelejo desde su réplica (es_replica=True)",
          enc is not None and enc["es_replica"] is True and enc["sede_nombre"] == "Sincelejo")
    check(f"la sede {s} sirve el RDA de Sincelejo (Composition primero)", bundle_en(s))

resp = [http("GET", f"{GW}/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento={DOC_A}", timeout=30)[0]
        for _ in range(10)]
check(f"el gateway sigue respondiendo lecturas con Sincelejo caída ({resp.count(200)}/10 con 200)",
      resp.count(200) == 10)
check("el gateway indica que Sincelejo no está disponible (/sede/1)",
      http("GET", f"{GW}/sede/1/api/health", timeout=30)[0] in (502, 503, 504))

persona_b, pac_b = registrar(2)
persona_c, pac_c = registrar(3)
check("Cartagena y Corozal aceptan escrituras con Sincelejo caída", pac_b and pac_c)
check("Cartagena abre un encuentro propio", abrir_encuentro(2, pac_b) is not None)
for s, doc in ((3, persona_b["numero_documento"]), (2, persona_c["numero_documento"])):
    t = esperar(lambda s=s, doc=doc: existe(s, doc))
    check(f"los pacientes se replican entre Cartagena y Corozal sin Sincelejo (sede {s} ve {doc[-6:]})", t is not None)

st, c = http("POST", f"{S[2]}/api/v2/encuentros", {
    "id_paciente": pac_a, "fecha_hora_inicio": "2026-03-16T08:30:00", "cod_modalidad": "01",
    "cod_grupo_servicio": "01", "cod_entorno": "01", "cod_via_ingreso": "01",
    "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
check("los registros de Sincelejo son de solo lectura en otras sedes mientras está caída (409 con la dueña)",
      st == 409 and c.get("sede_propietaria") == 1)

# ------------------------------------------------------------ C. recuperación
print("C   RECUPERACIÓN de Sincelejo")
t_inicio = time.time()
docker("start", "pg_sincelejo", "hapi_sincelejo", "api_sincelejo")
rto = esperar(lambda: sede_sana(1), 120)
check(f"Sincelejo vuelve a atender (RTO de la sede: {rto}s)" if rto is not None else "Sincelejo no volvió en 120 s",
      rto is not None)
for doc, quien in ((persona_b["numero_documento"], "Cartagena"), (persona_c["numero_documento"], "Corozal")):
    t = esperar(lambda doc=doc: existe(1, doc))
    check(f"Sincelejo se puso al día con lo que se registró en {quien} mientras estaba caída" +
          (f" ({t}s tras volver)" if t is not None else ""), t is not None)
persona_d, pac_d = registrar(1, reintentos=10)
check("Sincelejo escribe de inmediato tras recuperarse", pac_d is not None)
for s in (2, 3):
    t = esperar(lambda s=s: existe(s, persona_d["numero_documento"]))
    check(f"la escritura de Sincelejo llega a la sede {s}", t is not None)
reiniciar_gateway()
check("el gateway vuelve a enrutar a Sincelejo (/sede/1)",
      esperar(lambda: http("GET", f"{GW}/sede/1/api/health", timeout=10)[0] == 200, 30) is not None)
print(f"    (tiempo total de la caída hasta estar de nuevo operativa: {round(time.time() - t_caida)}s)")

# ----------------------------------------------------------- D. aislamiento
print("D   AISLAMIENTO de Sincelejo (viva, sin red hacia las otras sedes)")
docker("network", "rm", RED_AISLADA)                      # por si quedó de una corrida anterior
docker("network", "create", RED_AISLADA)
for c_ in ("pg_sincelejo", "api_sincelejo"):
    docker("network", "connect", RED_AISLADA, c_)
for c_ in ("pg_sincelejo", "api_sincelejo"):
    docker("network", "disconnect", RED, c_)

persona_e, pac_e = registrar(1, reintentos=15)             # reintenta: el pool se reconecta solo
check("Sincelejo aislada sigue registrando pacientes en su base local", pac_e is not None)
persona_f, pac_f = registrar(2)
check("Cartagena sigue operando mientras Sincelejo está aislada", pac_f is not None)
enc_e = abrir_encuentro(1, pac_e) if pac_e else None
check("Sincelejo aislada también abre encuentros", enc_e is not None)

print("    (15 s de partición para superar los timeouts de replicación...)")
time.sleep(15)
check("Cartagena NO ve lo registrado en la Sincelejo aislada (hay partición real)",
      not existe(2, persona_e["numero_documento"]))
check("Sincelejo aislada NO ve lo registrado en Cartagena",
      not existe(1, persona_f["numero_documento"]))

t_heal = time.time()
for c_ in ("pg_sincelejo", "api_sincelejo"):
    docker("network", "connect", RED, c_)
for c_ in ("pg_sincelejo", "api_sincelejo"):
    docker("network", "disconnect", RED_AISLADA, c_)
docker("network", "rm", RED_AISLADA)

for s, doc, que in ((2, persona_e["numero_documento"], "lo de Sincelejo"), (3, persona_e["numero_documento"], "lo de Sincelejo"),
                    (1, persona_f["numero_documento"], "lo de Cartagena")):
    t = esperar(lambda s=s, doc=doc: existe(s, doc), 90)
    check(f"al reconectar, la sede {s} recibe {que}" + (f" ({round(time.time() - t_heal, 1)}s tras reconectar)" if t is not None else ""),
          t is not None)
t = esperar(lambda: http("GET", f"{S[2]}/api/v2/encuentros/{enc_e}", timeout=10)[0] == 200, 60)
check("el encuentro creado durante el aislamiento también converge en Cartagena", t is not None)
reiniciar_gateway()
check("el gateway enruta a las tres sedes tras la reconexión",
      all(http("GET", f"{GW}/sede/{s}/api/health", timeout=15)[0] == 200 for s in (1, 2, 3)))

print()
if FALLOS == 0:
    print("\033[32mTodas las pruebas de failover pasaron.\033[0m")
else:
    print(f"\033[31m{FALLOS} prueba(s) fallaron.\033[0m")
sys.exit(1 if FALLOS else 0)
