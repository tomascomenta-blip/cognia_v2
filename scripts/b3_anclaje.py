# -*- coding: utf-8 -*-
"""
b3_anclaje.py — ¿el literal que el examen exige está FIJADO por el enunciado?

PREREG_INVENCION_VS_SECUENCIA_20260730. Cierra lo único que quedaba abierto
del diagnóstico del contrato interno: de los 292 literales AUSENTES (67.5%),
cuántos son un valor INVENTADO y cuántos un valor legítimo al que el examen
llega por una secuencia equivocada.

Este script hace SOLO la parte automática (regla A: anclaje literal) y saca
las tres muestras con semilla que se auditan A MANO — incluidas las dos de
CONTROL, porque auditar solo el lado que conviene es cómo se firman números
falsos.
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_contratos_ampliado")
SEMILLA = 20260730

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def enunciados() -> dict:
    out = {}
    for f in sorted((RAIZ / "scripts").glob("b1_tareas*.json")):
        datos = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(datos, dict):
            datos = datos.get("tareas", list(datos.values()))
        for t in datos:
            if isinstance(t, dict) and t.get("id") and t.get("idea"):
                out.setdefault(t["id"], t["idea"])
    return out


def _valores(texto: str) -> set:
    """Números del texto, por VALOR (así 50 ≡ 50.00 ≡ 50,00)."""
    vals = set()
    for m in _NUM.findall(texto or ""):
        try:
            vals.add(float(m.replace(",", ".")))
        except ValueError:
            pass
    return vals


def anclado_literal(literal: str, enunciado: str) -> bool:
    """Regla A del prereg: el literal aparece textualmente en el enunciado,
    normalizando la forma de los números."""
    lit = (literal or "").strip()
    if not lit:
        return False
    if _NUM.fullmatch(lit):
        try:
            return float(lit.replace(",", ".")) in _valores(enunciado)
        except ValueError:
            return False
    return lit.lower() in (enunciado or "").lower()


def main():
    filas = json.loads((DATOS / "invencion_real.json")
                       .read_text(encoding="utf-8"))["filas"]
    ideas = enunciados()

    sin_enunciado = sorted({f["tarea"] for f in filas
                            if f["tarea"] not in ideas})
    if sin_enunciado:
        print(f"[!] tareas sin enunciado a mano: {sin_enunciado}")

    ausentes, presentes = [], []
    for f in filas:
        if f["tarea"] not in ideas:
            continue
        f["_idea"] = ideas[f["tarea"]]
        f["_anclado"] = anclado_literal(f["literal"], f["_idea"])
        f["_largo"] = len(str(f["literal"]).strip())
        # 'presente_tras_actuar' llega como bool o como la cadena "True"
        pres = f["presente_tras_actuar"]
        pres = pres if isinstance(pres, bool) else str(pres) == "True"
        (presentes if pres else ausentes).append(f)

    n = len(ausentes) + len(presentes)
    print(f"literales con enunciado disponible: {n} de {len(filas)}")
    print(f"  SELECTOR_EQUIVOCADO (presente) : {len(presentes)} "
          f"({len(presentes)/n:.1%})")
    print(f"  VALOR_AUSENTE                  : {len(ausentes)} "
          f"({len(ausentes)/n:.1%})")

    anc = [f for f in ausentes if f["_anclado"]]
    noanc = [f for f in ausentes if not f["_anclado"]]
    print(f"\n== REGLA A (automática) sobre los {len(ausentes)} AUSENTES ==")
    print(f"  A  ANCLADO_LITERAL   : {len(anc)} ({len(anc)/len(ausentes):.1%})")
    print(f"  ~A NO anclado (B o C): {len(noanc)} "
          f"({len(noanc)/len(ausentes):.1%})")

    cortos = sum(1 for f in anc if f["_largo"] <= 2)
    print(f"\n  [aviso pre-registrado] de los A, {cortos}/{len(anc)} "
          f"({cortos/max(1,len(anc)):.0%}) tienen literal de 1-2 caracteres:")
    print(f"  un '2' aparece por azar en casi cualquier enunciado, así que A "
          f"SOBRESTIMA el anclaje. Lo mide la muestra de control.")
    print(f"  largo del literal en A: "
          f"{dict(Counter(min(f['_largo'], 5) for f in anc))}  (5 = >=5)")

    por_tarea = defaultdict(lambda: [0, 0])
    for f in ausentes:
        por_tarea[f["tarea"]][0 if f["_anclado"] else 1] += 1
    print(f"\n  por tarea (anclados / no anclados):")
    for t, (a, b) in sorted(por_tarea.items(),
                            key=lambda kv: -(kv[1][0] + kv[1][1]))[:12]:
        print(f"    {t:<24} {a:>3} / {b:>3}")

    # ---- las tres muestras con semilla, para auditar A MANO ----
    rng = random.Random(SEMILLA)

    def muestra(pool, k, nombre):
        sel = rng.sample(pool, min(k, len(pool)))
        return [{"_muestra": nombre, "tarea": f["tarea"],
                 "pagina": f["pagina"], "check": f["check"],
                 "literal": f["literal"], "anclado_literal": f["_anclado"],
                 "enunciado": f["_idea"]} for f in sel]

    aud = (muestra(noanc, 40, "ausente_NO_anclado")
           + muestra(anc, 15, "ausente_anclado_CONTROL")
           + muestra(presentes, 15, "selector_equivocado_CONTROL"))
    out = DATOS / "auditoria_anclaje.json"
    out.write_text(json.dumps(aud, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> muestra para auditar a mano ({len(aud)} filas): {out}")


if __name__ == "__main__":
    main()
