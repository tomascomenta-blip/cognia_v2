# -*- coding: utf-8 -*-
"""Tests de la capa de expresividad (cognia/musica/expresividad.py).

POR QUE con MIDIs sinteticos construidos aqui: reproducen los HECHOS del
exportador del vendor (tpq=480, todo a velocity 100, cuantizado a fusas,
sin tempo, pista "Harmonic Outline", drums con is_drum) sin depender de la
GPU ni del vendor. Lo que se testea son PROPIEDADES: notas intactas,
varianza real de velocity dentro del rango seguro, drums sin CC11, outline
segun spec, determinismo byte a byte, idempotencia y el opt-out del backend.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import miditoolkit
import pytest

from cognia.musica import symphony_backend
from cognia.musica.expresividad import MARKER, aplicar_expresividad, main

TPQ = 480
COMPAS = TPQ * 4


def _pieza(ruta: Path, *, compases: int = 8, con_outline: bool = True,
           con_drums: bool = True) -> Path:
    """Pieza multi-pista al estilo del exportador: violin (melodia), cello
    (bajo), piano (acordes de relleno), drums y Harmonic Outline; TODO a
    velocity 100 y en grilla de fusas."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]

    violin = miditoolkit.Instrument(program=40, is_drum=False, name="Violin")
    escala = [72, 74, 76, 79, 81, 79, 76, 74]
    for c in range(compases):
        # beat 4 de cada 4o compas en silencio: respiracion que marca frontera
        beats = 3 if (c % 4) == 3 else 4
        for b in range(beats):
            t = c * COMPAS + b * TPQ
            p = escala[(c * 4 + b) % len(escala)]
            violin.notes.append(miditoolkit.Note(100, p, t, t + 420))

    cello = miditoolkit.Instrument(program=42, is_drum=False, name="Cello")
    for c in range(compases):
        for b in range(4):
            t = c * COMPAS + b * TPQ
            cello.notes.append(miditoolkit.Note(100, 36 + (b * 5) % 12, t, t + 420))

    piano = miditoolkit.Instrument(program=0, is_drum=False, name="Piano")
    for c in range(compases):
        for mitad in range(2):
            t = c * COMPAS + mitad * (2 * TPQ)
            for p in (55, 59, 62):
                piano.notes.append(miditoolkit.Note(100, p, t, t + 900))

    midi.instruments = [violin, cello, piano]

    if con_drums:
        drums = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")
        for c in range(compases):
            for b in range(4):
                t = c * COMPAS + b * TPQ
                drums.notes.append(miditoolkit.Note(100, 36 if b % 2 == 0 else 38,
                                                    t, t + 60))
                drums.notes.append(miditoolkit.Note(100, 42, t + 240, t + 300))
        midi.instruments.append(drums)

    if con_outline:
        outline = miditoolkit.Instrument(program=0, is_drum=False,
                                         name="Harmonic Outline")
        for c in range(compases):
            t = c * COMPAS
            for p in (48, 52, 55):
                outline.notes.append(miditoolkit.Note(100, p, t, t + COMPAS))
        midi.instruments.append(outline)

    midi.dump(str(ruta))
    return ruta


def _por_nombre(midi, nombre):
    return next(i for i in midi.instruments if i.name == nombre)


# --------------------------------------------------- propiedades del pipeline

def test_regresion_velocities_con_vida(tmp_path):
    """Regresion del feature: sin la capa, TODO sale a velocity 100 plana.
    Con ella tiene que haber varianza real dentro del rango seguro."""
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    vels = [n.velocity for i in m.instruments for n in i.notes]
    assert vels, "quedo sin notas"
    assert any(v != 100 for v in vels), "sigue plano: la capa no hizo nada"
    media = sum(vels) / len(vels)
    std = (sum((v - media) ** 2 for v in vels) / len(vels)) ** 0.5
    assert std > 3.0, f"varianza anemica: std={std:.2f}"
    assert all(20 <= v <= 112 for v in vels)
    # drums en su piso propio
    for n in _por_nombre(m, "Drums").notes:
        assert 30 <= n.velocity <= 112


