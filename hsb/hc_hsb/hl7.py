"""Lectura de mensajes HL7 v2 (ADT^A01 y ORU^R01). Solo sintaxis: la validación de negocio está en normalizador.py.

Los segmentos se separan con CR (lo normal en HL7), pero se aceptan también LF y CRLF porque muchos sistemas y `curl` los cambian.
Los campos se separan con `|` y los componentes con `^`. En MSH el campo 1 es el propio `|`, así que MSH-n es el elemento n-1 al partir.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class ErrorHL7(Exception):
    pass


@dataclass
class Mensaje:
    segmentos: dict[str, list[list[str]]] = field(default_factory=dict)

    def todos(self, nombre: str) -> list[list[str]]:
        return self.segmentos.get(nombre, [])

    def primero(self, nombre: str) -> Optional[list[str]]:
        s = self.todos(nombre)
        return s[0] if s else None


def parsear(texto: str) -> Mensaje:
    crudo = texto.replace("\r\n", "\r").replace("\n", "\r")
    lineas = [s for s in crudo.split("\r") if s.strip()]
    if not lineas or not lineas[0].startswith("MSH|"):
        raise ErrorHL7("el mensaje debe comenzar con el segmento MSH")
    m = Mensaje()
    for linea in lineas:
        campos = linea.split("|")
        m.segmentos.setdefault(campos[0], []).append(campos)
    return m


def campo(segmento: Optional[list[str]], n: int, componente: Optional[int] = None) -> str:
    """Valor del campo n (y componente, base 1) de un segmento; cadena vacía si no existe. En MSH, n=1 es el separador."""
    if not segmento:
        return ""
    if segmento[0] == "MSH":
        if n == 1:
            return "|"
        i = n - 1
    else:
        i = n
    if i >= len(segmento):
        return ""
    valor = segmento[i].split("~")[0]           # primera repetición
    if componente is None:
        return valor.strip()
    partes = valor.split("^")
    return partes[componente - 1].strip() if componente - 1 < len(partes) else ""


def fecha_hl7(texto: str) -> Optional[datetime]:
    """AAAAMMDD, AAAAMMDDHHMM o AAAAMMDDHHMMSS (con zona opcional) -> datetime; None si no es una fecha válida."""
    m = re.match(r"^(\d{8}|\d{12}|\d{14})(?:\.\d+)?(?:[+-]\d{4})?$", (texto or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).ljust(14, "0"), "%Y%m%d%H%M%S")
    except ValueError:
        return None
