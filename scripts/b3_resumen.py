# -*- coding: utf-8 -*-
"""
b3_resumen.py — la tabla que se pega en MANAGER_LOG / META.

Lee los análisis ya calculados y los pone uno al lado del otro, con las
etiquetas que el prereg exige que viajen con cada número (qué banco cuenta
como réplica y cuál no, y contra qué nulo se mide).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"


def fila(a: dict) -> str:
    L = a.get("primaria_limpias") or a.get("todo") or {}
    p = L.get("p", 1.0)
    ps = "< 1e-4" if p <= 1e-4 else f"{p:.4f}"
    pv = L.get("p_validas", 1.0)
    pvs = "< 1e-4" if pv <= 1e-4 else f"{pv:.4f}"
    return (f"| {a['etiqueta']} | {a['n']} | {a['pass1']:.1%} | "
            f"{'sí' if a['admite'] else 'NO'} | "
            f"{a['discriminantes']} ({a['discriminantes']/a['n']:.0%}) | "
            f"{L.get('control','?')} | {L.get('azar',0):.2f} | "
            f"{L.get('bon','?')} | {L.get('techo','?')} | "
            f"{L.get('bon',0)-L.get('azar',0):+.2f} | {ps} | "
            f"{L.get('bon',0)-L.get('azar_validas',0):+.2f} | {pvs} | "
            f"{'SÍ' if a.get('cuenta_como_replica') else 'no (humo)'} |")


def main():
    ficheros = sys.argv[1:] or ["analisis_mbpp.json", "analisis_lcb.json"]
    filas = []
    for f in ficheros:
        p = Path(f)
        if not p.is_absolute():
            p = SALIDA / f
        if not p.exists():
            print(f"[!] falta {p}")
            continue
        for a in json.loads(p.read_text(encoding="utf-8")):
            filas.append(a)

    if not filas:
        return
    print("| banco | n | pass@1 | en banda | discrim. | s1 | AZAR | BoN | "
          "techo | neto vs AZAR | P | neto vs AZAR-1-TEST | P | ¿réplica? |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for a in filas:
        print(fila(a))
    print()
    print("Notas que viajan con los números (prereg + enmiendas):")
    print("- La referencia del veredicto es el AZAR, nunca s1; aquí s1 y AZAR")
    print("  son además la MISMA distribución (K muestras i.i.d. a temp 0.8).")
    print("- AZAR-1-TEST ya usa el examen: es un selector débil, no un nulo")
    print("  de basura. El hueco contra él mide lo que añade exigir TODOS los")
    print("  visibles sobre exigir solo el primer bit de señal.")
    print("- MBPP no cuenta como réplica ni entrando en banda: su juez oculto")
    print("  es 1 assert en el 97.8% y P(oculto|visibles) = 0.849.")
    print("- La primaria excluye las tareas con fallo de instrumento entre")
    print("  las K; si el efecto solo vive incluyéndolas, es INACTIVIDAD.")

    for a in filas:
        if a.get("estratos"):
            print()
            print(f"Desglose por dificultad — {a['etiqueta']}:")
            print("| dificultad | n | pass@1 | AZAR | BoN | techo | neto |")
            print("|---|---|---|---|---|---|---|")
            for d, e in a["estratos"].items():
                print(f"| {d} | {e['n']} | {e['pass1']:.1%} | {e['azar']:.2f}"
                      f" | {e['bon']} | {e['techo']} | "
                      f"{e['bon']-e['azar']:+.2f} |")


if __name__ == "__main__":
    main()
