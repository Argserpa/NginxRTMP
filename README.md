## Trabajo de Fin de Grado

Este repositorio es uno de los dos entregables de código de un Trabajo de Fin de Grado:

- **Título**: Virtualización ligera y cloud computing para el despliegue de servidores
  streaming para la docencia online de ingeniería.
- **Autor**: Ángel Roberto García Serpa
- **Tutor**: Agustín Carlos Caminero Herráez
- **Titulación**: Grado en Ingeniería Informática
- **Universidad**: Universidad Nacional de Educación a Distancia (UNED),
  Escuela Técnica Superior de Ingeniería Informática
- **Curso académico**: 2025/2026

El TFG compara dos paradigmas de *streaming* en igualdad de condiciones (mismas métricas,
mismos escenarios de carga, mismo despliegue en Kubernetes): este repositorio implementa
el **Proyecto 1** (HLS/MPEG-DASH sobre Nginx-RTMP); el **Proyecto 2** (WebRTC con `aiortc`);
vive en [github.com/Argserpa/WebRTC](https://github.com/Argserpa/WebRTC).

# NginxRTMP
Servidor de medios con Nginx  RTMP V0 docker localhost.

# Construir y levantar todo
``` bash
docker compose up -d --build
```
# Ver logs de todos los servicios
``` bash
docker compose logs -f
```
# Solo logs de nginx
``` bash
docker compose logs -f nginx-stream-rtmp
```
# Parar todo
``` bash
docker compose down
```
# Parar y borrar volúmenes (Prometheus + Grafana data)
``` bash
docker compose down -v
```
--- 
## Comandos Habituales
ejecutar bash del contenedor
``` bash
    docker exec -it nginx-stream-rtmp /bin/bash   
```
Debuggear errores en la emisión
``` bash       
    docker exec -it nginx-stream-rtmp netstat -tulnp
```
pasos para la ejecución y el despliegue y redespliegue de la aplicación:
se para y elimina el contenedor.
``` bash
docker stop nginx-stream-rtmp
docker rm nginx-stream-rtmp
``` 
---
## Comandos útiles

### Crear una red (si no la crea automáticamente)
``` bash
    docker network create -d bridge streaming_network
```
### Puerto 80 en uso:

``` bash
sudo ss -tlnp | grep :80
```

### parar nginx
``` bash
sudo systemctl stop nginx
```

### Recargar nginx
``` bash
docker exec nginx-stream-rtmp /usr/local/nginx/sbin/nginx -s reload
```
