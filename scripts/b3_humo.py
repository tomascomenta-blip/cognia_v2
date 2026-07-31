# -*- coding: utf-8 -*-
"""
b3_humo.py — humo del INSTRUMENTO, sin GPU y sin red.

Control POSITIVO: el código de referencia que MBPP trae en `code` tiene que
pasar sus propios asserts. Si no los pasa, el juez está roto y cualquier
número posterior mide el juez, no el modelo. (El repo ya se comió el caso
inverso: un contrato que reprueba páginas sanas.)

Control NEGATIVO: código deliberadamente roto tiene que fallar.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import (carga_lcb, carga_mbpp, extract_code, juzga_lcb,
                       juzga_mbpp, prompt_lcb, tests_mbpp)


def humo_mbpp(n=40, semilla=20260730):
    todas = carga_mbpp()
    pool = [t for t in todas if 11 <= t["task_id"] <= 510]
    rng = random.Random(semilla)
    rng.shuffle(pool)
    muestra = pool[:n]

    print(f"== MBPP: {len(todas)} tareas, slice 11-510 = {len(pool)} ==")
    n3 = sum(1 for t in todas if len(t.get("test_list") or []) == 3)
    ch = sum(1 for t in todas if t.get("challenge_test_list"))
    print(f"   con exactamente 3 asserts: {n3}/{len(todas)}")
    print(f"   con challenge_test_list no vacio: {ch}/{len(todas)}")

    ok_pos = fallos = 0
    sin_ocultos = 0
    t0 = time.time()
    for t in muestra:
        vis, oc = tests_mbpp(t)
        if not oc:
            sin_ocultos += 1
        v, _ = juzga_mbpp(t["code"], t, vis)
        o, _ = juzga_mbpp(t["code"], t, oc)
        if v == len(vis) and (not oc or o == len(oc)):
            ok_pos += 1
        else:
            fallos += 1
            if fallos <= 3:
                print(f"   [!] task {t['task_id']}: ref pasa vis {v}/{len(vis)}"
                      f" oc {o}/{len(oc)}")
    print(f"   CONTROL POSITIVO (codigo de referencia pasa sus tests): "
          f"{ok_pos}/{len(muestra)}  ({(time.time()-t0):.0f}s)")
    print(f"   tareas SIN tests ocultos (split degenerado): {sin_ocultos}"
          f"/{len(muestra)}")

    roto = "def _nada():\n    return 1\n"
    neg = sum(1 for t in muestra[:10]
              if juzga_mbpp(roto, t, tests_mbpp(t)[0])[0] == 0)
    print(f"   CONTROL NEGATIVO (codigo roto falla): {neg}/10")

    # ¿son REDUNDANTES los asserts? Un juez oculto que el selector ya implica
    # no mide nada nuevo. Se estima con mutantes: codigo de referencia
    # perturbado, ¿cuantas veces pasa visibles y falla ocultos?
    return ok_pos, len(muestra)


def humo_lcb():
    t0 = time.time()
    tareas = carga_lcb()
    print(f"\n== LiveCodeBench test6, post-corte (>2024-06-30) ==")
    print(f"   tareas utilizables: {len(tareas)}  ({time.time()-t0:.0f}s)")
    if not tareas:
        print("   [!] CERO tareas: el filtro o el decodificado fallan")
        return 0
    fechas = sorted(t["fecha"] for t in tareas)
    print(f"   ventana: {fechas[0]} .. {fechas[-1]}")
    from collections import Counter
    print(f"   plataforma: {dict(Counter(t['plataforma'] for t in tareas))}")
    print(f"   dificultad: {dict(Counter(t['dificultad'] for t in tareas))}")
    con_starter = sum(1 for t in tareas if t["starter_code"].strip())
    print(f"   con starter_code (functional): {con_starter}/{len(tareas)}")
    pub = [len(t['publicos']) for t in tareas]
    priv = [len(t['privados']) for t in tareas]
    print(f"   casos publicos  (selector): min={min(pub)} "
          f"mediana={sorted(pub)[len(pub)//2]} max={max(pub)}")
    print(f"   casos privados  (juez):     min={min(priv)} "
          f"mediana={sorted(priv)[len(priv)//2]} max={max(priv)}")
    t = tareas[0]
    print(f"   ejemplo: {t['task_id']} [{t['dificultad']}] {t['titulo']!r} "
          f"{t['fecha']} pub={len(t['publicos'])} priv={len(t['privados'])}")
    print(f"   prompt (200 chars): {prompt_lcb(t)[:200]!r}")
    return len(tareas)


if __name__ == "__main__":
    humo_mbpp()
    humo_lcb()
