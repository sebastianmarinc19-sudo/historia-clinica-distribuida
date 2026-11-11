# Guía de entrega y sustentación

Lo que el código no puede hacer por el equipo: el historial de git, el repositorio, la etiqueta `v1.0`, el ensayo de la demostración y la sustentación individual.
Esta guía es una lista de pasos, no un historial inventado: **los commits, las fechas y las contribuciones deben ser los reales de cada integrante.**

## 1. Repositorio, commits y etiqueta (la guía pide commits de ambos a lo largo de las 5 fases)

Estado al escribir esto: el trabajo está **sin commit** y `origin` apunta al repositorio del docente (no se le hace push).

1. Cree su repositorio **privado** y dé acceso de lectura al docente. En el clon local: `git remote rename origin docente` (o bórrelo) y `git remote add origin <su-repo>`. No haga push al del docente.
2. Cada integrante configura su propia identidad **en su propia máquina o cuenta**: `git config user.name "..."` y `git config user.email "..."`.
3. Haga commits con lo que cada uno hizo de verdad. Si hasta ahora todo se hizo en una sola copia de trabajo, no reparta commits para aparentar otra cosa ni cambie fechas: haga el commit inicial tal cual está y, desde ahí, que **cada uno haga commits reales** (revisión del código que va a sustentar, correcciones, roles en el README, contribución en la bitácora, ensayo de la demo). La bitácora ya declara el uso de IA y que el trabajo está sin commit.
4. Una forma ordenada de agrupar por fase, si le sirve (decida usted qué commit hace cada quien según quién trabajó en qué):

   | Fase | Qué agrupa | Rutas |
   |---|---|---|
   | 1. Análisis, UML y diseño | esquema, UML, informe | `db/`, `docs/uml/`, `docs/img/`, `docs/construir_documento.py` |
   | 2. Datos distribuidos y FHIR | API, réplica, MPI, FHIR | `app/`, `fhir/`, `scripts/prueba_replicacion.sh`, `scripts/prueba_acid.sh` |
   | 3. HSB | bus, ejemplos, métricas | `hsb/`, `ejemplos/`, `scripts/prueba_hsb*.sh` |
   | 4. Seguridad, resiliencia y despliegue | auth, auditoría, K8s, respaldos, CI | `infra/`, `.github/`, `scripts/prueba_auditoria.sh`, `scripts/sre_k8s.py` |
   | 5. Prototipo, informe y sustentación | vistas, demo, informe | `app/hc_api/static/`, `scripts/demo.sh`, `tests/e2e/`, `docs/` |

5. Con commits hechos: `bash scripts/bitacora_commits.sh --por-fase` genera la tabla de contribuciones (se pega en `docs/BITACORA.md`). No se redacta a mano.
6. Complete en `README.md` y `docs/BITACORA.md` los textos «por completar» (roles y qué hizo cada uno).
7. Etiqueta final: `git tag -a v1.0 -m "Entrega final"` y `git push origin v1.0` (en **su** repositorio).
8. Antes de entregar: `bash scripts/ci.sh` (lint, pruebas, manifiestos, secretos) y comprobar que `git status` no muestra `credenciales/` ni `respaldos/` (están en `.gitignore`).

## 2. Ensayo de la demostración (rúbrica «Demo desde cero»)

Hágalo los dos, desde el equipo donde se va a presentar, con el reloj en la mano.

```bash
time (docker compose down -v && docker compose up -d --build)   # con imágenes ya construidas tardó ~20 s; con imágenes nuevas tardará bastante más
bash scripts/demo.sh                                            # paso a paso: Enter para continuar (usar --sin-pausas para de corrido)
```

- Si es la primera vez en esa máquina, mida también la construcción de las imágenes y la descarga de `hapiproject/hapi` (~1 GB): hágala **antes** de la sustentación.
- El HAPI tarda en responder la primera vez (calentamiento); haga una corrida previa. El script `demo.sh` espera hasta 4 minutos al primer mensaje.
- Un solo comando levanta todo: `docker compose up -d --build`. Opcional: `docker compose --profile observabilidad up -d` (Prometheus y Grafana en `localhost:3000`).
- Para ver la interfaz con HTTPS en el navegador hay que confiar en la CA de laboratorio (`credenciales/ca.crt`) o aceptar el aviso del certificado. Las claves de las cuentas están en `credenciales/credenciales.json` (no se suben a git).

## 3. Sustentación individual (15 min, «explica y modifica en vivo»)

Cada integrante debe poder explicar **cualquier parte que entregó** y hacer un cambio pequeño en vivo. Lo que sigue son ejercicios típicos con dónde tocar y cómo comprobarlos.

