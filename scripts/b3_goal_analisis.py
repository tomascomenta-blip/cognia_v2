# -*- coding: utf-8 -*-
"""
b3_goal_analisis.py — el análisis formal del goal: ¿iguala el 20B+cómputo al
frontier? ANALISIS_GOAL_RESPONDIDO_20260801.md. Solo lee disco; cero GPU.

PRIMARIA: neto apareado frontier(k=1, split sin_fuga) − 20B BoN@4 realizable
sobre las tareas hard comunes reparacion∩frontier, n=80 (arc191_d fuera por
instrumento del PLAN). C1/C3/C4 sitúan el hueco a k=1 y contra los techos.
Sign-flip 10k + binomial 1 cola, IC95 Wilson, MDE SIEMPRE.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from math import comb, sqrt
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

REPLICAS = 10000
ARC_INSTRUMENTO_PLAN = "arc191_d"   # salida >64k del harness del PLAN


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if not n:
        return (0.0, 0.0)
    p = ok / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    ancho = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(100 * (centro - ancho), 1), round(100 * (centro + ancho), 1))


def _perm(difs, semilla=20260801):
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


def _p1(gana, d):
    if d == 0:
        return 1.0
    return sum(comb(d, j) for j in range(gana, d + 1)) / 2 ** d


def _mde(d):
    """Efecto mínimo detectable con d discordantes (victorias para P<0.05)."""
    for v in range(d + 1):
        if _p1(v, d) < 0.05:
            return 2 * v - d
    return None


def contraste(pares, etiqueta):
    """pares = [(a, b)] booleanos por tarea; neto = sum(a) - sum(b).

    La P de 1 cola es en la dirección PRE-especificada del plan (F − 20B > 0,
    o sea `gana`), no en la observada: usar max(g, p) sería anticonservador
    y firmaría "significativo" un neto en la dirección contraria (refutación
    adversarial del 2026-08-01). Hoy da lo mismo (pierde=0 en todo), pero el
    código no puede depender de eso.
    """
    difs = [int(a) - int(b) for a, b in pares]
    g = sum(1 for x in difs if x > 0)
    p = sum(1 for x in difs if x < 0)
    d = g + p
    return {"etiqueta": etiqueta, "n": len(pares), "neto": sum(difs),
            "gana": g, "pierde": p, "discordantes": d,
            "p_una_cola": _p1(g, d),
            "p_dos_colas": _perm(difs),
            "mde": _mde(d)}


def selector(pool):
    """La política LITERAL de cognia/program_creator/bon.py."""
    return sorted(pool, key=lambda m: (not m["pasa_vis"], -m["vis_ok"],
                                       m.get("idx", m.get("s", 0))))[0]


def pools_reparacion(rep):
    por = defaultdict(list)
    for m in rep["muestras"]:
        por[m["tarea"]].append(m)
    out = {}
    for t, ms in por.items():
        if not any(m.get("cierre") for m in ms):
            continue
        raiz = [m for m in ms if m["brazo"] == "raiz"]
        if len(raiz) != 1:
            continue
        bon = raiz + sorted([m for m in ms if m["brazo"] == "bon"
                             and not m.get("no_generado")],
                            key=lambda m: m["idx"])
        todos = [m for m in ms if not m.get("cierre")
                 and not m.get("no_generado")]
        out[t] = {"raiz": raiz[0], "bon": bon, "todos": todos}
    return out


def fmt(c):
    mde = f"{c['mde']:+d}" if c["mde"] is not None else "IMPOSIBLE"
    return (f"  {c['etiqueta']:<44} neto {c['neto']:+4d}  "
            f"(gana {c['gana']:>2}, pierde {c['pierde']:>2})  "
            f"P1 {c['p_una_cola']:.2e}  P2 {c['p_dos_colas']:.4f}  "
            f"MDE {mde}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="analisis_goal.json")
    args = ap.parse_args()

    rep = json.loads((SALIDA / "reparacion.json").read_text(encoding="utf-8"))
    pools = pools_reparacion(rep)
    sf = json.loads((SALIDA / "frontier_hard_sinfuga.json")
                    .read_text(encoding="utf-8"))
    fro_sf = {m["tarea"]: m for m in sf["muestras"]}
    fro_orig = {m["tarea"]: m
                for m in json.loads((SALIDA / "frontier_resultados.json")
                                    .read_text(encoding="utf-8"))["muestras"]}

    comunes = sorted(set(pools) & set(fro_sf))
    primaria_t = [t for t in comunes if t != ARC_INSTRUMENTO_PLAN]
    print(f"{'='*74}\nEL GOAL, RESPONDIDO — 20B+cómputo vs frontier  "
          f"(hard comunes: {len(comunes)}, primaria n={len(primaria_t)})\n"
          f"{'='*74}")

    # --- niveles con IC (universo de la primaria) -------------------------
    def nivel(f):
        ok = sum(1 for t in primaria_t if f(t))
        return ok, wilson(ok, len(primaria_t))

    F = lambda t: bool(fro_sf[t]["pasa_oc"])
    R1 = lambda t: bool(pools[t]["raiz"]["pasa_oc"])
    B4 = lambda t: bool(selector(pools[t]["bon"][:4])["pasa_oc"])
    P4 = lambda t: any(m["pasa_oc"] for m in pools[t]["bon"][:4])
    PT = lambda t: any(m["pasa_oc"] for m in pools[t]["todos"])

    niveles = {}
    print(f"\n  --- NIVELES (n={len(primaria_t)}, IC95 Wilson) ---")
    for clave, f, etiq in (
            ("frontier_k1", F, "frontier opus-5 k=1 (sin_fuga)"),
            ("raiz_k1", R1, "20B k=1 (raíz s1)"),
            ("bon4", B4, "20B BoN@4 realizable"),
            ("pool_bon4", P4, "20B techo pool BoN@4 (oráculo)"),
            ("pool_total", PT, "20B techo pool TOTAL (~10 cand, 2.4x)")):
        ok, ic = nivel(f)
        niveles[clave] = {"ok": ok, "n": len(primaria_t),
                          "pct": round(100 * ok / len(primaria_t), 1),
                          "ic95": ic}
        print(f"  {etiq:<44} {ok:>3}/{len(primaria_t)}  "
              f"({niveles[clave]['pct']:>5.1f}%)  IC95 [{ic[0]}, {ic[1]}]")

    # --- contrastes apareados --------------------------------------------
    print(f"\n  --- APAREADOS (sign-flip 10k + binomial; MDE SIEMPRE) ---")
    cts = {}
    for clave, g, etiq in (
            ("c1_f_menos_k1", R1, "C1  F − 20B k=1"),
            ("c2_f_menos_bon4", B4, "C2* F − 20B BoN@4 realizable (PRIMARIA)"),
            ("c3_f_menos_pool4", P4, "C3  F − techo pool BoN@4"),
            ("c4_f_menos_pooltotal", PT, "C4  F − techo pool TOTAL")):
        cts[clave] = contraste([(F(t), g(t)) for t in primaria_t], etiq)
        print(fmt(cts[clave]))

    # sensibilidad: arc191_d como FALLO del frontier (n=81)
    sens = contraste([(F(t) if t != ARC_INSTRUMENTO_PLAN else False, B4(t))
                      for t in comunes],
                     "C2 sensib. arc191_d=fallo frontier (n=81)")
    print(fmt(sens))

    # sensibilidad al split: frontier CON fuga (fichero original)
    Ff = lambda t: bool(fro_orig[t]["mio_pasa"])
    sens_fuga = contraste([(Ff(t), B4(t)) for t in primaria_t],
                          "C2 sensib. frontier con fuga")
    print(fmt(sens_fuga))
    cambian = [t for t in comunes
               if bool(fro_sf[t]["pasa_oc"]) != bool(fro_orig[t]["mio_pasa"])]
    print(f"  veredictos frontier que cambia el split sin_fuga: "
          f"{len(cambian)} {cambian}")

    # --- cota peor-caso de la parada temprana sobre los techos -----------
    # El pool realizado se trunca al pasar visibles: si la parada fue sobre
    # un FALSO POSITIVO (pasa vis, falla oc) y nada del pool acierta, el
    # oráculo verdadero a k=4 podría haber rescatado la tarea. La cota
    # peor-caso asume que TODAS esas tareas se rescatan (refutación
    # adversarial 2026-08-01: el umbral "no puede" se evalúa contra C4, así
    # que esta cota se publica con el número, no como nota abierta).
    # La parada puede dispararla CUALQUIER candidato que pase visibles, no
    # solo la raíz (arc190_d paró en idx3 por un FP de bon): la condición es
    # pool truncado + algún falso positivo de visibles + cero éxitos ocultos
    # en el pool total.
    fp_parada = [t for t in primaria_t
                 if len(pools[t]["bon"]) < 4                 # paró temprano
                 and any(m["pasa_vis"] and not m["pasa_oc"]
                         for m in pools[t]["bon"])           # FP que detuvo
                 and not any(m["pasa_oc"] for m in pools[t]["todos"])]
    c4_peor = niveles["pool_total"]["ok"] + len(fp_parada)
    dif_peor = [(F(t), True if t in fp_parada else PT(t)) for t in primaria_t]
    c4_peor_c = contraste(dif_peor, "C4 peor-caso (FP de parada rescatados)")
    print(f"\n  --- COTA PEOR-CASO de la parada temprana ---")
    print(f"  tareas con parada en falso positivo sin éxito en el pool: "
          f"{len(fp_parada)} {fp_parada}")
    print(f"  C4 peor-caso: {c4_peor}/{len(primaria_t)} "
          f"({100*c4_peor/len(primaria_t):.1f}%)")
    print(fmt(c4_peor_c))

    # --- sensibilidad simétrica: instrumento del lado 20B ----------------
    # arc191_d (frontier) se excluye; los candidatos 20B con instrumento
    # cuentan como fallo. La sensibilidad simétrica excluye también las
    # tareas de la primaria con algún candidato raiz/bon instrumentado.
    inst_20b = [t for t in primaria_t
                if any(m["instrumento"] for m in pools[t]["bon"])]
    sim = contraste([(F(t), B4(t)) for t in primaria_t if t not in inst_20b],
                    f"C2 sensib. sin {len(inst_20b)} tareas inst. 20B")
    print(f"\n  tareas primaria con candidato raiz/bon instrumentado: "
          f"{len(inst_20b)} {inst_20b}")
    print(fmt(sim))

    # --- curva BoN k=1..4 sobre la primaria ------------------------------
    print(f"\n  --- CURVA BoN k=1..4 (n={len(primaria_t)}) ---")
    curva = []
    for K in (1, 2, 3, 4):
        rz = sum(1 for t in primaria_t
                 if selector(pools[t]["bon"][:K])["pasa_oc"])
        oc = sum(1 for t in primaria_t
                 if any(m["pasa_oc"] for m in pools[t]["bon"][:K]))
        tok = sum(sum(m.get("tok_salida") or 0 for m in pools[t]["bon"][:K])
                  for t in primaria_t)
        curva.append({"k": K, "realizable": rz, "oraculo": oc, "tokens": tok})
        print(f"  k={K}  realizable {rz:>3}  oráculo {oc:>3}  "
              f"tokens salida {tok:>8}")

    # --- S2: estratos easy/medium ----------------------------------------
    from b3_codigo import carga_lcb
    dif_banco = {str(t["task_id"]): t["dificultad"] for t in carga_lcb(
        ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))}
    lcb = json.loads((SALIDA / "lcb_sinfuga.json").read_text(encoding="utf-8"))
    por_lcb = defaultdict(list)
    for m in lcb["muestras"]:
        por_lcb[m["tarea"]].append(m)
    for ms in por_lcb.values():
        ms.sort(key=lambda m: m["s"])

    print(f"\n  --- S2: uplift BoN por estrato en banco lcb propio "
          f"(k=4, effort low/8k; DESCRIPTIVO) ---")
    s2 = {}
    for dif in ("easy", "medium", "hard"):
        ts = [t for t in por_lcb if dif_banco.get(t) == dif]
        if not ts:
            continue
        k1 = sum(1 for t in ts if por_lcb[t][0]["pasa_oc"])
        b4 = sum(1 for t in ts if selector(por_lcb[t][:4])["pasa_oc"])
        o4 = sum(1 for t in ts if any(m["pasa_oc"] for m in por_lcb[t][:4]))
        s2[dif] = {"n": len(ts), "k1": k1, "bon4": b4, "oraculo4": o4}
        print(f"  {dif:<7} n={len(ts):<3}  k1 {k1:>3} ({100*k1/len(ts):.0f}%)"
              f"  BoN@4 {b4:>3} ({100*b4/len(ts):.0f}%)"
              f"  oráculo@4 {o4:>3} ({100*o4/len(ts):.0f}%)"
              f"  uplift realizable +{100*(b4-k1)/len(ts):.0f} pts")

    # k=1 oficial por estrato en las 198 (frontier vs oficial_low, firmado)
    low = {}
    for nombre in ("factorial.json", "factorial_low198.json"):
        d = json.loads((SALIDA / nombre).read_text(encoding="utf-8"))
        for m in d["muestras"]:
            if m["celda"] == "oficial_low":
                low.setdefault(m["tarea"], m)
    print(f"\n  --- S2: hueco k=1 por estrato en las 198 (ya firmado; "
          f"referencia) ---")
    s2_k1 = {}
    for dif in ("easy", "medium", "hard"):
        ts = [t for t, m in fro_orig.items() if m["dificultad"] == dif
              and t in low]
        fr = sum(1 for t in ts if fro_orig[t]["mio_pasa"])
        lo = sum(1 for t in ts if low[t]["mio_pasa"])
        s2_k1[dif] = {"n": len(ts), "frontier": fr, "low": lo}
        print(f"  {dif:<7} n={len(ts):<3}  frontier {fr:>3}/{len(ts)}  "
              f"20B low {lo:>3}/{len(ts)}  hueco {fr-lo:+d}")

    # apareado en el solape lcb∩frontier easy/medium (se espera SIN POTENCIA)
    print(f"\n  --- S2: apareado frontier vs BoN@4(lcb) en el solape "
          f"easy/medium (config distinta, DECLARADO) ---")
    s2_ap = {}
    for dif in ("easy", "medium"):
        ts = [t for t in por_lcb if dif_banco.get(t) == dif and t in fro_orig]
        if not ts:
            continue
        c = contraste([(bool(fro_orig[t]["mio_pasa"]),
                        bool(selector(por_lcb[t][:4])["pasa_oc"]))
                       for t in ts], f"S2  F − BoN@4(lcb) {dif} (n={len(ts)})")
        s2_ap[dif] = c
        print(fmt(c))

    # --- factor y gasto ---------------------------------------------------
    f_pct = niveles["frontier_k1"]["pct"]
    factores = {k: round(f_pct / max(0.1, niveles[k]["pct"]), 2)
                for k in ("raiz_k1", "bon4", "pool_bon4", "pool_total")}
    tok_raiz = sum(pools[t]["raiz"].get("tok_salida") or 0
                   for t in primaria_t)
    tok_bon4 = curva[-1]["tokens"]
    tok_total = sum(sum(m.get("tok_salida") or 0 for m in pools[t]["todos"])
                    for t in primaria_t)
    print(f"\n  --- FACTOR frontier/20B (descriptivo) y GASTO ---")
    print(f"  factores: {factores}")
    print(f"  tokens de salida: raíz {tok_raiz}  BoN@4 {tok_bon4}  "
          f"pool total {tok_total}")

    out = {"analisis": "ANALISIS_GOAL_RESPONDIDO_20260801.md",
           "universo": {"comunes": len(comunes),
                        "primaria_n": len(primaria_t),
                        "excluida_instrumento_plan": ARC_INSTRUMENTO_PLAN},
           "niveles": niveles, "contrastes": cts,
           "sensibilidad_arc191d": sens,
           "sensibilidad_confuga": sens_fuga,
           "cota_peor_caso_parada": {"tareas_fp": fp_parada,
                                     "c4_peor": c4_peor,
                                     "contraste": c4_peor_c},
           "sensibilidad_inst_20b": {"tareas": inst_20b, "contraste": sim},
           "veredictos_cambia_split": cambian,
           "curva_bon": curva, "s2_lcb_estratos": s2,
           "s2_k1_198": s2_k1, "s2_apareado_solape": s2_ap,
           "factores": factores,
           "gasto_tokens": {"raiz": tok_raiz, "bon4": tok_bon4,
                            "pool_total": tok_total}}
    (SALIDA / args.salida).write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {SALIDA / args.salida}")


if __name__ == "__main__":
    main()
