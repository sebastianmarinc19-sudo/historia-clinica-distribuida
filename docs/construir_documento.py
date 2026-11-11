#!/usr/bin/env python3
"""Genera el documento del proyecto sobre la plantilla del curso (Plantilla_Proyecto_Interoperabilidad_v7.docx).

    python3 docs/construir_documento.py

Lee los diagramas de docs/img, las capturas de las vistas y las cifras de
docs/resultados_sre.json, y escribe ../Propuesta_Historia_Clinica_Distribuida.docx
junto a la plantilla. Solo usa la biblioteca estándar.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from docx_lib import (Imagenes, codigo, construir, h1, h2, justificado, p, pie, tabla, viñetas)

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PARCIAL = os.path.dirname(RAIZ)
PLANTILLA = os.path.join(PARCIAL, "Plantilla_Proyecto_Interoperabilidad_v7.docx")
SALIDA = os.path.join(PARCIAL, "Propuesta_Historia_Clinica_Distribuida.docx")
IMG = os.path.join(RAIZ, "docs", "img")

_J = json.load(open(os.path.join(RAIZ, "docs", "resultados_sre.json"), encoding="utf-8"))
R = _J["experimentos"]
NOBJ = len(_J["objetivos"])
rc = R["reconstruccion"]
assert all(_J["objetivos"].values()), "hay objetivos SRE sin cumplir: revise antes de redactar"
fmt = lambda x, d=1: f"{x:.{d}f}".replace(".", ",")
miles = lambda n: f"{n:,}".replace(",", " ")

imagenes = Imagenes()
cuerpo = []
add = cuerpo.append
_fig = [0]
_tab = [0]


def figura(archivo, ancho, texto, alt=None):
    _fig[0] += 1
    add(imagenes.en_linea(os.path.join(IMG, archivo), ancho, alt or texto))
    add(pie(f"Figura {_fig[0]}. {texto}"))


def tabla_con_pie(encabezado, filas, anchos, texto, **kw):
    _tab[0] += 1
    add(tabla(encabezado, filas, anchos, **kw))
    add(pie(f"Tabla {_tab[0]}. {texto}"))


def par(texto, **kw):
    add(justificado(texto, **kw))


def extraer(archivo, desde, hasta):
    """Fragmento de código real del repositorio (para los anexos)."""
    fuente = open(os.path.join(RAIZ, archivo), encoding="utf-8").read()
    i = fuente.index(desde)
    j = fuente.index(hasta, i) if hasta else len(fuente)
    return fuente[i:j].rstrip()


TITULO = "Reingeniería de una historia clínica distribuida interoperable: sedes autónomas con replicación lógica, HL7 FHIR y Kubernetes"
AUTORES = "Marín, Sebastián; Tuiran, Halit"

# ====================================================================== PORTADA
add(p(TITULO.upper(), jc="center", b=True, despues=120))
add(p(f"Autores: {AUTORES}", jc="center"))
add(p("Sincelejo, Colombia", jc="center"))
add(p("Correo electrónico: maceadmon@gmail.com", jc="center"))
add(p("Sistemas Distribuidos · Docente: Jaider Reyes · Corporación Universitaria Antonio José de Sucre (UAJS)", jc="center", despues=200, sz=21))

# ====================================================================== RESUMEN
add(h1("RESUMEN / ABSTRACT"))
par("Este trabajo presenta la reingeniería de un sistema de historia clínica distribuida para que tres sedes (Sincelejo, Cartagena y Corozal) "
    "sigan operando cuando una cae o queda aislada. El diseño original fragmentaba a los pacientes por rango de documento y concentraba aplicación, "
    "servidor FHIR e identidad federada en puntos únicos de falla. La propuesta combina el modelo relacional de 57 campos de la Resolución 866 "
    "de 2021 (45 tablas); una base PostgreSQL por sede con replicación lógica en malla y una regla de sede dueña por fila que evita conflictos de "
    "escritura; un índice maestro de pacientes (MPI) determinista calculado en cada sede; un servidor HAPI FHIR R4 por sede; un bus de integración (HSB) "
    "que recibe HL7 v2 y CSV, los valida, evita duplicados con idempotencia persistida y los entrega con reintentos; y cuatro vistas web "
    "que verifican los casos de uso CU-01 a CU-15. Se desplegó en Kubernetes y se validó con 141 pruebas de API, 68 del bus, 19 E2E, 29 de restricciones SQL, "
    f"32 comprobaciones de failover y {NOBJ} objetivos SRE. "
    f"En un clúster Minikube de un nodo, la caída de la base de una sede se recuperó en {fmt(R['rpo']['rto_base_sede_s'])} s mientras las otras seguían "
    f"sirviendo su historia, el retraso de réplica fue de {fmt(R['latencia_replicacion']['p95_ms'], 0)} ms (p95) y no se perdió ninguna escritura "
    f"confirmada al reiniciar. La carga alcanzó unas {miles(R['carga']['transacciones_por_minuto'])} transacciones por minuto, por debajo de la meta de "
    "10 000. Hay autenticación por roles y TLS; faltan consentimiento y cifrado en reposo.")
par("**Abstract.** This work re-engineers a distributed electronic health record so that three sites (Sincelejo, Cartagena and Corozal) keep working when one "
    "of them fails or is partitioned. The original design sharded patients by identity-number range and kept the application, the FHIR server and the "
    "federated identity in single points of failure. The proposal combines the 57-field relational model of Colombian Resolution 866 of 2021; one "
    "PostgreSQL database per site with full-mesh logical replication and a row-owner rule that avoids write conflicts; a deterministic master patient "
    "index computed locally at each site; one HAPI FHIR R4 server per site; a health service bus that ingests HL7 v2 messages and CSV files, validates them, "
    "deduplicates them with persisted idempotency and delivers them with retries; and four web "
    "views used to verify use cases CU-01 to CU-15. It was deployed on Kubernetes and tested on a "
    f"single-node Minikube cluster: a site database crash recovered in {fmt(R['rpo']['rto_base_sede_s']).replace(',', '.')} s while the other sites kept serving its records, replication delay was {fmt(R['latencia_replicacion']['p95_ms'], 0)} ms "
    f"(p95), and no acknowledged write was lost after a restart. Throughput reached about {miles(R['carga']['transacciones_por_minuto']).replace(chr(160), ',').replace(' ', ',')} transactions per minute, below the 10,000 target. "
    "Role-based authentication and TLS are implemented; consent, encryption at rest and full ATNA auditing remain future work.")
par("**Palabras clave:** HL7 FHIR; historia clínica distribuida; replicación lógica; PostgreSQL; Kubernetes; ingeniería de confiabilidad (SRE); "
    "índice maestro de pacientes (MPI); Resolución 866 de 2021.")

# ====================================================================== INTRODUCCIÓN
add(h1("INTRODUCCIÓN"))
par("Una historia clínica útil es la que está disponible cuando el paciente llega, sin importar en qué sede fue atendido antes ni si alguna sede "
    "tiene una falla. En Colombia, la Resolución 866 de 2021 define 57 elementos de datos clínicos mínimos que deben poder intercambiarse "
    "(MinSalud y MinTIC, 2021), y el uso de HL7 FHIR crece de forma sostenida en la literatura "
    "reciente (Lehne et al., 2019; Vorisek et al., 2022; Gazzarata et al., 2024). Sin embargo, interoperar no basta: si la historia vive en un "
    "repositorio único, la caída de ese repositorio detiene a todas las sedes.")
par("El proyecto de partida («historia-clinica-distribuida») repartía a los pacientes en tres bases de datos según el rango numérico del documento de "
    "identidad, con una sola aplicación, un solo servidor HAPI FHIR y su base alojada en el primer nodo. Eso reproduce el problema que se quería evitar: "
    "si cae el primer nodo se pierden la aplicación, el FHIR y los pacientes de su rango. La reingeniería que se presenta cambia el criterio de "
    "distribución (por sede real, no por rango de documento) y sustituye los puntos únicos de falla por sedes autónomas que se replican entre sí.")
par("**Aportes.** (1) Un esquema reconstruido y verificado con 45 tablas que cubre los 57 campos; (2) una arquitectura de sedes autónomas con replicación lógica, "
    "regla de sede dueña e identidad federada determinista; (3) un bus de integración (HSB) que lleva HL7 v2 y CSV a FHIR con idempotencia y reintentos; "
    "(4) una API v2 y un HAPI FHIR por sede con los casos de uso CU-01 a CU-15, auditoría encadenada por hash y cuatro vistas web (Admisionista, Médico, Paciente y Reportero) para verificarlos; "
    "(5) un despliegue de un solo comando y en Kubernetes con métricas, evidencia ACID y experimentos de fallo que miden RTO, RPO y objetivos de nivel de servicio (SLO); y (6) un registro honesto de lo que no se logró.")
par("El documento sigue la plantilla del curso. Las secciones finales (viabilidad técnica, interoperabilidad basada en datos y validación de modelos UML) "
    "responden a los puntos de la plantilla indicando, para cada uno, si está implementado, parcial o pendiente.")

# ====================================================================== OBJETIVOS
add(h1("OBJETIVOS"))
add(h2("Objetivo general"))
par("Diseñar, implementar y validar un sistema de historia clínica interoperable, distribuido en tres sedes autónomas, que siga operando cuando una sede "
    "falla o queda aislada, con bases de datos distribuidas por replicación y cumpliendo el modelo de 57 campos de la Resolución 866 de 2021 y HL7 FHIR R4.")
add(h2("Objetivos específicos"))
add(viñetas([
    "Reconstruir y validar el esquema relacional normalizado (45 tablas: 29 catálogos y 16 tablas de núcleo) que cubre los 57 campos, y replicarlo entre las tres sedes sin conflictos de escritura ni servicio central, midiendo el retraso de réplica.",
    "Resolver la identidad federada de un paciente de forma determinista y generar su RDA como Bundle FHIR de tipo document en un servidor HAPI FHIR por sede.",
    "Integrar los sistemas legados de las sedes mediante un bus de servicios de salud que reciba HL7 v2 y CSV, valide y normalice a FHIR con idempotencia persistida, reintentos y mensajes muertos.",
    "Ofrecer cuatro vistas con acceso por rol y auditoría encadenada por hash, y desplegarlo con un solo comando (Docker Compose) y en Kubernetes, midiendo RTO, RPO, ACID y carga.",
]))

# ====================================================================== MARCO TEÓRICO
add(h1("MARCO TEÓRICO"))
add(h2("Interoperabilidad en salud y HL7 FHIR"))
par("La interoperabilidad se suele describir en tres niveles: técnico (cómo viajan los datos), semántico (qué significan) y organizacional (quién los gobierna). "
    "HL7 FHIR modela la información clínica como recursos (Patient, Encounter, Condition, Observation…) accesibles por una API REST y agrupables en Bundles; "
    "su diseño pensado para la web explica su rápida adopción frente a HL7 v2 y CDA (Bender y Sartipi, 2013; HL7 International, 2019). Un Bundle de tipo "
    "*document* cuyo primer recurso es una Composition permite entregar una atención completa como un documento clínico autocontenido; es la forma que se usa "
    "aquí para el RDA. Las plataformas basadas en FHIR también se han utilizado como base para aplicaciones clínicas autorizadas (Mandel et al., 2016).")
add(h2("Sistemas distribuidos: disponibilidad frente a consistencia"))
par("El teorema CAP indica que, ante una partición de red, un sistema debe elegir entre consistencia y disponibilidad; en la práctica, la decisión se "
    "toma por operación y el diseño debe gestionar la partición en lugar de ignorarla (Brewer, 2012). Para una historia clínica, no poder atender a un "
    "paciente es peor que ver durante unos segundos una copia ligeramente atrasada, por lo que este proyecto elige disponibilidad con *consistencia eventual* "
    "(Vogels, 2009) y la acota con reglas de dominio: cada fila tiene una sola sede dueña que la escribe, de modo que las réplicas no entran en conflicto. "
    "Existen alternativas con convergencia automática, como los tipos de datos replicados sin conflicto (Shapiro et al., 2011), pero exigen modelar cada dato "
    "como un CRDT; la regla de sede dueña es más simple y encaja con la realidad clínica (una atención ocurre en una sede).")
add(h2("Replicación lógica de PostgreSQL"))
par("La replicación lógica de PostgreSQL publica los cambios de tablas concretas (publicación) y los aplica en otro servidor (suscripción) a partir del "
    "registro de escritura anticipada (WAL), con un *slot* que conserva los cambios pendientes mientras el suscriptor está desconectado (PostgreSQL "
    "Global Development Group, 2024). Dos propiedades condicionan el diseño: el proceso de aplicación omite las claves foráneas y los disparadores, y "
    "las restricciones únicas sí se aplican, de modo que dos sedes que inserten la misma clave detendrían la réplica. Por eso la unicidad se define por sede "
    "y el parámetro `origin = none` evita que una sede reenvíe lo que recibió de otra.")
add(h2("Identidad de pacientes"))
par("Un índice maestro de pacientes (MPI) agrupa los registros de una misma persona en distintos sistemas. La literatura clásica sobre vinculación de registros "
    "plantea un modelo probabilístico (Fellegi y Sunter, 1969). Aquí se parte de un puntaje simple, tomado del laboratorio del curso (0,6 por similitud de nombre, 0,3 por fecha de nacimiento y 0,1 por sexo, con umbral de 0,9), "
    "pero se usa con una política conservadora: unir a dos personas distintas mezcla sus historias, y es peor que dejar un duplicado. Por eso solo el documento une solo; "
    "los datos parecidos con documentos distintos (gemelos, homónimos) quedan como candidatos que una persona confirma, y esa decisión se replica a las tres sedes. "
    "El resultado es determinista: el identificador depende solo del miembro «ancla» del grupo, no de qué sede resolvió ni de cuándo.")
add(h2("Confiabilidad de sitios (SRE) y orquestación"))
par("La ingeniería de confiabilidad define indicadores (SLI) y objetivos (SLO) medibles, y distingue el tiempo de recuperación (RTO) de la pérdida "
    "tolerable de datos (RPO) (Beyer et al., 2016). Kubernetes aporta las piezas para cumplirlos: Deployments con réplicas, StatefulSets con disco persistente, "
    "Services con IP estable y sondas de vida y de disponibilidad que sacan del servicio a un pod enfermo (The Kubernetes Authors, 2024).")
add(h2("Marco normativo"))
par("La Resolución 866 de 2021 define los 57 elementos de datos clínicos relevantes para la interoperabilidad; el tratamiento de datos personales de salud "
    "está sujeto a la Ley Estatutaria 1581 de 2012 (Congreso de la República de Colombia, 2012). Esta última exige, entre otras cosas, autorización, "
    "seguridad y trazabilidad, que el prototipo aún no implementa (véase la sección de viabilidad técnica).")

# ====================================================================== MARCO CONCEPTUAL
add(h1("MARCO CONCEPTUAL"))
par("La tabla siguiente define los conceptos clave y su papel en el proyecto.")
tabla_con_pie(["Concepto", "Definición", "En este proyecto"], [
    ["**FHIR / Recurso**", "Estándar HL7 de intercambio; un recurso es la unidad de información (Patient, Encounter…).", "HAPI FHIR R4 por sede; recursos Patient, Encounter, Condition, MedicationRequest, Procedure, Observation y Composition."],
    ["**Bundle document / RDA**", "Conjunto de recursos cuyo primer elemento es una Composition; forma un documento clínico.", "El Reporte de Detalle de Atención de un encuentro."],
    ["**Perfil y terminología**", "Restricciones sobre un recurso y vocabularios controlados (CIE-10, LOINC, UCUM).", "Catálogos locales de muestra; no hay perfiles propios ni servidor de terminología."],
    ["**API RESTful**", "Interfaz HTTP basada en recursos y verbos.", "API v2 por sede (unas 30 rutas) y cuatro vistas web que la consumen."],
    ["**Sede dueña**", "Única sede autorizada a escribir una fila.", "Cada fila clínica la escribe la sede que la creó; las demás ven una copia de solo lectura (HTTP 409 si intentan escribir)."],
    ["**Réplica lógica**", "Copia de tablas mediante publicación y suscripción.", "Malla completa de 6 suscripciones entre las 3 sedes."],
    ["**MPI / identidad federada**", "Agrupación de registros de una misma persona.", "Calculada localmente en cada sede, sin servicio central."],
    ["**Encuentro**", "Atención de un paciente en una sede (contacto con el servicio).", "Núcleo del modelo: de él cuelgan triage, diagnósticos, tecnologías, resultados, egreso y RDA."],
    ["**RTO / RPO**", "Tiempo para recuperar el servicio / datos que se pueden perder.", "Medidos en los experimentos SRE."],
    ["**SLI / SLO**", "Indicador medido y objetivo sobre ese indicador.", f"Métricas Prometheus y {NOBJ} objetivos propuestos por el equipo."],
], [1900, 3300, 3642], "Conceptos clave y su uso en el proyecto.")

# ====================================================================== ESTADO DEL ARTE
add(h1("ESTADO DEL ARTE"))
add(h2("Panorama global"))
par("Las revisiones de la literatura documentan un uso creciente de FHIR para el intercambio de datos clínicos y de investigación (Lehne et al., 2019; "
    "Vorisek et al., 2022; Gazzarata et al., 2024, esta última centrada en la gestión de enfermedades crónicas). Pedrera-Jiménez et al. (2023) analizan cómo conviven FHIR, openEHR e ISO 13606 en espacios de datos de salud, "
    "y proponen elegir el estándar según el caso de uso. Para arquitecturas, Bettoni et al. (2021) aplican FHIR en microservicios para navegación de pacientes, "
    "lo que respalda el patrón de servicios independientes por sede.")
add(h2("Latinoamérica y Colombia"))
par("En Colombia, la Resolución 866 de 2021 fija el conjunto de datos que debe poder intercambiarse (MinSalud y MinTIC, 2021). Este trabajo toma esos 57 elementos como contrato de datos y los lleva a un "
    "esquema relacional trazable campo por campo (CU-15).")
add(h2("Enfoques de distribución de datos"))
tabla_con_pie(["Enfoque", "Qué resuelve", "Brecha frente al objetivo"], [
    ["Repositorio FHIR central (HAPI, Smile CDR)", "Interoperabilidad por estándar y consulta unificada.", "Punto único de falla: si cae, ninguna sede consulta."],
    ["PostgreSQL distribuido con coordinador (Citus)", "Escala horizontal por fragmentos.", "El coordinador es un punto de entrada único; una sede aislada no puede operar por sí sola."],
    ["Primario y réplica con conmutación (Patroni)", "Alta disponibilidad dentro de un sitio.", "No da autonomía de escritura entre sedes distintas."],
    ["Multimaestro / CRDT", "Convergencia sin coordinación.", "Exige modelar cada dato como un tipo convergente (Shapiro et al., 2011); complejo para datos clínicos."],
    ["**Propuesta: sedes autónomas con sede dueña**", "Cada sede opera sola y replica a las demás; sin conflictos por construcción.", "Consistencia eventual; los registros de una sede caída son de solo lectura en las otras."],
], [2500, 3000, 3342], "Comparación de enfoques de distribución frente al objetivo del proyecto.")
add(h2("Brechas y oportunidades"))
par("En la literatura que se revisó no se encontró un trabajo que combine, sobre el modelo de 57 campos colombiano, autonomía operativa por sede, réplica "
    "entre sedes, identidad federada sin servicio central y evidencia de pruebas de fallo. Esta es la oportunidad que aborda el proyecto. Se debe leer con cautela: "
    "la búsqueda fue acotada a las fuentes del equipo y no constituye una revisión sistemática.")

# ====================================================================== SOLUCIÓN
add(h1("SOLUCIÓN PROPUESTA Y METODOLOGÍA"))
add(h2("Arquitectura"))
par("Cada sede es un sistema completo y autónomo: una base PostgreSQL (con la base clínica y la base propia de HAPI FHIR), un servidor HAPI FHIR R4 y una "
    "API v2 con dos réplicas. Un gateway reparte las lecturas entre las sedes sanas y permite apuntar a una sede concreta para escribir. Los datos clínicos "
    "se replican entre las tres bases y Prometheus recoge las métricas (Figura 1).")
figura("01_arquitectura.png", 5.1, "Arquitectura: tres sedes autónomas con replicación lógica entre sí.",
       "Diagrama de arquitectura con tres sedes, gateway, Prometheus y flechas de replicación lógica entre las bases")
add(h2("Decisiones de diseño"))
tabla_con_pie(["Decisión", "Alternativa descartada", "Razón"], [
    ["Replicación lógica en malla completa", "Citus (coordinador y trabajadores)", "El coordinador sería un punto único y una sede aislada no podría operar."],
    ["Sede dueña por fila (un solo escritor)", "Multimaestro con resolución de conflictos", "Evita conflictos por construcción; encaja con que una atención ocurre en una sede."],
    ["MPI derivado y determinista, calculado en cada sede", "Servicio MPI central", "Sin punto único de falla; dos sedes llegan al mismo id_mpi sin coordinarse."],
    ["HAPI FHIR por sede", "Un HAPI compartido", "Un HAPI compartido sería el punto único que se quería eliminar."],
    ["`bundle_json` replicado junto al RDA", "Leer el RDA siempre del HAPI de la sede dueña", "El RDA sigue consultable aunque esa sede esté caída."],
    ["Vistas estáticas sin recursos externos", "Plantillas con fuentes e iconos de CDN", "Deben cargar aunque la sede esté aislada de Internet."],
    ["Prometheus siempre; Grafana solo como perfil opcional de Compose", "Prometheus y Grafana siempre", "Junto al clúster de un nodo no caben en 5,7 GB de RAM: en Kubernetes los SLI se consultan por Prometheus y por la API HTTP, y el tablero de Grafana se activa con `docker compose --profile observabilidad up -d`."],
], [2900, 2700, 3242], "Decisiones de diseño y alternativas descartadas.")
add(h2("Tecnologías empleadas"))
tabla_con_pie(["Componente", "Tecnología", "Rol"], [
    ["Base de datos", "PostgreSQL 16 (replicación lógica)", "Una instancia por sede; `wal_level=logical`, `origin = none`."],
    ["Servidor FHIR", "HAPI FHIR v6.8.0 (R4 4.0.1)", "Almacén del RDA y del Patient de cada sede."],
    ["API", "Python 3.11, FastAPI, psycopg2, httpx", "Casos de uso, regla de sede dueña, MPI y generación del RDA."],
    ["Vistas", "HTML, CSS y JavaScript sin dependencias", "Cuatro vistas servidas por la propia API."],
    ["Orquestación", "Docker, Docker Compose, Kubernetes (Minikube), Kustomize", "Despliegue de desarrollo y de pruebas de fallo."],
    ["Gateway", "nginx 1.27", "Reparto de lecturas con reintento en otra sede."],
    ["Observabilidad", "Prometheus v2.53", "SLI de disponibilidad, latencia, estado de la base y retraso de réplica."],
    ["Modelado y pruebas", "PlantUML, pytest, scripts de caos propios", "Diagramas UML, pruebas unitarias e integrales, experimentos SRE."],
], [1900, 3300, 3642], "Pila tecnológica.")
add(h2("Metodología y hoja de ruta"))
par("Se trabajó por iteraciones cortas y cada una cerró con verificación ejecutable: el esquema con pruebas de restricciones, la réplica con pruebas de "
    "aislamiento y caída, la API con pruebas de integración, y el despliegue con experimentos SRE. No se aplicó Scrum de forma formal; sí se mantuvo la "
    "práctica DevOps de que todo se reproduce con comandos versionados.")
tabla_con_pie(["Fase", "Entregable", "Estado"], [
    ["1. Esquema de 57 campos", "45 tablas, semillas, pruebas de restricciones sobre PostgreSQL real (29 hoy)", "Completa"],
    ["2. Replicación entre sedes", "Malla de 6 suscripciones; pruebas de propagación, aislamiento y caída", "Completa"],
    ["3. API v2 y FHIR por sede", "CU-01 a CU-15, MPI determinista, RDA, gateway; 13 unitarias y 17 de integración", "Completa (HAPI probado en una sede)"],
    ["4. Kubernetes y SRE", "Kustomize, métricas Prometheus, experimentos de caos y carga", "Completa"],
    ["5. Vistas y documento", "Cuatro vistas web, 6 pruebas de integración adicionales, la demostración de los 57 campos y este documento", "Completa"],
    ["6. Siguientes", "Consentimiento, HPA, alta disponibilidad dentro de la sede, ejecutar el CI/CD en GitHub, terminologías", "Pendiente"],
], [2500, 4900, 1442], "Hoja de ruta de implementación.")

# ====================================================================== UML
add(h1("MODELADO UML"))
par("Los diagramas se escribieron en PlantUML y sus fuentes están en `docs/uml`. Los casos de uso se organizan en las cuatro vistas que exige el curso.")
add(h2("Diagrama de Casos de Uso"))
par("El modelo original del laboratorio tenía siete actores. Se reagruparon en las cuatro vistas: el **Admisionista** registra y abre el encuentro (con el triage, "
    "como en el módulo de admisión del proyecto original); el **Médico** atiende y, al cerrar, genera el RDA; el **Paciente** consulta su propia historia; y el "
    "**Reportero** produce los reportes de cobertura y auditoría (Figura 2, Tabla 6).")
figura("02_casos_de_uso.png", 6.1, "Casos de uso CU-01 a CU-15 organizados en las cuatro vistas.",
       "Diagrama de casos de uso con los actores Admisionista, Médico, Paciente, Reportero y HAPI FHIR")
tabla_con_pie(["Actor del modelo original", "Vista", "Casos de uso"], [
    ["Personal de admisión", "Admisionista", "CU-01, CU-02, CU-03"],
    ["Enfermería (triage, entregas, resultados)", "Admisionista (triage) y Médico (entregas y resultados)", "CU-03, CU-06, CU-07"],
    ["Médico tratante", "Médico", "CU-04, CU-05, CU-08, CU-09, CU-13"],
    ["Ingeniero de interoperabilidad", "Médico (botón «Migrar a FHIR»)", "CU-10, CU-11, CU-12"],
    ["*(no existía)* Paciente", "Paciente", "CU-13 y CU-12 en solo lectura"],
    ["Administrador de plataforma y Auditor de calidad", "Reportero", "CU-14, CU-15 y estado de la réplica"],
], [3300, 3300, 2242], "Correspondencia entre los actores originales y las cuatro vistas.")
add(h2("Diagrama de Secuencias"))
par("La Figura 3 muestra el flujo completo: registro en la sede dueña, migración a FHIR con generación del RDA y resolución del MPI, y la consulta "
    "federada desde otra sede, que se resuelve con la copia local y por eso funciona aunque la sede dueña esté caída.")
figura("03_secuencia_migracion_federada.png", 5.0, "Secuencia de registro, migración a FHIR y consulta federada.",
       "Diagrama de secuencia con médico de Sincelejo, API, base, HAPI, réplica en Cartagena y médico de Cartagena")
add(h2("Diagrama de Clases"))
par("Las 16 tablas de núcleo se dividen en dos figuras. La primera cubre la organización y la identidad; la segunda, el detalle clínico del encuentro. Los 29 "
    "catálogos se referencian por código y no se dibujan.")
figura("04a_clases_identidad.png", 3.9, "Diagrama de clases (1/2): organización, identidad y federación.",
       "Clases Prestador, Sede, ProfesionalSalud, Paciente, IdentidadFederada, Encuentro y ComposicionBundle")
figura("04b_clases_clinico.png", 5.4, "Diagrama de clases (2/2): detalle clínico del encuentro.",
       "Clases del detalle clínico: triage, egreso, diagnóstico, tecnología, medicamento, entrega, observación, antecedente y exposición")
add(h2("Diagrama de Estados"))
par("El encuentro tiene dos estados que evolucionan por separado: la atención (abierto o cerrado) y la migración a FHIR (PENDIENTE, MIGRADO o ERROR), "
    "esta última restringida con un CHECK en la base de datos (Figura 6). La sede, por su parte, pasa por cuatro estados operativos frente a fallos (Figura 7).")
figura("05_estados_encuentro.png", 4.2, "Estados de un encuentro: atención y migración a FHIR.",
       "Diagrama de estados del encuentro con atención y migración")
figura("06_estados_sede.png", 4.6, "Estados operativos de una sede frente a fallos.",
       "Diagrama de estados de una sede: operativa, aislada, caída y recuperando")

# ====================================================================== PROCESO
add(h1("PROCESO DE DESARROLLO"))
add(h2("Fases"))
add(viñetas([
    "**Análisis.** Lectura del informe del laboratorio, del modelo de 57 campos y del repositorio. Hallazgo clave: el código v2 que describe el informe no estaba en el repositorio; se reconstruyó desde el modelo.",
    "**Diseño.** Decisiones de la Tabla 3: sede dueña, réplica lógica, MPI determinista, HAPI por sede.",
    "**Desarrollo.** Esquema SQL → réplica → API → manifiestos de Kubernetes → vistas, en ese orden, verificando cada capa antes de apilar la siguiente.",
    "**Pruebas.** Restricciones en PostgreSQL real, propagación y fallos entre sedes, integración de la API, experimentos SRE y pruebas E2E de las vistas en Chromium.",
    "**Despliegue.** Docker Compose para iterar y Kubernetes (Minikube) para las pruebas de fallo y de carga.",
]))
add(h2("Herramientas de soporte y límites"))
par("Los despliegues y las pruebas se reproducen con comandos versionados (Anexo A). Tampoco se usó Visual Paradigm ni Figma: los diagramas se hicieron con PlantUML y las "
    "interfaces se programaron directamente.")
add(h2("Integración y entrega continuas"))
par("El repositorio incluye un pipeline de GitHub Actions en tres flujos más Dependabot. Para que lo que corre en la nube sea lo mismo que se prueba en el equipo, los chequeos de calidad "
    "viven en un solo script (`scripts/ci.sh`) que usa contenedores, y los jobs de integración llaman a los mismos scripts de prueba. "
    "**El pipeline está escrito y validado con actionlint y se ejecutó paso a paso en local, pero no se ha corrido en GitHub Actions**: las acciones de terceros (setup-minikube, GHCR, Trivy, cosign) "
    "y los tiempos en un ejecutor de 2 a 4 núcleos no se han probado.")
tabla_con_pie(["Flujo", "Cuándo", "Qué hace"], [
    ["CI · calidad", "Cada push y pull request", "En paralelo: ruff (errores y pyflakes), shellcheck, retención de respaldos, 28 pruebas unitarias, 29 pruebas SQL en un PostgreSQL limpio, validación de 56 recursos de Kubernetes con kubeconform y búsqueda de secretos (archivos sensibles versionados y gitleaks sobre todo el historial)."],
    ["CI · integración", "Tras la calidad", "Docker Compose con 3 sedes, TLS, HAPI y HSB: 141 pruebas de API y el contrato del bus. Minikube con el despliegue completo: 141 pruebas de API, el guion del bus con caída de HAPI, 14 E2E de las vistas y un respaldo real que se copia fuera del clúster y se restaura; guarda las capturas de las que fallan."],
    ["Nocturno", "Semanal y a pedido", "Failover de punta a punta en Compose (32 comprobaciones) y los 12 objetivos SRE en Kubernetes; adjunta resultados_sre.json."],
    ["CD", "Etiqueta vX.Y.Z y a pedido", "Repite el CI; construye la imagen, la escanea con Trivy (falla con CRITICAL que ya tengan corrección), la publica en GHCR con SBOM y procedencia, la firma con cosign y empaqueta los manifiestos de Kubernetes con la imagen fijada por digest. No despliega en ningún clúster."],
    ["Dependabot", "Semanal", "Propone actualizar las dependencias de Python, las imágenes base y las acciones; las versiones de Python quedan fijadas en un archivo de bloqueo."],
], [1700, 2200, 4942], "Pipeline de CI/CD del proyecto.")
add(h2("Lecciones del proceso"))
add(viñetas([
    "Tomcat (HAPI FHIR) responde HTTP 400 si el nombre de host contiene guion bajo; la API parecía no encontrar al HAPI hasta usar nombres con guion.",
    "Con 22 peticiones simultáneas se agotó el pool de conexiones de la API (HTTP 500). Se añadió una cola de espera y respuesta 503 si la sede se satura.",
    "Cambiar el selector de un Service de Kubernetes no corta las conexiones de réplica ya abiertas; para simular una partición hubo que cerrarlas explícitamente.",
    "Con los pesos originales del MPI, dos personas distintas con nombre, fecha de nacimiento y sexo iguales o casi iguales (gemelos, homónimos) se unían solas, y un documento repetido por error se unía sin mirar nada más. Se corrigió: solo el documento une, los datos parecidos piden una decisión humana que se replica, y un documento con datos contradictorios se marca como conflicto.",
    "Un porcentaje de disponibilidad medido sobre unas 100 peticiones no es verificable (una petición es 1 %); se reformuló como ventana máxima de fallo.",
    "Para simular la pérdida de un disco en Minikube no basta borrar el volumen: el aprovisionador nombra la carpeta por el volumen y el nuevo reutiliza los datos viejos; hubo que borrar también la carpeta del nodo.",
    "El volcado `pg_dump` incluye las suscripciones de réplica; hay que restaurarlo con `--no-subscriptions` o la base restaurada queda atada a slots inexistentes.",
    "Con escrituras en curso, comparar sedes con una ventana de tiempo que se mueve nunca coincide; la verificación usa un corte de tiempo fijo compartido.",
    "El kernel terminó (OOMKilled) el HAPI FHIR con un límite de 720 MiB tras unos 10 minutos de uso; se subió a 880 MiB. Su validador (`$validate`) agotó entonces la memoria de metaspace; después, con el montón y el metaspace acotados del Compose (320 MB y 160 MB, límite de 700 MB), respondió a una llamada a la vez (la primera tarda unos 25 s) y varias seguidas o interrumpidas dejaron al HAPI sin responder hasta reiniciarlo. "
    "Más tarde, las métricas del propio HAPI (`/actuator/prometheus`) mostraron que con un montón de 320 MB pasaba el tiempo en recolecciones completas (698 y un 22 % de sobrecarga de memoria) y una migración a FHIR tardaba unos 34 s, cerca del límite de 45 s de la API; con 400 MB (límite de 880 MiB en Compose y de 940 MiB en Kubernetes) la sobrecarga bajó al 6 % y la suite completa de la API en Kubernetes pasó de 385 s con fallos a 77 s con las 141 pruebas.",
]))

# ====================================================================== INTERFACES
add(h1("DISEÑO DE INTERFACES E IMPLEMENTACIÓN"))
par("Las cuatro vistas son páginas HTML, CSS y JavaScript sin dependencias externas, servidas por la propia API de cada sede en `/vistas/` (y detrás del gateway "
    "en `/sede/N/vistas/`). Usan rutas relativas y construyen el DOM sin `innerHTML`, de modo que ningún dato clínico se interpreta como código. Todas muestran "
    "en la barra superior la sede que atiende y el estado de su base y de su FHIR.")
figura("vista_00_inicio.jpg", 4.6, "Página de inicio: cuatro vistas y los casos de uso que verifica cada una.",
       "Captura de la página de inicio con las tarjetas de las cuatro vistas")
add(h2("Vista del Admisionista (CU-01, CU-02, CU-03)"))
par("Busca al paciente en la copia local de las tres sedes; si ya fue atendido en otra, copia sus datos al formulario para registrarlo también en la sede local. "
    "Los desplegables salen de los catálogos de la base (la comunidad étnica se filtra por la etnia elegida, como exige la clave foránea compuesta). Después abre el "
    "encuentro y registra el triage.")
figura("vista_10_admision_paciente.jpg", 4.7, "Vista del Admisionista: datos del paciente (CU-01).")
figura("vista_11_admision_encuentro_triage.jpg", 4.7, "Vista del Admisionista: encuentro abierto y triage registrado (CU-02, CU-03).")
figura("vista_75_admision_bus.jpg", 4.7, "Vista del Admisionista: mensajes del bus de integración con su estado (entregado o rechazado) y el motivo de cada rechazo.")
add(h2("Vista del Médico (CU-04 a CU-13)"))
par("Busca por documento y muestra la historia entre sedes (CU-13) con la identidad federada (CU-11). Al abrir un encuentro propio permite registrar diagnósticos, "
    "tecnologías con su medicamento, entregas, resultados, antecedentes, factores de riesgo y egreso, y migrar a FHIR para generar el RDA (CU-10, CU-12). "
    "Si el encuentro pertenece a otra sede, la vista lo muestra como copia de solo lectura, sin formularios ni botón de migrar. "
    "Cuando hay registros que podrían ser la misma persona pero no comparten documento (por ejemplo, gemelos), la vista no los une: los muestra lado a lado con el puntaje y pide que el médico "
    "confirme «es la misma persona» o «son personas distintas» (con un motivo opcional). La decisión se replica a las tres sedes, vale la más reciente y se puede revertir.")
figura("vista_60_duplicados_mpi.png", 4.7, "Vista del Médico: dos registros con documentos distintos y datos casi idénticos quedan pendientes de revisión en lugar de unirse solos.")
figura("vista_20_medico_historia.jpg", 4.7, "Vista del Médico: paciente, historia entre sedes y encuentro migrado.")
figura("vista_21_medico_detalle.jpg", 4.7, "Vista del Médico: tecnología con medicamento y entrega, resultado, antecedente y riesgo.")
figura("vista_22_medico_replica_cartagena.jpg", 4.7, "Vista del Médico servida por Cartagena: el encuentro de Sincelejo aparece como copia de solo lectura.")
add(h2("Vista del Paciente (CU-13 y CU-12 en solo lectura)"))
par("El paciente ingresa con tipo y número de documento y su fecha de nacimiento, y ve sus atenciones de todas las sedes con un lenguaje sin tecnicismos; puede "
    "descargar su RDA. La sede verifica esos datos contra su copia local y entrega un token que solo permite consultar ese documento (otro documento da 403); los datos de ingreso son semipúblicos, así que sirve para el laboratorio y no para producción, y no hay consentimiento (la vista lo advierte; véase la viabilidad normativa).")
figura("vista_30_paciente_ingreso.jpg", 4.7, "Vista del Paciente: ingreso con documento y fecha de nacimiento, y datos personales.")
figura("vista_31_paciente_historia.jpg", 4.7, "Vista del Paciente servida por Corozal: atención hecha en Sincelejo, con su detalle y descarga del RDA.")
figura("vista_76_paciente_mis_datos.jpg", 4.7, "Vista del Paciente (paciente sintético 7000001): sus datos y sus tres atenciones, una en cada sede.")
figura("vista_77_paciente_accesos.jpg", 4.7, "Vista del Paciente: «Quién ha accedido a mi historia», con la fecha, el usuario y su rol, la acción y el resultado.")
add(h2("Ingreso y control de acceso por rol"))
par("Toda ruta clínica de la API exige sesión. El personal entra con usuario y clave (hash PBKDF2-HMAC-SHA256 de 200 000 iteraciones) y el paciente con documento y "
    "fecha de nacimiento; la sede devuelve un token firmado (JWT HS256) que vence a las 8 horas para el personal y a los 30 minutos para el paciente. La clave de firma es la misma en las tres sedes, "
    "de modo que **un token emitido por una sede vale en las otras dos** y cada sede lo verifica sola: no existe un servidor de identidad central que pueda caerse, coherente con la autonomía de las sedes. "
    "Cada vista exige su rol (admisionista, médico, reportero; el administrador de laboratorio entra a todas); un rol equivocado recibe 403 y la vista lo explica. El paciente solo puede consultar su propio documento: "
    "buscar por nombre, ver a otra persona, escribir o abrir las vistas de reportes da 403, y su historia federada se filtra a sus propios registros. "
    "Las claves de laboratorio son aleatorias por instalación (`scripts/credenciales.py`), se guardan fuera del repositorio y llegan a las sedes como un Secret de Kubernetes; no hay contraseñas por defecto. "
    "Los clientes entran por el gateway con HTTPS (TLS 1.2 y 1.3, HSTS); el puerto HTTP solo responde la sonda de salud y redirige. El certificado lo firma una CA de laboratorio creada con `scripts/certificados.py`, que en Compose corre solo en el servicio `init` (clave de la CA fuera de los pods y de los contenedores de las sedes), "
    "y el gateway fija la cabecera de IP de origen en lugar de aceptar la del cliente.")
figura("vista_50_acceso_por_rol.jpg", 4.7, "Vista del Médico con la sesión de un paciente: se rechaza por rol y se pide ingresar con un usuario que corresponda.")
par("Cada sede registra en una tabla local (`evento_auditoria`, no replicada) quién consultó o modificó datos, con su rol, la acción, el documento consultado, el resultado y la dirección de origen, incluidos los ingresos fallidos. "
    "La vista del Reportero la muestra y permite filtrar solo los intentos rechazados. Es un registro mínimo en la línea del perfil ATNA, no una implementación completa: no guarda el cuerpo de las peticiones y, "
    "detrás de un NodePort de Kubernetes, la dirección de origen suele ser la del nodo y no la del cliente.")
par("**Cadena de hash.** Cada evento guarda `hash = SHA-256(hash anterior + contenido)`, con un punto de partida distinto por sede, y la tabla es de solo anexar para la aplicación (un disparador rechaza UPDATE, DELETE y TRUNCATE). "
    "Toda escritura exitosa devuelve su sello (número de evento y hash) en la cabecera `X-Sello-Auditoria`; el verificador (`GET /api/v2/auditoria/verificar`, para reportero y médico) recorre la cadena y señala el primer evento "
    "alterado, y la vista del Reportero lo muestra junto al sello de cada fila. El paciente ve quién accedió a su historia (`/auditoria/mis-accesos`). Se probó con un guion que altera un evento con `psql` como superusuario, comprueba que el "
    "verificador lo señala, restaura, borra otro evento y comprueba el salto de secuencia. **Límite de la cadena sola:** detecta alteraciones que no recalculan los hashes; un administrador de la base que desactive el disparador y recalcule toda la cadena "
    "no se detecta con ella, y borrar los últimos eventos solo cambia la cabeza. Por eso se añadió el anclaje (siguiente párrafo). El evento se anexa después de confirmar la escritura, "
    "no en la misma transacción.")
par("**Anclaje de la cabeza en las otras sedes.** Cada sede publica la cabeza de su cadena (secuencia y hash del último evento) en las otras dos cada 10 s si cambió (`POST /api/v2/auditoria/anclas`, con una cuenta de rol `sistema_sede`); los pares la guardan en `ancla_auditoria`, una tabla de solo anexar que no se replica. "
    "Como el hash de un evento depende de todos los anteriores, el hash anclado en la secuencia N compromete el historial completo hasta N. El verificador (`/auditoria/verificar`) pregunta a los pares qué tienen anclado de la sede y lo compara con la cadena local: "
    "si cualquier evento anterior se reescribió, su hash en N no coincide («historial reescrito»); si se borraron los últimos, la cadena queda por debajo de lo anclado («cadena truncada»); y si la sede intenta anclar otro hash para una secuencia ya anclada, el par responde 409 y lo registra. "
    "Un par que no responde no cuenta como fallo, para que la caída de una sede no tumbe la verificación. El guion `prueba_auditoria.sh` ataca la cadena de las dos formas que antes pasaban desapercibidas (reescribirla entera recalculando todos los hashes y borrar sus últimos eventos): la cadena local sigue cuadrando consigo misma, el anclaje los detecta y la cadena se restaura. "
    "**Límites:** lo ocurrido después del último anclaje (unos 10 s) no está cubierto; las sedes comparten la clave de firma de los tokens de laboratorio, así que una sede comprometida podría firmar como otra; y si las dos sedes pares fueran comprometidas a la vez no habría con qué comparar. "
    "Si una sede pierde su disco, su cadena nueva empieza en 1 y los pares la señalan como truncada: es la alarma correcta, porque se perdió el historial de auditoría. Hyperledger Fabric (el bonus de la guía) no se implementó: sus imágenes no caben en el equipo de laboratorio, y el anclaje entre sedes cubre el mismo riesgo con la propia red de sedes.")
par("**AuditEvent de FHIR.** `GET /api/v2/auditoria/fhir` (reportero y médico; opcional `documento`) devuelve los eventos de la sede como un Bundle `searchset` de recursos `AuditEvent` R4: cada uno es una interacción REST (`action` C, R, U o D y `subtype` de `restful-interaction`), con el resultado (`outcome` 0, 4 u 8 según el estado HTTP), el agente (usuario, rol y dirección de origen), la sede como `source`, el paciente consultado como `entity` con referencia a `Patient/pac-<documento>` (el mismo id que usa el HAPI) y una segunda `entity` con la secuencia, el hash y el hash previo, de modo que quien lo reciba puede reverificar la cadena. "
    "La tabla `evento_auditoria` sigue siendo la fuente de verdad; el AuditEvent es una vista de salida. Un Bundle de ocho eventos reales (`fhir/ejemplos/auditevent_bundle.json`) pasó `$validate` de HAPI con 0 errores (solo la advertencia de narrativa `dom-6`, como los demás ejemplos). No se centraliza en un repositorio ATNA.")
figura("vista_51_accesos_reportero.jpg", 4.7, "Vista del Reportero: registro local de accesos con intentos rechazados (401 y 403).")
add(h2("Vista del Reportero (reporte de HC, CU-14, CU-15)"))
par("Es la vista del auditor. Genera el **reporte de historia clínica de un paciente**: lo que cada sede registró, la cobertura de los 57 campos de ese paciente con la lista de lo que falta, un aviso si alguna sede no responde "
    "(se muestra su última copia replicada) y un sello SHA-256 del contenido clínico que el propio navegador puede recalcular. Se puede imprimir o guardar como PDF con el diálogo del navegador, y se descargan el reporte en JSON y el Bundle de cada encuentro migrado. "
    "Consultar un reporte queda en la auditoría encadenada y el paciente lo ve en su vista. Además muestra la cobertura de migración a FHIR por sede, la auditoría de los 57 campos (completos, parciales y pendientes, con detalle campo por campo), el estado de "
    "las suscripciones de réplica, la integridad de la cadena de auditoría y el estado de la plataforma. Los reportes de cobertura y de los 57 campos se descargan como CSV. Los datos salen de la copia local, así que el reporte de las tres sedes funciona aunque alguna esté caída. "
    "El auditor ve datos clínicos de cualquier paciente porque la guía lo pide; el control es que cada consulta queda registrada y visible para el paciente.")
par("Otras vistas con funciones nuevas: el **Paciente** ve quién y cuándo accedió a su historia en la sede; el **Admisionista** ve la tabla de mensajes que llegaron al bus de integración con su estado y el motivo de los rechazos (solo por el gateway); "
    "el **Médico** ve el estado de la plataforma (sedes, base de datos, FHIR y verificación de la auditoría), y cada escritura muestra en la barra el último sello de auditoría. "
    "Estas pantallas se probaron cargándolas en jsdom contra el despliegue real y se vieron en el navegador integrado de la aplicación (Chromium) sobre Docker Compose, con datos sintéticos; las capturas siguientes son de esa revisión. Además el E2E de Playwright las cubre con 5 pruebas nuevas (19 en total, en Compose).")
figura("vista_70_reporte_hc_sedes.jpg", 4.7, "Vista del Reportero: Reporte de HC del paciente sintético 7000001, con lo que registró cada sede y la cobertura de sus 57 campos (30 completos).")
figura("vista_71_reporte_hc_sello.jpg", 4.7, "Vista del Reportero: sello SHA-256 del reporte, que el navegador puede recalcular, junto con el estado de la plataforma.")
figura("vista_72_reporte_sede_caida.jpg", 4.7, "Vista del Reportero con Cartagena apagada: el reporte la marca «no responde» y avisa que muestra su última copia replicada.")
figura("vista_73_tablero_estado.jpg", 4.7, "Tablero de estado de la plataforma con Cartagena «NO RESPONDE»: sedes, base de datos, FHIR, integridad de la auditoría y resumen del bus.")
figura("vista_74_integridad_auditoria.jpg", 4.7, "Vista del Reportero: verificación de la cadena de auditoría y accesos recientes con el sello de cada evento.")
par("**Tablero de Grafana (opcional, bonus).** Con `docker compose --profile observabilidad up -d` se añaden Prometheus y Grafana; el tablero «Historia clínica distribuida · plataforma» viene provisionado desde `infra/observabilidad/grafana/` y se abre en `http://localhost:3000` (solo desde el propio equipo, de solo lectura y sin contraseña por defecto). "
    "Muestra por sede la base de datos, el HAPI y la cadena de auditoría; la edad del último mensaje de réplica y su retraso; los mensajes del bus por estado, el porcentaje de fallidos, la latencia media y su percentil 95; las peticiones por segundo y la latencia de las APIs; el gateway y la memoria del HAPI. "
    "Prometheus recoge las tres APIs, el bus, el gateway y el HAPI (seis objetivos, todos arriba en la prueba). La captura se tomó justo después de la demostración, con Cartagena apagada y encendida durante ella.")
figura("vista_80_grafana_plataforma.jpg", 4.9, "Tablero de Grafana: estado de las sedes, bus de integración (HSB), APIs, gateway y HAPI, con los datos de la demostración.")
figura("vista_40_reportero_cobertura.jpg", 4.7, "Vista del Reportero: cobertura de migración por sede (CU-14).")
figura("vista_41_reportero_auditoria.jpg", 4.7, "Vista del Reportero: auditoría de los 57 campos y estado de la réplica (CU-15).")
n57 = _fig[0] + 1
par("**Demostración de trazabilidad (57 de 57).** Con los datos de prueba acumulados ninguna sede tenía los 57 campos completos, porque los flujos no recorrían todos los casos "
    "(por ejemplo, nunca se registró una complicación ni una causa de muerte). Para demostrar que el modelo los captura todos se añadió un filtro por lote a la auditoría "
    "(`lote`, prefijo del documento) y un escenario (`escenario_57_campos.py`) que registra, por la API de Sincelejo, un paciente y un encuentro **sintéticos** con un dato en "
    "cada campo. La auditoría de ese lote da 57 completos en Sincelejo y, leyendo su réplica, también en Cartagena y en Corozal (Figura " + str(n57) + "). Los valores no tienen coherencia "
    "clínica (el encuentro tiene a la vez causa básica de muerte, remisión, incapacidad y licencia de maternidad): sirven solo para comprobar la trazabilidad.")
figura("vista_42_reportero_57_completos.jpg", 4.7, "Vista del Reportero servida por Corozal: auditoría del lote de demostración sobre Sincelejo, 57 de 57 campos completos.")
add(h2("Lineamientos de experiencia de usuario y accesibilidad"))
add(viñetas([
    "Cada etiqueta está asociada a su control (`for` e `id`): 28 etiquetas y 0 controles sin etiqueta en la vista del Admisionista.",
    "Los errores de la API se traducen a mensajes en lenguaje claro (por ejemplo, «este registro pertenece a la sede X; aquí es solo lectura»).",
    "Estados con color y texto (no solo color); foco visible en los controles; diseño que se adapta a anchos pequeños; idioma `es` declarado.",
    "Sin recursos externos: la vista sigue cargando si la sede pierde Internet.",
    "Las pruebas E2E comprueban en las cinco páginas que todo control visible tiene nombre accesible, que hay un solo encabezado principal, que el idioma es `es` y que no hay desbordamiento horizontal a 375 px.",
    "**No se auditó** la accesibilidad con una herramienta (Lighthouse, axe) ni con un lector de pantalla; queda como trabajo pendiente.",
]))
add(h2("Verificación de los casos de uso por vista"))
tabla_con_pie(["Vista", "Casos de uso", "Evidencia"], [
    ["Admisionista", "CU-01, CU-02, CU-03", "Flujo completo en navegador (paciente, encuentro y triage creados); validación de campos obligatorios; pruebas de integración de la API."],
    ["Médico", "CU-04 a CU-13", "Flujo en navegador: diagnóstico, tecnología con medicamento, entrega, resultado, antecedente, riesgo, egreso, migración a FHIR (Bundle 6 recursos, HAPI confirmado) y consulta del RDA; copia de solo lectura desde Cartagena."],
    ["Paciente", "CU-13, CU-12", "Ingreso con fecha incorrecta rechazado; con la correcta, historia atendida en Sincelejo mostrada desde Corozal y RDA descargable."],
    ["Reportero", "CU-14, CU-15", "Cobertura de las tres sedes, 57 cuadros de auditoría y suscripciones activas vistos desde Corozal."],
    ["Las cuatro", "CU-01 a CU-15", "Prueba automática `test_flujo_de_las_cuatro_vistas_entre_sedes` y pruebas de que las vistas se sirven y no usan recursos externos."],
], [1500, 1900, 5442], "Evidencia de verificación de los casos de uso por vista. El flujo de cada vista se verificó además con las pruebas E2E automáticas descritas en los resultados.")

# ====================================================================== PROTOTIPO
add(h1("PROTOTIPO FINAL"))
par("**Código fuente.** https://github.com/sebastianmarinc19-sudo/historia-clinica-distribuida (público; rama `reingenieria-3-sedes`, etiqueta `v1.0`). Las instrucciones para clonarlo y ejecutarlo están en el Anexo A.")
par("**Entorno.** Un portátil con 4 vCPU y 5,7 GiB de RAM, Ubuntu 24.04, Docker 29 y un clúster Minikube de un nodo (2,8 GB). Tres namespaces de sede, un namespace de "
    "gateway y uno de observabilidad. Cada sede tiene un StatefulSet de PostgreSQL con disco persistente, un Deployment de API con dos réplicas, un Job que crea las "
    "suscripciones y, solo en Sincelejo, un HAPI FHIR (los otros dos no caben en la memoria disponible; esas sedes degradan a «FHIR no disponible» y siguen registrando).")
par("**Código.** Unas 1 500 líneas de Python en la API, 1 100 de HTML, CSS y JavaScript en las vistas, 830 de SQL y scripts de base de datos, 1 100 de scripts de despliegue y "
    "pruebas, y 590 de manifiestos de Kubernetes.")
tabla_con_pie(["Criterio de aceptación", "Estado", "Evidencia"], [
    ["RF1 · Ingerir las 3 sedes en al menos 2 formatos", "Cumple", "HL7 v2 (ADT^A01 y ORU^R01) y CSV legado de la sede 3 por el bus; los cuatro mensajes de ejemplo del docente dan el resultado esperado (Tabla 14)."],
    ["RF2 · Normalizar a FHIR R4 (Patient, Encounter, Observation, Condition con CIE-10)", "Cumple", "Bundle `transaction` con `PUT` e ids deterministas; `$validate` de HAPI: 0 errores en 5 Bundle (quedan advertencias de narrativa y `performer`)."],
    ["RF3 · Enrutamiento por sede, validación, reintentos e idempotencia", "Cumple", "Ruteo por sede, rechazo con motivos, reintentos exponenciales, mensajes muertos e idempotencia persistida; 68 pruebas del bus (Tabla 14)."],
    ["RF4 · Datos distribuidos y consulta unificada de un paciente en las 3 sedes", "Cumple", "Un PostgreSQL por sede con réplica lógica en malla; el paciente de demostración 7000001 tiene su encuentro en cada sede y se consulta desde cualquiera; ACID demostrado (Tabla 15)."],
    ["RF5 · Token, roles y auditoría encadenada por hash", "Cumple (con límites)", "JWT y roles por vista; cadena SHA-256 por sede con verificador y prueba que detecta una fila alterada y una borrada. Sin Hyperledger Fabric (era opcional, no cabe en el equipo de laboratorio), con anclaje de la cabeza en las otras sedes (detecta la reescritura completa y el truncamiento) y `AuditEvent` de FHIR; sin sello de tiempo externo ni repositorio ATNA central."],
    ["RF6 · Cuatro vistas por rol (Paciente, Admisionista, Médico y Reporte de HC con tablero de estado)", "Cumple", "Las cuatro vistas respetan los permisos por rol; el Reporte de HC trae un sello SHA-256 y el tablero muestra el estado de las sedes, la integridad de la auditoría y el resumen del bus."],
    ["RNF · Un solo comando, sede caída y `/health` y `/metrics`", "Cumple", "`docker compose up -d --build` levanta todo y la demostración completa pasó sin intervención sobre volúmenes vacíos (113 s en total, con las imágenes ya construidas); apagar una sede no detiene la vista y la marca «no responde» (demo, paso 6, en Compose y en Kubernetes); `/health` y `/metrics` en la API, el bus y el gateway (en Kubernetes con un exportador de nginx) y `/actuator/prometheus` en el HAPI; en Kubernetes Prometheus los raspa."],
    ["Esquema de 57 campos ejecutado en PostgreSQL real", "Cumple", "45 tablas del modelo más mpi_decision (propia); 29 pruebas de restricciones."],
    ["Una sede caída o aislada no detiene a las demás", "Cumple", "32 comprobaciones de failover; experimentos E3 y E4."],
    ["La sede caída o aislada sigue funcionando", "Cumple", "Escribe en aislamiento; se pone al día al volver."],
    ["Casos de uso CU-01 a CU-15 disponibles", "Cumple", "API y cuatro vistas; 23 pruebas de integración."],
    ["Trazabilidad de los 57 campos demostrada", "Cumple (caso sintético)", "Un paciente y un encuentro sintéticos dan 57 de 57 campos completos en Sincelejo y en las dos réplicas (Figura " + str(n57) + ")."],
    ["RDA como Bundle FHIR document en HAPI", "Cumple (una sede)", "Bundle de 6 a 8 recursos; HAPI confirma el tipo `document`."],
    ["Base de datos distribuida", "Cumple", "Replicación lógica en malla; datos completos en las 3 sedes."],
    ["Despliegue en Kubernetes", "Cumple (1 nodo)", "Kustomize; 17 + 6 pruebas de integración dentro del clúster."],
    ["Recuperar una sede que perdió su disco", "Cumple (1 nodo)", f"Reconstrucción desde sus pares en unos {fmt(rc['segundos_desde_el_desastre'], 0)} s, sin perder lo ya replicado; los respaldos diarios cifrados se restauran en un PostgreSQL desechable con conteos idénticos al manifiesto."],
    ["HAPI FHIR en las tres sedes", "Parcial", "Definido en los manifiestos; activo solo en Sincelejo por memoria."],
    ["Seguridad (autenticación, cifrado, auditoría)", "Parcial", "Autenticación y roles por vista, acceso del paciente limitado a lo suyo, auditoría encadenada por hash y TLS 1.2/1.3 en el gateway; sin cifrado en reposo, consentimiento ni ATNA completo (véase viabilidad normativa)."],
    ["Escalado automático y alta disponibilidad dentro de la sede", "No cumple", "Sin HPA ni Patroni; API fija de 2 réplicas, un Postgres por sede."],
], [3500, 1500, 3842], "Criterios de aceptación del prototipo.")

# ====================================================================== RESULTADOS
add(h1("RESULTADOS Y DISCUSIÓN"))
add(h2("Pruebas automáticas"))
tabla_con_pie(["Conjunto", "Cantidad", "Qué verifica"], [
    ["Restricciones SQL", "29", "Unicidad, claves foráneas, CHECK, trigger de medicamento, identidades del MPI y la tabla de decisiones."],
    ["Unitarias de la API", "45", "Ids y transacción PUT del RDA, secretos por archivo, cadena de hash de la auditoría (alterar, borrar, insertar y reordenar eventos), política del MPI (gemelos, homónimos, documento repetido, decisiones, determinismo y orden), RDA FHIR, mapa de 57 campos y filtro por lote; hash de claves, firma, vencimiento y manipulación de tokens, límite de intentos y reinicio del pool de conexiones sin bloqueo."],
    ["Integración (Kubernetes)", "23", "CU-01 a CU-15 entre sedes, regla de sede dueña, vistas, catálogos, gateway y 57 de 57 campos."],
    ["Autenticación y roles (Kubernetes)", "12", "401 sin sesión en las 3 sedes, matriz de roles (403), token válido entre sedes, tokens manipulados o vencidos, alcance del paciente, límite de intentos (429) y registro de accesos."],
    ["TLS del gateway (Kubernetes y Compose)", "8", "Certificado de la CA de laboratorio y rechazo sin ella, HTTP que solo redirige, HSTS, TLS 1.2 y 1.3 aceptados y 1.0/1.1 rechazados, ingreso por HTTPS y IP de origen no falsificable."],
    ["E2E de las vistas (Compose; las 14 primeras también en Kubernetes)", "19", "Chromium real por el gateway HTTPS: puerta de ingreso y rol equivocado, flujo clínico CU-01 a CU-12 en las vistas del Admisionista y del Médico, revisión de posibles duplicados, historia del Paciente, copia de solo lectura en otra sede, reportes y registro de accesos, el Reporte de HC con su sello recalculado en el navegador y la verificación de la cadena de auditoría, los accesos que ve el Paciente, la tabla del bus del Admisionista, el estado de la plataforma del Médico, la portada, nombres accesibles de los controles y ausencia de desbordamiento horizontal a 375 px."],
    ["MPI entre sedes (Kubernetes y Compose)", "9", "Gemelos que no se unen solos, decisión replicada a las 3 sedes con el mismo id_mpi, reversión por la decisión más reciente, conflicto de documento, recálculo desde cero y permisos."],
    ["Retención de respaldos (shell)", "9", "Conserva los 14 más recientes y el último de cada mes, borra el resto con su suma, no toca archivos ajenos y es idempotente."],
    ["Migración a FHIR con PUT (Compose; necesita HAPI)", "4", "Recursos propios con ids deterministas (`pac-<documento>`, `enc-…`), migrar dos veces el mismo encuentro no crea otro Bundle ni duplica recursos en HAPI y el Patient queda con el id que usa el bus."],
    ["ACID (Kubernetes y Compose)", "6", "Prescripción y egreso atómicos con error a la mitad (nada queda ni en las réplicas), la réplica nunca muestra el egreso sin el cierre del encuentro y ocho peticiones simultáneas dejan un solo diagnóstico de ingreso. Además `prueba_acid.sh` (SQL real, SIGKILL de la base)."],
    ["Reporte de HC y estado (Kubernetes y Compose)", "8", "Reporte por sede con cobertura de los 57 campos del paciente y faltantes, mismo sello desde otra sede y distinto si cambian los datos, roles (solo el reportero), el reporte queda en el registro y lo ve el paciente, bundle para el reportero y estado de la plataforma para médico y reportero. Además `prueba_vistas.sh` carga las vistas en jsdom contra el gateway."],
    ["Auditoría encadenada, anclaje y AuditEvent (Compose)", "15", "Sello en cada escritura, mismo hash en el registro, cadena verificable en las 3 sedes, cadenas independientes, 16 escrituras concurrentes sin secuencias repetidas, roles del verificador y acceso del paciente a su registro, anclaje entre sedes (recepción, roles, conflicto 409 y que anclar no agrega eventos en bucle) y el Bundle de `AuditEvent`. Además, el guion `prueba_auditoria.sh` altera y borra eventos en la base, reescribe toda la cadena y borra su cabeza, y comprueba que se detectan (los dos últimos, por el anclaje)."],
    ["Rol del bus en la API (Kubernetes y Compose)", "11", "Mínimo privilegio del rol `hsb`, alta idempotente de encuentros, diagnósticos, triage y observaciones, y actualización parcial del paciente."],
    ["HSB (PostgreSQL real, destinos simulados)", "68", "Lectura de HL7 v2 y CSV, validación y motivos de rechazo, Bundle FHIR con ids deterministas, cola (reintentos, también ante un 409 de versión del HAPI, muertos, reencolado, recuperación de mensajes a medias, idempotencia) y la API del bus con roles."],
    ["Failover (Compose)", "32", "Caída, recuperación y aislamiento de Sincelejo de punta a punta."],
    ["Objetivos SRE (Kubernetes)", str(NOBJ), "Pod, gateway, base de datos, partición, réplica, carga y pérdida de disco de una sede."],
], [3000, 1300, 4542], "Pruebas ejecutadas y su alcance. Las 141 de la API (45 + 23 + 12 + 9 + 8 + 11 + 15 + 8 + 6 + 4) pasaron en Docker Compose; en el clúster de Kubernetes pasaron las 132 anteriores y, por separado después de los últimos cambios, las 60 unitarias y de auditoría (con las 9 nuevas de anclaje y AuditEvent), y el failover de 32 comprobaciones se repitió con la autenticación activa.")
add(h2("Experimentos de fallo y de carga"))
a, g, rp, pa, la, ca, rc = R["api"], R["gateway"], R["rpo"], R["particion"], R["latencia_replicacion"], R["carga"], R["reconstruccion"]
tabla_con_pie(["Experimento", "Resultado medido", "Objetivo", "Estado"], [
    ["Muere un pod de la API (acceso directo)", f"{a['acceso_directo']['fallidas']} de {a['acceso_directo']['peticiones']} peticiones perdidas; ventana de {fmt(a['acceso_directo']['segundos_con_fallos'])} s; reemplazo listo en {fmt(a['segundos_hasta_2_replicas_listas'])} s", "Ventana ≤ 2 s", "Cumple"],
    ["Muere un pod de la API (vía gateway)", f"{a['via_gateway']['fallidas']} de {a['via_gateway']['peticiones']} peticiones perdidas", "0 pérdidas", "Cumple"],
    ["Muere un pod del gateway", f"{g['fallidas']} de {g['peticiones']} peticiones; ventana de {fmt(g['segundos_con_fallos'])} s", "Ventana ≤ 2 s", "Cumple"],
    ["Cae la base de Sincelejo escribiendo: RTO", f"{fmt(rp['rto_base_sede_s'])} s", "≤ 60 s", "Cumple"],
    ["Lecturas por gateway con la base caída", f"{rp['gateway']['fallidas']} fallidas de {rp['gateway']['peticiones']}", "≥ 99,9 %", "Cumple"],
    ["RPO al reiniciar con su disco", f"{rp['perdidas_tras_reiniciar']} escrituras perdidas de {rp['escrituras_confirmadas']} confirmadas; {rp['escrituras_rechazadas_durante_la_caida']} rechazadas durante la caída", "0", "Cumple"],
    ["RPO si el disco se perdiera (a 6 escrituras/s)", f"{rp['expuestas_sin_replicar_en_cartagena']} escrituras sin replicar de {rp['confirmadas_antes_de_caer']} confirmadas", "Informativo", "—"],
    ["Cartagena pierde su disco y se reconstruye desde sus pares (con escrituras en curso en Sincelejo)",
     f"{fmt(rc['segundos_desde_el_desastre'])} s desde el desastre ({fmt(rc['segundos_reconstruccion'])} s de reconstrucción); {rc['escrituras_confirmadas_en_sincelejo_durante']} escrituras confirmadas durante el proceso, 0 perdidas; mismos datos que sus pares", "≤ 180 s y sin pérdida", "Cumple"],
    ["Partición de Sincelejo", f"Sin fugas; {pa['escrituras_sincelejo']}/8 y {pa['escrituras_cartagena']}/8 escrituras confirmadas; convergencia en {fmt(pa['segundos_hasta_convergencia'], 2)} s", "Converge", "Cumple"],
    ["Retraso de réplica", f"p50 {fmt(la['p50_ms'])} ms; p95 {fmt(la['p95_ms'])} ms; máx {fmt(la['max_ms'])} ms ({la['muestras']} muestras)", "p95 ≤ 2 s", "Cumple"],
    ["Carga de 25 s (16 lectores y 6 escritores)", f"{miles(ca['transacciones_por_minuto'])} tx/min; lectura p95 {fmt(ca['lectura_p95_ms'], 0)} ms; {ca['lecturas_errores'] + ca['escrituras_errores']} errores", "Sin errores", "Cumple"],
], [2700, 3700, 1342, 1100], "Resultados de los experimentos SRE en Minikube (un nodo).")
add(h2("Comparación entre la versión de partida y la propuesta"))
tabla_con_pie(["Aspecto", "Versión de partida", "Propuesta"], [
    ["Criterio de distribución", "Rango numérico del documento de identidad", "Sede real; cada sede dueña de sus filas"],
    ["Cae un nodo", "Se pierden aplicación, FHIR y pacientes del rango", "Las demás sedes siguen sirviendo su historia y su RDA"],
    ["La sede caída o aislada", "No puede operar", "Opera con lo suyo y se sincroniza al volver"],
    ["Identidad federada", "Base única en el primer nodo", "Calculada en cada sede, determinista"],
    ["Servidor FHIR", "Uno, con su base en el primer nodo", "Uno por sede con su propia base"],
    ["Modelo de datos", "Tabla única con nombre completo", "45 tablas en 3FN; 57 campos trazables"],
], [2300, 3200, 3342], "Versión de partida frente a la propuesta.")
add(h2("Discusión"))
par("Los resultados muestran que la combinación de réplica lógica y sede dueña cumple el objetivo central: la caída de una sede se absorbe sin pérdida de las escrituras "
    "confirmadas y las demás siguen sirviendo su historia desde su copia. El costo es la consistencia eventual: los registros de una sede caída son de solo lectura en "
    "las otras hasta que vuelva, algo que en la práctica clínica es aceptable porque una atención ocurre en una sola sede, y que se hace explícito en la interfaz.")
par("La medición del RPO exige cautela. Con 6 escrituras por segundo no quedó ninguna sin replicar, pero bajo carga el WAL pendiente llegó a unos "
    f"{fmt(ca['max_wal_pendiente_bytes'] / 1024, 0)} KB; si la sede perdiera su disco en ese momento habría pérdida. Lo que se demostró es **RPO = 0 si la sede reinicia con su "
    "disco**. Si la sede pierde el disco, las otras conservan una copia de sus filas: la sede se reconstruyó desde sus pares en "
    f"{fmt(rc['segundos_desde_el_desastre'], 0)} s, con escrituras en curso en otra sede y sin pérdida; solo se pierde lo que aún no se había replicado al caer. "
    "Contra los errores lógicos (un borrado malo se replica a las tres sedes) cada sede tiene un respaldo programado: un CronJob diario (02:00 UTC) vuelca las bases y los roles, comprueba que el volcado se pueda leer y lo cifra con una clave pública, de modo que el clúster no guarda la clave privada; aplica una retención (los 14 más recientes y el último de cada uno de los 6 meses anteriores) y puede subir una copia a un almacenamiento externo con rclone. "
    "Se probó el ciclo completo: respaldo, copia fuera del clúster, descifrado y restauración en un PostgreSQL desechable con conteos idénticos a los del manifiesto; una clave equivocada o un archivo manipulado fallan al descifrar, y sin la clave pública el respaldo falla y el Job queda en rojo. "
    "Límites: el RPO frente a un error lógico es de hasta unas 24 horas; el volumen está en el mismo nodo, así que solo la copia externa protege de perder el nodo, y esa se probó contra un servidor S3 local y no contra un proveedor real; no hay recuperación a un punto en el tiempo (sin archivado de WAL); restaurar dentro de la sede es un procedimiento manual que no se ensayó en el clúster, y la custodia de la clave privada es responsabilidad de quien opera.")
par(f"Frente a la meta de la plantilla (10 000 transacciones FHIR por minuto), el prototipo alcanzó unas {miles(R['carga']['transacciones_por_minuto'])} mixtas por minuto; no es comparable porque el clúster tiene un "
    "solo nodo, cada pod usa un proceso, y las transacciones medidas son llamadas a la API v2 y no escrituras FHIR.")
add(h2("Amenazas a la validez"))
add(viñetas([
    "Un solo portátil y un solo nodo de Kubernetes: no hay fallas de red reales entre máquinas; la partición se simuló (Service sin selector, suscripciones deshabilitadas y conexiones cerradas).",
    "Datos sintéticos y catálogos de muestra no confirmados contra el Anexo Técnico de la Resolución 866.",
    "Carga baja y breve (25 s); los tiempos de réplica son sin saturación.",
    "Tras desplegar en Kubernetes, la primera corrida de las pruebas de API dio 3 fallos de 132 (migración a FHIR, tiempo de espera del HAPI mientras se calienta); repetidas con el HAPI caliente pasaron las 132, y el tiempo de espera de los primeros usos del HAPI depende de la memoria del equipo.",
    "El HAPI FHIR solo se ejercitó en Sincelejo; en las otras sedes está definido pero no se activó por memoria.",
    "Los objetivos SLO los propuso el equipo y tres de ellos (los de pod, gateway y lectura durante la reconstrucción) se reformularon tras ver los datos, de porcentaje a ventana de fallo (véase Lecciones del proceso).",
    "Las pruebas E2E corren solo en Chromium, con el certificado de laboratorio sin verificar en el navegador y sobre un único nodo; no se probó Firefox, Safari ni un lector de pantalla, y no cubren la migración a FHIR cuando HAPI no está disponible (se omite).",
]))

# ====================================================================== CONCLUSIONES
# ====================================================================== HSB
add(h1("BUS DE INTEGRACIÓN DE SALUD (HSB)"))
par("Los sistemas de las sedes que no hablan FHIR (mensajes HL7 v2 y archivos CSV heredados) entran por un **Health Service Bus** propio (`hsb/`, FastAPI) con su "
    "propia base PostgreSQL. El bus no escribe en las bases de las sedes: entrega a la **API de la sede** con un usuario de servicio de mínimo privilegio, de modo que se "
    "respetan la regla de sede dueña, la autenticación y el registro de accesos ya probados. Cada mensaje queda guardado con su estado y su bitácora de eventos, así que "
    "reiniciar el bus no pierde nada.")
add(h2("Decisión: servicio propio frente a Mirth Connect, Camel u OpenHIM"))
par("Se evaluaron los tres. Todos resuelven el ruteo y la transformación, pero cada uno añade una JVM o un servidor adicional y su propia administración, y el entorno de pruebas "
    "tiene 5,7 GiB de RAM compartidos con tres PostgreSQL y HAPI. Además, la parte que la guía pide demostrar (idempotencia persistida, máquina de estados, reintentos con espera "
    "exponencial, mensajes muertos y reencolado) se programa en unos cientos de líneas sobre PostgreSQL, y así cada integrante puede explicarla y modificarla en vivo. "
    "El costo es real: no hay editor gráfico de canales ni conectores listos, y los formatos soportados son solo los dos del contrato (ADT^A01, ORU^R01 y CSV con separador «;»).")
figura("07_secuencia_hsb.png", 4.5, "Secuencia de un mensaje a través del HSB hasta FHIR, con los caminos de duplicado, rechazo y reintento.",
       "Diagrama de secuencia: sistema de sede, gateway, HSB, base del bus, normalizador, trabajador de entrega, HAPI FHIR y API de la sede")
par("**Idempotencia.** La clave es MSH-10 en HL7 y el sha256 de la fila más la sede en CSV, con restricción `UNIQUE` en la base. Reenviar un mensaje responde `duplicado` y aumenta un "
    "contador que se publica como métrica. La entrega al HAPI usa `PUT` con identificadores deterministas (`pac-<documento>`, `enc-<sede>-<visita>`, `obs-<mensaje>-<n>`), de modo que "
    "repetir un intento no crea recursos nuevos; en la API de la sede los identificadores los fija el cliente, y el diagnóstico, el triage y la observación repetidos responden «existente».")
figura("07_estados_mensaje.png", 4.8, "Estados de un mensaje del HSB.", "Diagrama de estados: recibido, validado, transformado, entregado, rechazado, reintentando y muerto")
par("**Reintentos.** Un fallo transitorio (conexión, tiempo de espera, 5xx, 429, o un 401/403 por configuración) pone el mensaje en `reintentando` con espera `base·2^(n-1)` y tope; "
    "al agotar los intentos pasa a `muerto` y un administrador lo reencola. Un rechazo de negocio (409 o 422) pasa a `rechazado` y no se reintenta. Varias réplicas del bus comparten la "
    "cola con `FOR UPDATE SKIP LOCKED`, y un mensaje que quedó a medias por un reinicio se recupera pasado un plazo. Cada paso cumplido se guarda (`hapi_ok`, `nodo_ok`) para no repetirlo.")
figura("04c_clases_hsb.png", 5.2, "Diagrama de clases (3/3): bus de integración.", "Clases MensajeBus, EventoMensaje, RefTerminologia, MensajeCanonico, Normalizador, ConstructorFhir y Destino")
add(h2("Mapeo de HL7 v2 y CSV a la base y a FHIR"))
tabla_con_pie(["Origen HL7 v2", "Origen CSV", "Campo en la API de la sede", "Recurso FHIR y campo"], [
    ["MSH-10", "sha256(fila + sede)", "clave de idempotencia del bus", "base del id de `Observation` (`obs-<clave>-n`)"],
    ["MSH-4", "parámetro `sede`", "sede dueña (1 a 3)", "parte del id de `Encounter` (`enc-<sede>-<visita>`)"],
    ["MSH-9", "—", "tipo (ADT^A01 u ORU^R01)", "decide si el mensaje lleva observaciones"],
    ["PID-3.1", "`documento`", "`numero_documento`", "`Patient.identifier.value` e id `pac-<documento>`"],
    ["(por defecto CC)", "(por defecto CC)", "`cod_tipo_documento`", "`Patient.identifier.system`"],
    ["PID-5.2 y 5.3", "`nombre` (primeras palabras)", "`primer_nombre`, `segundo_nombre`", "`Patient.name.given`"],
    ["PID-5.1", "`nombre` (últimas palabras)", "`primer_apellido`, `segundo_apellido`", "`Patient.name.family`"],
    ["PID-7", "`nacimiento`", "`fecha_hora_nacimiento`", "`Patient.birthDate`"],
    ["PID-8", "`sexo`", "`cod_sexo` (M, F u O)", "`Patient.gender`"],
    ["PV1-7", "`profesional`", "profesional de la sede", "`Practitioner.identifier` y `Encounter.participant`"],
    ["PV1-19", "(un encuentro por fila)", "`id_encuentro` determinista", "`Encounter.id`"],
    ["PV1-2", "—", "clase de atención (E, O o I)", "`Encounter.class`"],
    ["PV1-44 o MSH-7", "`fecha`", "`fecha_hora_inicio`", "`Encounter.period.start`"],
    ["DG1-3 (CIE-10)", "`dx_local` → `ref_terminologia`", "`cod_cie10`, `fecha_diagnostico`", "`Condition.code` (sistema CIE-10)"],
    ["DG1-7", "—", "`cod_tipo_diagnostico`", "`Condition.clinicalStatus`"],
    ["—", "`triage`", "`cod_triage`", "(la API lo guarda; el Bundle no lo incluye)"],
    ["OBX-3 (LOINC)", "—", "`cod_loinc`", "`Observation.code`"],
    ["OBX-5 y OBX-6", "—", "`valor_numerico` y `cod_unidad`; o `valor_texto`", "`Observation.valueQuantity` (UCUM) o `valueString`"],
    ["OBX-14 o OBR-7", "—", "`fecha_hora_medicion`", "`Observation.effectiveDateTime`"],
], [1500, 1900, 2800, 2642], "Mapeo de los formatos de entrada a la API de la sede y a los recursos FHIR del Bundle `transaction` que se envía al HAPI.")
par("**Terminología.** El diagnóstico del CSV legado es texto local; la tabla `ref_terminologia` (siete equivalencias del archivo del contrato) lo traduce a CIE-10 y se expone como `ConceptMap` en "
    "`/hsb/terminologia/conceptmap`. En HL7 el diagnóstico debe llegar ya como CIE-10; un código local sin equivalencia se **rechaza con el motivo**, no se adivina. "
    "Los LOINC y las unidades se validan contra los catálogos de la API.")
add(h2("Resultados del HSB"))
tabla_con_pie(["Mensaje del contrato", "Resultado esperado", "Resultado observado"], [
    ["01 · ADT^A01, sede 2", "entregado: Patient 1007, Encounter y Condition J45.9", "Entregado; el paciente 1007 existe una vez en la sede 2 con J45.9 y el HAPI tiene los tres recursos por separado."],
    ["02 · ORU^R01, sede 1", "entregado: Observation 718-7 = 13,8 g/dL", "Entregado; observación de 13,8 g/dL en la sede 1."],
    ["03 · ADT inválido", "rechazado con tres motivos", "Rechazado con los tres motivos; no se reintenta ni se escribe nada."],
    ["04 · CSV de la sede 3", "3 entregadas y 2 rechazadas", "3 entregadas (1008 a 1010) y 2 rechazadas con su motivo; los rechazados no existen en la sede."],
    ["Reenvío de 01", "duplicado", "Responde `duplicado`; no se crea otro paciente ni otro encuentro."],
    ["HAPI caído durante el envío", "reintentando y luego entregado, sin duplicar", "Se cortó el servicio del HAPI en Kubernetes: reintentando con espera creciente; al volver, entregado con una sola observación nueva."],
    ["HAPI caído más allá del máximo", "muerto", "Con 3 intentos pasa a muerto; tras recuperar el HAPI, el administrador lo reencola y queda entregado."],
], [2200, 2900, 3742], "Resultados del HSB frente a los mensajes de ejemplo del contrato del curso (`ejemplos/`, sin modificar).")
par("**Métricas del bus (Docker Compose, un solo HAPI, 4 hilos, `scripts/carga_bus.py`).** Se enviaron 60 mensajes ADT sintéticos (50 válidos y 10 con documento no numérico) y luego 10 reenvíos. "
    "**Mensajes por minuto:** la ingesta fue de unos 61 por minuto (60 mensajes en 59 s, porque cada envío intenta entregar al HAPI antes de responder) y la entrega de extremo a extremo de unos 49 por minuto (50 entregados en 61,5 s). "
    "**Latencia de entrega** (de la recepción a «entregado»): mediana 1,6 s, percentil 95 de 52,8 s, máximo 59,6 s y media 13,7 s; 15 de los 50 entregados (30 %) necesitaron al menos un reintento por tiempo de espera del HAPI con cuatro envíos simultáneos, y todos terminaron entregados, sin ninguno muerto. "
    "**Fallidos:** 16,7 % (10 de 60), todos rechazados a propósito por documento inválido. **Duplicados:** los 10 reenvíos respondieron «duplicado» y el total se mantuvo en 60. "
    "**Cobertura:** el Reporte de HC del paciente de demostración muestra 30 de los 57 campos completos en cada una de las tres sedes (el caso de 57 de 57 está en la Figura " + str(n57) + "). "
    "Con solo los cinco mensajes del contrato sobre un HAPI recién arrancado el bus midió 8 mensajes, 5 entregados, 3 rechazados (37,5 %, los esperados) y una latencia media de 31,6 s: el arranque en frío del HAPI domina el tiempo, no el bus. "
    "Son mediciones de un portátil de 4 vCPU y no una capacidad del diseño.")
par("El bus se probó con 68 pruebas automáticas contra un PostgreSQL real (HL7 y CSV, Bundle FHIR, cola y API, con los destinos simulados), un guion en vivo en Kubernetes (dos réplicas del bus) y un escenario en Docker Compose "
    "con la sede 3 caída. Para esto la API de la sede ganó los roles `hsb` y `sistema_sede` y se hizo idempotente en el alta de encuentros, diagnósticos, triage y observaciones (11 pruebas nuevas). "
    "Métricas en `/metrics`: mensajes por estado, porcentaje de fallidos, duplicados, mensajes del último minuto y latencia de entrega.")
par("**Validación FHIR.** Los tres Bundle `transaction` del bus (uno por mensaje de ejemplo) y un RDA sintético como `document` y como `transaction` de recursos propios, generados por el mismo código del sistema (`fhir/ejemplos/`), se pasaron por `Bundle/$validate` de HAPI (`fhir/validar.sh`): **0 errores**. "
    "La primera ejecución encontró un error real que los demás controles no habían visto: «si una fecha tiene hora, debe tener zona horaria» (`Encounter.period.start` y otras fechas con hora, porque los sistemas legados y las columnas `TIMESTAMP` no guardan zona); "
    "se corrigió añadiendo UTC−05:00 (Colombia, sin horario de verano) en el bus y en el generador del RDA, con una prueba por cada uno. El validador también agotó el metaspace del HAPI (160 MB) tras el primer uso; con 256 MB y un límite de 820 MB validó los cinco Bundle incluso después de las migraciones. Al migrar un encuentro la API sube ahora sus recursos propios con `PUT` e ids deterministas y el RDA con `PUT Bundle/rda-<encuentro>`, así que migrar dos veces no duplica. Quedan advertencias (los recursos no llevan narrativa y las observaciones no llevan `performer`) que no se atendieron.")
par("**Límites.** En el laboratorio el bus entrega al HAPI de Sincelejo para las tres sedes (solo uno cabe en memoria). Con la memoria justa el HAPI tardó minutos en arrancar en frío y las primeras transacciones daban "
    "tiempo de espera; eso se absorbió con reintentos, pero indica que el tiempo de entrega medido depende del equipo. Los códigos locales de DG1 no se mapean a propósito. Los cinco Bundle de ejemplo pasan `$validate` sin errores (véase la validación FHIR). "
    "La auditoría de cada mensaje es su bitácora de eventos en el bus, sin encadenar por hash. El bus reenvía el token de servicio en la red interna sin cifrar.")

add(h2("Evidencia de ACID"))
par("Cada sede es un PostgreSQL con transacciones y la réplica lógica conserva sus límites. Se demostró con SQL real y con la API, mostrando el estado antes, el error a la mitad y el estado después (Tabla 15). "
    "`prueba_acid.sh` crea un paciente y dos encuentros en una transacción cuyo tercer `INSERT` viola un CHECK: no queda nada, ni en la sede 1 ni en las réplicas; sin el error, la misma transacción llega completa a las otras dos sedes. "
    "Por la API, una prescripción con un medicamento inválido no deja la tecnología huérfana y un egreso con cierre anterior al inicio no deja el egreso ni cierra el encuentro; sondeando la réplica sin parar nunca se vio el egreso sin el cierre.")
tabla_con_pie(["Propiedad", "Prueba", "Resultado"], [
    ["Atomicidad", "Transacción de paciente + 2 encuentros con un CHECK violado en el tercer INSERT", "Antes 0|0 · error «violates check constraint» · después 0|0 en las tres sedes; sin el error, 1|2 completo en las réplicas"],
    ["Atomicidad (API)", "Prescripción con medicamento inválido; egreso con cierre anterior al inicio", "422 y ni la tecnología ni el egreso quedan; con datos válidos se confirman las dos escrituras"],
    ["Consistencia", "Clave foránea, CHECK y restricción única inválidos", "Rechazados por la base; el contenido no cambia"],
    ["Aislamiento", "Dos sesiones: una inserta sin confirmar; la otra lee e intenta insertar lo mismo", "La lectura no ve la fila (sin lecturas sucias); la inserción espera 5 s y falla con la restricción única"],
    ["Aislamiento (API)", "Ocho peticiones simultáneas por el diagnóstico de ingreso de un encuentro", "Se crea exactamente uno; el resto es idempotente (200) o conflicto (409), ningún 5xx"],
    ["Durabilidad", "SIGKILL de la base con una transacción confirmada y otra sin confirmar", "Lo confirmado sigue; lo no confirmado desapareció; las réplicas reciben lo confirmado y nunca lo no confirmado"],
], [1700, 3600, 3542], "Evidencia de ACID en la sede 1 y sus réplicas (Compose y Kubernetes).")
par("**Alcance.** El aislamiento es el predeterminado de PostgreSQL (`READ COMMITTED`); no se probó `SERIALIZABLE`. La réplica entre sedes es asíncrona, así que no hay atomicidad ni aislamiento *entre* sedes: una lectura en otra sede puede ver el estado anterior unos milisegundos, "
    "y solo se garantiza que cada transacción se aplica entera. La durabilidad es la de un solo nodo por sede; un disco perdido se recupera desde los pares con el RPO de la réplica.")

add(h1("CONCLUSIONES"))
add(viñetas([
    "Un esquema de 45 tablas basado en la Resolución 866 se ejecutó por primera vez en PostgreSQL real y pasó sus pruebas de restricciones (hoy 29); se necesitaron dos ajustes frente al modelo en Word (`id_sede_origen` en profesional y `bundle_json` en el RDA) para que la réplica no se detuviera, y se añadió una tabla propia (`mpi_decision`) para las decisiones del MPI.",
    "La réplica lógica en malla con sede dueña mantiene las tres sedes sincronizadas en decenas de milisegundos y permite que cada sede opere sola durante una caída o un aislamiento.",
    "La identidad federada se puede calcular sin servicio central: las tres sedes obtuvieron el mismo id_mpi sin coordinarse. Para no mezclar historias, solo el documento une solo; los datos parecidos (gemelos, homónimos) piden una decisión humana que también se replica.",
    f"En Kubernetes, la caída de la base de una sede se recupera en {fmt(rp['rto_base_sede_s'])} s y los clientes del gateway no notan la falla; un pod de API caído deja una ventana de 1 s o menos en acceso directo.",
    "Las cuatro vistas permiten verificar los 15 casos de uso, incluida la lectura de una historia atendida en otra sede.",
    "La autenticación puede seguir el mismo principio de autonomía: un token firmado con una clave común vale en las tres sedes y cada una lo verifica sola, de modo que ninguna depende de un servidor de identidad central.",
]))
add(h2("Fallas encontradas al repetir las pruebas con autenticación"))
par("Repetir el failover y los experimentos SRE con la autenticación activa destapó defectos que ya existían o que la autenticación agravó (1 a 3), y repetir las pruebas y la demostración destapó dos más (4 y 5); todos se corrigieron y las pruebas se repitieron. "
    "(1) El registro de accesos se escribía en la base antes de responder: con la base caída, cada petición quedaba retenida hasta el tiempo de espera de conexión y el cliente se rendía antes de que el gateway reintentara en otra sede (aparecían 1 o 2 lecturas fallidas por corrida). "
    "Ahora se escribe en segundo plano con una cola acotada y cada acceso queda además en el log del pod. "
    "(2) El tiempo de espera de conexión a la base era de 3 s; se bajó a 1 s para que la sede falle rápido y el gateway reintente a tiempo, y una carrera al reiniciar el pool de conexiones dejaba pasar un error 500 (ahora responde 503, que nginx sí reintenta). "
    "(3) Tras aislar la red de una sede, la API quedó paralizada de forma indefinida: `closeall()` del pool de psycopg2 retiene su candado y se bloquea al cerrar una conexión en plena consulta, y esa conexión no moría porque el keepalive de TCP no actúa cuando hay datos sin confirmar. "
    "Se encontró con `py-spy`, se corrigió cerrando el pool viejo en un hilo aparte y añadiendo `tcp_user_timeout`, y se agregó una prueba de regresión. "
    "Con estos cambios la lectura vía gateway durante la caída de la base fue de 0 fallos en cinco corridas seguidas (721 peticiones). "
    "(4) Una prueba E2E intermitente destapó un defecto de la vista del Médico: «Resolver identidad federada» mostraba su mensaje y de inmediato recargaba la historia, que redibujaba la tarjeta y lo borraba; ahora el mensaje se muestra después de recargar. "
    "(5) Al repetir la demostración, el reporte marcaba a la sede apagada como «no responde» solo unos segundos y luego volvía a «en línea»: con el par caído el proceso de réplica se reinicia cada 5 s y PostgreSQL le pone su hora de arranque como «último mensaje», así que la regla de «sin mensajes en 25 s» nunca se cumplía. "
    "Ahora una réplica solo cuenta como viva si ya recibió datos (`received_lsn` no nulo); la demostración verifica además que el Reporte de HC advierta de la sede caída. "
    "Un costo conocido: con un tiempo de espera de conexión de 1 s, una sede con la CPU saturada podría marcarse como no lista sin estar caída.")
add(h2("Limitaciones"))
add(viñetas([
    "Seguridad parcial: hay autenticación, roles y TLS en el gateway, pero los puertos directos de las APIs de laboratorio son HTTP (el token y las claves viajarían en claro si se usan), la réplica entre bases y la comunicación API-HAPI no van cifradas y no hay cifrado en reposo, OpenID Connect, revocación de tokens, consentimiento ni auditoría ATNA completa. La CA es de laboratorio (el navegador avisa hasta importarla). El paciente se identifica con documento y fecha de nacimiento, datos semipúblicos; el límite de intentos fallidos se lleva en memoria de cada réplica y la IP de origen sale de una cabecera que el gateway fija pero que un cliente puede falsificar si entra por un puerto directo.",
    "Se validó con `$validate` de HAPI solo un RDA sintético (como documento y como transacción de recursos propios) y los Bundle de ejemplo del HSB (0 errores; advertencias de narrativa y de «performer»), no el de cada encuentro real; el Patient lo comparten el bus y la API con el mismo id, pero su `identifier.system` difiere y gana el último que escribe.",
    "Un Postgres por sede (sin alta disponibilidad interna). La reconstrucción de una sede es manual. Los respaldos programados y cifrados cubren errores lógicos con un RPO de hasta unas 24 horas; la copia externa es opcional y solo se probó contra un servidor S3 local, y restaurar dentro de la sede es un procedimiento manual no ensayado en el clúster. La base de HAPI de la sede perdida no se recupera (el RDA sí, desde `bundle_json`).",
    "HAPI FHIR activo en una sola sede en el entorno de pruebas; arranque en frío de varios minutos.",
    "Sin escalado automático (HPA). El pipeline de CI/CD está escrito y validado con actionlint, y sus pasos se corrieron en local, pero no se ha ejecutado en GitHub Actions; las acciones se fijan por etiqueta y no por SHA, y el CD publica y firma artefactos pero no despliega en ningún clúster.",
]))
add(h2("Trabajo futuro"))
add(viñetas([
    "Sustituir la autenticación propia por OAuth 2.0 y OpenID Connect (por ejemplo, Keycloak), con revocación de tokens, consentimiento (recurso Consent) y auditoría ATNA completa.",
    "Cifrado en tránsito entre componentes (réplica de PostgreSQL, HAPI; por ejemplo con cert-manager) y en reposo; archivado de WAL para recuperar a un punto en el tiempo, copia externa en un proveedor real con alertas sobre la edad del último respaldo y un ensayo periódico de restauración dentro de la sede; automatizar la reconstrucción de una sede (por ejemplo, con un operador de Kubernetes).",
    "Alta disponibilidad dentro de cada sede (primario y réplica con conmutación) y escalado horizontal con HPA.",
    "Perfiles FHIR propios, terminologías (SNOMED CT, RxNorm) y un MPI probabilístico (por ejemplo, con pesos según la frecuencia de nombres) que proponga mejores candidatos y reduzca la revisión manual.",
    "Auditoría de accesibilidad con una herramienta (axe, Lighthouse) y un lector de pantalla, E2E en más navegadores, ejecutar y ajustar el pipeline en GitHub (acciones fijadas por SHA) y un despliegue continuo a un clúster real.",
    "Pruebas en un clúster de varios nodos con fallas de red reales y a mayor carga.",
]))

# ====================================================================== REFERENCIAS
add(h1("REFERENCIAS"))
referencias = [
    "Bender, D., y Sartipi, K. (2013). HL7 FHIR: An agile and RESTful approach to healthcare information exchange. En *Proceedings of the 26th IEEE International Symposium on Computer-Based Medical Systems* (pp. 326–331). IEEE. https://doi.org/10.1109/CBMS.2013.6627810",
    "Bettoni, G. N., Lobo, T. C., Tavares dos Santos, B. G., Dias Flores, C., y Santana da Silva, F. (2021). Application of HL7 FHIR in a microservice architecture for patient navigation on registration and appointments. En *3rd International Workshop on Software Engineering for Healthcare (SEH 2021), junto a ICSE 2021* (pp. 44–51). IEEE. https://doi.org/10.1109/SEH52539.2021.00015 (versión previa: arXiv:2103.07589)",
    "Beyer, B., Jones, C., Petoff, J., y Murphy, N. R. (Eds.). (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media.",
    "Brewer, E. (2012). CAP twelve years later: How the «rules» have changed. *Computer, 45*(2), 23–29. https://doi.org/10.1109/MC.2012.37",
    "Congreso de la República de Colombia. (2012). *Ley Estatutaria 1581 de 2012, por la cual se dictan disposiciones generales para la protección de datos personales*. Diario Oficial No. 48.587, 18 de octubre de 2012.",
    "Fellegi, I. P., y Sunter, A. B. (1969). A theory for record linkage. *Journal of the American Statistical Association, 64*(328), 1183–1210. https://doi.org/10.2307/2286061",
    "Gazzarata, R., Almeida, J., Lindsköld, L., Cangioli, G., Gaeta, E., Fico, G., y Chronaki, C. E. (2024). HL7 Fast Healthcare Interoperability Resources (HL7 FHIR) in digital healthcare ecosystems for chronic disease management: Scoping review. *International Journal of Medical Informatics, 189*, 105507. https://doi.org/10.1016/j.ijmedinf.2024.105507",
    "HL7 International. (2019). *FHIR release 4 (R4)*. https://hl7.org/fhir/R4/",
    "Lehne, M., Luijten, S., Vom Felde genannt Imbusch, P., y Thun, S. (2019). The use of FHIR in digital health – A review of the scientific literature. *Studies in Health Technology and Informatics, 267*, 52–58. https://doi.org/10.3233/SHTI190805",
    "Mandel, J. C., Kreda, D. A., Mandl, K. D., Kohane, I. S., y Ramoni, R. B. (2016). SMART on FHIR: A standards-based, interoperable apps platform for electronic health records. *Journal of the American Medical Informatics Association, 23*(5), 899–908. https://doi.org/10.1093/jamia/ocv189",
    "Ministerio de Salud y Protección Social [MinSalud], y Ministerio de Tecnologías de la Información y las Comunicaciones [MinTIC]. (2021). *Resolución 866 de 2021, por la cual se reglamenta el conjunto de elementos de datos clínicos relevantes para la interoperabilidad de la historia clínica en el país y se dictan otras disposiciones*. Diario Oficial No. 51.716, 25 de junio de 2021. https://normograma.supersalud.gov.co/compilacion/docs/resolucion_minsaludps_0866_2021.htm",
    "Pedrera-Jiménez, M., García-Barrio, N., Frid, S., Moner, D., Boscá-Tomás, D., Lozano-Rubí, R., Kalra, D., Beale, T., Muñoz-Carrero, A., y Serrano-Balazote, P. (2023). Can openEHR, ISO 13606, and HL7 FHIR work together? An agnostic approach for the selection and application of electronic health record standards to the next-generation health data spaces. *Journal of Medical Internet Research, 25*, e48702. https://doi.org/10.2196/48702",
    "PostgreSQL Global Development Group. (2024). *PostgreSQL 16 documentation: Logical replication*. https://www.postgresql.org/docs/16/logical-replication.html",
    "Shapiro, M., Preguiça, N., Baquero, C., y Zawirski, M. (2011). Conflict-free replicated data types. En X. Défago, F. Petit, y V. Villain (Eds.), *Stabilization, Safety, and Security of Distributed Systems* (LNCS 6976, pp. 386–400). Springer. https://doi.org/10.1007/978-3-642-24550-3_29",
    "The Kubernetes Authors. (2024). *Kubernetes documentation*. https://kubernetes.io/docs/",
    "Vogels, W. (2009). Eventually consistent. *Communications of the ACM, 52*(1), 40–44. https://doi.org/10.1145/1435417.1435432",
    "Vorisek, C. N., et al. (2022). Fast Healthcare Interoperability Resources (FHIR) for interoperability in health research: Systematic review. *JMIR Medical Informatics, 10*(7), e35724. https://doi.org/10.2196/35724",
]
for r in referencias:
    add(p(r, jc="left", despues=100, ind=567, sz=21))
add(p("Verificación de las referencias (7 de noviembre de 2026): cada una se contrastó contra registros en línea de la editorial, Crossref, PubMed, arXiv o el normograma oficial. "
      "Se corrigieron seis: Bettoni et al. (identificador de arXiv, sede, DOI y autores), Gazzarata et al. (título, volumen y DOI), Lehne et al. (DOI y autores), "
      "Pedrera-Jiménez et al. (número de artículo y DOI), la Resolución 866 de 2021 (título completo y emisor, que es conjunto con el MinTIC) y Fellegi y Sunter (se usa el DOI de JSTOR, el único confirmado). "
      "Límites: se comprobó la existencia, los autores, la sede y el identificador, pero no se releyó cada texto completo para confirmar que respalde la frase exacta que lo cita; "
      "el intervalo de páginas de Shapiro et al. proviene de una fuente secundaria; y no se abrieron las direcciones de la documentación de FHIR R4, PostgreSQL y Kubernetes. "
      "Se usa «et al.» en el texto, pero la lista completa de autores solo se dio donde se verificó. La vigencia de la Resolución 866 no se comprobó más allá de que su página oficial no muestra modificaciones.",
      despues=120, sz=19, i=True, color="7F4F00"))

# ====================================================================== ANEXOS
add(h1("ANEXOS"))
add(h2("Anexo A. Estructura del repositorio y cómo reproducir"))
par("**Repositorio (público):** https://github.com/sebastianmarinc19-sudo/historia-clinica-distribuida · rama `reingenieria-3-sedes` · versión entregada: etiqueta `v1.0`. Para obtenerlo y ejecutarlo desde cero (solo Docker):")
add(codigo("""
git clone --branch reingenieria-3-sedes https://github.com/sebastianmarinc19-sudo/historia-clinica-distribuida.git
cd historia-clinica-distribuida
docker compose up -d --build
bash scripts/demo.sh
"""))
add(codigo("""
historia-clinica-distribuida/            (rama reingenieria-3-sedes)
  app/         API v2 de cada sede: hc_api/ (main, auth, auditoria, mpi, fhir, reporte, campos57, static/ = vistas)
  hsb/         bus de integración: hc_hsb/ (HL7 v2, CSV, normalizador, Bundle FHIR, cola con reintentos), tests/
  fhir/        Bundles de ejemplo generados por el código y validar.sh (Bundle/$validate)
  db/          esquema (01), semillas (02), réplica (03), fhir_db (04), migraciones/, tests/ (SQL)
  infra/       k8s/ (base, overlays por sede, gateway TLS, hsb, observabilidad) · gateway/ · backup/ · init/
  tests/       api/ (unitarias, integración, seguridad, ACID, auditoría, reporte) · e2e/ (Playwright, jsdom) · coleccion/ (Postman)
  ejemplos/    contrato del HSB (mensajes del parcial, sin modificar)
  docs/        UML (PlantUML), img/, BITACORA.md, resultados_sre.json, construir_documento.py
  scripts/     k8s_desplegar.sh, ci.sh, credenciales.py, certificados.py, demo.sh, nodo.sh, datos_demo.py, respaldos.sh,
               sre_k8s.py, prueba_api*.sh, prueba_hsb*.sh, prueba_acid.sh, prueba_auditoria.sh, prueba_vistas.sh, prueba_e2e.sh
  docker-compose.yml   un solo comando: sedes, HAPI, HSB, gateway y métricas del gateway
  .github/     workflows de CI, nocturno y CD, y Dependabot
