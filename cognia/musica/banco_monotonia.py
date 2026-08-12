# -*- coding: utf-8 -*-
"""Banco de monotonia: mide cuanto se repite una pieza MIDI.

POR QUE existe: la queja del dueno ("repiten y repiten el mismo ritmo") es
una sensacion; antes de tocar sampling o entrenar, hace falta un examen que
la convierta en numero. Sin este banco no se puede saber si una palanca
anti-monotonia funciono (leccion del repo: el banco va ANTES que la palanca).

Metricas por archivo (todas en [0,1]; MAS ALTO = MAS MONOTONO para las
tasas, MAS BAJO = MAS MONOTONO para las entropias):

- rep_ritmo   : fraccion de compases cuyo patron ritmico (onsets en grilla
                de fusas) es IDENTICO al del compas anterior de su pista.
                Es la metrica que captura "repite el mismo ritmo".
- rep_melodia : igual pero con la secuencia de pitches de la voz superior
                de la pista (ritmo Y notas clavadas = compas clonado).
- ent_ritmo   : entropia normalizada de la distribucion de patrones
                ritmicos distintos (0 = un unico patron para toda la pieza).
- ent_pc      : entropia normalizada de las pitch-classes (0 = una sola
                nota; 1 = las 12 por igual). Captura pobreza armonica.
- var_densidad: coeficiente de variacion de notas-por-compas a lo largo de
                la pieza (0 = misma densidad siempre; una pieza con climax
                y valles tiene CV alto).

El agregado `monotonia` pondera las cinco en una sola cifra [0,1] (mas alto
= peor) SOLO para ordenar corridas; las decisiones se toman mirando las
metricas crudas, nunca el agregado solo.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path


def _miditoolkit():
    try:
        import miditoolkit
        return miditoolkit
    except ImportError as e:
        raise ImportError(
            "banco_monotonia necesita miditoolkit (pip install miditoolkit)") from e


def _compases_ticks(midi, max_tick):
    """Limites [ini, fin) de cada compas segun los time signatures."""
    tpq = midi.ticks_per_beat
    sigs = sorted(midi.time_signature_changes, key=lambda s: s.time) or None
    limites, t, i = [], 0, 0
    num, den = (4, 4)
    while t < max_tick:
        if sigs:
            while i < len(sigs) and sigs[i].time <= t:
                num, den = sigs[i].numerator, sigs[i].denominator
                i += 1
        largo = round(tpq * 4 * num / den)
        limites.append((t, t + largo))
        t += largo
    return limites


def _patron(notas, ini, fin, tpq):
    """Patron ritmico del compas: onsets cuantizados a fusas, como tupla."""
    fusa = max(1, round(tpq / 8))
    return tuple(sorted({round((n.start - ini) / fusa)
                         for n in notas if ini <= n.start < fin}))


def _voz_superior(notas, ini, fin):
    """Secuencia de pitches de la voz mas aguda por onset del compas."""
    por_onset = {}
    for n in notas:
        if ini <= n.start < fin:
            por_onset[n.start] = max(por_onset.get(n.start, 0), n.pitch)
    return tuple(p for _, p in sorted(por_onset.items()))


def _entropia_norm(cuentas):
    """Entropia de Shannon normalizada por el maximo posible ([0,1])."""
    total = sum(cuentas)
    if total <= 0 or len(cuentas) <= 1:
        return 0.0
    h = -sum((c / total) * math.log2(c / total) for c in cuentas if c)
    return h / math.log2(len(cuentas)) if len(cuentas) > 1 else 0.0


def medir(ruta_mid) -> dict:
    """Metricas de monotonia de UN archivo. Ver el docstring del modulo."""
    mt = _miditoolkit()
    midi = mt.MidiFile(str(ruta_mid))
    tpq = midi.ticks_per_beat
    max_tick = max((n.end for i in midi.instruments for n in i.notes), default=tpq * 4)
    compases = _compases_ticks(midi, max_tick)

    rep_r, rep_m, comparables = 0, 0, 0
    patrones_globales: Counter = Counter()
    densidad = [0] * len(compases)

    for inst in midi.instruments:
        if not inst.notes:
            continue
        notas = sorted(inst.notes, key=lambda n: (n.start, n.pitch))
        previo_patron, previo_voz = None, None
        for ci, (ini, fin) in enumerate(compases):
            pat = _patron(notas, ini, fin, tpq)
            voz = _voz_superior(notas, ini, fin)
            densidad[ci] += sum(1 for n in notas if ini <= n.start < fin)
            if pat:
                patrones_globales[pat] += 1
                if previo_patron:
                    comparables += 1
                    if pat == previo_patron:
                        rep_r += 1
                        if voz and voz == previo_voz:
                            rep_m += 1
                previo_patron, previo_voz = pat, voz
            # compas en silencio: no rompe la cadena (un respiro entre dos
            # compases clonados no los vuelve variados)

    densidad_activa = [d for d in densidad if d > 0]
    media_d = sum(densidad_activa) / len(densidad_activa) if densidad_activa else 0.0
    if media_d > 0 and len(densidad_activa) > 1:
        var = sum((d - media_d) ** 2 for d in densidad_activa) / len(densidad_activa)
        cv = math.sqrt(var) / media_d
    else:
        cv = 0.0

    pcs = Counter(n.pitch % 12 for i in midi.instruments if not i.is_drum
                  for n in i.notes)
    ent_pc = _entropia_norm([pcs.get(k, 0) for k in range(12)]) if pcs else 0.0

    m = {
        "rep_ritmo": round(rep_r / comparables, 4) if comparables else 0.0,
        "rep_melodia": round(rep_m / comparables, 4) if comparables else 0.0,
        "ent_ritmo": round(_entropia_norm(list(patrones_globales.values())), 4),
        "ent_pc": round(ent_pc, 4),
        "var_densidad": round(min(cv, 1.0), 4),
        "compases": len(compases),
    }
    # agregado: promedio de "senales de monotonia" (tasas directas, entropias
    # y variacion invertidas). Solo para ordenar; decidir con las crudas.
    m["monotonia"] = round((m["rep_ritmo"] + m["rep_melodia"]
                            + (1 - m["ent_ritmo"]) + (1 - m["ent_pc"])
                            + (1 - m["var_densidad"])) / 5, 4)
    return m


def medir_lote(rutas) -> dict:
    """Media por metrica sobre varios archivos (para comparar corridas)."""
    filas = {str(r): medir(r) for r in rutas}
    if not filas:
        return {"archivos": {}, "media": {}}
    claves = [k for k in next(iter(filas.values())) if k != "compases"]
    media = {k: round(sum(f[k] for f in filas.values()) / len(filas), 4)
             for k in claves}
    return {"archivos": filas, "media": media}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.banco_monotonia",
        description="Mide la monotonia de MIDIs (mas alto = mas monotono)")
    ap.add_argument("ruta", help=".mid o directorio (recursivo, salta .crudo.mid)")
    ap.add_argument("--json", action="store_true", help="salida JSON completa")
    args = ap.parse_args(argv)

    ruta = Path(args.ruta)
    if ruta.is_dir():
        rutas = sorted(p for p in ruta.rglob("*.mid")
                       if not p.name.endswith(".crudo.mid"))
    elif ruta.is_file():
        rutas = [ruta]
    else:
        print(f"banco_monotonia: no existe {ruta}", file=sys.stderr)
        return 2
    if not rutas:
        print(f"banco_monotonia: sin .mid en {ruta}", file=sys.stderr)
        return 2

    lote = medir_lote(rutas)
    if args.json:
        print(json.dumps(lote, ensure_ascii=False, indent=1))
    else:
        for r, m in lote["archivos"].items():
            print(f"{Path(r).name}: monotonia={m['monotonia']:.3f} "
                  f"rep_ritmo={m['rep_ritmo']:.3f} rep_melodia={m['rep_melodia']:.3f} "
                  f"ent_ritmo={m['ent_ritmo']:.3f} ent_pc={m['ent_pc']:.3f} "
                  f"var_densidad={m['var_densidad']:.3f}")
        med = lote["media"]
        print(f"MEDIA ({len(lote['archivos'])} archivos): "
              f"monotonia={med['monotonia']:.3f} rep_ritmo={med['rep_ritmo']:.3f} "
              f"rep_melodia={med['rep_melodia']:.3f} ent_ritmo={med['ent_ritmo']:.3f} "
              f"ent_pc={med['ent_pc']:.3f} var_densidad={med['var_densidad']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
