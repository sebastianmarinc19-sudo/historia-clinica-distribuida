"""Los 57 campos de la Resolución 866/2021 y su ubicación en el modelo.

Fuente: tabla 1 de Modelo_57_campos_BDD.docx.

Cobertura de un campo en una sede (CU-15):
  - nivel 'paciente' : pacientes de la sede con el dato / pacientes de la sede
  - nivel 'encuentro': encuentros de la sede con el dato / encuentros de la sede
  - nivel 'hijo'     : encuentros de la sede con al menos una fila con el dato
                       / encuentros de la sede
Estado: completo (100 %), parcial (0 < x < 100 %), pendiente (0 % o sin datos).
"""
from typing import NamedTuple, Optional


class Campo(NamedTuple):
    n: int
    nombre: str
    nivel: str                      # paciente | encuentro | hijo
    tabla: str
    columna: str
    filtro: Optional[str] = None    # solo nivel hijo


# Subconsultas que entregan (id_encuentro, valor) para cada tabla hija.
_ORIGEN_HIJO = {
    "triage": "SELECT id_encuentro, {col} AS valor FROM triage",
    "egreso": "SELECT id_encuentro, {col} AS valor FROM egreso",
    "diagnostico_encuentro":
        "SELECT id_encuentro, {col} AS valor FROM diagnostico_encuentro WHERE {filtro}",
    "tecnologia_encuentro": "SELECT id_encuentro, {col} AS valor FROM tecnologia_encuentro",
    "medicamento_prescrito":
        "SELECT te.id_encuentro, m.{col} AS valor FROM medicamento_prescrito m "
        "JOIN tecnologia_encuentro te ON te.id_tecnologia_encuentro = m.id_tecnologia_encuentro",
    "entrega_tecnologia":
        "SELECT te.id_encuentro, x.{col} AS valor FROM entrega_tecnologia x "
        "JOIN tecnologia_encuentro te ON te.id_tecnologia_encuentro = x.id_tecnologia_encuentro",
    "observacion": "SELECT id_encuentro, {col} AS valor FROM observacion",
    "antecedente_salud": "SELECT id_encuentro, {col} AS valor FROM antecedente_salud",
    "exposicion_riesgo": "SELECT id_encuentro, {col} AS valor FROM exposicion_riesgo",
}

P, E, H = "paciente", "encuentro", "hijo"
DX = "diagnostico_encuentro"

CAMPOS: list[Campo] = [
    # 1. Identificación del usuario (1–20)
    Campo(1, "País de la nacionalidad", P, "paciente", "cod_pais_nacionalidad"),
    Campo(2, "Tipo de documento de identificación", P, "paciente", "cod_tipo_documento"),
    Campo(3, "Número de documento de identificación", P, "paciente", "numero_documento"),
    Campo(4, "Primer apellido", P, "paciente", "primer_apellido"),
    Campo(5, "Segundo apellido", P, "paciente", "segundo_apellido"),
    Campo(6, "Primer nombre", P, "paciente", "primer_nombre"),
    Campo(7, "Segundo nombre", P, "paciente", "segundo_nombre"),
    Campo(8, "Fecha y hora de nacimiento", P, "paciente", "fecha_hora_nacimiento"),
    Campo(9, "Sexo biológico", P, "paciente", "cod_sexo"),
    Campo(10, "Identidad de género", P, "paciente", "cod_identidad_genero"),
    Campo(11, "Ocupación al momento de la atención", E, "encuentro", "cod_ocupacion"),
    Campo(12, "Oposición a la presunción legal de donación", P, "paciente", "oposicion_donacion"),
    Campo(13, "Documento de voluntad anticipada", P, "paciente", "tiene_voluntad_anticipada"),
    Campo(14, "Categoría de discapacidad", P, "paciente", "cod_categoria_discapacidad"),
    Campo(15, "País de residencia habitual", P, "paciente", "cod_pais_residencia"),
    Campo(16, "Municipio de residencia habitual", P, "paciente", "cod_municipio_residencia"),
    Campo(17, "Etnia", P, "paciente", "cod_etnia"),
    Campo(18, "Comunidad étnica", P, "paciente", "cod_comunidad_etnica"),
    Campo(19, "Zona territorial de residencia", P, "paciente", "cod_zona_territorial"),
    Campo(20, "Entidad que responde por el plan de beneficios", E, "encuentro", "cod_entidad_responsable"),
    # 2. Contacto con el servicio de salud (21–30)
    Campo(21, "Código del prestador que realiza la atención (derivado de la sede)", E, "encuentro", "id_sede"),
    Campo(22, "Fecha y hora de inicio de la atención", E, "encuentro", "fecha_hora_inicio"),
    Campo(23, "Modalidad de realización de la tecnología", E, "encuentro", "cod_modalidad"),
    Campo(24, "Grupo de servicios", E, "encuentro", "cod_grupo_servicio"),
    Campo(25, "Entorno donde se realiza la atención", E, "encuentro", "cod_entorno"),
    Campo(26, "Vía de ingreso del usuario", E, "encuentro", "cod_via_ingreso"),
    Campo(27, "Causa que motiva la atención", E, "encuentro", "cod_causa_atencion"),
    Campo(28, "Fecha y hora del triage", H, "triage", "fecha_hora_triage"),
    Campo(29, "Clasificación del triage", H, "triage", "cod_triage"),
    Campo(30, "Diagnóstico principal de ingreso", H, DX, "cod_cie10", "cod_tipo_diagnostico = 'IN'"),
    # 3. Tecnologías en salud (31–43)
    Campo(31, "Tecnología en salud", H, "tecnologia_encuentro", "cod_tecnologia"),
    Campo(32, "Finalidad de la tecnología", H, "tecnologia_encuentro", "cod_finalidad"),
    Campo(33, "Descripción común del medicamento", H, "medicamento_prescrito", "cod_medicamento"),
    Campo(34, "Fecha de prescripción de la tecnología", H, "tecnologia_encuentro", "fecha_prescripcion"),
    Campo(35, "Dosis prescrita del medicamento", H, "medicamento_prescrito", "dosis_prescrita"),
    Campo(36, "Vía de administración", H, "medicamento_prescrito", "cod_via_administracion"),
    Campo(37, "Duración prescrita del tratamiento", H, "medicamento_prescrito", "duracion_tratamiento"),
    Campo(38, "Frecuencia de administración", H, "medicamento_prescrito", "frecuencia_valor"),
    Campo(39, "Dosis administrada institucionalmente", H, "entrega_tecnologia", "dosis_administrada"),
    Campo(40, "Fecha de entrega de la tecnología", H, "entrega_tecnologia", "fecha_entrega"),
    Campo(41, "Dosis entregadas del medicamento", H, "entrega_tecnologia", "dosis_entregada"),
    Campo(42, "Unidades entregadas o aplicadas", H, "entrega_tecnologia", "unidades_entregadas"),
    Campo(43, "Talento humano que realiza, entrega o aplica la tecnología", H, "entrega_tecnologia", "id_profesional"),
    # 4. Resultados del uso de las tecnologías (44–57)
    Campo(44, "Diagnóstico principal de egreso", H, DX, "cod_cie10", "cod_tipo_diagnostico = 'EP'"),
    Campo(45, "Diagnóstico relacionado", H, DX, "cod_cie10", "cod_tipo_diagnostico = 'RE'"),
    Campo(46, "Resultado de evaluación de valoración clínica", H, "observacion", "cod_loinc"),
    Campo(47, "Diagnósticos de la complicación", H, DX, "cod_cie10", "cod_tipo_diagnostico = 'CO'"),
    Campo(48, "Condición y destino del usuario al egreso", H, "egreso", "cod_condicion_egreso"),
    Campo(49, "Diagnóstico de la causa básica de muerte", H, DX, "cod_cie10", "cod_tipo_diagnostico = 'CM'"),
    Campo(50, "Fecha y hora de finalización de la atención", E, "encuentro", "fecha_hora_fin"),
    Campo(51, "Prestador a donde se refiere al usuario", H, "egreso", "cod_prestador_referencia"),
    Campo(52, "Incapacidad", H, "egreso", "dias_incapacidad"),
    Campo(53, "Días de licencia de maternidad", H, "egreso", "dias_licencia_maternidad"),
    Campo(54, "Antecedentes de salud", H, "antecedente_salud", "cod_cie10"),
    Campo(55, "Exposición a factores de riesgo", H, "exposicion_riesgo", "cod_factor_riesgo"),
    Campo(56, "Tipo de documento del talento humano que realizó el egreso", H, "egreso", "id_profesional_egreso"),
    Campo(57, "Número de documento del talento humano que realizó el egreso", H, "egreso", "id_profesional_egreso"),
]


