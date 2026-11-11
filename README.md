# Historia clínica distribuida · v2

Reingeniería del proyecto para que **tres sedes (Sincelejo, Cartagena y Corozal) sigan operando cuando una cae o queda aislada**, con bases de datos distribuidas, identidad federada y HL7 FHIR R4.

> **Este repositorio contiene dos generaciones.** La **v2** (esta) está en `app/`, `hsb/`, `fhir/`, `db/`, `infra/`, `tests/`, `ejemplos/`, `docs/`, `scripts/`, `.github/` y `docker-compose.yml`. La **v1** del laboratorio (fragmentación por rango de documento, una sola app) está archivada en [`v1/`](v1/README.md) y **no es la que se evalúa**. En la raíz quedan además los archivos del artículo IEEE del equipo (`FHIR_IEEE_Conference_v*.tex` y `fig_*.png`), que se sincronizan con Overleaf y por eso no se movieron.

## Equipo y entrega

| Integrante | Rol en el proyecto |
|---|---|
| Sebastián Marín | _por completar por el equipo_ |
| Halit Tuiran | _por completar por el equipo_ |

Docente: Jaider Reyes · Sistemas Distribuidos · Corporación Universitaria Antonio José de Sucre (UAJS). Repositorio público: https://github.com/sebastianmarinc19-sudo/historia-clinica-distribuida (rama `reingenieria-3-sedes`). Versión entregada: etiqueta **`v1.0`**
(`git tag -a v1.0 -m "Entrega final" && git push origin v1.0`, hecho por el equipo en su propio repositorio). La contribución de cada integrante y el uso declarado de IA y de código abierto están en la **[bitácora](docs/BITACORA.md)**.

Para lo que solo puede hacer el equipo (commits reales de ambos, repositorio público, etiqueta `v1.0`, ensayo de la demostración y preparación de la sustentación individual) hay una lista de pasos en **[docs/GUIA_ENTREGA_Y_SUSTENTACION.md](docs/GUIA_ENTREGA_Y_SUSTENTACION.md)**.

## Ejecución desde cero (solo Docker)

```bash
git clone --branch reingenieria-3-sedes https://github.com/sebastianmarinc19-sudo/historia-clinica-distribuida.git && cd historia-clinica-distribuida   # 0. obtener el código
docker compose up -d --build        # 1. levanta todo: 3 sedes + réplica, HAPI FHIR, bus HSB y gateway TLS (claves y certificados incluidos)
python3 scripts/datos_demo.py        # 2. datos sintéticos: el paciente 7000001 queda atendido en las tres sedes
bash scripts/demo.sh                 # 3. guion de la demostración paso a paso (Enter avanza; --sin-pausas de corrido)
docker compose down -v               # lo borra todo; el siguiente `up` empieza de cero
```

Vistas por el gateway: `https://localhost:8443/sede/1/vistas/` (también `/sede/2/…` y `/sede/3/…`). El certificado es de una CA de laboratorio: importe `credenciales/ca.crt` en el navegador o use `curl --cacert credenciales/ca.crt`.
El primer arranque del HAPI FHIR tarda decenas de segundos. Detalles, Kubernetes y alternativas más abajo.

### Usuarios de prueba

Las claves son **aleatorias por instalación** y no están en el repositorio: `python3 scripts/credenciales.py` las muestra (o `credenciales/credenciales.json`, creado por `docker compose up`).

| Usuario | Rol | Entra en la vista | Para qué |
|---|---|---|---|
| `admision` | admisionista | Admisionista | registrar paciente, abrir encuentro, triage, ver los mensajes del bus |
| `medico` | médico | Médico | atención clínica, MPI, historia unificada, estado de la plataforma, reporte de HC |
| `auditor` y `reportero` | reportero (el «auditor» de la guía) | Reportero · Reporte de HC | reporte de cualquier paciente, cobertura, auditoría, verificación de la cadena |
| paciente `7000001` | paciente | Paciente | documento `7000001` y fecha de nacimiento `1988-04-12` (datos sintéticos de `datos_demo.py`) |
| `sede` | sistema_sede | — | envía mensajes HL7 y CSV al bus (cuenta del sistema legado) |
| `admin` | administrador | todas | laboratorio (reencolar mensajes muertos del bus) |

### Enviar los ejemplos al bus

```bash
G=https://localhost:8443; CA=credenciales/ca.crt
TOKEN=$(python3 - <<'PY'
import json, ssl, urllib.request
c = json.load(open("credenciales/credenciales.json"))["usuarios"]["sede"]["clave"]
r = urllib.request.Request("https://localhost:8443/sede/1/api/v2/auth/login", data=json.dumps({"usuario": "sede", "clave": c}).encode(), headers={"content-type": "application/json"})
print(json.load(urllib.request.urlopen(r, context=ssl.create_default_context(cafile="credenciales/ca.crt")))["token"])
PY
)
curl --cacert $CA -H "Authorization: Bearer $TOKEN" --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 $G/hsb/hl7      # entregado (se repite: duplicado)
curl --cacert $CA -H "Authorization: Bearer $TOKEN" --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 $G/hsb/hl7
curl --cacert $CA -H "Authorization: Bearer $TOKEN" --data-binary @ejemplos/03_adt_a01_invalido.hl7 $G/hsb/hl7           # rechazado con 3 motivos
curl --cacert $CA -H "Authorization: Bearer $TOKEN" --data-binary @ejemplos/04_sede3_legado.csv "$G/hsb/csv?sede=3"      # 3 entregadas, 2 rechazadas
```

