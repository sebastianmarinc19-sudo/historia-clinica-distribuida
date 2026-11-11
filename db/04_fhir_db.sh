#!/bin/bash
# Base de datos propia de HAPI FHIR en cada sede.
# Es una base distinta de historia_clinica, así que la replicación lógica
# (que es por base de datos) no la toca: cada sede conserva sus propios
# recursos FHIR.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -c "CREATE DATABASE fhir_db"

echo "Base fhir_db creada para el HAPI FHIR de esta sede."
