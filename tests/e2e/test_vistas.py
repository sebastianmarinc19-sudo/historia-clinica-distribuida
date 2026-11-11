"""E2E de las 4 vistas en un navegador real: ingreso por rol, flujo clínico CU-01..CU-15, historia en otra sede
(copia de solo lectura), acceso del paciente, reportes, accesibilidad básica y ancho móvil.

Las pruebas son secuenciales (el flujo del paciente alimenta a las siguientes) y usan un documento nuevo por corrida.
Variables: E2E_BASE (gateway https://IP:30443), HC_CREDENCIALES (claves de laboratorio), HC_CA (CA, para consultar la API).
"""
import json
import os
import re
import time
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

import sesion
from conftest import abrir, url

CRED = sesion.credenciales()
DOC = f"E2E{int(time.time())}"
NACIMIENTO = date(1940, 1, 1) + timedelta(days=int(time.time()) % 20000)
E = {}


# ------------------------------------------------------------------ utilidades
@pytest.fixture(scope="module")
def ctx_admision(contexto):
    return contexto()


@pytest.fixture(scope="module")
def ctx_medico(contexto):
    return contexto()


@pytest.fixture(scope="module")
def ctx_paciente(contexto):
    return contexto()


@pytest.fixture(scope="module")
def ctx_reportero(contexto):
    return contexto()


def ingresar(page, usuario):
    """Si la vista pide ingreso, entra con las claves de laboratorio del usuario y espera la vista."""
    if page.locator("#ingreso-personal").count():
        page.get_by_label("Usuario").fill(usuario)
        page.get_by_label("Clave").fill(CRED[usuario]["clave"])
        page.get_by_role("button", name="Ingresar").click()
    expect(page.locator("main#puerta")).to_have_count(0)
    expect(page.locator("main h2")).to_be_visible()


def elegir(select, valor):
    select.select_option(value=valor)


def primera_opcion(select):
    """Elige la primera opción con valor (espera a que el catálogo llegue)."""
    select.page.wait_for_function("(el) => [...el.options].some((o) => o.value)", arg=select.element_handle())
    valor = select.evaluate("(el) => [...el.options].find((o) => o.value).value")
    select.select_option(value=valor)


def abrir_plegable(page, titulo):
    d = page.locator("details.plegable", has=page.locator("summary", has_text=titulo))
    d.locator("summary").click()
    return d


def sin_nombre(page):
    """Controles de formulario visibles sin nombre accesible (etiqueta, aria-label o título)."""
    return page.evaluate("""() => [...document.querySelectorAll('input, select, textarea')]
        .filter((e) => e.type !== 'hidden' && e.offsetParent !== null)
        .filter((e) => !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby') && !e.title)
        .map((e) => e.outerHTML.slice(0, 80))""")


def api_json(sede, ruta, usuario="admin"):
    import urllib.request
    base = os.environ["E2E_BASE"].rstrip("/")
    req = urllib.request.Request(f"{base}/sede/{sede}/api/v2{ruta}", headers={"Authorization": "Bearer " + sesion.token(f"{base}/sede/1/api/v2/x", usuario)})
    with urllib.request.urlopen(req, timeout=30, context=sesion.contexto()) as r:
        return json.loads(r.read())


def esperar_replica(sede, timeout=40):
    limite = time.time() + timeout
    while time.time() < limite:
        r = api_json(sede, f"/pacientes/buscar?cod_tipo_documento=CC&numero_documento={DOC}")
        if r["total"] >= 1 and api_json(sede, f"/historia-federada/{DOC}?cod_tipo_documento=CC")["total_encuentros"] >= 1:
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------- puerta de ingreso
def test_las_vistas_del_personal_piden_ingreso_y_rechazan_claves_malas(contexto):
    ctx = contexto()
    for vista in ("admision", "medico", "reportes"):
        page = abrir(ctx, url(1, vista))
        expect(page.get_by_role("heading", name="Ingrese para continuar")).to_be_visible()
        expect(page.locator("main h2", has_text="Vista del")).to_be_hidden()        # los datos no se ven sin sesión
    page.get_by_label("Usuario").fill("reportero")
    page.get_by_label("Clave").fill("clave-incorrecta")
    page.get_by_role("button", name="Ingresar").click()
    expect(page.get_by_text("Usuario o clave incorrectos")).to_be_visible()
    expect(page.get_by_label("Clave")).to_have_value("")                           # la clave se borra tras el fallo


