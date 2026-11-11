#!/usr/bin/env python3
"""Experimentos SRE sobre el despliegue en Minikube: caos, RTO/RPO, SLO y carga.

Requiere el entorno desplegado (scripts/k8s_desplegar.sh) y `kubectl` y
`minikube` en el PATH. Solo usa la biblioteca estándar.

    python3 scripts/sre_k8s.py                 # todos los experimentos
    python3 scripts/sre_k8s.py api rpo         # solo algunos
    Experimentos: api, gateway, rpo, particion, latencia, carga, reconstruccion

Los resultados se imprimen y se guardan en docs/resultados_sre.json.
Los objetivos (SLO) son propuestas del proyecto, no una norma:
  - lectura vía gateway con una sede caída      >= 99,9 % disponible (cientos de muestras)
  - falla en seco de un pod de API              ventana de fallos <= 2 s en acceso directo; 0 pérdidas vía gateway
  - falla en seco de un pod del gateway         ventana de fallos <= 2 s
    (un porcentaje sobre ~100 muestras no es verificable: 1 petición = 1 %; mientras
     kube-proxy retira el endpoint muerto se pierden unas pocas peticiones)
  - RTO de una sede tras caer su base de datos  <= 60 s
  - retraso de réplica entre sedes (p95)        <= 2 s
  - RPO si la sede reinicia con su disco        = 0 escrituras perdidas
  - reconstrucción de una sede con disco vacío  <= 180 s y datos idénticos a los de sus pares
"""
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "api"))
import sesion  # noqa: E402

RID = int(time.time())


def sh(*args, entrada=None):
    return subprocess.run(args, capture_output=True, text=True, input=entrada)


IP = sh("minikube", "ip").stdout.strip()
NS = {1: "sede-sincelejo", 2: "sede-cartagena", 3: "sede-corozal"}
API = {1: f"http://{IP}:30101", 2: f"http://{IP}:30102", 3: f"http://{IP}:30103"}
GW = f"https://{IP}:30443"
PROM = f"http://{IP}:30090"
RESULTADOS: dict = {"corrida": RID, "objetivos": {}, "experimentos": {}}


# ------------------------------------------------------------------ utilidades
def http(metodo, url, cuerpo=None, timeout=30):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json", **sesion.cabecera(url)})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=sesion.contexto()) as r:
            return r.status, _json(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read())
    except Exception as e:
        return 0, {"error": str(e)}


def _json(b):
    try:
        return json.loads(b)
    except Exception:
        return {"texto": b.decode(errors="replace")[:200]}


def kubectl(*args):
    return sh("kubectl", *args)


def esperar(cond, timeout=60, paso=0.25):
    t0 = time.time()
    while time.time() - t0 <= timeout:
        try:
            if cond():
                return round(time.time() - t0, 2)
        except Exception:
            pass
        time.sleep(paso)
    return None


def pct(valores, p):
    if not valores:
        return None
    v = sorted(valores)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 1)


def persona(prefijo, n):
    return {"cod_tipo_documento": "CC", "numero_documento": f"{prefijo}{n}",
            "primer_nombre": f"{prefijo}n{n}", "primer_apellido": "Sre",
            "fecha_hora_nacimiento": (date(1930, 1, 1) + timedelta(days=(RID * 7 + n * 13) % 25000)).isoformat() + "T08:00:00",
            "cod_sexo": "F", "cod_pais_residencia": "COL"}


def prom(consulta):
    st, c = http("GET", f"{PROM}/api/v1/query?query={urllib.parse.quote(consulta)}", timeout=10)
    return c.get("data", {}).get("result", []) if st == 200 else []


def pacientes_de(sede_obs, sede_origen):
    """Cuántos pacientes de `sede_origen` ve la sede `sede_obs` (réplica incluida)."""
    st, c = http("GET", f"{API[sede_obs]}/api/v2/cobertura", timeout=10)
    if st != 200:
        return None
    return next(s["pacientes"] for s in c["sedes"] if s["id_sede"] == sede_origen)


def titulo(txt):
    print(f"\n== {txt}")


def linea(txt):
    print(f"   {txt}")


def veredicto(nombre, ok_, detalle):
    marca = "\033[32mCUMPLE\033[0m" if ok_ else "\033[31mNO CUMPLE\033[0m"
    print(f"   [{marca}] {nombre}: {detalle}")
    return bool(ok_)