La colección de Postman (con las mismas peticiones y sus aserciones) está en `tests/coleccion/` (`bash tests/coleccion/ejecutar.sh` la corre con newman sin instalar nada).

### Apagar y encender una sede

```bash
bash scripts/nodo.sh apagar 2        # apaga Cartagena (base, API y HAPI); la vista unificada sigue con las otras dos y la marca «no responde»
bash scripts/nodo.sh encender 2      # vuelve y se pone al día sola
bash scripts/nodo.sh estado
```

No hay un botón en la aplicación a propósito: apagar contenedores desde la API exigiría darle el socket de Docker (equivale a root en el equipo).

## Qué resuelve

| Problema de la v1 | v2 |
|---|---|
| Pacientes repartidos por rango de documento; si cae un nodo se pierde su rango | Cada **sede** es dueña de sus filas y se **replica** (replicación lógica de PostgreSQL, malla completa) |
| Una sola app y un solo HAPI FHIR (su base en el nodo 1) | Una **API y un HAPI FHIR por sede** |
| Identidad federada en una base única | **MPI determinista** que cada sede calcula desde su copia (sin servicio central) |
| Tabla `usuario` con `nombre_completo` | **45 tablas** (29 catálogos + 16 de núcleo) con los **57 campos** de la Resolución 866 de 2021 |

Reglas clave: una fila solo la escribe su **sede dueña** (si otra sede intenta escribir recibe `409` con la dueña); las demás sedes la ven como **copia de solo lectura**; la consulta de historia entre sedes sale de la copia local, así que funciona aunque la sede dueña esté caída.

```
                   gateway (nginx)
        ┌────────────┼────────────┐
   Sede Sincelejo  Sede Cartagena  Sede Corozal        cada sede:  API v2 (x2) · PostgreSQL · HAPI FHIR
   PG ◄────────────► PG ◄────────► PG                  réplica lógica en malla (origin = none)
```

## Las cuatro vistas (verifican los casos de uso CU-01 a CU-15)

Las sirve la propia API de cada sede en `/vistas/` (HTML/CSS/JS sin recursos externos).

| Vista | Casos de uso |
|---|---|
| Admisionista (`admision.html`) | CU-01 registrar paciente · CU-02 abrir encuentro · CU-03 triage |
| Médico (`medico.html`) | CU-04 diagnósticos · CU-05 tecnologías · CU-06 entregas · CU-07 resultados · CU-08 antecedentes y riesgos · CU-09 egreso · CU-10 migrar a FHIR · CU-11 MPI · CU-12 RDA · CU-13 historia entre sedes |
| Paciente (`paciente.html`) | CU-13 y CU-12 en solo lectura; entra con documento y fecha de nacimiento y solo ve lo suyo |
| Reportero / auditor (`reportes.html`) | **Reporte de historia clínica de un paciente** (por sede, cobertura de los 57 campos y campos faltantes, sedes que no responden, sello SHA-256 que el navegador puede recalcular, imprimir o guardar como PDF, descarga del reporte en JSON y del Bundle) · CU-14 cobertura de migración · CU-15 auditoría de los 57 campos (con filtro por lote) · réplica · integridad de la auditoría · estado de la plataforma |

## Ingreso y roles

Toda ruta clínica exige sesión. El personal entra con usuario y clave (`POST /api/v2/auth/login`) y el paciente con documento y
fecha de nacimiento (`POST /api/v2/auth/paciente`, verificados contra la copia local). La sede devuelve un token firmado
(JWT HS256) **que vale en las tres sedes**: no hay servidor de autenticación central que pueda caerse. Cada vista pide su rol:

| Rol | Vista | Puede |
|---|---|---|
| admisionista | Admisionista | registrar paciente, abrir encuentro, triage, buscar pacientes y **ver el estado de los mensajes que llegaron al bus** |
| medico | Médico | atención clínica, migración a FHIR, revisión y decisión del MPI, historia entre sedes y **estado de la plataforma** |
| reportero (el «auditor» de la guía) | Reportero | **reporte de HC de cualquier paciente**, cobertura, auditoría de 57 campos, réplica, registro de accesos, verificación de la cadena de auditoría y estado de la plataforma |
| paciente | Paciente | su propia información e historia y quién accedió a ella (otro documento da 403) |
| administrador | todas | todo (uso de laboratorio) |

Las claves de laboratorio son **aleatorias por instalación**: `python3 scripts/credenciales.py` las crea en `credenciales/credenciales.json`
(0600, ignorado por git) y las muestra; `--rotar` las cambia (`--env` escribe un `.env`, que ya no hace falta: `docker compose up` crea las claves con el servicio `init`). `k8s_desplegar.sh`
las carga como Secret `hc-auth` en cada sede. Cada sede guarda su propio registro local de accesos (`evento_auditoria`, encadenado por hash y no replicado),
visible en la vista del Reportero.

## Reporte de historia clínica y estado de la plataforma

