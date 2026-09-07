# -*- coding: utf-8 -*-
"""
cognia/agent/medios_tools.py
============================
Familias `audio_*` y `video_*` (2026-09-07): que el agente pueda COMPROBAR un
sonido o un video que genero, sin oidos ni ojos. Pedido del dueno: "mas
herramientas para probar sus propios resultados". Antes, un WAV escrito por el
agente solo se podia listar; ahora se mide: duracion, pico y RMS en dBFS,
porcentaje de silencio, clipping, silencio inicial/final; y un video se
inspecciona (ffprobe), se descompone en fotogramas rotulados (y se sabe si esta
congelado) o se arma desde PNGs.

Backends: ffmpeg/ffprobe (winget, pruebas_comun.binario los encuentra aunque no
esten en el PATH del shell), soundfile (wav/flac/ogg; para mp3 se convierte a
wav temporal con ffmpeg), numpy, matplotlib (Agg) para el espectrograma. Sin
alguno se dice cual y como instalarlo.
"""
from __future__ import annotations

import glob as _glob
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

from cognia.agent import pruebas_comun as _pc

_ULTIMO: dict = {"tool": "", "entrada": "", "salida": "", "detalle": "", "ts": 0.0}
_EXT_SOUNDFILE = (".wav", ".flac", ".ogg", ".aiff", ".aif")
_UMBRAL_SILENCIO_DB = -60.0
_VENTANA_S = 0.05


def _marcar(tool: str, entrada, salida="", detalle: str = "") -> None:
    _ULTIMO.update({"tool": tool, "entrada": str(entrada), "salida": str(salida or ""),
                    "detalle": detalle[:200], "ts": time.time()})


def ultimo() -> dict:
    return dict(_ULTIMO)


def _ruta(ruta, ctx=None):
    """Como pruebas_comun.resolver_ruta, pero mirando PRIMERO en el scratchpad
    de la tarea: las salidas de esta familia caen ahi, y el modelo las vuelve a
    nombrar en relativo ('prueba.wav'); sin esto, escribir y leer el mismo
    nombre daba 'no existe'."""
    f = (ruta or "").strip().strip("\"'")
    scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
    if f and scratch and not Path(f).is_absolute() and (Path(str(scratch)) / f).exists():
        return (Path(str(scratch)) / f).resolve()
    return _pc.resolver_ruta(f)


def _db(v: float) -> float:
    return 20.0 * math.log10(v) if v > 0 else -120.0


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------

def ffprobe_json(ruta) -> dict:
    exe = _pc.binario("ffprobe", "Instala ffmpeg: winget install Gyan.FFmpeg")
    code, out, err = _pc.correr([exe, "-v", "error", "-print_format", "json", "-show_format",
                                 "-show_streams", str(ruta)], timeout=60)
    if code != 0:
        raise ValueError("ffprobe no pudo leer %s: %s" % (Path(str(ruta)).name, (err or out).strip()[:200]))
    try:
        return json.loads(out or "{}")
    except Exception:
        raise ValueError("ffprobe devolvio algo que no es JSON para %s" % Path(str(ruta)).name)


def _fps(stream: dict) -> float:
    for k in ("avg_frame_rate", "r_frame_rate"):
        v = stream.get(k, "")
        m = re.match(r"^(\d+)/(\d+)$", str(v))
        if m and int(m.group(2)):
            f = int(m.group(1)) / int(m.group(2))
            if f > 0:
                return round(f, 3)
    return 0.0


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def _leer_muestras(p: Path):
    """(muestras float32 mono, sample_rate) via soundfile; mp3 y otros pasan
    por ffmpeg a un wav temporal."""
    sf = _pc.importar("soundfile")
    np = _pc.importar("numpy")
    fuente = p
    tmp = None
    if p.suffix.lower() not in _EXT_SOUNDFILE:
        exe = _pc.binario("ffmpeg", "Instala ffmpeg: winget install Gyan.FFmpeg")
        fd, tmp = tempfile.mkstemp(prefix="cognia_audio_", suffix=".wav")
        os.close(fd)
        code, _, err = _pc.correr([exe, "-v", "error", "-y", "-i", str(p), "-ac", "1", tmp], timeout=120)
        if code != 0:
            raise ValueError("ffmpeg no pudo convertir %s: %s" % (p.name, err.strip()[:200]))
        fuente = Path(tmp)
    try:
        datos, sr = sf.read(str(fuente), dtype="float32", always_2d=True)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    mono = datos.mean(axis=1) if datos.shape[1] > 1 else datos[:, 0]
    return np.asarray(mono, dtype="float32"), int(sr)


