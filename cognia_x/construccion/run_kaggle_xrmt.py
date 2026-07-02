r"""Orquestador del XRMT en Kaggle T4. Patrón de run_kaggle_xarch.py.
Uso: venv312\Scripts\python.exe cognia_x/construccion/run_kaggle_xrmt.py [--push-only|--download-only]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_FILE = HERE / "xrmt_kernel.py"
OUT_DIR = HERE / "results_xrmt"
SLUG = "cognia-xrmt"


def kaggle(*args, check=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()
    user = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]
    ref = f"{user}/{SLUG}"
    if args.download_only:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        kaggle("kernels", "output", ref, "-p", str(OUT_DIR))
        res = OUT_DIR / "xrmt_results.json"
        print(res.read_text(encoding="utf-8") if res.exists() else "[kaggle] sin results — mirar log")
        return
    staging = HERE / "_xrmt_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(KERNEL_FILE, staging / KERNEL_FILE.name)
    meta = {
        "id": ref, "title": SLUG,
        "code_file": KERNEL_FILE.name, "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [], "kernel_sources": [],
        "competition_sources": [], "model_sources": [],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main()
