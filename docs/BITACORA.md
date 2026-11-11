# Bitácora del proyecto

Equipo: Sebastián Marín y Halit Tuiran · Docente: Jaider Reyes · Sistemas Distribuidos (UAJS).
Lo que no se pudo saber desde el repositorio queda marcado **«por completar»**: ese texto lo escribe el equipo, no se inventa.

## 1. Declaración de uso de inteligencia artificial y de código abierto

La guía del parcial permite usar asistentes de IA y código abierto **si se declaran aquí**, y exige que cada integrante pueda explicar y modificar en vivo cualquier parte que entregue.

**Asistente de IA usado:** Claude (Anthropic), a través de Claude Code, en varias sesiones de trabajo (7 a 9 de noviembre de 2026 según el registro de las sesiones). El asistente escribió, ejecutó y corrigió gran parte del código, de las pruebas, de los scripts, del documento Word y de los diagramas; las decisiones de alcance las tomó el equipo cuando el asistente las consultó (por ejemplo, ir primero por el HSB, mantener la réplica entre sedes, renombrar las carpetas a la estructura de la guía).

| Parte | Qué hizo la IA | Revisión del equipo |
|---|---|---|
| Esquema de 45 tablas y réplica lógica (`db/`) | Reconstruyó el esquema desde el modelo de 57 campos y escribió la réplica en malla y sus pruebas (29 de restricciones SQL) | por completar |
| API de cada sede (`app/`): autenticación, MPI, RDA FHIR, reporte de HC | Escribió las rutas, la autenticación por roles (JWT), el MPI determinista con decisión humana y el reporte con sello | por completar |
| Bus de integración (`hsb/`) | Diseñó e implementó HL7 v2 y CSV, la máquina de estados, la idempotencia persistida, los reintentos y los mensajes muertos (68 pruebas) | por completar |
| Auditoría encadenada por hash (`app/hc_api/auditoria.py`) | Diseñó la cadena, el verificador, el sello y la prueba de alteración | por completar |
| Vistas web (`app/hc_api/static/`) | Escribió las cuatro vistas (HTML, CSS y JavaScript sin dependencias) y sus pruebas E2E | por completar |
| Despliegue (`docker-compose.yml`, `infra/`) | Escribió el compose de un solo comando, el servicio `init`, los manifiestos de Kubernetes, los respaldos cifrados y el CI/CD | por completar |
| Pruebas y evidencia (`tests/`, `scripts/`) | Escribió las pruebas de API (141), el guion ACID, la prueba de alteración, la colección de Postman y el guion de la demostración | por completar |
| Documento y UML (`docs/`) | Generó el documento Word (`docs/construir_documento.py`), los diagramas PlantUML y esta bitácora | por completar |

**Cómo se verificó lo que escribió la IA.** Cada pieza se ejecutó antes de darse por buena: pruebas automáticas con PostgreSQL real, despliegue en Docker Compose y en Minikube, E2E en Chromium (19 pruebas), CI local (ruff, shellcheck, kubeconform, gitleaks) y comprobaciones con los mensajes de ejemplo del parcial. Las referencias del informe (17) se abrieron una por una y se corrigieron 6.
**Lo que no se verificó:** el CI/CD en GitHub Actions nunca se ejecutó en GitHub; `$validate` se corrió el 9 de noviembre solo con los 5 Bundle de ejemplo (0 errores; no con los Bundle de cada encuentro real); los reportes y vistas nuevos se probaron con jsdom y se vieron en el navegador integrado de la app (Chromium) el 9 de noviembre, y el E2E de Playwright las cubre desde el 9 de noviembre (5 pruebas nuevas, 19 en total, en Compose).

**Qué debe poder explicar cada integrante en la sustentación (recorrido sugerido antes de la entrega):**
`app/hc_api/mpi.py` (por qué solo el documento une), `app/hc_api/auth.py` (JWT y roles), `app/hc_api/auditoria.py` (cadena de hash y sus límites), `hsb/hc_hsb/bus.py` (estados, idempotencia, reintentos),
`db/03_replicacion.sh` (publicación y suscripciones), `scripts/prueba_acid.sh` (qué prueba cada propiedad), `infra/init/init.sh` y `docker-compose.yml`.

