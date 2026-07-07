#!/usr/bin/env python3
"""
Generador de carga para el Proyecto 1 (NginxRTMP/HLS).

Abre N espectadores HLS reales (aiohttp) contra el manifest .m3u8 de nginx-stream:
refrescan la playlist y descargan los segmentos nuevos igual que haría video.js/
hls.js en un navegador, hasta Ctrl-C. Es el equivalente de loadgen-webrtc.py
(repo WebRTC) pero para el Proyecto 1, para poder correr el mismo plan de pruebas
E1-E4 sin abrir N pestañas a mano.

Uso A — desde otra máquina de la LAN que alcance el HTTP de nginx-stream
(recomendado, ver CAVEAT de red más abajo):
    python loadgen-hls.py 10 http://<host>:8080

Uso B — dentro de un pod del cluster:
    kubectl cp monitoring/loadgen-hls.py streaming/<pod>:/tmp/loadgen.py
    kubectl exec -it -n streaming <pod> -- python /tmp/loadgen.py 10 http://nginx-stream

    OJO: si el pod es el PROPIO nginx-stream, los N espectadores compiten por la
    misma CPU/red que Nginx y contaminan la medida de pod_cpu_m. Para N alto
    lánzalo desde OTRO pod o desde la LAN (Uso A).

Argumentos:
    N       número de espectadores (por defecto 5)
    BASE    URL base de nginx-stream (por defecto http://localhost:8080, que es
            el puerto que publica portForwards.sh; Docker Compose sirve el mismo
            Nginx directamente en :80)
    RAMP    segundos entre el alta de cada espectador (por defecto 0.2)
    STREAM  nombre del stream (por defecto mi_stream, el stream key fijado en
            nginx.conf / index.html)

NOTA de conteo (si no se respeta, Grafana marca 0 o 1 espectador aunque N sea
mayor): rtmp-exporter cuenta 'vid' distintos vistos en los últimos
HLS_VIEWER_WINDOW=20s del log de accesos al .m3u8 (cae a IP si no hay vid). Como
todos los espectadores de este script salen de la misma IP, cada uno usa su
propio vid (uuid4) fijo de por vida y refresca el manifest muy por debajo de
esos 20s (al ritmo de EXT-X-TARGETDURATION, ~hls_fragment=3s) — igual que hace
el navegador con su ?vid=<uuid> en index.html.

CAVEAT de red (igual que en loadgen-webrtc.py, para la métrica "egress vs N"):
    Si los espectadores corren en la MISMA máquina que nginx-stream, el tráfico
    va por 'lo' y NO aparece en node_network_*{device!="lo"}. Para egress real
    en la NIC, lanza los espectadores desde OTRA(S) máquina(s) de la LAN. Además
    el conteo de espectadores solo depende de pedir el .m3u8, pero el bitrate
    depende de descargar también los .ts: por eso este script drena los
    segmentos igual que el navegador, no se limita a pedir la playlist.
"""
import asyncio
import sys
import time
import uuid
from urllib.parse import urljoin

import aiohttp

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8080"
RAMP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.2
STREAM = sys.argv[4] if len(sys.argv) > 4 else "mi_stream"

POLL_MAX = 8.0  # tope entre refrescos del manifest; muy por debajo de HLS_VIEWER_WINDOW=20s


class Viewer:
    """Un espectador HLS: vid fijo de por vida, poll de manifest + descarga de segmentos nuevos."""

    def __init__(self, session):
        self.session = session
        self.manifest_url = f"{BASE}/live/{STREAM}.m3u8?vid={uuid.uuid4().hex}"
        self.seen = set()
        self.connected = False
        self.bytes_down = 0

    async def _fetch_segment(self, seg_url):
        try:
            async with self.session.get(seg_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.read()   # drenar como haría el buffer del navegador
                self.bytes_down += len(data)
        except Exception:
            pass  # el segmento ya pudo salir de la playlist entre el parseo y la descarga

    async def run(self):
        try:
            while True:
                poll = 3.0
                try:
                    async with self.session.get(self.manifest_url,
                                                 timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        self.connected = resp.status == 200
                        text = await resp.text() if self.connected else ""
                except Exception:
                    self.connected = False
                    text = ""

                if self.connected:
                    lines = [ln.strip() for ln in text.splitlines()]
                    for ln in lines:
                        if ln.startswith("#EXT-X-TARGETDURATION:"):
                            poll = min(float(ln.split(":", 1)[1]), POLL_MAX)
                            break
                    for seg in lines:
                        if not seg or seg.startswith("#") or seg in self.seen:
                            continue
                        self.seen.add(seg)
                        await self._fetch_segment(urljoin(self.manifest_url, seg))

                await asyncio.sleep(poll)
        except asyncio.CancelledError:
            pass


async def main():
    print(f"Abriendo {N} espectadores HLS contra {BASE}/live/{STREAM}.m3u8 (ramp {RAMP}s/espectador) ...")
    async with aiohttp.ClientSession() as session:
        viewers = [Viewer(session) for _ in range(N)]
        tasks = []
        for v in viewers:
            tasks.append(asyncio.create_task(v.run()))
            await asyncio.sleep(RAMP)

        # Ventana de estabilización, igual que loadgen-webrtc.py
        for _ in range(6):
            await asyncio.sleep(5)
            up = sum(1 for v in viewers if v.connected)
            print(f"  conectados: {up}/{N}")

        print(f"{sum(1 for v in viewers if v.connected)}/{N} conectados. "
              f"Comprueba hls_stream_viewers en Grafana. Ctrl-C para cerrar.")
        try:
            last_bytes, last_t = sum(v.bytes_down for v in viewers), time.monotonic()
            while True:
                await asyncio.sleep(5)
                now_bytes, now_t = sum(v.bytes_down for v in viewers), time.monotonic()
                mbps = (now_bytes - last_bytes) * 8 / (now_t - last_t) / 1e6
                last_bytes, last_t = now_bytes, now_t
                print(f"  conectados: {sum(1 for v in viewers if v.connected)}/{N}  "
                      f"~{mbps:.2f} Mbps descargados")
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print("cerrados.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
