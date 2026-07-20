# -*- coding: utf-8 -*-
"""G4 — Integridad merge+GGUF en el CLI REAL (TEORIA Parte 3 §3.3, DC-9/E5).

Re-corre G1(100) + G2A(147) con llama.cpp local (el MISMO camino del deploy:
node/llama-server.exe b9391, threads=3) sobre un GGUF dado, y compara ITEM A
ITEM contra los binarios del adapter-vivo medidos en el kernel de Kaggle
(McNemar pareado). PASA si el delta agregado GGUF-vs-adapter-vivo >= -4pp y
sin regresion significativa (p<0.05 con n10>n01).

La corrida de PERPLEXITY (+5% vs merge fp16, llama-perplexity) es una corrida
APARTE (protocolo comun) — este script la deja explicitamente fuera y lo
declara en el reporte (no finge un gate completo).

Instrumento pareado con el kernel: system neutro por idioma (E1b), greedy,
mismos oraculos (suite_oracle canonico).

Uso:
  # smoke del instrumento con la base Q4_K_M (sin kernel-json: solo accuracies)
  .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_g4_cli --gguf <path> --limit 8

  # gate real contra el adapter-vivo del kernel
  .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_g4_cli --gguf <path> \\
      --kernel-json results_emix/emix_results.json --brazo brazo_a
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITES = REPO / "cognia_v3" / "eval" / "suites"
sys.path.insert(0, str(SUITES))
from suite_oracle import oracle_pass, accion_pass, es_espanol, carga_suite  # noqa: E402

SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."


def chatml(prompt: str, idioma: str) -> str:
    sistema = SYSTEM_ES if idioma == "es" else SYSTEM_EN
    return (f"<|im_start|>system\n{sistema}<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def mcnemar_p(n01, n10):
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


SUITE_FILES = {"g1": "g1_general.jsonl", "g2a": "g2_accion.jsonl",
               "g3": "g3_identidad.jsonl", "g5": "g5_espanol.jsonl",
               "g2r": "g2_razonamiento.jsonl",
               "g2rlog": "g2_razonamiento_logica.jsonl"}


def resolve_suites(csv: str) -> dict:
    """csv 'g1,g2a' -> {clave: archivo}; ValueError si hay claves desconocidas."""
    pedidas = [s.strip() for s in csv.split(",") if s.strip()]
    invalidas = [s for s in pedidas if s not in SUITE_FILES]
    if invalidas:
        raise ValueError(f"suites desconocidas {invalidas} (validas: {sorted(SUITE_FILES)})")
    return {clave: SUITE_FILES[clave] for clave in pedidas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True, help="GGUF a evaluar en el CLI real")
    ap.add_argument("--kernel-json", default="", help="resultados del kernel con binarios del adapter-vivo")
    ap.add_argument("--brazo", default="", help="nombre del brazo en el kernel-json")
    ap.add_argument("--limit", type=int, default=0, help="solo N items por suite (smoke)")
    ap.add_argument("--suites", default="g1,g2a",
                    help="suites a correr (csv de g1,g2a,g3,g5,g2r); default el gate G4 clasico")
    ap.add_argument("--stepwise", action="store_true",
                    help="aplica augment_stepwise al prompt (la transformacion del "
                         "turno de chat del CLI) — instrumento de E-INT")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    try:
        archivos = resolve_suites(args.suites)
    except ValueError as e:
        print(f"[g4] ERROR: {e}")
        sys.exit(1)

    os.environ["LLAMA_GGUF_PATH"] = str(Path(args.gguf).resolve())
    from node.llama_backend import LlamaBackend
    backend = LlamaBackend.try_load()
    if backend is None:
        print("[g4] ERROR: no se pudo levantar llama-server con ese GGUF")
        sys.exit(1)
    print(f"[g4] backend OK: {backend.gguf_path.name if backend.gguf_path else '?'}", flush=True)

    suites = {}
    for clave in archivos:
        items = carga_suite(str(SUITES / archivos[clave]))
        if args.limit:
            items = items[:args.limit]
        suites[clave] = items

    transform = None
    if args.stepwise:
        # la MISMA transformacion del turno de chat del CLI (E-INT): asi el
        # numero medido es el del CAMINO REAL, no el del modelo pelado
        from cognia.agent.stepwise import augment_stepwise as transform
    res = {"gate": "G4", "gguf": str(args.gguf), "stepwise": bool(args.stepwise),
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "nota_honesta": ("perplexity (+5% vs merge fp16) NO corre aca: es la "
                            "corrida aparte del protocolo comun (llama-perplexity)"),
           "suites": {}, "veredicto": None}
    out = Path(args.out) if args.out else Path(
        f"cognia_v3/eval/results_g4_{time.strftime('%Y%m%d_%H%M')}.json")

    t0 = time.time()
    for clave, items in suites.items():
        binarios = {}
        for i, it in enumerate(items):
            prompt = transform(it["prompt"]) if transform else it["prompt"]
            # CoT necesita espacio para razonar antes de la respuesta
            max_new = it["max_new_tokens"] + (220 if transform and prompt != it["prompt"] else 0)
            # cache_prompt=False: benchmark DETERMINISTA. El KV-cache reusado
            # cambia los logits (experimento 2026-06-11) y metia ruido entre
            # corridas: E-INT lo cazo (G5 flip en un item NO transformado).
            raw = backend.generate(chatml(prompt, it["idioma"]),
                                   max_tokens=max_new, temperature=0.0,
                                   cache_prompt=False)
            raw = (raw or "").strip()
            if it["gate"] == "G2A":
                ok = accion_pass(raw, it["oracle"])
            else:
                ok = oracle_pass(raw, it["oracle"])
                if it["gate"] == "G5":
                    ok = ok and es_espanol(raw)
            binarios[it["id"]] = bool(ok)
            if (i + 1) % 10 == 0:
                acc = sum(binarios.values()) / len(binarios)
                print(f"  [{clave}] {i+1}/{len(items)} acc={acc:.1%} "
                      f"({(time.time()-t0)/60:.0f} min)", flush=True)
                out.write_text(json.dumps(res | {"parcial": {clave: binarios}},
                                          indent=1), encoding="utf-8")
        res["suites"][clave] = {"binarios": binarios,
                                "acc": round(sum(binarios.values()) / len(binarios), 4)}
        print(f"[g4] {clave}: {res['suites'][clave]['acc']:.1%}", flush=True)
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")

    # comparacion pareada vs adapter-vivo del kernel
    if args.kernel_json and args.brazo:
        kj = json.load(open(args.kernel_json, encoding="utf-8"))
        vivo = kj["evals"][args.brazo]["items"]
        comp, deltas = {}, []
        for clave in res["suites"]:
            b_vivo = vivo.get(clave)
            if not b_vivo:
                continue
            b_gguf = res["suites"][clave]["binarios"]
            comunes = [k for k in b_vivo if k in b_gguf]
            n01 = sum(1 for k in comunes if not b_vivo[k] and b_gguf[k])
            n10 = sum(1 for k in comunes if b_vivo[k] and not b_gguf[k])
            acc_v = sum(b_vivo[k] for k in comunes) / len(comunes)
            acc_g = sum(b_gguf[k] for k in comunes) / len(comunes)
            delta = (acc_g - acc_v) * 100
            deltas.append((len(comunes), delta))
            comp[clave] = {"acc_vivo": round(acc_v, 4), "acc_gguf": round(acc_g, 4),
                           "delta_pp": round(delta, 1), "n01": n01, "n10": n10,
                           "p": round(mcnemar_p(n01, n10), 4)}
        total = sum(n for n, _ in deltas)
        delta_agg = sum(n * d for n, d in deltas) / total if total else 0.0
        regresion_sig = any(c["p"] < 0.05 and c["n10"] > c["n01"] for c in comp.values())
        res["comparacion_vivo"] = comp
        res["veredicto"] = {"delta_agregado_pp": round(delta_agg, 2),
                            "pasa_delta": delta_agg >= -4.0,
                            "regresion_significativa": regresion_sig,
                            "G4_decode": (delta_agg >= -4.0) and not regresion_sig,
                            "pendiente": "perplexity (corrida aparte)"}
        print(f"[g4] VEREDICTO decode: {json.dumps(res['veredicto'])}", flush=True)

    res["wall_min"] = round((time.time() - t0) / 60, 1)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"[g4] DONE {res['wall_min']} min -> {out}", flush=True)


if __name__ == "__main__":
    main()
