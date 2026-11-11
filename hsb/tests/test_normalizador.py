"""Normalización y validación contra los archivos de ejemplo del parcial (ejemplos/, que no se modifican)."""
import os
import pathlib

import pytest

from hc_hsb import csvlegado, hl7, normalizador as nz

EJEMPLOS = pathlib.Path(os.getenv("HSB_EJEMPLOS", pathlib.Path(__file__).resolve().parents[2] / "ejemplos"))


def leer(nombre: str) -> str:
    return (EJEMPLOS / nombre).read_bytes().decode("utf-8")


def terminologia() -> dict:
    t = {}
    for linea in (EJEMPLOS / "05_ref_terminologia.csv").read_text(encoding="utf-8").splitlines()[1:]:
        dx, cie, desc = linea.split(";")
        t[nz.clave_terminologia(dx)] = {"cie10": cie, "descripcion": desc}
    return t


# ----------------------------------------------------------------------------- HL7 v2
def test_los_segmentos_se_leen_con_cr_lf_o_crlf():
    base = leer("01_adt_a01_valido_sede2.hl7")
    for variante in (base, base.replace("\r", "\n"), base.replace("\r", "\r\n")):
        assert nz.normalizar_hl7(variante).canonico is not None


def test_adt_valido_sede2_queda_normalizado():
    n = nz.normalizar_hl7(leer("01_adt_a01_valido_sede2.hl7"))
    assert n.motivos == [] and n.sede == 2 and n.clave == "MSG-0001" and n.tipo == "ADT^A01" and n.documento == "1007"
    c = n.canonico
    assert c["paciente"] == {"documento": "1007", "tipo_documento": "CC", "nacimiento": "1990-02-14", "sexo": "F",
                             "primer_nombre": "Andrea", "segundo_nombre": None, "primer_apellido": "Rojas", "segundo_apellido": None}
    assert c["encuentro"]["clase"] == "O" and c["encuentro"]["visita"] == "V-S2-0101" and c["encuentro"]["inicio"] == "2026-11-07T10:15:00"
    assert c["encuentro"]["medico"] == {"codigo": "MED-02", "apellido": "Ruiz", "nombre": "Mateo"}
    assert c["diagnosticos"] == [{"cie10": "J45.9", "texto": "Asma", "tipo": "IN", "fecha": "2026-11-07"}]
    assert c["observaciones"] == []


def test_oru_valido_sede1_trae_la_observacion_loinc():
    n = nz.normalizar_hl7(leer("02_oru_r01_laboratorio_sede1.hl7"))
    assert n.motivos == [] and n.sede == 1 and n.tipo == "ORU^R01" and n.documento == "1001"
    obs, = n.canonico["observaciones"]
    assert (obs["loinc"], obs["valor"], obs["unidad"]) == ("718-7", 13.8, "g/dL")
    assert n.canonico["paciente"]["sexo"] == "M" and n.canonico["encuentro"]["clase"] == "E"


def test_adt_invalido_se_rechaza_con_los_tres_motivos_del_contrato():
    n = nz.normalizar_hl7(leer("03_adt_a01_invalido.hl7"))
    assert n.canonico is None and n.sede == 3 and n.clave == "MSG-0003"
    assert len(n.motivos) == 3, n.motivos
    texto = " | ".join(n.motivos)
    assert "documento no numérico" in texto and "sexo no válido" in texto and "sin mapeo a CIE-10" in texto


@pytest.mark.parametrize("cambio,motivo", [
    (("ADT^A01", "ADT^A08"), "tipo de mensaje no soportado"),
    (("SEDE2", "SEDE9"), "sede no válida"),
    (("|MSG-0001|", "||"), "MSH-10"),
    (("|19900214|", "|19901340|"), "fecha de nacimiento"),
    (("1007^^^HIS", "12^^^HIS"), "longitud inválida"),
])
def test_cada_regla_de_validacion_rechaza_con_su_motivo(cambio, motivo):
    n = nz.normalizar_hl7(leer("01_adt_a01_valido_sede2.hl7").replace(*cambio))
    assert n.canonico is None and any(motivo in m for m in n.motivos), n.motivos


