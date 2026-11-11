"""Eventos de la auditoría encadenada expresados como recursos FHIR R4 `AuditEvent`.

La fuente de verdad sigue siendo la tabla `evento_auditoria` (con su cadena de hash); esto es una vista de salida para que otro sistema
FHIR (o el propio HAPI) pueda leer la trazabilidad en el formato estándar. Cada evento es una interacción REST de la API; la cadena
viaja en una segunda `entity` con su secuencia, su hash y el hash previo, de modo que quien reciba el recurso puede reverificarla.

  método HTTP -> action / subtype:  GET R read · POST C create · PUT/PATCH U update · DELETE D delete
  estado HTTP -> outcome:           < 400 -> 0 (éxito) · 4xx -> 4 (fallo menor) · 5xx -> 8 (fallo grave)
"""
from typing import Optional

TIPO_REST = {"system": "http://terminology.hl7.org/CodeSystem/audit-event-type", "code": "rest", "display": "Restful Operation"}
_INTERACCION = {"GET": ("R", "read", "read"), "POST": ("C", "create", "create"), "PUT": ("U", "update", "update"),
                "PATCH": ("U", "update", "update"), "DELETE": ("D", "delete", "delete")}
_SISTEMA_INTERACCION = "http://hl7.org/fhir/restful-interaction"


def _resultado(estado: int) -> str:
    return "0" if estado < 400 else ("4" if estado < 500 else "8")


def id_auditevent(id_sede: int, seq: int) -> str:
    return f"audit-{id_sede}-{seq}"


def a_auditevent(e: dict, id_sede: int, nombre_sede: Optional[str] = None) -> dict:
    """Un evento de `evento_auditoria` (con `instante` ya en ISO) como AuditEvent."""
    accion, codigo, display = _INTERACCION.get(e["metodo"], ("E", "operation", "operation"))
    agente: dict = {"requestor": True, "who": {"display": e.get("usuario") or "anónimo"}}
    if e.get("rol"):
        agente["role"] = [{"text": e["rol"]}]
    if e.get("ip"):
        agente["network"] = {"address": e["ip"], "type": "2"}
    entidades = []
    if e.get("documento"):
        entidades.append({"what": {"reference": f"Patient/pac-{e['documento']}"}, "type": {
            "system": "http://terminology.hl7.org/CodeSystem/audit-entity-type", "code": "1", "display": "Person"},
            "detail": [{"type": "ruta", "valueString": e["ruta"]}]})
    entidades.append({"what": {"display": f"evento {e['seq']} de la cadena de auditoría de la sede {id_sede}"}, "type": {
        "system": "http://terminology.hl7.org/CodeSystem/audit-entity-type", "code": "4", "display": "Other"},
        "detail": [{"type": "seq", "valueString": str(e["seq"])}, {"type": "hash", "valueString": e["hash"].strip()},
                   {"type": "hash_previo", "valueString": e["hash_previo"].strip()}]})
    return {
        "resourceType": "AuditEvent", "id": id_auditevent(id_sede, e["seq"]),
        "type": TIPO_REST,
        "subtype": [{"system": _SISTEMA_INTERACCION, "code": codigo, "display": display}],
        "action": accion, "recorded": e["instante"], "outcome": _resultado(e["estado"]), "outcomeDesc": f"HTTP {e['estado']}",
        "agent": [agente],
        "source": {"site": nombre_sede or f"sede {id_sede}", "observer": {"display": f"API v2 de la sede {id_sede}"}},
        "entity": entidades,
    }


def bundle(eventos: list[dict], id_sede: int, nombre_sede: Optional[str] = None, url_busqueda: str = "/api/v2/auditoria/fhir") -> dict:
    """`searchset` con los AuditEvent de esta sede (del más reciente al más antiguo)."""
    return {"resourceType": "Bundle", "type": "searchset", "total": len(eventos), "link": [{"relation": "self", "url": url_busqueda}],
            "entry": [{"fullUrl": f"AuditEvent/{id_auditevent(id_sede, e['seq'])}", "search": {"mode": "match"},
                       "resource": a_auditevent(e, id_sede, nombre_sede)} for e in eventos]}
