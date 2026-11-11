-- Catálogos que usa el bus de integración (HSB) con los mensajes de ejemplo del parcial. Idempotente.
-- Una sede nueva ya los trae (db/02_semillas_catalogos.sql). Se aplica con scripts/migrar_sql.sh.
INSERT INTO cie10 VALUES
    ('J45.9', 'Asma, no especificada'),
    ('N39.0', 'Infección de vías urinarias, sitio no especificado'),
    ('M54.5', 'Lumbago no especificado'),
    ('R51',   'Cefalea')
ON CONFLICT DO NOTHING;

INSERT INTO loinc VALUES ('718-7', 'Hemoglobina [Masa/Volumen] en sangre') ON CONFLICT DO NOTHING;

INSERT INTO unidad_medida VALUES ('g/dL', 'Gramo por decilitro') ON CONFLICT DO NOTHING;
