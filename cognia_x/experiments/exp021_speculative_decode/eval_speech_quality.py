r"""
exp021 / eval_speech_quality.py
===============================
El lever de 4.3x (base 0.5B) solo sirve para "hablar" si el español del 0.5B es
FLUIDO. Esto genera respuestas REALES (temp=0.7, EOS real, no ignore_eos) del 0.5B
y del 3B en prompts conversacionales en español, para comparar calidad vs velocidad.

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\eval_speech_quality.py
Solo stdlib.
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
MODELS = {
    "3B-Coder": REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
    "0.5B-Coder": REPO / "model_shards" / "qwen-coder-0.5b-q4" / "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
    "0.5B-Instruct": REPO / "model_shards" / "qwen-0.5b-instruct-q4" / "qwen2.5-0.5b-instruct-q4_k_m.gguf",
}
OUT = Path(__file__).resolve().parent / "results"
PORT = 8099
N_THREADS = max(1, (os.cpu_count() or 4) - 1)

SYS = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."
PROMPTS = {
    "cielo": "Cuéntame en pocas palabras por qué el cielo es azul, como si hablaras con un amigo.",
    "saludo": "Salúdame y preséntate como Cognia en dos frases.",
    "dormir": "Dame un consejo corto y práctico para dormir mejor.",
    "gravedad": "Explica qué es la gravedad en una sola frase sencilla.",
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


def gen(u):
    payload = json.dumps({"prompt": chatml(u), "n_predict": 130, "temperature": 0.7,
                          "top_p": 0.9, "seed": 0, "cache_prompt": True,
                          "stop": ["<|im_end|>", "<|endoftext|>"]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    t = d.get("timings", {}) or {}
    return {"text": d.get("content", "").strip(),
            "tok_s": round(t.get("predicted_per_second") or 0, 2),
            "n": t.get("predicted_n")}


def main():
    res = {}
    for tag, gguf in MODELS.items():
        if not gguf.is_file():
            print(f"[eval] {tag}: GGUF ausente, salto"); continue
        assert _port_free(), f"puerto {PORT} ocupado"
        cmd = [str(BINARY), "--model", str(gguf), "--port", str(PORT), "--ctx-size", "4096",
               "--n-gpu-layers", "0", "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
               "--flash-attn", "on", "--log-disable"]
        fh = open(OUT / f"srv_eval_{tag}.log", "w", encoding="utf-8", errors="ignore")
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
        dl = time.time() + 120
        while time.time() < dl and not _health():
            if p.poll() is not None:
                print(f"{tag} NO arranco"); break
            time.sleep(0.5)
        try:
            res[tag] = {}
            for pn, pt in PROMPTS.items():
                m = gen(pt)
                res[tag][pn] = m
                print(f"\n##### [{tag}] {pn}  ({m['tok_s']} tok/s, n={m['n']})", flush=True)
                print(m["text"], flush=True)
        finally:
            p.terminate()
            try: p.wait(timeout=10)
            except Exception: p.kill()
            time.sleep(1.0)
    (OUT / "results_speech_quality.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n[eval] LISTO ->", OUT / "results_speech_quality.json")


if __name__ == "__main__":
    main()
