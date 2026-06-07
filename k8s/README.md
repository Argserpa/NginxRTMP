# NginxRTPM — Kubernetes Setup

## Requisitos

- [minikube](https://minikube.sigs.k8s.io/docs/start/) >= 1.32
- [kubectl](https://kubernetes.io/docs/tasks/tools/) >= 1.29
- Docker (para construir las imágenes)

---

## 1. Arrancar Minikube

```bash
minikube start --driver=docker --cpus=4 --memory=4096
```

---

## 2. Cargar las imágenes locales en Minikube

Las imágenes `nginx-rtmp-server`, `rtmp-exporter` y `recordings-api` son
personalizadas y no están en Docker Hub.

> **Importante:** ejecutar los `docker build` **desde la raíz del repositorio**
> (no desde `k8s/`). El contexto de build es `.` y el Dockerfile copia rutas
> relativas a esa raíz (`./nginx/...`, `./certs/...`, `./monitoring/...`).

Hay dos opciones equivalentes:

### Opción A — Construir directamente en el Docker de Minikube (recomendado)

Apuntando el CLI al daemon interno de Minikube, las imágenes quedan disponibles
para el clúster sin necesidad de `minikube image load`.

```bash
# Desde la raíz del repositorio:

# 1. Apuntar el CLI de Docker al daemon de Minikube (SIN -u)
eval $(minikube docker-env)

# 2. Construir las imágenes dentro de ese daemon
docker build -t nginx-rtmp-server:latest -f ./nginx/Dockerfile .
docker build -t rtmp-exporter:latest ./monitoring/rtmp-exporter/
docker build -t recordings-api:latest ./recordings-api/

# 3. (Opcional) Volver al Docker del sistema
eval $(minikube docker-env -u)
```

### Opción B — Construir en el Docker del sistema y cargarlas

```bash
# Desde la raíz del repositorio, con el Docker del sistema:
docker build -t nginx-rtmp-server:latest -f ./nginx/Dockerfile .
docker build -t rtmp-exporter:latest ./monitoring/rtmp-exporter/
docker build -t recordings-api:latest ./recordings-api/

# Cargar las imágenes ya construidas en Minikube
minikube image load nginx-rtmp-server:latest
minikube image load rtmp-exporter:latest
minikube image load recordings-api:latest
```

> Con `imagePullPolicy: Never` en los manifests, Kubernetes nunca intentará
> bajar estas imágenes de un registry externo: deben existir en Minikube por una
> de las dos vías anteriores.
>
> Tras **modificar `nginx.conf`, el Dockerfile o el código del exporter**, hay
> que reconstruir la imagen y reiniciar el despliegue para que tome la nueva
> versión:
> ```bash
> kubectl rollout restart deployment/nginx-stream -n streaming
> ```

---

## 3. Desplegar todo

```bash
# Desde la carpeta k8s/
kubectl apply -k .

# Para pruebas y debug: manifest por manifest (mismo orden)
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-secrets.yaml
kubectl apply -f nginx-stream.yaml
kubectl apply -f nginx-exporter.yaml
kubectl apply -f rtmp-exporter.yaml
kubectl apply -f prometheus.yaml
kubectl apply -f grafana.yaml
kubectl apply -f node-exporter.yaml
```

Verificar que todos los pods están `Running`:

```bash
kubectl get pods -n streaming -w
```

---

## 4. Acceder a los servicios

### Nginx (RTMP + web) — LoadBalancer

El servicio `nginx-stream` es de tipo `LoadBalancer`. En Minikube la columna
`EXTERNAL-IP` permanece en `<pending>` **hasta que se ejecuta `minikube tunnel`**.
Si no se puede conectar, casi siempre es porque el tunnel no está corriendo.

#### Opción A — `minikube tunnel` (IP externa real)

```bash
# En una terminal separada (mantener abierta mientras se usa; pide sudo)
minikube tunnel
```

Luego obtener la IP asignada:

```bash
kubectl get svc nginx-stream -n streaming
# Buscar la columna EXTERNAL-IP (ya no debería estar <pending>)
```

- **Stream RTMP** (OBS): `rtmp://<EXTERNAL-IP>:1935/live`  →  stream key: `mi_stream`
- **Página web (en vivo)**: `http://<EXTERNAL-IP>`
- **Web de grabaciones (VOD)**: `http://<EXTERNAL-IP>/recordings.html` (ver §5)

#### Opción B — NodePort (sin tunnel, acceso rápido)

El `LoadBalancer` también expone NodePorts, accesibles directamente por la IP del
nodo sin necesidad de tunnel:

```bash
minikube ip                                  # IP del nodo, p.ej. 192.168.49.2
kubectl get svc nginx-stream -n streaming    # ver los puertos 3xxxx asignados
```

Con el mapeo `80 -> 3xxxx` y `1935 -> 3yyyy` mostrado en la columna `PORT(S)`:

- **Página web**: `http://<NODE-IP>:<nodePort-de-80>`
- **Stream RTMP** (OBS): `rtmp://<NODE-IP>:<nodePort-de-1935>/live`  →  key: `mi_stream`

### Grafana — NodePort

```bash
# Abre el navegador directamente
minikube service grafana -n streaming

# O acceder manualmente
minikube ip  # obtener IP del nodo
# → http://<NODE-IP>:30300
```

Credenciales: `admin` / `prom_admin`

### Prometheus — port-forward (acceso puntual)

```bash
kubectl port-forward svc/prometheus 9090:9090 -n streaming
# → http://localhost:9090
```

---

## 5. Grabaciones y web de VOD

Cada emisión se graba automáticamente y queda disponible para verla después como
VOD en una **web de grabaciones** (`/recordings.html`), con la misma interfaz que
el proyecto WebRTC: barra lateral de fechas (de más reciente a más antigua),
tarjetas por grabación, reproductor inline y botón de descarga.

### Cómo funciona

1. La aplicación `live` graba cada emisión (`record all`). nginx-rtmp solo graba
   FLV, así que escribe primero a `/tmp/rec` (efímero).
2. Al terminar la emisión, `exec_record_done` lanza `record-done.sh`, que remuxea
   el FLV a MPEG-TS (ffmpeg `-c copy`, sin recodificar) en el volumen persistente:
   **`/recordings/AAAA-MM-DD/HH-MM-SS.ts`** (+ un sidecar `.dur` con la duración).
3. El servicio **`recordings-api`** (Python/aiohttp, `ClusterIP :8081`) lista las
   grabaciones por fecha y genera el playlist VOD `.m3u8`.
4. **nginx** sirve los `.ts` en `/recordings/` y hace `proxy_pass` de
   `/api/recordings` a `recordings-api`. La página `/recordings.html` los reproduce
   con hls.js.

El directorio `/recordings` está respaldado por el PVC `nginx-recordings`
(`nginx-stream.yaml`, 5Gi), montado de escritura en `nginx-stream` y de **solo
lectura** en `recordings-api`, así que las grabaciones **sobreviven a reinicios**.

> Los segmentos HLS/DASH *en vivo* viven en `/tmp` (efímeros); las grabaciones
> VOD `.ts` son las que se conservan en `/recordings`.

### Acceso y verificación

```bash
# Web de grabaciones: misma IP que la web en vivo (tunnel o NodePort), ruta /recordings.html
#   http://<EXTERNAL-IP>/recordings.html      (con minikube tunnel)
#   http://<NODE-IP>:<nodePort-de-80>/recordings.html   (NodePort)

# Probar la API directamente
curl http://<EXTERNAL-IP>/api/recordings            # { "dates": [...] }

# Inspeccionar las grabaciones en disco
kubectl exec -it deployment/nginx-stream -n streaming -- ls -R /recordings

# Descargar una grabación al equipo local
kubectl cp streaming/$(kubectl get pod -n streaming -l app=nginx-stream -o jsonpath='{.items[0].metadata.name}'):/recordings/<fecha>/<HH-MM-SS>.ts ./grabacion.ts
```

> 💡 Para probar sin OBS, se puede emitir un patrón de test desde dentro del pod:
> ```bash
> POD=$(kubectl get pod -n streaming -l app=nginx-stream -o jsonpath='{.items[0].metadata.name}')
> kubectl exec -n streaming "$POD" -- ffmpeg -re \
>   -f lavfi -i testsrc=size=320x240:rate=15 -f lavfi -i sine=frequency=1000 \
>   -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -t 10 \
>   -f flv rtmp://localhost:1935/live/test
> ```

---

## 6. Operaciones habituales

```bash
# Ver logs de nginx
kubectl logs -f deployment/nginx-stream -n streaming

# Recargar config de Prometheus sin reiniciar (web.enable-lifecycle activo)
kubectl port-forward svc/prometheus 9090:9090 -n streaming &
curl -X POST http://localhost:9090/-/reload

# Escalar (no aplicable a nginx-stream con RTMP, pero útil para otros)
kubectl scale deployment grafana --replicas=1 -n streaming

# Eliminar todo el despliegue (incluido el PVC de grabaciones)
kubectl delete namespace streaming
```
para exponer



