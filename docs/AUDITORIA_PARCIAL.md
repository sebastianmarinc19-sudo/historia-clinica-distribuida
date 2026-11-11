# Auditoría frente a la guía del Parcial Final (8 de noviembre de 2026)

Se contrastó el repositorio (rama `reingenieria-3-sedes`) con la guía general, las 5 guías por fase y los mensajes de ejemplo del paquete del parcial.
Cada afirmación sobre el código se verificó en el repositorio. Los puntos son **una lectura mía de la rúbrica, no una nota**: el criterio lo aplica el docente.

> **Actualización (8 de noviembre de 2026, tras implementar el HSB):** RF1, RF3 y los criterios «HSB» y «Terminologías y métricas» pasan a **cumplidos** (secciones 2, 3 y 5 marcadas abajo).
> La auditoría encadenada por hash (P3), las vistas con el Reporte de HC (P4) y el `docker compose up` de un solo comando (P5) y la evidencia ACID (P6) también están hechos. Lo único abierto es lo que solo el equipo puede hacer (commits, `v1.0`, repositorio, sustentación). Lo que se afirma del HSB está verificado: 68 pruebas con PostgreSQL real, API 123/123, guion en vivo en Kubernetes y escenario en Compose; detalle en el README.

## 1. Resumen

**Lo fuerte (y que la rúbrica premia o da como bonus):** sedes que sobreviven a la caída de otra, réplica lógica con sede dueña, identidad federada con decisión humana,
autenticación por roles con el control en la API (no solo en pantalla), TLS, FHIR R4 con HAPI por sede, 4 vistas, `/health` y `/metrics` en la API, Kubernetes probado en
Minikube, pruebas de carga, Prometheus, 123 pruebas de API + 67 del HSB + 14 E2E + failover, CI/CD y respaldos cifrados, y ahora el **bus de integración (HSB)** con HL7 v2 y CSV.

**Lo que falta y pesa más:** la **auditoría encadenada por
hash con verificador**, la vista **Reporte de HC** por paciente, **validar los Bundle contra HAPI**, **`docker compose up` en un solo comando** y varios entregables del informe (bitácora con declaración de IA,
mapeo HL7/CSV→FHIR, UML alineados a la guía, presentación).

Orden de magnitud: antes del HSB se cubría aproximadamente **2,0 a 2,7 de 5,0**; con el HSB (≈1,1 de los 1,25 de la fase) sube a **≈3,1 a 3,8** (sin sustentación ni bonus). Cerrar P2 a P5 lo acercaría a 4 o más.

## 2. Requisitos funcionales y no funcionales

