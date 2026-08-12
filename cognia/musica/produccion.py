# -*- coding: utf-8 -*-
"""Capa de produccion: mezcla por stems con cadenas pedalboard por rol.

POR QUE existe: el render GM plano de fluidsynth suena a "General MIDI de
los 90" -- todas las pistas al mismo nivel, sin espacio ni pegada. Esta capa
separa el MIDI por pistas, renderiza cada una por separado, clasifica su rol
(reusando el clasificador de expresividad: mismo criterio en toda la linea),
le aplica una cadena de efectos idiomatica del genero y mezcla con niveles
relativos + master con limiter. pedalboard es DSP puro (sin torch: legal en
cognia/).

POR QUE cadenas y presets como DATOS y no como codigo: un preset es una
lista de operaciones (mod/del/ins) sobre la cadena base del rol, y TODO se
valida al importar el modulo (_validar_presets). Una referencia rota en un
preset revienta con ValueError al arrancar, jamas en mitad de un render de
10 minutos (la leccion del repo: una leccion en prosa no impide nada, un
chequeo al arrancar si).

POR QUE cero aleatoriedad: todos los parametros son literales de la spec;
misma entrada + mismo genero => mismos bytes de salida (patron del repo).

Imports pesados (numpy/soundfile/pedalboard/miditoolkit) son PEREZOSOS: el
paquete cognia.musica se puede importar sin tenerlos (mismo contrato que
expresividad).
"""
from __future__ import annotations

import argparse
import math
import sys
import tempfile
from pathlib import Path

from cognia.musica.render import midi_a_wav
from cognia.musica.expresividad import (_clasificar, _compases, _es_outline,
                                        _miditoolkit, _rol_dominante)

SR = 44100
GENEROS = ("orquestal", "videojuegos", "andina", "phonk", "electro")

# tope duro del pico final: -1 dBFS (el Limiter a -1.5 puede sobrepasar decimas)
_TOPE_PICO = 10.0 ** (-1.0 / 20.0)  # 0.8913


def _clamp_delay(segundos: float) -> float:
    """Delays tempo-relativos acotados a [0.08, 0.60] s: por debajo es un
    comb filter, por encima un eco de estadio que embarra cualquier genero."""
    return min(0.60, max(0.08, segundos))


# --------------------------------------------------------- cadenas base (spec §1)
# Cada efecto es (id, ClasePedalboard, kwargs). El id es lo que los presets
# referencian; kwargs con valor ("negra", f) se resuelven en build-time como
# clamp(f * negra). El Gain final ES el nivel de mezcla del rol (spec §3):
# no hay gains sueltos fuera de la cadena.

