"""
Runner del experimento E1 (ablación de métodos) — COGNIA 3B.

Pasos:
  1. build: arma e1_train.jsonl = D1 (3 archivos validados) + tooluse_train_v2.
  2. dataset: crea/versiona el dataset privado cognia3b-e1 con e1_train +
     suites congeladas + SUITES_FROZEN.json + tooluse_eval.jsonl.
  3. kernel: pushea e1_metodos_kernel.py (T4, internet ON).

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_e1 --push-only
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = HERE / "data"
SUITES = REPO / "cognia_v3" / "eval" / "suites"
TOOLUSE = REPO / "cognia_v3" / "training" / "tooluse" / "data"
OUT_DIR = HERE / "results_e1"
KERNEL_SLUG = "cognia-e1-metodos"
DATASET_SLUG = "cognia3b-e1"
SEED = 20260707

D1_FILES = ["d1_ab_identidad.jsonl", "d1_cd_capacidades.jsonl", "d1_e_estilo.jsonl"]


def kaggle(*args, check=True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "kaggle"] + list(args),
                          check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username():
    cred = Path.home() / ".kaggle" / "kaggle.json"
    return json.loads(cred.read_text())["username"]


def build_e1_train() -> Path:
    pares = []
    for nombre in D1_FILES:
        with open(DATA / nombre, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    pares.append({"prompt": r["prompt"], "completion": r["completion"]})
    n_d1 = len(pares)
    with open(TOOLUSE / "tooluse_train_v2.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                pares.append({"prompt": r["prompt"], "completion": r["completion"]})
    random.Random(SEED).shuffle(pares)
    out = DATA / "e1_train.jsonl"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for p in pares:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"e1_train.jsonl: {len(pares)} pares ({n_d1} D1 + {len(pares)-n_d1} tooluse)")
    return out


def ensure_dataset(user: str, e1_train: Path) -> str:
    ref = f"{user}/{DATASET_SLUG}"
    staging = HERE / "_e1_dataset_staging"
    staging.mkdir(exist_ok=True)
    for old in staging.glob("*"):
        old.unlink()
    shutil.copy(e1_train, staging / "e1_train.jsonl")
    for s in ("g1_general.jsonl", "g3_identidad.jsonl", "g5_espanol.jsonl",
              "SUITES_FROZEN.json"):
        shutil.copy(SUITES / s, staging / s)
    shutil.copy(TOOLUSE / "tooluse_eval.jsonl", staging / "tooluse_eval.jsonl")
    meta = {"title": DATASET_SLUG, "id": ref, "licenses": [{"name": "unknown"}]}
    (staging / "dataset-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    r = kaggle("datasets", "status", ref, check=False)
    if r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower():
        print(f"[kaggle] dataset existente -> nueva versión: {ref}")
        kaggle("datasets", "version", "-p", str(staging), "-m", "update")
    else:
        print(f"[kaggle] creando dataset PRIVADO: {ref}")
        kaggle("datasets", "create", "-p", str(staging))
    return ref


def push_kernel(user: str, dataset_ref: str) -> str:
    ref = f"{user}/{KERNEL_SLUG}"
    staging = HERE / "_e1_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "e1_metodos_kernel.py", staging / "e1_metodos_kernel.py")
    meta = {
        "id": ref, "title": KERNEL_SLUG,
        "code_file": "e1_metodos_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [dataset_ref],
        "kernel_sources": [], "competition_sources": [],
        "model_sources": ["qwen-lm/qwen2.5-coder/transformers/3b-instruct/1"],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (T4)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip())
    return ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()
    e1_train = build_e1_train()
    if args.build_only:
        return
    user = get_username()
    ds = ensure_dataset(user, e1_train)
    ref = push_kernel(user, ds)
    print(f"\nstatus:   .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
    print(f"download: .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {OUT_DIR}")


if __name__ == "__main__":
    main()