def analizar_audio(p: Path) -> dict:
    np = _pc.importar("numpy")
    x, sr = _leer_muestras(p)
    n = len(x)
    info = {"muestras": n, "sample_rate": sr, "duracion_s": round(n / float(sr), 3) if sr else 0.0}
    if n == 0:
        info.update({"pico_db": -120.0, "rms_db": -120.0, "silencio_pct": 100.0, "clipping_pct": 0.0,
                     "silencio_inicial_ms": 0, "silencio_final_ms": 0, "veredicto": "VACIO: cero muestras"})
        return info
    pico = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x.astype("float64") ** 2)))
    info["pico_db"] = round(_db(pico), 1)
    info["rms_db"] = round(_db(rms), 1)
    clip = float(np.mean(np.abs(x) >= 0.999)) * 100.0
    info["clipping_pct"] = round(clip, 3)
    ven = max(1, int(sr * _VENTANA_S))
    nv = n // ven
    if nv >= 1:
        bloques = x[:nv * ven].reshape(nv, ven).astype("float64")
        rms_v = np.sqrt(np.mean(bloques ** 2, axis=1))
        callado = rms_v < (10 ** (_UMBRAL_SILENCIO_DB / 20.0))
        info["silencio_pct"] = round(float(np.mean(callado)) * 100.0, 1)
        ini = 0
        while ini < nv and callado[ini]:
            ini += 1
        fin = 0
        while fin < nv - ini and callado[nv - 1 - fin]:
            fin += 1
        info["silencio_inicial_ms"] = int(ini * _VENTANA_S * 1000)
        info["silencio_final_ms"] = int(fin * _VENTANA_S * 1000)
    else:
        info["silencio_pct"] = 100.0 if pico < 1e-3 else 0.0
        info["silencio_inicial_ms"] = info["silencio_final_ms"] = 0
    if info["silencio_pct"] >= 99.5 or info["pico_db"] <= _UMBRAL_SILENCIO_DB:
        info["veredicto"] = "SILENCIO total: no suena nada"
    elif clip > 0.1:
        info["veredicto"] = "CLIPPING (%.2f%% de muestras saturadas): distorsiona" % clip
    elif info["rms_db"] < -40:
        info["veredicto"] = "muy bajo (RMS %.1f dBFS): apenas se oye" % info["rms_db"]
    else:
        info["veredicto"] = "OK"
    return info


