-- Esquema de la base del bus (idempotente: se ejecuta en cada arranque).

-- Un renglón por mensaje recibido. `clave` es la clave de idempotencia: MSH-10 en HL7 y el hash del contenido
-- de cada fila en CSV. Vive en la base (no en memoria): reiniciar el bus no deja pasar un duplicado.
CREATE TABLE IF NOT EXISTS mensaje_bus (
    id_mensaje      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    clave           TEXT        NOT NULL UNIQUE,
    hash_contenido  TEXT        NOT NULL,
    formato         TEXT        NOT NULL CHECK (formato IN ('HL7', 'CSV')),
    tipo            TEXT,
    sede            INT,
    documento       TEXT,
    estado          TEXT        NOT NULL CHECK (estado IN
                    ('recibido', 'validado', 'transformado', 'entregado', 'rechazado', 'reintentando', 'muerto')),
    contenido       TEXT        NOT NULL,
    motivos         JSONB       NOT NULL DEFAULT '[]',
    canonico        JSONB,
    bundle          JSONB,
    hapi_ok         BOOLEAN     NOT NULL DEFAULT FALSE,
    nodo_ok         BOOLEAN     NOT NULL DEFAULT FALSE,
    intentos        INT         NOT NULL DEFAULT 0,
    proximo_intento TIMESTAMPTZ,
    ultimo_error    TEXT,
    duplicados      INT         NOT NULL DEFAULT 0,
    recibido_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    entregado_en    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_mensaje_estado ON mensaje_bus (estado, proximo_intento);
CREATE INDEX IF NOT EXISTS ix_mensaje_recibido ON mensaje_bus (recibido_en);

-- Bitácora de cada transición de estado (de aquí salen los logs de «falla, se reintenta y se entrega»).
CREATE TABLE IF NOT EXISTS evento_mensaje (
    id_evento   BIGSERIAL   PRIMARY KEY,
    id_mensaje  UUID        NOT NULL REFERENCES mensaje_bus ON DELETE CASCADE,
    fecha       TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado      TEXT        NOT NULL,
    intento     INT         NOT NULL DEFAULT 0,
    detalle     TEXT
);
CREATE INDEX IF NOT EXISTS ix_evento_mensaje ON evento_mensaje (id_mensaje, id_evento);

-- Terminología: diagnóstico local (texto del sistema legado) -> CIE-10. Se siembra desde datos/ref_terminologia.csv.
CREATE TABLE IF NOT EXISTS ref_terminologia (
    dx_local    TEXT PRIMARY KEY,
    cie10       TEXT NOT NULL,
    descripcion TEXT NOT NULL
);
