# -*- coding: utf-8 -*-
"""Qué parte del banco cae dentro de la ventana de la referencia publicada.

La única cifra publicada que he encontrado para gpt-oss-20b en LiveCodeBench
(blog.collinear.ai/p/gpt-oss-lcb) es **pass@1 = 70 en LCB v6, ventana
2024-08-01 → 2025-01-31, 3 muestras por problema, reasoning HIGH, 64k de
secuencia**. No es una entrada del leaderboard oficial y no declara temperatura.

Antes de decir una sola palabra sobre si mi número es comparable, hay que medir
CUÁNTO del banco que tengo cae dentro de esa ventana. Es exactamente el error
que firmé dos veces ayer (declarar una ventana sin abrir el fichero).
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb

DESDE, HASTA = "2024-08-01", "2025-01-31"

for ficheros, etiq in ((("lcb_test6.jsonl",), "test6 solo (el de anoche)"),
                       (("lcb_test5.jsonl", "lcb_test6.jsonl"), "AMPLIADO")):
    ts = carga_lcb(ficheros=ficheros)
    fechas = sorted(t["fecha"] for t in ts)
    dentro = [t for t in ts if DESDE <= t["fecha"] <= HASTA]
    print(f"\n{etiq}: {len(ts)} tareas   ventana {fechas[0]} .. {fechas[-1]}")
    print(f"  dificultad: {dict(Counter(t['dificultad'] for t in ts))}")
    print(f"  DENTRO de [{DESDE}, {HASTA}]: {len(dentro)}/{len(ts)} "
          f"({len(dentro)/len(ts):.1%})")
    if dentro:
        fd = sorted(t["fecha"] for t in dentro)
        print(f"    su ventana real: {fd[0]} .. {fd[-1]}")
        print(f"    dificultad: {dict(Counter(t['dificultad'] for t in dentro))}")
        print(f"    plataforma: {dict(Counter(t['plataforma'] for t in dentro))}")
    fuera_ini = [t for t in ts if t["fecha"] < DESDE]
    print(f"  del banco NO cubierto por la referencia (posterior a {HASTA}): "
          f"{sum(1 for t in ts if t['fecha'] > HASTA)}")
    print(f"  anterior a {DESDE} (fuera por el otro lado): {len(fuera_ini)}")
