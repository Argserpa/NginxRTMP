FROM python:3.10-slim

WORKDIR /app

# Dependencias en una capa independiente para aprovechar la caché
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY exporter.py .

# Puerto en el que Flask sirve las métricas en formato Prometheus exposition.
# Prometheus hace GET /metrics a este puerto según lo expuesto en prometheus.yml.
EXPOSE 9114

CMD ["python", "exporter.py"]