_CADENAS_BASE = {
    "MELODIA": [
        ("hpf", "HighpassFilter", {"cutoff_frequency_hz": 120.0}),
        ("eq_barro", "PeakFilter", {"cutoff_frequency_hz": 250.0, "gain_db": -2.0, "q": 1.0}),
        ("comp", "Compressor", {"threshold_db": -18.0, "ratio": 2.5,
                                "attack_ms": 10.0, "release_ms": 120.0}),
        ("eq_presencia", "PeakFilter", {"cutoff_frequency_hz": 3000.0, "gain_db": 2.0, "q": 0.8}),
        # corchea con puntillo
        ("delay", "Delay", {"delay_seconds": ("negra", 0.75), "feedback": 0.20, "mix": 0.10}),
        ("reverb", "Reverb", {"room_size": 0.45, "damping": 0.50, "wet_level": 0.18,
                              "dry_level": 0.82, "width": 1.0, "freeze_mode": 0.0}),
        ("gain", "Gain", {}),
    ],
    "CONTRAMELODIA": [
        ("hpf", "HighpassFilter", {"cutoff_frequency_hz": 140.0}),
        ("comp", "Compressor", {"threshold_db": -20.0, "ratio": 2.0,
                                "attack_ms": 15.0, "release_ms": 150.0}),
        # cede presencia a la melodia
        ("eq_presencia", "PeakFilter", {"cutoff_frequency_hz": 3000.0, "gain_db": -1.5, "q": 0.8}),
        ("chorus", "Chorus", {"rate_hz": 0.8, "depth": 0.15, "centre_delay_ms": 7.0,
                              "feedback": 0.0, "mix": 0.15}),
        ("reverb", "Reverb", {"room_size": 0.55, "damping": 0.55, "wet_level": 0.22,
                              "dry_level": 0.78, "width": 1.0, "freeze_mode": 0.0}),
        ("gain", "Gain", {}),
    ],
    # sin reverb: graves limpios
    "BAJO": [
        ("hpf", "HighpassFilter", {"cutoff_frequency_hz": 30.0}),
        ("low_shelf", "LowShelfFilter", {"cutoff_frequency_hz": 100.0, "gain_db": 2.0, "q": 0.707}),
        ("comp", "Compressor", {"threshold_db": -16.0, "ratio": 4.0,
                                "attack_ms": 8.0, "release_ms": 80.0}),
        # definicion en parlantes chicos
        ("eq_definicion", "PeakFilter", {"cutoff_frequency_hz": 800.0, "gain_db": 1.5, "q": 1.0}),
        ("lpf", "LowpassFilter", {"cutoff_frequency_hz": 8000.0}),
        ("gain", "Gain", {}),
    ],
    "ACOMPANAMIENTO": [
        ("hpf", "HighpassFilter", {"cutoff_frequency_hz": 160.0}),  # deja sitio al bajo
        ("comp", "Compressor", {"threshold_db": -22.0, "ratio": 2.0,
                                "attack_ms": 20.0, "release_ms": 200.0}),
        # hueco para la melodia
        ("eq_hueco", "PeakFilter", {"cutoff_frequency_hz": 2500.0, "gain_db": -2.0, "q": 0.9}),
        ("chorus", "Chorus", {"rate_hz": 0.6, "depth": 0.10, "centre_delay_ms": 8.0,
                              "feedback": 0.0, "mix": 0.12}),
        ("reverb", "Reverb", {"room_size": 0.50, "damping": 0.60, "wet_level": 0.20,
                              "dry_level": 0.80, "width": 1.0, "freeze_mode": 0.0}),
        ("gain", "Gain", {}),
    ],
    "DRUMS": [
        ("hpf", "HighpassFilter", {"cutoff_frequency_hz": 40.0}),
        ("comp", "Compressor", {"threshold_db": -14.0, "ratio": 3.0,
                                "attack_ms": 5.0, "release_ms": 100.0}),
        ("eq_bombo", "PeakFilter", {"cutoff_frequency_hz": 60.0, "gain_db": 1.5, "q": 1.2}),
        ("eq_caja", "PeakFilter", {"cutoff_frequency_hz": 3500.0, "gain_db": 1.5, "q": 0.9}),
        ("shelf_aire", "HighShelfFilter", {"cutoff_frequency_hz": 8000.0, "gain_db": 1.5, "q": 0.707}),
        ("reverb", "Reverb", {"room_size": 0.30, "damping": 0.60, "wet_level": 0.08,
                              "dry_level": 0.92, "width": 1.0, "freeze_mode": 0.0}),
        ("gain", "Gain", {}),
    ],
}

# ------------------------------------------------------ presets por genero (spec §2)
# Operaciones: ("mod", id, {param: valor})   reemplaza parametros
#              ("del", id)                    elimina el efecto
#              ("ins", "antes"|"despues", id_ref, id_nuevo, Clase, kwargs)

