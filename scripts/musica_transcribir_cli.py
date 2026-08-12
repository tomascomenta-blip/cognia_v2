# -*- coding: utf-8 -*-
"""CLI de transcripcion audio -> MIDI multi-pista (corre EN symphonygen312).

Contrato (patron musica_orquestar_cli.py): stdout = UNA linea JSON
{"ok": true, "midi": ..., "stems": [...], "seg": ...} o {"ok": false,
"error": ...} con exit != 0; TODO el progreso va a stderr.

Pipeline: Demucs (htdemucs) separa el audio en 4 stems (drums/bass/vocals/
other) y Basic Pitch (backend ONNX) transcribe CADA stem tonal por separado
-- transcribir la mezcla entera funde las voces; por stem sale un MIDI mucho
mas limpio y con las velocities del interprete. Los drums no son tonales:
Basic Pitch alucinaria pitches, asi que van por deteccion de onsets de
librosa mapeados a kick/caja/hihat por centroide espectral (suficiente para
darle el ritmo a song2song; no pretende ser una transcripcion de bateria).

POR QUE --sin-stems existe: para audio ya separado o mono-instrumental,
Demucs solo agrega minutos y VRAM; se transcribe el archivo directo.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# programs GM por stem: contrabajo para el bajo (registro orquestal), voz
# "oohs" para vocals, cuerdas para other (rol de armonia). song2song los
# re-mapea despues; esto solo deja el MIDI escuchable por si solo.
PROGRAM_POR_STEM = {"bass": 43, "vocals": 54, "other": 48}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _separar_stems(audio: Path, workdir: Path) -> dict[str, Path]:
    """Demucs htdemucs -> {stem: wav}. Baja el modelo al cache la 1a vez."""
    import torch
    from demucs.api import Separator, save_audio

    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    _log(f"[demucs] separando {audio.name} en {dispositivo}")
    sep = Separator(model="htdemucs", device=dispositivo, progress=True)
    _, stems = sep.separate_audio_file(str(audio))
    rutas = {}
    for nombre, tensor in stems.items():
        destino = workdir / f"{nombre}.wav"
        save_audio(tensor, str(destino), samplerate=sep.samplerate)
        rutas[nombre] = destino
    return rutas


def _grilla_beats(audio: Path):
    """Tiempos (seg) de los beats del audio COMPLETO, o None si no hay pulso.

    POR QUE: la transcripcion sale en segundos, pero SymphonyGen cuantiza a
    compases; sin mapear segundos -> beats reales, una cancion a 96 BPM
    entraria como sincopas sin sentido en la grilla implicita de 120. El
    mapeo es lineal a trozos entre beats consecutivos: beat i -> tick 480*i.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    if not float(np.abs(y).max() or 0):
        return None
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    if len(beats) < 8:
        return None
    _log(f"[beats] tempo estimado {float(np.atleast_1d(tempo)[0]):.1f} BPM, "
         f"{len(beats)} beats")
    return list(map(float, beats))


def _seg_a_tick(seg: float, beats, tpq: int) -> int:
    """Segundos -> ticks por interpolacion sobre la grilla de beats."""
    if not beats:
        return int(round(seg * 2 * tpq))  # 120 BPM implicito
    import bisect
    i = bisect.bisect_right(beats, seg) - 1
    if i < 0:
        frac = seg / beats[0] if beats[0] > 0 else 0.0
        return int(round(frac * tpq))
    if i >= len(beats) - 1:
        paso = beats[-1] - beats[-2]
        return int(round((len(beats) - 1 + (seg - beats[-1]) / paso) * tpq))
    frac = (seg - beats[i]) / (beats[i + 1] - beats[i])
    return int(round((i + frac) * tpq))


def _transcribir_tonal(wav: Path):
    """Basic Pitch sobre un stem tonal -> PrettyMIDI (con velocities)."""
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    _log(f"[basic-pitch] transcribiendo {wav.name}")
    _, midi_data, _ = predict(str(wav), model_or_model_path=ICASSP_2022_MODEL_PATH)
    return midi_data


