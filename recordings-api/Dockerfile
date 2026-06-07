#  Imagen del servicio recordings-api
# Servicio Python ligero (aiohttp) que expone los metadatos de las grabaciones
# generadas por nginx-rtmp en /recordings. Solo lee el volumen de grabaciones;
# no necesita ffmpeg ni otras dependencias del sistema.
#
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py

EXPOSE 8081

CMD ["python", "app.py"]
