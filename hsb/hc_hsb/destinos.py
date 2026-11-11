"""Entrega a los destinos: el HAPI FHIR y la API v2 de la sede (que es la dueña de sus datos).

Todo error de entrega se clasifica en uno de dos grupos, porque el bus actúa distinto en cada uno:
  * Transitorio: el destino no respondió o está saturado (conexión, tiempo, 5xx, 429, o un 409 de versión del HAPI). Se REINTENTA con espera creciente.
  * Rechazo: el destino entendió y dijo que no (validación, conflicto, 4xx). Reintentar no sirve: el mensaje queda «rechazado» con el motivo.
Cada paso es idempotente (PUT con ids deterministas en HAPI; ids derivados del mensaje en la sede), así un reintento tras un
fallo a medias —o un bus que murió entre HAPI y el nodo— no duplica nada.
"""
import logging
import time
import uuid
from typing import Optional

import httpx

from . import config

logger = logging.getLogger("hc_hsb.destinos")
NS_HSB = uuid.UUID("0b4f6f1e-8a5e-4c43-9a8e-6c1a2d9e7b10")


class Transitorio(Exception):
    """Fallo pasajero del destino: se reintenta."""


class Rechazo(Exception):
    """El destino rechazó el contenido: no se reintenta."""


def uuid_encuentro(sede: int, visita: str) -> uuid.UUID:
    return uuid.uuid5(NS_HSB, f"enc|{sede}|{visita}")


def uuid_observacion(clave: str, n: int) -> uuid.UUID:
    return uuid.uuid5(NS_HSB, f"obs|{clave}|{n}")


def _timeout(plazo: Optional[float]) -> float:
    """Tiempo para la siguiente llamada: el de una llamada, sin pasar del plazo total del intento (instante en `time.monotonic()`)."""
    if plazo is None:
        return config.TIMEOUT_S
    resto = plazo - time.monotonic()
    if resto <= 0.5:
        raise Transitorio("se agotó el tiempo de este intento (el destino responde muy lento)")
    return min(config.TIMEOUT_S, resto)


def _detalle(r: httpx.Response) -> str:
    try:
        d = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(d, dict):
        if d.get("resourceType") == "OperationOutcome":
            return "; ".join(i.get("diagnostics") or i.get("details", {}).get("text", "") for i in d.get("issue", []))[:300]
        partes = [str(d[k]) for k in ("error", "restriccion", "detalle", "mensaje", "detail") if d.get(k)]
        if partes:
            return " · ".join(partes)[:300]
    return str(d)[:300]


class ClienteHapi:
    def __init__(self, transporte: Optional[httpx.BaseTransport] = None):
        self._transporte = transporte

    def enviar(self, sede: int, bundle: dict, plazo: Optional[float] = None) -> None:
        base = config.url_fhir(sede)
        if not base:
            raise Transitorio(f"no hay servidor FHIR configurado para la sede {sede}")
        try:
            with httpx.Client(transport=self._transporte) as c:
                r = c.post(base, json=bundle, headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
                           timeout=_timeout(plazo))
        except httpx.HTTPError as e:
            raise Transitorio(f"HAPI no responde ({e.__class__.__name__})") from e
        if r.status_code >= 500 or r.status_code in (408, 425, 429):
            raise Transitorio(f"HAPI respondió {r.status_code}")
        if r.status_code == 409:
            # Conflicto de versión: un intento anterior (que agotó el tiempo del cliente pero siguió en el HAPI) y este escribían el mismo recurso a la vez.
            # Los ids son deterministas y el PUT es idempotente, así que reintentar es seguro; si persiste, el mensaje acaba «muerto» para revisión humana.
            raise Transitorio(f"HAPI respondió 409 (conflicto de versión, otra escritura del mismo recurso estaba en curso): {_detalle(r)}")
        if r.status_code >= 400:
            raise Rechazo(f"HAPI rechazó el Bundle ({r.status_code}): {_detalle(r)}")


# Clase de paciente HL7 (PV1-2) -> códigos del catálogo de la sede (grupo de servicios, vía de ingreso)
GRUPO_Y_VIA = {"E": ("05", "01"), "O": ("01", "02"), "I": ("03", "01")}


