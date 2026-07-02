r"""
Orquestador del XOLMO baseline en Kaggle (T4, INTERNET ON: baja OLMo-1B-hf + wikitext de HF).

Mismo patrón que run_kaggle_xspeed.py (PYTHONUTF8 obligatorio: el CLI lee code_file en cp1252).

Uso:
  venv312\Scripts\python.exe cognia_x/construccion/run_kaggle_xolmo.py --push-only
  venv312\Scripts\python.exe cognia_x/construccion/run_kaggle_xolmo.py --download-only
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_FILE = HERE / "xolmo_kernel.py"
OUT_DIR = HERE / "results_xolmo"
SLUG = "cognia-xolmo-base"


def kaggle(*args, check=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit("FALTA ~/.kaggle/kaggle.json")
    return json.loads(cred.read_text())["username"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()
    user = get_username()
    ref = f"{user}/{SLUG}"
    if args.download_only:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        kaggle("kernels", "output", ref, "-p", str(OUT_DIR))
        res = OUT_DIR / "xolmo_results.json"
        if res.exists():
            print(res.read_text(encoding="utf-8"))
        else:
            print("[kaggle] sin xolmo_results.json — mirar el log")
        return
    staging = HERE / "_xolmo_staging"
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
    print(f"status:   python -m kaggle kernels status {ref}")


if __name__ == "__main__":
    main()
