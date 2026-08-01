# -*- coding: utf-8 -*-
"""
b3_frontier_k3_analisis.py — varianza del denominador frontier (enmiendas 5 y
5.1 de DISENO_REFERENCIA_FRONTIER_20260731.md). Solo lee disco.

Lectura PRE-REGISTRADA:
  (a) pass@1 promedio por tarea = media de los 3 veredictos {s1, s2, s3};
      perdida/vacía/64k = FALLO con instrumento anotado (regla uniforme,
      la misma con la que se firmó s=1). El promedio SUSTITUYE al número
      hard k=1 del informe del goal, sea cual sea la dirección.
  (b) no-unanimidad: denominador = tareas con 3 veredictos; desglose por
      causa (instrumento vs respuesta incorrecta). Chequeo de deriva:
      discordancia(s1 vs s2/s3) contra discordancia(s2 vs s3).
  (c) pass@3 = descriptivo etiquetado (cota, no primaria).
  (d) apareado actualizado contra oficial_low en las 83: D_t = media3 − low;
      PRIMARIA test de signos sobre las D_t no nulas, P 1 cola en la
      dirección pre-especificada frontier>20B; secundarias: media de D_t y
      permutación sign-flip sobre las D_t (usa magnitudes).
  (e) lo mismo bajo split sin_fuga en las comunes con reparacion (para el
      informe del goal).
Sensibilidad etiquetada: perdida=EXCLUIDA del promedio (la regla retirada).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
REPLICAS = 10000


def _p1_signos(gana: int, d: int) -> float:
    if d == 0:
        return 1.0
    return sum(comb(d, j) for j in range(gana, d + 1)) / 2 ** d


def _mde(d: int):
    for v in range(d + 1):
        if _p1_signos(v, d) < 0.05:
            return 2 * v - d
    return None


def _perm_signflip(difs, semilla=20260801):
    obs = sum(difs)
    nz = [x for x in difs if x]
    if not nz:
        return 1.0
    rng = random.Random(semilla)
    ge = 0
    for _ in range(REPLICAS):
        s = sum(x if rng.random() < 0.5 else -x for x in nz)
        if s >= obs:
            ge += 1
    return ge / REPLICAS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="analisis_k3.json")
    args = ap.parse_args()

    fro1 = {m["tarea"]: m
            for m in json.loads((SALIDA / "frontier_resultados.json")
                                .read_text(encoding="utf-8"))["muestras"]
            if m["dificultad"] == "hard"}
    k3 = json.loads((SALIDA / "frontier_k3_resultados.json")
                    .read_text(encoding="utf-8"))["muestras"]
    sf1 = {m["tarea"]: m
           for m in json.loads((SALIDA / "frontier_hard_sinfuga.json")
                               .read_text(encoding="utf-8"))["muestras"]}

    low = {}
    for nombre in ("factorial.json", "factorial_low198.json"):
        d = json.loads((SALIDA / nombre).read_text(encoding="utf-8"))
        for m in d["muestras"]:
            if m["celda"] == "oficial_low":
                low.setdefault(m["tarea"], m)

    por = defaultdict(dict)
    for m in k3:
        por[m["tarea"]][m["s"]] = m

    completas = sorted(t for t in fro1
                       if 2 in por.get(t, {}) and 3 in por.get(t, {}))
    incompletas = sorted(t for t in fro1 if t not in completas)
    print(f"{'='*72}\nVARIANZA DEL DENOMINADOR — frontier k=3 en hard "
          f"(enmiendas 5/5.1)\n{'='*72}")
    print(f"  tareas con s=2 Y s=3: {len(completas)}/83"
          f"{'  INCOMPLETAS: ' + str(incompletas) if incompletas else ''}")

    # veredictos {0,1} por muestra; regla uniforme: perdida/vacía = 0
    V = {t: [int(bool(fro1[t]["mio_pasa"])),
             int(bool(por[t][2]["pasa_oc"])),
             int(bool(por[t][3]["pasa_oc"]))] for t in completas}
    inst = {t: [bool(fro1[t]["instrumento"]),
                bool(por[t][2]["instrumento"]),
                bool(por[t][3]["instrumento"])] for t in completas}
    n_inst = sum(1 for t in completas if any(inst[t]))

    n = len(completas)
    p_por_s = [sum(V[t][i] for t in completas) for i in range(3)]
    promedio = sum(sum(V[t]) for t in completas) / (3 * n)
    pass3 = sum(1 for t in completas if any(V[t]))
    unanimes = [t for t in completas if len(set(V[t])) == 1]
    no_unan = [t for t in completas if len(set(V[t])) > 1]
    no_unan_inst = [t for t in no_unan if any(inst[t])]
    print(f"\n  --- NIVELES por muestra (n={n}) ---")
    for i, s in enumerate((1, 2, 3)):
        print(f"  s={s}: {p_por_s[i]}/{n} ({100*p_por_s[i]/n:.1f}%)")
    print(f"  pass@1 PROMEDIO (primaria del nivel): {100*promedio:.1f}%")
    print(f"  pass@3 (descriptivo, cota)          : {pass3}/{n} "
          f"({100*pass3/n:.1f}%)")

    print(f"\n  --- NO-UNANIMIDAD (la varianza que importa) ---")
    print(f"  unánimes {len(unanimes)}/{n}  no-unánimes {len(no_unan)}/{n} "
          f"({100*len(no_unan)/n:.1f}%)")
    print(f"  no-unánimes con instrumento implicado: {len(no_unan_inst)} "
          f"{no_unan_inst}")
    print(f"  no-unánimes por respuesta (modelo)   : "
          f"{sorted(set(no_unan) - set(no_unan_inst))}")

    d12 = sum(1 for t in completas if V[t][0] != V[t][1])
    d13 = sum(1 for t in completas if V[t][0] != V[t][2])
    d23 = sum(1 for t in completas if V[t][1] != V[t][2])
    print(f"\n  --- CHEQUEO DE DERIVA (s1 fue el 07-31; s2/s3 hoy) ---")
    print(f"  discordancia s1-s2: {d12}  s1-s3: {d13}  s2-s3: {d23}")
    deriva = (d12 + d13) / 2 > 2 * max(1, d23)
    aviso = ("SÍ — la lectura se degrada a 2 sorteos + s1 hermana "
             "(enmienda 5.1.5)") if deriva else "no"
    print(f"  ¿(d12+d13)/2 >> d23? {aviso}")

    # --- apareado actualizado contra oficial_low (las que tengan low) ----
    def apareado(tareas, v_fro, v_low, etiqueta):
        D = [v_fro[t] - v_low[t] for t in tareas]
        nz = [x for x in D if x]
        gana = sum(1 for x in nz if x > 0)
        pierde = len(nz) - gana
        p1 = _p1_signos(gana, len(nz))
        print(f"\n  --- {etiqueta} (n={len(tareas)}) ---")
        print(f"  media de D_t (neto fraccionario): {sum(D)/max(1,len(D)):+.3f}")
        mde = _mde(len(nz))
        mde_txt = f"{mde:+d}" if mde is not None else "IMPOSIBLE"
        print(f"  signos: gana {gana}, pierde {pierde}, no nulas {len(nz)}  "
              f"P1(signos) {p1:.2e}  MDE {mde_txt}")
        print(f"  permutación sign-flip sobre D_t (secundaria): "
              f"P {_perm_signflip(D):.4f}")
        return {"n": len(tareas), "media_D": sum(D)/max(1,len(D)),
                "gana": gana, "pierde": pierde, "p1_signos": p1,
                "mde": _mde(len(nz)),
                "p_signflip": _perm_signflip(D)}

    con_low = [t for t in completas if t in low]
    prom_fro = {t: sum(V[t]) / 3 for t in completas}
    v_low = {t: float(bool(low[t]["mio_pasa"])) for t in con_low}
    ap_low = apareado(con_low, prom_fro, v_low,
                      "APAREADO ACTUALIZADO frontier(media k=3) − oficial_low")

    # --- goal: bajo sin_fuga en las comunes con reparacion ---------------
    comunes_sf = [t for t in completas if t in sf1]
    V_sf = {t: [int(bool(sf1[t]["pasa_oc"])),
                int(bool(por[t][2]["pasa_oc_sinfuga"])),
                int(bool(por[t][3]["pasa_oc_sinfuga"]))] for t in comunes_sf}
    prom_sf = {t: sum(V_sf[t]) / 3 for t in comunes_sf}
    print(f"\n  --- PARA EL GOAL: promedio k=3 bajo sin_fuga en las "
          f"comunes ({len(comunes_sf)}) ---")
    prom_sf_nivel = sum(prom_sf.values()) / max(1, len(comunes_sf))
    print(f"  pass@1 promedio sin_fuga: {100*prom_sf_nivel:.1f}%  "
          f"(s=1 solo: "
          f"{100*sum(1 for t in comunes_sf if V_sf[t][0])/max(1,len(comunes_sf)):.1f}%)")

    # --- sensibilidad etiquetada: perdida=excluida -----------------------
    def prom_excl(t):
        vals = [V[t][i] for i in range(3) if not inst[t][i]]
        return sum(vals) / len(vals) if vals else None
    excl = {t: prom_excl(t) for t in completas}
    validos = {t: v for t, v in excl.items() if v is not None}
    print(f"\n  --- SENSIBILIDAD (perdida=EXCLUIDA; regla retirada, "
          f"solo se reporta) ---")
    print(f"  pass@1 promedio: "
          f"{100*sum(validos.values())/max(1,len(validos)):.1f}%  "
          f"(tareas con instrumento: {n_inst})")

    out = {"diseno": "enmiendas 5/5.1", "n_completas": n,
           "incompletas": incompletas,
           "niveles_por_s": p_por_s, "promedio": promedio,
           "pass3": pass3, "no_unanimes": no_unan,
           "no_unanimes_instrumento": no_unan_inst,
           "deriva": {"d12": d12, "d13": d13, "d23": d23,
                      "degradada": bool(deriva)},
           "apareado_low": ap_low,
           "goal_sinfuga": {"n": len(comunes_sf),
                            "promedio": prom_sf_nivel},
           "sensibilidad_excluida": {
               "promedio": sum(validos.values())/max(1,len(validos)),
               "tareas_instrumento": n_inst}}
    (SALIDA / args.salida).write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {SALIDA / args.salida}")


if __name__ == "__main__":
    main()
