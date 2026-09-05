# -*- coding: utf-8 -*-
"""Optimiza los pesos del reranker con el banco de retrieval (sin modelo).

Ingesta UNA vez el dataset en un almacén temporal y evalúa muchas
configuraciones de pesos sobre las 7 preguntas sembradas:
    objetivo = recall_medio + 0.5·precision_media − 0.05·irrelevantes − 0.2·(1 − contradiccion_ok)
Búsqueda: los pesos por defecto + búsqueda aleatoria acotada (semilla fija) +
refinado local alrededor del mejor. Imprime la tabla y guarda el mejor en
--salida (JSON con la forma de PESOS_DEFECTO). NO escribe ~/.cognia.

Uso: venv312/Scripts/python.exe scripts/memoria_larga/optimizar_pesos.py --dataset scratchpad/ml/100000 --n 60
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "memoria_larga"))

from banco import _ESPERADOS, _cargar  # noqa: E402

from cognia.memoria_larga import PESOS_DEFECTO  # noqa: E402

RANGOS = {"semantic": (0.0, 0.6), "lexical": (0.0, 0.6), "task": (0.0, 0.3), "importance": (0.0, 0.3),
          "recency": (0.0, 0.3), "confidence": (0.0, 0.15), "graph": (0.0, 0.2), "type_match": (0.0, 0.4),
          "redundancy": (-0.5, 0.0), "contradiction": (-0.8, -0.1), "obsolescence": (-0.5, 0.0)}


def ingestar(dataset: Path):
    import os
    import tempfile
    from cognia.memoria_larga import contradicciones, dedup, extraccion
    from cognia.memoria_larga.almacen import Almacen
    msgs, preguntas = _cargar(dataset)
    tmp = Path(tempfile.mkdtemp(prefix="ml_pesos_")) / "m.db"
    alm = Almacen(str(tmp))
    tags = {}
    for m in msgs:
        tool = m.get("tool") if m["role"] == "tool" else None
        for mem in extraccion.extraer(m["role"], m["content"], tool=tool, task_id="banco", session_id="s", paso=m["i"],
                                      ok=("rc=1" not in m["content"][:80])):
            dup = dedup.es_duplicada(alm, mem)
            if dup is not None:
                dedup.fusionar(alm, dup, mem)
                continue
            vieja = contradicciones.detectar(alm, mem)
            mid = alm.guardar(mem)
            tags[mid] = m.get("sembrado")
            if vieja is not None:
                contradicciones.resolver(alm, vieja, mem)
    return alm, preguntas, tags


def evaluar(rec, preguntas, tags) -> dict:
    prec = rec_ = 0.0
    irrel = 0
    contra_ok = True
    for p in preguntas:
        q = p["pregunta"] + (" historial" if p["id"] == "D" else "")
        r = rec.buscar(q, task_id="banco", limite=12)
        sel = [tags.get(m.id) for m in r.memorias]
        esperados = set(_ESPERADOS[p["id"]])
        prec += sum(1 for t in sel if t in esperados) / max(1, len(sel))
        rec_ += len(esperados & set(sel)) / max(1, len(esperados))
        irrel += sum(1 for t in sel if t == "B")
        if p["id"] == "C" and "C1" in sel and ("C2" not in sel or sel.index("C2") > sel.index("C1")):
            contra_ok = False
    n = len(preguntas)
    prec, rec_ = prec / n, rec_ / n
    obj = rec_ + 0.5 * prec - 0.05 * irrel - (0.0 if contra_ok else 0.2)
    return {"objetivo": round(obj, 4), "recall": round(rec_, 3), "precision": round(prec, 3), "irrelevantes": irrel,
            "contradiccion_ok": contra_ok}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--semilla", type=int, default=11)
    ap.add_argument("--salida", default="scratchpad/ml/pesos_optimizados.json")
    a = ap.parse_args()
    from cognia.memoria_larga.retrieval import Recuperador
    t0 = time.perf_counter()
    alm, preguntas, tags = ingestar(Path(a.dataset))
    print(f"ingesta {time.perf_counter() - t0:.1f}s, {len(tags)} memorias", flush=True)
    rng = random.Random(a.semilla)
    resultados = []

    def probar(pesos, etiqueta):
        rec = Recuperador(alm, pesos=pesos)
        ev = evaluar(rec, preguntas, tags)
        ev["pesos"] = dict(pesos)
        ev["etiqueta"] = etiqueta
        resultados.append(ev)
        return ev

    base = probar(dict(PESOS_DEFECTO), "defecto")
    print("defecto:", {k: v for k, v in base.items() if k != "pesos"}, flush=True)
    for i in range(a.n):
        pesos = {k: round(rng.uniform(*RANGOS[k]), 3) for k in RANGOS}
        probar(pesos, f"aleatorio{i}")
    mejor = max(resultados, key=lambda r: r["objetivo"])
    # refinado local: perturbar el mejor
    for i in range(max(10, a.n // 3)):
        pesos = {k: round(min(max(v + rng.gauss(0, 0.05), RANGOS[k][0]), RANGOS[k][1]), 3) for k, v in mejor["pesos"].items()}
        probar(pesos, f"refinado{i}")
    mejor = max(resultados, key=lambda r: r["objetivo"])
    resultados.sort(key=lambda r: -r["objetivo"])
    print("\nTop 5:")
    for r in resultados[:5]:
        print(f"  {r['objetivo']:.3f}  R={r['recall']} P={r['precision']} irrel={r['irrelevantes']} contra={r['contradiccion_ok']}  {r['etiqueta']}  "
              + json.dumps(r["pesos"]))
    print(f"\ndefecto: {base['objetivo']:.3f}  mejor: {mejor['objetivo']:.3f}  ({len(resultados)} configuraciones, "
          f"{time.perf_counter() - t0:.0f}s)")
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps({"mejor": mejor, "defecto": base, "n": len(resultados)}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    alm.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
