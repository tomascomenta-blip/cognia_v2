"""
Runner de E-MIX (árbitro de topología DC-4) — COGNIA 3B.

Pasos:
  1. dataset: crea/versiona el dataset privado cognia3b-emix con los corpora
     (e1_train + d5_espanol + tooluse_train_v3) + las 5 suites congeladas +
     SUITES_FROZEN.json.
  2. kernel: pushea emix_kernel.py (T4, internet ON, ~6 GPU-h).

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_emix
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = HERE / "data"
SUITES = REPO / "cognia_v3" / "eval" / "suites"
TOOLUSE = REPO / "cognia_v3" / "training" / "tooluse" / "data"
OUT_DIR = HERE / "results_emix"
KERNEL_SLUG = "cognia-emix-topologia"
DATASET_SLUG = "cognia3b-emix"


def kaggle(*args, check=True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "kaggle"] + list(args),
                          check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username():
    return json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]


def ensure_dataset(user: str) -> str:
    ref = f"{user}/{DATASET_SLUG}"
    staging = HERE / "_emix_dataset_staging"
    staging.mkdir(exist_ok=True)
    for old in staging.glob("*"):
        old.unlink()
    shutil.copy(DATA / "e1_train.jsonl", staging / "e1_train.jsonl")
    shutil.copy(DATA / "d5_espanol.jsonl", staging / "d5_espanol.jsonl")
    shutil.copy(TOOLUSE / "tooluse_train_v3.jsonl", staging / "tooluse_train_v3.jsonl")
    for s in ("g1_general.jsonl", "g3_identidad.jsonl", "g5_espanol.jsonl",
              "g2_accion.jsonl", "SUITES_FROZEN.json"):
        shutil.copy(SUITES / s, staging / s)
    meta = {"title": DATASET_SLUG, "id": ref, "licenses": [{"name": "unknown"}]}
    (staging / "dataset-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    r = kaggle("datasets", "status", ref, check=False)
    if r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower():
        print(f"[kaggle] dataset existente -> nueva versión: {ref}")
        kaggle("datasets", "version", "-p", str(staging), "-m", "emix corpora")
    else:
        print(f"[kaggle] creando dataset PRIVADO: {ref}")
        kaggle("datasets", "create", "-p", str(staging))
    return ref


def push_kernel(user: str, dataset_ref: str) -> str:
    ref = f"{user}/{KERNEL_SLUG}"
    staging = HERE / "_emix_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "emix_kernel.py", staging / "emix_kernel.py")
    meta = {
        "id": ref, "title": KERNEL_SLUG,
        "code_file": "emix_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [dataset_ref],
        "kernel_sources": [], "competition_sources": [],
        "model_sources": ["qwen-lm/qwen2.5-coder/transformers/3b-instruct/1"],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (T4, ~6 GPU-h)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip() or r.stderr.strip())
    return ref


def main():
    user = get_username()
    ds = ensure_dataset(user)
    ref = push_kernel(user, ds)
    print(f"\nstatus:   .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
    print(f"download: .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {OUT_DIR}")


if __name__ == "__main__":
    main()
