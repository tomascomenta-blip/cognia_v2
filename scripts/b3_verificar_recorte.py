# -*- coding: utf-8 -*-
"""Verificación PROPIA del número que midió el revisor adversarial.

El revisor reportó que la política vieja del contraejemplo (el PRIMER visible
fallido) dejaba el 24.4% con la entrada recortada, y la nueva (el de entrada
MÁS CORTA) el 4.9%. Ese número entró en MANAGER_LOG, así que se comprueba con
código propio antes de firmarlo — la regla es verificar uno mismo lo que
devuelven los subagentes.

Se replica sobre las muestras `s=1` de `lcb_hard_r2.json` (código real ya
generado), con el mismo RNG de split por tarea.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import SALIDA, carga_lcb, extract_code, juzga_lcb, tests_lcb
from b3_reparacion import TOPE_CAMPO

res = json.loads((SALIDA / "lcb_hard_r2.json").read_text(encoding="utf-8"))
tareas = {str(t["task_id"]): t for t in carga_lcb()}

viejo_rec = nuevo_rec = patologico = total = 0
for m in res["muestras"]:
    if m["s"] != 1:
        continue
    t = tareas.get(m["tarea"])
    if not t:
        continue
    vis, _ = tests_lcb(t, random.Random(f"20260730:{m['tarea']}"))
    code = extract_code(m.get("crudo") or "")
    if not code or not vis:
        continue
    det = {}
    ok, _mot = juzga_lcb(code, t, vis, detalle=det)
    fallidos = [i for i in range(len(vis)) if i in det]
    if not fallidos:
        continue
    total += 1
    # POLÍTICA VIEJA: el primer fallido por índice
    v = vis[fallidos[0]]
    ent_v = v.get("input") or ""
    if len(ent_v) > TOPE_CAMPO:
        viejo_rec += 1
        # el patrón patológico: entrada recortada + salida esperada COMPLETA
        if len(v.get("output") or "") <= TOPE_CAMPO:
            patologico += 1
    # POLÍTICA NUEVA: el de entrada más corta
    j = min(fallidos, key=lambda k: (len(vis[k].get("input") or ""), k))
    if len(vis[j].get("input") or "") > TOPE_CAMPO:
        nuevo_rec += 1

print(f"contraejemplos construibles: {total}")
print(f"  politica VIEJA (primer fallido) recortados: {viejo_rec}/{total} "
      f"({viejo_rec/max(1,total):.1%})   [el revisor dijo 24.4%]")
print(f"     de esos, patron PATOLOGICO (entrada cortada + esperada entera): "
      f"{patologico}")
print(f"  politica NUEVA (entrada mas corta) recortados: {nuevo_rec}/{total} "
      f"({nuevo_rec/max(1,total):.1%})   [el revisor dijo 4.9%]")
print(f"  MEJORA: {viejo_rec-nuevo_rec} contraejemplos dejan de llegar "
      f"mutilados")
