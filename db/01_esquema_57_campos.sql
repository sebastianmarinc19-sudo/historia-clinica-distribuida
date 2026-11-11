-- =====================================================================
-- esquema_57_campos.sql
-- Modelo relacional (3FN) de los 57 campos interoperables de la
-- Resolución 866 de 2021. Reconstruido a partir de
-- "Modelo_57_campos_BDD.docx" (secciones 2, 5.1, 5.2 y 5.3).
--
-- 45 tablas: 29 catálogos + 16 tablas de núcleo.
-- Se carga idéntico en cada sede (nodo). Objetivo: PostgreSQL 16.
--
-- Pendiente de confirmar con el Anexo Técnico: dominios de los
-- catálogos y el formato exacto de los campos 13 y 52.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Catálogos de referencia (29)
-- ---------------------------------------------------------------------

CREATE TABLE pais (
    cod_pais     CHAR(3)      PRIMARY KEY,           -- ISO 3166-1 alfa-3
    descripcion  VARCHAR(100) NOT NULL
);

CREATE TABLE departamento (
    cod_departamento CHAR(2)      PRIMARY KEY,       -- DIVIPOLA
    descripcion      VARCHAR(100) NOT NULL
);

CREATE TABLE municipio (
    cod_municipio    CHAR(5)      PRIMARY KEY,       -- DIVIPOLA
    cod_departamento CHAR(2)      NOT NULL REFERENCES departamento,
    descripcion      VARCHAR(100) NOT NULL
);

CREATE TABLE tipo_documento (
    cod_tipo_documento VARCHAR(3)  PRIMARY KEY,
    descripcion        VARCHAR(80) NOT NULL
);

CREATE TABLE sexo_biologico (
    cod_sexo    CHAR(1)     PRIMARY KEY,
    descripcion VARCHAR(40) NOT NULL
);

CREATE TABLE identidad_genero (
    cod_identidad_genero VARCHAR(2)  PRIMARY KEY,
    descripcion          VARCHAR(80) NOT NULL
);

CREATE TABLE ocupacion (
    cod_ocupacion VARCHAR(6)   PRIMARY KEY,
    descripcion   VARCHAR(150) NOT NULL
);

CREATE TABLE categoria_discapacidad (
    cod_categoria_discapacidad VARCHAR(2)  PRIMARY KEY,
    descripcion                VARCHAR(80) NOT NULL
);

CREATE TABLE etnia (
    cod_etnia   VARCHAR(2)  PRIMARY KEY,
    descripcion VARCHAR(80) NOT NULL
);

CREATE TABLE comunidad_etnica (
    cod_comunidad_etnica VARCHAR(4)   PRIMARY KEY,
    cod_etnia            VARCHAR(2)   NOT NULL REFERENCES etnia,
    descripcion          VARCHAR(100) NOT NULL,
    -- Permite la FK compuesta desde paciente (la comunidad pertenece a la etnia).
    UNIQUE (cod_comunidad_etnica, cod_etnia)
);

CREATE TABLE zona_territorial (
    cod_zona_territorial CHAR(1)     PRIMARY KEY,
    descripcion          VARCHAR(40) NOT NULL
);

CREATE TABLE entidad_responsable (
    cod_entidad VARCHAR(10)  PRIMARY KEY,
    descripcion VARCHAR(150) NOT NULL
);

CREATE TABLE prestador (
    cod_prestador VARCHAR(12)  PRIMARY KEY,          -- código de habilitación
    nombre        VARCHAR(150) NOT NULL
);

CREATE TABLE modalidad_atencion (
    cod_modalidad VARCHAR(2)   PRIMARY KEY,
    descripcion   VARCHAR(100) NOT NULL
);

CREATE TABLE grupo_servicio (
    cod_grupo_servicio VARCHAR(2)   PRIMARY KEY,
    descripcion        VARCHAR(100) NOT NULL
);

CREATE TABLE entorno_atencion (
    cod_entorno VARCHAR(2)   PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL
);

CREATE TABLE via_ingreso (
    cod_via_ingreso VARCHAR(2)   PRIMARY KEY,
    descripcion     VARCHAR(100) NOT NULL
);

CREATE TABLE causa_atencion (
    cod_causa_atencion VARCHAR(2)   PRIMARY KEY,
    descripcion        VARCHAR(100) NOT NULL
);

CREATE TABLE clasificacion_triage (
    cod_triage  SMALLINT    PRIMARY KEY,
    descripcion VARCHAR(80) NOT NULL
);

