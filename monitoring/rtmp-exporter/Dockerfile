FROM python:3.10-slim

WORKDIR /app

# Dependencias en una capa independiente para aprovechar la caché
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente del exportador
COPY exporter.py .

EXPOSE 9114

CMD ["python", "exporter.py"]
