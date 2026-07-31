# -*- coding: utf-8 -*-
"""b3_anclaje_ver.py — imprime la muestra de auditoría agrupada por tarea."""
import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_contratos_ampliado")

quiere = sys.argv[1] if len(sys.argv) > 1 else "ausente_NO_anclado"
filas = [f for f in json.loads((DATOS / "auditoria_anclaje.json")
                               .read_text(encoding="utf-8"))
         if f["_muestra"] == quiere]

por = defaultdict(list)
for f in filas:
    por[f["tarea"]].append(f)

print(f"MUESTRA: {quiere}  ({len(filas)} filas, {len(por)} tareas)\n")
i = 0
for tarea, fs in sorted(por.items()):
    print("=" * 72)
    print(f"TAREA {tarea}")
    print(f"ENUNCIADO: {fs[0]['enunciado']}")
    print("-" * 72)
    for f in fs:
        i += 1
        print(f"  [{i:>2}] literal={f['literal']!r}")
        print(f"       check: {f['check']}")
    print()
