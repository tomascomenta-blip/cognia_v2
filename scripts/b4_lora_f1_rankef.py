# -*- coding: utf-8 -*-
"""
b4_lora_f1_rankef.py — FASE 1 del PREREG_LORAS_20260801 (enmiendas 1-2):
¿lleva señal un ranker entrenado (RankEF sobre coder-14B) para elegir el
candidato correcto SIN ejecutar tests?

Diseño (todo pre-registrado):
- Pools: los discriminantes TOTALES de reparacion.json (>=2 candidatos,
  pasa_oc mixto). El ranker ve SOLO enunciado + _code (nunca crudo,
  contraejemplo ni metadatos). Orden de candidatos aleatorizado por pool
  (semilla 20260801:<tarea>), permutacion registrada.
- /tokenize ANTES de rankear: un pool que no quepa se EXCLUYE ENTERO y los
  nulos se recomputan sobre el n analizado (prohibido truncar, jamas).
- Un solo server 14B + adapter (--lora-init-without-apply): brazo BASE =
  escala 0, brazo ADAPTER = escala 1, hot-swap por /lora-adapters,
  cache_prompt=false. Gate de actividad S0->S1->S0 antes de rankear.
- Dos formatos de prompt (F-A directo, F-B con analisis breve), corridos
  AMBOS: si discrepan en el veredicto, "sin veredicto: señal fragil al
  prompt". Eleccion no parseable = fallo del metodo; >10% por formato x
  brazo => PARAR.
- Nulos (recomputados sobre los pools analizados, semilla 20260801):
  azar simulado (p95/p99) / ultimo-generado / mas-largo / primero.
  Lecturas: "señal sobre azar" si aciertos > p95; "UTIL para el goal" solo
  si > ultimo-generado (el mejor nulo gratuito).
"""
from __future__ import annotations

import json
import random
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb

SALIDA = RAIZ / "b4_loras"
B3 = RAIZ / "b3_codigo"
URL = "http://127.0.0.1:8091"
SEMILLA = 20260801
CTX = 16384
MARGEN_GEN = 512          # tokens reservados para la respuesta del ranker
# ENMIENDA 3: FA a 64 (bajo el adapter el numero llegaba tarde) y corrida 2
# por chat template (el adapter se entreno con plantilla; el crudo era una
# asimetria de instrumento contra el)
N_PREDICT = {"FA": 64, "FB": 400}


def _post(ruta, cuerpo, timeout=600):
    req = urllib.request.Request(
        f"{URL}{ruta}", data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _escala(s):
    _post("/lora-adapters", [{"id": 0, "scale": s}])


def _completa(prompt, n_predict):
    """ENMIENDA 3: via /v1/chat/completions para que el server aplique el
    chat template de la base — identico en ambos brazos y formatos."""
    r = _post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": n_predict, "temperature": 0.0, "top_k": 1,
        "seed": SEMILLA, "cache_prompt": False})
    return (r.get("choices") or [{}])[0].get("message", {}).get("content", "")


def pools_discriminantes():
    rep = json.loads((B3 / "reparacion.json").read_text(encoding="utf-8"))
    por = defaultdict(list)
    for m in rep["muestras"]:
        por[m["tarea"]].append(m)
    out = []
    for t, v in sorted(por.items()):
        if not any(x.get("cierre") for x in v):
            continue
        p = [x for x in v if not x.get("cierre") and not x.get("no_generado")]
        if len(p) >= 2 and len({m["pasa_oc"] for m in p}) > 1:
            out.append((t, p))
    return out


def prompt_de(tarea, enunciado, cands, formato):
    partes = [
        "You are reviewing candidate solutions to a competitive programming "
        "problem. WITHOUT running any code, decide which candidate is most "
        "likely to be fully correct on all hidden tests.",
        f"\n## Problem\n{enunciado}\n"]
    for i, c in enumerate(cands, 1):
        partes.append(f"\n## Candidate {i}\n```python\n{c}\n```\n")
    if formato == "FA":
        partes.append(f"\nAnswer with ONLY the number (1-{len(cands)}) of "
                      f"the most likely correct candidate.")
    else:
        partes.append(f"\nIn one short line per candidate, note its likely "
                      f"flaw or strength. Then answer on a new line with "
                      f"'FINAL: <number>' (1-{len(cands)}).")
    return "".join(partes)


def parsea(texto, n, formato):
    if formato == "FB":
        m = re.search(r"FINAL:\s*(\d+)", texto)
        if m and 1 <= int(m.group(1)) <= n:
            return int(m.group(1))
        return None
    m = re.search(r"\d+", texto)
    if m and 1 <= int(m.group(0)) <= n:
        return int(m.group(0))
    return None


def nulos_sobre(pools_orden_generacion):
    """ENMIENDA 3: los nulos deterministas van sobre el ORDEN DE GENERACION
    (la heuristica gratuita real), no sobre el barajado — mi corrida 1
    computaba 'ultimo' sobre el pool barajado, que es otra eleccion al azar.
    """
    rng = random.Random(SEMILLA)
    azar = sorted(sum(1 for p in pools_orden_generacion
                      if rng.choice(p)["pasa_oc"]) for _ in range(10000))
    ultimo = sum(1 for p in pools_orden_generacion if p[-1]["pasa_oc"])
    largo = sum(1 for p in pools_orden_generacion
                if max(p, key=lambda m: len(m.get("_code") or ""))["pasa_oc"])
    primero = sum(1 for p in pools_orden_generacion if p[0]["pasa_oc"])
    esperado = sum(sum(1 for m in p if m["pasa_oc"]) / len(p)
                   for p in pools_orden_generacion)
    return {"n": len(pools_orden_generacion),
            "azar_esperado": round(esperado, 2),
            "azar_p95": azar[9500], "azar_p99": azar[9900],
            "ultimo_generado": ultimo, "mas_largo": largo,
            "primero": primero}