def test_un_rol_equivocado_no_entra_a_otra_vista(contexto):
    ctx = contexto()
    page = abrir(ctx, url(1, "medico"))
    page.get_by_label("Usuario").fill("admision")
    page.get_by_label("Clave").fill(CRED["admision"]["clave"])
    page.get_by_role("button", name="Ingresar").click()
    expect(page.get_by_text("esta vista es de otro rol")).to_be_visible()
    expect(page.locator("main h2", has_text="Vista del Médico")).to_be_hidden()


# ----------------------------------------------------------- Admisionista
def test_admisionista_registra_paciente_abre_encuentro_y_hace_triage(ctx_admision):
    page = abrir(ctx_admision, url(1, "admision"))
    ingresar(page, "admision")

    page.get_by_label("Tipo de documento", exact=True).select_option("CC")
    page.get_by_label("Número de documento", exact=True).fill(DOC)
    page.get_by_role("button", name="Buscar", exact=True).click()
    expect(page.locator("#m-buscar")).to_contain_text("No hay registros con ese documento")
    expect(page.get_by_label("Número de documento *")).to_have_value(DOC)           # precarga el documento

    page.get_by_label("Primer nombre *").fill("Elena")
    page.get_by_label("Primer apellido *").fill("Navegador" + DOC[-4:])
    page.get_by_label("Segundo apellido").fill("Pruebas")
    page.get_by_label("Fecha y hora de nacimiento *").fill(f"{NACIMIENTO.isoformat()}T08:00")
    elegir(page.get_by_label("Sexo biológico *"), "F")
    expect(page.get_by_label("País de residencia *")).to_have_value("COL")
    page.get_by_role("button", name="Guardar paciente").click()
    expect(page.locator("#m-paciente")).to_contain_text("Paciente creado")

    # CU-02: aparece el formulario de encuentro con valores por defecto sensatos
    expect(page.locator("#f-encuentro")).to_be_visible()
    primera_opcion(page.get_by_label("Entidad responsable del plan *"))
    page.get_by_role("button", name="Abrir encuentro").click()
    expect(page.locator("#m-encuentro")).to_contain_text("Encuentro abierto")

    # CU-03
    expect(page.locator("#f-triage")).to_be_visible()
    primera_opcion(page.get_by_label("Clasificación *"))
    page.get_by_role("button", name="Registrar triage").click()
    expect(page.locator("#m-triage")).to_contain_text("Triage registrado")
    assert sin_nombre(page) == []


def test_buscar_un_documento_ya_registrado_reutiliza_el_registro_de_la_sede(ctx_admision):
    """Buscar un documento ya registrado reutiliza el registro de esta sede."""
    page = ctx_admision.pages[0]
    page.get_by_label("Tipo de documento", exact=True).select_option("CC")
    page.get_by_label("Número de documento", exact=True).fill(DOC)
    page.get_by_role("button", name="Buscar", exact=True).click()
    expect(page.locator("#r-buscar")).to_contain_text("Sincelejo (esta sede)")
    expect(page.locator("#f-encuentro")).to_be_visible()                           # ya queda seleccionado para abrir otro encuentro
    expect(page.get_by_label("Primer nombre *")).to_have_value("Elena")


