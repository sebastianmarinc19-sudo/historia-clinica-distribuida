-- =====================================================================
-- Semillas de catálogos y de las 3 sedes.
--
-- DATOS DE PRUEBA: se propusieron a partir del nombre de cada campo y
-- de los ejemplos del informe de laboratorio. Deben confirmarse contra
-- el Anexo Técnico de la Resolución 866/2021 antes de usar datos reales.
-- Los códigos de prestador son sintéticos.
-- Idéntico en las tres sedes (los catálogos no se replican).
-- =====================================================================

INSERT INTO pais VALUES
    ('COL', 'Colombia'), ('VEN', 'Venezuela'), ('ECU', 'Ecuador'),
    ('PER', 'Perú'), ('PAN', 'Panamá'), ('USA', 'Estados Unidos'),
    ('ESP', 'España');

INSERT INTO departamento VALUES
    ('13', 'Bolívar'), ('23', 'Córdoba'), ('70', 'Sucre');

INSERT INTO municipio VALUES
    ('13001', '13', 'Cartagena de Indias'),
    ('23001', '23', 'Montería'),
    ('70001', '70', 'Sincelejo'),
    ('70215', '70', 'Corozal');

INSERT INTO tipo_documento VALUES
    ('CC', 'Cédula de ciudadanía'), ('TI', 'Tarjeta de identidad'),
    ('RC', 'Registro civil'), ('CE', 'Cédula de extranjería'),
    ('PA', 'Pasaporte'), ('PT', 'Permiso por protección temporal');

INSERT INTO sexo_biologico VALUES
    ('F', 'Mujer'), ('M', 'Hombre'), ('I', 'Intersexual');

INSERT INTO identidad_genero VALUES
    ('01', 'Masculino'), ('02', 'Femenino'), ('03', 'Transgénero'),
    ('04', 'No binario'), ('99', 'Otro');

INSERT INTO ocupacion VALUES
    ('231000', 'Profesionales de la enseñanza'),
    ('221000', 'Profesionales de la salud'),
    ('411000', 'Empleados administrativos'),
    ('521000', 'Vendedores y comerciantes'),
    ('611000', 'Trabajadores agropecuarios'),
    ('999999', 'Sin ocupación informada');

INSERT INTO categoria_discapacidad VALUES
    ('01', 'Física'), ('02', 'Auditiva'), ('03', 'Visual'),
    ('04', 'Sordoceguera'), ('05', 'Intelectual'),
    ('06', 'Psicosocial'), ('07', 'Múltiple');

INSERT INTO etnia VALUES
    ('01', 'Indígena'), ('02', 'ROM (gitano)'), ('03', 'Raizal'),
    ('04', 'Palenquero'), ('05', 'Negro, mulato, afrodescendiente'),
    ('06', 'Ninguna de las anteriores');

INSERT INTO comunidad_etnica VALUES
    ('0101', '01', 'Zenú'),
    ('0102', '01', 'Wayuu'),
    ('0401', '04', 'San Basilio de Palenque'),
    ('0501', '05', 'Consejo comunitario afrodescendiente');

INSERT INTO zona_territorial VALUES
    ('1', 'Urbana'), ('2', 'Rural');

INSERT INTO entidad_responsable VALUES
    ('EPS001', 'EPS de prueba 001'), ('EPS002', 'EPS de prueba 002'),
    ('PART',   'Particular');

-- Un solo prestador que opera las tres sedes (relación 1:N con sede).
INSERT INTO prestador VALUES
    ('700010000001', 'IPS Red Caribe (sintético)'),
    ('130010000001', 'IPS Externa Cartagena (sintético)');

INSERT INTO modalidad_atencion VALUES
    ('01', 'Intramural'), ('02', 'Extramural'),
    ('03', 'Telemedicina'), ('04', 'Telemedicina interactiva');

INSERT INTO grupo_servicio VALUES
    ('01', 'Consulta externa'), ('02', 'Apoyo diagnóstico y complementación terapéutica'),
    ('03', 'Internación'), ('04', 'Quirúrgico'), ('05', 'Atención inmediata (urgencias)');

INSERT INTO entorno_atencion VALUES
    ('01', 'Institucional'), ('02', 'Domiciliario'),
    ('03', 'Comunitario'), ('04', 'Educativo'), ('05', 'Laboral');

INSERT INTO via_ingreso VALUES
    ('01', 'Urgencias'), ('02', 'Consulta externa o programada'),
    ('03', 'Remitido'), ('04', 'Nacido en la institución');

INSERT INTO causa_atencion VALUES
    ('01', 'Enfermedad general'), ('02', 'Accidente de tránsito'),
    ('03', 'Accidente de trabajo'), ('04', 'Lesión por agresión'),
    ('05', 'Promoción y prevención');