"""))
add(codigo("""
# Opción A: un solo comando con Docker Compose, desde un clon limpio (el servicio init crea claves y certificados)
docker compose up -d --build               # 3 sedes + réplica, HAPI de Sincelejo, bus HSB y gateway TLS (https://localhost:8443)
python3 scripts/credenciales.py            # claves de laboratorio (aleatorias, fuera de git); CA para los clientes: credenciales/ca.crt
bash scripts/prueba_api.sh                 # unitarias, integración, autenticación, bus, auditoría, reporte y TLS
bash scripts/prueba_hsb_compose.sh         # contrato del HSB: HL7 v2, CSV, rechazo, duplicado y sede caída
bash scripts/prueba_auditoria.sh compose   # altera y borra eventos de la auditoría y comprueba que se detectan
bash scripts/prueba_vistas.sh compose      # vistas nuevas cargadas en jsdom contra el gateway
docker compose down -v                     # lo borra todo; el siguiente up empieza de cero
# Opción B: Kubernetes
minikube start --driver=docker --memory=2800 --cpus=3
bash scripts/k8s_desplegar.sh              # imagen, claves, certificados, 3 sedes, gateway y Prometheus
python3 scripts/credenciales.py            # muestra las claves de laboratorio (aleatorias, fuera de git)
bash scripts/prueba_api_k8s.sh             # unitarias, integración, autenticación y TLS
bash scripts/prueba_e2e.sh                 # E2E de las 4 vistas en Chromium
python3 scripts/sre_k8s.py                 # experimentos de caos y carga
bash scripts/ci.sh                         # lint, unitarias, SQL, manifiestos y secretos
# vistas por el gateway: https://$(minikube ip):30443/sede/1/vistas/  (CA: credenciales/ca.crt)
#         directas (HTTP, solo laboratorio): :30101 Sincelejo · :30102 Cartagena · :30103 Corozal
"""))
add(h2("Anexo B. Puntaje y vinculación determinista del MPI (app/hc_api/mpi.py)"))
add(codigo(extraer("app/hc_api/mpi.py", "def calcular_score", "@dataclass")))
add(h2("Anexo C. Publicación de réplica y suscripciones"))
add(codigo(extraer("db/03_replicacion.sh", "CREATE PUBLICATION", "EOSQL")))
add(codigo("""
CREATE SUBSCRIPTION sub_sincelejo_desde_cartagena
    CONNECTION 'host=pg.sede-cartagena... dbname=historia_clinica user=replicator ...'
    PUBLICATION pub_sede
    WITH (origin = none, copy_data = false);
