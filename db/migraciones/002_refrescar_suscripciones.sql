-- Fase 2 de la migración 001: cuando mpi_decision existe en las TRES sedes, cada suscripción debe enterarse de la tabla nueva.
-- copy_data = false: las sedes están vacías de decisiones (y las que ya existan se replican desde ahora).
-- Cada ALTER va como sentencia propia (\gexec) porque no puede ejecutarse dentro de una transacción.
SELECT format('ALTER SUBSCRIPTION %I REFRESH PUBLICATION WITH (copy_data = false)', subname) FROM pg_subscription \gexec
