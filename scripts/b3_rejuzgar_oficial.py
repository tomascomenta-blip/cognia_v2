# -*- coding: utf-8 -*-
"""
b3_rejuzgar_oficial.py — el eje EVALUADOR de las condiciones oficiales, GRATIS.

PREREG_CONDICIONES_OFICIALES_20260731. Mi pass@1 y el publicado difieren en
cuatro cosas (prompt, esfuerzo, evaluador, ventana). El eje EVALUADOR se puede
medir SIN GASTAR UN TOKEN: el código de las 668 muestras de anoche está en
disco, así que basta volver a juzgarlo con el evaluador oficial de
LiveCodeBench — TODOS los casos (públicos + privados), sin cap de número ni de
tamaño, con su fórmula de timeout.

Es perfectamente apareado: las MISMAS muestras, dos jueces.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_rejuzgar_oficial.py [--limite 40]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import SALIDA, carga_lcb, extract_code
from b3_oficial import casos_oficiales, juzga_oficial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default="lcb_uniforme.json")
    ap.add_argument("--salida", default="lcb_juez_oficial.json")
    ap.add_argument("--ficheros", default="lcb_test6.jsonl")
    ap.add_argument("--limite", type=int, default=0,
                    help="piloto: solo las N primeras muestras")
    ap.add_argument("--minutos", type=int, default=0,
                    help="corte por reloj; lo hecho se guarda")
    ap.add_argument("--reanudar", action="store_true")
    args = ap.parse_args()

    res = json.loads((SALIDA / args.entrada).read_text(encoding="utf-8"))
    tareas = {str(t["task_id"]): t for t in carga_lcb(
        ficheros=tuple(x.strip() for x in args.ficheros.split(",")))}

    fichero = SALIDA / args.salida
    hechas = {}
    if fichero.exists() and args.reanudar:
        prev = json.loads(fichero.read_text(encoding="utf-8"))
        hechas = {(r["tarea"], r["s"]): r for r in prev["juicios"]}
        print(f"[of] reanudando: {len(hechas)} juicios en disco", flush=True)

    juicios = list(hechas.values())
    t0 = time.time()
    ms = res["muestras"][:args.limite] if args.limite else res["muestras"]
    for i, m in enumerate(ms):
        if (m["tarea"], m["s"]) in hechas:
            continue
        if args.minutos and (time.time() - t0) / 60 >= args.minutos:
            print(f"[of] CORTE POR RELOJ a los {args.minutos} min", flush=True)
            break
        t = tareas.get(m["tarea"])
        if not t:
            continue
        casos = casos_oficiales(t)
        code = extract_code(m.get("crudo") or "")
        ts = time.time()
        pasa, motivo = juzga_oficial(code, t, casos)
        juicios.append({
            "tarea": m["tarea"], "s": m["s"],
            "mio_pasa": bool(m["pasa_oc"]),
            "oficial_pasa": bool(pasa),
            "oficial_motivo": motivo,
            "n_casos_oficial": len(casos),
            "n_casos_mio": m["oc_n"],
            "instrumento_gen": m["instrumento"],
            "segundos_juez": round(time.time() - ts, 1),
        })
        if (i + 1) % 25 == 0:
            d = sum(1 for j in juicios if j["mio_pasa"] != j["oficial_pasa"])
            print(f"[of] {len(juicios)} juicios  discrepan {d} "
                  f"({d/max(1,len(juicios)):.1%})  "
                  f"({(time.time()-t0)/60:.1f} min)", flush=True)
            fichero.write_text(json.dumps(
                {"entrada": args.entrada, "juicios": juicios}, indent=1),
                encoding="utf-8")

    fichero.write_text(json.dumps(
        {"entrada": args.entrada, "juicios": juicios}, indent=1),
        encoding="utf-8")

    # --- lectura -------------------------------------------------------
    n = len(juicios)
    mio = sum(1 for j in juicios if j["mio_pasa"])
    ofi = sum(1 for j in juicios if j["oficial_pasa"])
    solo_mio = sum(1 for j in juicios if j["mio_pasa"]
                   and not j["oficial_pasa"])
    solo_of = sum(1 for j in juicios if j["oficial_pasa"]
                  and not j["mio_pasa"])
    exp = sum(1 for j in juicios if j["oficial_motivo"] == "lote_expirado")
    print(f"\n{'='*66}")
    print(f"EJE EVALUADOR — mismas {n} muestras, dos jueces")
    print(f"{'='*66}")
    print(f"  juez MIO     (5 vis / 15 oc capados) : {mio}/{n} "
          f"({mio/max(1,n):.1%})")
    print(f"  juez OFICIAL (todos los casos)       : {ofi}/{n} "
          f"({ofi/max(1,n):.1%})")
    print(f"  NETO (oficial - mio)                 : "
          f"{(ofi-mio)/max(1,n)*100:+.1f} pts")
    print(f"  pasa el mio y NO el oficial          : {solo_mio}  "
          f"[mi juez es MAS LAXO aqui: 15 ocultos, entradas <=100 KB]")
    print(f"  pasa el oficial y NO el mio          : {solo_of}")
    print(f"  lotes EXPIRADOS con el juez oficial  : {exp}/{n} "
          f"({exp/max(1,n):.1%})  [instrumento, no fallo del modelo]")
    # por tarea, para saber si el sesgo se concentra
    por = defaultdict(list)
    for j in juicios:
        por[j["tarea"]].append(j)
    tareas_dif = sum(1 for v in por.values()
                     if any(x["mio_pasa"] != x["oficial_pasa"] for x in v))
    print(f"  tareas con alguna discrepancia       : {tareas_dif}/{len(por)}")
    print(f"  segundos de juez oficial (total)     : "
          f"{sum(j['segundos_juez'] for j in juicios):.0f}")
    print(f"-> {fichero}")


if __name__ == "__main__":
    main()