# ----------------------------------------------------------------- Médico
def test_medico_atiende_el_encuentro(ctx_medico):
    page = abrir(ctx_medico, url(1, "medico"))
    ingresar(page, "medico")
    page.get_by_label("Tipo de documento", exact=True).select_option("CC")
    page.get_by_label("Número de documento", exact=True).fill(DOC)
    page.get_by_role("button", name="Ver historia clínica").click()
    expect(page.get_by_role("heading", name="Historia entre sedes (1 encuentro)")).to_be_visible()
    page.get_by_role("button", name="Abrir", exact=True).click()
    expect(page.get_by_role("heading", name=re.compile("^Encuentro del"))).to_be_visible()
    ok = page.locator("#m-encuentro-ok")

    # Profesional (lo piden las entregas y el egreso)
    d = abrir_plegable(page, "Registrar un profesional de salud nuevo")
    d.get_by_label("Tipo de documento *").select_option("CC")
    d.get_by_label("Número *").fill("P" + DOC)
    d.get_by_label("Nombres *").fill("Camila")
    d.get_by_label("Apellidos *").fill("Restrepo")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Profesional registrado")

    # CU-04 diagnósticos
    d = abrir_plegable(page, "Agregar diagnóstico")
    d.get_by_label("Diagnóstico CIE-10 *").select_option("J00")
    d.get_by_label("Rol del diagnóstico *").select_option("IN")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Diagnóstico registrado")
    expect(page.locator("li", has_text="Ingreso: J00")).to_be_visible()

    # CU-05 medicamento y procedimiento
    d = abrir_plegable(page, "Prescribir o registrar una tecnología")
    d.get_by_label("Tecnología *").select_option("19938")
    d.get_by_label("Finalidad *").select_option("02")
    d.get_by_label("Dosis prescrita *").fill("500")
    d.get_by_label("Unidad de la dosis *").select_option("mg")
    d.get_by_label("Vía de administración *").select_option("01")
    d.get_by_label("Duración *", exact=True).fill("5")
    d.get_by_label("Unidad de la duración *").select_option("d")
    d.get_by_label("Frecuencia (cada…) *").fill("8")
    d.get_by_label("Unidad de la frecuencia *").select_option("h")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Tecnología registrada")

    d = abrir_plegable(page, "Prescribir o registrar una tecnología")
    d.get_by_label("Tecnología *").select_option("890201")
    d.get_by_label("Finalidad *").select_option("01")
    d.get_by_role("button", name="Guardar").click()
    # el mensaje es el mismo que el de la primera tecnología: se espera por el contenido real (2 filas)
    tarjeta = page.locator(".tarjeta", has=page.get_by_role("heading", name=re.compile("^Tecnologías en salud")))
    expect(tarjeta.locator("tbody tr")).to_have_count(2)

    # CU-06 entrega
    d = abrir_plegable(page, "Registrar entrega o aplicación")
    primera_opcion(d.get_by_label("Tecnología *"))
    primera_opcion(d.get_by_label("Profesional que entrega o aplica *"))
    d.get_by_label("Dosis administrada").fill("500")
    d.get_by_label("Unidad de la dosis").select_option("mg")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Entrega registrada")

    # CU-07 resultado, CU-08 antecedente y riesgo
    d = abrir_plegable(page, "Agregar resultado")
    d.get_by_label("Prueba (LOINC) *").select_option("8310-5")
    d.get_by_label("Valor numérico", exact=True).fill("38.5")
    d.get_by_label("Unidad (obligatoria con valor numérico)").select_option("C")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Resultado registrado")

    d = abrir_plegable(page, "Agregar antecedente")
    d.get_by_label("Diagnóstico CIE-10").select_option("I10")
    d.get_by_label("Descripción").fill("Hipertensión diagnosticada hace 3 años")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Antecedente registrado")

    d = abrir_plegable(page, "Agregar factor de riesgo")
    d.get_by_label("Factor de riesgo *").select_option("004")
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("Exposición registrada")

    # CU-09 egreso: el encuentro queda cerrado
    d = abrir_plegable(page, "Registrar egreso y cerrar el encuentro")
    d.get_by_label("Condición y destino *").select_option("01")
    primera_opcion(d.get_by_label("Profesional que da el egreso *"))
    d.get_by_role("button", name="Guardar").click()
    expect(ok).to_contain_text("el encuentro quedó cerrado")
    expect(page.get_by_text("Cerrado el")).to_be_visible()

    # CU-11 identidad federada (sin otra sede todavía: no hay coincidencia)
    page.get_by_role("button", name="Resolver identidad federada").click()
    expect(page.locator("#m-mpi")).to_contain_text("No hay otro registro con el mismo documento")

    assert sin_nombre(page) == []