class Sonda(threading.Thread):
    """Sondea una URL cada `intervalo` s y guarda (instante, ok, ms)."""

    def __init__(self, url, intervalo=0.1):
        super().__init__(daemon=True)
        self.url, self.intervalo = url, intervalo
        self.muestras = []
        self.codigos = {}                       # código HTTP -> cuántas veces (0 = sin conexión o timeout)
        self.errores_0 = []
        self._parar = threading.Event()

    def run(self):
        while not self._parar.is_set():
            t0 = time.time()
            st, cuerpo = http("GET", self.url, timeout=3)
            self.muestras.append((t0, st == 200, (time.time() - t0) * 1000))
            if st != 200:
                self.codigos[st] = self.codigos.get(st, 0) + 1
                if st == 0:
                    self.errores_0.append((round(time.time() - t0, 2), str(cuerpo.get('error'))[:120]))
            time.sleep(max(0, self.intervalo - (time.time() - t0)))

    def detener(self):
        self._parar.set()
        self.join(timeout=5)
        return self.resumen()

    def resumen(self):
        m = self.muestras
        fallidas = [x for x in m if not x[1]]
        racha = mejor = 0
        for _, ok_, _ in m:
            racha = 0 if ok_ else racha + 1
            mejor = max(mejor, racha)
        return {"peticiones": len(m), "fallidas": len(fallidas),
                "disponibilidad_pct": round(100 * (1 - len(fallidas) / len(m)), 3) if m else None,
                "max_fallos_seguidos": mejor, "codigos_fallidos": dict(self.codigos), "errores_sin_codigo": self.errores_0[:5],
                "segundos_con_fallos": round(fallidas[-1][0] - fallidas[0][0], 1) if fallidas else 0.0,
                "latencia_p95_ms": pct([x[2] for x in m if x[1]], 95)}


class Escritor(threading.Thread):
    """Registra pacientes en una sede a ritmo fijo y anota los que se confirmaron."""

    def __init__(self, sede, prefijo, tasa=5):
        super().__init__(daemon=True)
        self.sede, self.prefijo, self.tasa = sede, prefijo, tasa
        self.acks, self.errores = [], []
        self._parar = threading.Event()

    def run(self):
        n = 0
        while not self._parar.is_set():
            t0 = time.time()
            n += 1
            st, _ = http("POST", f"{API[self.sede]}/api/v2/pacientes", persona(self.prefijo, n), timeout=5)
            (self.acks if st == 201 else self.errores).append((t0, n, st))
            time.sleep(max(0, 1 / self.tasa - (time.time() - t0)))

    def detener(self):
        self._parar.set()
        self.join(timeout=10)


def esperar_sedes_sanas(timeout=120):
    def listo():
        return all(http("GET", f"{API[s]}/api/health", timeout=4)[0] == 200 for s in (1, 2, 3))
    return esperar(listo, timeout, 1)


# ---------------------------------------------------------------- experimentos
def exp_api():
    """Mata un pod de la API de Sincelejo (2 réplicas), con y sin gateway delante."""
    titulo("E1  Muere un pod de la API (Sincelejo tiene 2 réplicas)")
    directa = Sonda(f"{API[1]}/api/v2/sede")        # sin reintentos: lo que vería un cliente directo
    via_gw = Sonda(f"{GW}/api/v2/sede")             # el gateway reintenta en otra sede las lecturas fallidas
    directa.start(); via_gw.start()
    time.sleep(5)
    pods = kubectl("-n", NS[1], "get", "pods", "-l", "app=api", "-o", "jsonpath={.items[*].metadata.name}").stdout.split()
    kubectl("-n", NS[1], "delete", "pod", pods[0], "--grace-period=0", "--force", "--wait=false")
    t_listo = esperar(lambda: kubectl("-n", NS[1], "get", "deploy/api", "-o", "jsonpath={.status.readyReplicas}").stdout == "2", 90, 0.5)
    time.sleep(8)
    rd, rg = directa.detener(), via_gw.detener()
    r = {"pod_eliminado": pods[0], "segundos_hasta_2_replicas_listas": t_listo, "acceso_directo": rd, "via_gateway": rg}
    RESULTADOS["experimentos"]["api"] = r
    linea(f"acceso directo (sin reintentos): {rd['peticiones']} peticiones, {rd['fallidas']} fallidas, ventana de fallos "
          f"{rd['segundos_con_fallos']} s; el pod de reemplazo estuvo listo en {t_listo}s")
    linea(f"vía gateway: {rg['peticiones']} peticiones, {rg['fallidas']} fallidas")
    RESULTADOS["objetivos"]["api_pod_en_seco_directo"] = veredicto(
        "pod de API (acceso directo)", rd["segundos_con_fallos"] <= 2,
        f"{rd['fallidas']} peticiones perdidas en una ventana de {rd['segundos_con_fallos']} s (objetivo ≤ 2 s)")
    RESULTADOS["objetivos"]["api_pod_en_seco_gateway"] = veredicto(
        "pod de API (vía gateway)", rg["fallidas"] == 0, f"{rg['fallidas']} peticiones perdidas")


