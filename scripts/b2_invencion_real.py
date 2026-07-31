#!/usr/bin/env python
"""
b2_invencion_real.py — ¿el valor es INVENTADO o solo aparece tras interactuar?

PREREG_ADAPTADOR_ANTIINVENCION_20260730. Cero GPU. **El número que faltaba.**

EL PROBLEMA CON LA MEDICIÓN ANTERIOR. `b2_selector_equivocado.py` buscó los
literales en la página **en reposo** y dejó un 67.3% de "VALOR_AUSENTE" que NO
es interpretable: un `540.00` que solo aparece **después** de escribir 60 en
`#cant` cuenta como ausente aunque el producto lo genere perfectamente.

LA SOLUCIÓN, sin tocar el juez de producción: por cada check crítico fallido
se arma un contrato con **ese check y un paso final que vuelca el DOM**. El
juez ejecuta las acciones del check tal cual y el volcado captura el estado
**justo después**. Entonces:

  - el literal aparece en ese volcado -> **SELECTOR_EQUIVOCADO**: la página SÍ
    produce el valor, el check lo busca donde no es
  - no aparece ni siquiera después de interactuar -> **INVENTADO/AUSENTE**: el
    producto no genera ese valor en ningún sitio

Esa es la separación limpia que decide la función objetivo del adaptador.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402
from cognia.program_creator import juez_ejecutable                        # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"

_JS_VOLCADO = ("(() => { const t=[document.body.innerText||'']; "
               "document.querySelectorAll('input,textarea,select')"
               ".forEach(e=>t.push(e.value||'')); return t.join(' | '); })()")


def _literales(paso: dict) -> list:
    subs = paso["acciones"] if isinstance(paso.get("acciones"), list) else [paso]
    out = []
    for s in subs:
        for k in ("contiene", "esperado"):
            if k in s and isinstance(s[k], (str, int, float)):
                v = str(s[k]).strip()
                if v and v not in ("True", "False"):
                    out.append(v)
    return out


def main() -> int:
    juicios = json.loads((SALIDA / "juicios.json").read_text(encoding="utf-8"))
    pasos = {}
    for f in json.loads((SALIDA / "indice.json").read_text(
            encoding="utf-8"))["filas"]:
        if not f["ok"]:
            continue
        corpus, carpeta = f["pagina"].split("/", 1)
        c = json.loads((GENERADOS / corpus / carpeta / "contrato_interno.json")
                       .read_text(encoding="utf-8"))
        for p in c.get("pasos", []):
            pasos.setdefault((f["tarea"], p.get("nombre")), p)

    sanas = [f for f in juicios["filas"] if f.get("gt") and f.get("detalle")]
    cuenta, ejemplos, filas = Counter(), [], []
    t0 = time.time()
    hecho = 0
    for f in sanas:
        corpus, carpeta = f["pagina"].split("/", 1)
        html = GENERADOS / corpus / carpeta / "index.html"
        for c in f["detalle"]:
            if c["ok"] or not c["critico"]:
                continue
            paso = pasos.get((f["tarea"], c["n"]))
            if not paso:
                continue
            lits = _literales(paso)
            if not lits:
                continue
            # contrato de UN solo check + volcado del DOM justo despues
            mini = {"nombre": "sonda", "pasos": [
                {**paso, "critico": False},
                {"nombre": "__volcado__", "critico": False,
                 "accion": "js", "expr": _JS_VOLCADO}]}
            try:
                v = con_presupuesto(120, juez_ejecutable.juzgar_web, html, mini)
                dom = ""
                for ch in v.checks:
                    if ch.nombre == "__volcado__":
                        dom = str(ch.detalle)
                        break
            except (PresupuestoAgotado, Exception):              # noqa: B014
                continue
            hecho += 1
            for lit in lits:
                presente = lit in dom
                cuenta["SELECTOR_EQUIVOCADO" if presente
                       else "INVENTADO_O_AUSENTE"] += 1
                filas.append({"tarea": f["tarea"], "pagina": f["pagina"],
                              "check": c["n"], "literal": lit,
                              "presente_tras_actuar": presente})
                if presente and len(ejemplos) < 10:
                    ejemplos.append((f["tarea"], lit, c["n"][:48]))
            if hecho % 40 == 0:
                print(f"[{hecho}] {(time.time()-t0)/60:.1f} min", flush=True)

    (SALIDA / "invencion_real.json").write_text(
        json.dumps({"filas": filas}, ensure_ascii=False), encoding="utf-8")

    tot = sum(cuenta.values())
    print(f"\nchecks criticos fallidos sondeados: {hecho}")
    print(f"LITERALES evaluados TRAS EJECUTAR el check: {tot}")
    for c, n in cuenta.most_common():
        print(f"  {c:22s} {n:4d} ({100*n/max(1,tot):.1f}%)")
    print("\ncomparacion con la medicion EN REPOSO (b2_selector_equivocado):")
    print("  en reposo : SELECTOR_EQUIVOCADO 32.7% · ausente 67.3%")
    print("\nejemplos de valor que SI aparece tras interactuar:")
    for t, lit, ch in ejemplos:
        print(f"  [{t:20s}] {lit!r:14s} en el check {ch!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
