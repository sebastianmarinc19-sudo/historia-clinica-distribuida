"""Identidad federada (MPI) determinista, sin punto único de falla.

Cada sede materializa su propia copia de identidad_federada a partir de las tablas paciente y mpi_decision, que SÍ se
replican a las tres sedes. La función es determinista: el id_mpi depende solo del "ancla" del grupo (el miembro con menor
clave documento/sede), no de qué sede resolvió ni de cuándo. Así dos sedes que resuelven por separado llegan al mismo
id_mpi y no hay nada que replicar ni reconciliar (salvo las decisiones humanas, que se replican como datos).

Política. Unir a dos personas distintas es peor que dejar un duplicado, porque mezcla sus historias clínicas; por eso:

1. Solo el DOCUMENTO identifica. Mismo tipo y número de documento y datos no contradictorios -> se unen solos.
2. Los datos demográficos solo PROPONEN. Documentos distintos con nombre, fecha y sexo parecidos (puntaje >= umbral:
   gemelos, homónimos, cambio de TI a CC...) son "candidatos": no se unen hasta que una persona lo confirme.
3. Mismo documento con otra fecha de nacimiento Y otro nombre es un "conflicto" (posible error de digitación): no se une.
4. Una decisión humana (MISMA_PERSONA / PERSONAS_DISTINTAS) manda sobre las reglas y se replica a todas las sedes. Para
   cada par vale la más reciente (fecha, sede, id); sin cadenas por similitud: solo las aristas anteriores unen.

Los grupos son los componentes conexos de ese grafo, calculados con la misma función pura en todas las sedes.
"""
import unicodedata
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from . import db

NAMESPACE_MPI = uuid.UUID("6f1c2a3e-5b7d-4e19-9a40-3c8d2b1f7a55")
NOMBRE_COHERENTE = 0.6          # similitud mínima de nombre para aceptar un mismo documento con otra fecha de nacimiento
MISMA_PERSONA = "MISMA_PERSONA"
PERSONAS_DISTINTAS = "PERSONAS_DISTINTAS"


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def nombre_completo(p: dict) -> str:
    partes = [p.get("primer_nombre"), p.get("segundo_nombre"),
              p.get("primer_apellido"), p.get("segundo_apellido")]
    return " ".join(x for x in partes if x)


def similitud_nombre(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _normalizar(nombre_completo(a)),
                           _normalizar(nombre_completo(b))).ratio()


def mismo_documento(a: dict, b: dict) -> bool:
    return (a["cod_tipo_documento"] == b["cod_tipo_documento"]
            and _normalizar(a["numero_documento"]) == _normalizar(b["numero_documento"]))


def _fecha(p: dict):
    return p["fecha_hora_nacimiento"].date()


def score_demografico(a: dict, b: dict) -> float:
    """0.6 por similitud de nombre + 0.3 por fecha de nacimiento + 0.1 por sexo (no mira el documento)."""
    score = 0.6 * similitud_nombre(a, b) + 0.3 * (_fecha(a) == _fecha(b)) + 0.1 * (a["cod_sexo"] == b["cod_sexo"])
    return round(score, 4)


def calcular_score(a: dict, b: dict) -> float:
    """1.0 si coinciden tipo y número de documento; si no, el puntaje demográfico."""
    return 1.0 if mismo_documento(a, b) else score_demografico(a, b)


def datos_contradictorios(a: dict, b: dict) -> bool:
    return _fecha(a) != _fecha(b) and similitud_nombre(a, b) < NOMBRE_COHERENTE


def evaluar_par(a: dict, b: dict, umbral: float, decision: Optional[str] = None) -> dict:
    """Clasifica un par de registros: vinculo | candidato | conflicto | descartado | ninguno."""
    s = score_demografico(a, b)
    if decision == PERSONAS_DISTINTAS:
        return {"clase": "descartado", "score": s, "origen": "manual"}
    if decision == MISMA_PERSONA:
        return {"clase": "vinculo", "score": s, "origen": "manual"}
    if mismo_documento(a, b):
        if datos_contradictorios(a, b):
            return {"clase": "conflicto", "score": s, "motivo": "documento_con_datos_contradictorios"}
        return {"clase": "vinculo", "score": 1.0, "origen": "documento"}
    if s >= umbral:
        return {"clase": "candidato", "score": s, "motivo": "datos_similares"}
    return {"clase": "ninguno", "score": s}


def id_mpi_para(tipo_documento: str, numero_documento: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_MPI, f"{tipo_documento}|{_normalizar(numero_documento)}")