def _transcribir_drums(wav: Path, tpq: int, beats=None):
    """Onsets de librosa -> notas de percusion GM (kick/caja/hihat).

    Clasificacion por centroide espectral alrededor del onset: grave=kick,
    medio=caja, agudo=hihat. Devuelve lista (tick, pitch_gm, velocity) con
    los ticks mapeados por la grilla de beats (fallback 120 BPM).
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    if not float(np.abs(y).max() or 0):
        return []
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
    fuerza = librosa.onset.onset_strength(y=y, sr=sr)
    tiempos_fuerza = librosa.times_like(fuerza, sr=sr)
    centroide = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    tiempos_cent = librosa.times_like(centroide, sr=sr)

    notas = []
    for t in onsets:
        c = float(np.interp(t, tiempos_cent, centroide))
        f = float(np.interp(t, tiempos_fuerza, fuerza))
        pitch = 36 if c < 1200 else (38 if c < 3200 else 42)
        vel = int(np.clip(60 + 40 * f / (fuerza.max() or 1), 40, 110))
        fusa = tpq // 8
        tick = round(_seg_a_tick(t, beats, tpq) / fusa) * fusa
        notas.append((tick, pitch, vel))
    return notas


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcripcion audio -> MIDI multi-pista")
    ap.add_argument("--audio", required=True, help="wav/mp3/flac/ogg de entrada")
    ap.add_argument("--salida", required=True, help="directorio de salida")
    ap.add_argument("--sin-stems", action="store_true",
                    help="sin Demucs: transcribe el archivo directo (mono-pista)")
    ap.add_argument("--sin-drums", action="store_true",
                    help="omite la pista de percusion")
    args = ap.parse_args()

    t0 = time.monotonic()
    audio = Path(args.audio).resolve()
    salida = Path(args.salida).resolve()
    salida.mkdir(parents=True, exist_ok=True)

    if not audio.is_file():
        print(json.dumps({"ok": False, "error": f"no existe el audio {audio}"},
                         ensure_ascii=False))
        return 1

    stdout_real = sys.stdout
    sys.stdout = sys.stderr  # demucs/librosa imprimen progreso: fuera del contrato
    try:
        import miditoolkit

        tpq = 480
        final = miditoolkit.MidiFile(ticks_per_beat=tpq)
        final.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
        stems_usados = []

        if args.sin_stems:
            stems = {"other": audio}
        else:
            stems = _separar_stems(audio, salida)

        # 1) transcribir TODO en segundos; 2) elegir la grilla DESPUES.
        # POR QUE: el beat tracker se equivoca con piezas ralas (visto en el
        # smoke: acordes en redondas -> tempo fantasma y recall 99%->21%).
        # La grilla no se cree, se ELIGE por error de cuantizacion medido:
        # gana la candidata (beats detectados vs 120 lineal) que deja los
        # onsets mas cerca de la grilla de fusas.
        transcritos = {}
        onsets_seg = []
        for nombre, wav in stems.items():
            if nombre == "drums":
                continue
            pm = _transcribir_tonal(wav)
            notas = [n for inst in pm.instruments for n in inst.notes]
            if not notas:
                _log(f"[stem {nombre}] sin notas, omitido")
                continue
            transcritos[nombre] = notas
            onsets_seg.extend(n.start for n in notas)

        candidatas = [("120bpm", None)]
        beats = _grilla_beats(audio)
        if beats:
            candidatas.append(("beats", beats))
        fusa = tpq // 8

        def _error_grilla(grilla):
            if not onsets_seg:
                return 1.0
            err = 0.0
            for s in onsets_seg:
                raw = _seg_a_tick(s, grilla, tpq)
                err += abs(raw - round(raw / fusa) * fusa) / fusa
            return err / len(onsets_seg)

        nombre_g, beats = min(candidatas, key=lambda c: _error_grilla(c[1]))
        _log(f"[grilla] elegida {nombre_g} "
             f"(error {_error_grilla(beats):.3f} en fusas)")

        for nombre, notas in transcritos.items():
            pista = miditoolkit.Instrument(
                program=PROGRAM_POR_STEM.get(nombre, 48), is_drum=False,
                name=nombre.capitalize())
            for n in notas:
                ini = round(_seg_a_tick(n.start, beats, tpq) / fusa) * fusa
                fin = max(ini + fusa, round(_seg_a_tick(n.end, beats, tpq) / fusa) * fusa)
                pista.notes.append(miditoolkit.Note(
                    int(max(1, min(127, n.velocity))), int(n.pitch), ini, fin))
            final.instruments.append(pista)
            stems_usados.append(nombre)

        if not args.sin_drums and "drums" in stems:
            golpes = _transcribir_drums(stems["drums"], tpq, beats)
            if golpes:
                bateria = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
                for tick, pitch, vel in golpes:
                    bateria.notes.append(miditoolkit.Note(vel, pitch, tick, tick + 60))
                final.instruments.append(bateria)
                stems_usados.append("drums")

        if not final.instruments:
            raise RuntimeError("ningun stem produjo notas (audio en silencio?)")

        destino = salida / f"{audio.stem}.transcrito.mid"
        final.dump(str(destino))
    except Exception:
        sys.stdout = stdout_real
        print(json.dumps({"ok": False, "error": traceback.format_exc()[-2000:]},
                         ensure_ascii=False))
        return 1
    finally:
        sys.stdout = stdout_real

    print(json.dumps({"ok": True, "midi": str(destino), "stems": stems_usados,
                      "seg": round(time.monotonic() - t0, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
