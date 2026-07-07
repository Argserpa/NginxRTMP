/*
 * qoe-meter.js
 * Instrumentación cliente (navegador) para dos métricas de QoE:
 *   - Tiempo hasta el primer fotograma (startup delay), en ms
 *   - Tasa de stalling (rebufferings/congelaciones), de la que se deriva 1/min
 *
 * Funciona para los dos proyectos del TFG:
 *   - Proyecto 1 (HLS con Video.js):       QoE.attachVideoJs(player)
 *   - Proyecto 1 (HLS / hls.js, <video>):  QoE.attach(video)
 *   - Proyecto 2 (WebRTC, aiortc):         QoE.attach(video, pc)
 *     (al pasar el RTCPeerConnection se usa freezeCount de getStats; en Chrome)
 *
 * USO TÍPICO (por cada ejecución de un escenario):
 *   QoE.attach(document.querySelector('video'), pc);   // pc opcional (solo P2)
 *   QoE.start({ sistema: 'P2', escenario: 'E2', parametro: 'N=10', repeticion: 1 });
 *   // ...lanzar la reproducción JUSTO DESPUÉS de start() para un startup justo...
 *   // ...esperar la ventana de la toma (p. ej. 60 s en E4)...
 *   await QoE.stop();           // registra una fila y la imprime en consola
 *   QoE.downloadCSV();          // descarga el CSV con todas las filas acumuladas
 *   // alternativa si la descarga falla: QoE.dumpCSV()  -> vuelca el CSV a consola
 *
 * NOTA sobre comparabilidad: fija t0 (el momento de start()) con el mismo criterio
 * en ambos sistemas —p. ej. el gesto del usuario / la carga de la página que dispara
 * la reproducción— para que los valores de startup sean comparables entre P1 y P2.
 * En escenarios multi-visionador (E2), ejecuta el módulo en cada pestaña/cliente:
 * cada instancia mide su propia QoE de cliente.
 */
