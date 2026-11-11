#!/usr/bin/env python3
"""Crea la CA de LABORATORIO y el certificado TLS del gateway (necesita el binario `openssl`).

    python3 scripts/certificados.py                      # crea (o reutiliza) los archivos y los lista
    python3 scripts/certificados.py --rotar              # certificados nuevos
    python3 scripts/certificados.py --ip 192.168.49.2    # IP adicional en el certificado (por defecto, la de `minikube ip`)

Salida en credenciales/ (ignorada por git; nada de esto debe publicarse):
    ca.crt          certificado de la CA: es lo que confían los clientes (curl --cacert, pruebas, navegador)
    ca.key          clave privada de la CA (solo para firmar; no la lleva ningún pod)
    gateway.crt/.key  certificado y clave del gateway (los consume el Secret `gateway-tls` o el contenedor de Compose)

Es una CA propia de laboratorio: el navegador mostrará una advertencia hasta que se importe ca.crt. En un
despliegue real el certificado lo emite una CA reconocida (o cert-manager con Let's Encrypt) y la clave rota sola.
"""
import argparse
import os
import shutil
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR = os.path.join(RAIZ, "credenciales")
DIAS_CA, DIAS_CERT = 825, 397        # 397 días es el máximo que aceptan los navegadores para un certificado de servidor
NOMBRES_DNS = ["localhost", "hc_gateway", "gateway", "gateway.hc-gateway.svc.cluster.local"]
IPS = ["127.0.0.1"]


def correr(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"Falló: {' '.join(args[:3])}…\n{r.stderr}")
    return r.stdout


def ip_minikube():
    if not shutil.which("minikube"):
        return None
    r = subprocess.run(["minikube", "ip"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def crear(ips):
    os.makedirs(DIR, exist_ok=True)
    ruta = lambda n: os.path.join(DIR, n)
    correr("openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", ruta("ca.key"))
    correr("openssl", "req", "-x509", "-new", "-key", ruta("ca.key"), "-sha256", "-days", str(DIAS_CA), "-out", ruta("ca.crt"),
           "-subj", "/O=Historia clinica distribuida (laboratorio)/CN=CA de laboratorio",
           "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    correr("openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", ruta("gateway.key"))
    san = ",".join([f"DNS:{d}" for d in NOMBRES_DNS] + [f"IP:{i}" for i in ips])
    ext = ruta("gateway.ext")
    with open(ext, "w") as f:
        f.write(f"subjectAltName={san}\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n")
    correr("openssl", "req", "-new", "-key", ruta("gateway.key"), "-subj", "/O=Historia clinica distribuida (laboratorio)/CN=gateway",
           "-out", ruta("gateway.csr"))
    correr("openssl", "x509", "-req", "-in", ruta("gateway.csr"), "-CA", ruta("ca.crt"), "-CAkey", ruta("ca.key"), "-CAcreateserial",
           "-days", str(DIAS_CERT), "-sha256", "-extfile", ext, "-out", ruta("gateway.crt"))
    for tmp in ("gateway.csr", "gateway.ext", "ca.srl"):
        if os.path.exists(ruta(tmp)):
            os.remove(ruta(tmp))
    for secreto in ("ca.key", "gateway.key"):
        os.chmod(ruta(secreto), 0o600)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotar", action="store_true")
    ap.add_argument("--ip", action="append", default=[], help="IP adicional para el certificado")
    a = ap.parse_args()
    ips = list(dict.fromkeys(IPS + a.ip + ([ip_minikube()] if ip_minikube() else [])))
    existe = all(os.path.exists(os.path.join(DIR, n)) for n in ("ca.crt", "gateway.crt", "gateway.key"))
    if a.rotar or not existe:
        crear(ips)
        print("Certificados creados.")
    else:
        print("Certificados existentes (use --rotar para cambiarlos).")
    sal = correr("openssl", "x509", "-in", os.path.join(DIR, "gateway.crt"), "-noout", "-subject", "-enddate", "-ext", "subjectAltName")
    print(sal.strip())
    print(f"\nCA para los clientes: {os.path.relpath(os.path.join(DIR, 'ca.crt'), RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
