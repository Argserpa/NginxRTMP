#!/bin/sh
#  record-done.sh
# Lo invoca nginx-rtmp (exec_record_done) cuando una emisión termina y su
# grabación FLV queda cerrada. Convierte el FLV temporal en un fichero MPEG-TS
# dentro del volumen persistente /recordings, organizado por fecha, para que el
# servicio recordings-api lo liste y el navegador lo reproduzca como VOD.
#
#   Entrada : $1 = ruta completa del FLV recién grabado (la pasa nginx como $path)
#             p.ej. /tmp/rec/mi_stream_2026-06-06_14-30-00.flv
#   Salida  : /recordings/AAAA-MM-DD/HH-MM-SS.ts
#
# La conversión es un remux (-c copy): no recodifica, solo cambia el contenedor
# FLV → MPEG-TS, por lo que es rápida y no pierde calidad.
#
set -eu

flv="${1:-}"
[ -n "$flv" ] && [ -f "$flv" ] || exit 0

base=$(basename "$flv")
base=${base%.flv}

# El nombre incluye la fecha y hora de inicio (record_suffix _%Y-%m-%d_%H-%M-%S.flv).
date=$(printf '%s\n' "$base" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -n1 || true)
time=$(printf '%s\n' "$base" | grep -oE '[0-9]{2}-[0-9]{2}-[0-9]{2}' | tail -n1 || true)
[ -n "$date" ] || date=$(date +%F)
[ -n "$time" ] || time=$(date +%H-%M-%S)

outdir="/recordings/$date"
ts="$outdir/$time.ts"
mkdir -p "$outdir"

# Remux FLV (H.264/AAC) → MPEG-TS sin recodificar.
if ffmpeg -y -loglevel error -i "$flv" -c copy -f mpegts "$ts"; then
    rm -f "$flv"      # ya tenemos el .ts persistente; el FLV temporal sobra
else
    # Si falla la conversión, conservar el FLV para no perder la grabación.
    echo "record-done: ffmpeg falló para $flv" >&2
    exit 1
fi

# Duración real (redondeada hacia arriba) para que recordings-api genere un playlist
# VOD con un EXTINF correcto. Sin esto, una estimación por tamaño puede quedarse corta
# y hls.js cortaría la reproducción antes del final. Se guarda como sidecar HH-MM-SS.dur
# (no es .ts, así que la API no lo confunde con una grabación).
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$ts" 2>/dev/null || true)
if [ -n "$dur" ]; then
    # ceil: parte entera + 1 si hay decimales > 0
    whole=${dur%.*}
    case "$dur" in
        *.*) frac=${dur#*.} ;;
        *)   frac=0 ;;
    esac
    [ "$frac" -gt 0 ] 2>/dev/null && whole=$((whole + 1))
    [ "$whole" -gt 0 ] 2>/dev/null && printf '%s\n' "$whole" > "$outdir/$time.dur"
fi