def test_notas_intactas(tmp_path):
    """Ningun note-on cambia de tick ni de pitch; conteo identico por pista
    (salvo el outline, quitado por default); duraciones dentro de banda."""
    ruta = _pieza(tmp_path / "song_0.mid")
    orig = miditoolkit.MidiFile(str(ruta))
    aplicar_expresividad(ruta)
    nuevo = miditoolkit.MidiFile(str(ruta))

    assert len(nuevo.instruments) == len(orig.instruments) - 1  # sin outline
    for nombre in ("Violin", "Cello", "Piano", "Drums"):
        a = sorted(_por_nombre(orig, nombre).notes, key=lambda n: (n.start, n.pitch))
        b = sorted(_por_nombre(nuevo, nombre).notes, key=lambda n: (n.start, n.pitch))
        assert len(a) == len(b)
        onsets = sorted({n.start for n in a})
        siguiente = {onsets[i]: onsets[i + 1] for i in range(len(onsets) - 1)}
        for x, y in zip(a, b):
            assert (x.start, x.pitch) == (y.start, y.pitch)
            do, dn = x.end - x.start, y.end - y.start
            assert dn >= max(30, round(0.5 * do))
            if x.start in siguiente:
                assert dn <= round(1.02 * (siguiente[x.start] - x.start))


def test_outline_quitar_y_crudo(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta)
    nombres = [i.name for i in miditoolkit.MidiFile(str(ruta)).instruments]
    assert "Harmonic Outline" not in nombres
    # el original queda al lado como <nombre>.crudo.mid, intacto y SIN marker
    crudo = tmp_path / "song_0.crudo.mid"
    assert crudo.is_file()
    mc = miditoolkit.MidiFile(str(crudo))
    assert "Harmonic Outline" in [i.name for i in mc.instruments]
    assert all(n.velocity == 100 for i in mc.instruments for n in i.notes)
    assert not any(m.text.startswith(MARKER) for m in mc.markers)


def test_outline_atenuar(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta, outline="atenuar")
    m = miditoolkit.MidiFile(str(ruta))
    out = _por_nombre(m, "Harmonic Outline")
    assert out.program == 48  # colchon de cuerdas, no piano martillado
    assert all(28 <= n.velocity <= 56 for n in out.notes)
    cc7 = [c for c in out.control_changes if c.number == 7]
    assert cc7 and cc7[0].value == 50
    assert not [c for c in out.control_changes if c.number == 11]


