r"""
exp021_speculative_decode / bench_draft.py  (v2 LIMPIA, con warmup)
==================================================================
Benchmark definitivo de decode tok/s sobre el i3 real, comparando:
  - baseline (sin speculative)
  - el mejor n-gram (ngram-simple, 0 modelo extra)
  - draft-simple con Qwen2.5-Coder-0.5B (draft real, vocab compatible)

Arregla el artefacto cold-mmap del bench v1: hace un WARMUP corto tras arrancar
el server (faultea los pesos a page-cache) ANTES de medir, asi todos los prompts
miden ancho-de-banda (RAM) y no disco.

Requiere el GGUF draft en DRAFT_GGUF (bajalo antes con curl; ver SESSION log).
Solo stdlib -> venv312.
  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_draft.py
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
GGUF = REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
DRAFT_GGUF = REPO / "model_shards" / "qwen-coder-0.5b-q4" / "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

PORT = 8099
N_THREADS = max(1, (os.cpu_count() or 4) - 1)
CTX = 8192
N_PREDICT = 160
BOOT_TIMEOUT = 150

SYS = "Eres Cognia, un asistente util y conciso."
ECHO_TEXT = (
    "La fotosintesis es el proceso por el cual las plantas, las algas y algunas "
    "bacterias convierten la luz solar, el agua y el dioxido de carbono en glucosa "
    "y oxigeno. Ocurre principalmente en los cloroplastos, gracias a un pigmento "
    "llamado clorofila que captura la energia luminosa."
)
PROMPTS = {
    "code": "Escribe una funcion en Python llamada quicksort que ordene una lista de "
            "enteros, con comentarios que expliquen cada paso y un ejemplo de uso.",
    "speech": "Explica en un parrafo, como si lo dijeras en voz alta a un nino, que es "
              "la fotosintesis y por que es importante para la vida en la Tierra.",
    "echo": "Reescribe el siguiente texto en una lista de vinetas, conservando las "
            "mismas palabras tanto como sea posible:\n\n" + ECHO_TEXT,
}


def chatml(u: str) -> str:
    return (f"<|im_start|>system\n{SYS}<|im_end|>\n"
            f"<|im_start|>user\n{u}<|im_end|>\n<|im_start|>assistant\n")


def configs() -> list:
    c = [
        {"name": "baseline", "args": []},
        {"name": "ngram-simple", "args": ["--spec-type", "ngram-simple",
                                          "--spec-ngram-simple-size-n", "2",
                                          "--spec-ngram-simple-size-m", "8",
                                          "--spec-ngram-simple-min-hits", "1",
                                          "--spec-draft-n-max", "8"]},
    ]
    if DRAFT_GGUF.is_file():
        c.append({"name": "draft-0.5B", "args": ["--spec-type", "draft-simple",
                                                 "-md", str(DRAFT_GGUF),
                                                 "--spec-draft-n-max", "5"]})
    return c


def _port_free() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) != 0
    finally:
        s.close()


def _health() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def launch(cfg: dict):
    log = OUT / f"srv2_{cfg['name']}.log"
    cmd = [str(BINARY), "--model", str(GGUF), "--port", str(PORT),
           "--ctx-size", str(CTX), "--n-gpu-layers", "0",
           "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
           "--flash-attn", "on", "--log-disable"] + cfg["args"]
    fh = open(log, "w", encoding="utf-8", errors="ignore")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    dl = time.time() + BOOT_TIMEOUT
    while time.time() < dl:
        if p.poll() is not None:
            return None, log
        if _health():
            return p, log
        time.sleep(0.5)
    p.kill(); return None, log


def gen(user: str, n_predict: int = N_PREDICT) -> dict:
    payload = json.dumps({
        "prompt": chatml(user), "n_predict": n_predict, "temperature": 0.0,
        "seed": 0, "cache_prompt": False, "ignore_eos": True, "stop": [],
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.loads(r.read())
    tim = data.get("timings", {}) or {}
    content = data.get("content", "")
    return {"decode_tps": tim.get("predicted_per_second"),
            "predicted_n": tim.get("predicted_n") or data.get("tokens_predicted"),
            "sha": hashlib.sha1(content.encode("utf-8", "ignore")).hexdigest()[:12]}


def main() -> None:
    assert BINARY.is_file() and GGUF.is_file()
    results = {"experiment": "exp021/bench_draft_v2",
               "config": {"threads": N_THREADS, "ctx": CTX, "n_predict": N_PREDICT,
                          "draft_present": DRAFT_GGUF.is_file()},
               "runs": [], "errors": []}
    for cfg in configs():
        if not _port_free():
            print(f"[bench2] puerto {PORT} ocupado; abort"); break
        print(f"\n[bench2] === {cfg['name']} ===", flush=True)
        p, log = launch(cfg)
        if p is None:
            tail = log.read_text(encoding="utf-8", errors="ignore")[-800:]
            print(f"[bench2] {cfg['name']} NO arranco:\n{tail}", flush=True)
            results["errors"].append({"config": cfg["name"], "log_tail": tail}); continue
        try:
            gen("Hola, di una frase corta.", n_predict=24)          # WARMUP (page-cache)
            for pn, pt in PROMPTS.items():
                m = gen(pt)
                results["runs"].append({"config": cfg["name"], "prompt": pn, **m})
                print(f"[bench2] {cfg['name']:>12} | {pn:>6} | "
                      f"decode={m['decode_tps']:.2f} tok/s | sha={m['sha']}", flush=True)
        finally:
            p.terminate()
            try: p.wait(timeout=10)
            except Exception: p.kill()
            time.sleep(1.0)

    base = {r["prompt"]: r for r in results["runs"] if r["config"] == "baseline"}
    summary = []
    for r in results["runs"]:
        if r["config"] == "baseline":
            continue
        b = base.get(r["prompt"])
        if b and b["decode_tps"] and r["decode_tps"]:
            summary.append({"config": r["config"], "prompt": r["prompt"],
                            "baseline_tps": round(b["decode_tps"], 2),
                            "spec_tps": round(r["decode_tps"], 2),
                            "speedup": round(r["decode_tps"] / b["decode_tps"], 3),
                            "lossless": r["sha"] == b["sha"]})
    results["summary"] = summary
    (OUT / "results_draft.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    print("\n[bench2] LISTO ->", OUT / "results_draft.json", flush=True)
    for s in summary:
        print(f"  {s['config']:>12} | {s['prompt']:>6} | {s['speedup']}x | "
              f"lossless={'OK' if s['lossless'] else 'NO'}", flush=True)


if __name__ == "__main__":
    main()
