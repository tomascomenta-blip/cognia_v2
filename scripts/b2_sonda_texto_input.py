#!/usr/bin/env python
"""
b2_sonda_texto_input.py — ¿cuánto del ACUSA_SANOS explica el bug de FORMA?

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (sonda del 41%). Cero GPU.

QUÉ HACE. La taxonomía encontró que **113 de los 275 checks que fallan en
todas las páginas sanas (41.1%)** son una aserción de `texto` sobre un
`<input>`: no pueden pasar jamás porque `innerText` de un campo es vacío, dé
igual el valor. Aquí se reescriben **mecánicamente** esos checks para que lean
`.value` con `js`, y se re-juzgan las MISMAS páginas con los MISMOS contratos.

Es una transformación puramente sintáctica —no cambia qué se comprueba ni
contra qué valor, solo cómo se lee el campo— así que cualquier cambio en el
veredicto es atribuible al instrumento.

Es una sonda más limpia que el modo `corregido` que el repo ya mató: aquel
REGENERABA el contrato con otro prompt, mezclando el fix con un contrato
distinto. Aquí el contrato es el mismo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402
from cognia.program_creator import juez_ejecutable                        # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"
PRESUPUESTO = 300

RE_CAMPO = re.compile(r"input|textarea|#(cant|nueva-cap|personas|pass|pass2|"
                      r"edad|q|txt|doc|desde|hasta|cupon|nuevo-stock)\b")


def _arreglar(sub: dict) -> tuple[dict, bool]:
    """`texto` sobre un campo -> `js` que lee .value. Mismo valor esperado."""
    if sub.get("accion") != "texto":
        return sub, False
    sel = str(sub.get("selector", ""))
    if not RE_CAMPO.search(sel):
        return sub, False
    esperado = sub.get("contiene")
    if esperado is None:
        return sub, False
    nuevo = dict(sub)
    nuevo["accion"] = "js"
    # includes() para conservar la semantica de "contiene" del original
    nuevo["expr"] = (f"(document.querySelector({sel!r})||{{}}).value"
                     f".includes({str(esperado)!r})")
    nuevo["esperado"] = True
    nuevo.pop("contiene", None)
    nuevo.pop("selector", None)
    return nuevo, True


def transformar(contrato: dict) -> tuple[dict, int]:
    n = 0
    pasos = []
    for p in contrato.get("pasos", []):
        p = dict(p)
        if isinstance(p.get("acciones"), list):
            subs = []
            for s in p["acciones"]:
                s2, cambiado = _arreglar(s)
                n += cambiado
                subs.append(s2)
            p["acciones"] = subs
        else:
            p2, cambiado = _arreglar(p)
            n += cambiado
            p = p2
        pasos.append(p)
    return {**contrato, "pasos": pasos}, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    args = ap.parse_args(argv)

    base = json.loads((SALIDA / "juicios.json").read_text(encoding="utf-8"))
    gt = {f["pagina"]: f["gt"] for f in base["filas"]}
    antes = {f["pagina"]: f["interno_aprueba"] for f in base["filas"]}

    f_out = SALIDA / "sonda_texto_input.json"
    res = (json.loads(f_out.read_text(encoding="utf-8"))
           if args.reanudar and f_out.is_file() else {"filas": []})
    hechas = {f["pagina"] for f in res["filas"]}

    pend = [f for f in base["filas"]
            if f["pagina"] not in hechas and f.get("gt") is not None]
    print(f"{len(pend)} paginas", flush=True)
    t0 = time.time()
    for k, f in enumerate(pend, 1):
        corpus, carpeta = f["pagina"].split("/", 1)
        d = GENERADOS / corpus / carpeta
        contrato = json.loads((d / "contrato_interno.json")
                              .read_text(encoding="utf-8"))
        arreglado, n_fix = transformar(contrato)
        if n_fix == 0:
            # ojo: la fila del juicio original usa `interno_aprueba`, no
            # `antes` — se normaliza aqui o el resumen revienta con KeyError
            res["filas"].append({
                "pagina": f["pagina"], "tarea": f["tarea"], "corpus": corpus,
                "gt": f["gt"], "antes": f["interno_aprueba"],
                "despues": f["interno_aprueba"], "n_fix": 0})
            continue
        try:
            v = con_presupuesto(PRESUPUESTO, juez_ejecutable.juzgar_web,
                                d / "index.html", arreglado)
            despues = bool(v.aprobado)
        except (PresupuestoAgotado, Exception):                 # noqa: B014
            despues = None
        res["filas"].append({"pagina": f["pagina"], "tarea": f["tarea"],
                             "corpus": corpus, "gt": f["gt"],
                             "antes": f["interno_aprueba"],
                             "despues": despues, "n_fix": n_fix})
        if k % 20 == 0:
            f_out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            print(f"[{k}/{len(pend)}] {(time.time()-t0)/60:.1f} min", flush=True)
    f_out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    tocadas = [f for f in res["filas"] if f["n_fix"] > 0]
    print(f"\npaginas con al menos un check reescrito: {len(tocadas)}"
          f"/{len(res['filas'])}   (checks reescritos: "
          f"{sum(f['n_fix'] for f in res['filas'])})")
    for etiq, filtro in (("BANCO DURO", lambda f: "duro" in f["corpus"]),
                         ("CABECERA", lambda f: "cabecera" in f["corpus"])):
        sub = [f for f in res["filas"] if filtro(f) and f["gt"]
               and f["despues"] is not None]
        if not sub:
            continue
        a = sum(1 for f in sub if f["antes"])
        b = sum(1 for f in sub if f["despues"])
        print(f"\n{etiq} (sanas n={len(sub)})")
        print(f"  aprueba ANTES   : {a}/{len(sub)} "
              f"-> ACUSA_SANOS {100*(1-a/len(sub)):.1f}")
        print(f"  aprueba DESPUES : {b}/{len(sub)} "
              f"-> ACUSA_SANOS {100*(1-b/len(sub)):.1f}")
        print(f"  --> ACUSA_SANOS baja {100*(b-a)/len(sub):.1f} pts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
