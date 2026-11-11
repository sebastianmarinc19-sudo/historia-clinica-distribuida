FROM python:3.15-slim

WORKDIR /app

COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY hc_api ./hc_api

# Cada sede corre su propia instancia; SEDE_ID, DB_HOST y FHIR_BASE_URL
# se definen en docker-compose.
EXPOSE 8001
CMD ["uvicorn", "hc_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
