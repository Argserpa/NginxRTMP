# Cómo rellenar los CSV de métricas (Proyecto 1 — NginxRTMP/HLS)

Guía paso a paso para generar los datos de `metricas_p1_escalado.csv`
(escenarios **E1** referencia, **E2** escalado de N y **E3** degradación de
red) y `metricas_p1_E4.csv` (escenario **E4**, resistencia 60 min). Se basa
en tres piezas ya existentes en el repo:

- `monitoring/toma-metricas-p1.sh` — toma muestras de Prometheus/`kubectl top`
  (columnas `N_peers … bitrate_Mbps`).
- `monitoring/loadgen-hls.py` — genera N espectadores HLS reales sin abrir N
  pestañas a mano.
- `nginx/html/js/qoe-meter.js` (usado desde `index.html`) — mide en el
  navegador `startup_ms` y `stalls_per_min` (columnas manuales del CSV).

> Nota sobre los ficheros actuales: `metricas_p1_escalado.csv` y
> `metricas_p1_escalado00.csv` son idénticos — usa solo uno de los dos y borra
> el otro cuando puedas.
>
> Nota sobre las columnas: cada fila del CSV combinado son en realidad **dos
> CSV pegados uno junto a otro** (el de `toma-metricas-p1.sh` a la izquierda,
> el que descarga `qoe-meter.js` a la derecha), separados por una columna en
> blanco. Por eso `timestamp` y `escenario` aparecen dos veces con valores
> distintos: las de la izquierda son del muestreo Prometheus, las de la
> derecha del navegador donde corrió `qoe-meter.js`.
>
> Esta guía sigue el plan de pruebas descrito en la memoria del TFG
> (`~/TFG/tfgRepoComplete/TFG/main.pdf`, sección 4.5.2 "Escenarios de
> prueba" y capítulo 6 "Pruebas"). Dos matices de esa memoria que conviene
> tener presentes al tomar más datos:
>
> - **Por qué `QoE.start()` es automático y no un clic manual.** Durante la
>   ejecución de E2 se detectó que si `QoE.start()` se llama antes de que
>   una persona pulse play a mano, el `startup_ms` medido incluye el tiempo
>   de reacción humana; y si se llama después de que el vídeo ya esté
>   reproduciéndose, el evento `playing` ya ha ocurrido y solo mide el
>   siguiente fotograma de un flujo en marcha (~5 ms), no el arranque real.
>   Por eso `index.html` arranca en autoplay silenciado (`muted`) y dispara
>   `QoE.start()` automáticamente al cargar, leyendo `?escenario=…` de la
>   propia URL — no hay que pulsar play a mano en ningún paso de esta guía.
> - **Repeticiones.** El plan formal (sección 4.5.3) pide un mínimo de 3
>   repeticiones independientes por combinación (sistema × escenario × N).
>   Por restricciones de tiempo, los datos ya existentes de E1–E3 solo
>   tienen **1 repetición completa** (las 4 `muestra`s consecutivas de cada
>   `rep`/N). Si el objetivo ahora es completar el plan, lo que falta por
>   cada combinación son **2 repeticiones independientes más** (repetir
>   desde cero los pasos de carga + toma de muestras + QoE, no solo tomar
>   más muestras seguidas), y reportarlas como media ± desviación típica
>   entre repeticiones.

## Requisitos previos (comunes a todos los escenarios)

1. Minikube arrancado y streaming desplegado (namespace `streaming`).
2. OBS (u otra fuente) emitiendo RTMP contra `nginx-stream` con la stream key
   `mi_stream` — sin esto `bitrate_Mbps` sale a 0 y no hay nada que ver.
3. Port-forward de Prometheus abierto en otra terminal:
   ```bash
   kubectl -n streaming port-forward svc/prometheus 9090:9090
   ```
4. Port-forward (o acceso LAN) al HTTP de `nginx-stream` para servir el
   `.m3u8`/`.ts` a los espectadores y al navegador de pruebas — el mismo host
   que usarías para ver `index.html`.
5. Comprobar que `kubectl top pod` funciona (metrics-server activo):
   ```bash
   kubectl top pod -n streaming -l app=nginx-stream
   ```
   Si falla, `pod_cpu_m`/`pod_mem_Mi` saldrán `NA` en el CSV (el script sigue
   funcionando igual).

Sitúate en `monitoring/` para lanzar los scripts (`./toma-metricas-p1.sh`,
`python loadgen-hls.py`).

---
## Escenario E1 prueba de referencia
Se ejecuta sin receptores (N_peers = 0) para ver cómo funciona el sistema:


```bash
  cd monitoring
  ./toma-metricas-p1.sh -e E1
```

## Escenario E2 — escalado (N = 1, 5, 10, 25)

En `metricas_p1_escalado.csv`, la columna `rep` no es "repetición del mismo
N": es el **índice del nivel de N** dentro de la secuencia de escalado.

| `rep` (CSV) | N espectadores |
|---|---|
| 1 | 1 |
| 2 | 5 |
| 3 | 10 |
| 4 | 25 |

Para cada nivel de N se toman 4 muestras de Prometheus (cada 30 s, por
defecto del script) **y**, por separado, 4 reproducciones reales en
navegador para medir QoE (esas 4 reproducciones son la `repeticion` 1–4 de
`qoe-meter.js`, y se alinean con el número de `muestra` al fusionar el CSV).

### Pasos, repetidos para cada N ∈ {1, 5, 10, 25} con su `rep` correspondiente

1. **Lanzar la carga de N espectadores** (deja esta terminal abierta durante
   todo el paso 2 y 3):
   ```bash
   python3 loadgen-hls.py <N> http://<host>:8080
   python3 monitoring/loadge n-hls.py 5 http://localhost:8080
   ```
   Espera a que imprima `conectados: <N>/<N>` (ventana de estabilización de
   ~30 s que el propio script hace).

2. **Tomar las 4 muestras de Prometheus/kubectl top** para ese nivel:
   ```bash
   ./toma-metricas-p1.sh -e E2 -r <rep> -o ../metricas_p1_escalado.csv
   ```
   (usa los valores por defecto: `-n 4 -i 30`, es decir 4 muestras cada 30 s
   ≈ 2 min). Esto añade 4 filas al CSV con `escenario=E2`, `rep=<rep>`,
   `muestra=1..4` y deja vacías las columnas manuales.

3. **Medir QoE en un cliente real (navegador)**, en paralelo o justo después
   del paso 2 — 4 reproducciones sueltas, una por cada `repeticion` 1–4:
   - Abre `index.html` con los parámetros del escenario en la URL:
     ```
     http://<host>:8080/index.html?escenario=E2&parametro=N=<N>&rep=1
     ```
   - `qoe-meter.js` arranca automáticamente `QoE.start()` justo antes de
     fijar el `src` del vídeo (ver `index.html:96-104`), captura el
     `startup_ms` al primer frame y cuenta eventos `waiting` como stalls.
   - Deja reproducir un rato razonable (en los datos históricos, entre 50 s y
     ~225 s por repetición), luego en la consola del navegador:
     ```js
     await QoE.stop()
     ```
   - Repite recargando la página con `rep=2`, `rep=3`, `rep=4` (mismo `N`).
   - Al terminar las 4, descarga el CSV acumulado:
     ```js
     QoE.downloadCSV()
     ```
     (o `QoE.dumpCSV()` si prefieres copiar de la consola).

4. **Cierra el loadgen** (Ctrl-C) antes de pasar al siguiente nivel de N.

5. Repite los pasos 1–4 para el siguiente `(N, rep)` de la tabla.

### Fusionar los dos CSV en `metricas_p1_escalado.csv`

El CSV que descarga `QoE.downloadCSV()` trae las columnas
`timestamp,sistema,escenario,parametro,repeticion,startup_ms,stalls_count,duracion_s,stalls_per_min,fuente_stalls`.
Pégalas como columnas adicionales a la derecha del CSV de
`toma-metricas-p1.sh` (deja una columna en blanco de separación, como en el
fichero actual), haciendo corresponder cada fila por:

- mismo `escenario`
- mismo `parametro` (`N=<N>`) ↔ mismo `rep`/N del CSV izquierdo
- `repeticion` (derecha) = `muestra` (izquierda)

También puedes rellenar a mano `latencia_g2g_ms` (columna del CSV izquierdo)
cronometrando el retardo emitido→visionado con un cronómetro, ya que no hay
forma automática de medirlo (así lo indica el panel de notas del dashboard de
Grafana).

---

## Escenario E3 — degradación de red (tc/netem)

El diseño formal (memoria, sección 4.5.2) especifica **dos** condiciones de
red degradada: 1% pérdida + 50 ms de RTT, y 5% pérdida + 200 ms de RTT. Por
restricciones de tiempo, en la ejecución real (capítulo 6) solo se ha
corrido **una condición exploratoria** (100 ms de RTT + 2% de pérdida),
aplicada igual a P1 y P2, con audiencia añadida (N=6) para acercarla a un
uso real. Las dos condiciones formales quedan pendientes — más abajo tienes
los comandos exactos si quieres completarlas.

Se aplica con `tc netem` sobre una interfaz del **host** (no dentro de los
pods). **Ojo con cuál**, porque depende de dónde corre el cliente que mide:

- Si el `loadgen`/navegador corren en el **mismo host** que minikube (el
  caso normal, `http://localhost:8080`): el tráfico **no** sale por la NIC
  LAN (`enp7s0`) — ni siquiera si usas la IP LAN del propio host, porque
  Linux resuelve conexiones a tu propia IP por rutas "local" (`lo`), sin
  tocar el cable. `kubectl port-forward` reenvía cada conexión local por un
  túnel ya abierto contra el **apiserver**, que vive dentro del contenedor
  de minikube (driver docker) y se alcanza por el **bridge Docker de
  minikube** — confirmado viendo las conexiones reales del proceso
  `kubectl port-forward` con `ss -tnp`: verás un `ESTAB` entre
  `192.168.49.1:<puerto> ↔ 192.168.49.2:8443`. Ese bridge (nombre tipo
  `br-xxxxxxxxxxxx`) es la interfaz correcta:
  ```bash
  docker network ls | grep minikube   # confirma el nombre del bridge
  ip -o link show | grep '^[0-9]*: br-'   # o así, si el nombre cambió
  ```
  Aplicar `netem` sobre `enp7s0` en este caso **no tiene ningún efecto** —
  se probó el 2026-08-30 y las muestras salieron indistinguibles de un E2
  sin degradación (ver `metricas_p1_escalado01.csv`).
- Si el cliente corre en **otro dispositivo de la LAN** apuntando a la IP
  del host (`http://<IP-LAN-host>:8080`, con el port-forward abierto con
  `--address 0.0.0.0`), entonces sí atraviesa `enp7s0` en ambos sentidos, y
  esa es la interfaz correcta para ese caso.

Da igual con qué flags arranques `minikube start` (cpus/memoria): eso no
cambia por qué interfaz sale el tráfico. Ejemplo asumiendo cliente en el
mismo host (caso normal):

```bash
BRIDGE=$(docker network ls --format '{{.Name}}' | grep minikube | xargs -I{} docker network inspect {} -f '{{.Id}}' | cut -c1-12)
sudo tc qdisc add dev br-$BRIDGE root netem delay 100ms loss 2%
./monitoring/toma-metricas-p1.sh -e E3 -r 1 -o metricas_p1_escalado.csv
sudo tc qdisc del dev br-$BRIDGE root netem
```

**Verifica siempre antes de dar la toma por buena** que el retardo se nota
de verdad en el mismo camino que usará el cliente de prueba:
```bash
curl -o /dev/null -s -w '%{time_total}\n' http://localhost:8080/live/mi_stream.m3u8
```
Sin `netem` activo debería salir cerca de 0; con la regla puesta en la
interfaz correcta, claramente por encima del `delay` configurado.

Las filas de E3 se añaden **al mismo `metricas_p1_escalado.csv`** de E2 (no
a un fichero aparte) — así están en el histórico, a continuación de las
filas de E2.

### Pasos

1. Deja conectados **N=6** espectadores (el valor usado en la prueba real,
   no uno de los niveles de la escalera de E2):
   ```bash
   python3 loadgen-hls.py 6 http://<host>:8080
   ```

2. **Aplica la degradación** en la interfaz correcta (ver arriba — el
   bridge Docker de minikube si el cliente corre en el mismo host,
   `enp7s0` si corre en otro dispositivo de la LAN):
   ```bash
   sudo tc qdisc add dev br-<id-bridge-minikube> root netem delay 100ms loss 2%
   ```
   Comprueba siempre con el `curl` de arriba que la latencia añadida se
   nota antes de tomar las muestras — si no se nota, casi seguro que la
   regla está en la interfaz equivocada
   (`ss -tnp | grep kubectl` para ver por dónde va de verdad, o
   `ip route get <IP del espectador>` si el cliente es remoto).

3. **Toma las 4 muestras** de Prometheus/kubectl top, igual que en E2, sobre
   el mismo CSV:
   ```bash
   ./toma-metricas-p1.sh -e E3 -r 1 -o ../metricas_p1_escalado.csv
   ```

4. **Mide QoE en el navegador**, una reproducción por `muestra`
   (`?escenario=E3&parametro=N=6&rep=1..4`). Con esta condición, el modelo
   HLS sobre TCP no tolera bien la degradación (cada segmento retransmitido
   bloquea al siguiente por cabeza de línea) — en la prueba real, resultado
   registrado en la Tabla 6.5 de la memoria:

   | Muestra | Startup (s) | Stalls/min | Observación |
   |---|---|---|---|
   | 1 | 79.7 | 1.93 | mucha degradación |
   | 2 | 59.1 | 1.25 | mucha degradación |
   | 3 | 114.9 | 1.37 | mucha degradación |
   | 4 | sin datos | sin datos | no llegó a cargar ningún fotograma |

   Si te pasa lo mismo que en la muestra 4 (el reproductor agota el tiempo
   de espera sin llegar a reproducir), no vas a poder volcar una fila de
   métricas de servidor coherente para ese intento —`toma-metricas-p1.sh`
   depende de que `hls_stream_viewers` refleje una sesión activa—; documenta
   ese caso de forma cualitativa en la columna `notas` (p. ej. `no llegó a
   cargar ningún fotograma`) en vez de forzar un valor numérico.
   `latencia_g2g_ms` puede quedar en `N/A` si la degradación hace inviable
   cronometrarla a mano; anota `mucha degradación` en `notas` para dejar
   constancia de que la toma se hizo con `netem` activo.

5. **IMPORTANTE — retira siempre la regla de `tc` al terminar la prueba**,
   o la máquina se queda con la red degradada para todo lo demás:
   ```bash
   sudo tc qdisc del dev br-<id-bridge-minikube> root netem
   ```
   Comprueba también que no quede ninguna regla huérfana de una sesión
   anterior (`tc qdisc show dev br-<id-bridge-minikube>` y
   `tc qdisc show dev enp7s0`) — el 2026-08-30 se encontró una regla en
   `enp7s0` olvidada de una prueba previa, sin efecto sobre las medidas
   pero degradando la LAN real de la máquina para todo lo demás mientras
   estuvo puesta.

### Pendiente: las dos condiciones formales del plan

Si quieres completar el plan tal y como está especificado en la memoria,
faltan estas dos condiciones (mismos pasos de arriba, cambiando solo el
`netem` y usando `-r 2` / `-r 3` para no pisar la fila de la condición
exploratoria):

```bash
# Condición A del plan: 1% pérdida + 50 ms RTT
sudo tc qdisc add dev br-<id-bridge-minikube> root netem delay 50ms loss 1%
./toma-metricas-p1.sh -e E3 -r 2 -o ../metricas_p1_escalado.csv
sudo tc qdisc del dev br-<id-bridge-minikube> root netem

# Condición B del plan: 5% pérdida + 200 ms RTT
sudo tc qdisc add dev br-<id-bridge-minikube> root netem delay 200ms loss 5%
./toma-metricas-p1.sh -e E3 -r 3 -o ../metricas_p1_escalado.csv
sudo tc qdisc del dev br-<id-bridge-minikube> root netem
```

---

## Escenario E4 — resistencia 60 minutos (N = 10 fijo)

Aquí no hay escalado: un único nivel de carga (N=10) sostenido una hora, con
muestreo denso de Prometheus (120 muestras × 30 s = 60 min) y **una sola**
medición larga de QoE que cubre toda la hora.

### Pasos

1. **Lanzar la carga fija de 10 espectadores** y dejarla corriendo toda la
   prueba:
   ```bash
   python loadgen-hls.py 10 http://<host>:8080
   ```

2. **Tomar 120 muestras cada 30 s** (60 minutos) de Prometheus/kubectl top:
   ```bash
   ./toma-metricas-p1.sh -e E4 -r 1 -n 120 -i 30 -o ../metricas_p1_E4.csv
   ```
   Esto tarda ~1 h en completarse (el script duerme 30 s entre muestras);
   déjalo corriendo en su propia terminal.

3. **Medir QoE una sola vez, para toda la hora**, en un cliente real:
   - Abre, justo cuando arranques el paso 2 (para que los tiempos se
     solapen):
     ```
     http://<host>:8080/index.html?escenario=E4&parametro=N=10&rep=1
     ```
   - Deja el vídeo reproduciendo sin recargar la página durante toda la hora
     (`qoe-meter.js` sigue contando eventos `waiting` todo ese tiempo).
   - Al cabo de ~60 min, en la consola:
     ```js
     await QoE.stop()      // startup_ms del arranque inicial, stalls acumulados en 1h
     QoE.downloadCSV()
     ```
   - Esto genera **una única fila** QoE con `duracion_s` ≈ 3600 s y
     `stalls_per_min` ya normalizado a esa hora completa.

4. **Fusionar**: pega esa única fila QoE junto a la fila del CSV de la
   izquierda que corresponda al final de la prueba (última `muestra`, la
   nº 120) — o a la primera, si prefieres registrar ahí el `startup_ms`
   inicial; en los datos históricos de `metricas_p1_E4.csv` se guardó tanto
   al principio (fila `muestra=1`) como al final (fila `muestra=120`), y el
   resto de filas intermedias se dejan con las columnas QoE vacías porque no
   hay una medición por muestra, solo la medición larga de toda la hora.

5. `latencia_g2g_ms`: igual que en E2, se mide a mano con cronómetro (no
   automatizada) y se anota en la columna correspondiente de una fila
   representativa.

---

## Resumen rápido de comandos

```bash
# Prerrequisito, en su propia terminal:
kubectl -n streaming port-forward svc/prometheus 9090:9090

# E2 — repetir para (rep,N) = (1,1) (2,5) (3,10) (4,25)
python loadgen-hls.py <N> http://<host>:8080
./toma-metricas-p1.sh -e E2 -r <rep> -o ../metricas_p1_escalado.csv
# + 4 reproducciones en navegador con ?escenario=E2&parametro=N=<N>&rep=1..4
#   y QoE.stop() / QoE.downloadCSV() tras cada una

# E3 — degradación de red (netem), añadido al mismo metricas_p1_escalado.csv
# condición exploratoria ya ejecutada (N=6, 100ms/2%); -r 2 y -r 3 son las
# dos condiciones formales del plan, aún pendientes (ver sección E3 arriba)
# IMPORTANTE: si el cliente corre en el mismo host que minikube, la interfaz
# es el bridge Docker de minikube, NO enp7s0 (ver sección E3 arriba) —
# comprobar antes con: ss -tnp | grep kubectl
python3 loadgen-hls.py 6 http://<host>:8080
sudo tc qdisc add dev br-<id-bridge-minikube> root netem delay 100ms loss 2%
./toma-metricas-p1.sh -e E3 -r 1 -o ../metricas_p1_escalado.csv
sudo tc qdisc del dev br-<id-bridge-minikube> root netem     # ¡no lo olvides!
# + navegador con ?escenario=E3&parametro=N=6&rep=1..4, notas="mucha degradación"

# E4 — una sola pasada, N=10, 60 min
python loadgen-hls.py 10 http://<host>:8080
./toma-metricas-p1.sh -e E4 -r 1 -n 120 -i 30 -o ../metricas_p1_E4.csv
# + navegador con ?escenario=E4&parametro=N=10&rep=1, reproduciendo 1h seguida,
#   luego QoE.stop() / QoE.downloadCSV()
```