_PRESETS = {
    # sala comun grande, dinamica respetada
    "orquestal": {
        "MELODIA": [
            ("mod", "comp", {"threshold_db": -24.0, "ratio": 1.8}),
            ("mod", "reverb", {"room_size": 0.85, "damping": 0.40,
                               "wet_level": 0.28, "dry_level": 0.72}),
            ("del", "delay"),
            ("ins", "antes", "reverb", "shelf_aire", "HighShelfFilter",
             {"cutoff_frequency_hz": 9000.0, "gain_db": 1.0, "q": 0.707}),
        ],
        "CONTRAMELODIA": [
            ("mod", "comp", {"threshold_db": -24.0, "ratio": 1.8}),
            ("mod", "reverb", {"room_size": 0.85, "damping": 0.40,
                               "wet_level": 0.32, "dry_level": 0.68}),
            ("del", "chorus"),
        ],
        "ACOMPANAMIENTO": [
            ("mod", "comp", {"threshold_db": -24.0, "ratio": 1.8}),
            ("mod", "reverb", {"room_size": 0.85, "damping": 0.40,
                               "wet_level": 0.32, "dry_level": 0.68}),
            ("del", "chorus"),
        ],
        "BAJO": [
            ("ins", "antes", "gain", "reverb", "Reverb",
             {"room_size": 0.70, "damping": 0.50, "wet_level": 0.12,
              "dry_level": 0.88, "width": 1.0, "freeze_mode": 0.0}),
        ],
        "DRUMS": [  # percusion orquestal
            ("mod", "comp", {"threshold_db": -18.0, "ratio": 2.0}),
            ("mod", "reverb", {"room_size": 0.70, "wet_level": 0.20, "dry_level": 0.80}),
        ],
    },
    # brillante, punch
    "videojuegos": {
        "MELODIA": [
            ("mod", "eq_presencia", {"gain_db": 3.0}),
            ("ins", "despues", "eq_presencia", "shelf_brillo", "HighShelfFilter",
             {"cutoff_frequency_hz": 9000.0, "gain_db": 2.5, "q": 0.707}),
            ("mod", "delay", {"mix": 0.12}),
            ("mod", "reverb", {"room_size": 0.35, "wet_level": 0.15, "dry_level": 0.85}),
        ],
        "CONTRAMELODIA": [
            ("mod", "reverb", {"room_size": 0.35, "wet_level": 0.15, "dry_level": 0.85}),
        ],
        "ACOMPANAMIENTO": [
            ("mod", "reverb", {"room_size": 0.35, "wet_level": 0.15, "dry_level": 0.85}),
        ],
        "BAJO": [
            ("mod", "comp", {"ratio": 5.0}),
        ],
        "DRUMS": [
            ("mod", "comp", {"threshold_db": -12.0, "ratio": 4.0, "attack_ms": 3.0}),
            ("mod", "eq_bombo", {"gain_db": 2.5}),
            ("mod", "reverb", {"room_size": 0.35, "wet_level": 0.15, "dry_level": 0.85}),
        ],
    },
    # aire, reverb de valle, calidez
    "andina": {
        "MELODIA": [  # quena/zamponia
            ("mod", "hpf", {"cutoff_frequency_hz": 200.0}),
            ("mod", "comp", {"threshold_db": -20.0, "ratio": 2.0}),
            ("ins", "antes", "delay", "shelf_aire", "HighShelfFilter",
             {"cutoff_frequency_hz": 8000.0, "gain_db": 2.0, "q": 0.707}),
            ("mod", "delay", {"delay_seconds": ("negra", 1.5), "feedback": 0.25, "mix": 0.12}),
            ("mod", "reverb", {"room_size": 0.75, "damping": 0.35,
                               "wet_level": 0.30, "dry_level": 0.70}),
        ],
        "CONTRAMELODIA": [
            ("mod", "reverb", {"room_size": 0.70, "wet_level": 0.28, "dry_level": 0.72}),
        ],
        "ACOMPANAMIENTO": [  # charango/guitarra
            ("ins", "despues", "hpf", "shelf_calidez", "LowShelfFilter",
             {"cutoff_frequency_hz": 200.0, "gain_db": 1.5, "q": 0.707}),
            ("mod", "chorus", {"mix": 0.10}),
            ("mod", "reverb", {"room_size": 0.65, "wet_level": 0.25, "dry_level": 0.75}),
        ],
        "BAJO": [  # calidez, sin brillo plastico
            ("mod", "low_shelf", {"gain_db": 1.5}),
            ("mod", "lpf", {"cutoff_frequency_hz": 6000.0}),
        ],
        "DRUMS": [  # bombo leguero
            ("mod", "eq_caja", {"gain_db": 0.0}),
            ("mod", "shelf_aire", {"gain_db": 0.5}),
            ("mod", "reverb", {"room_size": 0.55, "wet_level": 0.18, "dry_level": 0.82}),
        ],
    },
    # 808 con drive, cowbell presente, lo-fi. El "ducking" es el hueco
    # espectral a 60 Hz + niveles de rol + bus comp del master (spec §2):
    # nada de envolventes de gain simulando sidechain.
    "phonk": {
        "MELODIA": [  # cowbell/lead
            ("mod", "eq_presencia", {"cutoff_frequency_hz": 2500.0, "gain_db": 3.0, "q": 1.0}),
            ("ins", "despues", "comp", "dist", "Distortion", {"drive_db": 6.0}),
            ("mod", "delay", {"delay_seconds": ("negra", 0.5), "feedback": 0.15, "mix": 0.08}),
            ("mod", "reverb", {"room_size": 0.25, "wet_level": 0.12, "dry_level": 0.88}),
        ],
        "CONTRAMELODIA": [
            ("ins", "despues", "hpf", "hueco_808", "PeakFilter",
             {"cutoff_frequency_hz": 60.0, "gain_db": -3.0, "q": 1.4}),
        ],
        "ACOMPANAMIENTO": [
            ("ins", "despues", "comp", "bitcrush", "Bitcrush", {"bit_depth": 9}),
            ("ins", "despues", "bitcrush", "lpf_lofi", "LowpassFilter",
             {"cutoff_frequency_hz": 7000.0}),
            ("ins", "despues", "hpf", "hueco_808", "PeakFilter",
             {"cutoff_frequency_hz": 60.0, "gain_db": -3.0, "q": 1.4}),
        ],
        "BAJO": [  # 808
            ("mod", "low_shelf", {"cutoff_frequency_hz": 60.0, "gain_db": 4.0}),
            ("ins", "despues", "comp", "dist", "Distortion", {"drive_db": 12.0}),
            ("mod", "comp", {"threshold_db": -12.0, "ratio": 6.0,
                             "attack_ms": 2.0, "release_ms": 60.0}),
            ("mod", "lpf", {"cutoff_frequency_hz": 5000.0}),
        ],
        "DRUMS": [
            ("mod", "comp", {"threshold_db": -10.0, "ratio": 5.0,
                             "attack_ms": 2.0, "release_ms": 80.0}),
            ("ins", "despues", "comp", "bitcrush", "Bitcrush", {"bit_depth": 8}),
            ("ins", "despues", "bitcrush", "lpf_lofi", "LowpassFilter",
             {"cutoff_frequency_hz": 9000.0}),
            ("mod", "reverb", {"wet_level": 0.05, "dry_level": 0.95}),
        ],
    },
    # four-on-floor con punch, sintes anchos, brillo
    "electro": {
        "MELODIA": [  # sinte
            ("ins", "antes", "delay", "chorus", "Chorus",
             {"rate_hz": 1.2, "depth": 0.35, "centre_delay_ms": 7.0,
              "feedback": 0.1, "mix": 0.35}),
            ("ins", "despues", "eq_presencia", "shelf_brillo", "HighShelfFilter",
             {"cutoff_frequency_hz": 9000.0, "gain_db": 2.5, "q": 0.707}),
            ("mod", "delay", {"delay_seconds": ("negra", 0.5), "feedback": 0.30, "mix": 0.15}),
        ],
        "CONTRAMELODIA": [],
        "ACOMPANAMIENTO": [  # pads
            ("mod", "hpf", {"cutoff_frequency_hz": 180.0}),
            ("mod", "chorus", {"mix": 0.30, "depth": 0.25}),
        ],
        "BAJO": [
            ("ins", "despues", "comp", "dist", "Distortion", {"drive_db": 6.0}),
            ("mod", "comp", {"ratio": 5.0, "attack_ms": 5.0}),
        ],
        "DRUMS": [
            ("mod", "comp", {"threshold_db": -12.0, "ratio": 4.0,
                             "attack_ms": 2.0, "release_ms": 60.0}),
            ("mod", "eq_bombo", {"cutoff_frequency_hz": 55.0, "gain_db": 3.0}),
            ("mod", "shelf_aire", {"cutoff_frequency_hz": 9000.0, "gain_db": 2.0}),
        ],
    },
}