class ClienteSede:
    def __init__(self, transporte: Optional[httpx.BaseTransport] = None):
        self._transporte = transporte
        self._tokens: dict[int, str] = {}

    # ----- HTTP con sesión de servicio
    def _login(self, c: httpx.Client, sede: int, plazo: Optional[float]) -> str:
        try:
            r = c.post(f"{config.url_api(sede)}/api/v2/auth/login", json={"usuario": config.USUARIO_SERVICIO, "clave": config.CLAVE_SERVICIO},
                       timeout=_timeout(plazo))
        except httpx.HTTPError as e:
            raise Transitorio(f"la sede {sede} no responde ({e.__class__.__name__})") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise Transitorio(f"la sede {sede} respondió {r.status_code} al iniciar sesión")
        if r.status_code != 200:
            raise Transitorio(f"la sede {sede} rechazó la cuenta del bus al iniciar sesión ({r.status_code}): revisar HSB_USUARIO y HSB_CLAVE")
        self._tokens[sede] = r.json()["token"]
        return self._tokens[sede]

    def _post(self, c: httpx.Client, sede: int, ruta: str, cuerpo: dict, que: str, plazo: Optional[float]) -> dict:
        for intento in (1, 2):
            token = self._tokens.get(sede) or self._login(c, sede, plazo)
            try:
                r = c.post(f"{config.url_api(sede)}{ruta}", json=cuerpo, headers={"Authorization": f"Bearer {token}"}, timeout=_timeout(plazo))
            except httpx.HTTPError as e:
                raise Transitorio(f"{que}: la sede {sede} no responde ({e.__class__.__name__})") from e
            if r.status_code == 401 and intento == 1:         # token vencido: se inicia sesión de nuevo una vez
                self._tokens.pop(sede, None)
                continue
            break
        if r.status_code < 300:
            return r.json()
        if r.status_code in (401, 403):
            raise Transitorio(f"{que}: la sede {sede} rechazó la cuenta del bus ({r.status_code}): revisar el rol «hsb»")
        if r.status_code >= 500 or r.status_code in (408, 425, 429):
            raise Transitorio(f"{que}: la sede {sede} respondió {r.status_code} ({_detalle(r)})")
        raise Rechazo(f"{que} en la sede {sede}: {r.status_code} {_detalle(r)}")

    # ----- entrega de un mensaje canónico
    def entregar(self, canonico: dict, plazo: Optional[float] = None) -> dict:
        sede = canonico["sede"]
        if not config.url_api(sede):
            raise Transitorio(f"no hay API configurada para la sede {sede}")
        p, e = canonico["paciente"], canonico["encuentro"]
        acciones: dict = {}
        with httpx.Client(transport=self._transporte) as c:
            cuerpo = {"cod_tipo_documento": p["tipo_documento"], "numero_documento": p["documento"],
                      "primer_nombre": p["primer_nombre"], "primer_apellido": p["primer_apellido"],
                      "fecha_hora_nacimiento": f"{p['nacimiento']}T00:00:00", "cod_sexo": "I" if p["sexo"] == "O" else p["sexo"],
                      "cod_pais_residencia": config.PAIS_RESIDENCIA}
            for k in ("segundo_nombre", "segundo_apellido"):
                if p.get(k):
                    cuerpo[k] = p[k]
            r = self._post(c, sede, "/api/v2/pacientes", cuerpo, "paciente", plazo)
            acciones["paciente"] = r["accion"]
            id_paciente = r["paciente"]["id_paciente"]

            grupo, via = GRUPO_Y_VIA.get(e["clase"], GRUPO_Y_VIA["O"])
            id_enc = str(uuid_encuentro(sede, e["visita"]))
            r = self._post(c, sede, "/api/v2/encuentros", {
                "id_encuentro": id_enc, "id_paciente": id_paciente, "fecha_hora_inicio": e["inicio"], "cod_modalidad": "01",
                "cod_grupo_servicio": grupo, "cod_entorno": "01", "cod_via_ingreso": via, "cod_causa_atencion": "01",
                "cod_entidad_responsable": config.ENTIDAD_RESPONSABLE}, "encuentro", plazo)
            acciones["encuentro"] = r["accion"]

            for dx in canonico["diagnosticos"]:
                self._post(c, sede, f"/api/v2/encuentros/{id_enc}/diagnosticos",
                           {"cod_cie10": dx["cie10"], "cod_tipo_diagnostico": dx["tipo"], "fecha_diagnostico": dx["fecha"]}, f"diagnóstico {dx['cie10']}", plazo)
            acciones["diagnosticos"] = len(canonico["diagnosticos"])
            if e.get("triage"):
                self._post(c, sede, f"/api/v2/encuentros/{id_enc}/triage", {"fecha_hora_triage": e["inicio"], "cod_triage": e["triage"]}, "triage", plazo)
                acciones["triage"] = e["triage"]
            for ob in canonico["observaciones"]:
                self._post(c, sede, f"/api/v2/encuentros/{id_enc}/observaciones", {
                    "id_observacion": str(uuid_observacion(canonico["clave"], ob["n"])), "cod_loinc": ob["loinc"],
                    "valor_numerico": ob["valor"], "valor_texto": ob["valor_texto"], "cod_unidad": ob["unidad"],
                    "fecha_hora_medicion": ob["fecha"]}, f"observación {ob['loinc']}", plazo)
            acciones["observaciones"] = len(canonico["observaciones"])
        return acciones
