"""Modelos de entrada de la API v2 (los nombres siguen el modelo de 57 campos)."""
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PacienteIn(BaseModel):
    # id_sede_origen es opcional: si viene, debe coincidir con la sede local.
    id_sede_origen: Optional[int] = None
    cod_tipo_documento: str = Field(max_length=3)
    numero_documento: str = Field(min_length=1, max_length=20)
    primer_nombre: str = Field(min_length=1, max_length=50)
    segundo_nombre: Optional[str] = Field(default=None, max_length=50)
    primer_apellido: str = Field(min_length=1, max_length=50)
    segundo_apellido: Optional[str] = Field(default=None, max_length=50)
    fecha_hora_nacimiento: datetime
    cod_sexo: str = Field(min_length=1, max_length=1)
    cod_identidad_genero: Optional[str] = None
    cod_pais_nacionalidad: Optional[str] = None
    oposicion_donacion: bool = False
    tiene_voluntad_anticipada: bool = False
    cod_categoria_discapacidad: Optional[str] = None
    cod_pais_residencia: str = Field(min_length=3, max_length=3)
    cod_municipio_residencia: Optional[str] = None
    cod_etnia: Optional[str] = None
    cod_comunidad_etnica: Optional[str] = None
    cod_zona_territorial: Optional[str] = None


class ProfesionalIn(BaseModel):
    cod_tipo_documento: str = Field(max_length=3)
    numero_documento: str = Field(min_length=1, max_length=20)
    nombres: str = Field(min_length=1, max_length=100)
    apellidos: str = Field(min_length=1, max_length=100)


class EncuentroIn(BaseModel):
    # id opcional: el bus lo deriva del mensaje para que reenviarlo no cree otro encuentro (idempotencia)
    id_encuentro: Optional[UUID] = None
    id_paciente: UUID
    id_sede: Optional[int] = None          # si viene, debe ser la sede local
    fecha_hora_inicio: datetime
    cod_modalidad: str
    cod_grupo_servicio: str
    cod_entorno: str
    cod_via_ingreso: str
    cod_causa_atencion: str
    cod_ocupacion: Optional[str] = None
    cod_entidad_responsable: str


class TriageIn(BaseModel):
    fecha_hora_triage: datetime
    cod_triage: int


class DiagnosticoIn(BaseModel):
    cod_cie10: str
    cod_tipo_diagnostico: str = Field(max_length=2)
    fecha_diagnostico: date


class MedicamentoIn(BaseModel):
    cod_medicamento: str
    dosis_prescrita: float
    cod_unidad_dosis: str
    cod_via_administracion: str
    duracion_tratamiento: int
    cod_unidad_duracion: str
    frecuencia_valor: int
    cod_unidad_frecuencia: str


class TecnologiaIn(BaseModel):
    cod_tecnologia: str
    cod_finalidad: str
    fecha_prescripcion: datetime
    medicamento: Optional[MedicamentoIn] = None   # solo si la tecnología es un medicamento


class EntregaIn(BaseModel):
    id_tecnologia_encuentro: UUID
    id_profesional: UUID
    fecha_entrega: datetime
    dosis_administrada: Optional[float] = None
    dosis_entregada: Optional[float] = None
    cod_unidad_dosis: Optional[str] = None
    unidades_entregadas: int = 1


class ObservacionIn(BaseModel):
    id_observacion: Optional[UUID] = None      # opcional: idempotencia del bus
    cod_loinc: str
    valor_numerico: Optional[float] = None
    valor_texto: Optional[str] = None
    cod_unidad: Optional[str] = None
    fecha_hora_medicion: datetime


class AntecedenteIn(BaseModel):
    cod_cie10: Optional[str] = None
    descripcion: Optional[str] = None


class ExposicionIn(BaseModel):
    cod_factor_riesgo: str


class EgresoIn(BaseModel):
    fecha_hora_fin: datetime
    cod_condicion_egreso: str
    cod_prestador_referencia: Optional[str] = None
    id_profesional_egreso: UUID
    dias_incapacidad: Optional[int] = None
    dias_licencia_maternidad: Optional[int] = None


class LoginIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=60)
    clave: str = Field(min_length=1, max_length=200)


class PacienteLoginIn(BaseModel):
    cod_tipo_documento: str = Field(max_length=3)
    numero_documento: str = Field(min_length=1, max_length=20)
    fecha_nacimiento: date


class MpiDecisionIn(BaseModel):
    id_paciente_a: UUID
    id_paciente_b: UUID
    decision: Literal["MISMA_PERSONA", "PERSONAS_DISTINTAS"]
    motivo: Optional[str] = Field(default=None, max_length=300)
