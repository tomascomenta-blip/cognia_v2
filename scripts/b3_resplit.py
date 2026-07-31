# -*- coding: utf-8 -*-
"""
b3_resplit.py — RÉPLICA del experimento con OTRO examen, sin gastar GPU.

El resultado de B-LCB depende de qué 5 casos privados cayeron del lado
VISIBLE. Si el neto BoN−AZAR solo existe con ese sorteo, no es un mecanismo:
es una tirada. Y esa es exactamente la clase de conclusión que esta semana ya
firmó tres veces en falso.

Aquí se re-juzgan LOS MISMOS códigos ya generados con un split distinto
(otra semilla), así que:

  - la generación no se repite (0 GPU, 0 varianza entre corridas),
  - el apareado es perfecto: mismas muestras, mismo modelo, mismo minuto,
  - lo único que cambia es el EXAMEN.

Si el neto sobrevive a varias semillas de split, el mecanismo es del selector.
Si desaparece, era del sorteo — y se dice.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_resplit.py lcb.json --semillas 3
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import (LCB_VISIBLES, SALIDA, carga_lcb, extract_code,
                       juzga_lcb, tests_lcb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fichero")
    ap.add_argument("--semillas", type=int, default=3,
                    help="cuántos splits alternativos re-juzgar")
    args = ap.parse_args()

    p = Path(args.fichero)
    if not p.is_absolute():
        p = SALIDA / args.fichero
    base = json.loads(p.read_text(encoding="utf-8"))
    if base["banco"] != "lcb":
        print("solo aplica a B-LCB (MBPP tiene 3 asserts: no hay margen)")
        return

    tareas = {t["question_id"] if "question_id" in t else t["task_id"]: t
              for t in carga_lcb()}
    por_id = {str(k): v for k, v in tareas.items()}

    # CONTROL DE FIDELIDAD: re-juzgar con el split ORIGINAL tiene que
    # reproducir los veredictos originales. Si no, el `crudo` guardado está
    # truncado (se corta a 6000 chars) y toda réplica estaría sesgada a la
    # baja — un fallo de instrumento disfrazado de resultado.
    disc = n_ctrl = 0
    for m in base["muestras"]:
        t = por_id.get(m["tarea"])
        if t is None:
            continue
        vis, oc = tests_lcb(t, random.Random(f"{base['semilla']}:{m['tarea']}"))
        if not vis or not oc:
            continue
        code = extract_code(m.get("crudo") or "")
        oc_ok, _ = juzga_lcb(code, t, oc, parar_al_fallar=True)
        n_ctrl += 1
        if (oc_ok == len(oc)) != m["pasa_oc"]:
            disc += 1
    print(f"[control de fidelidad] re-juicio con el split ORIGINAL: "
          f"{disc}/{n_ctrl} veredictos discrepan "
          f"({disc/max(1,n_ctrl):.1%})", flush=True)
    if disc / max(1, n_ctrl) > 0.02:
        print(f"[!] ABORTA: más del 2% discrepa — el crudo guardado no basta "
              f"para re-juzgar; la réplica estaría sesgada.", flush=True)
        return

    for extra in range(1, args.semillas + 1):
        semilla = base["semilla"] + extra * 1000
        salida = SALIDA / f"lcb_resplit{extra}.json"
        res = dict(base)
        res["muestras"] = []
        res["semilla_split"] = semilla
        res["derivado_de"] = p.name
        # OJO: 'semilla' se deja igual que el original para que el conjunto
        # de TAREAS sea idéntico; lo que cambia es solo el sorteo del split.
        t0 = time.time()
        hechas = 0
        for m in base["muestras"]:
            t = por_id.get(m["tarea"])
            if t is None:
                continue
            vis, oc = tests_lcb(t, random.Random(f"{semilla}:{m['tarea']}"))
            if not vis or not oc:
                continue
            code = extract_code(m.get("crudo") or "")
            vis_ok, mv = juzga_lcb(code, t, vis)
            oc_ok, mo = juzga_lcb(code, t, oc, parar_al_fallar=True)
            n = dict(m)
            n.update(vis_ok=vis_ok, vis_n=len(vis), oc_ok=oc_ok, oc_n=len(oc),
                     pasa_vis=vis_ok == len(vis),
                     pasa_oc=oc_ok == len(oc),
                     juez_vis=mv, juez_oc=mo)
            res["muestras"].append(n)
            hechas += 1
            if hechas % 50 == 0:
                print(f"  [split{extra}] {hechas}/{len(base['muestras'])} "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)
        tmp = salida.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, salida)
        ok = sum(1 for x in res["muestras"] if x["pasa_oc"])
        print(f"[split{extra}] semilla={semilla}  {hechas} muestras  "
              f"pass@1={ok/max(1,hechas):.1%}  -> {salida}", flush=True)


if __name__ == "__main__":
    main()