| Si le piden… | Dónde | Cómo comprobarlo |
|---|---|---|
| Cambiar el umbral de coincidencia del MPI o explicar por qué solo el documento une | `app/hc_api/mpi.py`, `MPI_UMBRAL` | `tests/api/test_mpi.py` (se corre con `bash scripts/prueba_api.sh`, que ejecuta toda la suite) |
| Agregar un rol o cambiar qué puede ver cada rol | `app/hc_api/auth.py` (`ROLES`, `requiere(...)`), `scripts/credenciales.py` | `tests/api/test_autenticacion.py` |
| Cambiar el tiempo o el número de reintentos del bus, o el retroceso exponencial | `hsb/hc_hsb/config.py`, `hsb/hc_hsb/bus.py` (`espera`) | `bash scripts/prueba_hsb.sh -k exponencial` |
| Aceptar un campo HL7 nuevo (por ejemplo, otro segmento) | `hsb/hc_hsb/hl7.py` y `fhir.py` | `bash scripts/prueba_hsb.sh` y reenviar un mensaje con `curl` (ver README) |
| Agregar un código de terminología local (CSV → CIE-10) | tabla `ref_terminologia` (`hsb/hc_hsb/esquema.sql`, que se siembra desde `hsb/datos/ref_terminologia.csv`) y `hsb/hc_hsb/normalizador.py` | `GET /hsb/terminologia/conceptmap` |
| Explicar la idempotencia y qué pasa si se reenvía un mensaje | `hsb/hc_hsb/bus.py` (clave única) | demo, paso 4 |
| Cambiar cada cuánto una sede ancla su cabeza de auditoría | `HC_ANCLA_INTERVALO_S` en `app/hc_api/config.py` y `docker-compose.yml` | `bash scripts/prueba_auditoria.sh` (pasos 7 y 8) |
| Explicar por qué la cadena de hash no basta y qué agrega el anclaje | `app/hc_api/auditoria.py`, `app/hc_api/anclaje.py` | guion de alteración |
| Mostrar un campo más en el Reporte de HC | `app/hc_api/reporte.py` y `app/hc_api/static/reportes.html` | `bash scripts/prueba_vistas.sh compose` |
| Explicar ACID con un ejemplo real | `scripts/prueba_acid.sh` | `bash scripts/prueba_acid.sh` (atomicidad, consistencia, aislamiento y durabilidad con SQL) |
| Apagar una sede y mostrar que la vista sigue | `scripts/nodo.sh apagar 2` | demo, paso 6; el Reporte de HC advierte «sin respuesta de Cartagena» |

Preguntas que conviene saber responder sin mirar el código:

- ¿Por qué una base por sede y réplica lógica, y qué se sacrifica? (CAP: disponibilidad frente a consistencia inmediata; ACID solo dentro de cada sede, no entre sedes.)
- ¿Qué es la regla de «sede dueña» y cómo evita conflictos de escritura?
- ¿Qué entra por el bus, cómo se valida, cuándo es «rechazado» y cuándo «reintentando» o «muerto»? (400 del destino rechaza; 5xx, tiempo de espera y 409 de versión del HAPI reintentan.)
- ¿Qué detecta y qué no detecta la auditoría encadenada? ¿Qué agrega el anclaje y cuáles son sus límites? (Los límites están en `app/hc_api/anclaje.py`.)
- ¿Qué falta o es solo propuesta? (consentimiento, cifrado en reposo, OIDC, HAPI en las tres sedes, Fabric; todo está declarado en el informe, sección «Limitaciones».)

Regla práctica: **si no puede explicar una parte del código, léala antes y pregúntele a quien la revisó; si la escribió la IA, la bitácora lo declara y usted igual debe poder explicarla.** Las partes que conviene recorrer están listadas en `docs/BITACORA.md`.

## 4. Verificación rápida antes de presentar

```bash
bash scripts/ci.sh                          # lint, pruebas del bus y unitarias, SQL, manifiestos, secretos
docker compose up -d --build
bash scripts/demo.sh --sin-pausas           # debe terminar con «Demostración: todo en orden»
bash scripts/prueba_api.sh                  # 141 pruebas; si falla algo de FHIR justo tras reiniciar el HAPI, repetir con el HAPI ya caliente
python3 docs/construir_documento.py         # regenera el informe en ../Propuesta_Historia_Clinica_Distribuida.docx
```

Qué no se probó de punta a punta y debe tenerse presente: el CI/CD en GitHub Actions nunca se ejecutó en GitHub; la presentación (`docs/Presentacion_Historia_Clinica_Distribuida.pptx`) no se vio renderizada, ábrala en PowerPoint antes de presentar; en Kubernetes el E2E de Playwright no se repitió con las pantallas nuevas.
