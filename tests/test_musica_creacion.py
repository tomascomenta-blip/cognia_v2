# -*- coding: utf-8 -*-
"""Tests de la linea de creacion musical: banco de monotonia, compositor
estructurado, backend de transcripcion (contrato, sin GPU) y song2song
(remapeo de paleta y groove, sin GPU).

POR QUE sinteticos: cada propiedad se verifica con MIDIs construidos aqui;
los caminos con Demucs/Basic Pitch/SymphonyGen reales se cubren en los e2e
manuales (GPU) y aqui solo su CONTRATO (subprocess mockeado, patron de
test_musica_expresividad)."""
from __future__ import annotations

from pathlib import Path

import miditoolkit
import pytest

from cognia.musica import song2song
from cognia.musica import transcripcion
from cognia.musica.banco_monotonia import medir, medir_lote
from cognia.musica.compositor import (CARACTERES, componer_esqueleto,
                                      texto_a_caracter)

TPQ = 480
COMPAS = TPQ * 4


def _pieza_clonada(ruta, compases=8):
    """El mismo compas repetido: el caso 'repite y repite el mismo ritmo'."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    v = miditoolkit.Instrument(program=40, is_drum=False, name="V")
    for c in range(compases):
        t = c * COMPAS
        for b in range(4):
            v.notes.append(miditoolkit.Note(100, 60, t + b * TPQ, t + b * TPQ + 400))
    midi.instruments = [v]
    midi.dump(str(ruta))
    return ruta


def _pieza_variada(ruta, compases=8):
    """Cada compas con patron ritmico DISTINTO (onsets desplazados)."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    v = miditoolkit.Instrument(program=40, is_drum=False, name="V")
    for c in range(compases):
        t = c * COMPAS
        # c+1 onsets en posiciones que dependen del compas: patron unico
        for k in range(1 + (c % 4)):
            pos = t + ((k * (c + 2) * 3) % 32) * (TPQ // 8)
            v.notes.append(miditoolkit.Note(100, 60 + c, pos, pos + 200))
    midi.instruments = [v]
    midi.dump(str(ruta))
    return ruta


def test_banco_detecta_clonado(tmp_path):
    m = medir(_pieza_clonada(tmp_path / "clon.mid"))
    assert m["rep_ritmo"] >= 0.99
    assert m["rep_melodia"] >= 0.99
    assert m["ent_ritmo"] == 0.0
    assert m["monotonia"] > 0.7


def test_banco_detecta_variedad(tmp_path):
    m = medir(_pieza_variada(tmp_path / "vario.mid"))
    assert m["rep_ritmo"] <= 0.15
    assert m["ent_ritmo"] > 0.5
    # el contraste clonado vs variado tiene que ser GRANDE: es el examen
    clon = medir(_pieza_clonada(tmp_path / "clon.mid"))
    assert clon["monotonia"] - m["monotonia"] > 0.3


def test_banco_lote_media(tmp_path):
    lote = medir_lote([_pieza_clonada(tmp_path / "a.mid"),
                       _pieza_variada(tmp_path / "b.mid")])
    assert len(lote["archivos"]) == 2
    esperado = (lote["archivos"][str(tmp_path / "a.mid")]["rep_ritmo"]
                + lote["archivos"][str(tmp_path / "b.mid")]["rep_ritmo"]) / 2
    assert abs(lote["media"]["rep_ritmo"] - esperado) < 1e-6


def test_compositor_determinista(tmp_path):
    a = componer_esqueleto("epica", tmp_path / "a.mid", semilla=3)
    b = componer_esqueleto("epica", tmp_path / "b.mid", semilla=3)
    c = componer_esqueleto("epica", tmp_path / "c.mid", semilla=4)
    assert (tmp_path / "a.mid").read_bytes() == (tmp_path / "b.mid").read_bytes()
    assert (tmp_path / "a.mid").read_bytes() != (tmp_path / "c.mid").read_bytes()
    assert a["bpm"] == CARACTERES["epica"]["bpm"]


def test_compositor_estructura_anti_monotonia(tmp_path):
    """El esqueleto estructurado NO puede ser un loop: rep_ritmo acotado y
    la seccion B tiene que diferir de la A (ese era el defecto original)."""
    for caracter in CARACTERES:
        ruta = tmp_path / f"{caracter}.mid"
        componer_esqueleto(caracter, ruta, compases=24, semilla=7)
        m = medir(ruta)
        assert m["rep_ritmo"] < 0.6, f"{caracter}: esqueleto en loop ({m})"
        midi = miditoolkit.MidiFile(str(ruta))
        melo = next(i for i in midi.instruments if i.name == "Melody")
        tercio = 8 * COMPAS
        notas_a = [(n.start % COMPAS, n.pitch) for n in melo.notes if n.start < tercio]
        notas_b = [(n.start % COMPAS, n.pitch) for n in melo.notes
                   if tercio <= n.start < 2 * tercio]
        assert notas_a != notas_b, f"{caracter}: la seccion B clona la A"


def test_texto_a_caracter():
    assert texto_a_caracter("una cancion EPICA de batalla") == "epica"
    assert texto_a_caracter("algo suave para dormir") == "calma"
    assert texto_a_caracter("melancolica y lluviosa") == "triste"
    assert texto_a_caracter("qwerty sin pistas") == "epica"


def test_transcribir_no_disponible_sin_venv(monkeypatch):
    monkeypatch.setenv("COGNIA_TRANSCRIBIR_PY", r"C:\no\existe\python.exe")
    ok, motivo = transcripcion.transcribir_disponible()
    assert not ok and "no existe" in motivo


def test_transcribir_contrato_json(tmp_path, monkeypatch):
    """El wrapper exige UNA linea JSON valida con ok/midi (patron backend)."""
    import subprocess

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFFxxxx")
    destino = tmp_path / "t.mid"
    _pieza_variada(destino)

    class _Popen:
        def __init__(self, cmd, **kw):
            self.returncode = 0

        def communicate(self, timeout=None):
            import json
            return json.dumps({"ok": True, "midi": str(destino),
                               "stems": ["other"]}), ""

        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", _Popen)
    assert transcripcion.transcribir(str(audio), str(tmp_path)) == str(destino)

    class _PopenRoto(_Popen):
        def communicate(self, timeout=None):
            return "no es json", ""

    monkeypatch.setattr(subprocess, "Popen", _PopenRoto)
    with pytest.raises(RuntimeError, match="stdout"):
        transcripcion.transcribir(str(audio), str(tmp_path))


def _generada(ruta, con_drums=False):
    """Pieza 'generada por SymphonyGen': melodia aguda, bajo grave, relleno."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    melo = miditoolkit.Instrument(program=40, is_drum=False, name="Track 0")
    bajo = miditoolkit.Instrument(program=42, is_drum=False, name="Track 1")
    rell = miditoolkit.Instrument(program=48, is_drum=False, name="Track 2")
    for c in range(8):
        t = c * COMPAS
        for b in range(4):
            melo.notes.append(miditoolkit.Note(90, 76 + (b * 2 + c) % 7,
                                               t + b * TPQ, t + b * TPQ + 400))
        bajo.notes.append(miditoolkit.Note(80, 40 + c % 5, t, t + COMPAS))
        for p in (55, 59, 62):
            rell.notes.append(miditoolkit.Note(70, p, t, t + 2 * TPQ))
    midi.instruments = [melo, bajo, rell]
    if con_drums:
        d = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
        d.notes.append(miditoolkit.Note(100, 36, 0, 60))
        midi.instruments.append(d)
    midi.dump(str(ruta))
    return ruta


def _transcrita_con_drums(ruta):
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    d = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
    for b in range(8):  # groove de 2 compases
        d.notes.append(miditoolkit.Note(100, 36 if b % 2 == 0 else 38,
                                        b * TPQ, b * TPQ + 60))
    v = miditoolkit.Instrument(program=54, is_drum=False, name="Vocals")
    v.notes.append(miditoolkit.Note(90, 70, 0, TPQ))
    midi.instruments = [d, v]
    midi.dump(str(ruta))
    return ruta


def test_song2song_remapea_paleta_por_rol(tmp_path):
    ruta = _generada(tmp_path / "g.mid")
    song2song._remapear_instrumentos(
        ruta, {"tiene_drums": False}, {"melodia": 52, "bajo": 43, "armonia": 48})
    m = miditoolkit.MidiFile(str(ruta))
    por_nombre = {i.name: i.program for i in m.instruments}
    assert por_nombre["Track 0"] == 52   # melodia
    assert por_nombre["Track 1"] == 43   # bajo
    assert por_nombre["Track 2"] == 48   # relleno


def test_song2song_quita_drums_si_original_no_tiene(tmp_path):
    ruta = _generada(tmp_path / "g.mid", con_drums=True)
    song2song._remapear_instrumentos(
        ruta, {"tiene_drums": False}, dict(song2song.PALETA_DEFAULT))
    assert not any(i.is_drum for i in miditoolkit.MidiFile(str(ruta)).instruments)


def test_song2song_importa_groove_en_loop(tmp_path):
    """Original CON bateria + generada SIN -> el groove transcrito se
    importa repetido hasta cubrir la pieza (replicar, no inventar)."""
    gen = _generada(tmp_path / "g.mid", con_drums=False)
    trans = _transcrita_con_drums(tmp_path / "t.mid")
    song2song._remapear_instrumentos(
        gen, {"tiene_drums": True}, dict(song2song.PALETA_DEFAULT),
        midi_trans=trans)
    m = miditoolkit.MidiFile(str(gen))
    drums = next(i for i in m.instruments if i.is_drum)
    fin = max(n.end for i in m.instruments if not i.is_drum for n in i.notes)
    assert len(drums.notes) > 8, "el groove no se repitio en loop"
    assert max(n.start for n in drums.notes) < fin
    assert max(n.end for n in drums.notes) <= fin
