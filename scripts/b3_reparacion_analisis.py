# -*- coding: utf-8 -*-
"""
b3_reparacion_analisis.py — el veredicto del PREREG_REPARACION_CONTRAEJEMPLO.

Lee lo que b3_reparacion.py dejó en disco y NO genera nada.

Los tres brazos comparten la raíz `s1` y la MISMA política de selección (la
literal de bon.py: aprobado > vis_ok > el más temprano), así que la diferencia
entre ellos es de PRODUCCIÓN de candidatos. Por eso la primaria es un neto
APAREADO a nivel tarea y la significación un test de PERMUTACIÓN apareado
(sign-flip), no una comparación de niveles: la varianza ENTRE corridas de este
repo está medida en ±34 puntos y haría ilegible cualquier lectura no apareada.
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
BRAZOS = ("bon", "rep", "pla")
NOMBRE = {"bon": "BoN (muestras independientes)",
          "rep": "REP (contraejemplo)",
          "pla": "PLACEBO (sin contraejemplo)"}


def selector(pool: list) -> dict:
    """La política LITERAL de cognia/program_creator/bon.py:157-160."""
    return sorted(pool, key=lambda m: (not m["pasa_vis"], -m["vis_ok"],
                                       m["idx"]))[0]


def pools_por_tarea(res: dict) -> dict:
    """{tarea: {"bon": [...], "rep": [...], "pla": [...]}} con la raíz DENTRO
    de los tres. Solo tareas con marca de cierre (completas)."""
    por = defaultdict(list)
    for m in res["muestras"]:
        por[m["tarea"]].append(m)
    out = {}
    for t, ms in por.items():
        if not any(m.get("cierre") for m in ms):
            continue                       # tarea a medias: fuera
        raiz = [m for m in ms if m["brazo"] == "raiz"]
        if len(raiz) != 1:
            continue
        d = {}
        for b in BRAZOS:
            propios = sorted([m for m in ms if m["brazo"] == b],
                             key=lambda m: m["idx"])
            d[b] = raiz + propios
        d["_raiz"] = raiz[0]
        d["_todas"] = [m for m in ms if not m.get("cierre")]
        out[t] = d
    return out


def _perm_apareado(difs: list, semilla: int = 20260731) -> tuple:
    """Test de permutación APAREADO (sign-flip) sobre las diferencias por
    tarea. Devuelve (P una cola en la dirección observada, P dos colas).

    ENMIENDA 1 del prereg (escrita ANTES de correr): el criterio PASA es
    DIRECCIONAL (`REP - BoN > 0`), así que la P que decide es la de UNA COLA
    en la dirección pre-declarada; la de dos colas se reporta al lado y si las
    dos discrepan se dice.
    """
    obs = sum(difs)
    nz = [d for d in difs if d]
    if not nz:
        return 1.0, 1.0
    rng = random.Random(semilla)
    ge = dos = 0
    for _ in range(REPLICAS):
        s = sum(d if rng.random() < 0.5 else -d for d in nz)
        if s >= obs:
            ge += 1
        if abs(s) >= abs(obs):
            dos += 1
    return ge / REPLICAS, dos / REPLICAS


def _fmt_p(p: float) -> str:
    return "< 1e-4" if p <= 1.0 / REPLICAS else f"= {p:.4f}"


def _nulos(pools: dict, brazo: str, k: int) -> dict:
    """Los TRES nulos sobre el pool REALIZADO del brazo, restringidos a las
    tareas donde se gastó el presupuesto ENTERO.

    Por qué la restricción: con parada temprana el pool se trunca justo cuando
    un candidato ACIERTA los visibles, así que el AZAR sobre un pool truncado
    está sesgado AL ALZA y no es el nulo que se cree. La versión sobre todas
    las tareas se reporta aparte y etiquetada como descriptiva.
    """
    def calcula(sub):
        if not sub:
            return None
        n = len(sub)
        azar = azar_cod = azar_1t = 0.0
        elegido = 0
        for pool in sub:
            azar += sum(1 for m in pool if m["pasa_oc"]) / len(pool)
            con_cod = [m for m in pool if not m["instrumento"]] or pool
            azar_cod += sum(1 for m in con_cod if m["pasa_oc"]) / len(con_cod)
            vivas = [m for m in pool if m["vis_ok"] > 0] or pool
            azar_1t += sum(1 for m in vivas if m["pasa_oc"]) / len(vivas)
            elegido += bool(selector(pool)["pasa_oc"])
        rng = random.Random(20260731)
        nulo = sorted(sum(1 for p in sub
                          if p[rng.randrange(len(p))]["pasa_oc"])
                      for _ in range(REPLICAS))
        p95 = nulo[int(0.95 * REPLICAS)]
        p = sum(1 for x in nulo if x >= elegido) / REPLICAS
        return {"n": n, "elegido": elegido, "azar": round(azar, 2),
                "azar_con_codigo": round(azar_cod, 2),
                "azar_1test": round(azar_1t, 2), "p95": p95, "p": p,
                "neto_azar": round(elegido - azar, 2),
                "neto_azar_codigo": round(elegido - azar_cod, 2),
                "neto_azar_1test": round(elegido - azar_1t, 2),
                "vive": bool(elegido > p95)}

    completos = [p[brazo] for p in pools.values() if len(p[brazo]) == k]
    todos = [p[brazo] for p in pools.values()]
    return {"presupuesto_entero": calcula(completos),
            "todas_descriptivo": calcula(todos)}


def analiza(res: dict) -> dict:
    k = res["k"]
    pools = pools_por_tarea(res)
    n = len(pools)
    if not n:
        print("sin tareas completas")
        return {}

    todas_m = [m for p in pools.values() for m in p["_todas"]]

    def _sucia(m):
        """Instrumento = generación MAL (vacía, truncada, HTTP, presupuesto)
        O juez MAL (lote expirado, arnés reventado). La primera versión solo
        miraba `instrumento` y dejaba entrar los fallos del JUEZ como si
        fueran fallos del modelo — el error que costó 48 veredictos anoche,
        cazado esta vez por la revisión adversarial antes de gastar la GPU."""
        return bool(m["instrumento"] or m.get("juez_vis")
                    or m.get("juez_oc"))

    n_inst = sum(1 for m in todas_m if _sucia(m))
    limpias_set = {t for t, p in pools.items()
                   if not any(_sucia(m) for m in p["_todas"])}

    # PRIMARIA sobre TODAS las tareas, no sobre las limpias. Excluir una tarea
    # porque alguna de sus ~10 generaciones tuvo un fallo de instrumento es
    # condicionar sobre una variable POST-TRATAMIENTO: los brazos difieren en
    # cuántas generaciones hacen y en qué prompts usan, así que la exclusión no
    # es simétrica entre brazos. Un fallo de instrumento hace fallar a ESE
    # candidato, que es conservador e idéntico para los tres. La versión
    # limpia se reporta al lado; si las dos discrepan en el veredicto, se dice
    # y no se firma ninguna.
    todas_t = dict(pools)
    limpias = {t: p for t, p in pools.items() if t in limpias_set}

    print(f"\n{'='*70}")
    print(f"REPARACION CON CONTRAEJEMPLO vs BEST-OF-N  —  "
          f"{res.get('dificultad','?')}  n={n} tareas  k={k}")
    print(f"{'='*70}")
    print(f"  generaciones totales          : {len(todas_m)}")
    print(f"  fallos de INSTRUMENTO         : {n_inst}/{len(todas_m)} "
          f"({n_inst/max(1,len(todas_m)):.1%})"
          f"   {'<< PARA Y REPRODUCE UN CASO A MANO' if n_inst/max(1,len(todas_m)) > 0.08 else ''}")
    print(f"  PRIMARIA = TODAS las tareas   : {n}   "
          f"(limpias, secundaria: {len(limpias)})")

    # --- niveles por brazo -------------------------------------------------
    niveles, gasto = {}, {}
    for b in BRAZOS:
        niveles[b] = sum(1 for p in todas_t.values()
                         if selector(p[b])["pasa_oc"])
        # solo GENERACIONES reales: los registros de corte
        # (`sin_codigo_previo`, `sin_contraejemplo`) llevan segundos=0 y no
        # gastaron GPU — contarlos inflaría el cómputo del brazo y falsearía
        # justo la comparación a iso-cómputo que es el eje del experimento.
        propias = [m for p in pools.values() for m in p[b]
                   if m["brazo"] == b and m["segundos"] > 0]
        raices = [p["_raiz"] for p in pools.values()]
        gasto[b] = {
            "generaciones_propias": len(propias),
            "generaciones_con_raiz": len(propias) + len(raices),
            "segundos_propios": round(sum(m["segundos"] for m in propias), 1),
            "segundos_con_raiz": round(
                sum(m["segundos"] for m in propias)
                + sum(m["segundos"] for m in raices), 1),
            "prompt_chars_medio": round(
                sum(m["prompt_chars"] for m in propias) / max(1, len(propias))),
            # ISO-CÓMPUTO EN TOKENS GENERADOS: el reloj de pared favorece al
            # brazo que repite el MISMO prompt (caché de prefill del servidor)
            # y castiga al que manda uno nuevo cada vez. Los tokens de salida
            # no dependen del caché.
            "tokens_salida_propios": sum(m.get("tok_salida") or 0
                                         for m in propias),
            "tokens_salida_con_raiz": (
                sum(m.get("tok_salida") or 0 for m in propias)
                + sum(m.get("tok_salida") or 0 for m in raices)),
        }
    techo = sum(1 for p in todas_t.values()
                if any(m["pasa_oc"] for m in p["bon"] + p["rep"] + p["pla"]))
    raiz_ok = sum(1 for p in todas_t.values() if p["_raiz"]["pasa_oc"])

    print(f"\n  --- NIVELES (juez OCULTO, TODAS las tareas, apareados) ---")
    print(f"  RAIZ s1 sola (descriptivo)    : {raiz_ok}/{n} "
          f"({raiz_ok/max(1,n):.1%})")
    for b in BRAZOS:
        print(f"  {NOMBRE[b]:<32}: {niveles[b]}/{n} "
              f"({niveles[b]/max(1,n):.1%})")
    print(f"  TECHO (union de los tres)     : {techo}/{n}")

    print(f"\n  --- COMPUTO REALMENTE GASTADO (la parada temprana lo mueve) ---")
    for b in BRAZOS:
        g = gasto[b]
        print(f"  {b:<4} generaciones {g['generaciones_con_raiz']:>4}"
              f"  tokens de salida {g['tokens_salida_con_raiz']:>8}"
              f"  segundos {g['segundos_con_raiz']:>7.0f}"
              f"  prompt~{g['prompt_chars_medio']:>6} chars")

    # --- las tres comparaciones apareadas ---------------------------------
    def apareado(a, b, universo):
        difs = [int(selector(p[a])["pasa_oc"]) - int(selector(p[b])["pasa_oc"])
                for p in universo.values()]
        p1, p2 = _perm_apareado(difs)
        gan = sum(1 for d in difs if d > 0)
        per = sum(1 for d in difs if d < 0)
        return {"neto": sum(difs), "gana": gan, "pierde": per,
                "discordantes": gan + per, "p_una_cola": p1, "p_dos_colas": p2}

    comp = {"rep_menos_bon": apareado("rep", "bon", todas_t),
            "rep_menos_pla": apareado("rep", "pla", todas_t),
            "pla_menos_bon": apareado("pla", "bon", todas_t)}
    comp_limpias = {"rep_menos_bon": apareado("rep", "bon", limpias)} \
        if limpias else {}

    print(f"\n  --- APAREADO a nivel tarea (test de permutacion, sign-flip) ---")
    for clave, etiq in (("rep_menos_bon", "PRIMARIA   REP - BoN"),
                        ("rep_menos_pla", "SECUND. 1  REP - PLACEBO"),
                        ("pla_menos_bon", "SECUND. 2  PLACEBO - BoN")):
        c = comp[clave]
        print(f"  {etiq:<26}: {c['neto']:+3d}   "
              f"(gana {c['gana']}, pierde {c['pierde']}, "
              f"discordantes {c['discordantes']})   "
              f"P1 {_fmt_p(c['p_una_cola'])}  P2 {_fmt_p(c['p_dos_colas'])}")
    if comp_limpias:
        cl = comp_limpias["rep_menos_bon"]
        print(f"  {'(solo limpias, secundaria)':<26}: {cl['neto']:+3d}   "
              f"(n={len(limpias)}, discordantes {cl['discordantes']})   "
              f"P1 {_fmt_p(cl['p_una_cola'])}")

    # --- POTENCIA: ¿podía este diseño detectar algo? ----------------------
    # Sin esto, un neto <=0 se firma como KILL cuando puede ser "no lo
    # veríamos aunque lo hubiera". Un revisor adversarial midió que con ~10
    # discordantes el sign-flip exige 9 victorias de 10, y lo comprobé yo
    # sobre lcb_uniforme.json: en `hard` solo el 18% de las tareas puede
    # discordar. La potencia se REPORTA con el resultado, siempre.
    c = comp["rep_menos_bon"]
    d = c["discordantes"]
    minimas = None
    for v in range(d + 1):
        pp = sum(comb(d, x) for x in range(v, d + 1)) / 2 ** d if d else 1.0
        if pp < 0.05:
            minimas = v
            break
    # efecto mínimo detectable: victorias necesarias menos las derrotas
    mde = (2 * minimas - d) if minimas is not None else None
    print(f"\n  --- POTENCIA DEL CONTRASTE (se reporta SIEMPRE) ---")
    print(f"  discordantes observados       : {d}/{n}")
    if minimas is None:
        print(f"  victorias para P<0.05         : IMPOSIBLE con {d} "
              f"discordantes")
    else:
        print(f"  victorias para P<0.05         : {minimas}/{d}  "
              f"=> efecto minimo detectable = {mde:+d} tareas netas")

    seg_rep = gasto["rep"]["segundos_con_raiz"]
    seg_bon = gasto["bon"]["segundos_con_raiz"]
    tok_rep = gasto["rep"]["tokens_salida_con_raiz"]
    tok_bon = gasto["bon"]["tokens_salida_con_raiz"]
    ratio = tok_rep / max(1.0, tok_bon)          # ISO-CÓMPUTO EN TOKENS
    ratio_reloj = seg_rep / max(1.0, seg_bon)
    gana_pla = comp["rep_menos_pla"]["neto"] > 0
    if minimas is None:
        veredicto = "SIN POTENCIA"
    elif c["neto"] <= 0 or c["p_una_cola"] >= 0.05:
        veredicto = "KILL" if mde is not None and abs(mde) <= 6 \
            else "SIN POTENCIA"
    elif gana_pla and ratio <= 1.3:
        veredicto = "PASA"
    else:
        veredicto = "GRIS"
    print(f"\n  computo REP/BoN en TOKENS     : {ratio:.2f}x "
          f"(umbral del prereg 1.30x)   [en reloj: {ratio_reloj:.2f}x, "
          f"contaminado por cache de prefill]")
    print(f"  VEREDICTO PRE-REGISTRADO      : {veredicto}")
    if veredicto == "SIN POTENCIA":
        print(f"  >> El diseno no distingue 'no hay efecto' de 'no lo veriamos"
              f" aunque lo hubiera'. NO se firma KILL.")

    # --- los tres nulos, por brazo ----------------------------------------
    # DESCRIPTIVOS Y NADA MÁS. El subconjunto "gastó el presupuesto entero" es
    # exactamente "ningún candidato pasó los visibles", o sea un subconjunto
    # SELECCIONADO POR EL RESULTADO: su AZAR no es el AZAR del banco. Se
    # imprimen porque dan contexto contra las corridas de anoche, pero no
    # entran en ningún veredicto de esta corrida — el veredicto es arm-vs-arm.
    print(f"\n  --- LOS TRES NULOS (DESCRIPTIVOS; subconjunto sesgado) ---")
    nulos = {}
    for b in BRAZOS:
        nulos[b] = _nulos(todas_t, b, k)
        e = nulos[b]["presupuesto_entero"]
        if not e:
            print(f"  {b:<4} (ninguna tarea gasto el presupuesto entero)")
            continue
        print(f"  {b:<4} n={e['n']:>3}  elegido {e['elegido']:>3}  "
              f"AZAR {e['azar']:>6.2f} ({e['neto_azar']:+6.2f})  "
              f"CON-CODIGO {e['azar_con_codigo']:>6.2f} "
              f"({e['neto_azar_codigo']:+6.2f})  "
              f"1-TEST {e['azar_1test']:>6.2f} ({e['neto_azar_1test']:+6.2f})"
              f"  P {_fmt_p(e['p'])}  {'VIVE' if e['vive'] else 'no supera'}")

    # --- ¿SOBREAJUSTA la reparación el examen visible? --------------------
    # Predicción escrita ANTES de ver los datos: el brazo REP recibe el test
    # visible que falló, así que puede aprender a pasar ESE test sin arreglar
    # el programa. Si eso pasa, REP ganará en visibles y perderá en ocultos, y
    # su DEJA_PASAR (pasa el visible, falla el oculto) será mayor que el de
    # BoN. Es la lectura de MECANISMO, no un corte post-hoc.
    sobreajuste = {}
    for b in BRAZOS:
        sel = [selector(p[b]) for p in todas_t.values()]
        vis = [m for m in sel if m["pasa_vis"]]
        sobreajuste[b] = {
            "elegidos_que_pasan_visibles": len(vis),
            "de_esos_fallan_oculto": sum(1 for m in vis if not m["pasa_oc"]),
            "deja_pasar_pct": round(
                100 * sum(1 for m in vis if not m["pasa_oc"]) / max(1, len(vis)), 1),
        }
    print(f"\n  --- ¿SOBREAJUSTA el brazo el examen VISIBLE? ---")
    print(f"  (de los elegidos que PASAN los visibles, cuantos FALLAN el oculto)")
    for b in BRAZOS:
        s = sobreajuste[b]
        print(f"  {b:<4} {s['de_esos_fallan_oculto']:>3}/"
              f"{s['elegidos_que_pasan_visibles']:<3} = "
              f"{s['deja_pasar_pct']:>5.1f}%   DEJA_PASAR del brazo")

    # --- salud del contraejemplo ------------------------------------------
    reps = [m for p in pools.values() for m in p["rep"] if m["brazo"] == "rep"]
    fuente = [p["_raiz"] for p in pools.values()] + \
             [m for p in pools.values() for m in p["rep"]
              if m["brazo"] == "rep"]
    con_ce = [m for m in fuente if m.get("contraejemplo")]
    con_exc = [m for m in con_ce if m["contraejemplo"].get("excepcion")]
    paradas = {b: sum(1 for p in pools.values() if len(p[b]) < k)
               for b in BRAZOS}
    print(f"\n  --- SALUD DEL CONTRAEJEMPLO Y DE LA PARADA TEMPRANA ---")
    print(f"  candidatos con contraejemplo  : {len(con_ce)}/{len(fuente)}")
    print(f"  ... degradado a EXCEPCION     : {len(con_exc)}/{max(1,len(con_ce))}"
          f" ({len(con_exc)/max(1,len(con_ce)):.1%})  "
          f"[ahi REP se parece al PLACEBO]")
    print(f"  rondas de reparacion emitidas : {len(reps)}")
    for b in BRAZOS:
        print(f"  parada temprana en {b:<4}       : {paradas[b]}/{n} tareas")

    return {"n": n, "n_limpias": len(limpias), "k": k,
            "generaciones": len(todas_m), "instrumento": n_inst,
            "raiz_ok": raiz_ok, "niveles": niveles, "techo": techo,
            "gasto": gasto, "comparaciones": comp,
            "comparacion_limpias": comp_limpias, "nulos": nulos,
            "potencia": {"discordantes": d, "victorias_para_p05": minimas,
                         "efecto_minimo_detectable": mde},
            "ratio_tokens": round(ratio, 3),
            "ratio_reloj": round(ratio_reloj, 3), "veredicto": veredicto,
            "sobreajuste_visible": sobreajuste,
            "contraejemplos": len(con_ce),
            "contraejemplos_excepcion": len(con_exc),
            "paradas_tempranas": paradas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fichero", nargs="?", default="reparacion.json")
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
        Path(args.salida).write_text(json.dumps(r, indent=1,
                                                ensure_ascii=False),
                                     encoding="utf-8")
        print(f"\n-> {args.salida}")


if __name__ == "__main__":
    main()
