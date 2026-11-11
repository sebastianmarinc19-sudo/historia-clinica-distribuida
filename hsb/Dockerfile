# HSB (bus de integración de salud). La construye scripts/k8s_desplegar.sh / docker compose.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hc_hsb ./hc_hsb
COPY datos ./datos
COPY tests ./tests
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "hc_hsb.main:app", "--host", "0.0.0.0", "--port", "8000"]