CREATE TABLE tecnologia_salud (
    cod_tecnologia VARCHAR(15)  PRIMARY KEY,
    descripcion    VARCHAR(250) NOT NULL,
    tipo           VARCHAR(15)  NOT NULL
        CHECK (tipo IN ('PROCEDIMIENTO', 'MEDICAMENTO', 'DISPOSITIVO'))
);

CREATE TABLE finalidad_tecnologia (
    cod_finalidad VARCHAR(2)   PRIMARY KEY,
    descripcion   VARCHAR(100) NOT NULL
);

CREATE TABLE medicamento (
    cod_medicamento VARCHAR(15)  PRIMARY KEY,
    descripcion     VARCHAR(250) NOT NULL
);

CREATE TABLE via_administracion (
    cod_via_administracion VARCHAR(3)  PRIMARY KEY,
    descripcion            VARCHAR(80) NOT NULL
);

CREATE TABLE unidad_medida (
    cod_unidad  VARCHAR(15) PRIMARY KEY,             -- UCUM
    descripcion VARCHAR(80) NOT NULL
);

CREATE TABLE condicion_egreso (
    cod_condicion_egreso VARCHAR(2)   PRIMARY KEY,
    descripcion          VARCHAR(100) NOT NULL
);

CREATE TABLE cie10 (
    cod_cie10   VARCHAR(7)   PRIMARY KEY,
    descripcion VARCHAR(250) NOT NULL
);

CREATE TABLE tipo_diagnostico (
    cod_tipo_diagnostico VARCHAR(2)  PRIMARY KEY,    -- IN, EP, RE, CO, CM
    descripcion          VARCHAR(80) NOT NULL
);

CREATE TABLE loinc (
    cod_loinc   VARCHAR(10)  PRIMARY KEY,
    descripcion VARCHAR(200) NOT NULL
);

CREATE TABLE factor_riesgo (
    cod_factor_riesgo VARCHAR(3)   PRIMARY KEY,
    descripcion       VARCHAR(100) NOT NULL
);

-- ---------------------------------------------------------------------
-- 2. Tablas de núcleo (16)
-- ---------------------------------------------------------------------

CREATE TABLE sede (
    id_sede         INT          PRIMARY KEY,
    cod_prestador   VARCHAR(12)  NOT NULL REFERENCES prestador,       -- campo 21
    cod_municipio   CHAR(5)      NOT NULL REFERENCES municipio,
    nombre_ciudad   VARCHAR(80)  NOT NULL,
    vendor_his      VARCHAR(80)  NOT NULL,
    vendor_emr      VARCHAR(80)  NOT NULL,
    vendor_lis_pacs VARCHAR(80)  NOT NULL
);

-- Cambio frente al Word: se añade id_sede_origen y la unicidad pasa de
-- (tipo, número) a (sede, tipo, número). Con la replicación lógica entre
-- sedes, dos sedes que registren al mismo profesional a la vez chocarían
-- en la restricción única al aplicar la réplica y detendrían el flujo.
-- Cada sede es dueña de sus filas (igual que paciente).
CREATE TABLE profesional_salud (
    id_profesional     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_sede_origen     INT          NOT NULL REFERENCES sede,
    cod_tipo_documento VARCHAR(3)   NOT NULL REFERENCES tipo_documento,   -- campo 56
    numero_documento   VARCHAR(20)  NOT NULL,                             -- campo 57
    nombres            VARCHAR(100) NOT NULL,
    apellidos          VARCHAR(100) NOT NULL,
    UNIQUE (id_sede_origen, cod_tipo_documento, numero_documento)
);