def estado(cubiertos: int, esperados: int) -> str:
    if esperados == 0 or cubiertos == 0:
        return "pendiente"
    return "completo" if cubiertos == esperados else "parcial"


def patron_lote(lote: str, exacto: bool = False) -> str:
    """Prefijo de documento como patrón LIKE (se escapan los comodines del usuario); `exacto` = el documento completo, sin prefijo."""
    return lote.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ("" if exacto else "%")


def sql_cobertura(campo: Campo, con_lote: bool = False) -> str:
    """Consulta que devuelve (cubiertos, esperados) para una sede (parámetro %s).

    Con `con_lote` se restringe a los pacientes cuyo documento empieza por un prefijo
    (y a sus encuentros): sirve para auditar un lote de carga o un caso de demostración.
    Parámetros: ver `parametros_cobertura`.
    """
    solo_pac = " AND numero_documento LIKE %s" if con_lote else ""
    solo_enc = " AND id_paciente IN (SELECT id_paciente FROM paciente WHERE numero_documento LIKE %s)" if con_lote else ""
    solo_enc_e = solo_enc.replace("id_paciente IN", "e.id_paciente IN")
    if campo.nivel == P:
        return (f"SELECT count(*) FILTER (WHERE {campo.columna} IS NOT NULL) AS cubiertos, "
                f"count(*) AS esperados FROM paciente WHERE id_sede_origen = %s{solo_pac}")
    if campo.nivel == E:
        return (f"SELECT count(*) FILTER (WHERE {campo.columna} IS NOT NULL) AS cubiertos, "
                f"count(*) AS esperados FROM encuentro WHERE id_sede = %s{solo_enc}")
    origen = _ORIGEN_HIJO[campo.tabla].format(col=campo.columna, filtro=campo.filtro or "TRUE")
    return (f"SELECT (SELECT count(DISTINCT s.id_encuentro) FROM ({origen}) s "
            f"JOIN encuentro e ON e.id_encuentro = s.id_encuentro "
            f"WHERE e.id_sede = %s{solo_enc_e} AND s.valor IS NOT NULL) AS cubiertos, "
            f"(SELECT count(*) FROM encuentro WHERE id_sede = %s{solo_enc}) AS esperados")


def parametros_cobertura(campo: Campo, id_sede: int, lote: Optional[str] = None, exacto: bool = False) -> tuple:
    patron = patron_lote(lote, exacto) if lote else None
    if campo.nivel in (P, E):
        return (id_sede,) if not lote else (id_sede, patron)
    return (id_sede, id_sede) if not lote else (id_sede, patron, id_sede, patron)