- `GET /api/v2/reporte-hc/{documento}` (solo reportero): lo que cada sede registró del paciente, la cobertura de los 57 campos **de ese paciente** por sede con la lista de lo que falta, y el estado de cada sede. Si una sede no responde, el reporte lo dice y advierte que muestra su última copia replicada (la sede se infiere de su suscripción de réplica: se probó apagando la base de Cartagena, que apareció como «no responde» a los 10 s).
- **Sello.** `sello_sha256` es el SHA-256 del contenido clínico en JSON canónico (claves ordenadas, porcentajes como texto). La vista lo recalcula en el navegador con Web Crypto («Comprobar sello»): coincide con el del servidor, y cambia si cambia cualquier dato. Solo funciona en HTTPS o localhost.
- Imprimir o guardar como PDF usa el diálogo del navegador (hoja de estilos de impresión); no hay generación de PDF en el servidor. El Bundle (RDA) se descarga por encuentro migrado; los encuentros sin migrar no lo ofrecen.
- Consultar el reporte queda en la auditoría encadenada, y el paciente lo ve en «Quién ha accedido a mi historia» (`/auditoria/mis-accesos`).
- `GET /api/v2/estado-plataforma` (reportero y médico): sedes, base de datos, HAPI FHIR y verificación de la cadena de auditoría; la vista suma el resumen del bus cuando se entra por el gateway.
- El Admisionista ve la tabla de mensajes del bus (`/hsb/mensajes`, mismo token) con filtro por estado. Esto solo funciona por el gateway (`/sede/N/vistas/`), no en los puertos directos de la API.
- Cada escritura muestra en la barra superior el **último sello de auditoría** (`X-Sello-Auditoria`).

Alcance: el auditor ve datos clínicos de cualquier paciente (la guía lo pide); por eso cada consulta se registra y es visible para el paciente. La vista «Reportero» conserva ese nombre por el enunciado del curso; en la guía se llama «auditor».

## Auditoría encadenada por hash

Cada sede lleva su propio registro `evento_auditoria` (no se replica). Cada evento guarda `hash = SHA-256(hash_previo + contenido)`: si alguien modifica, borra, inserta o reordena un evento
en la base, la cadena deja de cuadrar a partir de ahí. La tabla es de solo anexar para la aplicación (un disparador rechaza `UPDATE`, `DELETE` y `TRUNCATE`).

- **Sello en cada escritura.** Una escritura exitosa (POST, PUT, PATCH, DELETE) responde con la cabecera `X-Sello-Auditoria: <n.º de evento>:<hash>`. Las lecturas y los rechazos se anexan en segundo plano.
- **Verificador.** `GET /api/v2/auditoria/verificar` (reportero o médico) recorre la cadena y responde `ok`, los eventos verificados, la cabeza (último sello) y, si falla, el **primer evento alterado** y el motivo. La vista del Reportero tiene la tarjeta «Integridad de la auditoría» y el registro de accesos muestra el sello de cada fila.
- **Paciente.** `GET /api/v2/auditoria/mis-accesos` devuelve quién y cuándo accedió a su historia en esa sede (solo su documento).
- **Anclaje en las otras sedes.** Cada sede publica la cabeza de su cadena en las otras dos cada 10 s (`POST /api/v2/auditoria/anclas`, rol `sistema_sede`; `HC_PARES` en la configuración) y ellas la guardan en `ancla_auditoria` (solo anexar, no replicada). `/auditoria/verificar` compara la cadena local con lo anclado y devuelve `anclaje` (`ok` y por cada par `ok`, `sin_anclas`, `no_responde` o `discrepancia`): detecta la **reescritura completa** con hashes recalculados («historial reescrito») y el **truncamiento** de la cabeza («cadena truncada»); anclar otro hash para una secuencia ya anclada da 409. Un par caído no cuenta como fallo.
- **AuditEvent de FHIR.** `GET /api/v2/auditoria/fhir?limite=50&documento=…` (reportero o médico) devuelve los eventos como Bundle `searchset` de `AuditEvent` R4, con el paciente como `Patient/pac-<documento>` y la cadena (seq, hash, hash previo) en una `entity`. Ejemplo validado con `$validate`: `fhir/ejemplos/auditevent_bundle.json`.
- **Métricas.** `hc_auditoria_cadena_ok`, `hc_auditoria_eventos` y `hc_auditoria_ancla_ok` (1 coincide, 0 discrepancia, -1 sin confirmar) en `/metrics` (se verifica como mucho una vez por minuto).
- **Prueba de alteración.** `bash scripts/prueba_auditoria.sh [compose|k8s]` hace una escritura, altera un evento con `psql` (como superusuario, desactivando el disparador), comprueba que el verificador señala ese evento, restaura, borra otro evento y comprueba el salto de secuencia, y restaura de nuevo. Después **reescribe toda la cadena recalculando los hashes** (la cadena local cuadra, el anclaje lo detecta) y **borra los últimos eventos** (la cadena sigue válida pero más corta que lo anclado), y restaura.

Alcance honesto: detecta alteraciones que no recalculan los hashes. Quien tenga permisos de DDL en la base puede desactivar el disparador y recalcular toda la cadena sin que la cadena sola lo note; borrar los últimos eventos no rompe la cadena, solo cambia su cabeza. Eso lo cubre el anclaje en las otras sedes (lo ocurrido en los últimos ~10 s, antes del siguiente anclaje, no está cubierto; las sedes comparten la clave JWT de laboratorio; y si las dos sedes pares fueran comprometidas a la vez no habría con qué comparar). Hyperledger Fabric no se implementó. El anexo de una escritura ocurre después de su commit, no en la misma transacción: si falla, la escritura queda sin evento y solo hay un aviso en el log del pod.

