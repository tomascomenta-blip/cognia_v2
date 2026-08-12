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
from cognia.musica.compositor import (CARACTERES, GENEROS, componer_esqueleto,
                                      componer_genero, texto_a_caracter,
                                      texto_a_esqueleto)

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


def _solapes(notas):
    """Pares de notas consecutivas que se pisan dentro de una pista."""
    notas = sorted(notas, key=lambda n: n.start)
    return [(a, b) for a, b in zip(notas, notas[1:]) if b.start < a.end]


def test_celdas_ocupan_cuatro_negras():
    """Cada celda ritmica ocupa 4 negras (el 0 cuenta 1 de silencio): una
    celda de 5 planta su ultima nota en el compas siguiente y la melodia
    queda con dos notas simultaneas (bug real: [2,1,0,1] sumaba 5)."""
    from cognia.musica.compositor import _CELDAS
    for celda in _CELDAS:
        assert sum(d if d else 1 for d in celda) == 4, celda
    for genero, conf in GENEROS.items():
        for celda in conf["celdas"]:
            assert sum(d if d else 1 for d in celda) == 4, (genero, celda)


def test_melodia_monofonica_sin_solapes(tmp_path):
    """La pista de melodia (y la contra) es monofonica: ninguna nota puede
    pisar a la siguiente. Con las celdas de 5 negras habia 4 solapes por
    pieza (nota en el downbeat del compas siguiente contra la primera de
    ese compas, hasta a la MISMA altura en electro)."""
    for semilla in (0, 7):
        for caracter in CARACTERES:
            ruta = tmp_path / f"e_{caracter}_{semilla}.mid"
            componer_esqueleto(caracter, ruta, compases=24, semilla=semilla)
            midi = miditoolkit.MidiFile(str(ruta))
            melo = next(i for i in midi.instruments if i.name == "Melody")
            assert not _solapes(melo.notes), (caracter, semilla)
        for genero in GENEROS:
            ruta = tmp_path / f"g_{genero}_{semilla}.mid"
            componer_genero(genero, ruta, compases=24, semilla=semilla)
            midi = miditoolkit.MidiFile(str(ruta))
            for nombre in ("Melody", "Contra"):
                pista = next(i for i in midi.instruments if i.name == nombre)
                assert not _solapes(pista.notes), (genero, nombre, semilla)


def test_esqueleto_seccion_b_misma_tonalidad(tmp_path):
    """La armonia de B no introduce clases de altura fuera de las que las
    progresiones del caracter producen en la tonalidad ORIGINAL: el viejo
    'al relativo' sumaba +-3 cromatico a las raices (do# en do mayor)
    mientras la melodia seguia snapeada a la escala original."""
    tercio = 8 * COMPAS
    for caracter, conf in CARACTERES.items():
        permitidas = {(conf["tonica"] + grado + iv) % 12
                      for prog in conf["progresiones"]
                      for grado, triada in prog for iv in triada}
        ruta = tmp_path / f"b_{caracter}.mid"
        componer_esqueleto(caracter, ruta, compases=24, semilla=0)
        midi = miditoolkit.MidiFile(str(ruta))
        armo = next(i for i in midi.instruments if i.name == "Piano")
        clases_b = {n.pitch % 12 for n in armo.notes
                    if tercio <= n.start < 2 * tercio}
        assert clases_b <= permitidas, (
            f"{caracter}: B mete clases foraneas {sorted(clases_b - permitidas)}")


def test_esqueleto_escribe_tempo(tmp_path):
    """El bpm del caracter va AL ARCHIVO (TempoChange), no solo al dict:
    sin el, cualquier render directo del esqueleto suena a 120 mientras la
    metadata declara 72/100/... (componer_genero ya lo hacia bien)."""
    for caracter, conf in CARACTERES.items():
        ruta = tmp_path / f"t_{caracter}.mid"
        meta = componer_esqueleto(caracter, ruta, compases=12, semilla=1)
        midi = miditoolkit.MidiFile(str(ruta))
        assert midi.tempo_changes, f"{caracter}: sin TempoChange"
        assert midi.tempo_changes[0].tempo == pytest.approx(conf["bpm"])
        assert meta["bpm"] == conf["bpm"]


def test_texto_a_caracter():
    assert texto_a_caracter("una cancion EPICA de batalla") == "epica"
    assert texto_a_caracter("algo suave para dormir") == "calma"
    assert texto_a_caracter("melancolica y lluviosa") == "triste"
    assert texto_a_caracter("qwerty sin pistas") == "epica"


