#!/usr/bin/env python3
"""Carga datos SINTÉTICOS de demostración por la API (nada real: nombres inventados y documentos 7000001 a 7000003).

    python3 scripts/datos_demo.py                 # Docker Compose: https://localhost:8443
    python3 scripts/datos_demo.py --k8s           # Minikube: https://<minikube ip>:30443
    python3 scripts/datos_demo.py --base https://otra-direccion:8443

Deja:
  7000001  Ana Demo Tres     atendida en las TRES sedes (un encuentro cerrado en cada una): sirve para el Reporte de HC por sede y la historia unificada
  7000002  Beto Demo Cartagena   solo en Cartagena, con el encuentro abierto (sin egreso)
  7000003  Carla Demo Dos    en Sincelejo y Corozal

Es repetible: si un paciente ya existe en una sede no se le vuelven a crear encuentros. Usa las cuentas de laboratorio de credenciales/ (no se imprimen).
Solo biblioteca estándar.
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SEDES = {1: "Sincelejo", 2: "Cartagena", 3: "Corozal"}
# (documento, nombre, apellido, nacimiento, sexo, {sede: (cie10, descripción de lo que se atendió)})
PACIENTES = [
    ("7000001", "Ana", "Demo Tres", "1988-04-12", "F", {1: ("J45.9", True), 2: ("I10", True), 3: ("N39.0", True)}),
    ("7000002", "Beto", "Demo Cartagena", "1975-09-30", "M", {2: ("M54.5", False)}),
    ("7000003", "Carla", "Demo Dos", "2001-01-22", "F", {1: ("R51", True), 3: ("J00", True)}),
]


class Cliente:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.ctx = ssl.create_default_context(cafile=os.path.join(RAIZ, "credenciales", "ca.crt"))
        with open(os.path.join(RAIZ, "credenciales", "credenciales.json"), encoding="utf-8") as f:
            self.cred = json.load(f)["usuarios"]
        self.tokens = {}

    def _pedir(self, metodo, sede, ruta, cuerpo=None, token=None):
        cab = {"content-type": "application/json"}
        if token:
            cab["Authorization"] = "Bearer " + token
        req = urllib.request.Request(f"{self.base}/sede/{sede}/api/v2{ruta}", method=metodo, headers=cab,
                                     data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def token(self, usuario):
        if usuario not in self.tokens:
            estado, d = self._pedir("POST", 1, "/auth/login", {"usuario": usuario, "clave": self.cred[usuario]["clave"]})
            if estado != 200:
                sys.exit(f"No se pudo iniciar sesión como {usuario} ({estado}). ¿Está levantado el sistema y existe credenciales/?")
            self.tokens[usuario] = d["token"]
        return self.tokens[usuario]

    def llamar(self, usuario, metodo, sede, ruta, cuerpo=None):
        return self._pedir(metodo, sede, ruta, cuerpo, self.token(usuario))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="https://localhost:8443")
    ap.add_argument("--k8s", action="store_true", help="usa https://<minikube ip>:30443")
    a = ap.parse_args()
    base = a.base
    if a.k8s:
        base = "https://" + subprocess.check_output(["minikube", "ip"], text=True).strip() + ":30443"
    subprocess.run([sys.executable, os.path.join(RAIZ, "scripts", "credenciales.py")], stdout=subprocess.DEVNULL, check=True)
    c = Cliente(base)
    profesionales = {}
    for sede in SEDES:
        estado, d = c.llamar("admin", "POST", sede, "/profesionales", {"cod_tipo_documento": "CC", "numero_documento": f"7100{sede}", "nombres": "Medico", "apellidos": f"Demo {SEDES[sede]}"})
        if estado not in (200, 201):
            sys.exit(f"No se pudo crear el profesional en {SEDES[sede]}: {estado} {d}")
        profesionales[sede] = d["profesional"]["id_profesional"]

    for doc, nombre, apellido, nac, sexo, atenciones in PACIENTES:
        for sede, (cie10, cerrar) in atenciones.items():
            estado, d = c.llamar("admision", "POST", sede, "/pacientes", {
                "cod_tipo_documento": "CC", "numero_documento": doc, "primer_nombre": nombre, "primer_apellido": apellido,
                "fecha_hora_nacimiento": nac + "T08:00:00", "cod_sexo": sexo, "cod_pais_nacionalidad": "COL", "cod_pais_residencia": "COL",
                "cod_municipio_residencia": "70001", "cod_etnia": "06", "cod_zona_territorial": "1"})
            if estado not in (200, 201):
                sys.exit(f"Paciente {doc} en {SEDES[sede]}: {estado} {d}")
            if estado == 200:
                print(f"  {doc} ya estaba en {SEDES[sede]}: no se repiten sus encuentros")
                continue
            pid = d["paciente"]["id_paciente"]
            estado, d = c.llamar("admision", "POST", sede, "/encuentros", {
                "id_paciente": pid, "fecha_hora_inicio": "2026-11-05T08:30:00", "cod_modalidad": "01", "cod_grupo_servicio": "01", "cod_entorno": "01",
                "cod_via_ingreso": "01", "cod_causa_atencion": "01", "cod_entidad_responsable": "EPS001"})
            enc = d["encuentro"]["id_encuentro"]
            base_enc = f"/encuentros/{enc}"
            c.llamar("admision", "POST", sede, base_enc + "/triage", {"fecha_hora_triage": "2026-11-05T08:35:00", "cod_triage": 3})
            c.llamar("medico", "POST", sede, base_enc + "/diagnosticos", {"cod_cie10": cie10, "cod_tipo_diagnostico": "IN", "fecha_diagnostico": "2026-11-05"})
            c.llamar("medico", "POST", sede, base_enc + "/observaciones", {"cod_loinc": "8310-5", "valor_numerico": 37.2, "cod_unidad": "C", "fecha_hora_medicion": "2026-11-05T08:45:00"})
            if cerrar:
                estado, d = c.llamar("medico", "POST", sede, base_enc + "/egreso", {
                    "fecha_hora_fin": "2026-11-05T10:00:00", "cod_condicion_egreso": "01", "id_profesional_egreso": profesionales[sede], "dias_incapacidad": 0})
                if estado != 201:
                    sys.exit(f"Egreso de {doc} en {SEDES[sede]}: {estado} {d}")
            print(f"  {doc} {nombre} {apellido}: encuentro {'cerrado' if cerrar else 'abierto'} en {SEDES[sede]} ({cie10})")
    print("\nListo. Pruebe el Reporte de HC del paciente 7000001 (vista del Reportero) o su historia unificada (vista del Médico).")
    print("Para entrar como paciente: documento 7000001 y fecha de nacimiento 1988-04-12.")


if __name__ == "__main__":
    main()
