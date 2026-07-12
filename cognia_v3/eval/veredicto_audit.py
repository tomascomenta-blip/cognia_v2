# -*- coding: utf-8 -*-
"""Veredicto final del AUDIT (PREREG_AUDIT_COLONIA): tabla AUD-2, McNemar
pareado 3B-vs-mejor por eje, y resolución del prereg Self-MoA (techo).

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.veredicto_audit
"""
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def mcnemar_p(n01, n10):
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = json.loads((REPO / "cognia_v3" / "eval" /
                    "results_audit_colonia.json").read_text(encoding="utf-8"))
    m = d["miembros"]
    print("== AUD-2: perfil de skill (acc por eje) ==")
    for k, v in m.items():
        fila = {e: v[e]["acc"] for e in ("g2r", "g5") if e in v}
        lat = {e: round(v[e]["secs_total"] / max(1, len(v[e]["binarios"])), 1)
               for e in fila}
        print(f"  {k:16s} {fila}  (s/item {lat})")

    print("\n== McNemar pareado vs 3B por eje ==")
    for eje in ("g2r", "g5"):
        if eje not in m.get("3b", {}):
            continue
        b3 = m["3b"][eje]["binarios"]
        for k, v in m.items():
            if k == "3b" or eje not in v:
                continue
            bx = v[eje]["binarios"]
            n01 = sum(1 for i in b3 if not b3[i] and bx.get(i))
            n10 = sum(1 for i in b3 if b3[i] and not bx.get(i))
            p = mcnemar_p(n01, n10)
            print(f"  {eje} 3b({m['3b'][eje]['acc']:.0%}) vs {k}"
                  f"({v[eje]['acc']:.0%}): n01={n01} n10={n10} p={p:.4f}"
                  f"{'  **SIGNIFICATIVO**' if p < 0.05 and n01 > n10 else ''}")

    print("\n== veredictos AUD-1 (del runner) ==")
    print(json.dumps(d.get("veredictos", {}), indent=1, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