def _clave_ancla(p: dict) -> tuple:
    return (p["cod_tipo_documento"], _normalizar(p["numero_documento"]),
            p["id_sede_origen"], str(p["id_paciente"]))


def par_canonico(x, y) -> tuple:
    x, y = uuid.UUID(str(x)), uuid.UUID(str(y))
    return (x, y) if x < y else (y, x)


@dataclass
class GrupoMPI:
    id_mpi: uuid.UUID
    score: float                 # el del vínculo más débil del grupo
    miembros: list[dict]
    vinculos: list[dict]


def decisiones_vigentes(filas: Iterable[dict]) -> dict:
    """Decisión efectiva por par: la más reciente por (fecha, sede, id), igual en todas las sedes."""
    vigente: dict = {}
    for f in filas:
        k = par_canonico(f["id_paciente_a"], f["id_paciente_b"])
        orden = (f["fecha_decision"], f["id_sede_origen"], str(f["id_decision"]))
        if k not in vigente or orden > vigente[k][0]:
            vigente[k] = (orden, f)
    return {k: v[1] for k, v in vigente.items()}


def calcular_grupos(pacientes: Iterable[dict], decisiones: Iterable[dict], umbral: float) -> list[GrupoMPI]:
    """Función pura: componentes conexos de los vínculos (documento coherente o decisión MISMA_PERSONA)."""
    por_id = {p["id_paciente"]: p for p in pacientes}
    vigentes = decisiones_vigentes(decisiones)
    padre = {i: i for i in por_id}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    por_documento: dict = {}
    for p in por_id.values():
        por_documento.setdefault((p["cod_tipo_documento"], _normalizar(p["numero_documento"])), []).append(p["id_paciente"])
    pares = set()
    for ids in por_documento.values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pares.add(par_canonico(ids[i], ids[j]))
    pares |= {k for k in vigentes if k[0] in por_id and k[1] in por_id}

    aristas = []
    for x, y in sorted(pares):
        d = vigentes.get((x, y))
        ev = evaluar_par(por_id[x], por_id[y], umbral, d["decision"] if d else None)
        if ev["clase"] == "vinculo":
            padre[raiz(x)] = raiz(y)
            aristas.append({"a": x, "b": y, "origen": ev["origen"], "score": ev["score"]})

    componentes: dict = {}
    for i in por_id:
        componentes.setdefault(raiz(i), []).append(i)
    grupos = []
    for ids in componentes.values():
        if len(ids) < 2:
            continue
        miembros = sorted((por_id[i] for i in ids), key=_clave_ancla)
        ancla = miembros[0]
        vinculos = [a for a in aristas if raiz(a["a"]) == raiz(ids[0])]
        grupos.append(GrupoMPI(
            id_mpi=id_mpi_para(ancla["cod_tipo_documento"], ancla["numero_documento"]),
            score=min(a["score"] for a in vinculos), miembros=miembros, vinculos=vinculos))
    return sorted(grupos, key=lambda g: str(g.id_mpi))


def revisiones(paciente: dict, otros: Iterable[dict], decisiones: Iterable[dict], umbral: float) -> list[dict]:
    """Pares de `paciente` con otros registros que necesitan (o ya tuvieron) una decisión humana."""
    vigentes = decisiones_vigentes(decisiones)
    salida = []
    for o in otros:
        if o["id_paciente"] == paciente["id_paciente"]:
            continue
        d = vigentes.get(par_canonico(paciente["id_paciente"], o["id_paciente"]))
        natural = evaluar_par(paciente, o, umbral)
        if d is None and natural["clase"] not in ("candidato", "conflicto"):
            continue
        salida.append({"paciente": o, "score": natural["score"], "motivo": natural.get("motivo"),
                       "pendiente": d is None, "decision": d})
    return sorted(salida, key=lambda r: (-r["score"], str(r["paciente"]["id_paciente"])))


# ------------------------------------------------------------------ acceso a la base de la sede
def _vecindad(conn, p: dict, umbral: float) -> tuple[dict, list]:
    """Carga los registros enlazados con `p` (mismo documento o decisión) hasta que el componente deja de crecer."""
    cargados = {p["id_paciente"]: p}
    decisiones: dict = {}
    expandidos: set = set()
    while True:
        grupos = calcular_grupos(cargados.values(), decisiones.values(), umbral)
        comp = next(({m["id_paciente"] for m in g.miembros} for g in grupos if p["id_paciente"] in {m["id_paciente"] for m in g.miembros}),
                    {p["id_paciente"]})
        pendientes = comp - expandidos
        if not pendientes:
            return cargados, list(decisiones.values())
        expandidos |= pendientes
        ids = list(pendientes)
        claves = tuple({(cargados[i]["cod_tipo_documento"], _normalizar(cargados[i]["numero_documento"])) for i in ids})
        for d in db.consultar("SELECT * FROM mpi_decision WHERE id_paciente_a = ANY(%s) OR id_paciente_b = ANY(%s)", (ids, ids), conn):
            decisiones[d["id_decision"]] = d
        socios = {x for d in decisiones.values() for x in (d["id_paciente_a"], d["id_paciente_b"])} - set(cargados)
        filas = db.consultar(
            """SELECT * FROM paciente
                WHERE (cod_tipo_documento, lower(btrim(numero_documento))) IN %s
                   OR id_paciente = ANY(%s)""", (claves, list(socios)), conn)
        for f in filas:
            cargados.setdefault(f["id_paciente"], f)