## Identidad federada (MPI)

Unir a dos personas distintas mezcla sus historias, y es peor que dejar un duplicado. Por eso: **solo el documento identifica**
(mismo tipo y número, con datos no contradictorios, se unen solos); los **datos parecidos con documentos distintos** (gemelos, homónimos,
cambio de TI a CC) quedan como *candidatos* que el médico confirma en su vista («es la misma persona» / «son personas distintas»);
**mismo documento con otra fecha de nacimiento y otro nombre** es un *conflicto* y no se une. Cada decisión se guarda en la tabla
replicada `mpi_decision`, vale la más reciente por par (igual en las 3 sedes) y se puede revertir. Sin cadenas por similitud.

API (rol médico): `GET /api/v2/mpi/revision?cod_tipo_documento=&numero_documento=` · `POST /api/v2/mpi/decisiones` ·
`POST /api/v2/mpi/resolver/{id}`; el administrador puede `POST /api/v2/mpi/recalcular` (reconstruye la identidad local con la regla vigente).

**Sedes ya desplegadas:** la tabla es nueva; aplique `bash scripts/migrar_mpi_decision.sh k8s` (o `compose`) una vez, o recree los volúmenes.
Una sede nueva ya la trae (`db/01`, `db/03`).

## TLS

El gateway termina TLS 1.2/1.3 (HSTS; HTTP solo redirige y responde `/healthz`). El certificado lo firma una CA de laboratorio:
`python3 scripts/certificados.py` crea `credenciales/ca.crt` (la que confían los clientes), `ca.key` y `gateway.crt/.key` (ignorados por git;
`k8s_desplegar.sh` los carga como Secret `gateway-tls`, Compose los monta). El certificado cubre `localhost`, `127.0.0.1`, `hc_gateway` y la IP de Minikube.

```bash
curl --cacert credenciales/ca.crt https://$(minikube ip):30443/api/health
```

El navegador avisará hasta que importe `credenciales/ca.crt` como autoridad de confianza. Las APIs directas (`:30101-3`, Compose `:8101-3`) siguen en HTTP solo para pruebas
de laboratorio: en un despliegue real solo se expone el gateway. En Compose el gateway escucha en `https://localhost:8443`.

## Evidencia de ACID

Cada sede es un PostgreSQL con transacciones; la réplica lógica conserva los límites de la transacción. Lo que se demuestra y cómo:

| Propiedad | Evidencia |
|---|---|
| **Atomicidad** | Una transacción de paciente + 2 encuentros cuyo tercer `INSERT` viola un CHECK no deja nada: ni en la sede ni en las réplicas (antes 0\|0, a la mitad `ERROR … violates check constraint`, después 0\|0). Sin el error, la misma transacción llega **completa** a las otras dos sedes. Por la API: prescribir una tecnología con un medicamento inválido (el disparador falla en la 2.ª inserción) no deja la tecnología huérfana, y un egreso con cierre anterior al inicio no deja el egreso ni cierra el encuentro. Sondeando la réplica sin parar, nunca se vio el egreso sin el cierre del encuentro |
| **Consistencia** | La base rechaza una clave foránea, un CHECK y una restricción única inválidos y el contenido no cambia; la API traduce esos errores a 409 o 422 |
| **Aislamiento** | Una sesión no ve lo que otra no ha confirmado (sin lecturas sucias) y una inserción repetida espera a la otra y falla con la restricción única (5 s medidos); ocho peticiones simultáneas por el diagnóstico de ingreso de un encuentro crean exactamente uno |
| **Durabilidad** | `SIGKILL` de la base con una transacción confirmada y otra sin confirmar: al volver, lo confirmado sigue y lo no confirmado desapareció; las réplicas reciben lo confirmado y nunca lo no confirmado |

`bash scripts/prueba_acid.sh [k8s]` imprime el antes, el error y el después; `tests/api/test_acid.py` cubre lo que se ve por HTTP. Alcance: es aislamiento `READ COMMITTED` de PostgreSQL (el predeterminado), no se probó `SERIALIZABLE`;
la réplica entre sedes es **asíncrona**, así que no hay atomicidad ni aislamiento *entre* sedes (una lectura en otra sede puede ver el estado anterior unos milisegundos), solo atomicidad de cada transacción al aplicarse; y la durabilidad es la de un solo nodo por sede (un disco perdido se recupera desde los pares, con el RPO de la réplica).

## Bus de integración (HSB)

Los sistemas de sede que no hablan FHIR (mensajes **HL7 v2** ADT/ORU y archivos **CSV** heredados) entran por el **Health Service Bus** (`hsb/`, FastAPI, imagen `hc-hsb:local`),
que tiene su propia base PostgreSQL (`pg-hsb`) y **entrega a la API de la sede, nunca a las bases**. Cada mensaje recorre
`recibido → validado → transformado → entregado`, o termina en `rechazado` (dato inválido, no se reintenta) o en `reintentando → muerto` (falla transitoria que agotó los intentos).

