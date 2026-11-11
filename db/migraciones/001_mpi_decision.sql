-- Migración para sedes YA desplegadas: agrega mpi_decision y la publica. Idempotente.
-- Una sede nueva (db/01 y db/03) ya la trae. Se aplica con scripts/migrar_mpi_decision.sh, que además refresca las suscripciones.
CREATE TABLE IF NOT EXISTS mpi_decision (
    id_decision    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_sede_origen INT          NOT NULL REFERENCES sede,
    id_paciente_a  UUID         NOT NULL,
    id_paciente_b  UUID         NOT NULL,
    decision       VARCHAR(20)  NOT NULL CHECK (decision IN ('MISMA_PERSONA', 'PERSONAS_DISTINTAS')),
    decidido_por   VARCHAR(60)  NOT NULL,
    motivo         VARCHAR(300),
    fecha_decision TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (id_paciente_a < id_paciente_b)
);
CREATE INDEX IF NOT EXISTS ix_mpi_decision_a ON mpi_decision (id_paciente_a);
CREATE INDEX IF NOT EXISTS ix_mpi_decision_b ON mpi_decision (id_paciente_b);

GRANT SELECT ON mpi_decision TO replicator;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname = 'pub_sede' AND tablename = 'mpi_decision') THEN
        ALTER PUBLICATION pub_sede ADD TABLE mpi_decision;
    END IF;
END $$;
