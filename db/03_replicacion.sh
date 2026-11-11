#!/bin/bash
# Prepara cada sede para replicar con las demás:
#   - rol 'replicator' (solo lectura de las tablas publicadas),
#   - publicación 'pub_sede' con las tablas de núcleo clínico.
#
# Tablas NO publicadas: catálogos y sede (idénticos por semilla en cada
# nodo) e identidad_federada* (dato derivado, se materializa por nodo).
# mpi_decision (decisiones humanas del MPI) SÍ se publica.
# Las suscripciones cruzadas se crean después, cuando los tres nodos
# están arriba (scripts/configurar_suscripciones.sh).
set -e

: "${REPLICATION_PASSWORD:?Defina REPLICATION_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE replicator WITH LOGIN REPLICATION PASSWORD '${REPLICATION_PASSWORD}';

GRANT SELECT ON
    profesional_salud, paciente, encuentro, triage, egreso,
    diagnostico_encuentro, tecnologia_encuentro, medicamento_prescrito,
    entrega_tecnologia, observacion, antecedente_salud, exposicion_riesgo,
    composicion_bundle, mpi_decision
TO replicator;

-- Sin TRUNCATE: un truncado accidental en una sede no debe borrar las demás.
CREATE PUBLICATION pub_sede FOR TABLE
    profesional_salud, paciente, encuentro, triage, egreso,
    diagnostico_encuentro, tecnologia_encuentro, medicamento_prescrito,
    entrega_tecnologia, observacion, antecedente_salud, exposicion_riesgo,
    composicion_bundle, mpi_decision
WITH (publish = 'insert, update, delete');
EOSQL

echo "Replicación preparada: rol replicator y publicación pub_sede."