# ------------------------------------------------- niveles de mezcla (spec §3)

_NIVEL_BASE = {"MELODIA": 0.0, "CONTRAMELODIA": -4.5, "BAJO": -3.0,
               "ACOMPANAMIENTO": -6.0, "DRUMS": -2.0}
_NIVEL_GENERO = {
    "orquestal": {"CONTRAMELODIA": -3.5, "ACOMPANAMIENTO": -4.5, "DRUMS": -6.0},
    "videojuegos": {},
    "andina": {"ACOMPANAMIENTO": -5.0, "DRUMS": -5.0},
    "phonk": {"MELODIA": -2.0, "BAJO": 0.0, "ACOMPANAMIENTO": -9.0, "DRUMS": -1.0},
    "electro": {"BAJO": -2.0, "ACOMPANAMIENTO": -7.0, "DRUMS": -1.0},
}

# --------------------------------------------------------- master (spec §3)

_MASTER_BASE = {
    "bus_comp": {"threshold_db": -16.0, "ratio": 1.5, "attack_ms": 15.0, "release_ms": 200.0},
    "shelf": {"cutoff_frequency_hz": 12000.0, "gain_db": 1.0, "q": 0.707},
}
_MASTER_GENERO = {
    # dinamica respetada: SIN bus comp, shelf plano
    "orquestal": {"bus_comp": None,
                  "shelf": {"cutoff_frequency_hz": 12000.0, "gain_db": 0.0, "q": 0.707}},
    "phonk": {"bus_comp": {"threshold_db": -12.0, "ratio": 2.5,
                           "attack_ms": 10.0, "release_ms": 150.0}},
    "electro": {"bus_comp": {"threshold_db": -14.0, "ratio": 2.0,
                             "attack_ms": 15.0, "release_ms": 200.0},
                "shelf": {"cutoff_frequency_hz": 11000.0, "gain_db": 1.0, "q": 0.707}},
}