def test_drums_sin_cc11_y_cc_en_banda(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    assert not [c for c in _por_nombre(m, "Drums").control_changes
                if c.number == 11]
    # cuerdas (program 40/42) si reciben curva CC11, dentro de [40,118]
    cc11_violin = [c for c in _por_nombre(m, "Violin").control_changes
                   if c.number == 11]
    assert cc11_violin, "la melodia de cuerdas quedo sin fraseo CC11"
    assert all(40 <= c.value <= 118 for c in cc11_violin)
    assert len(cc11_violin) <= 2000
    # piano (program 0) excluido: su volumen es percusivo, CC11 le mete bombeo
    assert not [c for c in _por_nombre(m, "Piano").control_changes
                if c.number == 11]
    # solo CC7 y CC11 en toda la pieza; cero pitch bends
    for i in m.instruments:
        assert all(c.number in (7, 11) for c in i.control_changes)
        assert not i.pitch_bends


def test_tempo_explicito_y_en_banda(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    assert m.tempo_changes and m.tempo_changes[0].time == 0
    assert len(m.tempo_changes) <= 400
    for tc in m.tempo_changes:
        assert 0.78 * 120 - 0.1 <= tc.tempo <= 1.03 * 120 + 0.1


def test_determinismo_misma_semilla(tmp_path):
    a = _pieza(tmp_path / "a.mid")
    b = _pieza(tmp_path / "b.mid")
    aplicar_expresividad(a, semilla=7)
    aplicar_expresividad(b, semilla=7)
    assert a.read_bytes() == b.read_bytes()


def test_no_doble_aplicacion(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta)
    primera = ruta.read_bytes()
    aplicar_expresividad(ruta)  # marker presente => intacto, sin --force
    assert ruta.read_bytes() == primera
    marcas = [m for m in miditoolkit.MidiFile(str(ruta)).markers
              if m.text.startswith(MARKER)]
    assert len(marcas) == 1


def test_intensidad_cero_es_bypass_exacto(tmp_path):
    """El brazo de control del A/B apareado: ni una nota, ni un CC, ni el
    outline se tocan; solo el marker de idempotencia."""
    ruta = _pieza(tmp_path / "song_0.mid")
    aplicar_expresividad(ruta, intensidad=0.0)
    m = miditoolkit.MidiFile(str(ruta))
    assert len(m.instruments) == 5  # outline sigue ahi
    assert all(n.velocity == 100 for i in m.instruments for n in i.notes)
    assert all(not i.control_changes for i in m.instruments)
    assert any(mk.text.startswith(MARKER) for mk in m.markers)


def test_micro_timing_acotado(tmp_path):
    ruta = _pieza(tmp_path / "song_0.mid")
    orig = miditoolkit.MidiFile(str(ruta))
    aplicar_expresividad(ruta, micro_timing=True)
    nuevo = miditoolkit.MidiFile(str(ruta))
    for nombre in ("Violin", "Cello", "Piano", "Drums"):
        a = sorted(_por_nombre(orig, nombre).notes, key=lambda n: (n.start, n.pitch))
        b = sorted(_por_nombre(nuevo, nombre).notes, key=lambda n: (n.start, n.pitch))
        for x, y in zip(a, b):
            assert abs(y.start - x.start) <= 8
            assert x.pitch == y.pitch
    # drums y bajo son el reloj: no se mueven ni un tick
    for nombre in ("Drums", "Cello"):
        a = sorted(_por_nombre(orig, nombre).notes, key=lambda n: (n.start, n.pitch))
        b = sorted(_por_nombre(nuevo, nombre).notes, key=lambda n: (n.start, n.pitch))
        assert [n.start for n in a] == [n.start for n in b]


def test_repetidas_conservan_rearticulacion(tmp_path):
    """Regresion: el legato aceptaba Delta-pitch=0 y pisaba la duracion que la
    rama anti-repeticion deposito, fundiendo el 'ta-ta-ta' en una nota larga
    (gap de 10 ticks). Las repetidas de la melodia tienen que conservar un
    hueco audible (>= 30 ticks a tpq=480) antes de la siguiente igual."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    violin = miditoolkit.Instrument(program=40, is_drum=False, name="Violin")
    for c in range(8):
        beats = 3 if (c % 4) == 3 else 4
        for b in range(beats):
            t = c * COMPAS + b * TPQ
            p = 76 if b < 3 else 81  # motivo ta-ta-ta + salto
            violin.notes.append(miditoolkit.Note(100, p, t, t + 420))
    cello = miditoolkit.Instrument(program=42, is_drum=False, name="Cello")
    for c in range(8):
        for b in range(4):
            t = c * COMPAS + b * TPQ
            cello.notes.append(miditoolkit.Note(100, 36 + (b * 5) % 12, t, t + 420))
    midi.instruments = [violin, cello]
    ruta = tmp_path / "song_0.mid"
    midi.dump(str(ruta))

    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    notas = sorted(_por_nombre(m, "Violin").notes, key=lambda n: n.start)
    pares = [(a, b) for a, b in zip(notas, notas[1:])
             if a.pitch == b.pitch and b.start - a.start == TPQ]
    assert pares, "el motivo repetido desaparecio del test"
    for a, b in pares:
        assert b.start - a.end >= 30, (
            f"repetida en t={a.start} sin re-articulacion: gap={b.start - a.end}")


def test_cc11_sin_serrucho_en_negras(tmp_path):
    """Regresion: el swell aplicaba la excursion completa (0.90->1.10) a CADA
    nota >= corchea -- un serrucho de 16-22 unidades CC por negra (bombeo a
    2 Hz). En una linea de negras la excursion por nota debe quedar sutil."""
    ruta = _pieza(tmp_path / "song_0.mid", con_drums=False, con_outline=False)
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    cc11 = [c for c in _por_nombre(m, "Violin").control_changes if c.number == 11]
    assert cc11, "la melodia quedo sin CC11"
    # dentro de cada negra (saltando la inicializacion en tick 0), el rango
    # local tiene que ser chico: el arco de frase aporta ~2 y el swell ~5
    for t0 in range(TPQ, 24 * TPQ, TPQ):
        vs = [c.value for c in cc11 if t0 <= c.time < t0 + TPQ]
        if len(vs) >= 2:
            assert max(vs) - min(vs) <= 12, (
                f"serrucho en t={t0}: rango {max(vs) - min(vs)}")


def _pieza_tempo_propio(ruta, bpm=90.0):
    """Un .mid AJENO al exportador: trae su propio mapa de tempo."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    midi.tempo_changes = [miditoolkit.TempoChange(bpm, 0)]
    violin = miditoolkit.Instrument(program=40, is_drum=False, name="Violin")
    escala = [72, 74, 76, 79, 81, 79, 76, 74]
    for c in range(8):
        for b in range(4):
            t = c * COMPAS + b * TPQ
            violin.notes.append(miditoolkit.Note(100, escala[(c * 4 + b) % 8],
                                                 t, t + 420))
    midi.instruments = [violin]
    midi.dump(str(ruta))
    return ruta


def test_tempo_propio_bypass_no_reprueba(tmp_path):
    """Regresion: el gate bandeaba el tempo SIEMPRE contra bpm_base=120 y un
    bypass exacto sobre un .mid a 90 BPM reventaba sin haberlo tocado."""
    ruta = _pieza_tempo_propio(tmp_path / "song_90.mid")
    aplicar_expresividad(ruta, intensidad=0.0)
    m = miditoolkit.MidiFile(str(ruta))
    assert any(mk.text.startswith(MARKER) for mk in m.markers)
    assert len(m.tempo_changes) == 1
    assert abs(m.tempo_changes[0].tempo - 90.0) < 0.01  # tempo intacto


def test_tempo_propio_bypass_velocity_ajena(tmp_path):
    """En bypass tampoco se banda la velocity: el archivo ajeno sale intacto."""
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    violin = miditoolkit.Instrument(program=40, is_drum=False, name="Violin")
    violin.notes.append(miditoolkit.Note(127, 72, 0, 480))
    violin.notes.append(miditoolkit.Note(10, 74, 480, 960))
    midi.instruments = [violin]
    ruta = tmp_path / "ajeno.mid"
    midi.dump(str(ruta))
    aplicar_expresividad(ruta, intensidad=0.0)
    m = miditoolkit.MidiFile(str(ruta))
    assert sorted(n.velocity for i in m.instruments for n in i.notes) == [10, 127]


def test_tempo_propio_respetado_en_modo_normal(tmp_path):
    """Regresion: _generar_tempo pisaba el mapa propio con la curva a 120 y la
    pieza a 90 BPM pasaba a sonar a ~120 en silencio. La base del rubato debe
    ser el tempo del ARCHIVO."""
    ruta = _pieza_tempo_propio(tmp_path / "song_90.mid")
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    assert m.tempo_changes
    for tc in m.tempo_changes:
        assert 0.78 * 90 - 0.1 <= tc.tempo <= 1.03 * 90 + 0.1, (
            f"tempo {tc.tempo:.1f} fuera de la banda de 90 BPM")


def test_tempo_propio_multiple_se_conserva(tmp_path):
    """Con varios tempos propios no hay base honesta: el mapa sale INTACTO
    (sin curva de tempo) y el resto de la expresividad se aplica igual."""
    ruta = _pieza_tempo_propio(tmp_path / "song_multi.mid")
    midi = miditoolkit.MidiFile(str(ruta))
    midi.tempo_changes = [miditoolkit.TempoChange(90.0, 0),
                          miditoolkit.TempoChange(140.0, 4 * COMPAS)]
    midi.dump(str(ruta))
    aplicar_expresividad(ruta)
    m = miditoolkit.MidiFile(str(ruta))
    tempos = [(round(tc.tempo), tc.time) for tc in m.tempo_changes]
    assert tempos == [(90, 0), (140, 4 * COMPAS)]
    vels = {n.velocity for i in m.instruments for n in i.notes}
    assert vels != {100}, "la expresividad no se aplico"


# ----------------------------------------------------------------------- gate

def test_gate_rechaza_tempo_fuera_de_banda(tmp_path, monkeypatch):
    """CONTRAFACTUAL del gate: inyectado un bug (tempo 200 bpm, fuera de la
    banda dura), el gate tiene que reprobar y el original quedar intacto."""
    from cognia.musica import expresividad

    def _tempo_roto(midi, frases, compases, seed, bpm_base):
        midi.tempo_changes = [miditoolkit.TempoChange(200.0, 0)]

    monkeypatch.setattr(expresividad, "_generar_tempo", _tempo_roto)
    ruta = _pieza(tmp_path / "song_0.mid")
    antes = ruta.read_bytes()
    with pytest.raises(RuntimeError, match="gate"):
        expresividad.aplicar_expresividad(ruta)
    assert ruta.read_bytes() == antes          # ni un byte tocado
    assert not (tmp_path / "song_0.crudo.mid").exists()  # y sin basura al lado
    assert not list(tmp_path.glob("*.tmp*"))   # el temporal se descarto


def test_gate_rechaza_onset_movido(tmp_path, monkeypatch):
    """Si algun paso moviera un note-on (invariante 1), el gate lo caza."""
    from cognia.musica import expresividad

    original = expresividad._aplicar_duraciones

    def _mueve_notas(midi, duraciones):
        original(midi, duraciones)
        midi.instruments[0].notes[5].start += 60  # bug simulado: corre una nota

    monkeypatch.setattr(expresividad, "_aplicar_duraciones", _mueve_notas)
    ruta = _pieza(tmp_path / "song_0.mid")
    antes = ruta.read_bytes()
    with pytest.raises(RuntimeError, match="gate"):
        expresividad.aplicar_expresividad(ruta)
    assert ruta.read_bytes() == antes


# ------------------------------------------------------------------------ CLI

def test_cli_directorio_salta_crudos(tmp_path):
    _pieza(tmp_path / "song_0.mid")
    _pieza(tmp_path / "song_1.mid")
    assert main([str(tmp_path)]) == 0
    for nombre in ("song_0.mid", "song_1.mid"):
        m = miditoolkit.MidiFile(str(tmp_path / nombre))
        assert any(mk.text.startswith(MARKER) for mk in m.markers)
        crudo = tmp_path / nombre.replace(".mid", ".crudo.mid")
        assert crudo.is_file()
    # segunda pasada: los .crudo.mid NO se procesan (seguirian siendo control)
    assert main([str(tmp_path)]) == 0
    for nombre in ("song_0.crudo.mid", "song_1.crudo.mid"):
        m = miditoolkit.MidiFile(str(tmp_path / nombre))
        assert not any(mk.text.startswith(MARKER) for mk in m.markers)


def test_cli_ruta_inexistente(tmp_path):
    assert main([str(tmp_path / "nada")]) == 2


# ------------------------------------------------------- backend (opt-out)

def test_backend_optout_respetado(tmp_path, monkeypatch):
    ruta = _pieza(tmp_path / "song_0.mid")
    antes = ruta.read_bytes()
    monkeypatch.setenv("COGNIA_MUSICA_EXPRESIVIDAD", "0")
    assert symphony_backend._post_expresividad([str(ruta)]) == [str(ruta)]
    assert ruta.read_bytes() == antes  # ni marker ni crudo: opt-out total
    assert not (tmp_path / "song_0.crudo.mid").exists()


def test_backend_aplica_por_defecto(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_MUSICA_EXPRESIVIDAD", raising=False)
    ruta = _pieza(tmp_path / "song_0.mid")
    assert symphony_backend._post_expresividad([str(ruta)]) == [str(ruta)]
    m = miditoolkit.MidiFile(str(ruta))
    assert any(mk.text.startswith(MARKER) for mk in m.markers)
    assert (tmp_path / "song_0.crudo.mid").is_file()


def test_backend_degrada_sin_romper(tmp_path, monkeypatch, capsys):
    """Un .mid roto jamas tumba la entrega: se loguea y sale el crudo."""
    monkeypatch.delenv("COGNIA_MUSICA_EXPRESIVIDAD", raising=False)
    roto = tmp_path / "roto.mid"
    roto.write_bytes(b"no soy un midi")
    assert symphony_backend._post_expresividad([str(roto)]) == [str(roto)]
    assert "expresividad" in capsys.readouterr().err


def test_backend_orquestar_integra_expresividad(tmp_path, monkeypatch):
    """El caller de orquestar recibe las MISMAS rutas, ya procesadas."""
    ruta = _pieza(tmp_path / "song_0.mid")

    class _Popen:
        def __init__(self, cmd, **kw):
            self.returncode = 0

        def communicate(self, timeout=None):
            return json.dumps({"ok": True, "midis": [str(ruta)]}), ""

        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", _Popen)
    monkeypatch.delenv("COGNIA_MUSICA_EXPRESIVIDAD", raising=False)
    midis = symphony_backend.orquestar(None, str(tmp_path / "out"))
    assert midis == [str(ruta)]
    m = miditoolkit.MidiFile(str(ruta))
    assert any(mk.text.startswith(MARKER) for mk in m.markers)
    assert (tmp_path / "song_0.crudo.mid").is_file()


def _inyectar_solapes(ruta):
    """Replica el cluster real de song_2 (pista 12, pitch 75): dos notas
    arrancando en el mismo tick y una tercera solapada parcialmente."""
    midi = miditoolkit.MidiFile(str(ruta))
    violin = _por_nombre(midi, "Violin")
    t = 4 * COMPAS
    violin.notes.append(miditoolkit.Note(100, 75, t, t + 240))
    violin.notes.append(miditoolkit.Note(100, 75, t, t + 720))
    violin.notes.append(miditoolkit.Note(100, 75, t + 240, t + 720))
    midi.dump(str(ruta))
    return ruta


def test_solapes_mismo_pitch_del_vendor_no_tumban_el_gate(tmp_path):
    """Regresion del song_2 REAL: el vendor emite notas del mismo pitch
    solapadas; al escribir y re-leer, el apareamiento note_on/note_off se
    re-baraja y el gate veia duraciones fantasma (720 -> 485) en archivos
    que la capa jamas toco asi. El saneo de solapes lo elimina de raiz."""
    ruta = _inyectar_solapes(_pieza(tmp_path / "solapes.mid"))

    aplicar_expresividad(str(ruta))  # sin _sanear_solapes: RuntimeError

    salida = miditoolkit.MidiFile(str(ruta))
    assert any(mk.text.startswith(MARKER) for mk in salida.markers)
    for inst in salida.instruments:
        por_pitch = {}
        for n in inst.notes:
            por_pitch.setdefault(n.pitch, []).append(n)
        for ns in por_pitch.values():
            ns.sort(key=lambda x: x.start)
            for a, b in zip(ns, ns[1:]):
                assert a.end <= b.start, "quedo un solape de mismo pitch"


def test_bpm_explicito_gana_al_120_de_fabrica(tmp_path):
    """Regresion: el exportador del vendor deja UN evento tempo=120 de
    fabrica (artefacto de miditoolkit); con la regla 'el archivo manda',
    --bpm 72 se ignoraba sin aviso. El bpm explicito tiene que ganar al
    tempo UNICO del archivo; el default (None) sigue derivando del archivo."""
    ruta = _pieza(tmp_path / "song_0.mid")
    midi = miditoolkit.MidiFile(str(ruta))
    midi.tempo_changes = [miditoolkit.TempoChange(120.0, 0)]
    midi.dump(str(ruta))

    aplicar_expresividad(str(ruta), bpm_base=72)
    salida = miditoolkit.MidiFile(str(ruta))
    tempos = [t.tempo for t in salida.tempo_changes]
    assert tempos, "sin curva de tempo"
    assert max(tempos) <= 1.03 * 72 + 0.01, f"curva alrededor de 120, no de 72: max {max(tempos)}"
    assert min(tempos) >= 0.78 * 72 - 0.01


def test_song2_real_procesa_y_contrafactual_reprueba(tmp_path, monkeypatch):
    """El song_2 REAL del vendor (fixture con los solapes que tumbaron el
    gate: 'duracion 720 -> 485'). Con el saneo procesa; el contrafactual
    (saneo apagado) tiene que REPROBAR con el mismo archivo -- si no
    reprueba, el fix no esta probando nada."""
    from cognia.musica import expresividad as expr

    fixture = Path(__file__).parent / "fixtures" / "song2_solapes_vendor.mid"

    con_fix = tmp_path / "con_fix.mid"
    con_fix.write_bytes(fixture.read_bytes())
    expr.aplicar_expresividad(str(con_fix))
    salida = miditoolkit.MidiFile(str(con_fix))
    assert any(mk.text.startswith(MARKER) for mk in salida.markers)

    sin_fix = tmp_path / "sin_fix.mid"
    sin_fix.write_bytes(fixture.read_bytes())
    monkeypatch.setattr(expr, "_sanear_solapes", lambda m: 0)
    with pytest.raises(RuntimeError, match="gate"):
        expr.aplicar_expresividad(str(sin_fix))
    # y el original queda intacto tras el fallo
    assert sin_fix.read_bytes() == fixture.read_bytes()
