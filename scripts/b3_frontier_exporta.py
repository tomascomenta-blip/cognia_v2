# -*- coding: utf-8 -*-
"""b3_frontier_exporta.py — exporta las tareas del benchmark frontier.

DISENO_REFERENCIA_FRONTIER_20260731.md (enmienda 1): las MISMAS 60 tareas de
factorial.json, con el MISMO prompt oficial, para que el contraste
frontier vs gpt-oss-20b(oficial_low) sea apareado tarea a tarea.

Escribe b3_codigo/frontier_tareas.json: [{id, dificultad, prompt}] en el
orden de factorial.json. Sin GPU.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_factorial import carga_ventana
from b3_oficial import SYSTEM_OFICIAL


def main():
    import argparse
    ap = argparse.ArgumentParser()
    # enmienda 3 del diseño: --n 198 amplía al marco completo del solape
    # filtrado. El sorteo es determinista: las 60 primeras no cambian.
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args()

    fac = json.loads((RAIZ / "b3_codigo" / "factorial.json")
                     .read_text(encoding="utf-8"))
    orden = []
    for m in fac["muestras"]:
        if m["tarea"] not in orden:
            orden.append(m["tarea"])
    ventana = carga_ventana(args.n, fac["semilla"])
    tareas = {t["_id"]: t for t in ventana}
    # prefijo verificado: las tareas de factorial.json tienen que ser las
    # primeras del sorteo ampliado, en el mismo orden
    ids_v = [t["_id"] for t in ventana]
    if ids_v[:len(orden)] != orden:
        print("[!] el sorteo ampliado NO conserva el prefijo de "
              "factorial.json: ABORTA")
        sys.exit(2)
    out = []
    for tid in ids_v:
        t = tareas.get(tid)
        if t is None:
            print(f"[!] {tid} no está en carga_ventana({args.n}): ABORTA "
                  f"(los bancos habrían cambiado)")
            sys.exit(2)
        out.append({"id": tid, "dificultad": t["dificultad"],
                    "fecha": t["fecha"],
                    "prompt": t["_p_oficial"]})
    destino = RAIZ / "b3_codigo" / "frontier_tareas.json"
    destino.write_text(json.dumps(
        {"system_oficial": SYSTEM_OFICIAL, "tareas": out},
        indent=1, ensure_ascii=False), encoding="utf-8")
    tam = destino.stat().st_size
    print(f"{len(out)} tareas -> {destino.name} ({tam/1024:.0f} KB)")
    print("dificultades:", {d: sum(1 for x in out if x['dificultad'] == d)
                            for d in ('easy', 'medium', 'hard')})


if __name__ == "__main__":
    main()