def exp_gateway():
    """Mata un pod del gateway (2 réplicas)."""
    titulo("E2  Muere un pod del gateway (2 réplicas)")
    sonda = Sonda(f"{GW}/api/v2/sede")
    sonda.start()
    time.sleep(5)
    pods = kubectl("-n", "hc-gateway", "get", "pods", "-l", "app=gateway", "-o", "jsonpath={.items[*].metadata.name}").stdout.split()
    kubectl("-n", "hc-gateway", "delete", "pod", pods[0], "--grace-period=0", "--force", "--wait=false")
    esperar(lambda: kubectl("-n", "hc-gateway", "get", "deploy/gateway", "-o", "jsonpath={.status.readyReplicas}").stdout == "2", 90, 0.5)
    time.sleep(8)
    r = sonda.detener()
    RESULTADOS["experimentos"]["gateway"] = r
    linea(f"{r['peticiones']} peticiones, {r['fallidas']} fallidas, disponibilidad {r['disponibilidad_pct']} %, "
          f"ventana de fallos {r['segundos_con_fallos']} s")
    RESULTADOS["objetivos"]["gateway_pod_en_seco"] = veredicto(
        "gateway (pod muerto en seco)", r["segundos_con_fallos"] <= 2,
        f"{r['fallidas']} peticiones perdidas, ventana de {r['segundos_con_fallos']} s (objetivo ≤ 2 s)")


