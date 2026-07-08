# Cambiar entre Proyecto 1 (NginxRTMP/HLS) y Proyecto 2 (WebRTC) en Minikube

Los dos proyectos del TFG se despliegan en **el mismo namespace `streaming`** y
comparten nombres de recursos (`grafana`, `prometheus`, `node-exporter`, y el PVC
`grafana-pvc`). Por eso **NO pueden convivir** en el cluster: hay que tener solo
uno desplegado cada vez.

Además, para los tests de carga esto es **obligatorio**, no solo cómodo: la
métrica de capacidad se mide con `node_exporter` a nivel de **nodo entero**. Si
corrieran los dos stacks a la vez, las curvas "N vs CPU/mem/red" quedarían
contaminadas por el consumo del otro proyecto.

- **P1 (NginxRTMP):** `/home/args/AquaProjects/NginxRTMP`
- **P2 (WebRTC):**    `/home/args/AquaProjects/WebRTC`

---

## Conceptos clave

- **Las imágenes NO se borran al tirar el proyecto.** Viven en el docker de
  minikube y se cachean. `kubectl delete` quita pods/services/PVCs, no imágenes.
  → Solo hay que (re)construir imágenes la **primera vez** o cuando cambia el código.
- **El dashboard de Grafana vive en el PVC `grafana-pvc`.** Al tirar el namespace
  se borra el PVC y **se pierde el dashboard vivo**. Flujo actual = exportar el
  JSON antes y reimportarlo después (ver más abajo). (Alternativa futura:
  provisionar el dashboard desde un ConfigMap para que sobreviva a los teardowns.)
- Imágenes locales por proyecto (`imagePullPolicy: Never`):
  - **P1:** `nginx-rtmp-server`, `rtmp-exporter`, `recordings-api`
  - **P2:** `video-streamer`, `hls-web`

---

## 0) Comprobar qué hay desplegado ahora

```bash
kubectl get ns streaming                 # ¿existe el namespace?
kubectl -n streaming get pods            # ¿qué stack está corriendo?
minikube image ls | grep -E 'nginx-rtmp-server|rtmp-exporter|recordings-api|video-streamer|hls-web'
```

---

## 1) TIRAR el proyecto actual

Borrar el namespace entero es el teardown más limpio (se lleva pods, services y
PVCs, así no queda colisión con el otro proyecto):

```bash
# Si se va a tirar P1 y hay cambios en el dashboard de Grafana sin exportar:
#   abrir Grafana (port-forward) y exportar el JSON antes de borrar. Ver sección Grafana.

kubectl delete namespace streaming

# Esperar a que termine de eliminarse (es asíncrono); no aplicar el otro hasta que no exista:
kubectl get ns streaming -w     # Ctrl-C cuando dé "NotFound"
```

---

## 2) LEVANTAR el otro proyecto

### Proyecto 1 · NginxRTMP / HLS

```bash
cd /home/args/AquaProjects/NginxRTMP

# Construir imágenes EN minikube (solo 1ª vez o si cambió código):
eval $(minikube docker-env)
docker build -t nginx-rtmp-server:latest -f ./nginx/Dockerfile .   # OJO: contexto = raíz del repo
docker build -t rtmp-exporter:latest ./monitoring/rtmp-exporter/
docker build -t recordings-api:latest ./recordings-api/
eval $(minikube docker-env -u)     # (opcional) salir del docker de minikube

# Desplegar:
kubectl apply -k k8s/
kubectl -n streaming get pods -w
```

### Proyecto 2 · WebRTC

```bash
cd /home/args/AquaProjects/WebRTC

# Construir imágenes EN minikube (solo 1ª vez o si cambió código):
eval $(minikube docker-env)
docker build -t video-streamer:latest ./streamer
docker build -t hls-web:latest ./nginx
eval $(minikube docker-env -u)

# Desplegar:
kubectl apply -k k8s/
kubectl -n streaming get pods -w
```

> Si las imágenes ya estaban cacheadas y no cambió el código, **se pueden saltar
> los `docker build`** e ir directo al `kubectl apply -k k8s/`.

---

## 3) Grafana — exportar antes / reimportar después (flujo PVC)

Mientras el dashboard viva en el PVC, cada vez que se tire/borre el namespace se pierde.

**Exportar (antes de tirar, si se hicieron cambios en la UI):**
1. `kubectl -n streaming port-forward svc/grafana 3000:3000` → http://localhost:3000
2. Share → Export → "Export for sharing externally" (ON) → Save to file.
3. Reemplazar el JSON del repo correspondiente y commitear:
   - P1: `monitoring/grafana_proyecto1_rtmp Dashboard02.json`
   - P2: el JSON equivalente en el repo de WebRTC.

**Reimportar (después de levantar):**
1. `kubectl -n streaming port-forward svc/grafana 3000:3000`
2. Dashboards → New → Import → subir el JSON → seleccionar datasource Prometheus.

---

## Notas

- Acceso a Grafana también vía `minikube service grafana -n streaming`.
- `nginx-stream` (P1) es LoadBalancer: para `EXTERNAL-IP` real hace falta
  `minikube tunnel`; con NodePort funciona sin túnel.
- Despliegue manual paso a paso (sin kustomize): ver `k8s/README.md`.
