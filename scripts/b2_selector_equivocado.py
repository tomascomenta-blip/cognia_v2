#!/usr/bin/env python
"""
b2_selector_equivocado.py — ¿selector equivocado o valor inventado?

PREREG_ADAPTADOR_ANTIINVENCION_20260730. Cero GPU.

LA PREGUNTA. El diagnóstico dejó la hipótesis de que el contrato **apunta al
sitio equivocado**: comprueba un valor de SALIDA (`540.00`) contra el campo de
ENTRADA (`#cant`). Separarla de "valor inventado" es empírico y barato:

    para cada check FALLIDO con literal, ¿ese valor aparece en ALGÚN sitio de
    la página?

  - aparece en otro elemento -> **SELECTOR_EQUIVOCADO**: la página tiene el
    valor correcto, el check mira donde no es. El producto está bien y el
    examen mal.
  - no aparece en ninguna parte -> **VALOR_AUSENTE**: o el valor está
    inventado, o la página de verdad no lo produce.

Es descriptivo: no decide nada, cuantifica de qué está hecho el 88-94% de
ACUSA_SANOS.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"

# Todo el texto visible + todos los value de la página, para buscar el literal
_JS_TODO = """
() => {
  const t = [document.body.innerText || ''];
  document.querySelectorAll('input,textarea,select').forEach(e => t.push(e.value || ''));
  document.querySelectorAll('*').forEach(e => {
    for (const a of e.attributes) if (a.name.startsWith('data-')) t.push(a.value);
  });
  return t.join(' | ');
}
"""


def _literales(paso: dict) -> list:
    """(valor, selector) de cada sub-acción con literal."""
    subs = paso["acciones"] if isinstance(paso.get("acciones"), list) else [paso]
    out = []
    for s in subs:
        for k in ("contiene", "esperado"):
            if k in s and isinstance(s[k], (str, int, float)):
                v = str(s[k]).strip()
                if v and v not in ("True", "False"):
                    out.append((v, str(s.get("selector", ""))))
    return out


def _mirar(html: Path, valores: list) -> dict:
    from playwright.sync_api import sync_playwright
    from cognia.program_creator.juez_ejecutable import (MS_ASENTAR,
                                                        MS_TIMEOUT_CARGA)
    res = {}
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_page()
        page.set_default_timeout(5000)
        try:
            page.goto(html.resolve().as_uri(), wait_until="load",
                      timeout=MS_TIMEOUT_CARGA)
            page.wait_for_timeout(MS_ASENTAR)
            todo = page.evaluate(_JS_TODO)
        except Exception:
            todo = ""
        finally:
            nav.close()
    for v in valores:
        res[v] = v in todo
    return res


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

    cuenta = Counter()
    ejemplos = []
    sanas = [f for f in juicios["filas"] if f.get("gt") and f.get("detalle")]
    t0 = time.time()
    for k, f in enumerate(sanas, 1):
        corpus, carpeta = f["pagina"].split("/", 1)
        html = GENERADOS / corpus / carpeta / "index.html"
        pares = []
        for c in f["detalle"]:
            if c["ok"] or not c["critico"]:
                continue
            p = pasos.get((f["tarea"], c["n"]))
            if p:
                pares += _literales(p)
        if not pares:
            continue
        try:
            presente = con_presupuesto(120, _mirar, html,
                                       [v for v, _ in pares])
        except (PresupuestoAgotado, Exception):                  # noqa: B014
            continue
        for valor, sel in pares:
            if presente.get(valor):
                cuenta["SELECTOR_EQUIVOCADO"] += 1
                if len(ejemplos) < 12:
                    ejemplos.append((f["tarea"], valor, sel))
            else:
                cuenta["VALOR_AUSENTE"] += 1
        if k % 20 == 0:
            print(f"[{k}/{len(sanas)}] {(time.time()-t0)/60:.1f} min", flush=True)

    tot = sum(cuenta.values())
    print(f"\nLITERALES de checks CRITICOS FALLIDOS en paginas SANAS: {tot}")
    for c, n in cuenta.most_common():
        print(f"  {c:22s} {n:4d} ({100*n/max(1,tot):.1f}%)")
    print("\nejemplos de SELECTOR_EQUIVOCADO (el valor SI esta en la pagina, "
          "pero no donde el check mira):")
    for t, v, s in ejemplos:
        print(f"  [{t:22s}] espera {v!r:20s} mirando en {s!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
