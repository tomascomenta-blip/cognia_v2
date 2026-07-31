# -*- coding: utf-8 -*-
"""
b3_factorial_analisis.py — atribución del hueco contra la cifra publicada.

Lee lo que b3_factorial.py dejó en disco. Cuatro celdas de generación
(prompt mío|oficial x esfuerzo low|high) leídas con DOS evaluadores sobre las
MISMAS muestras. Todo APAREADO a nivel tarea: las diferencias entre celdas se
leen como netos apareados, nunca comparando niveles entre corridas (la varianza
entre corridas de este repo está medida en ±34 puntos).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
REPLICAS = 10000
CELDAS = ["mio_low", "oficial_low", "oficial_high"]
PUBLICADO = 70.0            # blog.collinear.ai, LCB v6, 2024-08→2025-01,
                            # 3 muestras, reasoning HIGH, 64k


def _perm(difs, semilla=20260731):
    obs = sum(difs)
    nz = [d for d in difs if d]
    if not nz:
        return 1.0
    rng = random.Random(semilla)
    dos = 0
    for _ in range(REPLICAS):
        s = sum(d if rng.random() < 0.5 else -d for d in nz)
        if abs(s) >= abs(obs):
            dos += 1
    return dos / REPLICAS


def _fmt_p(p):
    return "< 1e-4" if p <= 1.0 / REPLICAS else f"= {p:.4f}"


def analiza(res: dict) -> dict:
    por = defaultdict(dict)
    for m in res["muestras"]:
        por[m["tarea"]][m["celda"]] = m
    completas = {t: c for t, c in por.items()
                 if len(c) == len(CELDAS)}
    n = len(completas)
    print(f"\n{'='*70}")
    print(f"CONDICIONES OFICIALES — factorial 2x2, ventana "
          f"{res['ventana'][0]}..{res['ventana'][1]}   n={n} tareas completas")
    print(f"{'='*70}")
    if n < 35:
        print(f"  << N_min = 35 del prereg NO alcanzado ({n}): esto es "
              f"DESCRIPTIVO, no emite lectura.")

    # --- salud del instrumento por celda ---------------------------------
    print(f"\n  --- INSTRUMENTO por celda (truncar NO es fallo del modelo) ---")
    salud = {}
    for c in CELDAS:
        ms = [v[c] for v in completas.values()]
        trunc = sum(1 for m in ms if m["instrumento"] ==
                    "truncado_por_longitud")
        inst = sum(1 for m in ms if m["instrumento"])
        seg = sum(m["segundos"] for m in ms) / max(1, len(ms))
        ch = sum(m["chars"] for m in ms) / max(1, len(ms))
        salud[c] = {"truncadas": trunc, "instrumento": inst,
                    "pct_truncadas": round(100 * trunc / max(1, len(ms)), 1),
                    "seg_medio": round(seg, 1), "chars_medio": round(ch)}
        aviso = ("  << >15%: celda NO CONCLUYENTE por contexto (prereg 6.1)"
                 if trunc / max(1, len(ms)) > 0.15 else "")
        print(f"  {c:<13} truncadas {trunc:>3}/{len(ms):<3} "
              f"({salud[c]['pct_truncadas']:>5.1f}%)  instrumento {inst:>3}"
              f"  {seg:>6.1f} s/muestra  {ch:>6.0f} chars{aviso}")

    # --- pass@1 de las 8 lecturas ----------------------------------------
    print(f"\n  --- pass@1 (mismas muestras, DOS jueces) ---")
    print(f"  {'celda':<13} {'juez MIO':>10} {'juez OFICIAL':>14}")
    tabla = {}
    for c in CELDAS:
        ms = [v[c] for v in completas.values()]
        mio = sum(1 for m in ms if m["mio_pasa"])
        ofi = sum(1 for m in ms if m["oficial_pasa"])
        tabla[c] = {"mio": mio, "oficial": ofi, "n": len(ms),
                    "mio_pct": round(100 * mio / max(1, len(ms)), 1),
                    "oficial_pct": round(100 * ofi / max(1, len(ms)), 1)}
        print(f"  {c:<13} {mio:>4}/{len(ms):<3} {tabla[c]['mio_pct']:>5.1f}%"
              f"   {ofi:>4}/{len(ms):<3} {tabla[c]['oficial_pct']:>5.1f}%")

    # --- los tres ejes, apareados ----------------------------------------
    def neto(a, b, juez):
        k = "mio_pasa" if juez == "mio" else "oficial_pasa"
        difs = [int(v[a][k]) - int(v[b][k]) for v in completas.values()]
        return sum(difs), _perm(difs)

    print(f"\n  --- LOS EJES, apareados a nivel tarea ---")
    ejes = {}
    for juez in ("mio", "oficial"):
        d1, p1 = neto("oficial_low", "mio_low", juez)
        e2, q2 = neto("oficial_high", "oficial_low", juez)
        ejes[juez] = {"prompt_en_low": [d1, p1],
                      "esfuerzo_en_oficial": [e2, q2]}
        print(f"  juez {juez.upper()}:")
        print(f"    PROMPT  (oficial-mio), a esfuerzo low   {d1:+3d}  "
              f"P {_fmt_p(p1)}")
        print(f"    ESFUERZO(high-low), con prompt oficial  {e2:+3d}  "
              f"P {_fmt_p(q2)}")
    ev = {}
    for c in CELDAS:
        difs = [int(v[c]["oficial_pasa"]) - int(v[c]["mio_pasa"])
                for v in completas.values()]
        ev[c] = [sum(difs), _perm(difs)]
    print(f"    EVALUADOR (oficial-mio), mismas muestras:")
    for c in CELDAS:
        print(f"      {c:<13} {ev[c][0]:+3d}  P {_fmt_p(ev[c][1])}")

    # --- la celda que gana (o no) el derecho a comparar -------------------
    c = "oficial_high"
    ms = [v[c] for v in completas.values()]
    trunc_pct = salud[c]["pct_truncadas"]
    ofi_pct = tabla[c]["oficial_pct"]
    print(f"\n  {'='*66}")
    print(f"  LA CELDA COMPARABLE: prompt oficial + esfuerzo high + juez "
          f"oficial")
    print(f"  {'='*66}")
    # Intervalo de Wilson al 95%: con k=1 y n~35 el punto es GRUESO, y darlo
    # pelado invita a leer una diferencia que el diseño no resuelve.
    k_ok = sum(1 for m in ms if m["oficial_pasa"])
    nn = max(1, len(ms))
    ph = k_ok / nn
    z = 1.96
    den = 1 + z * z / nn
    centro = (ph + z * z / (2 * nn)) / den
    medio = z * ((ph * (1 - ph) / nn + z * z / (4 * nn * nn)) ** 0.5) / den
    lo, hi = 100 * (centro - medio), 100 * (centro + medio)
    print(f"  pass@1 = {ofi_pct:.1f}%   (n={len(ms)} tareas, k=1)   "
          f"IC95% Wilson [{lo:.1f}%, {hi:.1f}%]")
    print(f"  referencia publicada = {PUBLICADO:.0f}   "
          f"[blog.collinear.ai, LCB v6, 2024-08-01..2025-01-31, 3 muestras, "
          f"reasoning high, 64k]")
    puede = (n >= 35 and trunc_pct <= 15.0)
    if puede:
        print(f"  DIFERENCIA = {ofi_pct - PUBLICADO:+.1f} pts, y las "
              f"diferencias RESIDUALES que van en la MISMA frase:")
        print(f"    - mi banco no cubre 2024-08-01..2024-09-21")
        print(f"    - yo mido k=1; la referencia promedia 3 muestras")
        print(f"    - la referencia no declara temperatura; yo uso "
              f"{res['temp']}")
        print(f"    - su contexto era 64k; el mío 32k "
              f"({trunc_pct:.1f}% truncadas)")
        if not (lo <= PUBLICADO <= hi):
            print(f"    -> el {PUBLICADO:.0f} publicado queda FUERA de mi "
                  f"IC95% [{lo:.1f}, {hi:.1f}]")
        else:
            print(f"    -> el {PUBLICADO:.0f} publicado CAE DENTRO de mi "
                  f"IC95% [{lo:.1f}, {hi:.1f}]: con este n no se distinguen")
    else:
        motivo = (f"n={n} < 35" if n < 35
                  else f"{trunc_pct:.1f}% truncadas > 15%")
        print(f"  NO SE COMPARA ({motivo}). El prereg lo prohíbe y se dice "
              f"que no se comparó.")

    return {"n": n, "salud": salud, "tabla": tabla, "ejes": ejes,
            "evaluador": ev, "publicado": PUBLICADO,
            "celda_comparable": {"pass1_pct": ofi_pct, "n": len(ms),
                                 "truncadas_pct": trunc_pct,
                                 "derecho_a_comparar": bool(puede)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fichero", nargs="?", default="factorial.json")
    ap.add_argument("--salida", default="")
    args = ap.parse_args()
    p = Path(args.fichero)
    if not p.is_absolute():
        p = SALIDA / args.fichero
    if not p.exists():
        print(f"[!] no existe: {p}")
        sys.exit(1)
    r = analiza(json.loads(p.read_text(encoding="utf-8")))
    if args.salida and r:
        Path(args.salida).write_text(
            json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n-> {args.salida}")


if __name__ == "__main__":
    main()
