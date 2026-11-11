-- =====================================================================
-- Pruebas de las restricciones del esquema de 57 campos.
-- Todo corre dentro de una transacción que termina en ROLLBACK.
--
-- Uso (desde la raíz del repo, contra un nodo ya inicializado):
--   docker exec -i pg_sincelejo psql -U admin -d historia_clinica \
--       -v ON_ERROR_STOP=1 < db/tests/test_restricciones.sql
-- Termina con error (código != 0) si alguna prueba falla.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE resultados (nombre text, ok boolean, detalle text);

-- Ejecuta stmt y verifica el SQLSTATE esperado (NULL = debe tener éxito).
CREATE FUNCTION pg_temp.esperar(nombre text, sqlstate_esperado text, stmt text)
RETURNS void AS $$
DECLARE
    obtenido text := NULL;
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN OTHERS THEN
        obtenido := SQLSTATE;
    END;
    INSERT INTO resultados VALUES (
        nombre,
        obtenido IS NOT DISTINCT FROM sqlstate_esperado,
        format('esperado=%s obtenido=%s', coalesce(sqlstate_esperado, 'OK'), coalesce(obtenido, 'OK'))
    );
END;
$$ LANGUAGE plpgsql;

-- ---------- Estructura -------------------------------------------------
SELECT pg_temp.esperar('estructura: 46 tablas (45 del modelo + mpi_decision)',
    NULL,
    $$ DO $x$ BEGIN
         IF (SELECT count(*) FROM information_schema.tables
              WHERE table_schema = 'public' AND table_type = 'BASE TABLE') <> 46
         THEN RAISE EXCEPTION 'no hay 46 tablas'; END IF;
       END $x$ $$);

SELECT pg_temp.esperar('estructura: 3 sedes sembradas',
    NULL,
    $$ DO $x$ BEGIN
         IF (SELECT count(*) FROM sede) <> 3 THEN RAISE EXCEPTION 'no hay 3 sedes'; END IF;
       END $x$ $$);

-- ---------- Datos base -------------------------------------------------
INSERT INTO profesional_salud (id_profesional, id_sede_origen, cod_tipo_documento, numero_documento, nombres, apellidos)
VALUES ('00000000-0000-0000-0000-0000000000f1', 1, 'CC', '77889900', 'Camila', 'Restrepo');

INSERT INTO paciente (id_paciente, id_sede_origen, cod_tipo_documento, numero_documento,
                      primer_nombre, primer_apellido, fecha_hora_nacimiento, cod_sexo,
                      cod_pais_residencia, cod_etnia, cod_zona_territorial)
VALUES ('00000000-0000-0000-0000-0000000000a1', 1, 'CC', '1001234567', 'Ana', 'Torres',
        '1992-04-12 10:00', 'F', 'COL', '06', '1');

INSERT INTO encuentro (id_encuentro, id_paciente, id_sede, fecha_hora_inicio, cod_modalidad,
                       cod_grupo_servicio, cod_entorno, cod_via_ingreso, cod_causa_atencion,
                       cod_entidad_responsable)
VALUES ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000a1', 1,
        '2026-03-15 08:30', '01', '01', '01', '01', '01', 'EPS001');

INSERT INTO tecnologia_encuentro (id_tecnologia_encuentro, id_encuentro, cod_tecnologia,
                                  cod_finalidad, fecha_prescripcion)
VALUES ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000e1',
        '19938', '02', '2026-03-15 08:45'),
       ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000e1',
        '890201', '01', '2026-03-15 08:45');

-- ---------- Camino feliz -----------------------------------------------
SELECT pg_temp.esperar('paciente: mismo documento en OTRA sede es válido (lo resuelve el MPI)',
    NULL,
    $$ INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
                             primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia)
       VALUES (2, 'CC', '1001234567', 'Ana', 'Torres', '1992-04-12 10:00', 'F', 'COL') $$);

SELECT pg_temp.esperar('medicamento_prescrito: válido para tecnología MEDICAMENTO',
    NULL,
    $$ INSERT INTO medicamento_prescrito VALUES
       ('00000000-0000-0000-0000-0000000000b1', '19938', 500, 'mg', '01', 5, 'd', 8, 'h') $$);

SELECT pg_temp.esperar('diagnostico: varios RE en el mismo encuentro son válidos',
    NULL,
    $$ INSERT INTO diagnostico_encuentro (id_encuentro, cod_cie10, cod_tipo_diagnostico, fecha_diagnostico)
       VALUES ('00000000-0000-0000-0000-0000000000e1', 'J00', 'RE', '2026-03-15'),
              ('00000000-0000-0000-0000-0000000000e1', 'R50.9', 'RE', '2026-03-15') $$);

