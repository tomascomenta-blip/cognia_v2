"""
Runner de E-ID4B (adapter identidad Qwen3-4B, FLEET-30 #20) — ver PREREG_ID4B.md.

Reusa el dataset `cognia3b-emix` YA versionado en Kaggle (e1_train + suites
congeladas; lo subio run_eport). Solo pushea el kernel (T4, internet ON para
bajar la base 4B de HF).

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_eid4b
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results_eid4b"
KERNEL_SLUG = "cognia-eid4b"
DATASET_SLUG = "cognia3b-emix"


def kaggle(*args, check=True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "kaggle"] + list(args),
                          check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username():
    return json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]


def push_kernel(user: str) -> str:
    ref = f"{user}/{KERNEL_SLUG}"
    staging = HERE / "_eid4b_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "eid4b_kernel.py", staging / "eid4b_kernel.py")
    meta = {
        "id": ref, "title": KERNEL_SLUG,
        "code_file": "eid4b_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"{user}/{DATASET_SLUG}"],
        "kernel_sources": [], "competition_sources": [], "model_sources": [],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (T4, ~1-2 GPU-h)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip() or r.stderr.strip())
    return ref


def main():
    user = get_username()
    ref = push_kernel(user)
    print(f"\nstatus:   .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
    print(f"download: .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {OUT_DIR}")


if __name__ == "__main__":
    main()
