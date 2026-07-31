# -*- coding: utf-8 -*-
"""
b3_factorial.py — atribución del hueco contra la cifra publicada.

PREREG_CONDICIONES_OFICIALES_20260731. Mi pass@1 (51.8%) y el publicado (70)
difieren en CUATRO cosas a la vez: prompt, esfuerzo de razonamiento, evaluador
y ventana temporal. Compararlos sin separarlas no dice nada.

Factorial 2x2 en GENERACIÓN (prompt mío|oficial x esfuerzo low|high), leído con
DOS evaluadores sobre las MISMAS muestras (el mío: 5 visibles/15 ocultos
capados; el oficial: todos los casos sin cap). La ventana se cierra
restringiendo el banco al solape MEDIDO con la referencia (211 tareas).

Las cuatro celdas se generan INTERCALADAS a nivel tarea: si el reloj corta, el
diseño queda balanceado en vez de sesgado hacia la última celda.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_factorial.py --sonda
    venv312\\Scripts\\python.exe scripts\\b3_factorial.py --n 60 [--reanudar]
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

from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto
from b3_codigo import (SALIDA, SYSTEM_COD, carga_lcb, extract_code, genera,
                       juzga_lcb, prompt_lcb, tests_lcb)
from b3_oficial import SYSTEM_OFICIAL, casos_oficiales, juzga_oficial, \
    prompt_oficial

DESDE, HASTA = "2024-08-01", "2025-01-31"     # ventana de la referencia
# ENMIENDA 2 (2026-07-31 09:50), por RELOJ y por CONTEXTO, antes de que hubiera
# ninguna lectura: se cae la celda (mio, high). Las dos celdas `high` cuestan
# ~4x las `low` y con 4 celdas el ritmo medido era 4.3 min/tarea => ~30 tareas
# en la ventana, por debajo del N_min=35 que necesita LA celda que da el
# derecho a comparar. Con tres celdas se conserva el eje PROMPT (a esfuerzo
# low, que es donde es barato) y el eje ESFUERZO (con el prompt oficial, que es
# el que importa), y la celda (oficial, high) llega a su N.
CELDAS = [("mio", "low"), ("oficial", "low"), ("oficial", "high")]


def celdas_de(spec: str) -> list:
    """`--celdas mio_low,oficial_low`: recortar el diseño por RELOJ sin editar
    el fichero. Cada recorte se registra como enmienda del prereg."""
    if not spec:
        return list(CELDAS)
    out = []
    for x in spec.split(","):
        x = x.strip()
        if x:
            p, e = x.rsplit("_", 1)
            out.append((p, e))
    return out


def _prepara(t: dict) -> dict:
    t["_id"] = str(t["task_id"])
    t["_p_mio"] = prompt_lcb(t)
    t["_p_oficial"] = prompt_oficial(t)
    # MISMO examen que las corridas anteriores: RNG determinista POR TAREA
    t["_vis"], t["_oc"] = tests_lcb(t, random.Random(f"20260730:{t['_id']}"))
    return t


def carga_ventana(n: int, semilla: int) -> list:
    pool = [t for t in carga_lcb(ficheros=("lcb_test5.jsonl",
                                           "lcb_test6.jsonl"))
            if DESDE <= t["fecha"] <= HASTA]
    rng = random.Random(semilla)
    rng.shuffle(pool)
    out = []
    for t in pool:
        _prepara(t)
        if t["_vis"] and t["_oc"] and casos_oficiales(t):
            out.append(t)
        if len(out) >= n:
            break
    return out


def sonda_esfuerzo(tareas: list) -> None:
    """AMENAZA 2 del prereg: el esfuerzo REAL se fija por
    chat_template_kwargs, y una línea 'Reasoning: high' en el system NO hace
    nada (medido 3/3 en este repo). Antes de gastar la corrida se comprueba
    que `high` cambia algo VISIBLE."""
    t = tareas[0]
    print(f"[sonda] tarea {t['_id']} ({t['dificultad']})")
    for esf in ("low", "high"):
        ts = time.time()
        texto, motivo = genera(t["_p_oficial"], 0.8, 15000, esfuerzo=esf,
                               system=SYSTEM_OFICIAL)
        print(f"  esfuerzo={esf:<5} chars={len(texto):>6} "
              f"seg={time.time()-ts:>6.1f} motivo={motivo!r} "
              f"code={'si' if extract_code(texto) else 'NO'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--semilla", type=int, default=20260731)
    ap.add_argument("--pared", type=int, default=420)
    ap.add_argument("--max-tokens", dest="max_tokens", type=int, default=15000)
    ap.add_argument("--sufijo", default="")
    ap.add_argument("--sonda", action="store_true")
    ap.add_argument("--celdas", default="",
                    help="subconjunto de celdas, p.ej. 'mio_low,oficial_low'")
    ap.add_argument("--minutos", type=int, default=0,
                    help="corte por RELOJ: para ANTES de empezar una tarea "
                         "nueva, para que el diseno quede BALANCEADO (las 4 "
                         "celdas de cada tarea, o ninguna)")
    ap.add_argument("--reanudar", action="store_true")
    args = ap.parse_args()

    celdas = celdas_de(args.celdas)
    SALIDA.mkdir(exist_ok=True)
    fichero = SALIDA / f"factorial{args.sufijo}.json"
    print(f"[fac] celdas: {['%s_%s' % c for c in celdas]}", flush=True)
    tareas = carga_ventana(args.n, args.semilla)
    print(f"[fac] tareas={len(tareas)} ventana {DESDE}..{HASTA}", flush=True)
    if args.sonda:
        sonda_esfuerzo(tareas)
        return

    res = {"experimento": "condiciones_oficiales",
           "prereg": "PREREG_CONDICIONES_OFICIALES_20260731.md",
           "temp": args.temp, "semilla": args.semilla, "n_pedidas": args.n,
           "max_tokens": args.max_tokens, "ventana": [DESDE, HASTA],
           "muestras": []}
    if fichero.exists():
        if not args.reanudar:
            print(f"ABORTA: {fichero} existe y sin --reanudar lo "
                  f"SOBRESCRIBIRÍA en silencio.", flush=True)
            sys.exit(2)
        res = json.loads(fichero.read_text(encoding="utf-8"))
        for campo, valor in (("semilla", args.semilla), ("temp", args.temp),
                             ("max_tokens", args.max_tokens)):
            if res.get(campo) != valor:
                print(f"ABORTA: el fichero tiene {campo}={res.get(campo)!r} y "
                      f"se pide {valor!r}.", flush=True)
                sys.exit(2)
        print(f"[fac] reanudando: {len(res['muestras'])} muestras", flush=True)
    # una tarea solo cuenta si tiene sus CUATRO celdas: el balance del diseño
    # es lo que hace legible un corte por reloj
    por_tarea = {}
    for m in res["muestras"]:
        por_tarea.setdefault(m["tarea"], set()).add(m["celda"])
    hechas = {t for t, c in por_tarea.items() if len(c) == len(celdas)}
    antes = len(res["muestras"])
    res["muestras"] = [m for m in res["muestras"] if m["tarea"] in hechas]
    if antes != len(res["muestras"]):
        print(f"[fac] descartados {antes-len(res['muestras'])} registros de "
              f"tareas sin las 4 celdas", flush=True)

    def guardar():
        tmp = fichero.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero)

    t0 = time.time()
    for i, t in enumerate(tareas):
        if t["_id"] in hechas:
            continue
        if args.minutos and (time.time() - t0) / 60 >= args.minutos:
            print(f"[fac] CORTE POR RELOJ a los {args.minutos} min con "
                  f"{len(hechas)} tareas de 4 celdas", flush=True)
            break
        oficiales = casos_oficiales(t)
        for prom, esf in celdas:
            ts = time.time()
            p = t["_p_oficial"] if prom == "oficial" else t["_p_mio"]
            sysmsg = SYSTEM_OFICIAL if prom == "oficial" else SYSTEM_COD
            try:
                texto, motivo = con_presupuesto(
                    args.pared, genera, p, args.temp, args.max_tokens,
                    esf, sysmsg)
            except PresupuestoAgotado:
                texto, motivo = "", f"presupuesto_pared_{args.pared}s"
            code = extract_code(texto)
            if not code and not motivo:
                motivo = "sin_codigo_extraible"
            # JUEZ MÍO (el de las corridas anteriores)
            vis_ok, m_vis = juzga_lcb(code, t, t["_vis"])
            oc_ok, m_oc = juzga_lcb(code, t, t["_oc"], parar_al_fallar=True)
            # JUEZ OFICIAL (todos los casos, sin cap)
            of_pasa, m_of = juzga_oficial(code, t, oficiales)
            res["muestras"].append({
                "tarea": t["_id"], "celda": f"{prom}_{esf}",
                "prompt": prom, "esfuerzo": esf,
                "dificultad": t["dificultad"], "fecha": t["fecha"],
                "plataforma": t["plataforma"],
                "mio_pasa": oc_ok == len(t["_oc"]) and len(t["_oc"]) > 0,
                "mio_vis_ok": vis_ok, "mio_vis_n": len(t["_vis"]),
                "mio_oc_ok": oc_ok, "mio_oc_n": len(t["_oc"]),
                "oficial_pasa": bool(of_pasa),
                "oficial_n_casos": len(oficiales),
                "instrumento": motivo, "juez_mio": m_vis or m_oc,
                "juez_oficial": m_of,
                "segundos": round(time.time() - ts, 1),
                "chars": len(texto), "prompt_chars": len(p),
                "crudo": texto[:6000],
            })
            guardar()
        hechas.add(t["_id"])
        n_h = len({m["tarea"] for m in res["muestras"]})
        ms = res["muestras"]
        trunc = sum(1 for m in ms
                    if m["instrumento"] == "truncado_por_longitud")
        print(f"[fac] tarea {i+1}/{len(tareas)} completas={n_h} "
              f"muestras={len(ms)} truncadas={trunc} "
              f"({trunc/max(1,len(ms)):.1%}) "
              f"({(time.time()-t0)/60:.0f} min)", flush=True)

    guardar()
    print(f"[fac] FIN -> {fichero}", flush=True)


if __name__ == "__main__":
    main()