-- ---------- Violaciones esperadas (SQLSTATE) ---------------------------
-- 23505 = unique_violation, 23503 = foreign_key_violation, 23514 = check_violation
SELECT pg_temp.esperar('paciente: documento duplicado en la misma sede',
    '23505',
    $$ INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
                             primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia)
       VALUES (1, 'CC', '1001234567', 'Otra', 'Persona', '1990-01-01', 'F', 'COL') $$);

SELECT pg_temp.esperar('paciente: código de sexo fuera de catálogo',
    '23503',
    $$ INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
                             primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia)
       VALUES (1, 'CC', '555', 'X', 'Y', '1990-01-01', 'X', 'COL') $$);

SELECT pg_temp.esperar('paciente: comunidad étnica que no pertenece a la etnia',
    '23503',
    $$ INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
                             primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia,
                             cod_etnia, cod_comunidad_etnica)
       VALUES (1, 'CC', '556', 'X', 'Y', '1990-01-01', 'F', 'COL', '05', '0101') $$);

SELECT pg_temp.esperar('paciente: comunidad étnica sin etnia',
    '23514',
    $$ INSERT INTO paciente (id_sede_origen, cod_tipo_documento, numero_documento, primer_nombre,
                             primer_apellido, fecha_hora_nacimiento, cod_sexo, cod_pais_residencia,
                             cod_comunidad_etnica)
       VALUES (1, 'CC', '557', 'X', 'Y', '1990-01-01', 'F', 'COL', '0101') $$);

SELECT pg_temp.esperar('encuentro: fecha de fin anterior al inicio',
    '23514',
    $$ UPDATE encuentro SET fecha_hora_fin = '2026-03-15 07:00'
        WHERE id_encuentro = '00000000-0000-0000-0000-0000000000e1' $$);

SELECT pg_temp.esperar('encuentro: estado_migracion inválido',
    '23514',
    $$ UPDATE encuentro SET estado_migracion = 'OTRO'
        WHERE id_encuentro = '00000000-0000-0000-0000-0000000000e1' $$);

SELECT pg_temp.esperar('diagnostico: segundo diagnóstico de ingreso (IN) en el encuentro',
    '23505',
    $$ INSERT INTO diagnostico_encuentro (id_encuentro, cod_cie10, cod_tipo_diagnostico, fecha_diagnostico)
       VALUES ('00000000-0000-0000-0000-0000000000e1', 'J00', 'IN', '2026-03-15'),
              ('00000000-0000-0000-0000-0000000000e1', 'I10', 'IN', '2026-03-15') $$);

SELECT pg_temp.esperar('medicamento_prescrito: tecnología que no es MEDICAMENTO',
    '23514',
    $$ INSERT INTO medicamento_prescrito VALUES
       ('00000000-0000-0000-0000-0000000000b2', '19938', 500, 'mg', '01', 5, 'd', 8, 'h') $$);

SELECT pg_temp.esperar('observacion: sin valor numérico ni texto',
    '23514',
    $$ INSERT INTO observacion (id_encuentro, cod_loinc, fecha_hora_medicion)
       VALUES ('00000000-0000-0000-0000-0000000000e1', '8310-5', '2026-03-15 09:10') $$);

SELECT pg_temp.esperar('observacion: valor numérico sin unidad',
    '23514',
    $$ INSERT INTO observacion (id_encuentro, cod_loinc, valor_numerico, fecha_hora_medicion)
       VALUES ('00000000-0000-0000-0000-0000000000e1', '8310-5', 38.5, '2026-03-15 09:10') $$);

SELECT pg_temp.esperar('observacion: valor numérico con unidad es válido',
    NULL,
    $$ INSERT INTO observacion (id_encuentro, cod_loinc, valor_numerico, cod_unidad, fecha_hora_medicion)
       VALUES ('00000000-0000-0000-0000-0000000000e1', '8310-5', 38.5, 'C', '2026-03-15 09:10') $$);

SELECT pg_temp.esperar('antecedente: sin CIE-10 ni descripción',
    '23514',
    $$ INSERT INTO antecedente_salud (id_encuentro)
       VALUES ('00000000-0000-0000-0000-0000000000e1') $$);

