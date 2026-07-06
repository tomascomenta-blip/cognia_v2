"""
Runner local del experimento E0 (perfil QLoRA 3B en T4) — COGNIA 3B.

Pushea e0_perfil_kernel.py como kernel GPU de Kaggle montando el dataset
privado existente (cognia-dataset) + el modelo base Qwen2.5-Coder-3B-Instruct,
y opcionalmente pollea y descarga e0_results.json.

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_e0 --push-only
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_e0          # push + poll + download
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT_DIR = HERE / "results_e0"
KERNEL_SLUG = "cognia-e0-perfil"


def kaggle(*args, check=True) -> subprocess.CompletedProcess:
    # PYTHONUTF8: el CLI lee code_file con cp1252 en Windows y revienta con
    # UTF-8 (leccion run_kaggle_xspeed.py). El kernel es ASCII, pero igual.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    return subprocess.run(cmd, check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit("FALTA ~/.kaggle/kaggle.json")
    return json.loads(cred.read_text())["username"]


def push_kernel(user: str) -> str:
    ref = f"{user}/{KERNEL_SLUG}"
    staging = HERE / "_e0_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "e0_perfil_kernel.py", staging / "e0_perfil_kernel.py")
    meta = {
        "id": ref, "title": KERNEL_SLUG,
        "code_file": "e0_perfil_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        # el backend nuevo IGNORA enable_gpu; sin machine_shape corre en CPU
        # (fix 331db7c)
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"{user}/cognia-dataset"],
        "kernel_sources": [], "competition_sources": [],
        "model_sources": [
            "qwen-lm/qwen2.5-coder/transformers/3b-instruct/1",
        ],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (T4)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip())
    return ref


def wait_kernel(ref: str, poll_s: int = 90, max_h: float = 3.0) -> str:
    t0 = time.time()
    while time.time() - t0 < max_h * 3600:
        r = kaggle("kernels", "status", ref, check=False)
        line = (r.stdout + r.stderr).strip()
        print(f"[kaggle] {time.strftime('%H:%M:%S')} {line}", flush=True)
        low = line.lower()
        if "complete" in low:
            return "complete"
        if "error" in low or "cancel" in low:
            return "error"
        time.sleep(poll_s)
    return "timeout"


def download(ref: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kaggle("kernels", "output", ref, "-p", str(OUT_DIR))
    res = OUT_DIR / "e0_results.json"
    if res.exists():
        data = json.loads(res.read_text(encoding="utf-8"))
        print("\n=== E0 RESULTADOS ===")
        print("env:", json.dumps(data.get("env", {})))
        print("peso_base_gb:", data.get("peso_base_gb"))
        for c in data.get("configs", []):
            nombre = c.get("nombre", c.get("grupo_r", "?"))
            if "error" in c:
                print(f"  {nombre}: ERROR {c['error'][:120]}")
            else:
                print(f"  {nombre}: {c['tok_s_seq']} tok/s seq | "
                      f"{c['tok_s_util']} tok/s util | {c['vram_alloc_gb']} GB")
        print("unsloth:", json.dumps(data.get("unsloth") or {})[:400])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true")
    args = ap.parse_args()
    user = get_username()
    ref = push_kernel(user)
    if args.push_only:
        print(f"\nstatus:   .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
        print(f"download: .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {OUT_DIR}")
        return
    status = wait_kernel(ref)
    print(f"[kaggle] estado final: {status}")
    download(ref)


if __name__ == "__main__":
    main()