def test_un_mensaje_sin_msh_o_vacio_no_revienta():
    assert nz.normalizar_hl7("").motivos and nz.normalizar_hl7("PID|1||123").motivos


def test_oru_con_valor_no_numerico_o_sin_unidad_se_rechaza():
    base = leer("02_oru_r01_laboratorio_sede1.hl7")
    assert any("no es numérico" in m for m in nz.normalizar_hl7(base.replace("13.8", "abc")).motivos)
    assert any("unidad" in m for m in nz.normalizar_hl7(base.replace("g/dL", "")).motivos)


def test_la_fecha_hl7_acepta_los_tres_formatos_y_zona():
    assert hl7.fecha_hl7("20261107").isoformat() == "2026-11-07T00:00:00"
    assert hl7.fecha_hl7("202611071015").isoformat() == "2026-11-07T10:15:00"
    assert hl7.fecha_hl7("20261107101530-0500").isoformat() == "2026-11-07T10:15:30"
    assert hl7.fecha_hl7("2026-11-07") is None and hl7.fecha_hl7("20261340") is None


# ----------------------------------------------------------------------------- CSV legado
def test_csv_de_la_sede3_da_3_validas_y_2_rechazadas_como_pide_el_contrato():
    t = terminologia()
    res = {f["documento"]: nz.normalizar_fila_csv(3, i, f, t) for i, f in csvlegado.leer(leer("04_sede3_legado.csv"))}
    assert [d for d, n in res.items() if n.canonico] == ["1008", "1009", "1010"]
    assert any("sin mapeo a CIE-10" in m for m in res["1011"].motivos)
    assert any("longitud inválida" in m for m in res["12"].motivos)
    c = res["1008"].canonico
    assert c["diagnosticos"][0]["cie10"] == "A09" and c["encuentro"]["triage"] == 3 and c["encuentro"]["clase"] == "E"
    assert res["1009"].canonico["encuentro"]["triage"] is None and res["1009"].canonico["encuentro"]["clase"] == "O"
    assert c["paciente"]["primer_nombre"] == "Camila" and c["paciente"]["primer_apellido"] == "Suarez" and c["paciente"]["segundo_apellido"] == "Pineda"


def test_la_clave_del_csv_depende_del_contenido_y_de_la_sede_no_de_los_espacios():
    t = terminologia()
    (_, fila), = csvlegado.leer("documento;nombre;sexo;nacimiento;dx_local;fecha;triage;profesional\n"
                                " 1008 ; Camila Suarez Pineda;F;1996-02-10;DIARREA;2026-11-07T08:30;3;MED-01\n")
    (_, igual), = csvlegado.leer("documento;nombre;sexo;nacimiento;dx_local;fecha;triage;profesional\n"
                                 "1008;Camila Suarez Pineda;F;1996-02-10;DIARREA;2026-11-07T08:30;3;MED-01\n")
    assert csvlegado.hash_fila(3, fila) == csvlegado.hash_fila(3, igual) != csvlegado.hash_fila(2, igual)
    assert nz.normalizar_fila_csv(3, 2, fila, t).clave == nz.normalizar_fila_csv(3, 2, igual, t).clave


def test_csv_sin_las_columnas_esperadas_se_rechaza_completo():
    with pytest.raises(csvlegado.ErrorCSV):
        csvlegado.leer("a;b\n1;2\n")


def test_la_terminologia_ignora_tildes_y_mayusculas():
    t = terminologia()
    f = {"documento": "1234", "nombre": "Ana Lopez", "sexo": "F", "nacimiento": "1990-01-01", "dx_local": "infección urinaria",
         "fecha": "2026-11-07T08:00", "triage": "", "profesional": ""}
    assert nz.normalizar_fila_csv(1, 2, f, t).canonico["diagnosticos"][0]["cie10"] == "N39.0"


def test_la_tabla_de_terminologia_del_hsb_es_copia_fiel_de_la_del_paquete():
    copia = pathlib.Path(__file__).resolve().parents[1] / "datos" / "ref_terminologia.csv"
    assert copia.read_bytes() == (EJEMPLOS / "05_ref_terminologia.csv").read_bytes()