CREATE TABLE paciente (
    id_paciente                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    id_sede_origen             INT         NOT NULL REFERENCES sede,
    cod_tipo_documento         VARCHAR(3)  NOT NULL REFERENCES tipo_documento,        -- 2
    numero_documento           VARCHAR(20) NOT NULL,                                  -- 3
    primer_nombre              VARCHAR(50) NOT NULL,                                  -- 6
    segundo_nombre             VARCHAR(50),                                           -- 7
    primer_apellido            VARCHAR(50) NOT NULL,                                  -- 4
    segundo_apellido           VARCHAR(50),                                           -- 5
    fecha_hora_nacimiento      TIMESTAMP   NOT NULL,                                  -- 8
    cod_sexo                   CHAR(1)     NOT NULL REFERENCES sexo_biologico,        -- 9
    cod_identidad_genero       VARCHAR(2)  REFERENCES identidad_genero,               -- 10
    cod_pais_nacionalidad      CHAR(3)     REFERENCES pais,                           -- 1
    oposicion_donacion         BOOLEAN     NOT NULL DEFAULT FALSE,                    -- 12
    tiene_voluntad_anticipada  BOOLEAN     NOT NULL DEFAULT FALSE,                    -- 13
    cod_categoria_discapacidad VARCHAR(2)  REFERENCES categoria_discapacidad,         -- 14
    cod_pais_residencia        CHAR(3)     NOT NULL REFERENCES pais,                  -- 15
    cod_municipio_residencia   CHAR(5)     REFERENCES municipio,                      -- 16
    cod_etnia                  VARCHAR(2)  REFERENCES etnia,                          -- 17
    cod_comunidad_etnica       VARCHAR(4),                                            -- 18
    cod_zona_territorial       CHAR(1)     REFERENCES zona_territorial,               -- 19
    fhir_patient_id            VARCHAR(64),                      -- NULL = pendiente de migrar
    creado_en                  TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (id_sede_origen, cod_tipo_documento, numero_documento),
    -- La comunidad étnica siempre pertenece a la etnia registrada.
    FOREIGN KEY (cod_comunidad_etnica, cod_etnia)
        REFERENCES comunidad_etnica (cod_comunidad_etnica, cod_etnia),
    CHECK (cod_comunidad_etnica IS NULL OR cod_etnia IS NOT NULL)
);

CREATE TABLE encuentro (
    id_encuentro            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    id_paciente             UUID        NOT NULL REFERENCES paciente,
    id_sede                 INT         NOT NULL REFERENCES sede,                     -- 21 (vía sede → prestador)
    fecha_hora_inicio       TIMESTAMP   NOT NULL,                                     -- 22
    fecha_hora_fin          TIMESTAMP,                                                -- 50
    cod_modalidad           VARCHAR(2)  NOT NULL REFERENCES modalidad_atencion,       -- 23
    cod_grupo_servicio      VARCHAR(2)  NOT NULL REFERENCES grupo_servicio,           -- 24
    cod_entorno             VARCHAR(2)  NOT NULL REFERENCES entorno_atencion,         -- 25
    cod_via_ingreso         VARCHAR(2)  NOT NULL REFERENCES via_ingreso,              -- 26
    cod_causa_atencion      VARCHAR(2)  NOT NULL REFERENCES causa_atencion,           -- 27
    cod_ocupacion           VARCHAR(6)  REFERENCES ocupacion,                         -- 11
    cod_entidad_responsable VARCHAR(10) NOT NULL REFERENCES entidad_responsable,      -- 20
    estado_migracion        VARCHAR(10) NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estado_migracion IN ('PENDIENTE', 'MIGRADO', 'ERROR')),
    CHECK (fecha_hora_fin IS NULL OR fecha_hora_fin >= fecha_hora_inicio)
);

CREATE TABLE triage (
    id_encuentro      UUID      PRIMARY KEY REFERENCES encuentro,
    fecha_hora_triage TIMESTAMP NOT NULL,                                             -- 28
    cod_triage        SMALLINT  NOT NULL REFERENCES clasificacion_triage              -- 29
);

CREATE TABLE egreso (
    id_encuentro             UUID        PRIMARY KEY REFERENCES encuentro,
    cod_condicion_egreso     VARCHAR(2)  NOT NULL REFERENCES condicion_egreso,        -- 48
    cod_prestador_referencia VARCHAR(12) REFERENCES prestador,                        -- 51
    id_profesional_egreso    UUID        NOT NULL REFERENCES profesional_salud,       -- 56, 57
    dias_incapacidad         INT         CHECK (dias_incapacidad >= 0),               -- 52
    dias_licencia_maternidad INT         CHECK (dias_licencia_maternidad >= 0)        -- 53
);

CREATE TABLE diagnostico_encuentro (
    id_diagnostico       UUID       PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro         UUID       NOT NULL REFERENCES encuentro,
    cod_cie10            VARCHAR(7) NOT NULL REFERENCES cie10,                        -- 30, 44, 45, 47, 49
    cod_tipo_diagnostico VARCHAR(2) NOT NULL REFERENCES tipo_diagnostico,
    fecha_diagnostico    DATE       NOT NULL
);

-- A lo sumo un diagnóstico IN, EP y CM por encuentro; RE y CO admiten varios.
CREATE UNIQUE INDEX uq_diagnostico_rol_unico
    ON diagnostico_encuentro (id_encuentro, cod_tipo_diagnostico)
    WHERE cod_tipo_diagnostico IN ('IN', 'EP', 'CM');