def _ops_de(genero: str, rol: str, chiptune: bool, phaser: bool) -> list:
    """Operaciones del preset para (genero, rol) + flags opcionales.
    Genero desconocido => sin overrides (fallback explicito, spec regla 8)."""
    ops = list(_PRESETS.get(genero, {}).get(rol, ()))
    if genero == "videojuegos" and chiptune and rol in ("MELODIA", "ACOMPANAMIENTO"):
        ops += [("ins", "despues", "comp", "bitcrush_chip", "Bitcrush", {"bit_depth": 10}),
                ("ins", "despues", "bitcrush_chip", "lpf_chip", "LowpassFilter",
                 {"cutoff_frequency_hz": 12000.0})]
    if genero == "electro" and phaser and rol == "ACOMPANAMIENTO":
        ops += [("ins", "despues", "chorus", "phaser", "Phaser",
                 {"rate_hz": 0.3, "depth": 0.4, "centre_frequency_hz": 1000.0,
                  "feedback": 0.2, "mix": 0.15})]
    return ops


def _aplicar_ops(espec: list, ops: list, contexto: str) -> list:
    """Aplica mod/del/ins sobre la especificacion [[id, Clase, kwargs], ...].
    Toda referencia rota es ValueError con el contexto (genero/rol) legible."""
    for op in ops:
        ids = [e[0] for e in espec]
        tipo = op[0]
        if tipo == "mod":
            _, ref, cambios = op
            if ref not in ids:
                raise ValueError(f"preset {contexto}: 'mod' refiere a '{ref}' "
                                 f"que no existe en la cadena (hay: {ids})")
            espec[ids.index(ref)][2].update(cambios)
        elif tipo == "del":
            _, ref = op
            if ref not in ids:
                raise ValueError(f"preset {contexto}: 'del' refiere a '{ref}' "
                                 f"que no existe en la cadena (hay: {ids})")
            espec.pop(ids.index(ref))
        elif tipo == "ins":
            _, pos, ref, nuevo, clase, kwargs = op
            if ref not in ids:
                raise ValueError(f"preset {contexto}: 'ins' declara posicion "
                                 f"relativa a '{ref}' que no existe (hay: {ids})")
            if nuevo in ids:
                raise ValueError(f"preset {contexto}: 'ins' duplica el id '{nuevo}'")
            i = ids.index(ref) + (1 if pos == "despues" else 0)
            espec.insert(i, [nuevo, clase, dict(kwargs)])
        else:
            raise ValueError(f"preset {contexto}: operacion desconocida {tipo!r}")
    return espec


