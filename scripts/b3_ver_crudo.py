# -*- coding: utf-8 -*-
"""Imprime el texto CRUDO de las muestras con fallo de instrumento.

Reproducir un caso a mano antes de contarlo como fallo del modelo es la regla
más cara aprendida en este repo: anoche 107 muestras (16%) marcadas como fallo
eran del entorno, y re-juzgarlas movió el pass@1 siete puntos.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"

f = sys.argv[1] if len(sys.argv) > 1 else "reparacion.json"
motivo_filtro = sys.argv[2] if len(sys.argv) > 2 else "sin_codigo_extraible"
d = json.loads((SALIDA / f).read_text(encoding="utf-8"))

for m in d["muestras"]:
    if m.get("cierre") or m.get("instrumento") != motivo_filtro:
        continue
    print("=" * 70)
    print(f"tarea={m['tarea']} brazo={m['brazo']} idx={m['idx']} "
          f"tok_prompt={m.get('tok_prompt')} tok_salida={m.get('tok_salida')} "
          f"seg={m['segundos']}")
    print("=" * 70)
    print(repr(m["crudo"]))
    print()
