# -*- coding: utf-8 -*-
"""Tests de la capa de produccion (mezcla por stems con pedalboard).

POR QUE sin fluidsynth: el render GM real es GPU/instalacion-dependiente y
lento; aqui midi_a_wav se monkeypatchea por un renderizador sintetico (seno
por pista, MONO a proposito: ejercita la rama mono->estereo). Las cadenas y
presets se verifican por INTROSPECCION (construir la cadena y mirar sus
efectos), y la mezcla end-to-end por propiedades: 44100 estereo, pico <= -1
dBFS, sin clipping, longitud = pista mas larga + cola."""
from __future__ import annotations

import math

import miditoolkit
import numpy as np
import pytest
import soundfile as sf

from cognia.musica import produccion
from cognia.musica.produccion import (GENEROS, SR, _cadena_rol, _espec_rol,
                                      producir)

TPQ = 480
COMPAS = TPQ * 4


# ------------------------------------------------------------- constructores

def _midi(ruta, *, compases_mel=4, compases_bajo=None, con_drums=True, bpm=120):
    """MIDI sintetico: melodia aguda densa + bajo grave + drums opcionales."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    midi.tempo_changes = [miditoolkit.TempoChange(bpm, 0)]
    mel = miditoolkit.Instrument(program=73, is_drum=False, name="Flute")
    for c in range(compases_mel):
        t = c * COMPAS
        for b in range(4):
            p = 72 + ((b * 2 + c * 3) % 10)  # contorno variado: melodia real
            mel.notes.append(miditoolkit.Note(100, p, t + b * TPQ, t + b * TPQ + 400))
    midi.instruments = [mel]
    if compases_bajo:
        bajo = miditoolkit.Instrument(program=32, is_drum=False, name="Bass")
        for c in range(compases_bajo):
            t = c * COMPAS
            for b in range(4):
                bajo.notes.append(miditoolkit.Note(100, 40, t + b * TPQ,
                                                   t + b * TPQ + 440))
        midi.instruments.append(bajo)
    if con_drums:
        bat = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
        for c in range(compases_mel):
            t = c * COMPAS
            for b in range(4):
                bat.notes.append(miditoolkit.Note(100, 36, t + b * TPQ,
                                                  t + b * TPQ + 60))
        midi.instruments.append(bat)
    midi.dump(str(ruta))
    return ruta


@pytest.fixture
def render_falso(monkeypatch):
    """midi_a_wav sintetico: seno MONO cuya duracion sale del midi de UNA
    pista que produccion escribio (asi 'mezcla mas larga = pista mas larga'
    se puede verificar de verdad)."""
    def falso(midi, wav=None, *, soundfont=None, timeout=300, seco=False):
        falso.secos.append(seco)  # registra si produccion pidio render seco
        m = miditoolkit.MidiFile(str(midi))
        bpm = m.tempo_changes[0].tempo if m.tempo_changes else 120.0
        fin = max((n.end for i in m.instruments for n in i.notes),
                  default=m.ticks_per_beat)
        segundos = fin / m.ticks_per_beat * 60.0 / bpm
        n = max(1, int(segundos * SR))
        pitches = sorted(n_.pitch for i in m.instruments for n_ in i.notes)
        freq = 440.0 * 2 ** ((pitches[len(pitches) // 2] - 69) / 12)
        t = np.arange(n, dtype=np.float32) / SR
        x = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        sf.write(str(wav), x, SR)  # mono: produccion debe duplicar a estereo
        return str(wav)
    falso.secos = []
    monkeypatch.setattr(produccion, "midi_a_wav", falso)
    return falso


# ------------------------------------------------------------------ mezcla e2e

@pytest.mark.parametrize("genero", GENEROS)
def test_producir_wav_valido_todos_los_generos(tmp_path, render_falso, genero):
    ruta = _midi(tmp_path / "pieza.mid", compases_bajo=4)
    salida = producir(ruta, tmp_path / f"mix_{genero}.wav", genero=genero)
    datos, sr = sf.read(salida, always_2d=True)
    assert sr == SR
    assert datos.shape[1] == 2  # estereo
    pico = float(np.max(np.abs(datos)))
    assert pico < 1.0, f"{genero}: clipping (pico {pico})"
    # pico final <= -1 dBFS (0.8913), con margen de redondeo de float32
    assert pico <= 10 ** (-1.0 / 20.0) + 1e-4, f"{genero}: pico {pico} > -1 dBFS"
    assert pico > 1e-3, f"{genero}: la mezcla salio muda"


def test_genero_invalido_value_error(tmp_path):
    # se valida ANTES de tocar el midi: no hace falta ni archivo ni mock
    with pytest.raises(ValueError):
        producir(tmp_path / "no_importa.mid", genero="reggaeton")


def test_midi_una_sola_pista(tmp_path, render_falso):
    ruta = _midi(tmp_path / "solo.mid", con_drums=False)
    salida = producir(ruta, tmp_path / "solo.wav", genero="orquestal")
    datos, sr = sf.read(salida, always_2d=True)
    assert sr == SR and datos.shape[1] == 2
    assert 1e-3 < float(np.max(np.abs(datos))) <= 10 ** (-1.0 / 20.0) + 1e-4


def test_stems_se_renderizan_secos(tmp_path, render_falso):
    """produccion DEBE pedir seco=True en cada render de stem: fluidsynth
    trae reverb+chorus ACTIVOS por defecto y con ellos puestos cada rol
    sumaria SU reverb encima de la sala del synth (doble reverb) y el
    'BAJO sin reverb: graves limpios' seria mentira."""
    ruta = _midi(tmp_path / "seco.mid", compases_bajo=4)
    producir(ruta, tmp_path / "seco.wav", genero="orquestal")
    assert render_falso.secos, "no se rendereo ningun stem"
    assert all(render_falso.secos), "algun stem se rendereo con la sala default"


def test_mezcla_respeta_tempo_real(tmp_path, render_falso):
    """La regresion exacta que la copia de tempo_changes previene: a 60 bpm
    los 4 compases de melodia duran ~15.8 s; si produccion NO copiara los
    tempos al midi por pista, el render caeria al fallback de 120 y el stem
    saldria de ~7.9 s (mezcla desincronizada). bpm != 120 a proposito:
    con 120 el bug es invisible porque coincide con el fallback."""
    ruta = _midi(tmp_path / "lenta.mid", con_drums=False, bpm=60)
    salida = producir(ruta, tmp_path / "lenta.wav", genero="orquestal")
    frames = sf.info(str(salida)).frames
    # ultima nota de _midi: 3*COMPAS + 3*TPQ + 400 ticks -> segundos a 60 bpm
    fin_ticks = 3 * COMPAS + 3 * TPQ + 400
    esperado = int(fin_ticks / TPQ * (60.0 / 60.0) * SR) + 2 * SR  # + cola
    assert abs(frames - esperado) < int(0.1 * SR), (
        f"frames {frames} vs esperado {esperado}: el stem no salio del tempo real")


def test_mezcla_dura_lo_que_la_pista_mas_larga(tmp_path, render_falso):
    # melodia 2 compases (4 s a 120 bpm), bajo 4 compases (8 s): la mezcla
    # tiene que medir 8 s + 2 s de cola de reverb/delay, no 4 s
    ruta = _midi(tmp_path / "larga.mid", compases_mel=2, compases_bajo=4,
                 con_drums=False)
    salida = producir(ruta, tmp_path / "larga.wav", genero="orquestal")
    frames = sf.info(str(salida)).frames
    esperado = 8 * SR + 2 * SR
    assert frames >= 8 * SR, "la mezcla quedo mas corta que la pista mas larga"
    assert abs(frames - esperado) < int(0.1 * SR), (
        f"frames {frames} vs esperado {esperado} (pista mas larga + 2 s de cola)")


# ------------------------------------------------------ introspeccion de cadenas

def _nombres(cadena):
    return [type(p).__name__ for p in cadena]


def test_drums_reciben_cadena_de_drums():
    cadena = _cadena_rol("DRUMS", "orquestal", 0.5)
    nombres = _nombres(cadena)
    # la firma de la cadena de drums: bombo + caja (2 PeakFilter) + aire
    assert nombres.count("PeakFilter") == 2
    assert "HighShelfFilter" in nombres
    assert nombres[-1] == "Gain"  # el nivel de rol cierra la cadena SIEMPRE
    # y el preset phonk la degrada a lo-fi con el comp aplastado
    phonk = _cadena_rol("DRUMS", "phonk", 0.5)
    assert "Bitcrush" in _nombres(phonk)
    comp = next(p for p in phonk if type(p).__name__ == "Compressor")
    assert comp.threshold_db == -10.0 and comp.ratio == 5.0


def test_niveles_de_rol_en_el_gain_final():
    import pedalboard
    casos = [("MELODIA", "orquestal", 0.0), ("DRUMS", "orquestal", -6.0),
             ("DRUMS", "phonk", -1.0), ("BAJO", "phonk", 0.0),
             ("ACOMPANAMIENTO", "electro", -7.0)]
    for rol, genero, esperado in casos:
        gain = _cadena_rol(rol, genero, 0.5)[-1]
        assert isinstance(gain, pedalboard.Gain)
        assert gain.gain_db == pytest.approx(esperado), (rol, genero)
    # rol desconocido (p.ej. OUTLINE): cadena de acompanamiento a -6.0 fijo
    otro = _cadena_rol("OUTLINE", "phonk", 0.5)
    assert otro[-1].gain_db == pytest.approx(-6.0)


def test_delay_tempo_relativo_con_clamp():
    def _delay(cadena):
        return next(p for p in cadena if type(p).__name__ == "Delay")
    # 120 bpm: negra 0.5 s -> corchea con puntillo 0.375 s (sin clamp)
    assert _delay(_cadena_rol("MELODIA", "videojuegos", 0.5)).delay_seconds == \
        pytest.approx(0.375, abs=1e-3)
    # andina 1.5*negra a 40 bpm (negra 1.5 s) = 2.25 s -> clamp 0.60
    assert _delay(_cadena_rol("MELODIA", "andina", 1.5)).delay_seconds == \
        pytest.approx(0.60, abs=1e-3)
    # electro 0.5*negra a 600 bpm (negra 0.1 s) = 0.05 s -> clamp 0.08
    assert _delay(_cadena_rol("MELODIA", "electro", 0.1)).delay_seconds == \
        pytest.approx(0.08, abs=1e-3)


def test_presets_orquestal_y_flags():
    # orquestal: melodia SIN delay, bajo CON reverb (inserta antes del gain)
    mel = _nombres(_cadena_rol("MELODIA", "orquestal", 0.5))
    assert "Delay" not in mel
    bajo = _nombres(_cadena_rol("BAJO", "orquestal", 0.5))
    assert bajo[-2:] == ["Reverb", "Gain"]
    # bajo base NO tiene reverb (graves limpios)
    assert "Reverb" not in _nombres(_cadena_rol("BAJO", "videojuegos", 0.5))
    # chiptune solo agrega Bitcrush si se pide, y solo en melodia/acomp
    assert "Bitcrush" not in _nombres(_cadena_rol("MELODIA", "videojuegos", 0.5))
    con = _nombres(_cadena_rol("MELODIA", "videojuegos", 0.5, chiptune=True))
    assert "Bitcrush" in con
    assert "Bitcrush" not in _nombres(
        _cadena_rol("DRUMS", "videojuegos", 0.5, chiptune=True))
    # phaser opt-in en los pads de electro
    assert "Phaser" not in _nombres(_cadena_rol("ACOMPANAMIENTO", "electro", 0.5))
    assert "Phaser" in _nombres(
        _cadena_rol("ACOMPANAMIENTO", "electro", 0.5, phaser=True))


def test_todas_las_cadenas_construyen_y_genero_desconocido_cae_a_base():
    roles = ("MELODIA", "CONTRAMELODIA", "BAJO", "ACOMPANAMIENTO", "DRUMS")
    for genero in GENEROS:
        for rol in roles:
            assert _cadena_rol(rol, genero, 0.5, chiptune=True, phaser=True)
    # genero desconocido en el builder: fallback a la cadena base (regla 8 de
    # la spec; producir() en cambio SI valida el genero con ValueError)
    for rol in roles:
        espec, _ = _espec_rol(rol, "genero_inexistente")
        base = [e[0] for e in produccion._CADENAS_BASE[rol]]
        assert [e[0] for e in espec] == base