def _limpiar_identidades(conn, mpis: Iterable) -> None:
    mpis = list(mpis)
    if not mpis:
        return
    db.ejecutar(
        """DELETE FROM identidad_federada_paciente
            WHERE id_mpi = ANY(%s)
              AND id_mpi IN (SELECT id_mpi FROM identidad_federada_paciente GROUP BY id_mpi HAVING count(*) < 2)""", (mpis,), conn)
    db.ejecutar(
        """DELETE FROM identidad_federada i WHERE i.id_mpi = ANY(%s)
              AND NOT EXISTS (SELECT 1 FROM identidad_federada_paciente m WHERE m.id_mpi = i.id_mpi)""", (mpis,), conn)


def _mpis_de(conn, ids: list) -> dict:
    return {r["id_paciente"]: r["id_mpi"] for r in db.consultar(
        "SELECT id_paciente, id_mpi FROM identidad_federada_paciente WHERE id_paciente = ANY(%s)", (ids,), conn)}


def _materializar(conn, g: GrupoMPI) -> int:
    ids = [m["id_paciente"] for m in g.miembros]
    previos = _mpis_de(conn, ids)
    viejos = set(previos.values())
    nuevos = sum(1 for i in ids if previos.get(i) != g.id_mpi)
    if viejos:      # los miembros de una identidad vieja que ya no pertenecen a este grupo se desvinculan
        db.ejecutar("DELETE FROM identidad_federada_paciente WHERE id_mpi = ANY(%s) AND NOT (id_paciente = ANY(%s))",
                    (list(viejos), ids), conn)
    db.ejecutar("DELETE FROM identidad_federada_paciente WHERE id_paciente = ANY(%s)", (ids,), conn)
    db.ejecutar(
        """INSERT INTO identidad_federada (id_mpi, score_coincidencia) VALUES (%s, %s)
           ON CONFLICT (id_mpi) DO UPDATE SET score_coincidencia = EXCLUDED.score_coincidencia""", (g.id_mpi, g.score), conn)
    for m in g.miembros:
        db.ejecutar("INSERT INTO identidad_federada_paciente (id_mpi, id_paciente, id_sede) VALUES (%s, %s, %s)",
                    (g.id_mpi, m["id_paciente"], m["id_sede_origen"]), conn)
    _limpiar_identidades(conn, viejos - {g.id_mpi})
    return nuevos


def _pendientes_de(conn, p: dict, cargados: dict, decisiones: list, umbral: float) -> list[dict]:
    parecidos = db.consultar("SELECT * FROM paciente WHERE fecha_hora_nacimiento::date = %s::date AND id_paciente <> %s",
                             (p["fecha_hora_nacimiento"], p["id_paciente"]), conn)
    otros = {o["id_paciente"]: o for o in list(cargados.values()) + parecidos}
    return [r for r in revisiones(p, otros.values(), decisiones, umbral) if r["pendiente"]]


def resolver_identidad(conn, id_paciente: uuid.UUID, umbral: float) -> dict:
    """Resuelve y materializa la identidad federada local de un paciente."""
    p = db.uno("SELECT * FROM paciente WHERE id_paciente = %s", (id_paciente,), conn)
    if p is None:
        raise LookupError("paciente no encontrado")

    cargados, decisiones = _vecindad(conn, p, umbral)
    grupo = next((g for g in calcular_grupos(cargados.values(), decisiones, umbral)
                  if any(m["id_paciente"] == p["id_paciente"] for m in g.miembros)), None)
    pendientes = len(_pendientes_de(conn, p, cargados, decisiones, umbral))

    if grupo is None:           # ya no pertenece a ninguna identidad (o nunca la tuvo)
        previos = _mpis_de(conn, [p["id_paciente"]])
        if previos:
            db.ejecutar("DELETE FROM identidad_federada_paciente WHERE id_paciente = %s", (p["id_paciente"],), conn)
            _limpiar_identidades(conn, set(previos.values()))
        return {"resuelto": False, "id_mpi": None, "score": None, "miembros_totales": 1, "miembros_nuevos": 0,
                "candidatos_pendientes": pendientes}

    nuevos = _materializar(conn, grupo)
    return {"resuelto": True, "id_mpi": grupo.id_mpi, "score": grupo.score, "miembros_totales": len(grupo.miembros),
            "miembros_nuevos": nuevos, "candidatos_pendientes": pendientes,
            "vinculos": [{"origen": v["origen"], "score": v["score"]} for v in grupo.vinculos]}


