r"""
exp021_speculative_decode / bench_small_base.py
===============================================
La medicion REAL que prueba el lever RADICAL: si el draft model (que como draft
HUNDE el habla a 0.37x por competir por banda) corre SOLO como base, ¿cuanto tok/s
da? En CPU bandwidth-bound (exp004) tok/s ~= BW / bytes_por_token; el 0.5B mueve
~1/4 de los bytes del 3B -> deberia hablar MUCHO mas rapido.

Esto materializa la idea de difusion 'commit mas por lectura' por la via opuesta:
en vez de mas tokens por lectura, hacer la LECTURA mas barata (modelo pequeno) y
escalar al 3B solo cuando se necesita profundidad (cascada, ya usada para codigo).

Mide el 0.5B como modelo principal sobre los MISMOS prompts (warm). Solo stdlib.
  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_small_base.py
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BINARY = REPO / "node" / "llama-server.exe"
SMALL = REPO / "model_shards" / "qwen-coder-0.5b-q4" / "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"
OUT = Path(__file__).resolve().parent / "results"
PORT = 8099
N_THREADS = max(1, (os.cpu_count() or 4) - 1)
N_PREDICT = 160

SYS = "Eres Cognia, un asistente util y conciso."
ECHO_TEXT = ("La fotosintesis es el proceso por el cual las plantas, las algas y algunas "
             "bacterias convierten la luz solar, el agua y el dioxido de carbono en glucosa "
             "y oxigeno. Ocurre principalmente en los cloroplastos.")
PROMPTS = {
    "code": "Escribe una funcion en Python llamada quicksort que ordene una lista de enteros.",
    "speech": "Explica en un parrafo, como si lo dijeras en voz alta a un nino, que es la "
              "fotosintesis y por que es importante.",
    "echo": "Reescribe en vinetas, conservando las palabras:\n\n" + ECHO_TEXT,
}


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


def gen(u, n=N_PREDICT):
    payload = json.dumps({"prompt": chatml(u), "n_predict": n, "temperature": 0.0,
                          "seed": 0, "cache_prompt": False, "ignore_eos": True, "stop": []}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    t = d.get("timings", {}) or {}
    return {"decode_tps": t.get("predicted_per_second"),
            "sha": hashlib.sha1(d.get("content", "").encode("utf-8", "ignore")).hexdigest()[:12]}


def main():
    assert SMALL.is_file(), f"falta {SMALL}"
    assert _port_free(), f"puerto {PORT} ocupado"
    cmd = [str(BINARY), "--model", str(SMALL), "--port", str(PORT), "--ctx-size", "8192",
           "--n-gpu-layers", "0", "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
           "--flash-attn", "on", "--log-disable"]
    log = OUT / "srv_small.log"
    fh = open(log, "w", encoding="utf-8", errors="ignore")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    dl = time.time() + 120
    while time.time() < dl and not _health():
        if p.poll() is not None:
            print("NO arranco:", log.read_text(encoding="utf-8", errors="ignore")[-600:]); return
        time.sleep(0.5)
    rows = {}
    try:
        gen("Hola, di una frase corta.", n=24)   # warmup
        for pn, pt in PROMPTS.items():
            m = gen(pt)
            rows[pn] = m["decode_tps"]
            print(f"[small-0.5B] {pn:>6} | decode={m['decode_tps']:.2f} tok/s", flush=True)
    finally:
        p.terminate()
        try: p.wait(timeout=10)
        except Exception: p.kill()

    res = {"experiment": "exp021/bench_small_base", "model": SMALL.name,
           "threads": N_THREADS, "n_predict": N_PREDICT, "decode_tps_0.5b_solo": rows}
    (OUT / "results_small_base.json").write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                                 encoding="utf-8")
    print("\n[small-0.5B] LISTO ->", OUT / "results_small_base.json")


if __name__ == "__main__":
    main()