| Id | Requisito | Estado | Evidencia / brecha |
|---|---|---|---|
| RF1 | Ingerir las 3 sedes en ≥2 formatos (HL7 v2 ADT/ORU y CSV/JSON) | **Cumple** | `POST /hsb/hl7` (ADT^A01, ORU^R01) y `POST /hsb/csv?sede=N`; los 4 ejemplos del paquete dan el resultado esperado (`hsb/`, `ejemplos/`) |
| RF2 | Normalizar a FHIR R4: Patient, Encounter, Observation, Condition (CIE-10) en Bundle | **Parcial** | `fhir.py` genera los cuatro recursos, pero dentro de un Bundle `document` que se **POSTea** (HAPI asigna el id). En HAPI solo existe el Patient como recurso propio; Encounter, Condition y Observation viven dentro del Bundle. Los ejemplos piden `PUT` con ids deterministas (`pac-<documento>`) para que reenviar no duplique. **`$validate` se ejecutó el 9 de noviembre**: los 5 Bundle de `fhir/ejemplos/` (3 del HSB y el RDA como `document` y como `transaction`) dan 0 errores y solo advertencias (narrativa, «performer»). Encontró un error real (fechas con hora sin zona horaria) que se corrigió en el bus y en el RDA. El RDA de la API ahora usa `PUT` con ids deterministas y recursos propios en HAPI (4 pruebas; migrar dos veces no duplica) |
| RF3 | HSB: ruteo por sede, transformación, validación, cola con reintentos e idempotencia | **Cumple** | Servicio `hsb/` con base propia: idempotencia persistida (`UNIQUE clave`), estados recibido→…→entregado/rechazado/muerto, reintentos exponenciales, reencolado, entrega por la API de la sede. Probado con HAPI caído (reintentando→entregado sin duplicar) y agotando intentos (muerto) |
| RF4 | Datos distribuidos (fragmentación o Citus) y consulta unificada de un paciente en las 3 sedes | **Cumple (opción «un nodo por sede»)** | Una base por sede + réplica; `GET /api/v2/historia-federada/{doc}` devuelve las 3 sedes. **Evidencia de ACID** (`scripts/prueba_acid.sh`, `tests/api/test_acid.py`): transacción que falla a la mitad y no deja nada (ni en las réplicas), consistencia, aislamiento y durabilidad con SIGKILL |
| RF5 | Token, roles y **auditoría encadenada por hash** | **Cumple, con límites** | JWT firmado + roles + 403. `evento_auditoria` encadena cada evento con SHA-256, devuelve el sello en cada escritura (`X-Sello-Auditoria`), `GET /auditoria/verificar` señala el primer evento alterado y `scripts/prueba_auditoria.sh` lo demuestra (UPDATE y DELETE a mano detectados). El **anclaje** de la cabeza en las otras dos sedes detecta además reescribir toda la cadena con hashes recalculados y truncar su cabeza (pasos 7 y 8 del guion), y `GET /auditoria/fhir` la expone como `AuditEvent` R4. Límites: lo posterior al último anclaje (~10 s), la clave JWT compartida de laboratorio, sin Fabric ni sello de tiempo externo |
| RF6 | 4 vistas por rol (Paciente, Admisionista, Médico, **Reporte de HC**) | **Cumple** | Las cuatro vistas existen. El Reportero (auditor) genera el **Reporte de HC por paciente**: por sede, cobertura de campos con faltantes, aviso de sede sin respuesta, sello SHA-256 recalculable en el navegador, imprimir/PDF por el navegador, descarga del JSON y del Bundle, y estado de la plataforma con la verificación de la auditoría. El nombre de rol sigue siendo «reportero» |
| RNF1 | Un solo comando `docker compose up` levanta todo | **Cumple** | `docker-compose.yml` en la raíz y el servicio `init` (claves y certificados aleatorios en `credenciales/`, secretos montados como archivos y solo a quien los usa). Probado en un clon limpio (sin `credenciales/` ni `.env`): `up -d --build` y la API 123/123, el contrato del HSB, la auditoría y las vistas; `down -v` + `up` de nuevo en 17 s con las imágenes ya construidas. Por defecto un solo HAPI (RAM); uno por sede con `--profile fhir-completo` |
| RNF2 | Si una sede cae, la vista sigue con las otras dos y **marca la sede como no disponible** | **Cumple** | La vista sigue con la copia local y marca la sede como «no responde» (probado apagando la base de Cartagena: aparece en 10 s y se recupera). El reporte avisa que puede no incluir lo más reciente. La frescura se infiere de la suscripción de réplica, no de un sondeo directo a la API de la otra sede |
| RNF3 | Cada servicio expone `/health` y `/metrics` | **Casi** | API ✓, HSB ✓, gateway ✓ en Compose (`/health` y `/metrics` con el exportador oficial de nginx; el bus por `/hsb/health` y `/hsb/metrics`). Faltan: el HAPI (sin `/metrics` propio) y el gateway de Kubernetes, que sigue con `/healthz` |

## 3. Rúbrica criterio por criterio