def exp_rpo():
    """Mata la base de Sincelejo en seco mientras se escribe: mide RTO y RPO."""
    titulo("E3  Cae la base de datos de Sincelejo mientras se escribe (RTO y RPO)")
    prefijo = f"Rpo{RID % 10000}x"
    base1 = pacientes_de(1, 1)
    base2 = pacientes_de(2, 1)
    base3 = pacientes_de(3, 1)
    sonda_gw = Sonda(f"{GW}/api/v2/pacientes/buscar?nombre=zzz-no-existe-zzz&numero_documento=0")
    sonda_s1 = Sonda(f"{API[1]}/api/health")
    escritor = Escritor(1, prefijo, tasa=6)
    sonda_gw.start(); sonda_s1.start(); escritor.start()
    time.sleep(10)                                     # régimen estable

    t_kill = time.time()
    kubectl("-n", NS[1], "delete", "pod", "pg-0", "--grace-period=0", "--force", "--wait=false")
    time.sleep(2)                                      # la réplica ya no recibe nada de Sincelejo
    vistos2 = (pacientes_de(2, 1) or 0) - (base2 or 0)
    vistos3 = (pacientes_de(3, 1) or 0) - (base3 or 0)
    # Escritorio de Cartagena sigue operando mientras Sincelejo está caída.
    st_c, _ = http("POST", f"{API[2]}/api/v2/pacientes", persona(f"Rpo{RID % 10000}c", 1))

    ok_vuelve = esperar(lambda: http("GET", f"{API[1]}/api/health", timeout=3)[0] == 200, 180, 0.5)
    rto = round(time.time() - t_kill, 1) if ok_vuelve is not None else None   # desde que se mata el pod
    time.sleep(3)
    escritor.detener()
    acks = len(escritor.acks)

    # ¿Cuántas escrituras confirmadas no habían llegado a las otras sedes al caer?
    confirmadas_al_kill = sum(1 for t, _, _ in escritor.acks if t <= t_kill)
    expuestas2 = max(0, confirmadas_al_kill - vistos2)
    expuestas3 = max(0, confirmadas_al_kill - vistos3)

    # Tras volver: ¿todo lo confirmado existe en Sincelejo y llega a las demás?
    en_s1 = (pacientes_de(1, 1) or 0) - (base1 or 0)           # lo confirmado que sobrevivió en Sincelejo
    # Convergencia: las réplicas igualan lo que Sincelejo tiene en su base. (No se compara con `acks`:
    # una escritura cuyo cliente vio un error pudo haberse confirmado en el servidor.)
    conv = esperar(lambda: all((pacientes_de(s, 1) or 0) == (pacientes_de(1, 1) or 0) for s in (2, 3)), 120, 0.5)
    sonda_gw_r, sonda_s1_r = sonda_gw.detener(), sonda_s1.detener()

    r = {"escrituras_confirmadas": acks, "escrituras_rechazadas_durante_la_caida": len(escritor.errores),
         "confirmadas_antes_de_caer": confirmadas_al_kill,
         "expuestas_sin_replicar_en_cartagena": expuestas2, "expuestas_sin_replicar_en_corozal": expuestas3,
         "ventana_rpo_estimada_s": round(max(expuestas2, expuestas3) / 6, 2),
         "perdidas_tras_reiniciar": max(0, acks - en_s1),
         "confirmadas_en_servidor_sin_ack_al_cliente": max(0, en_s1 - acks), "rto_base_sede_s": rto,
         "segundos_hasta_convergencia_total": conv, "gateway": sonda_gw_r, "sede_1": sonda_s1_r,
         "cartagena_acepta_escrituras_con_sincelejo_caida": st_c == 201}
    RESULTADOS["experimentos"]["rpo"] = r
    linea(f"RTO de la base de Sincelejo: {rto}s; {r['escrituras_rechazadas_durante_la_caida']} escrituras rechazadas durante la caída")
    linea(f"RPO si el disco se hubiera perdido: {max(expuestas2, expuestas3)} escrituras sin replicar "
          f"(≈ {r['ventana_rpo_estimada_s']} s de datos) de {confirmadas_al_kill} confirmadas")
    linea(f"Gateway durante la caída: {sonda_gw_r['disponibilidad_pct']} % disponible "
          f"({sonda_gw_r['fallidas']} fallidas de {sonda_gw_r['peticiones']})")
    linea(f"Tras reiniciar: todo converge en {conv}s")
    RESULTADOS["objetivos"]["rto_sede"] = veredicto("RTO de sede", rto is not None and rto <= 60, f"{rto}s (objetivo ≤ 60 s)")
    RESULTADOS["objetivos"]["lectura_gateway_en_caida"] = veredicto(
        "lectura vía gateway", sonda_gw_r["disponibilidad_pct"] >= 99.9, f"{sonda_gw_r['disponibilidad_pct']} % (objetivo ≥ 99,9 %)")
    RESULTADOS["objetivos"]["rpo_con_disco"] = veredicto(
        "RPO reiniciando con su disco", conv is not None and r["perdidas_tras_reiniciar"] == 0,
        f"{r['perdidas_tras_reiniciar']} escrituras perdidas")


def _suscripciones(sede, accion):
    """Habilita o deshabilita las suscripciones de una sede (DISABLE / ENABLE)."""
    subs =sh("kubectl", "-n", NS[sede], "exec", "pg-0", "--", "psql", "-U", "admin", "-d", "historia_clinica",
              "-Atc", "SELECT subname FROM pg_subscription").stdout.split()
    for sub in subs:
        kubectl("-n", NS[sede], "exec", "pg-0", "--", "psql", "-U", "admin", "-d", "historia_clinica",
                "-c", f"ALTER SUBSCRIPTION {sub} {accion}")