def _espec_rol(rol: str, genero: str, *, chiptune: bool = False,
               phaser: bool = False) -> tuple[list, float]:
    """(especificacion resuelta, nivel de rol). Rol desconocido (p.ej.
    OUTLINE) => cadena de ACOMPANAMIENTO con nivel -6.0 (spec regla 9)."""
    conocido = rol in _CADENAS_BASE
    rol_base = rol if conocido else "ACOMPANAMIENTO"
    espec = [[i, c, dict(k)] for i, c, k in _CADENAS_BASE[rol_base]]
    espec = _aplicar_ops(espec, _ops_de(genero, rol_base, chiptune, phaser),
                         f"{genero}/{rol_base}")
    if conocido:
        nivel = _NIVEL_GENERO.get(genero, {}).get(rol, _NIVEL_BASE[rol])
    else:
        nivel = -6.0
    return espec, nivel


def _cadena_rol(rol: str, genero: str, negra: float, *, chiptune: bool = False,
                phaser: bool = False) -> list:
    """Instancia la cadena pedalboard del rol para el genero. Los kwargs
    ("negra", f) se resuelven aqui: clamp(f * negra) en segundos."""
    import pedalboard
    espec, nivel = _espec_rol(rol, genero, chiptune=chiptune, phaser=phaser)
    cadena = []
    for eid, clase, kwargs in espec:
        resueltos = {k: (_clamp_delay(v[1] * negra) if isinstance(v, tuple) else v)
                     for k, v in kwargs.items()}
        if eid == "gain":
            resueltos["gain_db"] = nivel
        cadena.append(getattr(pedalboard, clase)(**resueltos))
    return cadena


def _validar_presets() -> None:
    """Chequeo al importar (spec regla 10): cada operacion de cada preset
    debe referir a un efecto existente de la cadena base de su rol. Con los
    flags opcionales encendidos, que tambien son operaciones."""
    for genero in GENEROS:
        for rol in _CADENAS_BASE:
            espec = [[i, c, dict(k)] for i, c, k in _CADENAS_BASE[rol]]
            _aplicar_ops(espec, _ops_de(genero, rol, True, True), f"{genero}/{rol}")


_validar_presets()


# ------------------------------------------------------------ audio helpers

def _leer_estereo(ruta: str):
    """WAV -> (2, n) float32 a 44100 (spec robustez 2 y 3)."""
    import numpy as np
    import soundfile as sf
    datos, sr = sf.read(str(ruta), dtype="float32", always_2d=True)
    x = datos.T  # soundfile da (n, ch); el pipeline entero es (ch, n)
    if sr != SR:
        from pedalboard.io import AudioFile
        with AudioFile(str(ruta)).resampled_to(SR) as f:
            x = f.read(int(f.frames))
        x = np.asarray(x, dtype="float32")
    if x.shape[0] == 1:
        x = np.vstack([x, x])       # mono -> estereo por duplicacion
    elif x.shape[0] > 2:
        x = x[:2]                   # mas de 2 canales: los 2 primeros
    return np.ascontiguousarray(x.astype("float32"))