(function () {
  'use strict';

  const rows = [];        // filas acumuladas (una por ejecución)
  let run = null;         // ejecución en curso
  let videoRef = null;
  let pcRef = null;       // RTCPeerConnection (solo Proyecto 2)
  let vjsPlayer = null;   // reproductor Video.js (solo Proyecto 1, opcional)

  const nowMs = () => performance.now();
  const isoStamp = () => new Date().toISOString();
  const r1 = (x) => Math.round(x * 10) / 10;
  const r2 = (x) => Math.round(x * 100) / 100;

  // Lee freezeCount del inbound-rtp de vídeo (WebRTC). Devuelve null si no existe.
  async function readFreezeCount(pc) {
    try {
      const stats = await pc.getStats();
      let freezes = null;
      stats.forEach((s) => {
        if (s.type === 'inbound-rtp' && s.kind === 'video' &&
            typeof s.freezeCount === 'number') {
          freezes = s.freezeCount;
        }
      });
      return freezes;
    } catch (e) {
      return null;
    }
  }

  // Marca el primer fotograma una sola vez por ejecución.
  function markFirstFrame(t) {
    if (!run || run.tFirstFrame != null) return;
    run.tFirstFrame = t;
    run.startupMs = t - run.t0;
    run.playing = true;
    console.log('[QoE] primer frame — startup =', r1(run.startupMs), 'ms');
    if (pcRef) {
      readFreezeCount(pcRef).then((f) => { run.baselineFreeze = f; });
    }
  }

  function onPlaying() { markFirstFrame(nowMs()); }

  function onWaiting() {
    if (!run || !run.playing) return;   // ignora el buffering inicial
    run.stallsWaiting += 1;
    console.log('[QoE] evento waiting #' + run.stallsWaiting +
                ' a t+' + r1((nowMs() - run.t0) / 1000) + ' s');
  }

  function toCSV(data) {
    const cols = ['timestamp', 'sistema', 'escenario', 'parametro', 'repeticion',
                  'startup_ms', 'stalls_count', 'duracion_s', 'stalls_per_min',
                  'fuente_stalls'];
    const cell = (v) => {
      if (v == null) return '';
      const s = String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const head = cols.join(',');
    const body = data.map((row) => cols.map((c) => cell(row[c])).join(',')).join('\n');
    return head + '\n' + body + (data.length ? '\n' : '');
  }

  const QoE = {
    // Engancha al <video>. pc es opcional (pásalo solo en el Proyecto 2).
    attach(videoEl, pc) {
      videoRef = videoEl || document.querySelector('video');
      pcRef = pc || null;
      if (!videoRef) {
        console.warn('[QoE] no se encontró ningún elemento <video>');
        return QoE;
      }
      videoRef.addEventListener('playing', onPlaying);
      videoRef.addEventListener('waiting', onWaiting);
      console.log('[QoE] enganchado a <video>' +
        (pcRef ? ' + RTCPeerConnection (modo WebRTC: freezeCount, fallback waiting)'
               : ' (modo HLS/nativo: eventos waiting)'));
      return QoE;
    },

    // Engancha a un reproductor Video.js (Proyecto 1). Usa los eventos del player,
    // que Video.js normaliza, y el <video> subyacente para precisión de primer
    // frame (requestVideoFrameCallback) cuando el navegador lo soporta.
    attachVideoJs(player) {
      vjsPlayer = player;
      pcRef = null;
      try { videoRef = player.el().querySelector('video'); } catch (e) { videoRef = null; }
      player.on('playing', onPlaying);
      player.on('waiting', onWaiting);
      console.log('[QoE] enganchado a Video.js player (eventos playing/waiting)' +
                  (videoRef ? ' + <video> para precisión de primer frame' : ''));
      return QoE;
    },

    // Llamar JUSTO antes de lanzar la reproducción (video.play() / fetch('/offer')).
    start(meta) {
      meta = meta || {};
      run = {
        sistema: meta.sistema || '',
        escenario: meta.escenario || '',
        parametro: meta.parametro || '',
        repeticion: (meta.repeticion != null) ? meta.repeticion : '',
        t0: nowMs(),
        tFirstFrame: null,
        startupMs: null,
        playing: false,
        stallsWaiting: 0,
        baselineFreeze: null,
      };
      // Precisión de primer frame si el navegador lo soporta (Chrome, Safari).
      if (typeof videoRef?.requestVideoFrameCallback === 'function') {
        videoRef.requestVideoFrameCallback(() => markFirstFrame(nowMs()));
      }
      console.log('[QoE] START', run.sistema, run.escenario, run.parametro,
                  'rep', run.repeticion, '— lanza la reproducción ahora');
    },

    // Llamar al cortar la toma. Registra una fila con los valores de la ejecución.
    async stop() {
      if (!run) { console.warn('[QoE] stop() llamado sin start()'); return null; }
      const durS = (nowMs() - run.t0) / 1000;

      let stalls = run.stallsWaiting;
      let fuente = 'waiting';
      if (pcRef) {
        const f = await readFreezeCount(pcRef);
        if (f != null && run.baselineFreeze != null) {
          stalls = Math.max(0, f - run.baselineFreeze);
          fuente = 'freezeCount';
        } else {
          console.warn('[QoE] freezeCount no disponible (usa Chrome para el Proyecto 2); ' +
                       'se usa el contador de eventos waiting como aproximación');
        }
      }

      const stallsPerMin = durS > 0 ? stalls / (durS / 60) : 0;
      const row = {
        timestamp: isoStamp(),
        sistema: run.sistema,
        escenario: run.escenario,
        parametro: run.parametro,
        repeticion: run.repeticion,
        startup_ms: (run.startupMs != null) ? r1(run.startupMs) : '',
        stalls_count: stalls,
        duracion_s: r1(durS),
        stalls_per_min: r2(stallsPerMin),
        fuente_stalls: fuente,
      };
      rows.push(row);
      console.log('[QoE] FILA REGISTRADA', row);
      console.log('[QoE] ' + rows.length + ' fila(s) acumuladas — ' +
                  'QoE.downloadCSV() para descargar, QoE.dumpCSV() para volcar a consola');
      run = null;
      return row;
    },

    // Vuelca el CSV completo a consola (para copiar y pegar).
    dumpCSV() {
      const csv = toCSV(rows);
      console.log('\n' + csv);
      return csv;
    },

    // Descarga el CSV completo como archivo.
    downloadCSV(filename) {
      const csv = toCSV(rows);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || ('qoe_' + Date.now() + '.csv');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      console.log('[QoE] descargado ' + a.download);
    },

    rows() { return rows.slice(); },
    reset() { rows.length = 0; console.log('[QoE] filas borradas'); },
  };

  window.QoE = QoE;
  console.log('[QoE] cargado. Video.js: QoE.attachVideoJs(player). Otros: QoE.attach(video[, pc]). ' +
              'Luego QoE.start({...}); ... await QoE.stop();');
})();
