# -*- coding: utf-8 -*-
"""Cuánto ocupa el prompt de REPARACIÓN frente al de generación.

El prompt de reparación es enunciado + código roto + contraejemplo. Si no cabe
en n_ctx=16384 junto a max_tokens=8192, el modelo se queda sin sitio para
PENSAR y el resultado se leería como "no supo reparar" cuando es el arnés
quien no le dejó — el 8º caso del mismo bug en este repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb, prompt_lcb
from b3_reparacion import prompt_reparar

tareas = [t for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
          if t["dificultad"] == "hard"]
print(f"tareas hard: {len(tareas)}")

CODIGO_TIPICO = "\n".join(["def solve():"] + ["    x = 1"] * 60 + ["solve()"])
ce = {"entrada": "x" * 1200, "esperada": "y" * 1200, "obtenida": "z" * 1200,
      "excepcion": ""}

gen, rep = [], []
for t in tareas:
    gen.append(len(prompt_lcb(t)))
    rep.append(len(prompt_reparar(t, CODIGO_TIPICO, ce)))

gen.sort()
rep.sort()


def pct(xs, p):
    return xs[min(len(xs) - 1, int(p * len(xs)))]


# ~3.5 caracteres por token es la regla conservadora para inglés+código
for nombre, xs in (("generacion", gen), ("reparacion (peor caso)", rep)):
    print(f"\n{nombre}:")
    print(f"  chars  mediana {pct(xs,.5):>7}  p90 {pct(xs,.9):>7}  "
          f"max {xs[-1]:>7}")
    print(f"  tokens~ mediana {pct(xs,.5)//3.5:>7.0f}  p90 {pct(xs,.9)//3.5:>7.0f}"
          f"  max {xs[-1]//3.5:>7.0f}")

peor = xs[-1] // 3.5
print(f"\nn_ctx = 16384 ; max_tokens = 8192  ->  para el prompt quedan 8192 tok")
print(f"peor prompt de reparacion ~{peor:.0f} tok  "
      f"=> {'CABE' if peor < 8192 else 'NO CABE: hay que capar el enunciado'}")
n_no_caben = sum(1 for x in rep if x / 3.5 >= 8192)
print(f"prompts de reparacion que NO caben: {n_no_caben}/{len(rep)} "
      f"({n_no_caben/len(rep):.1%})")
n_gen_no = sum(1 for x in gen if x / 3.5 >= 8192)
print(f"prompts de GENERACION que no caben:  {n_gen_no}/{len(gen)} "
      f"({n_gen_no/len(gen):.1%})   [asi corrio anoche]")
