#!/usr/bin/env python
"""
b2_metamorfico_selector.py — FASE 2: ¿sirve el metamórfico para ELEGIR muestra?

PREREG_METAMORFICO_20260730.md (ENMIENDA 2, punto B3).

La pregunta del goal es si el sistema puede elegir su muestra buena SIN un
examen escrito a mano. Aquí se puntúa cada muestra por relaciones violadas y
se compara contra las tres referencias ya medidas: control s1 = 7/8, selector
a mano = 8/8 (pérdida 0), techo pass@4 = 8/8.

LO QUE ESTE SCRIPT NO DEJA HACER, y es la razón de que exista el brazo nulo:
un selector ALEATORIO saca 8/8 en estas dos corridas con probabilidad 0.211
(r1: tabla_compuesta 2 de 4 buenas y precedencia 3 de 4 → 0.375; r2: 0.5625).
Un "8/8" nominal NO es evidencia. El umbral pre-registrado es superar el
PERCENTIL 95 del azar en r1 y en r2.

Reglas pre-registradas que este código implementa al pie de la letra:
  - puntuación = FRACCIÓN violadas/instanciadas (no el conteo bruto: si no,
    una muestra con 0 relaciones instanciadas gana siempre a una con 2
    relaciones y 1 violación);
  - cobertura 0 = ABSTENCIÓN, nunca puntuación perfecta;
  - si TODAS las muestras de una tarea se abstienen, se cae al control s1 y
    esa tarea se cuenta APARTE, declarando cuántas se decidieron por señal.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
GT_DURO = GENERADOS / "validacion_heldout_v2.json"

SEMILLA = 20260730
N_NULO = 1000


def cargar_gt_duro() -> dict:
    """{(corpus, tarea, s): estricto} con el juez TRIPLE (orig ∧ v1 ∧ v2)."""
    d = json.loads(GT_DURO.read_text(encoding="utf-8"))
    gt = {}
    for f in d["filas"]:
        # pagina = "<tarea>__r1__s<M>"
        s = int(f["pagina"].rsplit("__s", 1)[1])
        gt[(f["corpus"], f["tarea"], s)] = bool(f["orig"] and f["v1"] and f["v2"])
    return gt


def puntuar(meta: dict) -> float | None:
    """Fracción de relaciones violadas. None = ABSTENCIÓN (sin cobertura)."""
    if meta.get("motivo_infra"):
        return None
    inst = meta.get("relaciones_instanciadas", 0)
    if inst <= 0:
        return None
    return len(meta.get("violaciones", [])) / inst


def elegir(muestras: dict) -> tuple:
    """
    (s_elegida, por_senal). muestras = {s: puntuacion|None}.

    Empate o abstención total → s1, que es el control. Declarado.
    """
    vivos = {s: p for s, p in muestras.items() if p is not None}
    if not vivos:
        return 1, False
    mejor = min(vivos.values())
    candidatas = sorted(s for s, p in vivos.items() if p == mejor)
    if 1 in candidatas:                      # empate: no se aparta del control
        return 1, len(candidatas) < len(muestras) or mejor > 0
    return candidatas[0], True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsons", nargs="+",
                    help="salidas del instrumento sobre el corpus duro")
    args = ap.parse_args(argv)

    gt = cargar_gt_duro()
    # {corpus: {tarea: {s: (punt, estricto)}}}
    datos = defaultdict(lambda: defaultdict(dict))
    for j in args.jsons:
        p = Path(j)
        if not p.is_absolute():
            p = GENERADOS / "b2_metamorfico" / j
        for f in json.loads(p.read_text(encoding="utf-8"))["filas"]:
            corpus = Path(f["html"]).parent.parent.name
            clave = (corpus, f["tarea"], f["s"])
            if clave not in gt:
                continue
            datos[corpus][f["tarea"]][f["s"]] = (puntuar(f["meta"]), gt[clave])

    rng = random.Random(SEMILLA)
    for corpus in sorted(datos):
        tareas = datos[corpus]
        print(f"\n{'='*72}\n{corpus}  ({len(tareas)} tareas)\n{'='*72}")
        print(f"{'tarea':22s} {'ctrl':>5s} {'META':>5s} {'techo':>6s} "
              f"{'elig':>5s} {'senal':>6s}  estrictos")
        modo = ctrl = techo = 0
        por_senal = rescata = estropea = 0
        for tarea in sorted(tareas):
            ms = tareas[tarea]
            punt = {s: v[0] for s, v in ms.items()}
            bien = {s: v[1] for s, v in ms.items()}
            s_el, senal = elegir(punt)
            c = bien.get(1, False)
            m = bien.get(s_el, False)
            t = any(bien.values())
            ctrl += c
            modo += m
            techo += t
            por_senal += senal
            if m and not c:
                rescata += 1
            if c and not m:
                estropea += 1
            print(f"{tarea:22s} {'OK' if c else '--':>5s} "
                  f"{'OK' if m else '--':>5s} {'OK' if t else '--':>6s} "
                  f"{'s'+str(s_el):>5s} {'si' if senal else 'no':>6s}  "
                  f"{sorted(s for s, b in bien.items() if b)}")
        n = len(tareas)
        print(f"\nCONTROL {ctrl}/{n} · METAMORFICO {modo}/{n} · TECHO {techo}/{n}")
        print(f"perdida del selector = {techo - modo}")
        print(f"decididas por SENAL: {por_senal}/{n}  "
              f"(el resto cayó al control por abstencion o empate)")
        print(f"RESCATA {rescata} · ESTROPEA {estropea}")

        # BRAZO NULO: el mismo juego, eligiendo al azar
        nulos = []
        for _ in range(N_NULO):
            k = 0
            for tarea in tareas:
                bien = {s: v[1] for s, v in tareas[tarea].items()}
                k += bien[rng.choice(sorted(bien))]
            nulos.append(k)
        nulos.sort()
        p95 = nulos[int(0.95 * len(nulos))]
        mejor_o_igual = sum(1 for x in nulos if x >= modo)
        print(f"\nBRAZO NULO ({N_NULO} selectores uniformes, semilla {SEMILLA}):")
        print(f"  media {sum(nulos)/len(nulos):.2f}/{n} · p95 = {p95}/{n} · "
              f"max {nulos[-1]}/{n}")
        print(f"  P(azar >= metamorfico) = {mejor_o_igual/len(nulos):.3f}")
        veredicto = ("SUPERA el p95 del azar" if modo > p95
                     else "NO supera el p95 del azar")
        print(f"  --> {veredicto}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
