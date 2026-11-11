"""Carga sintética del bus (Docker Compose, datos inventados): 50 ADT válidos, 10 inválidos y 10 reenvíos con 4 hilos.

    docker exec pg_hsb psql -U hsb -d hsb -qc "TRUNCATE mensaje_bus CASCADE"   # opcional: medir desde cero
    python3 scripts/carga_bus.py

Mide los mensajes por minuto de ingesta y de entrega de extremo a extremo, y muestra el resumen del bus (latencia media, % de fallidos, duplicados).
Los percentiles salen de la base: docker exec pg_hsb psql -U hsb -d hsb -c "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM entregado_en - recibido_en)) FROM mensaje_bus WHERE estado = 'entregado'".
"""
import concurrent.futures as cf
import json
import os
import ssl
import time
import urllib.error
import urllib.request

R = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ctx = ssl.create_default_context(cafile=R + '/credenciales/ca.crt')
c = json.load(open(R + '/credenciales/credenciales.json'))['usuarios']
def pedir(m, p, cuerpo=None, tok=None, raw=None):
    h = {'content-type': 'application/json'}
    if tok:
        h['Authorization'] = 'Bearer ' + tok
    d = raw if raw is not None else (json.dumps(cuerpo).encode() if cuerpo else None)
    r = urllib.request.Request('https://localhost:8443' + p, method=m, headers=h, data=d)
    try:
        return json.loads(urllib.request.urlopen(r, context=ctx, timeout=120).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}')
tok = pedir('POST', '/sede/1/api/v2/auth/login', {'usuario': 'sede', 'clave': c['sede']['clave']})['token']
def adt(i, valido=True):
    doc = str(8100000 + i) if valido else 'ABC%d' % i
    return ("MSH|^~\\&|HIS_SEDE2|SEDE2|HSB|CENTRAL|20261109101500||ADT^A01|CARGA-%04d|P|2.5\r"
            "PID|1||%s^^^HIS||Prueba^Carga%d||19900214|F\r"
            "PV1|1|O|||||MED-02^Ruiz^Mateo||||||||||||V-S2-%04d|||||||||||||||||||||||||202611091015\r"
            "DG1|1||J45.9^Asma^I10||20261109|A" % (i, doc, i, i)).encode()
trabajos = [(i, True) for i in range(50)] + [(100 + i, False) for i in range(10)]
t0 = time.time()
def enviar(t):
    return pedir('POST', '/hsb/hl7', tok=tok, raw=adt(*t))


with cf.ThreadPoolExecutor(4) as ex:
    res = list(ex.map(enviar, trabajos))
t_ing = time.time() - t0
dups = [pedir('POST', '/hsb/hl7', tok=tok, raw=adt(i)) for i in range(10)]
print('ingesta: %d mensajes en %.1f s; estados al responder: %s' % (len(res), t_ing, {e: sum(1 for r in res if r.get('estado') == e) for e in {r.get('estado') for r in res}}))
print('reenvíos:', {e: sum(1 for r in dups if r.get('estado') == e) for e in {r.get('estado') for r in dups}})
tm = pedir('POST', '/sede/1/api/v2/auth/login', {'usuario': 'medico', 'clave': c['medico']['clave']})['token']
while time.time() - t0 < 900:
    s = pedir('GET', '/hsb/resumen', tok=tm)
    pend = sum(s['por_estado'][k] for k in ('recibido', 'validado', 'transformado', 'reintentando'))
    if pend == 0:
        break
    time.sleep(2)
t_total = time.time() - t0
print('hasta que no queda nada pendiente: %.1f s' % t_total)
print(json.dumps(s))
print('mensajes por minuto (ingesta): %.0f; (entregados de extremo a extremo): %.0f' % (len(res) * 60 / t_ing, s['por_estado']['entregado'] * 60 / t_total))