def _normalizar_stem(x):
    """Pico a -6 dBFS antes de la cadena (spec robustez 4). Amplificacion
    acotada a +24 dB: subir mas es amplificar ruido de fondo del sf3."""
    import numpy as np
    pico = float(np.max(np.abs(x)))
    if pico <= 0.0:
        return x
    ganancia_db = min(-6.0 - 20.0 * math.log10(pico), 24.0)
    return (x * (10.0 ** (ganancia_db / 20.0))).astype("float32")


def _masterizar(suma, genero: str):
    """Master (spec §3): normaliza la suma a -6 dBFS, bus comp (segun
    genero), shelf de aire, Limiter, y chequeo DURO de -1 dBFS con numpy
    (el Limiter puede sobrepasar decimas; el clipping esta prohibido)."""
    import numpy as np
    import pedalboard
    pico = float(np.max(np.abs(suma)))
    if pico <= 0.0:
        raise RuntimeError("produccion: la mezcla quedo en silencio total")
    ganancia_db = min(-6.0 - 20.0 * math.log10(pico), 24.0)
    cfg = dict(_MASTER_BASE)
    cfg.update(_MASTER_GENERO.get(genero, {}))
    cadena = [pedalboard.Gain(gain_db=ganancia_db)]
    if cfg["bus_comp"] is not None:
        cadena.append(pedalboard.Compressor(**cfg["bus_comp"]))
    cadena.append(pedalboard.HighShelfFilter(**cfg["shelf"]))
    cadena.append(pedalboard.Limiter(threshold_db=-1.5, release_ms=200.0))
    y = pedalboard.Pedalboard(cadena)(suma, SR)
    y = np.nan_to_num(y.astype("float32"), nan=0.0, posinf=0.0, neginf=0.0)
    tope = float(np.max(np.abs(y)))
    if tope > _TOPE_PICO:
        y = (y * (_TOPE_PICO / tope)).astype("float32")
    return y


# ---------------------------------------------------------------- principal

