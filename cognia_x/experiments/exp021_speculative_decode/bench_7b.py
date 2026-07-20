r"""
exp021_speculative_decode / bench_7b.py
=======================================
Mide el 7B (Qwen2.5-Coder-7B Q4_K_M, 4.361 GiB) como modelo principal sobre los
MISMOS prompts y la MISMA metodologia warm que bench_small_base.py (0.5B) y el
baseline 3B, para responder con MEDICION (no proyeccion): en este i3
bandwidth-bound, ¿el 7B corre mas rapido o mas lento que el 3B (8.3 tok/s)?

Proyeccion de la ley de banda (exp004): 8.32 * (1.797 / 4.361) ~= 3.4 tok/s.
Esto lo verifica de verdad.
  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_7b.py
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
MODEL = REPO / "model_shards" / "qwen-coder-7b-q4" / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
OUT = Path(__file__).resolve().parent / "results"
PORT = 8097
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
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    t = d.get("timings", {}) or {}
    return {"decode_tps": t.get("predicted_per_second"),
            "sha": hashlib.sha1(d.get("content", "").encode("utf-8", "ignore")).hexdigest()[:12]}


def main():
    assert MODEL.is_file(), f"falta {MODEL}"
    assert _port_free(), f"puerto {PORT} ocupado"
    cmd = [str(BINARY), "--model", str(MODEL), "--port", str(PORT), "--ctx-size", "8192",
           "--n-gpu-layers", "0", "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
           "--flash-attn", "on", "--log-disable"]
    log = OUT / "srv_7b.log"
    fh = open(log, "w", encoding="utf-8", errors="ignore")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    dl = time.time() + 240
    while time.time() < dl and not _health():
        if p.poll() is not None:
            print("NO arranco:", log.read_text(encoding="utf-8", errors="ignore")[-600:]); return
        time.sleep(0.5)
    rows = {}
    try:
        gen("Hola, di una frase corta.", n=24)   # warmup (faultea pesos desde disco)
        for pn, pt in PROMPTS.items():
            m = gen(pt)
            rows[pn] = m["decode_tps"]
            print(f"[7B] {pn:>6} | decode={m['decode_tps']:.2f} tok/s", flush=True)
    finally:
        p.terminate()
        try: p.wait(timeout=10)
        except Exception: p.kill()

    base_3b = 8.32
    sp = rows.get("speech")
    res = {"experiment": "exp021/bench_7b", "model": MODEL.name, "size_GiB": 4.361,
           "threads": N_THREADS, "n_predict": N_PREDICT, "decode_tps_7b_solo": rows,
           "baseline_3b_speech_tps": base_3b,
           "ratio_7b_vs_3b_speech": round(sp / base_3b, 3) if sp else None,
           "proyeccion_banda_tps": round(8.32 * (1.797 / 4.361), 2)}
    (OUT / "results_7b.json").write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"\n[7B] speech vs 3B = {res['ratio_7b_vs_3b_speech']}x | proyeccion banda = "
          f"{res['proyeccion_banda_tps']} tok/s")
    print("[7B] LISTO ->", OUT / "results_7b.json")


if __name__ == "__main__":
    main()
