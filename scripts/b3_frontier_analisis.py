# -*- coding: utf-8 -*-
"""
b3_frontier_analisis.py — contraste apareado frontier vs gpt-oss-20b.

DISENO_REFERENCIA_FRONTIER_20260731.md (enmiendas 1-2). Primaria: neto
apareado `frontier − gpt-oss(oficial_low)` sobre las 60 tareas comunes, juez
MÍO como primaria (idéntico en ambos brazos, sin topes de lote) y juez
oficial-con-mis-topes al lado (los estratos demasiado_grande/lote_expirado son
concordantes forzadas y se cuentan). Secundaria descriptiva: contra
oficial_high en las tareas donde exista.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
REPLICAS = 10000


def _perm(difs, semilla=20260731):
    obs = sum(difs)
    nz = [d for d in difs if d]
    if not nz:
        return 1.0
    rng = random.Random(semilla)
    dos = 0
    for _ in range(REPLICAS):
        s = sum(d if rng.random() < 0.5 else -d for d in nz)
        if abs(s) >= abs(obs):
            dos += 1
    return dos / REPLICAS


def _p1(gana, d):
    if d == 0:
        return 1.0
    return sum(comb(d, j) for j in range(gana, d + 1)) / 2 ** d


def _carga(nombre, celda):
    p = SALIDA / nombre
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {m["tarea"]: m for m in d["muestras"] if m["celda"] == celda}


def contraste(fro, base, etiqueta):
    comunes = sorted(set(fro) & set(base))
    if not comunes:
        return
    print(f"\n--- frontier − {etiqueta} — {len(comunes)} tareas apareadas ---")
    for juez in ("mio_pasa", "oficial_pasa"):
        difs = [int(bool(fro[t][juez])) - int(bool(base[t][juez]))
                for t in comunes]
        g = sum(1 for x in difs if x > 0)
        l = sum(1 for x in difs if x < 0)
        print(f"  juez {juez.split('_')[0].upper():<8} neto {sum(difs):+3d} "
              f"(gana {g}, pierde {l}, disc {g+l})  "
              f"P(1c) = {_p1(g, g+l):.2e}  P(2c) = {_perm(difs):.4f}")
    # por estrato de dificultad (juez mío)
    por_dif = defaultdict(lambda: [0, 0, 0])
    for t in comunes:
        d = fro[t].get("dificultad") or "?"
        por_dif[d][0] += 1
        por_dif[d][1] += int(bool(fro[t]["mio_pasa"]))
        por_dif[d][2] += int(bool(base[t]["mio_pasa"]))
    print(f"  por estrato (juez mío, frontier vs base):")
    for d in ("easy", "medium", "hard"):
        n, f, b = por_dif[d]
        if n:
            print(f"    {d:<7} n={n:<3} frontier {f}/{n}  base {b}/{n}")


def main():
    fro = _carga("frontier_resultados.json", "frontier_opus5")
    low = _carga("factorial.json", "oficial_low")
    high = _carga("factorial_high2.json", "oficial_high")

    n = len(fro)
    mio = sum(1 for m in fro.values() if m["mio_pasa"])
    ofi = sum(1 for m in fro.values() if m["oficial_pasa"])
    nj = [t for t, m in fro.items()
          if str(m.get("juez_oficial") or "").startswith(
              ("demasiado_grande", "lote_expirado"))]
    fallos_reales = [t for t, m in fro.items()
                     if not m["mio_pasa"]]
    print(f"{'='*70}")
    print(f"REFERENCIA FRONTIER (claude-opus-5 via plan, k=1, effort high)  "
          f"n={n}")
    print(f"{'='*70}")
    print(f"  juez MÍO: {mio}/{n} ({100*mio/max(1,n):.1f}%)   "
          f"juez OFICIAL-con-mis-topes: {ofi}/{n} ({100*ofi/max(1,n):.1f}%)")
    print(f"  no juzgables por mi juez oficial (>8MB/120s): {len(nj)} {nj}")
    print(f"  fallos REALES (juez mío): {fallos_reales}")

    contraste(fro, low, "gpt-oss oficial_low (PRIMARIA)")
    if high:
        contraste(fro, high, "gpt-oss oficial_high (descriptiva; "
                  "truncadas de high cuentan como fallo)")


if __name__ == "__main__":
    main()