| Fase | Criterio | Máx. | Estado | Qué falta para «excelente» |
|---|---|---|---|---|
| 1 | Arquitectura y UML coherentes | 0,50 | **Cumple** | Casos de uso con «sistema de sede», «auditor» y el bus; secuencia HL7 → HSB → validador → HAPI → nodo con camino de error; clases con `MensajeBus`; estados del mensaje (`docs/uml/`). Límite: no hay clase `EventoAuditoria` en el UML (la cadena está en el código y en el informe) |
| 1 | Informe base y marco teórico | 0,25 | **Cumple** | Objetivos específicos: 4. Título de 16 palabras (el máximo). Referencias verificadas. La Tabla 9 del Word ya mapea los criterios de aceptación a RF1–RF6 y a los requisitos no funcionales (9 de noviembre) |
| 2 | Normalización a FHIR R4 | 0,50 | **Cumple** | `$validate` sin errores ✓, Bundle de ejemplo guardado (`fhir/ejemplos/`) ✓, `PUT` con ids deterministas ✓ en el bus y en la API, recursos propios en HAPI ✓. Quedan advertencias (narrativa, «performer») |
| 2 | Datos distribuidos y ACID | 0,50 | **Cumple** | Transacción atómica demostrada (antes / error a la mitad / después) en la sede y sus réplicas, más consistencia, aislamiento y durabilidad. Límites declarados: aislamiento `READ COMMITTED`, réplica asíncrona (sin ACID entre sedes) y un solo nodo por sede |
| 3 | HSB: ruteo, validación e idempotencia | **1,00** | **Cumple** | Los 5 ejemplos del docente dan el resultado esperado, con `docker compose up` único y la tabla de mensajes en la vista del Admisionista; la caída de HAPI con reintentos y el mensaje muerto se probaron en Kubernetes |
| 3 | Terminologías y métricas | 0,25 | **Cumple** | Medido el 9 de noviembre y escrito en el Word (sección HSB): 61 mensajes/min de ingesta y 49 de extremo a extremo, latencia mediana 1,6 s y p95 52,8 s, 16,7 % de fallidos, 10 reenvíos = 10 duplicados (`scripts/carga_bus.py`). `ref_terminologia` + ConceptMap en `/hsb/terminologia/conceptmap`; métricas de mensajes por estado, % fallidos, duplicados y latencia. Los códigos locales de DG1 se rechazan en vez de inventar equivalencias |
| 4 | Seguridad y auditoría | 0,40 | **Cumple** | Roles ✓, cadena de hash ✓, verificador ✓, prueba de alteración ✓, **anclaje de la cabeza en las otras sedes ✓** (detecta reescribir toda la cadena y truncar la cabeza; `scripts/prueba_auditoria.sh` pasos 7 y 8) y **`AuditEvent` de FHIR ✓** (`/auditoria/fhir`, 0 errores en `$validate`). Sin Fabric (bonus) |
| 4 | Resiliencia y observabilidad | 0,30 | **Cumple** | Sede caída ✓ (probado y en el guion, también en Kubernetes: se corrigió que el reporte la daba de nuevo por «en línea»). `/health` y `/metrics` en API, bus y gateway (Compose y Kubernetes, con exportador de nginx) y `/actuator/prometheus` en el HAPI; Prometheus los raspa en Kubernetes (verificado el 9 de noviembre). Tablero de estado con verificador de auditoría y resumen del bus ✓. El tablero de Grafana existe solo en Compose (bonus) |
| 4 | Viabilidad e interfaces | 0,30 | **Cumple** | Escalabilidad y cumplimiento ✓ (marcado lo implementado). Capturas reales de las vistas y del tablero ✓ (9 de noviembre: Reporte de HC, sello, sede caída, tablero de estado, integridad de la auditoría, tabla del bus y accesos del paciente; Figuras 22 a 26 y las de Admisionista y Paciente). El E2E de Playwright (19 pruebas, 5 nuevas para estas pantallas) pasa en Compose |
| 5 | Las cuatro vistas | 0,40 | **Cumple** | Reporte de HC, accesos del paciente, tabla del bus del admisionista, estado para el médico y sello visible tras cada escritura. Pendiente: E2E de Chromium de estas pantallas (hoy solo una prueba ligera con jsdom) y las capturas para el informe |
| 5 | Demo desde cero | 0,30 | **Cumple** | `docker compose down -v && docker compose up -d --build` y `bash scripts/demo.sh --sin-pausas`: todo en orden en 113 s (imágenes en caché; con imágenes sin construir tardará más y no se midió). También pasa en Kubernetes. Falta ensayar con los dos integrantes |
| 5 | Informe final y referencias | 0,15 | **Casi** | 17 referencias verificadas ✓ (≥8), bitácora con la declaración de IA ✓. Falta la contribución real de cada integrante (commits) |
| 5 | Sustentación individual | 0,15 | — | Cada integrante debe poder explicar y **modificar en vivo** una parte (ver sección 6) |
| Bonus | hasta +0,25 | | **Ya hay 3 de 4 opciones** | Kubernetes en Minikube ✓, pruebas de carga medidas ✓, tablero con Prometheus y Grafana ✓ (provisionado, perfil `observabilidad` de Compose, 6 objetivos arriba, captura en el informe). Falta Fabric |

