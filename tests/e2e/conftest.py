"""Fixtures de las pruebas E2E: un navegador Chromium y un contexto aislado por actor (cada uno con su sessionStorage)."""
import os
import pathlib

import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ["E2E_BASE"].rstrip("/")            # p. ej. https://192.168.49.2:30443 (gateway con TLS)
SALIDA = pathlib.Path(os.getenv("E2E_SALIDA", "/e2e/salida"))
_paginas: list = []


def url(sede: int, vista: str) -> str:
    return f"{BASE}/sede/{sede}/vistas/{vista}.html"


@pytest.fixture(scope="session")
def navegador():
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--no-sandbox"])
        yield nav
        nav.close()


@pytest.fixture(scope="session")
def contexto(navegador):
    """Fábrica de contextos aislados. El certificado es de una CA de laboratorio: aquí se omite su verificación
    (la validación de la CA ya la hacen las pruebas de TLS de la API)."""
    creados = []

    def crear(**kw):
        c = navegador.new_context(ignore_https_errors=True, locale="es-CO", timezone_id="America/Bogota", **kw)
        c.set_default_timeout(20_000)
        creados.append(c)
        return c
    yield crear
    for c in creados:
        c.close()


def abrir(ctx, ruta):
    page = ctx.new_page()
    _paginas.append(page)
    page.goto(ruta)
    return page


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    salida = yield
    informe = salida.get_result()
    if informe.when == "call" and informe.failed and _paginas:
        SALIDA.mkdir(parents=True, exist_ok=True)
        for i, pagina in enumerate(_paginas[-3:]):
            try:
                pagina.screenshot(path=str(SALIDA / f"{item.name}_{i}.png"), full_page=True)
            except Exception:       # noqa: BLE001  (página ya cerrada)
                pass