CREATE TABLE tecnologia_encuentro (
    id_tecnologia_encuentro UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro            UUID        NOT NULL REFERENCES encuentro,
    cod_tecnologia          VARCHAR(15) NOT NULL REFERENCES tecnologia_salud,         -- 31
    cod_finalidad           VARCHAR(2)  NOT NULL REFERENCES finalidad_tecnologia,     -- 32
    fecha_prescripcion      TIMESTAMP   NOT NULL                                      -- 34
);

CREATE TABLE medicamento_prescrito (
    id_tecnologia_encuentro UUID           PRIMARY KEY REFERENCES tecnologia_encuentro,
    cod_medicamento         VARCHAR(15)    NOT NULL REFERENCES medicamento,           -- 33
    dosis_prescrita         NUMERIC(10,3)  NOT NULL CHECK (dosis_prescrita > 0),      -- 35
    cod_unidad_dosis        VARCHAR(15)    NOT NULL REFERENCES unidad_medida,         -- 35
    cod_via_administracion  VARCHAR(3)     NOT NULL REFERENCES via_administracion,    -- 36
    duracion_tratamiento    INT            NOT NULL CHECK (duracion_tratamiento > 0), -- 37
    cod_unidad_duracion     VARCHAR(15)    NOT NULL REFERENCES unidad_medida,         -- 37
    frecuencia_valor        INT            NOT NULL CHECK (frecuencia_valor >= 0),    -- 38
    cod_unidad_frecuencia   VARCHAR(15)    NOT NULL REFERENCES unidad_medida         -- 38
);

-- Solo puede existir para tecnologías de tipo MEDICAMENTO.
CREATE FUNCTION fn_medicamento_solo_si_es_medicamento() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM tecnologia_encuentro te
          JOIN tecnologia_salud ts ON ts.cod_tecnologia = te.cod_tecnologia
         WHERE te.id_tecnologia_encuentro = NEW.id_tecnologia_encuentro
           AND ts.tipo = 'MEDICAMENTO'
    ) THEN
        RAISE EXCEPTION 'La tecnologia % no es de tipo MEDICAMENTO',
            NEW.id_tecnologia_encuentro
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_medicamento_prescrito_tipo
    BEFORE INSERT OR UPDATE ON medicamento_prescrito
    FOR EACH ROW EXECUTE FUNCTION fn_medicamento_solo_si_es_medicamento();

CREATE TABLE entrega_tecnologia (
    id_entrega              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    id_tecnologia_encuentro UUID          NOT NULL REFERENCES tecnologia_encuentro,
    id_profesional          UUID          NOT NULL REFERENCES profesional_salud,      -- 43
    fecha_entrega           TIMESTAMP     NOT NULL,                                   -- 40
    dosis_administrada      NUMERIC(10,3),                                            -- 39
    dosis_entregada         NUMERIC(10,3),                                            -- 41
    cod_unidad_dosis        VARCHAR(15)   REFERENCES unidad_medida,                   -- 39, 41
    unidades_entregadas     INT           NOT NULL CHECK (unidades_entregadas >= 0),  -- 42
    CHECK ((dosis_administrada IS NULL AND dosis_entregada IS NULL) OR cod_unidad_dosis IS NOT NULL)
);

CREATE TABLE observacion (
    id_observacion      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro        UUID          NOT NULL REFERENCES encuentro,
    cod_loinc           VARCHAR(10)   NOT NULL REFERENCES loinc,                      -- 46
    valor_numerico      NUMERIC(12,4),
    valor_texto         VARCHAR(250),
    cod_unidad          VARCHAR(15)   REFERENCES unidad_medida,
    fecha_hora_medicion TIMESTAMP     NOT NULL,
    CHECK (valor_numerico IS NOT NULL OR valor_texto IS NOT NULL),
    CHECK (valor_numerico IS NULL OR cod_unidad IS NOT NULL)
);

CREATE TABLE antecedente_salud (
    id_antecedente UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro   UUID         NOT NULL REFERENCES encuentro,
    cod_cie10      VARCHAR(7)   REFERENCES cie10,                                     -- 54
    descripcion    VARCHAR(300),
    CHECK (cod_cie10 IS NOT NULL OR descripcion IS NOT NULL)
);

CREATE TABLE exposicion_riesgo (
    id_exposicion     UUID       PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro      UUID       NOT NULL REFERENCES encuentro,
    cod_factor_riesgo VARCHAR(3) NOT NULL REFERENCES factor_riesgo                    -- 55
);

