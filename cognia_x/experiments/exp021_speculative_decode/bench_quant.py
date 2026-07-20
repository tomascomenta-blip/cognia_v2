r"""
exp021 / bench_quant.py — Lever de CUANTIZACIÓN (CYCLE 11, F-SPEED)
==================================================================
En un decoder bandwidth-bound (exp004), tok/s ≈ BW / bytes-por-token. Bajar la
cuantización del 3B mueve MENOS bytes/token → más rápido, a costa de calidad.
Mide Q3_K_S (1.45 GiB, ya en disco) vs Q4_K_M (1.93 GiB) sobre el i3 real: tok/s de
decode (warm, ignore_eos) + una muestra de calidad real (temp 0.7). Solo stdlib.

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_quant.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BINARY = REPO / "node" / "llama-server.exe"
MD = REPO / "model_shards" / "qwen-coder-3b-q4"
MODELS = {"Q4_K_M": MD / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
          "Q3_K_S": MD / "Qwen2.5-Coder-3B-Instruct-Q3_K_S.gguf"}
OUT = Path(__file__).resolve().parent / "results"
PORT = 8099
N_THREADS = max(1, (os.cpu_count() or 4) - 1)

SYS = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."
TIMED = {  # ignore_eos → tok/s de decode limpio
    "speech": "Explica en un parrafo, como en voz alta, que es la fotosintesis.",
    "code": "Escribe una funcion quicksort en Python con comentarios.",
}
QUALITY = "Explica en 2 frases por que el cielo es azul."


def chatml(u):
    return (f"<|im_start|>system\n{SYS}<|im_end|>\n<|im_start|>user\n{u}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def _port_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) != 0
    finally:
        s.close()


def _health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def gen(u, n, temp, ignore_eos):
    p = {"prompt": chatml(u), "n_predict": n, "temperature": temp, "seed": 0,
         "cache_prompt": False, "stop": ["<|im_end|>"]}
    if ignore_eos:
        p["ignore_eos"] = True
        p["stop"] = []
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion",
                                 data=json.dumps(p).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    t = d.get("timings", {}) or {}
    return {"tok_s": round(t.get("predicted_per_second") or 0, 2),
            "text": (d.get("content") or "").strip()}


def main():
    try:
        import sys; sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    res = {"experiment": "exp021/bench_quant", "threads": N_THREADS, "models": {}}
    for tag, gguf in MODELS.items():
        if not gguf.is_file() or not _port_free():
            print(f"[quant] {tag}: skip (falta GGUF o puerto ocupado)"); continue
        size_gib = round(gguf.stat().st_size / 1024**3, 3)
        cmd = [str(BINARY), "--model", str(gguf), "--port", str(PORT), "--ctx-size", "4096",
               "--n-gpu-layers", "0", "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
               "--flash-attn", "on", "--log-disable"]
        fh = open(OUT / f"srv_quant_{tag}.log", "w", encoding="utf-8", errors="ignore")
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
        dl = time.time() + 120
        while time.time() < dl and not _health():
            if proc.poll() is not None:
                print(f"[quant] {tag} NO arranco"); break
            time.sleep(0.5)
        try:
            gen("Hola.", 16, 0.0, True)  # warmup (page-cache)
            tps = {k: gen(v, 128, 0.0, True)["tok_s"] for k, v in TIMED.items()}
            quality = gen(QUALITY, 90, 0.7, False)["text"]
            res["models"][tag] = {"size_gib": size_gib, "tok_s": tps, "quality_sample": quality}
            print(f"\n##### {tag} ({size_gib} GiB)  tok/s={tps}")
            print(f"   calidad: {quality[:160]}")
        finally:
            proc.terminate()
            try: proc.wait(timeout=10)
            except Exception: proc.kill()
            time.sleep(1.0)

    # speedup Q3 vs Q4
    if "Q4_K_M" in res["models"] and "Q3_K_S" in res["models"]:
        q4, q3 = res["models"]["Q4_K_M"], res["models"]["Q3_K_S"]
        res["speedup_q3_vs_q4"] = {k: round(q3["tok_s"][k] / q4["tok_s"][k], 3)
                                   for k in q4["tok_s"] if q4["tok_s"][k]}
        print("\n[quant] speedup Q3_K_S vs Q4_K_M:", res["speedup_q3_vs_q4"])
    (OUT / "results_quant.json").write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    print("[quant] -> results_quant.json")


if __name__ == "__main__":
    main()
