# -*- coding: utf-8 -*-
"""
b3_analisis.py — el veredicto del PREREG_BANCO_CODIGO_20260730.

Lee lo que b3_codigo.py dejó en disco y NO genera nada: separar generación de
análisis es lo que permite re-analizar sin volver a gastar GPU.

Tres bloques:

  1. ADMISIÓN del banco (criterio pre-registrado: pass@1 en [20%,80%]).
  2. EL EXPERIMENTO: CONTROL(s1) · AZAR · BoN · TECHO, todos sobre el MISMO
     conjunto de muestras y puntuados con el juez OCULTO. Primaria = neto
     apareado BoN−AZAR contra el p95 del brazo nulo (10.000 réplicas).
  3. EL EXAMEN: Youden J de los tests VISIBLES prediciendo los OCULTOS. Es
     la misma escala en la que se midió el contrato interno autogenerado
     (J=+12.2, ACUSA_SANOS 88-94%), así que por primera vez hay una
     comparación directa entre un examen que TRAE el benchmark y uno que
     escribe un LLM.
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


def por_tarea(res: dict) -> dict:
    d = defaultdict(list)
    for m in res["muestras"]:
        d[m["tarea"]].append(m)
    return {t: sorted(v, key=lambda m: m["s"]) for t, v in d.items()
            if len(v) == res["k"]}


def selector_bon(muestras: list) -> dict:
    """La política LITERAL de cognia/program_creator/bon.py:157-160 —
    aprobado > checks_ok > la más temprana."""
    return sorted(muestras, key=lambda m: (not m["pasa_vis"],
                                           -m["vis_ok"], m["s"]))[0]


def _brazos(tareas: dict, k: int) -> dict:
    """Los cuatro brazos sobre el MISMO pool de K, sin filtrar (enmienda 1.7:
    una muestra sin código cuenta como fallo en los cuatro; ningún ensayo se
    descarta, n idéntico en todos)."""
    control = sum(1 for v in tareas.values() if v[0]["pasa_oc"])
    bon = sum(1 for v in tareas.values() if selector_bon(v)["pasa_oc"])
    techo = sum(1 for v in tareas.values() if any(m["pasa_oc"] for m in v))
    # AZAR = VALOR ESPERADO del selector uniforme, no un sorteo realizado:
    # un sorteo metería ruido gratis en la primaria.
    azar = sum(sum(1 for m in v if m["pasa_oc"]) / k for v in tareas.values())

    # AZAR-VÁLIDAS: uniforme entre las muestras que al menos pasan UN test
    # visible. Separa "el selector ELIGE entre candidatos plausibles" de "el
    # selector solo DESCARTA lo que no compila" — que sería otra vez detectar
    # INACTIVIDAD en vez de incorrección.
    azar_val = 0.0
    for v in tareas.values():
        vivas = [m for m in v if m["vis_ok"] > 0] or v
        azar_val += sum(1 for m in vivas if m["pasa_oc"]) / len(vivas)

    rng = random.Random(20260730)
    vals = [[m["pasa_oc"] for m in v] for v in tareas.values()]
    nulo = sorted(sum(1 for fila in vals if fila[rng.randrange(k)])
                  for _ in range(REPLICAS))
    p95 = nulo[int(0.95 * REPLICAS)]
    p = sum(1 for x in nulo if x >= bon) / REPLICAS

    # nulo de AZAR-VÁLIDAS: mismo sorteo pero restringido a las plausibles
    rng2 = random.Random(20260731)
    pools = [[m["pasa_oc"] for m in ([x for x in v if x["vis_ok"] > 0] or v)]
             for v in tareas.values()]
    nulo_v = sorted(sum(1 for f in pools if f[rng2.randrange(len(f))])
                    for _ in range(REPLICAS))
    p95_v = nulo_v[int(0.95 * REPLICAS)]
    p_v = sum(1 for x in nulo_v if x >= bon) / REPLICAS

    return {"n": len(tareas), "control": control, "azar": azar, "bon": bon,
            "techo": techo, "p95": p95, "p": p, "vive": bool(bon > p95),
            "azar_validas": azar_val, "p95_validas": p95_v, "p_validas": p_v,
            "vive_validas": bool(bon > p95_v)}


def _fmt_p(p: float) -> str:
    """Con 10.000 réplicas el suelo alcanzable es 1e-4: no se escribe
    'P = 0.0001' cuando lo medido es '0 de 10.000'."""
    return "< 1e-4" if p <= 1.0 / REPLICAS else f"= {p:.4f}"


def analiza(res: dict, etiqueta: str) -> dict:
    tareas = por_tarea(res)
    k = res["k"]
    n = len(tareas)
    if not n:
        print(f"[{etiqueta}] sin tareas completas")
        return {}

    todas = [m for v in tareas.values() for m in v]
    pass1 = sum(1 for m in todas if m["pasa_oc"]) / len(todas)
    inst = sum(1 for m in todas if m["instrumento"])
    inst_juez = sum(1 for m in todas
                    if m.get("juez_vis") or m.get("juez_oc"))
    expirados = sum(1 for m in todas
                    if m.get("juez_oc") == "lote_expirado")

    # PRIMARIA (enmienda 1.7): solo tareas con 0 fallos de instrumento entre
    # las K. Si el efecto solo vive incluyendo las muestras vacías, lo medido
    # es INACTIVIDAD — la frase que ya mató 10 vías — y se dice tal cual.
    limpias = {t: v for t, v in tareas.items()
               if not any(m["instrumento"] for m in v)}
    B = _brazos(tareas, k)                       # secundaria: todo dentro
    L = _brazos(limpias, k) if limpias else None  # PRIMARIA

    control, bon, techo, azar_esp = B["control"], B["bon"], B["techo"], B["azar"]
    p95, p_azar_ge_bon, vive = B["p95"], B["p"], B["vive"]

    discriminantes = [t for t, v in tareas.items()
                      if 0 < sum(1 for m in v if m["pasa_oc"]) < k]
    # Si las K muestras empatan en (pasa_vis, vis_ok), bon.py cae en "índice
    # más temprano" = s1: ahí el BoN NO PUEDE batir al azar por construcción.
    empate_vis = [t for t, v in tareas.items()
                  if len({(m["pasa_vis"], m["vis_ok"]) for m in v}) == 1]

    print(f"\n{'='*66}\n[{etiqueta}]  banco={res['banco']}  n={n} tareas  "
          f"k={k}  temp={res['temp']}\n{'='*66}")
    admite = 0.20 <= pass1 <= 0.80
    print(f"  pass@1 (juez OCULTO)         : {pass1:.1%}   "
          f"[{len(todas)} muestras]")
    print(f"  ADMISION [20%,80%]           : "
          f"{'ENTRA' if admite else 'NO ENTRA — no discrimina'}")
    print(f"  fallos de INSTRUMENTO (gen)  : {inst}/{len(todas)} "
          f"({inst/len(todas):.1%})")
    print(f"  fallos de INSTRUMENTO (juez) : {inst_juez}/{len(todas)} "
          f"({inst_juez/len(todas):.1%})   lotes expirados: {expirados}")
    print(f"  tareas DISCRIMINANTES        : {len(discriminantes)}/{n} "
          f"({len(discriminantes)/n:.0%})  [1<=aciertos<=k-1]")
    print(f"  tareas con EMPATE en visibles: {len(empate_vis)}/{n} "
          f"({len(empate_vis)/n:.0%})  [ahí el BoN cae en s1: no puede ganar]")
    print(f"  --- los cuatro brazos, juez OCULTO, MISMO pool, apareados ---")
    print(f"  CONTROL (s1) [descriptivo]   : {control}/{n} ({control/n:.1%})")
    print(f"  AZAR (valor esperado)        : {azar_esp:.2f}/{n} "
          f"({azar_esp/n:.1%})   p95 del nulo = {p95}")
    print(f"  BoN (selector sobre VISIBLES): {bon}/{n} ({bon/n:.1%})")
    print(f"  TECHO (pass@{k})               : {techo}/{n} ({techo/n:.1%})")
    print(f"  --- PRIMARIA: solo tareas SIN fallo de instrumento ---")
    if L:
        print(f"  n limpias                    : {L['n']}/{n}")
        print(f"  AZAR {L['azar']:.2f}  ·  BoN {L['bon']}  ·  "
              f"TECHO {L['techo']}  ·  p95 nulo {L['p95']}")
        print(f"  NETO BoN - AZAR (PRIMARIA)   : "
              f"{L['bon'] - L['azar']:+.2f}")
        print(f"  P(azar >= BoN)               : {_fmt_p(L['p'])}")
        print(f"  VEREDICTO (BoN > p95 nulo)   : "
              f"{'VIVE' if L['vive'] else 'NO SUPERA EL NULO'}")
        print(f"  -- control anti-'solo descarta basura' --")
        print(f"  AZAR-VÁLIDAS (>=1 test vis.) : {L['azar_validas']:.2f}"
              f"   p95 {L['p95_validas']}")
        print(f"  NETO BoN - AZAR-VÁLIDAS      : "
              f"{L['bon'] - L['azar_validas']:+.2f}   "
              f"P {_fmt_p(L['p_validas'])}   "
              f"{'VIVE' if L['vive_validas'] else 'NO supera este nulo'}")
    else:
        print(f"  (ninguna tarea limpia)")
    print(f"  --- secundarias (todo el pool dentro) ---")
    print(f"  neto BoN - AZAR              : {bon - azar_esp:+.2f}   "
          f"P {_fmt_p(p_azar_ge_bon)}   "
          f"{'VIVE' if vive else 'no supera el nulo'}")
    print(f"  neto BoN - CONTROL           : {bon - control:+d}   "
          f"[descriptivo: s1 y AZAR son la misma distribución aquí]")
    print(f"  perdida del selector         : {techo - bon} "
          f"(techo acierta y BoN no)")
    if not admite:
        print(f"  >> REGLA (enmienda 1.6): el banco NO entra en banda, así "
              f"que su neto es DESCRIPTIVO y NO cuenta como réplica.")
    if res.get("banco") == "mbpp":
        print(f"  >> REGLA (enmienda 1.6): MBPP es HUMO y no cuenta como "
              f"réplica ni entrando en banda — su juez oculto es 1 assert en "
              f"el 97.8% y P(pasa oculto|pasa visibles)=0.849.")

    # --- el examen VISIBLE como predictor del OCULTO (misma escala que el
    # contrato interno autogenerado) ---
    sanas = [m for m in todas if m["pasa_oc"]]
    rotas = [m for m in todas if not m["pasa_oc"]]
    acusa = (sum(1 for m in sanas if not m["pasa_vis"]) / len(sanas) * 100
             if sanas else float("nan"))
    deja = (sum(1 for m in rotas if m["pasa_vis"]) / len(rotas) * 100
            if rotas else float("nan"))
    j = 100 - acusa - deja
    print(f"  --- EL EXAMEN: tests VISIBLES prediciendo los OCULTOS ---")
    print(f"  ACUSA_SANOS (rechaza correcta): {acusa:.1f}%  [n={len(sanas)}]")
    print(f"  DEJA_PASAR  (aprueba rota)    : {deja:.1f}%  [n={len(rotas)}]")
    print(f"  Youden J                      : {j:+.1f}")
    print(f"  [NO comparable con el J=+12.2 del contrato interno: aquél es "
          f"por PÁGINA contra un juez a mano; esto es por MUESTRA y "
          f"tests-contra-tests. Descriptiva interna del banco.]")

    return {"etiqueta": etiqueta, "banco": res["banco"], "n": n, "k": k,
            "pass1": round(pass1, 4), "admite": bool(admite),
            "cuenta_como_replica": bool(admite and res["banco"] != "mbpp"),
            "instrumento_gen": inst, "instrumento_juez": inst_juez,
            "lotes_expirados": expirados, "muestras": len(todas),
            "discriminantes": len(discriminantes),
            "empate_visibles": len(empate_vis),
            "todo": B, "primaria_limpias": L,
            "neto_bon_azar": round(bon - azar_esp, 2),
            "neto_bon_control": bon - control,
            "perdida_selector": techo - bon,
            "examen": {"acusa_sanos": round(acusa, 1),
                       "deja_pasar": round(deja, 1), "youden_j": round(j, 1),
                       "nota": "no comparable con el contrato interno"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ficheros", nargs="+")
    ap.add_argument("--salida", default="")
    args = ap.parse_args()

    out = []
    for f in args.ficheros:
        p = Path(f)
        if not p.is_absolute():
            p = SALIDA / f
        if not p.exists():
            print(f"[!] no existe: {p}")
            continue
        res = json.loads(p.read_text(encoding="utf-8"))
        r = analiza(res, p.stem)
        if r:
            out.append(r)

    if args.salida and out:
        Path(args.salida).write_text(
            json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n-> {args.salida}")


if __name__ == "__main__":
    main()
