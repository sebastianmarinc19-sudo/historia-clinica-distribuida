# Navegador para las pruebas E2E de las 4 vistas (Playwright + Chromium). Se usa con scripts/prueba_e2e.sh.
FROM python:3.15-slim-bookworm
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install playwright==1.49.1 pytest==8.4.2 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /e2e