def test_genero_determinista(tmp_path):
    """Mismo genero y semilla -> bytes identicos; otra semilla -> otros."""
    for genero in GENEROS:
        a = componer_genero(genero, tmp_path / f"{genero}_a.mid", semilla=5)
        componer_genero(genero, tmp_path / f"{genero}_b.mid", semilla=5)
        componer_genero(genero, tmp_path / f"{genero}_c.mid", semilla=6)
        ba = (tmp_path / f"{genero}_a.mid").read_bytes()
        assert ba == (tmp_path / f"{genero}_b.mid").read_bytes(), genero
        assert ba != (tmp_path / f"{genero}_c.mid").read_bytes(), genero
        assert a["bpm"] == GENEROS[genero]["bpm"]
        assert a["genero"] == genero


def test_genero_drums_y_paleta(tmp_path):
    """Cada genero trae bateria GM (is_drum) y su paleta de programas; el
    cowbell 56 es obligatorio en phonk (es el gancho del genero)."""
    for genero, conf in GENEROS.items():
        ruta = tmp_path / f"{genero}.mid"
        componer_genero(genero, ruta, semilla=2)
        midi = miditoolkit.MidiFile(str(ruta))
        drums = [i for i in midi.instruments if i.is_drum]
        assert len(drums) == 1 and drums[0].notes, f"{genero}: sin bateria"
        por_nombre = {i.name: i.program for i in midi.instruments
                      if not i.is_drum}
        pal = conf["paleta"]
        assert por_nombre["Melody"] == pal["melodia"], genero
        assert por_nombre["Contra"] == pal["contra"], genero
        assert por_nombre["Chords"] == pal["armonia"], genero
        assert por_nombre["Bass"] == pal["bajo"], genero
        if genero == "phonk":
            assert any(n.pitch == 56 for n in drums[0].notes), "sin cowbell"


def test_genero_anti_monotonia(tmp_path):
    """El arreglo completo no puede ser un loop: mismo listen del esqueleto
    (rep_ritmo < 0.6 con el banco), ahora con bajo y bateria incluidos."""
    for genero in GENEROS:
        ruta = tmp_path / f"{genero}.mid"
        componer_genero(genero, ruta, compases=24, semilla=7)
        m = medir(ruta)
        assert m["rep_ritmo"] < 0.6, f"{genero}: arreglo en loop ({m})"


def test_genero_seccion_b_distinta(tmp_path):
    """B tiene que mutar respecto de A (progresion/registro/celdas) y en
    phonk/electro la bateria de B pierde piezas (drop/breakdown)."""
    tercio = 8 * COMPAS
    for genero in GENEROS:
        ruta = tmp_path / f"{genero}.mid"
        componer_genero(genero, ruta, compases=24, semilla=3)
        midi = miditoolkit.MidiFile(str(ruta))
        tonales = [n for i in midi.instruments if not i.is_drum
                   for n in i.notes]
        a = sorted((n.start % COMPAS, n.pitch) for n in tonales
                   if n.start < tercio)
        b = sorted((n.start % COMPAS, n.pitch) for n in tonales
                   if tercio <= n.start < 2 * tercio)
        assert a != b, f"{genero}: la seccion B clona la A"
        if genero in ("phonk", "electro"):
            d = next(i for i in midi.instruments if i.is_drum)
            pa = {n.pitch for n in d.notes if n.start < tercio}
            pb = {n.pitch for n in d.notes
                  if tercio <= n.start < 2 * tercio}
            assert pb < pa, f"{genero}: B no dropea piezas de la bateria"


def test_texto_a_caracter_generos():
    assert texto_a_caracter("musica de videojuego arcade") == "videojuegos"
    assert texto_a_caracter("un huayno con quena y charango") == "andina"
    assert texto_a_caracter("drift phonk con cowbell") == "phonk"
    assert texto_a_caracter("house para el club") == "electro"
    # el genero gana al caracter: "phonk oscuro" NO es misteriosa
    assert texto_a_caracter("phonk oscuro") == "phonk"


def test_texto_a_esqueleto_rutea_genero(tmp_path):
    """Texto con genero -> arreglo completo con drums; texto con caracter
    sigue yendo al esqueleto de SymphonyGen (sin drums)."""
    meta = texto_a_esqueleto("un tema 8-bit de boss final", tmp_path / "g.mid",
                             compases=12, semilla=1)
    assert meta["genero"] == "videojuegos"
    midi = miditoolkit.MidiFile(str(tmp_path / "g.mid"))
    assert any(i.is_drum for i in midi.instruments)
    meta2 = texto_a_esqueleto("una cancion epica de batalla",
                              tmp_path / "e.mid", compases=12, semilla=1)
    assert meta2["caracter"] == "epica"
    midi2 = miditoolkit.MidiFile(str(tmp_path / "e.mid"))
    assert not any(i.is_drum for i in midi2.instruments)


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
