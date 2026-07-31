# -*- coding: utf-8 -*-
"""
b3_nulo_validas_web.py — ¿el +5.82 del BoN en web era SELECCIÓN o solo
descartar lo que no compila?

La pregunta la levantó el banco de código: en MBPP el BoN saca **+10.75 sobre
el azar simple (P<1e-4)** pero solo **+2.17 sobre el azar restringido a las
muestras que pasan ≥1 test visible (P=0.18)**. Casi toda su ganancia era
DESCARTAR basura — o sea detectar INACTIVIDAD, que es la frase que ya mató 10
vías. Si el resultado web tuviera la misma forma, habría que reinterpretarlo.

Aquí se comprueba sobre los corpus web congelados. El análogo web de "válida"
es **haber producido HTML**, y hay dos nulos posibles:

  - NULO-TODAS   : sortea entre las K muestras del ensayo, produjeran o no.
  - NULO-VÁLIDAS : sortea solo entre las que produjeron HTML (`disp`).

`b2_bon_vs_azar.py` usó `disp`, es decir **ya usaba el nulo de válidas**. Esto
lo verifica y mide cuánto separa un nulo del otro.

Cero GPU.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GEN = RAIZ / "cognia" / "program_creator" / "generated_programs"
N_NULO = 10000
SEMILLA = 20260730


def corpus_planas(nombre: str) -> list:
    """Formato de `b2_bon_heldout`: lista plana de muestras con `estricto` y
    `aprobado_heldout`. El selector es el held-out y la política es la misma
    de bon.py: la primera que aprueba; si ninguna, s1."""
    raiz = GEN / nombre
    f = raiz / "resultados.json"
    if not f.exists():
        return []
    res = json.loads(f.read_text(encoding="utf-8"))
    ens = {}
    for m in res.get("muestras", []):
        ens.setdefault((m["tarea"], m["rep"]), []).append(m)
    salida = []
    for (tarea, rep), ms in ens.items():
        ms.sort(key=lambda m: m["s"])
        k = len(ms)
        disp, estr, aprueban_sel = [], set(), []
        for m in ms:
            s = int(m["s"])
            if not (raiz / f"{tarea}__r{rep}" / f"s{s}"
                    / "index.html").is_file():
                continue
            disp.append(s)
            if m.get("estricto"):
                estr.add(s)
            if m.get("aprobado_heldout"):
                aprueban_sel.append(s)
        if not disp:
            continue
        elegida = min(aprueban_sel) if aprueban_sel else (
            disp[0] if disp else None)
        salida.append({"ensayo": f"{tarea}:r{rep}", "k": k,
                       "disp": sorted(disp), "estrictos": sorted(estr),
                       "bon": elegida,
                       "s1": (1 in estr) if 1 in disp else None})
    return salida


def corpus(nombre: str) -> list:
    raiz = GEN / nombre
    f = raiz / "resultados.json"
    if not f.exists():
        return []
    res = json.loads(f.read_text(encoding="utf-8"))
    if "ensayos" not in res:
        return corpus_planas(nombre)
    salida = []
    for e in res.get("ensayos", []):
        sel = {int(m["s"]): m for m in (e.get("bon") or {}).get("muestras", [])}
        k = (e.get("bon") or {}).get("k") or 4
        disp, estr = [], set()
        for kk, v in (e.get("orig") or {}).items():
            s = int(kk)
            if not (raiz / f"{e['tarea']}__r{e['rep']}" / f"s{s}"
                    / "index.html").is_file():
                continue
            disp.append(s)
            if v.get("aprobado") and sel.get(s, {}).get("aprobado_sel"):
                estr.add(s)
        if not disp:
            continue
        elegida = (e.get("bon") or {}).get("elegida_s") or e.get("elegida_s")
        salida.append({"ensayo": f"{e['tarea']}:r{e['rep']}",
                       "k": k, "disp": sorted(disp), "estrictos": sorted(estr),
                       "bon": int(elegida) if elegida else None,
                       "s1": (1 in estr) if 1 in disp else None})
    return salida


def analiza(nombre: str, ens: list) -> None:
    apar = [e for e in ens if e["s1"] is not None and e["bon"]]
    n = len(apar)
    if n < 3:
        print(f"[{nombre}] n={n}: insuficiente")
        return
    ctrl = sum(1 for e in apar if e["s1"])
    bon = sum(1 for e in apar if e["bon"] in e["estrictos"])
    techo = sum(1 for e in apar if e["estrictos"])

    sin_html = sum(e["k"] - len(e["disp"]) for e in apar)
    tot = sum(e["k"] for e in apar)
    ensayos_incompletos = sum(1 for e in apar if len(e["disp"]) < e["k"])

    def nulo(pool_de):
        rng = random.Random(SEMILLA)
        v = sorted(sum(1 for e in apar if rng.choice(pool_de(e))
                       in e["estrictos"]) for _ in range(N_NULO))
        return (sum(v) / len(v), v[int(0.95 * len(v))],
                sum(1 for x in v if x >= bon) / len(v))

    m_val, p95_val, p_val = nulo(lambda e: e["disp"])
    m_tod, p95_tod, p_tod = nulo(lambda e: list(range(1, e["k"] + 1)))

    print(f"\n{'='*68}\n{nombre}   (n={n} ensayos apareados)\n{'='*68}")
    print(f"  muestras SIN HTML: {sin_html}/{tot} ({sin_html/tot:.1%})   "
          f"ensayos con alguna: {ensayos_incompletos}/{n}")
    print(f"  CONTROL (s1) {ctrl:3d}   BoN {bon:3d}   TECHO {techo:3d}")
    print(f"  NULO-VÁLIDAS (solo con HTML) : media {m_val:6.2f}  p95 {p95_val}"
          f"   neto {bon-m_val:+6.2f}   P {'< 1e-4' if p_val <= 1/N_NULO else f'= {p_val:.4f}'}")
    print(f"  NULO-TODAS   (las K siempre) : media {m_tod:6.2f}  p95 {p95_tod}"
          f"   neto {bon-m_tod:+6.2f}   P {'< 1e-4' if p_tod <= 1/N_NULO else f'= {p_tod:.4f}'}")
    print(f"  separación entre los dos nulos: {m_val - m_tod:+.2f}")
    if sin_html == 0:
        print(f"  >> NO HAY MUESTRAS SIN HTML: los dos nulos son el MISMO, "
              f"así que aquí el BoN no puede estar cobrando por descartar "
              f"basura. Su ganancia es SELECCIÓN.")


if __name__ == "__main__":
    for c in (sys.argv[1:] or ["b2_bon_gate_v2", "b2_bon_heldout",
                               "b2_bon_heldout_duro", "b2_bon_heldout_duro_r2"]):
        e = corpus(c)
        if e:
            analiza(c, e)
        else:
            print(f"[{c}] sin datos")
