#!/usr/bin/env python
"""
b2_taxonomia_checks.py — ¿de qué falla REALMENTE el contrato interno?

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (auditoría de la etiqueta).

POR QUÉ. La premisa del adaptador era que el modo de fallo dominante es
**inventar valores que el enunciado no fija**. La auditoría a mano de una
muestra encontró otra cosa, así que aquí se clasifica **estructuralmente** —
sin juicio subjetivo — el contenido de cada check, para poner números.

Categorías, todas detectables leyendo el JSON del paso:

  SIN_ASERCION   solo acciones (click/escribir/tecla/esperar): no comprueba
                 nada, pasa siempre que la acción aterrice
  VACUO          compara `contiene` con la cadena vacía: TODO texto la
                 contiene, así que pasa siempre
  TEXTO_EN_INPUT aserción de `texto` sobre un campo de formulario: falla
                 siempre porque innerText de un <input> es vacío (medido
                 55/55). Es ruido del instrumento, no del contenido
  SELECTOR_NO_DECLARADO  usa un #id que el enunciado de la tarea NO nombra
  CON_VALOR      aserción real con un literal (`esperado`/`contiene`): la
                 única categoría donde "inventar un valor" es posible
  OTRA           el resto (existe/no_existe/contar sin literal, js, ...)

La pregunta que responde: de los checks que fallan en TODAS las páginas
sanas, ¿cuántos son de verdad "valor inventado" y cuántos son otra cosa?
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"
ACCIONES_PURAS = {"click", "escribir", "tecla", "esperar"}


def _ideas() -> dict:
    d = {}
    for f in ("b1_tareas_duras.json", "b1_tareas_cabecera.json",
              "b1_tareas_cabecera2.json"):
        for t in json.loads((RAIZ / "scripts" / f).read_text(
                encoding="utf-8"))["tareas"]:
            d[t["id"]] = t["idea"]
    return d


def _subacciones(paso: dict) -> list:
    if isinstance(paso.get("acciones"), list):
        return paso["acciones"]
    return [paso]


def clasificar(paso: dict, idea: str) -> str:
    subs = _subacciones(paso)
    tipos = {(s.get("accion") or "").strip() for s in subs}

    # ¿alguna sub-accion compara contra la cadena vacia?
    for s in subs:
        if "contiene" in s and str(s["contiene"]) == "":
            return "VACUO"

    # ¿asercion de texto sobre un campo de formulario?
    for s in subs:
        if (s.get("accion") == "texto"
                and re.search(r"input|textarea|#(cant|nueva-cap|personas|"
                              r"pass|pass2|edad|q|txt|doc|desde|hasta|cupon|"
                              r"nuevo-stock)\b", str(s.get("selector", "")))):
            return "TEXTO_EN_INPUT"

    # ¿usa un #id que el enunciado no nombra?
    for s in subs:
        for ident in re.findall(r"#([A-Za-z_][\w-]*)", str(s.get("selector", ""))):
            if ident not in idea:
                return "SELECTOR_NO_DECLARADO"

    if tipos and tipos <= ACCIONES_PURAS:
        return "SIN_ASERCION"

    for s in subs:
        if "esperado" in s or "contiene" in s:
            return "CON_VALOR"
    return "OTRA"


def main() -> int:
    ds = json.loads((SALIDA / "dataset_etiqueta_debil.json")
                    .read_text(encoding="utf-8"))
    idx = json.loads((SALIDA / "indice.json").read_text(encoding="utf-8"))["filas"]
    ideas = _ideas()

    # todos los pasos por (tarea, nombre)
    pasos = {}
    for f in idx:
        if not f["ok"]:
            continue
        corpus, carpeta = f["pagina"].split("/", 1)
        c = json.loads((GENERADOS / corpus / carpeta / "contrato_interno.json")
                       .read_text(encoding="utf-8"))
        for p in c.get("pasos", []):
            pasos.setdefault((f["tarea"], p.get("nombre")), p)

    print(f"{'':22s} {'INVENTADO-cand':>15s} {'CORRECTO-cand':>14s}")
    print("-" * 54)
    tot = {}
    for lado in ("inventado", "correcto"):
        cnt = Counter()
        for it in ds[lado]:
            p = pasos.get((it["tarea"], it["check"]))
            cnt[clasificar(p, ideas.get(it["tarea"], "")) if p else "NO_HALLADO"] += 1
        tot[lado] = cnt
    cats = sorted(set(tot["inventado"]) | set(tot["correcto"]))
    for c in cats:
        a, b = tot["inventado"][c], tot["correcto"][c]
        print(f"{c:22s} {a:8d} ({100*a/max(1,sum(tot['inventado'].values())):4.1f}%) "
              f"{b:7d} ({100*b/max(1,sum(tot['correcto'].values())):4.1f}%)")
    print("-" * 54)
    print(f"{'TOTAL':22s} {sum(tot['inventado'].values()):8d} "
          f"{sum(tot['correcto'].values()):15d}")

    inv = tot["inventado"]
    n = sum(inv.values())
    con_valor = inv["CON_VALOR"]
    print(f"\nDE LOS QUE FALLAN EN TODAS LAS SANAS ({n}):")
    print(f"  con un literal que PODRIA estar inventado : {con_valor} "
          f"({100*con_valor/max(1,n):.1f}%)")
    print(f"  el resto NO es 'valor inventado'          : {n-con_valor} "
          f"({100*(n-con_valor)/max(1,n):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