SELECT pg_temp.esperar('profesional: documento duplicado en la misma sede',
    '23505',
    $$ INSERT INTO profesional_salud (id_sede_origen, cod_tipo_documento, numero_documento, nombres, apellidos)
       VALUES (1, 'CC', '77889900', 'Otra', 'Persona') $$);

SELECT pg_temp.esperar('profesional: mismo documento en OTRA sede es válido (sin conflicto de réplica)',
    NULL,
    $$ INSERT INTO profesional_salud (id_sede_origen, cod_tipo_documento, numero_documento, nombres, apellidos)
       VALUES (2, 'CC', '77889900', 'Camila', 'Restrepo') $$);

SELECT pg_temp.esperar('composicion_bundle: segundo bundle para el mismo encuentro',
    '23505',
    $$ INSERT INTO composicion_bundle (id_encuentro, fhir_bundle_id)
       VALUES ('00000000-0000-0000-0000-0000000000e1', '1001'),
              ('00000000-0000-0000-0000-0000000000e1', '1002') $$);

SELECT pg_temp.esperar('MPI: una identidad válida con dos pacientes de distintas sedes',
    NULL,
    $$ INSERT INTO identidad_federada (id_mpi, score_coincidencia)
       VALUES ('00000000-0000-0000-0000-0000000000c1', 1.0);
       INSERT INTO identidad_federada_paciente (id_mpi, id_paciente, id_sede)
       VALUES ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000a1', 1) $$);

SELECT pg_temp.esperar('MPI: un paciente no puede estar en dos identidades',
    '23505',
    $$ INSERT INTO identidad_federada (id_mpi, score_coincidencia)
       VALUES ('00000000-0000-0000-0000-0000000000c2', 0.95);
       INSERT INTO identidad_federada_paciente (id_mpi, id_paciente, id_sede)
       VALUES ('00000000-0000-0000-0000-0000000000c2', '00000000-0000-0000-0000-0000000000a1', 1) $$);

SELECT pg_temp.esperar('MPI: score fuera de rango [0,1]',
    '23514',
    $$ INSERT INTO identidad_federada (id_mpi, score_coincidencia)
       VALUES ('00000000-0000-0000-0000-0000000000c3', 1.5) $$);

SELECT pg_temp.esperar('MPI decisión: par canónico válido, sin FK a paciente (puede llegar antes que el registro)',
    NULL,
    $$ INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por)
       VALUES (1, '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a9', 'MISMA_PERSONA', 'medico') $$);

SELECT pg_temp.esperar('MPI decisión: el par debe venir en orden canónico (a < b)',
    '23514',
    $$ INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por)
       VALUES (1, '00000000-0000-0000-0000-0000000000a9', '00000000-0000-0000-0000-0000000000a1', 'MISMA_PERSONA', 'medico') $$);

SELECT pg_temp.esperar('MPI decisión: un registro no puede decidirse contra sí mismo',
    '23514',
    $$ INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por)
       VALUES (1, '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a1', 'MISMA_PERSONA', 'medico') $$);

SELECT pg_temp.esperar('MPI decisión: valor de decisión inválido',
    '23514',
    $$ INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por)
       VALUES (1, '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a9', 'QUIZAS', 'medico') $$);

SELECT pg_temp.esperar('MPI decisión: la sede de origen debe existir',
    '23503',
    $$ INSERT INTO mpi_decision (id_sede_origen, id_paciente_a, id_paciente_b, decision, decidido_por)
       VALUES (99, '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a9', 'MISMA_PERSONA', 'medico') $$);

SELECT pg_temp.esperar('egreso: profesional inexistente',
    '23503',
    $$ INSERT INTO egreso (id_encuentro, cod_condicion_egreso, id_profesional_egreso)
       VALUES ('00000000-0000-0000-0000-0000000000e1', '01', '00000000-0000-0000-0000-00000000ffff') $$);

-- ---------- Reporte ----------------------------------------------------
SELECT CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS resultado, nombre, detalle
  FROM resultados
 ORDER BY ok, nombre;

DO $$
DECLARE
    fallos int;
    total  int;
BEGIN
    SELECT count(*) FILTER (WHERE NOT ok), count(*) INTO fallos, total FROM resultados;
    RAISE NOTICE 'Pruebas: % / % correctas', total - fallos, total;
    IF fallos > 0 THEN
        RAISE EXCEPTION '% prueba(s) fallaron', fallos;
    END IF;
END $$;

ROLLBACK;