def _fhir_disponible():
    import urllib.request
    base = os.environ["E2E_BASE"].rstrip("/")
    with urllib.request.urlopen(f"{base}/sede/1/api/health", timeout=60, context=sesion.contexto()) as r:
        return json.loads(r.read())["fhir"]["estado"] == "ok"


def test_medico_migra_a_fhir_y_ve_el_rda(ctx_medico):
    """CU-10 y CU-12. Necesita el HAPI FHIR de Sincelejo (en el entorno de pruebas arranca aparte y tarda minutos)."""
    E["fhir"] = False
    if not _fhir_disponible():
        pytest.skip("El HAPI FHIR de Sincelejo no está disponible; el resto del flujo clínico sí se probó")
    page = ctx_medico.pages[0]
    page.get_by_role("button", name="Migrar a FHIR y generar RDA").click()
    expect(page.locator("#m-fhir")).to_contain_text("Migrado. Bundle FHIR", timeout=90_000)
    E["fhir"] = True
    page.get_by_role("button", name="Ver el RDA").click()
    expect(page.locator("#v-rda")).to_contain_text("(document)")
    expect(page.locator("#v-rda")).to_contain_text("Composition")


# --------------------------------------------------- posibles duplicados (MPI)
def _api_post(sede, ruta, cuerpo, usuario="admin"):
    import urllib.request
    base = os.environ["E2E_BASE"].rstrip("/")
    req = urllib.request.Request(f"{base}/sede/{sede}/api/v2{ruta}", data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + sesion.token(f"{base}/sede/1/api/v2/x", usuario)})
    with urllib.request.urlopen(req, timeout=30, context=sesion.contexto()) as r:
        return json.loads(r.read())


def test_el_medico_revisa_gemelos_y_su_decision_se_aplica(ctx_medico):
    """Dos registros con documentos distintos y datos casi idénticos NO se unen solos: aparecen para revisar."""
    nac = (date(1945, 1, 1) + timedelta(days=(int(time.time()) + 4242) % 20000)).isoformat() + "T07:30:00"
    doc_a, doc_b = f"GE{int(time.time())}", f"GF{int(time.time())}"
    for doc, segundo in ((doc_a, "Pablo"), (doc_b, "Pedro")):
        _api_post(1, "/pacientes", {"cod_tipo_documento": "CC", "numero_documento": doc, "primer_nombre": "Juan", "segundo_nombre": segundo,
                                    "primer_apellido": "Gemelo", "segundo_apellido": "Prueba", "fecha_hora_nacimiento": nac, "cod_sexo": "M",
                                    "cod_pais_residencia": "COL"})
    page = abrir(ctx_medico, url(1, "medico"))
    ingresar(page, "medico")
    page.get_by_label("Tipo de documento", exact=True).select_option("CC")
    page.get_by_label("Número de documento", exact=True).fill(doc_a)
    page.get_by_role("button", name="Ver historia clínica").click()

    expect(page.get_by_role("heading", name="Posibles duplicados por revisar (1)")).to_be_visible()
    expect(page.get_by_text("Datos parecidos, documento distinto")).to_be_visible()
    expect(page.get_by_text("no hay otra sede con el mismo paciente")).to_be_visible()        # no se unieron solos

    if os.getenv("E2E_CAPTURAS"):            # captura opcional para la documentación
        page.locator("#s-revision").screenshot(path=f"{os.getenv('E2E_SALIDA', '/e2e/salida')}/duplicados_mpi.png")
    page.get_by_label("Motivo de la decisión").fill("gemelos, según la familia")
    page.get_by_role("button", name="Son personas distintas").click()
    expect(page.locator("#m-buscar")).to_contain_text("Decisión guardada: son personas distintas")
    expect(page.get_by_role("heading", name="Decisiones sobre posibles duplicados")).to_be_visible()
    expect(page.locator("#s-revision")).to_contain_text("personas distintas")

    page.get_by_role("button", name="Es la misma persona").click()                          # la decisión más reciente manda
    expect(page.locator("#m-buscar")).to_contain_text("Decisión guardada: son la misma persona")
    expect(page.locator("#s-revision")).to_contain_text("misma persona")
    expect(page.get_by_text("resuelta")).to_be_visible()                                     # ahora tienen identidad federada
    assert sin_nombre(page) == []


