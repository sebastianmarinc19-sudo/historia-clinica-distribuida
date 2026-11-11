"""Lectura del CSV legado (separador `;`): documento;nombre;sexo;nacimiento;dx_local;fecha;triage;profesional."""
import csv
import hashlib
import io

COLUMNAS = ["documento", "nombre", "sexo", "nacimiento", "dx_local", "fecha", "triage", "profesional"]


class ErrorCSV(Exception):
    pass


def hash_fila(sede: int, fila: dict) -> str:
    """Clave de idempotencia de una fila: hash del contenido (y de la sede), insensible a espacios sobrantes."""
    contenido = "|".join((fila.get(c) or "").strip() for c in COLUMNAS)
    return hashlib.sha256(f"{sede}|{contenido}".encode()).hexdigest()


def leer(texto: str) -> list[tuple[int, dict]]:
    """Devuelve [(número_de_fila, {columna: valor})]; el número cuenta desde 2 (la fila 1 es el encabezado)."""
    lector = csv.DictReader(io.StringIO(texto.lstrip("﻿")), delimiter=";")
    if not lector.fieldnames:
        raise ErrorCSV("el CSV está vacío")
    faltan = [c for c in COLUMNAS if c not in [f.strip() for f in lector.fieldnames]]
    if faltan:
        raise ErrorCSV("faltan columnas en el encabezado: " + ", ".join(faltan))
    filas = []
    for i, fila in enumerate(lector, start=2):
        limpia = {(k or "").strip(): (v or "").strip() for k, v in fila.items()}
        if any(limpia.values()):
            filas.append((i, limpia))
    return filas