**Código abierto usado** (licencias: revisar en cada proyecto): PostgreSQL 16 (réplica lógica), FastAPI, Uvicorn, psycopg2, Pydantic, HAPI FHIR (servidor FHIR R4), nginx y el exportador de Prometheus para nginx, Prometheus, Grafana, Kubernetes y Minikube (Kustomize, kubeconform),
Docker y Docker Compose, Playwright y Chromium, jsdom, newman (Postman), PlantUML, age y rclone (respaldos), ruff, shellcheck, gitleaks y actionlint. Los mensajes de `ejemplos/` y la guía son del paquete del docente (sin modificar).
El repositorio de partida es el del docente (`jaiderreyes/historia-clinica-distribuida`); la v1 del laboratorio quedó archivada en `v1/`.

## 2. Contribución de cada integrante

El historial de git debe mostrar commits de **ambos** integrantes a lo largo de las 5 fases. A la fecha de esta bitácora **el trabajo está sin commit**: la tabla se genera del historial real con

```bash
bash scripts/bitacora_commits.sh --por-fase
```

y se pega aquí cuando existan los commits (no se redacta a mano ni se reescribe el historial).

| Integrante | Commits | Qué hizo (por completar) |
|---|---|---|
| Sebastián Marín | por completar | por completar |
| Halit Tuiran | por completar | por completar |

## 3. Registro por fase (lo hecho, y las correcciones cuando una fase no cumplía su criterio)

| Fase | Lo hecho | Correcciones anotadas |
|---|---|---|
| 1. Análisis, UML y diseño | Reconstrucción del esquema, arquitectura de 3 sedes autónomas, UML (casos de uso, secuencia, clases, estados) y documento | Los UML no coincidían con los de la guía: se rehicieron con el actor «sistema de sede», la secuencia HL7 → HSB → HAPI → nodo con camino de error, las clases del bus y los estados del mensaje. Los objetivos específicos pasaron de 6 a 4 |
| 2. Datos distribuidos y FHIR | Réplica lógica en malla, MPI, RDA como Bundle `document`, HAPI por sede (activo en Sincelejo por RAM) | El Bundle `transaction` con `PUT` e ids deterministas llegó con el HSB (`fhir/ejemplos/`). `$validate` de HAPI encontró un error real (fechas con hora sin zona horaria) y se corrigió en el bus y en el RDA. La evidencia ACID se añadió después (`scripts/prueba_acid.sh`) |
| 3. HSB | Bus con HL7 v2 y CSV, idempotencia, reintentos exponenciales, mensajes muertos, terminología y métricas | El gateway devolvía 404 en `/hsb/` hasta reiniciar nginx: el despliegue lo reinicia. Los tiempos de espera del HAPI en frío se resolvieron con plazo por intento y presupuesto de tiempo del CSV |
| 4. Seguridad, resiliencia y despliegue | JWT y roles, TLS, experimentos SRE (RTO, RPO, partición, carga), respaldos cifrados, Kubernetes | La auditoría no estaba encadenada: se añadió la cadena de hash, el verificador y la prueba de alteración. El script de despliegue no reiniciaba las APIs al cambiar la imagen o las claves: corregido |
| 5. Prototipo, informe y sustentación | Cuatro vistas, `docker compose up` de un solo comando, demostración con guion, informe, presentación | Una referencia del informe apuntaba a la figura equivocada (18 en vez de 21) y se corrigió; el README tenía rutas que cambiaron con la nueva estructura de carpetas |

## 4. Decisiones y fallas encontradas (resumen)

- Se mantuvo la **réplica entre sedes** y se puso el HSB delante, entregando a la API de la sede y no a las bases (respeta la regla de sede dueña).
- El **MPI no une por similitud**: solo el documento identifica; lo parecido queda como candidato que confirma un médico.
- Fallas halladas al repetir pruebas: registro de accesos que retenía la respuesta con la base caída, pool de conexiones bloqueado por `closeall()`, mensaje del MPI borrado al recargar, al tomar las capturas, la portada mostraba «[object HTMLSpanElement]» en vez de las sedes (un `append(array)` sin `...`) y la tabla del bus repetía «CSV CSV» (ambos corregidos y con prueba en `tests/e2e/vistas_jsdom.mjs`), HAPI con tiempos de espera por poca RAM (5,8 GB), el estado «sede caída» que volvía a «en línea» a los pocos segundos (el proceso de réplica se reinicia y PostgreSQL le pone su hora de arranque como último mensaje: se detecta ahora con `received_lsn`; lo encontró la repetición de la demo el 9 de noviembre), `kubectl apply` que no reiniciaba pods con imagen `:local`, referencias del informe con figura equivocada.
- Pendiente declarado: advertencias de narrativa y «performer» de `$validate`, cifrado en reposo y en tránsito interno, consentimiento, OIDC, HAPI en las tres sedes, Hyperledger Fabric, sello de tiempo externo para la auditoría, ejecución del CI en GitHub.