## 4. Detalle contra los ejemplos del paquete (el HSB ya está hecho; se conserva como criterio de aceptación)

**HSB (`ejemplos/` es el contrato):** `POST /hsb/hl7`, `POST /hsb/csv?sede=N`, `GET /health`, `GET /metrics`; validación (documento 4 a 15 dígitos, sexo M/F/O, sede 1 a 3, fecha, CIE-10);
idempotencia con MSH-10 o hash del contenido **persistida** (no en memoria); estados recibido → validado → transformado → entregado | rechazado | reintentando | muerto; retroceso
exponencial 1, 2, 4 s con máximo de intentos y reencolado; mapeo `dx_local → CIE-10` con `05_ref_terminologia.csv`.
Resultados esperados: `01` entregado (Patient 1007, Encounter, Condition J45.9 en sede 2); `02` entregado (Observation LOINC 718-7 = 13,8 g/dL, paciente 1001, sede 1); `03` rechazado con **3 motivos**;
`04` → 3 entregados y 2 rechazados; reenviar `01` → `duplicado`; apagar HAPI durante `02` → `reintentando` y luego `entregado` sin duplicar; HAPI apagado más allá del máximo → `muerto`.

**Matriz de permisos de la guía frente a lo que hay hoy**

| Acción | Guía | Hoy |
|---|---|---|
| Paciente ve su historia / no la de otro | ✓ | ✓ (403 en otro documento) |
| Admisionista no ve la historia clínica | ✓ | ✓ |
| Médico ve la historia de otro paciente | ✓ | ✓ |
| Auditor ve el reporte de otro paciente | Sí | ✓ (`/reporte-hc`, solo reportero; queda auditado y el paciente lo ve) |
| Abrir atención solo admisionista | ✓ | ✓ |
| Registrar diagnóstico/egreso solo médico | ✓ | ✓ |
| Médico ve el estado de la plataforma | Sí | ✓ (`/estado-plataforma`) |
| **Auditor apaga/enciende un nodo (demo)** | Sí | **No existe** |
| Rol «auditor» | llamado `auditor` | llamado `reportero` |

**Vistas contra lo que pide la guía (actualizado):** Paciente ✓ lista de accesos a su historia (quién y cuándo). Admisionista ✓ tabla del estado de los mensajes del bus (solo por el gateway).
Médico ✓ sello de auditoría visible tras cada escritura (cabecera `X-Sello-Auditoria`, mostrado en la barra) y estado de la plataforma. Reporte de HC ✓ por paciente, agrupado por sede, con aviso de sede sin responder,
cobertura de campos con lista de faltantes, sello SHA-256, imprimir (PDF desde el navegador), descarga del JSON y del Bundle, y estado con verificación de auditoría. Pendiente: el médico recibe el sello pero no lo guarda por registro; no hay PDF generado en el servidor.

## 5. Plan priorizado (puntos en juego / esfuerzo)