def recalcular_todo(conn, umbral: float) -> dict:
    """Reconstruye identidad_federada* desde cero con la regla vigente (p. ej. tras cambiar la política)."""
    pacientes = db.consultar("SELECT * FROM paciente", conn=conn)
    decisiones = db.consultar("SELECT * FROM mpi_decision", conn=conn)
    grupos = calcular_grupos(pacientes, decisiones, umbral)
    db.ejecutar("DELETE FROM identidad_federada_paciente", conn=conn)
    db.ejecutar("DELETE FROM identidad_federada", conn=conn)
    for g in grupos:
        db.ejecutar("INSERT INTO identidad_federada (id_mpi, score_coincidencia) VALUES (%s, %s)", (g.id_mpi, g.score), conn)
        for m in g.miembros:
            db.ejecutar("INSERT INTO identidad_federada_paciente (id_mpi, id_paciente, id_sede) VALUES (%s, %s, %s)",
                        (g.id_mpi, m["id_paciente"], m["id_sede_origen"]), conn)
    return {"pacientes": len(pacientes), "decisiones": len(decisiones), "identidades": len(grupos),
            "registros_federados": sum(len(g.miembros) for g in grupos)}


def resumen_paciente(p: dict, sedes: dict) -> dict:
    return {"id_paciente": p["id_paciente"], "nombre": nombre_completo(p), "cod_tipo_documento": p["cod_tipo_documento"],
            "numero_documento": p["numero_documento"], "fecha_nacimiento": _fecha(p).isoformat(), "cod_sexo": p["cod_sexo"],
            "id_sede_origen": p["id_sede_origen"], "sede_nombre": sedes.get(p["id_sede_origen"])}


def revision_de_documento(conn, tipo: str, numero: str, umbral: float) -> list[dict]:
    """Pares con decisión pendiente (o ya tomada) para los registros de un documento, sin repetir pares."""
    propios = db.consultar("SELECT * FROM paciente WHERE cod_tipo_documento = %s AND lower(btrim(numero_documento)) = %s",
                           (tipo, _normalizar(numero)), conn)
    if not propios:
        return []
    ids = [p["id_paciente"] for p in propios]
    decisiones = db.consultar("SELECT * FROM mpi_decision WHERE id_paciente_a = ANY(%s) OR id_paciente_b = ANY(%s)", (ids, ids), conn)
    socios = list({x for d in decisiones for x in (d["id_paciente_a"], d["id_paciente_b"])} - set(ids))
    otros = db.consultar(
        """SELECT * FROM paciente
            WHERE id_paciente <> ALL(%s)
              AND (fecha_hora_nacimiento::date = ANY(%s) OR (cod_tipo_documento = %s AND lower(btrim(numero_documento)) = %s)
                   OR id_paciente = ANY(%s))""",
        (ids, [p["fecha_hora_nacimiento"].date() for p in propios], tipo, _normalizar(numero), socios), conn)
    sedes = {r["id_sede"]: r["nombre_ciudad"] for r in db.consultar("SELECT id_sede, nombre_ciudad FROM sede", conn=conn)}
    universo = {p["id_paciente"]: p for p in propios + otros}
    vistos, salida = set(), []
    for p in propios:
        for r in revisiones(p, universo.values(), decisiones, umbral):
            k = par_canonico(p["id_paciente"], r["paciente"]["id_paciente"])
            if k in vistos:
                continue
            vistos.add(k)
            d = r["decision"]
            salida.append({"a": resumen_paciente(universo[k[0]], sedes), "b": resumen_paciente(universo[k[1]], sedes),
                           "score": r["score"], "motivo": r["motivo"], "pendiente": r["pendiente"],
                           "decision": None if d is None else {
                               "decision": d["decision"], "decidido_por": d["decidido_por"], "motivo": d["motivo"],
                               "fecha": d["fecha_decision"], "sede": sedes.get(d["id_sede_origen"])}})
    return sorted(salida, key=lambda r: (not r["pendiente"], -r["score"]))
