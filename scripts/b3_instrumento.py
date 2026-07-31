# -*- coding: utf-8 -*-
"""Reparto de los fallos de INSTRUMENTO de una corrida, por motivo y brazo.

Regla pre-registrada: si la tasa se dispara, se PARA y se reproduce un caso a
mano antes de analizar nada. Anoche 107 muestras (16%) contadas como fallo del
modelo eran un fallo transitorio del entorno; re-juzgarlas cambió 48 veredictos.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"

f = sys.argv[1] if len(sys.argv) > 1 else "reparacion.json"
d = json.loads((SALIDA / f).read_text(encoding="utf-8"))
ms = [m for m in d["muestras"] if not m.get("cierre")]

print(f"generaciones: {len(ms)}")
print(f"\n--- motivo de INSTRUMENTO (generacion) ---")
for k, v in Counter(m["instrumento"] for m in ms if m["instrumento"]).items():
    print(f"  {k:<32} {v:>4}")
print(f"\n--- motivo del JUEZ ---")
for campo in ("juez_vis", "juez_oc"):
    c = Counter(m.get(campo) for m in ms if m.get(campo))
    for k, v in c.items():
        print(f"  {campo}: {k:<24} {v:>4}")

print(f"\n--- por BRAZO ---")
for b in ("raiz", "bon", "rep", "pla"):
    sub = [m for m in ms if m["brazo"] == b]
    if not sub:
        continue
    inst = sum(1 for m in sub if m["instrumento"])
    print(f"  {b:<5} n={len(sub):>4}  instrumento {inst:>4} "
          f"({inst/len(sub):.1%})   "
          f"{dict(Counter(m['instrumento'] for m in sub if m['instrumento']))}")

print(f"\n--- muestras con instrumento, detalle ---")
for m in ms:
    if m["instrumento"]:
        print(f"  {m['tarea']:>9} {m['brazo']:<5} idx={m['idx']} "
              f"{m['instrumento']:<28} seg={m['segundos']:>6} "
              f"pchars={m['prompt_chars']:>5} "
              f"tok_salida={m.get('tok_salida')} chars_crudo={len(m['crudo'])}")