def audio_inspeccionar(ruta: str, ctx=None) -> str:
    p = _ruta(ruta, ctx)
    partes = []
    try:
        pj = ffprobe_json(p)
        fmt = pj.get("format", {})
        a = next((s for s in pj.get("streams", []) if s.get("codec_type") == "audio"), None)
        if a is None:
            raise ValueError("%s no tiene stream de audio" % p.name)
        partes.append("%s %s Hz %s canal(es), %s s, %s" % (
            a.get("codec_name", "?"), a.get("sample_rate", "?"), a.get("channels", "?"),
            fmt.get("duration", "?")[:6] if isinstance(fmt.get("duration"), str) else fmt.get("duration", "?"),
            fmt.get("format_name", "")))
    except ValueError as exc:
        # sin ffprobe el analisis de muestras sigue valiendo para wav/flac
        if "stream de audio" in str(exc):
            raise
        partes.append("(ffprobe no disponible: %s)" % str(exc)[:80])
    info = analizar_audio(p)
    partes.append("pico %.1f dBFS · RMS %.1f dBFS · silencio %.1f%% · clipping %.2f%%"
                  % (info["pico_db"], info["rms_db"], info["silencio_pct"], info["clipping_pct"]))
    if info.get("silencio_inicial_ms") or info.get("silencio_final_ms"):
        partes.append("silencio al inicio %d ms, al final %d ms" % (info["silencio_inicial_ms"], info["silencio_final_ms"]))
    partes.append("duracion medida %.3f s" % info["duracion_s"])
    partes.append(info["veredicto"])
    _marcar("audio_inspeccionar", p, "", info["veredicto"])
    return " · ".join(partes)