def main():
    bank = {str(t["task_id"]): t for t in carga_lcb(
        ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))}
    pools = pools_discriminantes()
    print(f"pools discriminantes: {len(pools)}")

    # permutacion por pool + prompts en ambos formatos
    prep = []
    for tarea, p in pools:
        rng = random.Random(f"{SEMILLA}:{tarea}")
        perm = list(range(len(p)))
        rng.shuffle(perm)
        barajado = [p[i] for i in perm]
        enun = bank[tarea]["enunciado"]
        cands = [m.get("_code") or "" for m in barajado]
        prep.append({"tarea": tarea, "pool": barajado, "perm": perm,
                     "orig": p,
                     "pa": prompt_de(tarea, enun, cands, "FA"),
                     "pb": prompt_de(tarea, enun, cands, "FB")})

    # /tokenize ANTES: excluir pools que no caben (enteros, sin truncar)
    incluidos, excluidos = [], []
    for x in prep:
        toks = max(len(_post("/tokenize", {"content": x["pa"]})["tokens"]),
                   len(_post("/tokenize", {"content": x["pb"]})["tokens"]))
        x["tokens_prompt"] = toks
        if toks <= CTX - MARGEN_GEN:
            incluidos.append(x)
        else:
            excluidos.append((x["tarea"], toks))
    print(f"incluidos: {len(incluidos)}  excluidos por contexto: {excluidos}")

    nul = nulos_sobre([x["orig"] for x in incluidos])
    print(f"nulos sobre n={nul['n']}: azar~{nul['azar_esperado']} "
          f"p95={nul['azar_p95']} p99={nul['azar_p99']} "
          f"ULTIMO-GENERADO={nul['ultimo_generado']} "
          f"largo={nul['mas_largo']} primero={nul['primero']}")

    # gate de actividad del adapter (S0 -> S1 -> S0 sobre un prompt corto)
    sonda = "Explain in one sentence what a binary search does."
    _escala(0.0); s0a = _completa(sonda, 64)
    _escala(1.0); s1 = _completa(sonda, 64)
    _escala(0.0); s0b = _completa(sonda, 64)
    print(f"gate actividad: S1!=S0 {s1 != s0a}  ida-vuelta {s0a == s0b}")
    if s0a != s0b:
        print("FALLA: ida y vuelta de escala no reproducible"); sys.exit(2)
    if s1 == s0a:
        print("FALLA: el adapter RankEF es un no-op (S1==S0)"); sys.exit(2)

    res = {"prereg": "PREREG_LORAS_20260801.md (enmiendas 1-2)",
           "nulos": nul, "excluidos": excluidos, "brazos": {}}
    for brazo, escala in (("BASE", 0.0), ("ADAPTER", 1.0)):
        _escala(escala)
        for fmt, clave in (("FA", "pa"), ("FB", "pb")):
            aciertos = invalidos = 0
            detalle = []
            for x in incluidos:
                texto = _completa(x[clave], N_PREDICT[fmt])
                el = parsea(texto, len(x["pool"]), fmt)
                if el is None:
                    invalidos += 1
                    detalle.append({"tarea": x["tarea"], "eleccion": None})
                    continue
                ok = bool(x["pool"][el - 1]["pasa_oc"])
                aciertos += ok
                detalle.append({"tarea": x["tarea"], "eleccion": el,
                                "acierto": ok})
                print(f"  [{brazo}/{fmt}] {x['tarea']:<12} elige {el} "
                      f"{'OK' if ok else 'x'}", flush=True)
            clave_res = f"{brazo}_{fmt}"
            res["brazos"][clave_res] = {
                "aciertos": aciertos, "invalidos": invalidos,
                "n": len(incluidos), "detalle": detalle}
            tasa_inv = invalidos / max(1, len(incluidos))
            print(f"== {clave_res}: {aciertos}/{len(incluidos)} "
                  f"(invalidos {invalidos}, {tasa_inv:.0%})")
            if tasa_inv > 0.10:
                print("PARAR: >10% no parseable — reproducir a mano")
                res["parado_por_invalidos"] = clave_res
                break
        else:
            continue
        break

    # lecturas pre-registradas
    for clave_res, r in res["brazos"].items():
        senal = r["aciertos"] > nul["azar_p95"]
        util = r["aciertos"] > nul["ultimo_generado"]
        r["lee_senal_sobre_azar"] = senal
        r["lee_util_para_goal"] = util
        print(f"{clave_res}: señal>{nul['azar_p95']}: {senal}   "
              f"ÚTIL>{nul['ultimo_generado']}: {util}")

    SALIDA.mkdir(exist_ok=True)
    res["corrida"] = "2 (chat template, enmienda 3)"
    (SALIDA / "f1_rankef_v2.json").write_text(
        json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {SALIDA / 'f1_rankef_v2.json'}")


if __name__ == "__main__":
    main()
