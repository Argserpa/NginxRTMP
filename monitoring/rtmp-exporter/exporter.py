"""
Exportador Prometheus para nginx-rtmp.
Procesa el endpoint /stat de nginx-rtmp y expone las métricas en formato Prometheus.

Métricas expuestas:
  - rtmp_up                     → el exportador puede contactar con nginx-rtmp (1) o no (0)
  - rtmp_publishers_total       → número de publicadores activos (streams con <publishing/>)
  - rtmp_stream_clients         → clientes conectados por stream (incluye al publicador)
  - rtmp_stream_subscribers     → suscriptores por stream (clientes sin contar al publicador)
  - rtmp_stream_bw_in_bytes     → bitrate de entrada (bytes/s)
  - rtmp_stream_bw_out_bytes    → bitrate de salida (bytes/s)
  - rtmp_stream_bytes_in_total  → bytes totales recibidos
  - rtmp_stream_bytes_out_total → bytes totales enviados
  - rtmp_stream_up              → stream activo (1) o inactivo (0)
  - rtmp_stream_uptime_seconds  → tiempo de conexión del stream (segundos)
  - rtmp_server_uptime_seconds  → tiempo de actividad del servidor nginx-rtmp
  - hls_stream_viewers          → espectadores web (HLS) distintos por stream

Nota: rtmp_stream_subscribers cuenta suscriptores a nivel RTMP (otro reproductor
que tira del stream). Los espectadores que ven por la web vía HLS no abren una
conexión RTMP, por lo que se contabilizan aparte en hls_stream_viewers a partir
del log de peticiones al playlist .m3u8 que sirve Nginx.
"""

import os
import time
import logging
import xml.etree.ElementTree as ET

import requests
from flask import Flask, Response

# ── Config ────────────────────────────────────────────────────────────────────
NGINX_STAT_URL = os.getenv("NGINX_STAT_URL", "http://nginx-stream-rtpm:80/stat")
EXPORTER_PORT  = int(os.getenv("EXPORTER_PORT", "9114"))
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "5"))

# Espectadores web (HLS): se leen del log de accesos al playlist que sirve Nginx.
HLS_LOG_URL        = os.getenv("HLS_LOG_URL", "http://nginx-stream:80/hls_viewers_log")
HLS_VIEWER_WINDOW  = int(os.getenv("HLS_VIEWER_WINDOW", "20"))       # segundos que se considera "activo" a un espectador
HLS_LOG_TAIL_BYTES = int(os.getenv("HLS_LOG_TAIL_BYTES", "262144"))  # solo se lee el final del log (256 KiB)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


# ── Parser ────────────────────────────────────────────────────────────────────

def _safe_int(element, tag, default=0):
    """Devuelve el entero del subelemento indicado, o el valor por defecto si no existe."""
    node = element.find(tag)
    if node is not None and node.text:
        try:
            return int(node.text)
        except ValueError:
            pass
    return default