def audio_espectrograma(ruta: str, salida: str = "", ctx=None) -> str:
    p = _ruta(ruta, ctx)
    mpl = _pc.importar("matplotlib")
    mpl.use("Agg")
    plt = _pc.importar("matplotlib.pyplot")
    np = _pc.importar("numpy")
    x, sr = _leer_muestras(p)
    if len(x) == 0:
        raise ValueError("%s no tiene muestras" % p.name)
    png = _pc.ruta_salida(ctx, "espectro_" + p.stem, ".png", salida)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6), dpi=80)
    t = np.arange(len(x)) / float(sr)
    a1.plot(t, x, linewidth=0.5)
    a1.set_ylim(-1, 1)
    a1.set_title("forma de onda: %s (%.2f s, %d Hz)" % (p.name, len(x) / float(sr), sr))
    nfft = 1024 if len(x) >= 1024 else max(16, 1 << (len(x).bit_length() - 1))
    a2.specgram(x, NFFT=nfft, Fs=sr, noverlap=nfft // 2, cmap="magma")
    a2.set_xlabel("s")
    a2.set_ylabel("Hz")
    fig.tight_layout()
    fig.savefig(str(png))
    plt.close(fig)
    info = _pc.resumen_imagen(png)
    _marcar("audio_espectrograma", p, png, "")
    return "espectrograma + onda en %s · %s" % (png, _pc.texto_resumen_imagen(info))


def audio_generar_prueba(ruta: str, hz: float = 440.0, segundos: float = 1.0, amplitud: float = 0.5, ctx=None) -> str:
    np = _pc.importar("numpy")
    sf = _pc.importar("soundfile")
    # Salida RELATIVA al scratchpad de la tarea (como `salida=` en renderizar):
    # escribirla en el cwd del proceso la dejaba donde el modelo no la busca.
    p = _pc.ruta_salida(ctx, "tono", ".wav", ruta)
    if p.suffix.lower() != ".wav":
        p = p.with_suffix(".wav")
    sr = 44100
    segundos = max(0.05, min(60.0, float(segundos)))
    t = np.arange(int(sr * segundos)) / float(sr)
    y = (float(amplitud) * np.sin(2 * math.pi * float(hz) * t)).astype("float32")
    sf.write(str(p), y, sr)
    _marcar("audio_generar_prueba", p, p, "%s Hz %.2f s" % (hz, segundos))
    return "tono de %s Hz, %.2f s, amplitud %.2f escrito en %s (%d Hz mono)" % (hz, segundos, amplitud, p, sr)


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

def _info_video(p: Path) -> dict:
    pj = ffprobe_json(p)
    fmt = pj.get("format", {})
    v = next((s for s in pj.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in pj.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = 0.0
    for cand in (fmt.get("duration"), (v or {}).get("duration")):
        try:
            dur = float(cand)
            break
        except (TypeError, ValueError):
            continue
    # gif: ffprobe suele no traer duration en format; se estima por nb_frames/fps
    if dur == 0.0 and v:
        try:
            nb = int(v.get("nb_frames", 0))
            f = _fps(v)
            if nb and f:
                dur = nb / f
        except (TypeError, ValueError):
            pass
    info = {"duracion_s": round(dur, 3), "formato": fmt.get("format_name", ""),
            "bytes": int(fmt.get("size", 0) or 0), "bitrate": int(fmt.get("bit_rate", 0) or 0),
            "streams": len(pj.get("streams", [])), "video": None, "audio": None}
    if v:
        info["video"] = {"codec": v.get("codec_name", "?"), "ancho": int(v.get("width", 0) or 0),
                         "alto": int(v.get("height", 0) or 0), "fps": _fps(v),
                         "fotogramas": int(v.get("nb_frames", 0) or 0)}
    if a:
        info["audio"] = {"codec": a.get("codec_name", "?"), "sample_rate": a.get("sample_rate", "?"),
                         "canales": a.get("channels", "?")}
    if not v:
        info["veredicto"] = "SIN stream de video"
    elif dur <= 0:
        info["veredicto"] = "duracion 0: video vacio o corrupto"
    elif info["video"]["ancho"] == 0:
        info["veredicto"] = "sin resolucion: stream roto"
    else:
        info["veredicto"] = "OK"
    return info


def video_inspeccionar(ruta: str, ctx=None) -> str:
    p = _ruta(ruta, ctx)
    info = _info_video(p)
    partes = ["%s, %.3f s, %d bytes" % (info["formato"], info["duracion_s"], info["bytes"])]
    if info["video"]:
        v = info["video"]
        partes.append("video %s %dx%d %.3g fps%s" % (v["codec"], v["ancho"], v["alto"], v["fps"],
                                                      (", %d fotogramas" % v["fotogramas"]) if v["fotogramas"] else ""))
    if info["audio"]:
        a = info["audio"]
        partes.append("audio %s %s Hz %s ch" % (a["codec"], a["sample_rate"], a["canales"]))
    else:
        partes.append("sin audio")
    if info["bitrate"]:
        partes.append("%d kb/s" % (info["bitrate"] // 1000))
    partes.append("%d stream(s)" % info["streams"])
    partes.append(info["veredicto"])
    _marcar("video_inspeccionar", p, "", info["veredicto"])
    return " · ".join(partes)


def video_fotogramas(ruta: str, n: int = 6, salida: str = "", ctx=None) -> str:
    p = _ruta(ruta, ctx)
    exe = _pc.binario("ffmpeg", "Instala ffmpeg: winget install Gyan.FFmpeg")
    info = _info_video(p)
    if not info["video"]:
        raise ValueError("%s no tiene video" % p.name)
    n = _pc.entero(n, 6, 2, 24)
    dur = info["duracion_s"]
    carpeta = _pc.carpeta_salida(ctx) / ("fotogramas_%s_%s" % (re.sub(r"[^A-Za-z0-9_-]", "_", p.stem)[:30], time.strftime("%H%M%S")))
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas, etiquetas = [], []
    if dur > 0:
        tiempos = [dur * i / float(n) for i in range(n)]
        # el ultimo instante exacto suele caer detras del ultimo fotograma: se retrocede un poco
        tiempos[-1] = max(0.0, min(tiempos[-1], dur - 0.02))
    else:
        tiempos = [0.0] * n
    for i, t in enumerate(tiempos):
        destino = carpeta / ("f%02d.png" % i)
        code, _, err = _pc.correr([exe, "-v", "error", "-y", "-ss", "%.3f" % t, "-i", str(p),
                                   "-frames:v", "1", str(destino)], timeout=60)
        if code != 0 or not destino.exists():
            # fotogramas mas alla del final (duracion estimada de mas): se para ahi
            if rutas:
                break
            raise ValueError("ffmpeg no saco el fotograma en t=%.2f: %s" % (t, err.strip()[:160]))
        rutas.append(destino)
        etiquetas.append("t=%.2fs" % t)
    cambios = []
    for a, b in zip(rutas, rutas[1:]):
        cambios.append(_pc.fraccion_cambio(a, b))
    png = _pc.ruta_salida(ctx, "fotogramas_" + p.stem, ".png", salida)
    _pc.mosaico(rutas, png, etiquetas=etiquetas)
    validos = [c for c in cambios if c >= 0]
    if validos and max(validos) < 0.001:
        veredicto = "CONGELADO: ningun fotograma cambia"
    elif validos:
        veredicto = "se mueve: cambio entre fotogramas %s" % ", ".join("%.1f%%" % (c * 100) for c in validos)
    else:
        veredicto = "un solo fotograma"
    _marcar("video_fotogramas", p, png, veredicto)
    return "%d fotogramas de %s en %s (sueltos en %s) · %s" % (len(rutas), p.name, png, carpeta, veredicto)


def video_crear(patron: str, salida: str, fps: int = 10, ctx=None) -> str:
    exe = _pc.binario("ffmpeg", "Instala ffmpeg: winget install Gyan.FFmpeg")
    fps = _pc.entero(fps, 10, 1, 60)
    spec = (patron or "").strip().strip("\"'")
    rutas: list = []
    try:
        p = _ruta(spec, ctx)
        if p.is_dir():
            rutas = sorted(q for q in p.iterdir() if q.suffix.lower() in (".png", ".jpg", ".jpeg"))
        else:
            rutas = [p]
    except ValueError:
        scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
        for base in ([Path(str(scratch))] if scratch else []) + _pc.bases_relativas():
            rutas += [Path(h) for h in _glob.glob(str(base / spec))]
        rutas = sorted(set(rutas))
    if len(rutas) < 1:
        raise ValueError("ningun fotograma en: %s" % spec)
    destino = _pc.ruta_salida(ctx, "video", Path(salida).suffix or ".mp4", salida)
    ext = destino.suffix.lower()
    if ext not in (".mp4", ".gif"):
        raise ValueError("la salida tiene que ser .mp4 o .gif")
    # lista concat: rutas con cualquier nombre, en el orden elegido
    fd, lista = tempfile.mkstemp(prefix="cognia_concat_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in rutas:
            fh.write("file '%s'\nduration %.4f\n" % (str(r).replace("'", "'\\''"), 1.0 / fps))
        fh.write("file '%s'\n" % str(rutas[-1]).replace("'", "'\\''"))
    try:
        base_cmd = [exe, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista]
        if ext == ".mp4":
            cmd = base_cmd + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=%d" % fps, "-c:v", "libx264",
                              "-pix_fmt", "yuv420p", "-r", str(fps), str(destino)]
        else:
            cmd = base_cmd + ["-vf", "fps=%d,split[a][b];[a]palettegen[p];[b][p]paletteuse" % fps,
                              "-loop", "0", str(destino)]
        code, _, err = _pc.correr(cmd, timeout=180)
    finally:
        try:
            os.unlink(lista)
        except OSError:
            pass
    if code != 0 or not destino.exists():
        raise ValueError("ffmpeg fallo al crear %s: %s" % (destino.name, err.strip()[:200]))
    _marcar("video_crear", spec, destino, "%d fotogramas a %d fps" % (len(rutas), fps))
    return "%s creado con %d fotogramas a %d fps · %s" % (destino, len(rutas), fps, video_inspeccionar(str(destino), ctx=ctx))


def medios_estado() -> str:
    partes = []
    for b in ("ffmpeg", "ffprobe"):
        try:
            partes.append("%s: %s" % (b, _pc.binario(b)))
        except ValueError:
            partes.append("%s: NO (winget install Gyan.FFmpeg)" % b)
    for m in ("soundfile", "numpy", "matplotlib"):
        try:
            _pc.importar(m)
            partes.append("%s: si" % m)
        except ValueError:
            partes.append("%s: NO (pip install %s)" % (m, _pc._PIP.get(m, m)))
    u = ultimo()
    if u.get("tool"):
        partes.append("ultimo: %s %s -> %s %s" % (u["tool"], u["entrada"], u["salida"] or "-", u["detalle"]))
    return " · ".join(partes)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def _envolver(nombre, fn):
    def _t(args, ctx):
        try:
            return "RESULTADO %s: %s" % (nombre, fn(args, ctx))
        except ValueError as exc:
            return "RESULTADO %s ERROR: %s" % (nombre, exc)
        except Exception as exc:
            return "RESULTADO %s ERROR: %s: %s" % (nombre, type(exc).__name__, str(exc)[:200])
    _t.__name__ = "_t_" + nombre
    return _t


def _p(nombre, tipo, desc, requerido=False, clave=False):
    d = {"nombre": nombre, "tipo": tipo, "requerido": requerido, "descripcion": desc}
    if clave:
        d["clave"] = True
    return d


def register(tool) -> None:
    tool("audio_inspeccionar",
         "audio_inspeccionar <ruta>            -- mide un audio: duracion, Hz, canales, pico/RMS dBFS, % silencio, clipping",
         desc="Analiza un fichero de audio (wav/flac/ogg directo; mp3 y otros via ffmpeg): formato, sample "
              "rate, canales, duracion; pico y RMS en dBFS, porcentaje de silencio, silencio al inicio y al "
              "final, clipping; y un VEREDICTO: SILENCIO total, muy bajo, CLIPPING u OK. Usala para "
              "comprobar que un sonido que generaste suena de verdad y no es un fichero vacio.",
         params=[_p("ruta", "string", "fichero de audio", True)],
         timeout_s=120)(_envolver("audio_inspeccionar", lambda a, c: audio_inspeccionar(_pc.partir_args(a, [])[0], ctx=c)))

    def _esp(a, ctx):
        obj, o = _pc.partir_args(a, ["salida"])
        if not obj:
            raise ValueError("uso: audio_espectrograma <ruta> [| salida=X.png]")
        return audio_espectrograma(obj, salida=o.get("salida", ""), ctx=ctx)
    tool("audio_espectrograma",
         "audio_espectrograma <ruta> [| salida=X.png]  -- dibuja la forma de onda y el espectrograma en un PNG",
         desc="Genera un PNG con la forma de onda y el espectrograma del audio (matplotlib), para VER si hay "
              "sonido, donde, y en que frecuencias (un tono limpio es una linea; ruido es una mancha).",
         params=[_p("ruta", "string", "fichero de audio", True), _p("salida", "string", "ruta del PNG", clave=True)],
         timeout_s=120)(_envolver("audio_espectrograma", _esp))

    def _gen(a, ctx):
        obj, o = _pc.partir_args(a, ["hz", "segundos", "amplitud"])
        if not obj:
            raise ValueError("uso: audio_generar_prueba <ruta.wav> [| hz=440] [| segundos=1]")
        try:
            hz = float(o.get("hz") or 440)
            seg = float(o.get("segundos") or 1)
            amp = float(o.get("amplitud") or 0.5)
        except ValueError:
            raise ValueError("hz, segundos y amplitud tienen que ser numeros")
        return audio_generar_prueba(obj, hz=hz, segundos=seg, amplitud=max(0.0, min(1.0, amp)), ctx=ctx)
    tool("audio_generar_prueba",
         "audio_generar_prueba <ruta.wav> [| hz=440] [| segundos=1] [| amplitud=0.5]  -- escribe un tono de prueba",
         desc="Escribe un WAV con un tono senoidal (44100 Hz mono) para probar la cadena de audio de un "
              "programa o tener una referencia conocida con la que comparar.",
         params=[_p("ruta", "string", "ruta del wav a escribir", True),
                 _p("hz", "number", "frecuencia (default 440)", clave=True),
                 _p("segundos", "number", "duracion (default 1)", clave=True),
                 _p("amplitud", "number", "0..1 (default 0.5 = -6 dBFS)", clave=True)],
         timeout_s=30)(_envolver("audio_generar_prueba", _gen))

    tool("video_inspeccionar",
         "video_inspeccionar <ruta>            -- ffprobe: duracion, resolucion, fps, codecs, streams; vacio o roto",
         desc="Inspecciona un video o GIF con ffprobe: duracion, resolucion, fps, codec de video y audio, "
              "numero de streams, tamano y bitrate, con VEREDICTO (OK, sin stream de video, duracion 0). "
              "Para saber si el video que generaste existe de verdad y tiene contenido.",
         params=[_p("ruta", "string", "fichero de video o gif", True)],
         timeout_s=60)(_envolver("video_inspeccionar", lambda a, c: video_inspeccionar(_pc.partir_args(a, [])[0], ctx=c)))

    def _fot(a, ctx):
        obj, o = _pc.partir_args(a, ["n", "salida"])
        if not obj:
            raise ValueError("uso: video_fotogramas <ruta> [| n=6] [| salida=X.png]")
        return video_fotogramas(obj, n=_pc.entero(o.get("n"), 6, 2, 24), salida=o.get("salida", ""), ctx=ctx)
    tool("video_fotogramas",
         "video_fotogramas <ruta> [| n=6] [| salida=X.png]  -- saca N fotogramas repartidos en un mosaico rotulado y dice si el video esta congelado",
         desc="Extrae N fotogramas repartidos a lo largo del video (ffmpeg), los junta en un mosaico con su "
              "instante y mide cuanto cambia cada uno respecto al anterior: si nada cambia, el video esta "
              "CONGELADO. Sirve para ver una animacion o una grabacion sin reproducirla.",
         params=[_p("ruta", "string", "video o gif", True), _p("n", "integer", "fotogramas (2-24, default 6)", clave=True),
                 _p("salida", "string", "ruta del PNG del mosaico", clave=True)],
         timeout_s=240)(_envolver("video_fotogramas", _fot))

    def _cre(a, ctx):
        obj, o = _pc.partir_args(a, ["fps"])
        partes = [t.strip() for t in obj.split("|") if t.strip()]
        if len(partes) != 2:
            raise ValueError("uso: video_crear <patron o directorio> | <salida.mp4|.gif> [| fps=10]")
        return video_crear(partes[0], partes[1], fps=_pc.entero(o.get("fps"), 10, 1, 60), ctx=ctx)
    tool("video_crear",
         "video_crear <patron o directorio> | <salida.mp4|.gif> [| fps=10]  -- une fotogramas PNG en un mp4 o gif",
         desc="Junta imagenes (glob como frames/*.png, o un directorio, en orden de nombre) en un MP4 "
              "(h264, compatible) o un GIF con paleta, a fps dados, y devuelve la inspeccion del resultado. "
              "Para convertir una secuencia de capturas en algo que se pueda ver.",
         params=[_p("fotogramas", "string", "glob o directorio con los PNG", True),
                 _p("salida", "string", "ruta .mp4 o .gif", True),
                 _p("fps", "integer", "fotogramas por segundo (default 10)", clave=True)],
         timeout_s=240)(_envolver("video_crear", _cre))

    tool("medios_estado",
         "medios_estado                         -- que backends de audio/video hay (ffmpeg, ffprobe, soundfile, matplotlib)",
         desc="Dice que hay instalado para audio y video (ffmpeg, ffprobe, soundfile, numpy, matplotlib) y "
              "la ultima operacion de la familia. Usala si una tool de audio/video falla por dependencia.",
         params=[],
         timeout_s=30)(_envolver("medios_estado", lambda a, c: medios_estado()))


NOMBRES = ("audio_inspeccionar", "audio_espectrograma", "audio_generar_prueba",
           "video_inspeccionar", "video_fotogramas", "video_crear", "medios_estado")