INSERT INTO clasificacion_triage VALUES
    (1, 'Triage I - Reanimación'), (2, 'Triage II - Emergencia'),
    (3, 'Triage III - Urgente'), (4, 'Triage IV - Menos urgente'),
    (5, 'Triage V - No urgente');

INSERT INTO tecnologia_salud VALUES
    ('890201', 'Consulta de primera vez por medicina general', 'PROCEDIMIENTO'),
    ('902210', 'Hemograma',                                      'PROCEDIMIENTO'),
    ('19938',  'Acetaminofén 500 mg tableta',                   'MEDICAMENTO'),
    ('20001',  'Ibuprofeno 400 mg tableta',                     'MEDICAMENTO'),
    ('DISP01', 'Nebulizador',                                    'DISPOSITIVO');

INSERT INTO finalidad_tecnologia VALUES
    ('01', 'Diagnóstico'), ('02', 'Tratamiento'),
    ('03', 'Rehabilitación'), ('04', 'Protección específica'),
    ('05', 'Detección temprana');

INSERT INTO medicamento VALUES
    ('19938', 'Acetaminofén'), ('20001', 'Ibuprofeno'),
    ('30010', 'Amoxicilina'), ('40005', 'Losartán');

INSERT INTO via_administracion VALUES
    ('01', 'Oral'), ('02', 'Intravenosa'), ('03', 'Intramuscular'),
    ('04', 'Subcutánea'), ('05', 'Tópica'), ('06', 'Inhalatoria');

INSERT INTO unidad_medida VALUES
    ('mg',    'Miligramo'),
    ('g',     'Gramo'),
    ('mL',    'Mililitro'),
    ('kg',    'Kilogramo'),
    ('cm',    'Centímetro'),
    ('min',   'Minuto'),
    ('h',     'Hora'),
    ('d',     'Día'),
    ('C',     'Grados Celsius (UCUM: Cel)'),
    ('mm[Hg]','Milímetros de mercurio'),
    ('g/dL',  'Gramo por decilitro');                      -- la usa el bus de integración (HSB)

INSERT INTO condicion_egreso VALUES
    ('01', 'Vivo - mejoría'), ('02', 'Vivo - sin mejoría'),
    ('03', 'Remitido a otra institución'), ('04', 'Fallecido'),
    ('05', 'Egreso voluntario');

INSERT INTO cie10 VALUES
    ('J00',   'Rinofaringitis aguda (resfriado común)'),
    ('J18.9', 'Neumonía, no especificada'),
    ('I10',   'Hipertensión esencial (primaria)'),
    ('E11.9', 'Diabetes mellitus tipo 2 sin complicaciones'),
    ('E66.9', 'Obesidad, no especificada'),
    ('A09',   'Diarrea y gastroenteritis de presunto origen infeccioso'),
    ('R50.9', 'Fiebre, no especificada'),
    ('K29.7', 'Gastritis, no especificada'),
    -- los usa el bus de integración (HSB) para los diagnósticos de los sistemas legados
    ('J45.9', 'Asma, no especificada'),
    ('N39.0', 'Infección de vías urinarias, sitio no especificado'),
    ('M54.5', 'Lumbago no especificado'),
    ('R51',   'Cefalea');

INSERT INTO tipo_diagnostico VALUES
    ('IN', 'Diagnóstico principal de ingreso'),
    ('EP', 'Diagnóstico principal de egreso'),
    ('RE', 'Diagnóstico relacionado'),
    ('CO', 'Diagnóstico de la complicación'),
    ('CM', 'Causa básica de muerte');

INSERT INTO loinc VALUES
    ('8310-5',  'Temperatura corporal'),
    ('8480-6',  'Presión arterial sistólica'),
    ('8462-4',  'Presión arterial diastólica'),
    ('29463-7', 'Peso corporal'),
    ('8302-2',  'Talla corporal'),
    ('718-7',   'Hemoglobina [Masa/Volumen] en sangre');       -- la usa el bus de integración (HSB)

INSERT INTO factor_riesgo VALUES
    ('001', 'Tabaquismo'), ('002', 'Consumo de alcohol'),
    ('003', 'Sedentarismo'), ('004', 'Obesidad'),
    ('005', 'Exposición laboral a químicos');

-- Las tres sedes. Vendors de Sincelejo y Cartagena tomados del
-- Laboratorio N.º 5; los de Corozal son marcadores por confirmar.
INSERT INTO sede (id_sede, cod_prestador, cod_municipio, nombre_ciudad,
                  vendor_his, vendor_emr, vendor_lis_pacs) VALUES
    (1, '700010000001', '70001', 'Sincelejo',
        'Meditech', 'OpenMRS', 'Appliance dedicado'),
    (2, '700010000001', '13001', 'Cartagena',
        'Cerner', 'Vendor propio', 'Appliance imagenología'),
    (3, '700010000001', '70215', 'Corozal',
        'Vendor Z', 'SaaS regional (Vendor Z)', 'Por confirmar');
