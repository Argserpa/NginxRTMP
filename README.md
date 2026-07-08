# NginxRTMP — Proyecto 1 (RTMP/HLS)

Servidor de streaming en vivo con Nginx + módulo RTMP, grabación continua a VOD y
monitorización con Prometheus/Grafana. Es el Proyecto 1 (P1) del TFG, usado como
comparativa frente al Proyecto 2 (WebRTC).

## Servicios del stack

| Servicio            | Imagen                             | Puerto | Función                                           |
|----------------------|-------------------------------------|--------|----------------------------------------------------|
| `nginx-stream-rtpm`  | nginx + módulo RTMP (build propio)  | 1935/80/443 | Ingesta RTMP + servidor web/HLS + grabación   |
| `recordings-api`     | Python/aiohttp (build propio)       | interno | API de metadatos de grabaciones (recordings.html) |
| `nginx-exporter`     | `nginx/nginx-prometheus-exporter`   | 9113   | Métricas de Nginx (stub_status)                     |
| `rtmp-exporter`      | build propio                        | 9114   | Métricas RTMP (viewers, bitrate, uptime)            |
| `prometheus`         | `prom/prometheus`                   | 9090   | Scraping de métricas                                |
| `grafana`            | `grafana/grafana`                   | 3000   | Dashboards (fuente: Prometheus)                     |
| `node-exporter`      | `prom/node-exporter`                | 9100   | Métricas del SO del host                            |

---

## Otros documentos del proyecto

Los comandos de este README son para el **despliegue con Docker Compose**. El resto
de la documentación vive en sus propios ficheros dentro de `k8s/`:

- [`k8s/README.md`](k8s/README.md) — despliegue equivalente en Kubernetes/Minikube:
  build de imágenes, manifests, acceso a los servicios y grabaciones VOD.
- [`k8s/CAMBIAR-PROYECTO.md`](k8s/CAMBIAR-PROYECTO.md) — cómo alternar entre este
  proyecto (P1) y el Proyecto 2 (WebRTC) en el mismo namespace de Minikube, ya que
  no pueden convivir a la vez.

---

## Despliegue con Docker Compose

### Construir y levantar todo
```bash
docker compose up -d --build
```
### Ver logs de todos los servicios
```bash
docker compose logs -f
```
### Solo logs de nginx
```bash
docker compose logs -f nginx-stream-rtpm
```
### Parar todo
```bash
docker compose down
```
### Parar y borrar volúmenes (Prometheus + Grafana data)
```bash
docker compose down -v
```

---

## Comandos habituales

Ejecutar bash del contenedor
```bash
docker exec -it nginx_streaming_server /bin/bash
```
Debuggear errores en la emisión
```bash
docker exec -it nginx_streaming_server netstat -tulnp
```
Parar y eliminar el contenedor (para redesplegar)
```bash
docker stop nginx_streaming_server
docker rm nginx_streaming_server
```

---

## Comandos útiles

### Crear una red (si no la crea automáticamente)
```bash
docker network create -d bridge streaming_network
```
### Puerto 80 en uso
```bash
sudo ss -tlnp | grep :80
```
### Parar nginx del sistema (si choca con el del contenedor)
```bash
sudo systemctl stop nginx
```
### Recargar nginx sin reiniciar el contenedor
```bash
docker exec nginx_streaming_server /usr/local/nginx/sbin/nginx -s reload
```
