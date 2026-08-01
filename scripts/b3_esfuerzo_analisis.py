# -*- coding: utf-8 -*-
"""
b3_esfuerzo_analisis.py — cierre del eje ESFUERZO (enmiendas 4 y 5 del
PREREG_CONDICIONES_OFICIALES_20260731).

Junta la celda `oficial_high` (factorial_high2.json, n_ctx=65536,
max_tokens=60000, pared 1500) con `oficial_low` (factorial.json de la mañana,
y factorial_low2.json si existe — la réplica fresca de la misma noche) y lee
el contraste APAREADO a nivel tarea.

Decidido ANTES de correr (enmiendas 4 y 5, tras revisión adversarial):
- `truncado_por_longitud` a 60k es ESTRATO APARTE con TRES lecturas SIEMPRE
  juntas: fallo (principal), pase (cota superior real) y excluidas
  (descriptiva). Truncada => fallo se FUERZA en la principal aunque el juez
  hubiera aprobado código parcial extraído.
- `demasiado_grande` y `lote_expirado` del juez oficial son fallo de MI
  instrumento (tope 8 MB / 120 s que el juez oficial real no tiene): estrato
  aparte, pass@1 oficial CON y SIN, y enumerado en la frase de comparación.
- El contraste del eje se lee con P de UNA cola en la dirección pre-declarada
  (high > low: es el candidato de los ~18 pts) y la de dos colas al lado.
- El MDE del sign-flip se reporta SIEMPRE (bilateral, el mismo criterio que
  la P que decide se declara junto al número).
- La comparación con el 70 exige n>=35 y va SIEMPRE con IC95 Wilson.

AMENAZA DECLARADA: el apareado high-vs-low(mañana) CRUZA CORRIDAS Y CONFIGS
(low: backend 16k/32k, max_tokens 15000, ayer; high: 65536/60000, hoy). La
réplica low2 de la misma noche y bajo el backend de 65536 acota eso.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
REPLICAS = 10000
PUBLICADO = 70.0
NO_JUZGABLE_RX = re.compile(r"^(demasiado_grande|lote_expirado)")


def _perm(difs, semilla=20260731):
    """P bilateral por permutación de signos."""
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


def _p_binom_1cola(gana: int, d: int) -> float:
    """P(X >= gana | d, 0.5), la direccional high>low."""
    if d == 0:
        return 1.0
    return sum(comb(d, j) for j in range(gana, d + 1)) / 2 ** d


def _mde(d: int) -> tuple:
    """(victorias, MDE) BILATERAL con d discordantes."""
    if d <= 0:
        return 0, 0
    for k in range(d, -1, -1):
        p = 2 * sum(comb(d, j) for j in range(k, d + 1)) / 2 ** d
        if p >= 0.05:
            return k + 1, 2 * (k + 1) - d
    return d + 1, d + 2


def _carga(nombre: str, celda: str) -> dict:
    p = SALIDA / nombre
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {m["tarea"]: m for m in d["muestras"] if m["celda"] == celda}


def _wilson(k: int, n: int) -> tuple:
    if not n:
        return 0.0, 0.0
    ph, z = k / n, 1.96
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    m = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / den
    return 100 * (c - m), 100 * (c + m)


def _trunca(m: dict) -> bool:
    return m["instrumento"] == "truncado_por_longitud"


def _no_juzgable(m: dict) -> bool:
    return bool(NO_JUZGABLE_RX.match(str(m.get("juez_oficial") or "")))


def _pasa(m: dict, juez: str) -> bool:
    """El veredicto de la PRINCIPAL: truncada se fuerza a fallo aunque el
    juez hubiera aprobado código parcial (revisión adversarial 2026-07-31)."""
    if _trunca(m):
        return False
    return bool(m[juez])


def contraste(high: dict, low: dict, etiqueta: str) -> None:
    comunes = sorted(set(high) & set(low))
    if not comunes:
        print(f"\n  [{etiqueta}] sin tareas comunes")
        return
    print(f"\n  --- ESFUERZO (high − low) contra {etiqueta} — "
          f"{len(comunes)} tareas apareadas ---")
    for juez in ("oficial_pasa", "mio_pasa"):
        difs = [int(_pasa(high[t], juez)) - int(_pasa(low[t], juez))
                for t in comunes]
        g = sum(1 for x in difs if x > 0)
        l = sum(1 for x in difs if x < 0)
        v, mde = _mde(g + l)
        print(f"  juez {juez.split('_')[0].upper():<8} neto {sum(difs):+3d} "
              f"(gana {g}, pierde {l}, disc {g+l})  "
              f"P(1c, high>low) = {_p_binom_1cola(g, g+l):.4f}  "
              f"P(2c) = {_perm(difs):.4f}  "
              f"[MDE bilateral: {v}/{g+l} victorias => ±{max(mde, 0)}]")
    sin_t = [t for t in comunes if not _trunca(high[t])]
    if len(sin_t) < len(comunes):
        difs = [int(_pasa(high[t], "oficial_pasa"))
                - int(_pasa(low[t], "oficial_pasa")) for t in sin_t]
        g = sum(1 for x in difs if x > 0)
        l = sum(1 for x in difs if x < 0)
        print(f"  (descriptivo, sin las {len(comunes)-len(sin_t)} truncadas "
              f"de high: neto {sum(difs):+d}, gana {g}, pierde {l} — "
              f"juez oficial)")
    nj = [t for t in comunes if _no_juzgable(high[t]) or _no_juzgable(low[t])]
    if nj:
        print(f"  (concordantes FORZADAS por mi juez oficial "
              f"demasiado_grande/lote_expirado: {len(nj)} {nj} — no pueden "
              f"discordar, el n efectivo del eje es {len(comunes)-len(nj)})")


def lecturas(high: dict, juez: str, etiqueta: str, trunc: list,
             excl_nj: bool = False) -> None:
    hs = {t: m for t, m in high.items()
          if not (excl_nj and _no_juzgable(m))}
    n = len(hs)
    con = sum(1 for m in hs.values() if _pasa(m, juez))
    pase = sum(1 for t, m in hs.items()
               if _pasa(m, juez) or _trunca(m))
    ntc = [m for t, m in hs.items() if not _trunca(m)]
    sin = sum(1 for m in ntc if _pasa(m, juez))
    lo, hi_ = _wilson(con, n)
    print(f"\n  pass@1 juez {etiqueta}:")
    print(f"    truncadas=FALLO (principal): {con}/{n} "
          f"({100*con/max(1,n):.1f}%)  IC95 [{lo:.1f}, {hi_:.1f}]")
    print(f"    truncadas=PASE (cota superior real): {pase}/{n} "
          f"({100*pase/max(1,n):.1f}%)")
    print(f"    truncadas EXCLUIDAS (descriptiva): {sin}/{len(ntc)} "
          f"({100*sin/max(1,len(ntc)):.1f}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--high", default="factorial_high2.json")
    args = ap.parse_args()

    high = _carga(args.high, "oficial_high")
    low_m = _carga("factorial.json", "oficial_low")
    low_n = _carga("factorial_low2.json", "oficial_low")

    n = len(high)
    trunc = [t for t, m in high.items() if _trunca(m)]
    otros_inst = [t for t, m in high.items()
                  if m["instrumento"] and t not in trunc]
    nj = [t for t, m in high.items() if _no_juzgable(m)]
    toks = [m.get("tok_salida") for m in high.values()
            if m.get("tok_salida")]
    print(f"{'='*70}")
    print(f"EJE ESFUERZO — celda oficial_high   n={n} tareas   "
          f"(enmiendas 4-5 del prereg)")
    print(f"{'='*70}")
    print(f"\n  ESTRATO truncadas a 60k: {len(trunc)}/{n} "
          f"({100*len(trunc)/max(1,n):.1f}%)   otros instrumento: "
          f"{len(otros_inst)} {otros_inst if otros_inst else ''}")
    print(f"  ESTRATO no juzgables por MI juez oficial (tope 8MB/120s): "
          f"{len(nj)}/{n} {nj}")
    seg = sum(m["segundos"] for m in high.values()) / max(1, n)
    print(f"  {seg:.0f} s/muestra de media"
          + (f"   tokens de salida registrados en {len(toks)}/{n}"
             if toks else "   [muestras viejas sin tokens registrados]"))

    lecturas(high, "oficial_pasa", "OFICIAL (con mis topes 8MB/120s "
             "contados como fallo)", trunc)
    if nj:
        lecturas(high, "oficial_pasa",
                 "OFICIAL sin las no-juzgables (el techo estructural fuera)",
                 trunc, excl_nj=True)
    lecturas(high, "mio_pasa", "MIO", trunc)

    contraste(high, low_m, "oficial_low de la MAÑANA (factorial.json) "
              "[CRUZA CORRIDAS Y CONFIGS: se declara]")
    if low_n:
        contraste(high, low_n, "oficial_low fresco de ESTA NOCHE "
                  "(factorial_low2.json)")
        comunes = sorted(set(low_m) & set(low_n))
        if comunes:
            difs = [int(_pasa(low_n[t], "oficial_pasa"))
                    - int(_pasa(low_m[t], "oficial_pasa")) for t in comunes]
            g = sum(1 for x in difs if x > 0)
            l = sum(1 for x in difs if x < 0)
            print(f"\n  --- RÉPLICA low noche − low mañana ({len(comunes)} "
                  f"tareas): neto {sum(difs):+d} (gana {g}, pierde {l}) — "
                  f"estabilidad entre corridas del mismo día ---")

    # --- derecho a comparar ------------------------------------------------
    print(f"\n  {'='*66}")
    con = sum(1 for m in high.values() if _pasa(m, "oficial_pasa"))
    lo, hi_ = _wilson(con, n)
    if n >= 35:
        print(f"  COMPARACIÓN (n={n} >= 35): pass@1 = "
              f"{100*con/max(1,n):.1f}%  IC95 Wilson [{lo:.1f}, {hi_:.1f}]  "
              f"contra {PUBLICADO:.0f} publicado.")
        print(f"  En la MISMA frase, TODAS las diferencias residuales:")
        print(f"    - n={n} tareas sorteadas (semilla 20260731) del solape "
              f"FILTRADO (198 de 211; el filtro")
        print(f"      excluye 13, 10 de ellas hard => ~1-2 pts A MI FAVOR); "
              f"el 70 es sobre ~todo v6 en ventana")
        print(f"    - mi banco local no cubre 2024-08-01..09-21 y su "
              f"cobertura contra v6 no está contada")
        print(f"    - k=1 contra sus 3 muestras; temp 0.8 contra no "
              f"declarada; techo de pensamiento 60k contra ~63k")
        print(f"    - {len(trunc)} truncadas contadas como fallo; mi juez "
              f"capa lotes a 8 MB/120 s (el oficial no):")
        print(f"      {len(nj)} tareas no juzgables contadas como fallo en "
              f"la principal")
        print(f"    - mi extractor toma el PRIMER bloque de código; el "
              f"oficial el ÚLTIMO (escanear crudos multi-bloque)")
    else:
        print(f"  NO SE COMPARA: n={n} < 35 (prereg §5 + enmiendas 4-5). "
              f"El eje queda medido; la comparación exige el tramo 2.")


if __name__ == "__main__":
    main()