- **Idempotencia persistida** (`UNIQUE clave`): MSH-10 en HL7 y sha256 de la fila + sede en CSV. Reenviar el mismo mensaje responde `duplicado` y no crea nada.
- **Reintentos con espera exponencial** (`base·2ⁿ⁻¹` con tope), plazo por intento y recuperación de mensajes a medias tras un reinicio (`FOR UPDATE SKIP LOCKED`: varias réplicas no se pisan). Los **muertos** se reencolan a mano (`POST /hsb/mensajes/{id}/reencolar`).
- **Entrega**: Bundle FHIR `transaction` con `PUT` e ids deterministas (`pac-<doc>`, `enc-<sede>-<visita>`, `obs-<msgid>-<n>`) al HAPI y luego a la API v2 de la sede (usuario de servicio `hsb`, mínimo privilegio). Rehacer una entrega no duplica nada.
- **Terminología**: `ref_terminologia` (CIE-10, LOINC, unidades) y `ConceptMap` en `/hsb/terminologia/conceptmap`. Los códigos locales sin equivalencia no se inventan: el mensaje se rechaza con el motivo.
- **Seguridad**: valida el mismo JWT que las sedes. `sistema_sede` envía; admisionista, médico y reportero consultan estado; solo el administrador reencola.

| Ruta (por el gateway `/hsb/`) | Qué hace |
|---|---|
| `POST /hsb/hl7` | Un mensaje HL7 v2 (ADT^A01 u ORU^R01); separadores CR, LF o CRLF |
| `POST /hsb/csv?sede=N` | Archivo CSV heredado de la sede N (cada fila es un mensaje; las que sobran por el presupuesto de tiempo quedan en cola) |
| `GET /hsb/mensajes[?estado=]`, `GET /hsb/mensajes/{id}` | Estado y bitácora de eventos de cada mensaje |
| `POST /hsb/mensajes/{id}/reencolar` | Reencola un mensaje `muerto` (solo el administrador; un `rechazado` se corrige y se reenvía) |
| `GET /hsb/resumen`, `GET /hsb/terminologia[/conceptmap]` | Conteo por estado; terminología |
| `GET /health`, `/health/live`, `/metrics` | Salud y métricas Prometheus (`hsb_mensajes{estado}`, latencia, % fallidos, duplicados, último minuto) |

```bash
# token del usuario de servicio de la sede (la clave sale de credenciales/credenciales.json; no la pegue en el historial)
curl --cacert credenciales/ca.crt -H "Authorization: Bearer $TOKEN" --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 https://localhost:8443/hsb/hl7
```

`ejemplos/` son los archivos del contrato del parcial, **sin modificar**: 01 ADT válido (sede 2), 02 ORU (sede 1), 03 inválido (3 motivos), 04 CSV (sede 3: 3 entregadas, 2 rechazadas), 05 terminología.
Pruebas del bus: `bash scripts/prueba_hsb.sh` (68, PostgreSQL real y destinos simulados), `bash scripts/prueba_hsb_compose.sh` (contrato, duplicado y sede 3 caída, en Compose) y
`bash scripts/prueba_hsb_vivo.sh [--reiniciar]` (Kubernetes: corta el HAPI, comprueba los reintentos y la entrega posterior, un muerto y su reencolado).

## Requisitos

Linux con Docker (y tu usuario en el grupo `docker`), `kubectl` y `minikube` para la ruta de Kubernetes. Python 3 solo para los scripts de experimentos (biblioteca estándar). **RAM**: Minikube con 2,8 GB + un HAPI FHIR (~0,9 GB); en un equipo de 6 GB solo cabe **un HAPI**, por eso los manifiestos lo activan solo en Sincelejo (las otras sedes degradan a «FHIR no disponible» y siguen funcionando).

## Inicio rápido (Kubernetes / Minikube)

```bash
minikube start --driver=docker --memory=2800 --cpus=3
bash scripts/k8s_desplegar.sh          # imagen, 3 sedes, gateway y Prometheus
# El HAPI FHIR de Sincelejo tarda unos minutos en arrancar en frío.
```

| Qué | Dónde |
|---|---|
| **Gateway con HTTPS** (reparte lecturas; `/sede/N/…` apunta a una sede; vistas en `/vistas/`) | `https://$(minikube ip):30443/` (CA: `credenciales/ca.crt`) |
| Gateway HTTP (solo `/healthz` y redirección a HTTPS) | `http://$(minikube ip):30100/` |
| APIs directas de laboratorio, **sin TLS** (pruebas) | `http://$(minikube ip):30101` · `:30102` · `:30103` (vistas en `/vistas/`) |
| Prometheus | `http://$(minikube ip):30090/` |
| Documentación interactiva de la API | `…:30101/docs` |

## Inicio con un solo comando (Docker Compose)

Desde un clon limpio, sin pasos previos (solo Docker):

```bash
docker compose up -d --build        # construye, crea las claves y los certificados y levanta todo
docker compose down -v              # lo borra todo, datos incluidos; el siguiente `up` empieza de cero
```

**Tablero de observabilidad (opcional, bonus).** `docker compose --profile observabilidad up -d` añade Prometheus (`http://localhost:9090`) y Grafana (`http://localhost:3000`, tablero «Historia clínica distribuida · plataforma» ya cargado, de solo lectura y sin contraseña por defecto; ambos escuchan solo en 127.0.0.1). Recogen las tres APIs, el bus, el gateway y el HAPI; la configuración está en `infra/observabilidad/`. En Kubernetes Prometheus ya viene en `infra/k8s/observabilidad/` (`:30090`).