"""))
add(h2("Anexo D. Restricciones del modelo que se verifican en la base"))
add(codigo(extraer("db/01_esquema_57_campos.sql", "-- A lo sumo un diagnóstico IN", "CREATE TABLE tecnologia_encuentro")))

add(h2("Anexo E. Reconstrucción de una sede con disco vacío (scripts/reconstruir_sede.sh)"))
add(viñetas([
    "**Precondición:** el pod `pg-0` de la sede ya arrancó con una base nueva (esquema, semillas y publicación); el script aborta si la sede ya tiene pacientes.",
    "**1.** Detiene la API de la sede (no debe recibir escrituras mientras se reconstruye).",
    "**2.** En cada par elimina la suscripción rota hacia la sede y el slot huérfano de la sede.",
    "**3.** En la sede crea las suscripciones hacia los pares con `copy_data = false`: desde ese instante cada par le envía lo que cambie.",
    "**4.** Copia las filas existentes de cada par con `pg_dump --data-only --on-conflict-do-nothing` y `session_replication_role = replica`; lo que ya llegó por la suscripción no se duplica.",
    "**5.** En cada par crea de nuevo la suscripción hacia la sede.",
    "**6.** Verifica que la sede igualó a sus pares (con un corte de tiempo fijo, porque otras sedes siguen escribiendo) y vuelve a levantar la API.",
]))

add(h2("Anexo F. Bitácora y declaración de uso de IA y de código abierto (resumen; completa en docs/BITACORA.md)"))
par("**Uso de IA.** Este proyecto se desarrolló con apoyo de un asistente de IA (Claude, de Anthropic, mediante Claude Code) en varias sesiones de trabajo. El asistente escribió, ejecutó y corrigió gran parte del código, de las pruebas, de los scripts, "
    "de este documento y de los diagramas; las decisiones de alcance las tomó el equipo cuando el asistente las consultó. Cada pieza se ejecutó antes de darse por buena (pruebas con PostgreSQL real, despliegue en Docker Compose y en Minikube, E2E en Chromium, CI local y los mensajes de ejemplo del curso). "
    "Quedan sin verificar: el CI/CD en GitHub Actions y el E2E de las vistas nuevas contra Kubernetes (pasó en Compose; en Kubernetes se verificaron con jsdom). Cada integrante debe poder explicar y modificar en vivo cualquier parte que se entregue; la bitácora lista qué partes revisar antes de la sustentación.")
par("**Código abierto usado** (licencias: revisar en cada proyecto): PostgreSQL, FastAPI, Uvicorn, psycopg2, Pydantic, HAPI FHIR, nginx, Prometheus, Kubernetes y Minikube, Docker Compose, Grafana, Playwright, jsdom, newman, PlantUML, age, rclone, ruff, shellcheck y gitleaks.")
par("**Contribución por integrante.** Debe salir del historial real de git (`scripts/bitacora_commits.sh`); a la fecha de este documento el trabajo está sin commit y el equipo completa esa tabla con sus commits. No se fabrica ni se reescribe el historial.")

# ====================================================================== AVANCE
add(h1("AVANCE INICIAL"))
add(viñetas([
    "Revisión del informe del laboratorio, del modelo de 57 campos y del repositorio de partida; se identificó que el código v2 no estaba disponible y se reconstruyó. Completa.",
    "Mapa de actores reorganizado en cuatro vistas (Paciente, Médico, Admisionista, Reportero) y 15 casos de uso modelados en PlantUML. Completo.",
    "Entorno: PostgreSQL 16, HAPI FHIR en contenedor, Docker Compose y Minikube; repositorio git con rama local de trabajo. Completo (sin publicación en remoto).",
    "Interfaces: cuatro vistas web funcionales verificadas en navegador (no hubo maquetas en Figma).",
    "Diagramas: casos de uso, secuencia, clases (2), estados (2) y arquitectura en PlantUML. Completos.",
    "API REST (FastAPI, no Spring Boot) con unas 30 rutas, incluidas /Patient y /Encounter mediante el RDA hacia HAPI FHIR. Completa.",
    "Plan de pruebas ejecutado: 45 unitarias, 23 de integración, 12 de autenticación y roles, 8 de TLS, 9 del MPI, 11 del rol del bus, 15 de la auditoría (con anclaje y AuditEvent), 8 del reporte de HC, 6 de ACID, 4 de la migración PUT, 68 del HSB, 19 E2E de las vistas, 29 de restricciones, 32 de failover y 12 objetivos SRE. Completo.",
]))

# ====================================================================== VIABILIDAD
add(h1("VIABILIDAD TÉCNICA: ESCALABILIDAD Y CUMPLIMIENTO NORMATIVO"))
add(h2("Escalabilidad"))
tabla_con_pie(["Punto de la plantilla", "Estado", "Detalle"], [
    ["Microservicios en contenedores con Kubernetes (Minikube en desarrollo)", "Implementado", "Tres sedes, gateway y Prometheus en Minikube con Kustomize."],
    ["HPA y VPA según CPU, RAM y rendimiento", "No implementado", "La API tiene 2 réplicas fijas; HPA requiere metrics-server."],
    ["Ingress con NGINX o Traefik, canary y blue-green", "Parcial", "Gateway nginx propio y actualización progresiva sin caída (`maxUnavailable: 0`); sin Ingress Controller ni canary."],
    ["PostgreSQL con particionado, replicación en clúster y Patroni", "Parcial", "Replicación lógica entre sedes implementada; sin Patroni ni réplicas de lectura dentro de la sede."],
    ["Observabilidad con Prometheus, Grafana y Jaeger", "Parcial", "Prometheus con SLI de disponibilidad, latencia y retraso de réplica y, en Compose, un tablero de Grafana provisionado (perfil `observabilidad`); sin trazas distribuidas (Jaeger)."],
    ["Pruebas de estrés con JMeter y k6 hasta 10 000 transacciones FHIR por minuto", "Parcial", f"Generador propio en Python: unas {miles(ca['transacciones_por_minuto'])} tx/min a la API v2."],
], [3500, 1500, 3842], "Escalabilidad: puntos de la plantilla frente a lo implementado.")
add(h2("Cumplimiento normativo"))
tabla_con_pie(["Punto de la plantilla", "Estado", "Detalle"], [
    ["Ley 1581 de 2012, GDPR y lineamientos de la Supersalud", "Parcial", "El acceso del paciente queda limitado a su documento y todo acceso se registra, pero no hay autorización del titular ni política de datos; la vista del Paciente advierte que es un prototipo."],
    ["TLS 1.3 en tránsito y AES-256 en reposo", "Parcial", "TLS 1.2 y 1.3 en el gateway (certificado de una CA de laboratorio, HSTS, HTTP solo redirige; 1.0 y 1.1 rechazados). Sin TLS entre componentes internos (réplica, API-HAPI) ni en los puertos directos de laboratorio; discos sin cifrar."],
    ["Perfil ATNA de HL7 para auditoría", "Parcial", "Registro local por sede (quién, rol, acción, documento, resultado e IP), también de los ingresos fallidos; se expone como `AuditEvent` de FHIR (`/auditoria/fhir`) pero no se centraliza en un repositorio ATNA. Además hay métricas y trazabilidad de los 57 campos (CU-15)."],
    ["Gestión de consentimientos con el recurso Consent", "No implementado", "—"],
    ["OAuth 2.0 / OpenID Connect con Keycloak y RBAC por rol", "Parcial", "RBAC por rol con tokens JWT firmados que valen en las 3 sedes (sin servidor central que pueda caer); es autenticación propia, no OpenID Connect, y sin revocación."],
    ["RPO ≤ 15 min y RTO ≤ 1 hora", "Parcial", f"RTO de la base de la sede {fmt(rp['rto_base_sede_s'])} s; HAPI en frío unos 6 min; RPO 0 si el disco sobrevive; sede reconstruida desde sus pares en unos 30 s si lo pierde; respaldos diarios cifrados (hasta unas 24 h de datos frente a un error lógico) con restauración verificada; copia externa opcional probada solo en local."],
    ["Certificación ISO 27001 e ISO 27799", "No aplica aún", "Prevista para la fase de operación."],
], [3500, 1500, 3842], "Cumplimiento normativo: puntos de la plantilla frente a lo implementado.")

# ====================================================================== INTEROPERABILIDAD BASADA EN DATOS
add(h1("INTEROPERABILIDAD BASADA EN DATOS: ENFOQUE SEMÁNTICO, TÉCNICO Y ORGANIZACIONAL"))
par("La interoperabilidad no se limita a intercambiar mensajes: exige que los datos circulen con significado, integridad y valor. A continuación se indica, "
    "para cada pilar de la plantilla, qué se hizo y qué falta.")
add(h2("1. Calidad y gestión de datos"))
add(viñetas([
    "**Hecho:** modelo canónico relacional de 57 campos con 29 catálogos controlados; unicidad por sede, claves foráneas y CHECK verificados; MDM determinista: el documento identifica, los datos parecidos piden decisión humana replicada (no es un MPI probabilístico completo).",
    "**Hecho:** los recursos FHIR conservan el identificador del documento y el RDA se versiona por encuentro (`composicion_bundle`).",
    "**Pendiente:** perfiles FHIR locales, validación con el módulo de validación de FHIR, metadatos FAIR y recurso Provenance.",
]))
add(h2("2. Interoperabilidad semántica"))
add(viñetas([
    "**Hecho:** CIE-10 para diagnósticos, LOINC para resultados y UCUM para unidades (en catálogos de muestra), CUM para medicamentos, y un `ConceptMap` de diagnóstico local a CIE-10 en el HSB.",
    "**Pendiente:** SNOMED CT y RxNorm, servidor de terminología, CQL y validación semántica continua con SUSHI.",
]))
add(h2("3. Interoperabilidad técnica"))
add(viñetas([
    "**Hecho:** API REST y FHIR R4 en JSON; Bundle de tipo document con Composition, Patient, Encounter, Condition, MedicationRequest, Procedure y Observation.",
    "**Equivalente:** la réplica lógica cumple entre sedes el papel de propagación de eventos que la plantilla asigna a FHIR Subscriptions y Kafka.",
    "**Hecho:** ingesta de HL7 v2 (ADT^A01, ORU^R01) y CSV por un bus propio. **Pendiente:** IHE XDS.b y MHD, Mirth Connect (se sustituyó por el bus propio), pruebas de conformidad con Touchstone.",
]))
add(h2("4. Gobernanza organizacional"))
par("No se abordó: comité de datos clínicos, roles de custodia, madurez HIMSS EMRAM, gestión del cambio ni KPIs institucionales. Las métricas del proyecto (cobertura de "
    "migración y trazabilidad de los 57 campos) podrían alimentar esos KPIs.")
add(h2("5. Herramientas de integración técnica"))
par("Se eligió **HAPI FHIR** por ser de código abierto, nativo de FHIR R4 y fácil de contenerizar, y se descartó Smile CDR (licencia). Para HL7 v2 y CSV se escribió un bus propio en lugar de usar Mirth o Rhapsody "
    "(véase el HSB). La Tabla 18 reproduce la matriz de compatibilidad de la plantilla.")
add(h2("6. Herramientas de integración semántica"))
par("No se desplegó un servidor de terminología: los catálogos son tablas locales con códigos reales de muestra. El módulo de terminología de HAPI FHIR sería el primer paso, "
    "porque se integra en el mismo servidor.")
add(h2("7. Compatibilidad de herramientas con estándares de interoperabilidad"))
par("Se conserva la matriz de la plantilla como referencia; el proyecto usa HAPI FHIR (fila destacada).")
_tab_plantilla = _tab[0]
tabla_con_pie(["Herramienta", "HL7 v2.x", "HL7 CDA", "HL7 FHIR", "IHE perfiles"], [
    ["**HAPI FHIR Server** (usado)", "✖", "✖", "✔", "◑"],
    ["Smile CDR", "✔", "✔", "✔", "✔"],
    ["Mirth Connect", "✔", "✔", "✔", "◑"],
    ["OpenHIM", "✔", "◑", "✔", "✔"],
    ["Apache Camel + camel-fhir", "✔", "◑", "✔", "◑"],
    ["Kong API Gateway", "✖", "✖", "✔", "✖"],
    ["Redox (SaaS)", "✔", "✔", "◑", "✖"],
    ["Rhapsody Integrator", "✔", "✔", "✔", "✔"],
    ["GCP Healthcare API / Azure HDS", "✔", "◑", "✔", "✖"],
    ["Snowstorm", "✖", "✖", "✔", "✖"],
    ["Ontoserver", "✖", "✖", "✔", "✖"],
    ["Apelon DTS", "✖", "✖", "◑", "✖"],
], [3242, 1400, 1400, 1400, 1400], "Compatibilidad de herramientas con los estándares (tomada de la plantilla del curso; ✔ soporte nativo, ◑ parcial, ✖ sin soporte directo).",
    alinear_centro=(1, 2, 3, 4))
assert _tab[0] == 18, f'la tabla de compatibilidad es la {_tab[0]}, no la 18: actualice la referencia'

# ====================================================================== VALIDACIÓN UML
add(h1("VALIDACIÓN DE MODELOS UML"))
add(h2("Métodos"))
par("No se usaron Visual Paradigm, Enterprise Architect ni OCL. Los diagramas se escribieron en PlantUML (texto versionado) y se validaron **contra la "
    "implementación**: cada regla de los modelos se convirtió en una prueba ejecutable que falla si el código se aparta del diagrama.")
tabla_con_pie(["Elemento", "Regla de validación", "Herramienta o prueba"], [
    ["Caso de uso", "Cada CU-01 a CU-15 tiene una ruta de la API y una vista", "Pruebas de integración y verificación en navegador"],
    ["Clase", "Claves, cardinalidades y catálogos del modelo", "29 pruebas de restricciones SQL; mapa de 57 campos (`campos57.py`)"],
    ["Secuencia", "Verbos y códigos HTTP del flujo (201, 200, 409, 503)", "Pruebas de integración y de failover"],
    ["Estado", "El estado de migración solo toma PENDIENTE, MIGRADO o ERROR; el egreso cierra el encuentro", "CHECK en la base y prueba de la API"],
    ["Arquitectura", "Una sede caída o aislada no detiene a las otras", "Pruebas de failover y experimentos SRE"],
], [1800, 4300, 2742], "Reglas de validación de los modelos y evidencia ejecutable.")
add(h2("Resultados"))
par("La validación contra la implementación encontró discrepancias entre el modelo y la realidad que obligaron a corregir los diagramas y el esquema: el modelo "
    "de clases original permitía que dos sedes registraran al mismo profesional con una restricción única global, lo que detenía la réplica (se añadió `id_sede_origen`); "
    "el diagrama de casos de uso no tenía al Paciente ni al Reportero; y el RDA solo vivía en el HAPI de la sede dueña (se añadió `bundle_json`).")
add(h2("Discusión"))
par("Validar los modelos con pruebas ejecutables, en lugar de solo con revisión visual, detectó errores que un modelo estático no muestra, en particular los "
    "relacionados con la distribución (conflictos de réplica y orden de llegada). La limitación es que las reglas validadas son las que el equipo pensó en escribir; "
    "una validación formal (OCL sobre el XMI) quedaría como trabajo futuro.")

construir(PLANTILLA, SALIDA, "".join(cuerpo), imagenes, TITULO, AUTORES)
print(f"Documento escrito: {SALIDA}")
print(f"Figuras: {_fig[0]} · Tablas: {_tab[0]} · Imágenes incrustadas: {len(imagenes.archivos)}")
