#  recordings-api 
# Pequeño servicio aiohttp que expone los metadatos de las grabaciones que produce
# nginx-rtmp (vía record-done.sh) en /recordings/AAAA-MM-DD/HH-MM-SS.ts.
#
# Reproduce el mismo contrato que la API de grabaciones del proyecto WebRTC para
# que el frontend (recordings.html) sea idéntico:
#
#   GET /api/recordings
#       → { "dates": [ {"date": "AAAA-MM-DD", "count": N}, ... ] }   (más reciente primero)
#
#   GET /api/recordings/{fecha}
#       → { "files": [ {name, display_time, size_mb, url, download_url}, ... ] }
#
#   GET /api/recordings/{fecha}/{fichero}/playlist.m3u8
#       → playlist HLS VOD mínimo que envuelve el .ts como un único segmento,
#         para que hls.js lo reproduzca en navegadores sin HLS nativo.
# 
import os
import re

from aiohttp import web

# Directorio de grabaciones (volumen compartido con nginx-stream, montado de solo lectura)
RECORD_DIR = os.getenv("RECORD_DIR", "/recordings")
PORT = int(os.getenv("PORT", "8081"))

# Bytes/segundo asumidos para estimar la duración del playlist a partir del tamaño.
# ~500 kbps. Como el bitrate real de RTMP suele ser mayor, la duración estimada
# queda por encima de la real: la barra de tiempo es algo larga pero nunca trunca
# la reproducción (un valor demasiado corto sí cortaría el vídeo antes de tiempo).
BYTES_PER_SEC = int(os.getenv("BYTES_PER_SEC", "62500"))
MIN_DURATION = int(os.getenv("MIN_DURATION", "6"))

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})\.ts$")


def _read_duration_sidecar(date_str, filename):
    """Lee la duración real (segundos, entero) del sidecar HH-MM-SS.dur, o None."""
    dur_path = os.path.join(RECORD_DIR, date_str, filename[:-3] + ".dur")
    try:
        with open(dur_path) as fh:
            value = int(fh.read().strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


async def api_recording_dates(request):
    """GET /api/recordings — fechas con grabaciones, de más reciente a más antigua."""
    dates = []
    try:
        for entry in sorted(os.listdir(RECORD_DIR), reverse=True):
            full_path = os.path.join(RECORD_DIR, entry)
            if os.path.isdir(full_path) and DATE_RE.match(entry):
                ts_count = len([f for f in os.listdir(full_path) if f.endswith(".ts")])
                if ts_count > 0:
                    dates.append({"date": entry, "count": ts_count})
    except FileNotFoundError:
        pass
    return web.json_response({"dates": dates})


async def api_recordings_for_date(request):
    """GET /api/recordings/{fecha} — grabaciones de un día con sus metadatos."""
    date_str = request.match_info["date"]
    if not DATE_RE.match(date_str):
        return web.json_response({"error": "Invalid date format"}, status=400)

    dir_path = os.path.join(RECORD_DIR, date_str)
    if not os.path.isdir(dir_path):
        return web.json_response({"files": []})

    files = []
    for f in sorted(os.listdir(dir_path)):
        if not f.endswith(".ts"):
            continue
        full = os.path.join(dir_path, f)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        # Los ficheros se llaman HH-MM-SS.ts — mostrar como HH:MM:SS
        m = TIME_RE.match(f)
        display_time = f"{m.group(1)}:{m.group(2)}:{m.group(3)}" if m else f
        files.append({
            "name": f,
            "display_time": display_time,
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "url": f"/api/recordings/{date_str}/{f}/playlist.m3u8",  # wrapper VOD para hls.js
            "download_url": f"/recordings/{date_str}/{f}",            # .ts directo para descargar
        })
    return web.json_response({"files": files})


async def api_recording_playlist(request):
    """GET /api/recordings/{fecha}/{fichero}/playlist.m3u8 — wrapper HLS VOD del .ts."""
    date_str = request.match_info["date"]
    filename = request.match_info["file"]

    if not DATE_RE.match(date_str):
        return web.Response(text="Invalid date", status=400)
    if not filename.endswith(".ts"):
        return web.Response(text="Invalid file", status=400)

    file_path = os.path.join(RECORD_DIR, date_str, filename)
    if not os.path.isfile(file_path):
        return web.Response(text="Not found", status=404)

    # Duración: usar el sidecar HH-MM-SS.dur que escribe record-done.sh (duración real
    # vía ffprobe). Si no existe (grabación antigua), estimar por tamaño como respaldo.
    duration = _read_duration_sidecar(date_str, filename)
    if duration is None:
        duration = max(int(os.path.getsize(file_path) / BYTES_PER_SEC), MIN_DURATION)
    ts_url = f"/recordings/{date_str}/{filename}"

    playlist = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        f"#EXT-X-TARGETDURATION:{duration}\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        f"#EXTINF:{duration},\n"
        f"{ts_url}\n"
        "#EXT-X-ENDLIST\n"
    )
    return web.Response(
        text=playlist,
        content_type="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def make_app():
    app = web.Application()
    app.router.add_get("/api/recordings", api_recording_dates)
    app.router.add_get("/api/recordings/{date}", api_recordings_for_date)
    app.router.add_get("/api/recordings/{date}/{file}/playlist.m3u8", api_recording_playlist)
    return app


if __name__ == "__main__":
    # El directorio /recordings lo crea y rellena nginx-stream; aquí solo se lee.
    web.run_app(make_app(), host="0.0.0.0", port=PORT)