El servicio `init` crea la primera vez las claves aleatorias y los certificados de laboratorio en `credenciales/` (ignorada por git) y entrega a cada servicio solo los secretos que necesita
(`credenciales/runtime/…`, montados como archivos: `HC_JWT_SECRETO_FILE`, etc.); la clave de la CA y las claves en claro del personal no llegan a ningún contenedor de las sedes. Es idempotente: repetir `up` o `down -v` + `up` reutiliza las mismas claves
(para claves nuevas, borre `credenciales/` salvo `LEEME.md`).

| Qué | Dónde |
|---|---|
| Vistas y API por el gateway | `https://localhost:8443/sede/1/vistas/` (también `/sede/2/…`, `/sede/3/…`) |
| Claves del personal (en claro) | `credenciales/credenciales.json` o `python3 scripts/credenciales.py` |
| Certificado de la CA (curl, navegador) | `credenciales/ca.crt` → `curl --cacert credenciales/ca.crt https://localhost:8443/health` |
| Bus de integración | `https://localhost:8443/hsb/…` (con la cuenta `sede`, rol `sistema_sede`) |
| Salud y métricas del gateway | `https://localhost:8443/health` y `/metrics` (formato Prometheus, del exportador oficial de nginx); la API: `/sede/N/api/health` y `/sede/N/metrics`; el bus: `/hsb/health` y `/hsb/metrics` |
| APIs directas (solo laboratorio, HTTP) | `:8101` / `:8102` / `:8103` · HAPI `:8081` · bus `:8000` · PostgreSQL `:5441-5443` |

Por defecto corre **un solo HAPI FHIR** (el de Sincelejo, como en Kubernetes: cada uno pide ~700 MB). Las otras dos sedes degradan a «FHIR no disponible» y siguen registrando. Con RAM de sobra: `docker compose --profile fhir-completo up -d`.
El HAPI tarda decenas de segundos en responder la primera vez. Variables opcionales (acceso desde otro equipo, usuario de las bases): `.env.example`. Las claves de laboratorio quedan con permisos 0600 a nombre de quien creó la carpeta.

## Pruebas

| Qué | Comando |
|---|---|
| **HSB** (67: normalizador HL7/CSV, Bundle FHIR, cola con reintentos, API) | `bash scripts/prueba_hsb.sh` |
| Restricciones del esquema (29) | `docker exec -i <pg> psql -U admin -d historia_clinica -v ON_ERROR_STOP=1 < db/tests/test_restricciones.sql` |
| Unitarias, integración y autenticación/roles de la API (Kubernetes y Compose; 141 pruebas: 45 unitarias, 23 de integración, 12 de autenticación, 9 del MPI, 8 de TLS, 11 del rol `hsb`, 15 de la auditoría (anclaje y AuditEvent incluidos), 8 del reporte de HC, 6 de ACID, 4 de la migración a FHIR con PUT) | `bash scripts/prueba_api_k8s.sh` |
| Unitarias e integración de la API (Compose) | `bash scripts/prueba_api.sh` (`… unit` solo unitarias) |
| 57 de 57 campos en una sede y sus réplicas | `python3 tests/api/escenario_57_campos.py http://IP:30101 http://IP:30102 http://IP:30103` |
| **Demostración completa** (la lista de verificación de la guía: HL7 y CSV a FHIR, duplicado, reporte de 3 sedes, sede apagada, auditoría alterada) | `bash scripts/demo.sh [k8s] --sin-pausas` |
| **Colección de Postman** (24 peticiones, 23 aserciones, con newman) | `bash tests/coleccion/ejecutar.sh [k8s]` |
| **Vistas nuevas** (reporte de HC y su sello, accesos del paciente, tabla del bus, estado de la plataforma; jsdom en un contenedor node, sin Chromium) | `bash scripts/prueba_vistas.sh [compose]` |
| **ACID** (atomicidad, consistencia, aislamiento y durabilidad con SQL real: antes / error a la mitad / después, en la sede y en sus réplicas; incluye un SIGKILL de la base) | `bash scripts/prueba_acid.sh [k8s]` (y `tests/api/test_acid.py` por HTTP) |
| **Carga del bus** (60 ADT sintéticos con 4 hilos, 10 inválidos y 10 reenvíos: mensajes por minuto, latencia y % de fallidos) | `python3 scripts/carga_bus.py` |
| **Alteración de la auditoría** (altera y borra eventos con `psql` y comprueba que el verificador los señala) | `bash scripts/prueba_auditoria.sh [compose\|k8s]` |
| Replicación, aislamiento y caída (Compose) | `bash scripts/prueba_replicacion.sh` |
| **E2E de las 4 vistas en Chromium** (Playwright, 19 pruebas; primera vez construye una imagen de ~1 GB) | `bash scripts/prueba_e2e.sh [compose]` (Minikube por defecto; capturas de lo que falle en `tests/e2e/salida/`) |
| Failover de punta a punta (Compose) | `python3 scripts/prueba_failover.py` |
| Experimentos SRE: pods, base de datos, partición, carga, pérdida de disco (Kubernetes) | `python3 scripts/sre_k8s.py [api gateway rpo particion latencia carga reconstruccion]` |

Los resultados de los experimentos quedan en `docs/resultados_sre.json`.

## CI/CD (GitHub Actions)

`.github/workflows/`: **ci.yml** (calidad en paralelo → integración en Compose y en Minikube con E2E), **nightly.yml** (semanal: failover y SRE),
**cd.yml** (etiqueta `vX.Y.Z`: repite el CI, construye la imagen, la escanea con Trivy, la publica en GHCR con SBOM y procedencia, la firma con cosign y
empaqueta los manifiestos con la imagen fijada por digest; **no despliega** en ningún clúster) y `dependabot.yml`.