def producir(midi, wav_salida=None, *, genero: str = "orquestal",
             timeout: float = 600, chiptune: bool = False,
             phaser: bool = False) -> str:
    """MIDI -> WAV mezclado y masterizado por stems. Devuelve la ruta.

    Separa el MIDI por pistas (conservando tempo/metricas), renderiza cada
    una con fluidsynth EN SECO (midi_a_wav con -R 0 -C 0: la sala la pone
    la cadena del rol), clasifica su rol con el clasificador de
    expresividad (drums por is_drum, rol dominante para el resto), aplica la
    cadena pedalboard del rol modificada por el preset del genero y mezcla
    con niveles de la spec + master con Limiter (pico final <= -1 dBFS).

    timeout: por render de pista (fluidsynth), no total.
    """
    if genero not in GENEROS:
        raise ValueError(f"produccion: genero {genero!r} desconocido "
                         f"(validos: {', '.join(GENEROS)})")
    import numpy as np
    import soundfile as sf
    mt = _miditoolkit()

    ruta = Path(midi)
    if not ruta.is_file():
        raise RuntimeError(f"produccion: no existe el MIDI {midi}")
    m = mt.MidiFile(str(ruta))
    pistas = [(ip, inst) for ip, inst in enumerate(m.instruments) if inst.notes]
    if not pistas:
        raise RuntimeError(f"produccion: {ruta.name} no tiene ninguna nota")

    tempos = sorted(m.tempo_changes, key=lambda t: t.time)
    bpm = float(tempos[0].tempo) if tempos else 120.0
    negra = 60.0 / bpm

    # mismo criterio de rol que la capa de expresividad: outs congelado y
    # ventanas de 4 compases; aqui solo interesa el rol DOMINANTE por pista
    max_tick = max(n.end for _, inst in pistas for n in inst.notes)
    outs = [_es_outline(i) for i in m.instruments]
    compases = _compases(m, max_tick)
    roles, _escasas = _clasificar(m, compases, outs)

    stems = []
    with tempfile.TemporaryDirectory(prefix="cognia_produccion_") as td:
        tdir = Path(td)
        for ip, inst in pistas:
            rol = "DRUMS" if inst.is_drum else _rol_dominante(roles[ip])
            # midi de UNA pista conservando tempo y time signatures: sin
            # ellos fluidsynth renderizaria a 120 fijos y la mezcla quedaria
            # desincronizada del original
            solo = mt.MidiFile(ticks_per_beat=m.ticks_per_beat)
            solo.tempo_changes = m.tempo_changes
            solo.time_signature_changes = m.time_signature_changes
            solo.key_signature_changes = m.key_signature_changes
            solo.instruments = [inst]
            ruta_mid = tdir / f"pista_{ip}.mid"
            solo.dump(str(ruta_mid))
            # seco=True: sin la reverb/chorus default de fluidsynth -- la
            # sala la pone la cadena del rol; con la default puesta habria
            # DOS reverbs en serie y el bajo llegaria con sala en los graves
            ruta_wav = midi_a_wav(str(ruta_mid), str(tdir / f"pista_{ip}.wav"),
                                  timeout=timeout, seco=True)
            x = _leer_estereo(ruta_wav)
            # pico < -80 dBFS: solo hay ruido de fondo del sf3; amplificarlo
            # a -6 dBFS meteria soplido puro en la mezcla (spec robustez 1)
            if x.size == 0 or float(np.max(np.abs(x))) < 1e-4:
                continue
            x = _normalizar_stem(x)
            # 2 s de cola ANTES de procesar: la reverb y el delay necesitan
            # espacio para decaer o la pista termina en un corte seco
            x = np.concatenate([x, np.zeros((2, 2 * SR), dtype="float32")], axis=1)
            import pedalboard
            cadena = pedalboard.Pedalboard(
                _cadena_rol(rol, genero, negra, chiptune=chiptune, phaser=phaser))
            y = cadena(x, SR)
            y = np.nan_to_num(y.astype("float32"), nan=0.0, posinf=0.0, neginf=0.0)
            stems.append(y)

    if not stems:
        raise RuntimeError(f"produccion: ninguna pista de {ruta.name} produjo "
                           "senal audible (renders vacios o en silencio)")

    n_max = max(s.shape[1] for s in stems)
    suma = np.zeros((2, n_max), dtype="float32")
    for s in stems:
        suma[:, :s.shape[1]] += s

    y = _masterizar(suma, genero)
    salida = Path(wav_salida) if wav_salida else ruta.with_name(f"{ruta.stem}_{genero}.wav")
    salida.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(salida), y.T, SR, subtype="FLOAT")
    return str(salida)


# ---------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.produccion",
        description="Mezcla y masteriza un MIDI por stems con cadenas por rol y genero")
    ap.add_argument("midi", help="archivo .mid de entrada")
    ap.add_argument("--genero", choices=list(GENEROS), default="orquestal")
    ap.add_argument("--salida", default=None, help="ruta del wav (default: <midi>_<genero>.wav)")
    ap.add_argument("--chiptune", action="store_true",
                    help="videojuegos: bitcrush suave en melodia y acompanamiento")
    ap.add_argument("--phaser", action="store_true",
                    help="electro: phaser en los pads del acompanamiento")
    ap.add_argument("--timeout", type=float, default=600,
                    help="segundos por render de pista (fluidsynth)")
    args = ap.parse_args(argv)
    try:
        salida = producir(args.midi, args.salida, genero=args.genero,
                          timeout=args.timeout, chiptune=args.chiptune,
                          phaser=args.phaser)
    except Exception as e:
        print(f"produccion: FALLO {args.midi}: {e}", file=sys.stderr)
        return 1
    print(f"produccion: OK {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
