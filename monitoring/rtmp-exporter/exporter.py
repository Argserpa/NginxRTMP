"""
Exportador Prometheus para nginx-rtmp.
Procesa el endpoint /stat de nginx-rtmp y expone las métricas en formato Prometheus.

Métricas expuestas:
  - rtmp_stream_clients        → usuarios conectados por stream
  - rtmp_stream_bw_in_bytes    → bitrate de entrada (bytes/s)
  - rtmp_stream_bw_out_bytes   → bitrate de salida (bytes/s)
  - rtmp_stream_bytes_in_total → bytes totales recibidos
  - rtmp_stream_bytes_out_total→ bytes totales enviados
  - rtmp_stream_up             → stream activo (1) o inactivo (0)
  - rtmp_server_uptime_seconds → tiempo de actividad del servidor nginx-rtmp
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

            streams.append({
                "app":            app_name,
                "stream":         name,
                "clients":        _safe_int(stream_node, "nclients"),
                "bw_in_bytes":    bw_in,
                "bw_out_bytes":   bw_out,
                "bytes_in_total": _safe_int(stream_node, "bytes_in"),
                "bytes_out_total":_safe_int(stream_node, "bytes_out"),
                "active":         1,
            })

    return {"uptime": uptime, "streams": streams}


# ── Prometheus text format ────────────────────────────────────────────────────

def build_metrics(stats):
    """Genera el texto en formato de exposición de Prometheus."""
    lines = []

    def gauge(name, help_text, metric_type="gauge"):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")

    # Tiempo de actividad del servidor
    gauge("rtmp_server_uptime_seconds", "Segundos transcurridos desde el arranque de nginx-rtmp")
    lines.append(f'rtmp_server_uptime_seconds {stats["uptime"]}')

    # Si no hay streams activos, emitimos igual las métricas para que Grafana
    # muestre cero en lugar de "no data"
    if not stats["streams"]:
        for metric, help_text, mtype in [
            ("rtmp_stream_clients",         "Clientes conectados al stream",        "gauge"),
            ("rtmp_stream_bw_in_bytes",      "Bitrate de entrada en bytes/s",        "gauge"),
            ("rtmp_stream_bw_out_bytes",     "Bitrate de salida en bytes/s",         "gauge"),
            ("rtmp_stream_bytes_in_total",   "Bytes totales recibidos",              "counter"),
            ("rtmp_stream_bytes_out_total",  "Bytes totales enviados",               "counter"),
            ("rtmp_stream_up",               "Stream activo (1) o inactivo (0)",     "gauge"),
        ]:
            gauge(metric, help_text, mtype)
        return "\n".join(lines) + "\n"

    # Métricas por stream
    gauge("rtmp_stream_clients", "Clientes conectados al stream")
    for s in stats["streams"]:
        lbl = f'app="{s["app"]}",stream="{s["stream"]}"'
        lines.append(f'rtmp_stream_clients{{{lbl}}} {s["clients"]}')

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

    body = build_metrics(stats)
    return Response(body, status=200, mimetype="text/plain; version=0.0.4")


@app.route("/health")
def health():
    return {"status": "ok", "target": NGINX_STAT_URL}, 200


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("rtmp-exporter arrancando en el puerto %d", EXPORTER_PORT)
    log.info("Origen de métricas: %s", NGINX_STAT_URL)
    app.run(host="0.0.0.0", port=EXPORTER_PORT)