def exp_particion():
    """Parte Sincelejo del resto (ambos sentidos) con las dos sedes escribiendo."""
    titulo("E4  Partición: Sincelejo queda aislada de las otras sedes y todas siguen escribiendo")
    prefijo = f"Par{RID % 10000}x"
    base = {(o, v): pacientes_de(v, o) for o in (1, 2) for v in (1, 2, 3)}
    # Sin salida: quitar el selector del Service que usan los pares. Sin entrada: deshabilitar sus suscripciones.
    kubectl("-n", NS[1], "patch", "svc", "pg", "-p", '{"spec":{"selector":{"app":"aislada"}}}')
    _suscripciones(1, "DISABLE")
    # El cambio de Service no corta las conexiones de réplica ya abiertas (conntrack): se cierran los walsenders.
    kubectl("-n", NS[1], "exec", "pg-0", "--", "psql", "-U", "admin", "-d", "historia_clinica", "-Atc",
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_replication")
    n_a = n_b = 0
    for i in range(1, 9):
        if http("POST", f"{API[1]}/api/v2/pacientes", persona(prefijo + "a", i))[0] == 201: n_a += 1
        if http("POST", f"{API[2]}/api/v2/pacientes", persona(prefijo + "b", i))[0] == 201: n_b += 1
    linea(f"durante la partición: Sincelejo confirmó {n_a}/8 escrituras y Cartagena {n_b}/8")
    time.sleep(15)
    ve_1_de_2 = (pacientes_de(1, 2) or 0) - (base[(2, 1)] or 0)
    ve_2_de_1 = (pacientes_de(2, 1) or 0) - (base[(1, 2)] or 0)
    ve_3_de_1 = (pacientes_de(3, 1) or 0) - (base[(1, 3)] or 0)
    ve_3_de_2 = (pacientes_de(3, 2) or 0) - (base[(2, 3)] or 0)
    linea(f"Cartagena ve {ve_2_de_1} de las escrituras de Sincelejo; Sincelejo ve {ve_1_de_2} de las de Cartagena; "
          f"Corozal ve {ve_3_de_2} de Cartagena (esperado {n_b}) y {ve_3_de_1} de Sincelejo (esperado 0)")

    lag = prom('max(hc_replication_slot_lag_bytes{sede="1"})')
    lag_bytes = float(lag[0]["value"][1]) if lag else None

    kubectl("-n", NS[1], "patch", "svc", "pg", "-p", '{"spec":{"selector":{"app":"pg"}}}')
    _suscripciones(1, "ENABLE")
    conv = esperar(lambda: all(
        (pacientes_de(2, 1) or 0) - (base[(1, 2)] or 0) == n_a and
        (pacientes_de(3, 1) or 0) - (base[(1, 3)] or 0) == n_a and
        (pacientes_de(1, 2) or 0) - (base[(2, 1)] or 0) == n_b for _ in (0,)), 120, 0.5)
    r = {"escrituras_sincelejo": n_a, "escrituras_cartagena": n_b,
         "particion_real": ve_2_de_1 == 0 and ve_1_de_2 == 0, "corozal_sigue_recibiendo_de_cartagena": ve_3_de_2 == n_b,
         "lag_slots_sincelejo_bytes_durante_particion": lag_bytes, "segundos_hasta_convergencia": conv}
    RESULTADOS["experimentos"]["particion"] = r
    linea(f"WAL pendiente en los slots de Sincelejo durante la partición: {lag_bytes} bytes")
    linea(f"Al sanar la partición todas convergen en {conv}s")
    veredicto("partición real (sin fugas)", r["particion_real"], "Cartagena no ve a Sincelejo y viceversa")
    veredicto("escritura durante la partición", n_a == 8 and n_b == 8, f"{n_a}/8 y {n_b}/8 confirmadas")
    RESULTADOS["objetivos"]["particion_converge"] = veredicto("convergencia tras la partición", conv is not None,
                                                              f"{conv}s")


def exp_latencia(muestras=40):
    """Retraso de réplica: tiempo desde que se confirma una escritura hasta que otra sede la ve."""
    titulo(f"E5  Retraso de réplica en régimen normal ({muestras} muestras)")
    prefijo = f"Lat{RID % 10000}x"
    lat = {2: [], 3: []}
    for i in range(1, muestras + 1):
        p = persona(prefijo, i)
        t0 = time.time()
        if http("POST", f"{API[1]}/api/v2/pacientes", p)[0] != 201:
            continue
        pend = {2, 3}
        while pend and time.time() - t0 < 10:
            for s in list(pend):
                st, c = http("GET", f"{API[s]}/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento={p['numero_documento']}", timeout=5)
                if st == 200 and c["total"] >= 1:
                    lat[s].append((time.time() - t0) * 1000)
                    pend.discard(s)
    todas = lat[2] + lat[3]
    r = {"muestras": len(todas), "p50_ms": pct(todas, 50), "p95_ms": pct(todas, 95), "max_ms": pct(todas, 100),
         "nota": "incluye la latencia HTTP de escribir y de consultar (≈ decenas de ms)"}
    RESULTADOS["experimentos"]["latencia_replicacion"] = r
    linea(f"p50 {r['p50_ms']} ms, p95 {r['p95_ms']} ms, máx {r['max_ms']} ms")
    RESULTADOS["objetivos"]["replicacion_p95"] = veredicto("retraso de réplica p95", r["p95_ms"] is not None and r["p95_ms"] <= 2000,
                                                           f"{r['p95_ms']} ms (objetivo ≤ 2000 ms)")


def exp_carga(duracion=25, lectores=16, escritores=6):
    """Carga mixta: lecturas por el gateway y escrituras en las 3 sedes."""
    titulo(f"E6  Carga durante {duracion}s: {lectores} lectores por el gateway + {escritores} escritores")
    doc = f"Car{RID % 10000}x0"
    http("POST", f"{API[1]}/api/v2/pacientes", persona(f"Car{RID % 10000}x", 0))
    rutas = ["/api/v2/sede", "/api/v2/cobertura",
             f"/api/v2/pacientes/buscar?cod_tipo_documento=CC&numero_documento={doc}",
             f"/api/v2/historia-federada/{doc}?cod_tipo_documento=CC"]
    fin = time.time() + duracion
    lat_r, lat_w, err_r, err_w = [], [], [0], [0]
    cont = [0]
    lock = threading.Lock()

    def lector():
        while time.time() < fin:
            t0 = time.time()
            st, _ = http("GET", GW + random.choice(rutas), timeout=15)
            with lock:
                lat_r.append((time.time() - t0) * 1000)
                err_r[0] += st != 200

    def escritor(k):
        sede = (k % 3) + 1
        while time.time() < fin:
            with lock:
                cont[0] += 1
                n = cont[0]
            t0 = time.time()
            st, _ = http("POST", f"{API[sede]}/api/v2/pacientes", persona(f"Car{RID % 10000}w{sede}x", n), timeout=15)
            with lock:
                lat_w.append((time.time() - t0) * 1000)
                err_w[0] += st != 201

    antes = {s: pacientes_de(s, s) for s in (1, 2, 3)}
    with ThreadPoolExecutor(max_workers=lectores + escritores) as ex:
        t0 = time.time()
        futs = [ex.submit(lector) for _ in range(lectores)] + [ex.submit(escritor, k) for k in range(escritores)]
        for f in futs:
            f.result()
        dur = time.time() - t0
    lag = prom('max_over_time(hc_replication_slot_lag_bytes[1m])')
    max_lag = max((float(x["value"][1]) for x in lag), default=None)
    drenaje = esperar(lambda: all(
        (pacientes_de(v, s) or 0) - (antes[s] or 0) >= 0 for v in (1, 2, 3) for s in (1, 2, 3)) and
        sum((pacientes_de(1, s) or 0) - (antes[s] or 0) for s in (1, 2, 3)) ==
        sum((pacientes_de(3, s) or 0) - (antes[s] or 0) for s in (1, 2, 3)), 60, 0.5)
    r = {"lecturas": len(lat_r), "lecturas_por_s": round(len(lat_r) / dur, 1), "lecturas_errores": err_r[0],
         "lectura_p50_ms": pct(lat_r, 50), "lectura_p95_ms": pct(lat_r, 95), "lectura_p99_ms": pct(lat_r, 99),
         "escrituras": len(lat_w), "escrituras_por_s": round(len(lat_w) / dur, 1), "escrituras_errores": err_w[0],
         "escritura_p50_ms": pct(lat_w, 50), "escritura_p95_ms": pct(lat_w, 95), "escritura_p99_ms": pct(lat_w, 99),
         "max_wal_pendiente_bytes": max_lag, "segundos_hasta_drenar_replicas": drenaje,
         "transacciones_por_minuto": round(60 * (len(lat_r) + len(lat_w)) / dur)}
    RESULTADOS["experimentos"]["carga"] = r
    linea(f"lecturas: {r['lecturas_por_s']}/s, p50 {r['lectura_p50_ms']} ms, p95 {r['lectura_p95_ms']} ms, p99 {r['lectura_p99_ms']} ms, errores {r['lecturas_errores']}")
    linea(f"escrituras: {r['escrituras_por_s']}/s, p50 {r['escritura_p50_ms']} ms, p95 {r['escritura_p95_ms']} ms, errores {r['escrituras_errores']}")
    linea(f"≈ {r['transacciones_por_minuto']} transacciones/min (la plantilla plantea 10 000/min FHIR; aquí es un clúster de laboratorio de 1 nodo)")
    linea(f"WAL máximo pendiente: {max_lag} bytes; réplicas drenadas en {drenaje}s tras la carga")
    # SLI desde Prometheus (lo que vería un tablero)
    tot = prom('sum by (sede) (increase(hc_http_requests_total[3m]))')
    err = prom('sum by (sede) (increase(hc_http_requests_total{estado=~"5.."}[3m]))')
    p95 = prom('histogram_quantile(0.95, sum by (le, sede) (rate(hc_http_request_duration_seconds_bucket[3m])))')
    sli = {}
    for x in tot:
        sede = x["metric"]["sede"]
        t_ = float(x["value"][1])
        e_ = next((float(y["value"][1]) for y in err if y["metric"].get("sede") == sede), 0.0)
        pp = next((float(y["value"][1]) for y in p95 if y["metric"].get("sede") == sede), None)
        sli[sede] = {"peticiones": round(t_), "errores_5xx": round(e_), "disponibilidad_pct": round(100 * (1 - e_ / t_), 3) if t_ else None,
                     "p95_s": round(pp, 3) if pp is not None else None}
    RESULTADOS["experimentos"]["sli_prometheus"] = sli
    linea(f"SLI según Prometheus (últimos 3 min): {json.dumps(sli, ensure_ascii=False)}")
    RESULTADOS["objetivos"]["carga_sin_errores"] = veredicto("carga sin errores", r["lecturas_errores"] == 0 and r["escrituras_errores"] == 0,
                                                             f"{r['lecturas_errores']} lecturas y {r['escrituras_errores']} escrituras con error")


def _huella_sede(ns):
    """Conteos y huella de identificadores de una sede (para comparar réplicas)."""
    sql = ("SELECT (SELECT count(*) FROM paciente) || '/' || (SELECT count(*) FROM encuentro) || '/' || "
           "(SELECT count(*) FROM diagnostico_encuentro) || '/' || (SELECT count(*) FROM composicion_bundle) || '/' || "
           "md5(coalesce((SELECT string_agg(id_paciente::text, ',' ORDER BY id_paciente) FROM paciente), ''))")
    return kubectl("-n", ns, "exec", "pg-0", "--", "psql", "-U", "admin", "-d", "historia_clinica", "-Atc", sql).stdout.strip()


def _borrar_disco(ns):
    """Simula la pérdida del disco de una sede: borra el volumen Y su carpeta en el nodo.

    (El aprovisionador de Minikube nombra la carpeta por el volumen: si no se borra, el
    volumen nuevo reutiliza los datos viejos y no hay desastre.)
    """
    kubectl("-n", ns, "scale", "statefulset/pg", "--replicas=0")
    kubectl("-n", ns, "wait", "--for=delete", "pod/pg-0", "--timeout=120s")
    kubectl("-n", ns, "delete", "pvc", "data-pg-0", "--wait=true", "--timeout=120s")
    sh("minikube", "ssh", f"sudo rm -rf /tmp/hostpath-provisioner/{ns}/data-pg-0")
    kubectl("-n", ns, "scale", "statefulset/pg", "--replicas=1")
    esperar(lambda: kubectl("-n", ns, "get", "pod", "pg-0", "-o", "jsonpath={.status.containerStatuses[0].ready}").stdout == "true", 240, 2)


def exp_reconstruccion():
    """Pierde el disco de Cartagena y la reconstruye desde sus pares, con escrituras en curso."""
    titulo("E7  Cartagena pierde su disco y se reconstruye desde Sincelejo y Corozal")
    ns = NS[2]
    antes = _huella_sede(ns)
    sonda_gw = Sonda(f"{GW}/api/v2/sede")
    escritor = Escritor(1, f"Rec{RID % 10000}x", tasa=5)
    sonda_gw.start(); escritor.start()
    time.sleep(5)

    t0 = time.time()
    _borrar_disco(ns)
    vacia = kubectl("-n", ns, "exec", "pg-0", "--", "psql", "-U", "admin", "-d", "historia_clinica", "-Atc",
                    "SELECT count(*) FROM paciente").stdout.strip()
    t_vacia = round(time.time() - t0, 1)
    t1 = time.time()
    rec = sh("bash", "scripts/reconstruir_sede.sh", "cartagena")
    t_rec = round(time.time() - t1, 1)
    t_total = round(time.time() - t0, 1)
    time.sleep(3)
    escritor.detener()
    rg = sonda_gw.detener()

    acks = len(escritor.acks)
    # Todo lo confirmado en Sincelejo mientras duró el desastre debe existir en Cartagena y en Corozal.
    def igualadas():
        h = [_huella_sede(NS[i]) for i in (1, 2, 3)]
        return h[0] == h[1] == h[2]
    conv = esperar(igualadas, 60, 1)
    h1, h2 = _huella_sede(NS[1]), _huella_sede(ns)
    pacientes_sinc = pacientes_de(1, 1) or 0
    r = {"pacientes_antes": int(antes.split("/")[0]), "base_nueva_pacientes": int(vacia or -1),
         "segundos_hasta_base_vacia": t_vacia, "segundos_reconstruccion": t_rec, "segundos_desde_el_desastre": t_total,
         "script_ok": rec.returncode == 0, "huellas_iguales_con_sincelejo": h1 == h2, "segundos_hasta_igualar": conv,
         "escrituras_confirmadas_en_sincelejo_durante": acks, "escrituras_rechazadas": len(escritor.errores),
         "pacientes_sincelejo_al_final": pacientes_sinc, "gateway": rg}
    RESULTADOS["experimentos"]["reconstruccion"] = r
    linea(f"base nueva vacía ({vacia} pacientes) a los {t_vacia}s; reconstrucción en {t_rec}s; {t_total}s desde el desastre")
    linea(f"antes: {antes.split('/')[0]} pacientes; ahora: {h2.split('/')[0]}; huella igual a la de Sincelejo: {h1 == h2}")
    linea(f"escrituras confirmadas en Sincelejo durante el desastre: {acks} ({len(escritor.errores)} rechazadas); "
          f"gateway: {rg['disponibilidad_pct']} % disponible ({rg['fallidas']} fallidas de {rg['peticiones']})")
    RESULTADOS["objetivos"]["reconstruccion_sede"] = veredicto(
        "reconstrucción de una sede con disco vacío", r["script_ok"] and r["huellas_iguales_con_sincelejo"] and t_total <= 180,
        f"{t_total}s hasta tener la sede operativa (objetivo ≤ 180 s) y datos idénticos a los de sus pares")
    RESULTADOS["objetivos"]["reconstruccion_sin_perdidas"] = veredicto(
        "sin pérdida durante la reconstrucción", r["huellas_iguales_con_sincelejo"] and conv is not None,
        f"{acks} escrituras confirmadas en otra sede durante el proceso; las tres sedes quedan con la misma huella")
    # Con ~250 peticiones (el proceso dura ~20 s) un porcentaje no es verificable: 1 petición = 0,4 %.
    # Se mide la ventana de fallo, como en los demás experimentos de pods.
    RESULTADOS["objetivos"]["lectura_gateway_en_reconstruccion"] = veredicto(
        "lectura vía gateway durante la reconstrucción", rg["segundos_con_fallos"] <= 2,
        f"{rg['fallidas']} peticiones perdidas de {rg['peticiones']}, ventana de {rg['segundos_con_fallos']} s (objetivo ≤ 2 s)")


EXPERIMENTOS = {"api": exp_api, "gateway": exp_gateway, "rpo": exp_rpo, "particion": exp_particion,
                "latencia": exp_latencia, "carga": exp_carga, "reconstruccion": exp_reconstruccion}


def main():
    elegidos = sys.argv[1:] or list(EXPERIMENTOS)
    print(f"== Experimentos SRE (corrida {RID}) sobre Minikube {IP} ==")
    if esperar_sedes_sanas(30) is None:
        print("Las tres sedes no están sanas; abortando.")
        sys.exit(2)
    for nombre in elegidos:
        EXPERIMENTOS[nombre]()
        if esperar_sedes_sanas(180) is None:
            print("   (!) las sedes no se recuperaron a tiempo; se detienen los experimentos")
            break
        time.sleep(3)
    # Se acumulan los resultados de corridas parciales en el mismo archivo.
    os.makedirs("docs", exist_ok=True)
    ruta = "docs/resultados_sre.json"
    acumulado = {"experimentos": {}, "objetivos": {}}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            acumulado = json.load(f)
    acumulado["ultima_corrida"] = RID
    acumulado.setdefault("experimentos", {}).update(RESULTADOS["experimentos"])
    acumulado.setdefault("objetivos", {}).update(RESULTADOS["objetivos"])
    acumulado.pop("corrida", None)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(acumulado, f, ensure_ascii=False, indent=2, default=str)
    obj = RESULTADOS["objetivos"]
    print(f"\nObjetivos cumplidos en esta corrida: {sum(obj.values())}/{len(obj)}  (acumulado en {ruta})")
    sys.exit(0 if all(obj.values()) else 1)


if __name__ == "__main__":
    main()