| # | Qué | Puntos | Esfuerzo | Depende de |
|---|---|---|---|---|
| P1 ✅ | **HSB (hecho)** (`hsb/`, FastAPI): ingesta HL7 v2 y CSV, validación, tabla `mensaje_bus` persistida, idempotencia, reintentos + mensajes muertos + reencolar, `ref_terminologia`, `/health` y `/metrics`, pruebas con los 5 ejemplos | ~1,1 | Alto | — |
| P2 ✅ | **Normalizador FHIR** alineado (hecho; `$validate` sin errores y `PUT` en el bus y en la API): Bundle `transaction` con `PUT` y ids deterministas, recursos propios en HAPI, **`$validate` limpio** con evidencia | ~0,25 | Medio (la RAM: validar con un solo HAPI y más heap, o en CI) | P1 comparte código |
| P3 ✅ | **Auditoría encadenada (hecho, con anclaje en otras sedes y `AuditEvent`)**: tabla `evento_auditoria` (`hash = SHA-256(hash_anterior + contenido)`), verificador, sello en cada escritura, `AuditEvent`, prueba de alteración | ~0,3 | Medio | — |
| P4 ✅ | **Reporte de HC (hecho; sin E2E de Chromium ni capturas)** por paciente + rol `auditor` + estado para el médico + lista de accesos del paciente + tabla de mensajes del admisionista | ~0,3 | Medio | P1, P3 |
| P5 ✅ | **`docker compose up` en un solo comando (hecho)**: `docker-compose.yml` en la raíz, servicio de inicialización que genera claves y certificados, `.env.example`, HSB incluido, `/health` y `/metrics` en el gateway | ~0,25 | Medio | P1 |
| P6 ✅ | Evidencia **ACID** (hecho) (antes / error a la mitad / después) | ~0,1 | Bajo | — |
| P7 | **UML y mapeo**: casos de uso con «sistema de sede» y «auditor», secuencia HL7→FHIR con camino de error, clases con `MensajeBus` y `EventoAuditoria`, estados del mensaje; tabla de mapeo HL7/CSV → tabla → FHIR (≥15 filas) | ~0,2 | Bajo-medio | P1, P3 |
| P8 ✅ | Entregables administrativos (sección 6; falta lo que solo el equipo puede hacer) | variable | Bajo | — |

El control de nodo del auditor (apagar/encender) no debe simularse: la API no puede detener contenedores sin montar el socket de Docker (riesgo de seguridad). Propuesta: script `scripts/nodo.sh`
documentado y mostrado en la demo, y explicarlo en la sustentación.

## 6. Reglas e integridad: lo que no es código (actualizado)

| Entregable | Estado |
|---|---|
| Declaración de uso de IA y de código abierto | ✅ `docs/BITACORA.md` y Anexo F del informe. La columna «revisión del equipo» queda **por completar** por ellos |
| Contribución de cada integrante (commits) | ⏳ El trabajo sigue **sin commit**: `bash scripts/bitacora_commits.sh --por-fase` genera la tabla del historial real cuando existan commits de ambos. No se fabrica historial |
| README con pasos de ejecución, usuarios de prueba, cómo enviar los ejemplos y cómo apagar una sede | ✅ (equipo y roles «por completar»: no se conoce el reparto) |
| Estructura `docs/ infra/ hsb/ fhir/ db/ app/ tests/ ejemplos/` | ✅ Renombrada y verificada (CI local, API 132/132, demo, colección) |
| Colección de pruebas y datos sintéticos | ✅ `tests/coleccion/` (Postman, 24 peticiones, corrida con newman) y `scripts/datos_demo.py` |
| Presentación de apoyo | ✅ `docs/Presentacion_Historia_Clinica_Distribuida.pptx` (10 diapositivas, sin renderizar: no hay LibreOffice en el equipo; validada y con revisión de ajuste por estimación) |
| Guion de la demostración | ✅ `scripts/demo.sh` (los 7 pasos de la lista de verificación de la guía) |
| Objetivos específicos 3 a 4 | ✅ 4 |
| Cuenta `auditor` (la guía pide roles paciente, admisionista, médico y auditor) | ✅ usuario `auditor` con rol `reportero` |
| Etiqueta `v1.0` y repositorio privado con acceso al docente | ⏳ Lo hace el equipo en su propio repositorio (`git tag -a v1.0`); yo no toco remotos |
| Sustentación individual (explicar y modificar en vivo) | ⏳ Cada integrante: recorrido sugerido en la bitácora |

## 7. Decisiones que cambian el plan

- **Mantener la arquitectura actual (réplica entre sedes) y agregar el HSB delante.** La guía acepta «un nodo por sede». El HSB recibe HL7/CSV, valida y entrega a la **API de la sede** (respetando la regla de sede dueña), no a las bases. Es la ruta recomendada: reutiliza lo ya probado (autenticación, TLS, réplica, MPI).
- Alternativa descartada: volver al esquema de la v1 (fragmentación por documento, archivada en `v1/`). Perdería la tolerancia a fallos que es el aporte del trabajo.
- Los nombres de tablas de la guía (`usuario`, `atencion`…) corresponden al esquema de la v1; el modelo de 57 campos de la v2 los cubre con otros nombres, y conviene dejar esa equivalencia escrita en el mapeo.
