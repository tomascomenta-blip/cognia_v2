# -*- coding: utf-8 -*-
"""Gates de PREREG_PORTERO_FASE2 — portero 0.5B en el deploy real.

Subcomandos:
  scan      P-PORT-4/5: cobertura del router sobre G3 (esperado 20/20) y FP
            sobre los 422 prompts no-triviales (g1+g2a+g2r+g2rlog+g5, esperado
            0). Determinista, sin modelo.
  g3        P-PORT-3/6: corre los 20 items de G3 por UN brazo del deploy
            (--brazo portero | 3b) con greedy + cache_prompt=false, guardando
            binarios del oraculo + timings reales del server (decode tok/s,
            prefill, wall). MATAR llama-server entre brazos (regla del
            programa; este script para su propio server al salir).
  veredicto Junta ambos brazos: G3-deploy (portero para lo ruteado + 3B para
            el resto), McNemar pareado y ratio de latencia pareado vs gates.

Uso (venv312, desde el repo):
  python -m cognia_v3.eval.eval_portero_deploy scan
  python -m cognia_v3.eval.eval_portero_deploy g3 --brazo portero
  taskkill /IM llama-server.exe /F
  python -m cognia_v3.eval.eval_portero_deploy g3 --brazo 3b
  taskkill /IM llama-server.exe /F
  python -m cognia_v3.eval.eval_portero_deploy veredicto
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITES = REPO / "cognia_v3" / "eval" / "suites"
sys.path.insert(0, str(SUITES))
from suite_oracle import oracle_pass, carga_suite  # noqa: E402

OUT_DIR = REPO / "cognia_v3" / "eval"
OUT_PORTERO = OUT_DIR / "results_portero_deploy_portero.json"
OUT_3B = OUT_DIR / "results_portero_deploy_3b.json"

SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

# gates congelados (PREREG_PORTERO_FASE2, commit cde2427)
GATE_G3_MIN = 0.90
GATE_LAT_RATIO_MIN = 3.0

NO_TRIVIALES = ["g1_general.jsonl", "g2_accion.jsonl", "g2_razonamiento.jsonl",
                "g2_razonamiento_logica.jsonl", "g5_espanol.jsonl"]


def _chatml(system: str, user: str) -> str:
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")


def _completion(port: int, prompt: str, n: int) -> dict:
    payload = json.dumps({"prompt": prompt, "n_predict": n, "temperature": 0.0,
                          "cache_prompt": False,
                          "stop": ["<|im_end|>", "<|endoftext|>"]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/completion",
                                 data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def cmd_scan() -> int:
    from node.speech_cascade import classify_turn

    g3 = carga_suite(str(SUITES / "g3_identidad.jsonl"))
    ruteados = [it["id"] for it in g3
                if classify_turn(it["prompt"], identidad=True) == "fast"]
    print(f"[scan] cobertura G3 -> portero: {len(ruteados)}/{len(g3)}")
    faltan = [it["id"] for it in g3 if it["id"] not in ruteados]
    if faltan:
        print(f"  [scan] NO rutean: {faltan}")

    fp_total = 0
    detalles = []
    for f in NO_TRIVIALES:
        items = carga_suite(str(SUITES / f))
        fps = [it["id"] for it in items
               if classify_turn(it["prompt"], identidad=True) == "fast"]
        fp_total += len(fps)
        print(f"[scan] {f}: {len(fps)} FP / {len(items)}")
        detalles += [(f, i) for i in fps]
    for f, i in detalles:
        print(f"  FP: {f} {i}")
    ok = (len(ruteados) == len(g3)) and fp_total == 0
    print(f"[scan] P-PORT-4 cobertura {len(ruteados)}/{len(g3)} "
          f"{'PASS' if len(ruteados) == len(g3) else 'FAIL'} | "
          f"P-PORT-5 FP={fp_total} {'PASS' if fp_total == 0 else 'FAIL'}")
    return 0 if ok else 1


def cmd_g3(brazo: str) -> int:
    g3 = carga_suite(str(SUITES / "g3_identidad.jsonl"))
    res = {"brazo": brazo, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
           "items": {}}
    backend = None
    try:
        if brazo == "portero":
            from node.speech_cascade import (classify_turn, fast_speech_backend,
                                             portero_activo, portero_system,
                                             _FAST_PORT)
            if not portero_activo():
                print("[g3] ERROR: portero no disponible (archivos/kill-switch)")
                return 1
            backend = fast_speech_backend()
            if backend is None:
                print("[g3] ERROR: el portero no arrancó")
                return 1
            port = _FAST_PORT
            print(f"[g3] brazo PORTERO arriba en :{port} (ctx 4096, LoRA estática)")
            for it in g3:
                route = classify_turn(it["prompt"], identidad=True)
                if route != "fast":
                    res["items"][it["id"]] = {"route": "deep"}
                    print(f"  {it['id']}: ruta 3B (no medido en este brazo)")
                    continue
                prompt = _chatml(portero_system(it["prompt"]), it["prompt"])
                t0 = time.time()
                data = _completion(port, prompt, it["max_new_tokens"])
                wall = time.time() - t0
                txt = (data.get("content") or "").strip()
                ok = bool(oracle_pass(txt, it["oracle"]))
                tim = data.get("timings", {})
                res["items"][it["id"]] = {
                    "route": "portero", "ok": ok, "wall_s": round(wall, 2),
                    "decode_tps": tim.get("predicted_per_second"),
                    "prefill_ms": tim.get("prompt_ms"),
                    "n_pred": tim.get("predicted_n"),
                    "resp": txt[:120]}
                print(f"  {it['id']}: {'OK ' if ok else 'FAIL'} "
                      f"{tim.get('predicted_per_second') and round(tim['predicted_per_second'], 1)} tok/s "
                      f"wall {wall:.1f}s — {txt[:60]!r}")
        elif brazo == "3b":
            # el deploy actual de identidad: 3B + experto accion (hot-swap)
            from cognia.first_run import apply_config
            apply_config()
            from node.llama_backend import _LlamaServerBackend, _find_gguf, LlamaBackend
            gguf = _find_gguf()
            if gguf is None:
                print("[g3] ERROR: no hay GGUF del 3B (LLAMA_GGUF_PATH/config.env)")
                return 1
            impl = _LlamaServerBackend(gguf)
            backend = LlamaBackend(impl)
            if "accion" not in backend.fleet_experts:
                print(f"[g3] ERROR: fleet sin 'accion' ({backend.fleet_experts})")
                return 1
            if not backend.activate_expert("accion"):
                print("[g3] ERROR: no se pudo activar el experto accion")
                return 1
            port = impl._port
            print(f"[g3] brazo 3B+accion arriba en :{port} ({gguf.name})")
            for it in g3:
                system = SYSTEM_ES if it["idioma"] == "es" else SYSTEM_EN
                prompt = _chatml(system, it["prompt"])
                t0 = time.time()
                data = _completion(port, prompt, it["max_new_tokens"])
                wall = time.time() - t0
                txt = (data.get("content") or "").strip()
                ok = bool(oracle_pass(txt, it["oracle"]))
                tim = data.get("timings", {})
                res["items"][it["id"]] = {
                    "route": "3b", "ok": ok, "wall_s": round(wall, 2),
                    "decode_tps": tim.get("predicted_per_second"),
                    "prefill_ms": tim.get("prompt_ms"),
                    "n_pred": tim.get("predicted_n"),
                    "resp": txt[:120]}
                print(f"  {it['id']}: {'OK ' if ok else 'FAIL'} "
                      f"{tim.get('predicted_per_second') and round(tim['predicted_per_second'], 1)} tok/s "
                      f"wall {wall:.1f}s — {txt[:60]!r}")
        else:
            print(f"[g3] brazo desconocido: {brazo}")
            return 1
    finally:
        stop = getattr(backend, "stop", None)
        if callable(stop):
            stop()
            print("[g3] server del brazo parado")

    out = OUT_PORTERO if brazo == "portero" else OUT_3B
    medidos = [v for v in res["items"].values() if "ok" in v]
    res["acc"] = round(sum(v["ok"] for v in medidos) / len(medidos), 4) if medidos else None
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[g3] {brazo}: acc={res['acc']} ({len(medidos)} medidos) -> {out.name}")
    return 0


def cmd_veredicto() -> int:
    from cognia_v3.eval.eval_g4_cli import mcnemar_p

    rp = json.loads(OUT_PORTERO.read_text(encoding="utf-8"))
    r3 = json.loads(OUT_3B.read_text(encoding="utf-8"))
    ids = list(r3["items"].keys())

    # G3 en deploy = portero donde ruteó + 3B donde no (la ruta real del CLI)
    deploy_ok, port_ids = {}, []
    for i in ids:
        p = rp["items"].get(i, {})
        if p.get("route") == "portero":
            deploy_ok[i] = p["ok"]
            port_ids.append(i)
        else:
            deploy_ok[i] = r3["items"][i]["ok"]
    acc_deploy = sum(deploy_ok.values()) / len(ids)
    acc_3b = sum(r3["items"][i]["ok"] for i in ids) / len(ids)

    n01 = sum(1 for i in ids if not r3["items"][i]["ok"] and deploy_ok[i])
    n10 = sum(1 for i in ids if r3["items"][i]["ok"] and not deploy_ok[i])
    p = mcnemar_p(n01, n10)

    # latencia pareada SOLO en los items que el portero atendió
    dec_p = [rp["items"][i]["decode_tps"] for i in port_ids
             if rp["items"][i].get("decode_tps")]
    dec_3 = [r3["items"][i]["decode_tps"] for i in port_ids
             if r3["items"][i].get("decode_tps")]
    wall_p = [rp["items"][i]["wall_s"] for i in port_ids]
    wall_3 = [r3["items"][i]["wall_s"] for i in port_ids]
    ratio_dec = (statistics.mean(dec_p) / statistics.mean(dec_3)) if dec_p and dec_3 else 0.0
    ratio_item = statistics.median(
        rp["items"][i]["decode_tps"] / r3["items"][i]["decode_tps"]
        for i in port_ids
        if rp["items"][i].get("decode_tps") and r3["items"][i].get("decode_tps"))

    v = {
        "cobertura_portero": f"{len(port_ids)}/{len(ids)}",
        "G3_deploy_acc": round(acc_deploy, 4),
        "G3_3b_acc": round(acc_3b, 4),
        "mcnemar": {"n01": n01, "n10": n10, "p": round(p, 4)},
        "decode_tps_portero": round(statistics.mean(dec_p), 1) if dec_p else None,
        "decode_tps_3b": round(statistics.mean(dec_3), 1) if dec_3 else None,
        "ratio_decode_medias": round(ratio_dec, 2),
        "ratio_decode_mediana_pareada": round(ratio_item, 2),
        "wall_portero_s_mediana": round(statistics.median(wall_p), 2) if wall_p else None,
        "wall_3b_s_mediana": round(statistics.median(wall_3), 2) if wall_3 else None,
        "P-PORT-3": "PASS" if acc_deploy >= GATE_G3_MIN else "FAIL",
        "P-PORT-6": "PASS" if ratio_dec >= GATE_LAT_RATIO_MIN else "FAIL",
    }
    out = OUT_DIR / "results_portero_deploy_veredicto.json"
    out.write_text(json.dumps(v, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(v, indent=1, ensure_ascii=False))
    return 0 if v["P-PORT-3"] == "PASS" and v["P-PORT-6"] == "PASS" else 1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    g3 = sub.add_parser("g3")
    g3.add_argument("--brazo", required=True, choices=["portero", "3b"])
    sub.add_parser("veredicto")
    args = ap.parse_args()
    if args.cmd == "scan":
        return cmd_scan()
    if args.cmd == "g3":
        return cmd_g3(args.brazo)
    return cmd_veredicto()


if __name__ == "__main__":
    sys.exit(main())