-- Capa federada (MPI). NO se replica: es un dato DERIVADO de paciente
-- (que sí se replica a las tres sedes). Cada sede la materializa
-- localmente con una función determinista, así dos sedes que resuelvan
-- a la vez llegan al mismo id_mpi sin conflictos de réplica.
-- id_paciente es una referencia lógica (el paciente puede vivir en otra
-- sede), por eso no lleva FK a paciente.
CREATE TABLE identidad_federada (
    id_mpi             UUID          PRIMARY KEY,
    score_coincidencia NUMERIC(5,4)  NOT NULL CHECK (score_coincidencia BETWEEN 0 AND 1),
    fecha_creacion     TIMESTAMP     NOT NULL DEFAULT now()
);

CREATE TABLE identidad_federada_paciente (
    id_mpi      UUID NOT NULL REFERENCES identidad_federada,
    id_paciente UUID NOT NULL,
    id_sede     INT  NOT NULL REFERENCES sede,
    PRIMARY KEY (id_mpi, id_paciente),
    UNIQUE (id_paciente)                    -- un registro pertenece a una sola identidad
);

-- Cambio frente al Word: se añade bundle_json, una copia del documento
-- FHIR. Se replica a las demás sedes, de modo que el RDA de una sede
-- sigue consultable aunque su HAPI FHIR (o la sede entera) esté caído.
-- El documento canónico sigue en el HAPI FHIR de la sede dueña.
CREATE TABLE composicion_bundle (
    id_bundle        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    id_encuentro     UUID        NOT NULL UNIQUE REFERENCES encuentro,
    fhir_bundle_id   VARCHAR(64) NOT NULL,
    fecha_generacion TIMESTAMP   NOT NULL DEFAULT now(),
    bundle_json      JSONB
);

-- ---------------------------------------------------------------------
-- 3. Índices de apoyo (consultas del MPI, cobertura y búsquedas)
-- ---------------------------------------------------------------------

CREATE INDEX ix_paciente_documento  ON paciente (cod_tipo_documento, numero_documento);
CREATE INDEX ix_paciente_pendientes ON paciente (id_sede_origen) WHERE fhir_patient_id IS NULL;
CREATE INDEX ix_encuentro_paciente  ON encuentro (id_paciente);
CREATE INDEX ix_encuentro_pendiente ON encuentro (id_sede) WHERE estado_migracion = 'PENDIENTE';
CREATE INDEX ix_diagnostico_enc     ON diagnostico_encuentro (id_encuentro);
-- Decisión humana sobre un par de registros que el MPI no resuelve solo (gemelos, homónimos, documento repetido por
-- error). A DIFERENCIA de identidad_federada*, esta tabla SÍ se replica: todas las sedes aplican la misma decisión.
-- Para cada par vale la más reciente (fecha_decision, id_sede_origen, id_decision), así dos decisiones opuestas en
-- sedes distintas se resuelven igual en todas. Sin FK a paciente: la decisión puede llegar a una sede antes que el
-- registro de otra sede (las suscripciones son independientes) y una FK detendría la réplica.
-- No es parte del modelo de 45 tablas del documento Word: se agregó para poder corregir falsos positivos y negativos.
CREATE TABLE mpi_decision (
    id_decision    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_sede_origen INT          NOT NULL REFERENCES sede,
    id_paciente_a  UUID         NOT NULL,
    id_paciente_b  UUID         NOT NULL,
    decision       VARCHAR(20)  NOT NULL CHECK (decision IN ('MISMA_PERSONA', 'PERSONAS_DISTINTAS')),
    decidido_por   VARCHAR(60)  NOT NULL,
    motivo         VARCHAR(300),
    fecha_decision TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (id_paciente_a < id_paciente_b)            -- par canónico: (a, b) y (b, a) son la misma decisión
);
CREATE INDEX ix_mpi_decision_a ON mpi_decision (id_paciente_a);
CREATE INDEX ix_mpi_decision_b ON mpi_decision (id_paciente_b);

CREATE INDEX ix_tecnologia_enc      ON tecnologia_encuentro (id_encuentro);
CREATE INDEX ix_entrega_tecnologia  ON entrega_tecnologia (id_tecnologia_encuentro);
CREATE INDEX ix_observacion_enc     ON observacion (id_encuentro);
CREATE INDEX ix_antecedente_enc     ON antecedente_salud (id_encuentro);
CREATE INDEX ix_exposicion_enc      ON exposicion_riesgo (id_encuentro);
CREATE INDEX ix_idfed_paciente_mpi  ON identidad_federada_paciente (id_mpi);