Los chequeos de calidad son los mismos en local, solo necesitan Docker (y `kubectl` para los manifiestos):

```bash
bash scripts/ci.sh                 # lint, unitarias, sql, manifiestos, secretos
bash scripts/ci.sh lint sql        # solo algunos
bash scripts/empaquetar_manifiestos.sh ghcr.io/usuario/repo/api@sha256:… dist
```

**Estado honesto:** los workflows pasan actionlint y sus pasos se ejecutaron en local, pero **no se han corrido en GitHub Actions**; las acciones de terceros van
fijadas por etiqueta (no por SHA) y las dependencias de Python por `app/requirements-lock.txt`.

## Copias de seguridad y reconstrucción de una sede (Kubernetes)

Dos protecciones distintas:

| Riesgo | Qué lo cubre | Cómo |
|---|---|---|
| Una sede **pierde su disco** | Se reconstruye desde sus pares (guardan una copia de sus filas): ~30 s, sin perder lo ya replicado | `bash scripts/reconstruir_sede.sh <sede>` (precondición: su `pg-0` ya arrancó con una base vacía) |
| Un **error lógico** (un DELETE o UPDATE malo se replica a las tres sedes) | **Respaldo programado y cifrado** de cada sede | Un CronJob diario (02:00 UTC); ver abajo |

### Respaldos programados (CronJob por sede)

Cada sede vuelca `historia_clinica`, `fhir_db` (si existe) y los roles, comprueba que el volcado se pueda leer y lo **cifra con una clave pública** (age):
el clúster nunca tiene la clave privada. Se guarda en un volumen propio (`respaldos`) con retención (los 14 más recientes y el último de cada uno de
los 6 meses anteriores) y, si configura un destino S3 (rclone), también **fuera del clúster**.

```bash
bash scripts/respaldos.sh claves            # una vez (k8s_desplegar.sh ya lo hace): crea credenciales/respaldo.key y deja la pública en cada sede
bash scripts/respaldos.sh ahora [sede...]   # respaldo manual ahora
bash scripts/respaldos.sh estado            # último éxito de cada sede; sale con 1 si alguna lleva más de 30 h sin respaldar
bash scripts/respaldos.sh traer             # copia los respaldos fuera del clúster (respaldos/cluster/) y comprueba sus sumas
bash scripts/respaldos.sh verificar         # descifra y RESTAURA en un PostgreSQL desechable; compara los conteos con el manifiesto
```

**Guarde `credenciales/respaldo.key` también fuera de este equipo y del repositorio** (gestor de contraseñas): sin ella los respaldos no se pueden leer,
y con ella cualquiera los lee. Para subir una copia a un almacenamiento externo cree en cada sede el Secret `hc-respaldo-remoto` con `RESPALDO_REMOTO`
(`remoto:bucket/ruta`) y las variables `RCLONE_CONFIG_REMOTO_*` de rclone; si la subida falla, el Job falla.

Lo que **sí** se probó: respaldo en las 3 sedes, copia fuera del clúster (contra un servidor S3 local), descifrado y restauración con conteos idénticos al
manifiesto; clave equivocada y archivo manipulado fallan; sin la clave pública el respaldo falla y se ve. Lo que **no**: un proveedor S3 real, la
recuperación a un punto en el tiempo (no hay archivado de WAL: el RPO frente a un error lógico es de hasta ~24 h), el volumen vive en el mismo nodo (solo la
copia externa protege de perder el nodo), ni restaurar **dentro** de la sede (es un procedimiento manual: pause las suscripciones, `pg_restore --no-owner
--no-subscriptions --clean --if-exists` sobre el volcado descifrado y reactívelas). Para sedes ya desplegadas aplique los manifiestos de nuevo
(`bash scripts/k8s_desplegar.sh`). `respaldo_sede.sh` y `probar_respaldo.sh` siguen disponibles como volcado manual sin cifrar.

Detalles que importan: el volcado se hace con `--no-subscriptions`; en Minikube, para **simular** la pérdida del disco hay que borrar también la carpeta
`/tmp/hostpath-provisioner/<namespace>/data-pg-0` del nodo (si no, el volumen nuevo reutiliza los datos). Lo que **no** se recupera por reconstrucción:
lo que la sede escribió y aún no había replicado al caer, y la base `fhir_db` de HAPI (el RDA sigue en `composicion_bundle.bundle_json` y se puede regenerar con
`POST /api/v2/migracion/encuentro/{id}`; el respaldo programado sí incluye `fhir_db`).

## Documento del proyecto

`../Propuesta_Historia_Clinica_Distribuida.docx` (sobre la plantilla del curso) y la presentación de apoyo [`docs/Presentacion_Historia_Clinica_Distribuida.pptx`](docs/Presentacion_Historia_Clinica_Distribuida.pptx) (10 diapositivas con notas del orador). Se regenera con `python3 docs/construir_documento.py`; los diagramas UML están en `docs/uml/*.puml` (PlantUML) y sus imágenes en `docs/img/`.

## Estructura del repositorio

