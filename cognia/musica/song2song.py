# -*- coding: utf-8 -*-
"""song2song: de una cancion (audio) a una cancion NUEVA con su paleta.

Pipeline: transcribir (Demucs+Basic Pitch) -> SymphonyGen condicionado con
la ARMONIA de la cancion -> replica de la paleta instrumental por ROL ->
capa de expresividad.

Que significa "replica de instrumentos" en v1 (limite honesto): los stems
dan ROLES (bajo/voz/armonia/bateria), no timbres exactos -- identificar "es
una guitarra Stratocaster" pide un clasificador que no tenemos. La paleta
por defecto mapea rol->program GM evocador (voz->coro, bajo->contrabajo,
armonia->cuerdas) y el parametro `instrumentos` permite fijar cualquier
paleta a mano. Si la cancion original NO tiene bateria, la replica tampoco.

POR QUE la expresividad va DESPUES del remapeo y no en orquestar(): la capa
decide CC11 por program (solo sostenidos); remapear programs despues de
generados los CC dejaria expresion en instrumentos no elegibles. Por eso
orquestar() corre con COGNIA_MUSICA_EXPRESIVIDAD=0 y la capa se aplica al
final, ya con la paleta puesta.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

from cognia.musica import symphony_backend
from cognia.musica.expresividad import (_clasificar, _compases, _es_outline,
                                        aplicar_expresividad)
from cognia.musica.transcripcion import transcribir, transcribir_disponible

# paleta por defecto rol -> program GM (override con `instrumentos`)
PALETA_DEFAULT = {"melodia": 52, "bajo": 43, "armonia": 48}


def _perfil_instrumental(ruta_midi_trans) -> dict:
    """Perfil de la cancion original a partir de su transcripcion por stems."""
    import miditoolkit
    midi = miditoolkit.MidiFile(str(ruta_midi_trans))
    stems = {i.name.lower() for i in midi.instruments}
    return {
        "tiene_drums": any(i.is_drum for i in midi.instruments),
        "tiene_voz": "vocals" in stems,
        "tiene_bajo": "bass" in stems,
    }


def _rol_dominante(roles_pista) -> str:
    """Rol global de una pista = moda de sus roles por ventana."""
    cuentas = Counter(r for r in roles_pista if r)
    return cuentas.most_common(1)[0][0] if cuentas else "ACOMPANAMIENTO"


def _remapear_instrumentos(ruta_mid, perfil: dict, paleta: dict,
                           midi_trans=None) -> None:
    """Pone la paleta de la cancion original sobre la pieza generada.

    Clasifica roles con el MISMO clasificador de la capa de expresividad
    (una sola definicion de "melodia" en el repo) y reasigna programs por
    rol. Bateria segun el original: si NO tenia, se quita; si tenia y
    SymphonyGen no genero ninguna (es un modelo orquestal: casi nunca la
    genera), se importa el GROOVE TRANSCRITO del propio original, en loop
    hasta cubrir la pieza -- eso es replicar, no inventar.
    """
    import miditoolkit
    midi = miditoolkit.MidiFile(str(ruta_mid))

    if not perfil.get("tiene_drums", True):
        midi.instruments = [i for i in midi.instruments if not i.is_drum]
    elif midi_trans and not any(i.is_drum for i in midi.instruments):
        origen = miditoolkit.MidiFile(str(midi_trans))
        drums_orig = next((i for i in origen.instruments if i.is_drum), None)
        fin_pieza = max((n.end for i in midi.instruments for n in i.notes),
                        default=0)
        if drums_orig and drums_orig.notes and fin_pieza:
            patron = sorted(drums_orig.notes, key=lambda n: n.start)
            largo = max(n.end for n in patron)
            bateria = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
            offset = 0
            while offset < fin_pieza and largo > 0:
                for n in patron:
                    if offset + n.start >= fin_pieza:
                        break
                    bateria.notes.append(miditoolkit.Note(
                        n.velocity, n.pitch, offset + n.start,
                        min(offset + n.end, fin_pieza)))
                offset += largo
            midi.instruments.append(bateria)

    outs = [_es_outline(i) for i in midi.instruments]
    max_tick = max((n.end for i in midi.instruments for n in i.notes),
                   default=midi.ticks_per_beat * 4)
    compases = _compases(midi, max_tick)
    roles, _ = _clasificar(midi, compases, outs)

    for ip, inst in enumerate(midi.instruments):
        if inst.is_drum or outs[ip]:
            continue
        rol = _rol_dominante(roles[ip])
        if rol == "MELODIA":
            inst.program = paleta["melodia"]
        elif rol == "BAJO":
            inst.program = paleta["bajo"]
        else:  # CONTRAMELODIA / ACOMPANAMIENTO
            inst.program = paleta["armonia"]
    midi.dump(str(ruta_mid))


def song_to_song(audio: str, salida_dir: str, *, grupo: int = 2,
                 instrumentos: dict | None = None, sin_stems: bool = False,
                 timeout: float = 1800) -> list[str]:
    """Cancion (audio) -> canciones NUEVAS con la paleta del original.

    Devuelve las rutas .mid generadas (transcripcion en <salida>/original).
    Levanta RuntimeError con motivo legible si alguna etapa falla.
    """
    ok, motivo = transcribir_disponible()
    if not ok:
        raise RuntimeError(f"song2song: {motivo}")
    ok, motivo = symphony_backend.musica_disponible()
    if not ok:
        raise RuntimeError(f"song2song: {motivo}")

    salida = Path(salida_dir).resolve()
    salida.mkdir(parents=True, exist_ok=True)

    print(f"song2song: transcribiendo {Path(audio).name}", file=sys.stderr)
    midi_trans = transcribir(audio, str(salida / "original"),
                             sin_stems=sin_stems, timeout=timeout / 2)
    perfil = _perfil_instrumental(midi_trans)
    paleta = {**PALETA_DEFAULT, **(instrumentos or {})}
    if perfil["tiene_voz"]:
        paleta.setdefault("melodia", 52)

    # generar SIN expresividad (se aplica al final, ya con la paleta);
    # env restaurado SIEMPRE para no contaminar el proceso
    previo = os.environ.get("COGNIA_MUSICA_EXPRESIVIDAD")
    os.environ["COGNIA_MUSICA_EXPRESIVIDAD"] = "0"
    try:
        print("song2song: orquestando con la armonia de la cancion", file=sys.stderr)
        midis = symphony_backend.orquestar(midi_trans, str(salida), grupo=grupo,
                                           timeout=timeout / 2)
    finally:
        if previo is None:
            os.environ.pop("COGNIA_MUSICA_EXPRESIVIDAD", None)
        else:
            os.environ["COGNIA_MUSICA_EXPRESIVIDAD"] = previo

    for m in midis:
        _remapear_instrumentos(m, perfil, paleta, midi_trans=midi_trans)
        try:
            aplicar_expresividad(m)
        except Exception as e:
            # misma politica que el backend: la expresividad jamas rompe la
            # entrega; el remapeo ya quedo aplicado
            print(f"song2song: expresividad degradada en {Path(m).name}: {e}",
                  file=sys.stderr)
    return midis


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.song2song",
        description="Cancion (audio) -> cancion nueva con su paleta instrumental")
    ap.add_argument("audio", help="wav/mp3/flac de entrada")
    ap.add_argument("--salida", default="song2song_out", help="directorio de salida")
    ap.add_argument("--grupo", type=int, default=2, help="variaciones a generar")
    ap.add_argument("--sin-stems", action="store_true",
                    help="audio mono-instrumental: salta Demucs")
    args = ap.parse_args(argv)
    try:
        midis = song_to_song(args.audio, args.salida, grupo=args.grupo,
                             sin_stems=args.sin_stems)
    except RuntimeError as e:
        print(f"song2song: {e}", file=sys.stderr)
        return 1
    for m in midis:
        print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
