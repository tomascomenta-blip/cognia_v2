r"""
exp021_speculative_decode / bench_real.py
=========================================
GOAL (North Star): que Cognia X hable a velocidad alta. El decode en CPU es
MEMORY-BANDWIDTH-BOUND (dato propio exp004: ~15-22 GB/s, satura a 2 hilos).
Cada token ~= una lectura completa de los pesos (Q4_K_M 3B ~1.93 GB) desde RAM.

Speculative decoding y la difusion (DiffusionGemma) son DUALES: ambos rompen
el acople "1 lectura de pesos = 1 token", commiteando varios tokens por lectura.
La difusion necesita un modelo de difusion (26B, GPU) -> inviable en i3.
Speculative funciona con el GGUF AR que YA existe, sin re-entrenar la base.

Este benchmark mide, SOBRE EL HARDWARE REAL (i3, llama-server b9391, Qwen3B
Q4_K_M), el tok/s de decode de:
  - baseline (sin speculative)
  - ngram-* (drafter de coste de banda ~0: 0 modelo extra, 0 entrenamiento)
para varios tipos de prompt (codigo, habla natural en espanol, eco/reescritura).

Verificacion de correctitud: a temperature=0 (greedy) speculative es LOSSLESS,
asi que la salida debe ser IDENTICA al baseline (se chequea por SHA del texto).

Solo stdlib -> corre con venv312 sin dependencias.
  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_real.py
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ── rutas reales del repo ──────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[3]
BINARY = REPO / "node" / "llama-server.exe"
GGUF = REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

PORT = 8099                      # puerto dedicado al bench (no choca con prod 8088)
N_THREADS = max(1, (os.cpu_count() or 4) - 1)   # 3 en el i3 (exp: 4to hilo dana)
CTX = 8192
N_PREDICT = 160                  # tokens de decode fijos por gen (ignore_eos)
SERVER_BOOT_TIMEOUT = 150        # s

# ── prompts (ChatML de Qwen) ───────────────────────────────────────────────
SYS = "Eres Cognia, un asistente util y conciso."
ECHO_TEXT = (
    "La fotosintesis es el proceso por el cual las plantas, las algas y algunas "
    "bacterias convierten la luz solar, el agua y el dioxido de carbono en glucosa "
    "y oxigeno. Ocurre principalmente en los cloroplastos, gracias a un pigmento "
    "llamado clorofila que captura la energia luminosa."
)
PROMPTS = {
    # codigo: estructura repetitiva, juega a favor del Coder + ngram
    "code": "Escribe una funcion en Python llamada quicksort que ordene una lista de "
            "enteros, con comentarios que expliquen cada paso y un ejemplo de uso.",
    # habla natural: el caso OBJETIVO ('hablar palabras a velocidad alta')
    "speech": "Explica en un parrafo, como si lo dijeras en voz alta a un nino, que es "
              "la fotosintesis y por que es importante para la vida en la Tierra.",
    # eco/reescritura: el modelo repite mucho el input -> ngram deberia brillar
    "echo": "Reescribe el siguiente texto en una lista de vinetas, conservando las "
            "mismas palabras tanto como sea posible:\n\n" + ECHO_TEXT,
}


def chatml(user: str) -> str:
    return (f"<|im_start|>system\n{SYS}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n")


# ── configuraciones a comparar ─────────────────────────────────────────────
CONFIGS = [
    {"name": "baseline", "spec": None, "extra": []},
    {"name": "ngram-simple",
     "spec": "ngram-simple",
     "extra": ["--spec-ngram-simple-size-n", "2",
               "--spec-ngram-simple-size-m", "8",
               "--spec-ngram-simple-min-hits", "1",
               "--spec-draft-n-max", "8"]},
    {"name": "ngram-map-k",
     "spec": "ngram-map-k",
     "extra": ["--spec-ngram-map-k-size-n", "2",
               "--spec-ngram-map-k-size-m", "8",
               "--spec-ngram-map-k-min-hits", "1",
               "--spec-draft-n-max", "8"]},
    {"name": "ngram-mod",
     "spec": "ngram-mod",
     "extra": ["--spec-ngram-mod-n-min", "1",
               "--spec-ngram-mod-n-max", "8",
               "--spec-ngram-mod-n-match", "24"]},
]


def _port_free() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
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


def launch(cfg: dict) -> tuple[subprocess.Popen | None, Path]:
    log = OUT / f"server_{cfg['name']}.log"
    cmd = [str(BINARY), "--model", str(GGUF), "--port", str(PORT),
           "--ctx-size", str(CTX), "--n-gpu-layers", "0",
           "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
           "--flash-attn", "on", "--log-disable"]
    if cfg["spec"]:
        cmd += ["--spec-type", cfg["spec"]] + cfg["extra"]
    fh = open(log, "w", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    deadline = time.time() + SERVER_BOOT_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            fh.flush()
            return None, log                  # murio al arrancar (flag mala, etc.)
        if _health():
            return proc, log
        time.sleep(0.5)
    proc.kill()
    return None, log


def gen(user: str) -> dict:
    payload = json.dumps({
        "prompt": chatml(user),
        "n_predict": N_PREDICT,
        "temperature": 0.0,            # greedy -> determinista + speculative lossless
        "seed": 0,
        "cache_prompt": False,         # prefill limpio (logits reproducibles)
        "ignore_eos": True,            # decodifica EXACTO N_PREDICT tokens
        "stop": [],
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion", data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
    wall = time.time() - t0
    tim = data.get("timings", {}) or {}
    content = data.get("content", "")
    return {
        "decode_tps": tim.get("predicted_per_second"),
        "predicted_n": tim.get("predicted_n") or data.get("tokens_predicted"),
        "prompt_n": tim.get("prompt_n"),
        "prefill_tps": tim.get("prompt_per_second"),
        "wall_s": round(wall, 2),
        "content_sha": hashlib.sha1(content.encode("utf-8", "ignore")).hexdigest()[:12],
        "content_head": content[:80].replace("\n", " "),
    }


def main() -> None:
    assert BINARY.is_file(), f"falta binario: {BINARY}"
    assert GGUF.is_file(), f"falta GGUF: {GGUF}"
    results = {
        "experiment": "exp021_speculative_decode/bench_real",
        "config": {"model": GGUF.name, "threads": N_THREADS, "ctx": CTX,
                   "n_predict": N_PREDICT, "temperature": 0.0, "cpu_count": os.cpu_count(),
                   "binary": BINARY.name},
        "hypothesis": "H-SPEC-1: en el sistema actual (i3 bandwidth-bound), "
                      "speculative decoding con drafter ngram (0 modelo extra, 0 "
                      "entrenamiento) sube tok/s de decode sin cambiar la salida "
                      "(temp=0 lossless). El payoff depende del tipo de prompt.",
        "runs": [],
        "errors": [],
    }
    for cfg in CONFIGS:
        if not _port_free():
            print(f"[bench] puerto {PORT} ocupado; abortando", flush=True)
            break
        print(f"\n[bench] === {cfg['name']} (spec={cfg['spec']}) ===", flush=True)
        proc, log = launch(cfg)
        if proc is None:
            tail = log.read_text(encoding="utf-8", errors="ignore")[-800:]
            print(f"[bench] {cfg['name']} NO arranco. log tail:\n{tail}", flush=True)
            results["errors"].append({"config": cfg["name"], "log_tail": tail})
            continue
        try:
            for pname, ptext in PROMPTS.items():
                m = gen(ptext)
                row = {"config": cfg["name"], "prompt": pname, **m}
                results["runs"].append(row)
                print(f"[bench] {cfg['name']:>12} | {pname:>6} | "
                      f"decode={m['decode_tps']:.2f} tok/s | n={m['predicted_n']} | "
                      f"sha={m['content_sha']}", flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            time.sleep(1.0)

    # ── analisis: speedup vs baseline + chequeo lossless ───────────────────
    base = {r["prompt"]: r for r in results["runs"] if r["config"] == "baseline"}
    summary = []
    for r in results["runs"]:
        if r["config"] == "baseline":
            continue
        b = base.get(r["prompt"])
        if not b or not b["decode_tps"] or not r["decode_tps"]:
            continue
        summary.append({
            "config": r["config"], "prompt": r["prompt"],
            "baseline_tps": round(b["decode_tps"], 2),
            "spec_tps": round(r["decode_tps"], 2),
            "speedup": round(r["decode_tps"] / b["decode_tps"], 3),
            "lossless": (r["content_sha"] == b["content_sha"]),
        })
    results["summary"] = summary

    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                      encoding="utf-8")

    # results.md
    lines = ["# exp021 — speculative decoding REAL en llama-server (i3, Qwen3B Q4_K_M)\n",
             f"- modelo: {GGUF.name} | threads={N_THREADS} | ctx={CTX} | "
             f"n_predict={N_PREDICT} | temp=0 (greedy)\n",
             "\n| config | prompt | baseline tok/s | spec tok/s | speedup | lossless |",
             "|---|---|---|---|---|---|"]
    for s in summary:
        lines.append(f"| {s['config']} | {s['prompt']} | {s['baseline_tps']} | "
                     f"{s['spec_tps']} | **{s['speedup']}x** | "
                     f"{'OK' if s['lossless'] else 'NO!'} |")
    if results["errors"]:
        lines.append("\n## Errores de arranque")
        for e in results["errors"]:
            lines.append(f"- **{e['config']}**: ver log")
    (OUT / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n[bench] LISTO. results.json + results.md escritos en", OUT, flush=True)
    for s in summary:
        flag = "" if s["lossless"] else "  <-- LOSSLESS ROTO"
        print(f"  {s['config']:>12} | {s['prompt']:>6} | {s['speedup']}x{flag}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