# --------------------------------------------------------------- Paciente
def test_paciente_ve_su_historia_y_rechaza_datos_que_no_coinciden(ctx_paciente):
    page = abrir(ctx_paciente, url(1, "paciente"))
    page.get_by_label("Tipo de documento").select_option("CC")
    page.get_by_label("Número de documento").fill(DOC)
    page.get_by_label("Fecha de nacimiento").fill((NACIMIENTO + timedelta(days=1)).isoformat())
    page.get_by_role("button", name="Ver mi historia clínica").click()
    expect(page.locator("#m-ingreso")).to_contain_text("no coinciden")
    expect(page.get_by_role("heading", name="Mis datos")).to_have_count(0)

    page.get_by_label("Fecha de nacimiento").fill(NACIMIENTO.isoformat())
    page.get_by_role("button", name="Ver mi historia clínica").click()
    expect(page.get_by_role("heading", name="Mis datos")).to_be_visible()
    expect(page.get_by_text("Elena Navegador" + DOC[-4:] + " Pruebas")).to_be_visible()
    expect(page.get_by_role("heading", name="Mis atenciones (1)")).to_be_visible()
    page.get_by_text("Ver el detalle de esta atención").click()
    expect(page.get_by_text("Hipertensión")).to_have_count(0)                       # el detalle muestra diagnósticos/medicamentos, no antecedentes
    expect(page.get_by_text("Rinofaringitis aguda")).to_be_visible()
    expect(page.get_by_text("Acetaminofén")).to_be_visible()
    if E.get("fhir"):
        with page.expect_download() as d:
            page.get_by_role("button", name="Descargar mi RDA").click()
        assert d.value.suggested_filename.startswith("mi-rda-")
    assert sin_nombre(page) == []


def test_la_sesion_del_paciente_se_retoma_al_recargar_y_se_cierra_con_salir(ctx_paciente):
    page = ctx_paciente.pages[0]
    page.reload()
    expect(page.get_by_role("heading", name="Mis atenciones (1)")).to_be_visible()   # sin volver a pedir los datos
    page.get_by_role("button", name="Salir").click()
    expect(page.get_by_role("heading", name="Mis datos")).to_have_count(0)
    expect(page.get_by_role("button", name="Ver mi historia clínica")).to_be_visible()