def fetch_rtmp_stats():
    """
    Realiza una petición GET a /stat, procesa el XML y devuelve una lista de
    diccionarios con las métricas de cada stream activo, junto al tiempo de
    actividad del servidor.
    """
    try:
        resp = requests.get(NGINX_STAT_URL, timeout=SCRAPE_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("No se pudo contactar con %s: %s", NGINX_STAT_URL, exc)
        return None

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        log.warning("XML inválido en /stat: %s", exc)
        return None

    # Tiempo de actividad del servidor en segundos desde el arranque de Nginx
    uptime = _safe_int(root, "uptime")

    streams = []
    for app_node in root.findall(".//application"):
        app_name = (app_node.findtext("name") or "unknown").strip()
        for stream_node in app_node.findall(".//stream"):
            name = (stream_node.findtext("name") or "unknown").strip()

            # bw_in / bw_out están en bits/s en la spec original de nginx-rtmp
            # los dividimos entre 8 para tenerlos en bytes/s
            bw_in  = _safe_int(stream_node, "bw_in")  // 8
            bw_out = _safe_int(stream_node, "bw_out") // 8

            # El elemento vacío <publishing/> marca que el stream tiene un
            # publicador conectado (OBS/ffmpeg). Es la misma señal que usa
            # la página stat.xsl para distinguir emisores de visionadores.
            publishing = 1 if stream_node.find("publishing") is not None else 0

            # nclients incluye al publicador; los suscriptores reales son el
            # resto de clientes conectados al stream.
            clients = _safe_int(stream_node, "nclients")
            subscribers = max(clients - publishing, 0)

            # <time> es el tiempo de vida del stream en milisegundos.
            stream_uptime = _safe_int(stream_node, "time") // 1000

            streams.append({
                "app":             app_name,
                "stream":          name,
                "clients":         clients,
                "subscribers":     subscribers,
                "publishing":      publishing,
                "uptime_seconds":  stream_uptime,
                "bw_in_bytes":     bw_in,
                "bw_out_bytes":    bw_out,
                "bytes_in_total":  _safe_int(stream_node, "bytes_in"),
                "bytes_out_total": _safe_int(stream_node, "bytes_out"),
                "active":          1,
            })

    return {"uptime": uptime, "streams": streams}


def fetch_hls_viewers():
    """
    Cuenta los espectadores web (HLS) distintos por stream.

    Nginx registra cada petición al playlist .m3u8 en un log (época, IP, URI, vid)
    que expone por HTTP. Un reproductor HLS pide el playlist de forma periódica
    añadiendo su ?vid=<id>, así que las sesiones (vid) distintas que lo han
    solicitado en los últimos HLS_VIEWER_WINDOW segundos aproximan los
    espectadores activos. Si una petición no trae vid, se cuenta por IP.

    Devuelve {stream: nº_espectadores}. Nunca lanza excepción: si el log no está
    disponible (Nginx caído, aún sin peticiones, etc.) devuelve {}.
    """
    try:
        # Range: solo el final del log, para no leer un fichero que crece sin límite.
        resp = requests.get(
            HLS_LOG_URL,
            headers={"Range": f"bytes=-{HLS_LOG_TAIL_BYTES}"},
            timeout=SCRAPE_TIMEOUT,
        )
        if resp.status_code not in (200, 206):
            return {}
    except requests.RequestException as exc:
        log.warning("No se pudo leer el log HLS en %s: %s", HLS_LOG_URL, exc)
        return {}

    lines = resp.text.splitlines()

    # Si la respuesta es parcial y no empieza en el byte 0, la primera línea puede
    # venir cortada por la mitad: se descarta.
    content_range = resp.headers.get("Content-Range", "")
    if content_range.startswith("bytes ") and not content_range.startswith("bytes 0-") and lines:
        lines = lines[1:]

    cutoff = time.time() - HLS_VIEWER_WINDOW
    viewers = {}  # stream -> set(identidades de espectador)
    for line in lines:
        parts = line.split()
        # Formato del log: <msec> <addr> <uri> [<vid>]. El vid (4º campo) puede
        # faltar si el reproductor no lo envió; en ese caso se cae a contar por IP.
        if len(parts) < 3:
            continue
        msec, addr, uri = parts[0], parts[1], parts[2]
        vid = parts[3] if len(parts) >= 4 else None
        if not uri.endswith(".m3u8"):
            continue
        try:
            if float(msec) < cutoff:
                continue
        except ValueError:
            continue
        # Se cuenta por sesión de reproductor (vid) para no infracontar cuando
        # varios espectadores comparten IP (proxy, NAT, varias pestañas, localhost).
        # Si no hay vid, la IP es el mejor identificador disponible.
        identity = vid or addr
        # /live/<stream>.m3u8 → <stream>
        stream = uri.rsplit("/", 1)[-1][:-len(".m3u8")]
        viewers.setdefault(stream, set()).add(identity)

    return {stream: len(ids) for stream, ids in viewers.items()}


# ── Prometheus text format ────────────────────────────────────────────────────

def build_metrics(stats):
    """Genera el texto en formato de exposición de Prometheus."""
    lines = []

    def gauge(name, help_text, metric_type="gauge"):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")

    # Salud del exportador: si llegamos aquí, /stat ha respondido correctamente.
    # (En caso de fallo, el endpoint /metrics emite rtmp_up 0 directamente.)
    gauge("rtmp_up", "Indica si el exportador puede contactar con nginx-rtmp")
    lines.append("rtmp_up 1")

    # Tiempo de actividad del servidor
    gauge("rtmp_server_uptime_seconds", "Segundos transcurridos desde el arranque de nginx-rtmp")
    lines.append(f'rtmp_server_uptime_seconds {stats["uptime"]}')

    # Publicadores activos en todo el servidor (streams con <publishing/>)
    publishers = sum(s["publishing"] for s in stats["streams"])
    gauge("rtmp_publishers_total", "Publicadores RTMP activos")
    lines.append(f"rtmp_publishers_total {publishers}")

    # Si no hay streams activos, emitimos las métricas CON una muestra a cero
    # (sin etiquetas) para que Grafana muestre 0 en lugar de "No data".
    # Solo HELP/TYPE sin muestra no genera serie alguna en Prometheus.
    if not stats["streams"]:
        for metric, help_text, mtype in [
            ("rtmp_stream_clients",          "Clientes conectados al stream (incluye publicador)", "gauge"),
            ("rtmp_stream_subscribers",      "Suscriptores del stream (sin contar publicador)",    "gauge"),
            ("rtmp_stream_bw_in_bytes",      "Bitrate de entrada en bytes/s",                      "gauge"),
            ("rtmp_stream_bw_out_bytes",     "Bitrate de salida en bytes/s",                       "gauge"),
            ("rtmp_stream_bytes_in_total",   "Bytes totales recibidos",                            "counter"),
            ("rtmp_stream_bytes_out_total",  "Bytes totales enviados",                             "counter"),
            ("rtmp_stream_up",               "Stream activo (1) o inactivo (0)",                   "gauge"),
            ("rtmp_stream_uptime_seconds",   "Tiempo de conexión del stream en segundos",          "gauge"),
        ]:
            gauge(metric, help_text, mtype)
            lines.append(f"{metric} 0")
        return "\n".join(lines) + "\n"

    # Métricas por stream
    gauge("rtmp_stream_clients", "Clientes conectados al stream (incluye publicador)")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_clients{{{lbl}}} {s["clients"]}')

    gauge("rtmp_stream_subscribers", "Suscriptores del stream (sin contar publicador)")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_subscribers{{{lbl}}} {s["subscribers"]}')

    gauge("rtmp_stream_bw_in_bytes", "Bitrate de entrada en bytes/s")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_bw_in_bytes{{{lbl}}} {s["bw_in_bytes"]}')

    gauge("rtmp_stream_bw_out_bytes", "Bitrate de salida en bytes/s")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_bw_out_bytes{{{lbl}}} {s["bw_out_bytes"]}')

    gauge("rtmp_stream_bytes_in_total", "Bytes totales recibidos", "counter")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_bytes_in_total{{{lbl}}} {s["bytes_in_total"]}')

    gauge("rtmp_stream_bytes_out_total", "Bytes totales enviados", "counter")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_bytes_out_total{{{lbl}}} {s["bytes_out_total"]}')

    gauge("rtmp_stream_up", "Stream activo (1) o inactivo (0)")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_up{{{lbl}}} {s["active"]}')

    gauge("rtmp_stream_uptime_seconds", "Tiempo de conexión del stream en segundos")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_uptime_seconds{{{lbl}}} {s["uptime_seconds"]}')

    return "\n".join(lines) + "\n"


def build_hls_metrics(stats, hls_viewers):
    """
    Genera el bloque Prometheus de espectadores web (HLS), independiente de las
    sesiones RTMP. Se emite una muestra por cada stream que esté emitiendo o que
    tenga espectadores; si no hay ninguno, una muestra a cero sin etiquetas para
    que Grafana muestre 0 en lugar de "No data".
    """
    lines = [
        "# HELP hls_stream_viewers Espectadores web (HLS) distintos por stream en la ventana reciente",
        "# TYPE hls_stream_viewers gauge",
    ]

    # Unión de streams en emisión y streams con espectadores: así un stream en
    # directo sin audiencia aparece con 0 y no desaparece del panel.
    streams = set(hls_viewers) | {s["stream"] for s in stats["streams"]}
    if not streams:
        lines.append("hls_stream_viewers 0")
    else:
        for stream in sorted(streams):
            lines.append(f'hls_stream_viewers{{app="live",stream="{stream}"}} {hls_viewers.get(stream, 0)}')

    return "\n".join(lines) + "\n"


# ── Endpoints Flask ───────────────────────────────────────────────────────────

@app.route("/metrics")
def metrics():
    stats = fetch_rtmp_stats()
    if stats is None:
        # Nginx no responde: se devuelve únicamente rtmp_up a 0 para no romper Prometheus
        body = (
            "# HELP rtmp_up Indica si el exportador puede contactar con nginx-rtmp\n"
            "# TYPE rtmp_up gauge\n"
            "rtmp_up 0\n"
        )
        return Response(body, status=200, mimetype="text/plain; version=0.0.4")

    body = build_metrics(stats) + build_hls_metrics(stats, fetch_hls_viewers())
    return Response(body, status=200, mimetype="text/plain; version=0.0.4")


@app.route("/health")
def health():
    return {"status": "ok", "target": NGINX_STAT_URL}, 200


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("rtmp-exporter arrancando en el puerto %d", EXPORTER_PORT)
    log.info("Origen de métricas: %s", NGINX_STAT_URL)
    app.run(host="0.0.0.0", port=EXPORTER_PORT)