```
app/         API v2 de cada sede (FastAPI): hc_api/ (main, auth, auditoria, mpi, fhir, reporte, campos57, static/ = las 4 vistas), Dockerfile
hsb/         bus de integración (HSB): hc_hsb/ (hl7, csvlegado, normalizador, fhir, destinos, bus, db), datos/ref_terminologia.csv, tests/ (67)
fhir/        Bundles FHIR de ejemplo generados por el código (ejemplos/) y validar.sh (Bundle/$validate de HAPI)
db/          esquema de 45 tablas (01), semillas (02), réplica (03), fhir_db (04), migraciones/ y tests/ (29 pruebas SQL)
infra/       k8s/ (base, overlays por sede, gateway, hsb, observabilidad) · gateway/ (nginx de Compose) · backup/ (respaldo cifrado) · init/ (claves y certificados)
tests/       api/ (unitarias, integración, seguridad, ACID, auditoría, reporte; se montan en la imagen de la API) · e2e/ (Playwright y jsdom) · coleccion/ (Postman)
ejemplos/    contrato del HSB: mensajes HL7 y CSV del parcial, SIN modificar
docs/        UML (PlantUML), imágenes, bitácora, auditoría del parcial, resultados SRE y el generador del documento
scripts/     despliegue, pruebas, experimentos, demostración (demo.sh) y operación (nodo.sh, respaldos.sh)
docker-compose.yml   un solo comando: sedes, HAPI, HSB, gateway y métricas
.github/     workflows de CI, nocturno y CD, y Dependabot
credenciales/        generada al arrancar (ignorada por git); LEEME.md explica cada archivo
v1/          versión 1 del laboratorio, archivada (no es la que se evalúa)
```

## Limitaciones conocidas (resumen; detalle en el documento)

- **Seguridad parcial.** Hay autenticación por roles, registro local de accesos y TLS en el gateway, pero los puertos directos de las APIs de laboratorio son HTTP, la réplica entre bases y API-HAPI no van cifradas, no hay cifrado en reposo, ni OpenID Connect/SMART on FHIR, ni revocación de tokens (vencen a las 8 h el personal y a los 30 min el paciente), ni registro de consentimiento (Ley 1581), ni auditoría ATNA completa. El paciente se identifica con dato semipúblico (documento + fecha de nacimiento): sirve para el laboratorio, no para producción. El límite de intentos fallidos se lleva en memoria de cada réplica de la API. No usar con datos reales.
- Un PostgreSQL por sede (sin alta disponibilidad interna). La pérdida de disco se recupera desde los pares, pero la recuperación es **manual**. Los respaldos programados y cifrados cubren errores lógicos (RPO de hasta ~24 h, sin recuperación a un punto en el tiempo); la copia fuera del clúster es opcional y solo se probó contra un servidor S3 local.
- El HSB entrega a un único HAPI (Sincelejo) en el laboratorio y los códigos locales del segmento DG1 no se mapean a propósito; HAPI solo en Sincelejo en el entorno de pruebas; los 5 Bundle de `fhir/ejemplos/` pasan `Bundle/$validate` de HAPI **sin errores** (`bash fhir/validar.sh`; quedan advertencias de narrativa y de «performer»). El validador necesita metaspace: con 160 MB / 700 MB se agotaba tras el primer uso del HAPI; con 256 MB / 820 MB (docker-compose.yml) validó los 5 Bundle incluso después de las migraciones. Varias llamadas seguidas o interrumpidas pueden dejar al HAPI sin responder hasta reiniciarlo. Al migrar un encuentro, la API sube sus recursos propios (Patient `pac-<documento>`, Encounter, Condition, Observation…) en una transacción de `PUT` con ids deterministas y el RDA con `PUT Bundle/rda-<encuentro>`: migrar dos veces **no duplica** (`GET /api/v2/bundles/{id}?verificar_hapi=true` cuenta los recursos propios en HAPI).
- El MPI no une por similitud: documentos distintos con datos parecidos (gemelos, homónimos, cambio de TI a CC) requieren que un médico confirme la decisión; no hay cola central de revisión ni avisos, y la decisión se aplica por par de registros (no hay deshacer en cadena). El puntaje es simple, no probabilístico.
- Pruebas hechas en un solo equipo y un solo nodo de Kubernetes; la partición de red se simuló.
- Credenciales de la base (`admin`, `repl_secret`) en los manifiestos; las claves de las vistas son aleatorias y quedan fuera del repositorio.

## Problemas frecuentes

- `permission denied … docker.sock`: tu sesión aún no tiene el grupo `docker` (`newgrp docker` o cerrar sesión).
- HAPI responde 400 desde la API: el nombre de host no puede llevar guion bajo (Tomcat); use `hapi` o `hapi-<sede>`.
- HAPI `OOMKilled`: suba `limits.memory` en `infra/k8s/base/hapi.yaml` (940 Mi con montón de 400 MB funcionó en pruebas; con 320 MB de montón el HAPI pasaba el tiempo en recolecciones completas y las migraciones a FHIR tardaban ~34 s).
- Una sede con la CPU muy saturada (p. ej. HAPI arrancando en frío con poca RAM) puede marcarse no lista: la API usa `DB_CONNECT_TIMEOUT=1` para fallar rápido cuando la base cae; súbalo a 2 o 3 si lo ve flapear.
- La primera llamada a `/api/health` tras arrancar HAPI en frío puede tardar decenas de segundos; espere a que responda antes del failover.
- Tras recrear una API en Compose, reinicie el gateway (`docker restart hc_gateway`): nginx guarda las IP al arrancar. En Kubernetes no hace falta.