# --------------------------------------------- historia en otra sede (réplica)
def test_el_medico_ve_en_cartagena_la_atencion_de_sincelejo_como_copia_de_solo_lectura(ctx_medico):
    assert esperar_replica(2), "la atención no llegó a Cartagena"
    page = ctx_medico.pages[0]
    page.goto(url(2, "medico"))      # misma pestaña: la sesión (token de Sincelejo) vale en Cartagena sin volver a ingresar
    expect(page.locator("main h2", has_text="Vista del Médico")).to_be_visible()
    page.get_by_label("Tipo de documento", exact=True).select_option("CC")
    page.get_by_label("Número de documento", exact=True).fill(DOC)
    page.get_by_role("button", name="Ver historia clínica").click()
    expect(page.get_by_text("Sincelejo · réplica")).to_be_visible()
    expect(page.get_by_text("Este paciente no está registrado en esta sede: solo lectura")).to_be_visible()
    page.get_by_role("button", name="Abrir", exact=True).click()
    expect(page.get_by_text("solo tiene una copia de lectura")).to_be_visible()
    expect(page.locator("summary", has_text="Agregar diagnóstico")).to_have_count(0)  # no hay formularios de escritura
    expect(page.get_by_role("button", name="Migrar a FHIR y generar RDA")).to_have_count(0)


def test_el_paciente_ve_en_corozal_su_atencion_de_sincelejo(ctx_paciente):
    assert esperar_replica(3), "la atención no llegó a Corozal"
    page = abrir(ctx_paciente, url(3, "paciente"))
    page.get_by_label("Tipo de documento").select_option("CC")
    page.get_by_label("Número de documento").fill(DOC)
    page.get_by_label("Fecha de nacimiento").fill(NACIMIENTO.isoformat())
    page.get_by_role("button", name="Ver mi historia clínica").click()
    expect(page.get_by_text("Atendido en Sincelejo")).to_be_visible()
    expect(page.get_by_text("copia disponible en esta sede")).to_be_visible()


# --------------------------------------------------------------- Reportero
def test_reportero_ve_cobertura_auditoria_replica_y_accesos(ctx_reportero):
    page = abrir(ctx_reportero, url(1, "reportes"))
    ingresar(page, "reportero")
    for ciudad in ("Sincelejo", "Cartagena", "Corozal"):                                   # CU-14
        expect(page.locator("#cobertura")).to_contain_text(ciudad)
    expect(page.locator("#tabla-cobertura table")).to_be_visible()

    page.get_by_label("Auditar solo un lote (opcional)").fill("E2E")                        # CU-15 con filtro por lote
    page.get_by_role("button", name="Aplicar").click()
    expect(page.locator("#resumen-auditoria")).to_contain_text("completos")
    completos = int(re.search(r"(\d+) completos", page.locator("#resumen-auditoria").inner_text()).group(1))
    assert completos >= 15, f"el caso clínico llenó pocos campos de los 57: {completos}"
    expect(page.locator("#celdas > div")).to_have_count(57)

    expect(page.locator("#replicacion")).to_contain_text("activa")                          # réplica
    expect(page.locator("#replicacion")).not_to_contain_text("inactiva")

    expect(page.locator("#accesos")).to_contain_text("medico")                              # registro de accesos
    page.get_by_label("Solo intentos rechazados").check()
    resultado = page.locator("#accesos tbody tr td:nth-child(5)")                         # columna «Resultado»
    expect(resultado.filter(has_text=re.compile(r"^2\d\d$"))).to_have_count(0)               # esperar a que el filtro se aplique
    expect(page.locator("#accesos")).to_contain_text("401")
    assert resultado.count() > 0
    for i in range(resultado.count()):
        assert re.fullmatch(r"4\d\d", resultado.nth(i).inner_text().strip()), "el filtro dejó una fila que no fue rechazada"
    assert sin_nombre(page) == []


