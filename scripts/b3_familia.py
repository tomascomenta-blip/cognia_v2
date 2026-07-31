# -*- coding: utf-8 -*-
"""
b3_familia.py — ¿sirve UN examen a mano por FAMILIA en vez de uno por tarea?

Prioridad 3 de la sesión. El cuello del goal es que el selector necesita un
examen escrito A MANO **por tarea**. Si bastara uno por FAMILIA (carritos,
undos, calculadoras...), el coste bajaría de O(tareas) a O(familias) y el
dominio web volvería a ser medible sin tests públicos.

Este paso es el BARATO y va primero: antes de ejecutar nada contra páginas,
se comprueba si los held-outs que ya existen son siquiera **instanciables**
en las páginas de sus tareas hermanas. Un held-out se escribe contra los
selectores OBLIGATORIOS del enunciado (`#cant`, `#total`, `.prod`...), así
que si la hermana no los declara, el examen no falla: **no aplica**, y
medirlo daría 100% de acusación a sanos — un KILL falso de la idea, que es
exactamente lo que pasó con el descubridor metamórfico.

Cero GPU, cero navegador.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCR = RAIZ / "scripts"

# Familias por PARENTESCO DE MECANISMO, fijadas antes de medir nada.
FAMILIAS = {
    "carrito/precio": ["carrito_cupones", "carrito_packs", "descuento_tramos",
                       "presupuesto_reparto"],
    "undo/historial": ["undo_redo", "editor_undo_buscar"],
    "capacidad/invariante": ["inventario_reservas", "turnos_capacidad",
                             "calendario_conflictos"],
    "tabla/vista": ["tabla_compuesta"],
    "calculadora/parser": ["precedencia", "parser_parentesis"],
    "tablero/turnos": ["tres_en_raya", "serpiente", "ascensor"],
    "tiempo": ["temporizador"],
    "formulario": ["form_cruzado"],
}

_SEL = re.compile(r"[#.][A-Za-z_][\w-]*|\[data-[\w-]+")


def selectores_de(obj) -> set:
    """Todos los selectores CSS que menciona una estructura (contrato o
    enunciado), sin interpretar: es una cota superior de lo que exige."""
    out = set()

    def rec(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("selector", "expr") and isinstance(v, str):
                    out.update(_SEL.findall(v))
                else:
                    rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)

    rec(obj)
    return out


def main():
    # held-outs a mano que existen
    def _lista(f):
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else (d.get("tareas") or [])

    heldouts = {}
    for f in SCR.glob("b1_contratos_heldout*.json"):
        for it in _lista(f):
            if isinstance(it, dict) and it.get("id"):
                heldouts.setdefault(it["id"], []).append((f.name, it))
    # enunciados
    ideas = {}
    for f in SCR.glob("b1_tareas*.json"):
        for t in _lista(f):
            if isinstance(t, dict) and t.get("id") and t.get("idea"):
                ideas.setdefault(t["id"], t["idea"])

    print(f"held-outs a mano disponibles: {len(heldouts)} tareas")
    print(f"enunciados: {len(ideas)} tareas\n")

    filas = []
    for fam, miembros in FAMILIAS.items():
        con = [m for m in miembros if m in heldouts and m in ideas]
        if len(con) < 2:
            continue
        print(f"=== FAMILIA {fam}  ({len(con)} miembros con held-out) ===")
        for a in con:
            sa = set()
            for _, it in heldouts[a]:
                sa |= selectores_de(it)
            if not sa:
                continue
            for b in con:
                if a == b:
                    continue
                # ¿los selectores que exige el held-out de A existen en el
                # enunciado de B? (el enunciado declara los OBLIGATORIOS)
                idea_b = ideas[b]
                presentes = {s for s in sa if s.lstrip("#.[").split("=")[0]
                             .strip('"') in idea_b or s in idea_b}
                cob = len(presentes) / len(sa)
                filas.append((fam, a, b, len(sa), len(presentes), cob))
                print(f"   held-out de {a:<22} -> páginas de {b:<22} "
                      f"cobertura de selectores {len(presentes):>2}/{len(sa):<2}"
                      f" = {cob:>5.0%}")
        print()

    if not filas:
        print("sin pares comparables")
        return
    med = sum(f[5] for f in filas) / len(filas)
    plenos = sum(1 for f in filas if f[5] >= 0.99)
    print(f"=== RESUMEN: {len(filas)} pares (A->hermana B) ===")
    print(f"  cobertura MEDIA de selectores: {med:.0%}")
    print(f"  pares con cobertura TOTAL    : {plenos}/{len(filas)}")
    print(f"\n  Lectura: si la cobertura es baja, el held-out de A no es que")
    print(f"  'repruebe' a B — es que NO APLICA. Medir el J sin comprobar")
    print(f"  esto daría ~100% de acusación a sanos y un KILL FALSO de la")
    print(f"  idea de examen-por-familia (el fallo sería del instrumento).")


if __name__ == "__main__":
    main()