# ------------------------------------------- pantallas nuevas: reporte de HC, accesos, bus y estado
def test_reportero_genera_el_reporte_de_hc_y_el_navegador_recalcula_su_sello(ctx_reportero):
    page = abrir(ctx_reportero, url(1, "reportes"))
    ingresar(page, "reportero")
    expect(page.locator("#s-estado")).to_contain_text("Sincelejo")                          # tablero de estado
    expect(page.locator("#s-estado")).to_contain_text("Auditoría íntegra")
    page.get_by_label("Número de documento").fill(DOC)
    page.get_by_role("button", name="Generar reporte").click()
    expect(page.locator("#s-reporte")).to_contain_text(DOC)
    expect(page.locator("#s-reporte")).to_contain_text("Sede Sincelejo")
    expect(page.locator("#s-reporte")).to_contain_text("campos completos")
    assert re.fullmatch(r"[0-9a-f]{64}", page.locator("#rep-sello").inner_text().strip())
    page.get_by_role("button", name="Comprobar sello en este navegador").click()
    expect(page.locator("#rep-comprobacion")).to_contain_text("El sello coincide con el contenido")
    with page.expect_download() as d:
        page.get_by_role("button", name="Descargar el reporte (JSON)").click()
    assert d.value.suggested_filename == f"reporte_hc_{DOC}.json"
    page.locator("#verificar-auditoria").click()                                            # integridad de la cadena de auditoría
    expect(page.locator("#s-integridad")).to_contain_text("cadena íntegra")
    assert sin_nombre(page) == []


def test_el_paciente_ve_en_sus_accesos_que_el_reportero_consulto_su_reporte(ctx_paciente):
    page = abrir(ctx_paciente, url(1, "paciente"))
    if page.get_by_role("button", name="Ver mi historia clínica").count():
        page.get_by_label("Tipo de documento").select_option("CC")
        page.get_by_label("Número de documento").fill(DOC)
        page.get_by_label("Fecha de nacimiento").fill(NACIMIENTO.isoformat())
        page.get_by_role("button", name="Ver mi historia clínica").click()
    expect(page.get_by_role("heading", name="Quién ha accedido a mi historia")).to_be_visible()
    expect(page.locator("#mis-accesos")).to_contain_text("reportero")
    expect(page.locator("#mis-accesos")).to_contain_text("permitido")


def test_el_admisionista_ve_la_tabla_de_mensajes_del_bus(ctx_admision):
    page = abrir(ctx_admision, url(1, "admision"))
    ingresar(page, "admision")
    expect(page.get_by_role("heading", name="Mensajes del bus de integración (HL7 v2 y CSV)")).to_be_visible()
    expect(page.locator("#bus-resumen")).to_contain_text("mensajes")
    expect(page.locator("#bus-tabla")).not_to_contain_text("[object")
    assert sin_nombre(page) == []


def test_el_medico_ve_el_estado_de_la_plataforma(ctx_medico):
    page = abrir(ctx_medico, url(1, "medico"))
    ingresar(page, "medico")
    expect(page.locator("#plataforma")).to_contain_text("Auditoría íntegra")
    expect(page.locator("#plataforma")).to_contain_text("Base de datos")


def test_la_portada_muestra_las_sedes_como_texto(contexto):
    page = abrir(contexto(), url(1, "index"))
    expect(page.locator("#sedes")).to_contain_text("Sincelejo")
    expect(page.locator("#sedes")).not_to_contain_text("object")


# ------------------------------------------------------ accesibilidad y móvil
PAGINAS = ["index", "admision", "medico", "paciente", "reportes"]


def test_las_paginas_declaran_idioma_titulo_y_un_h1(contexto):
    ctx = contexto()
    for vista in PAGINAS:
        page = abrir(ctx, url(1, vista))
        expect(page.locator("html")).to_have_attribute("lang", "es")
        assert page.title().strip(), vista
        expect(page.locator("header h1")).to_have_count(1)
        assert sin_nombre(page) == [], vista


def test_no_hay_desbordamiento_horizontal_en_pantalla_de_telefono(contexto):
    ctx = contexto(viewport={"width": 375, "height": 812})
    for vista in PAGINAS:
        page = abrir(ctx, url(1, vista))
        page.wait_for_load_state("networkidle")
        ancho = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        assert ancho[0] <= ancho[1] + 1, f"{vista}: contenido de {ancho[0]} px en pantalla de {ancho[1]} px"
