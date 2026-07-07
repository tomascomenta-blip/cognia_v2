"""Runner de E2A (A/B runtime steps igualados): monta el OUTPUT del kernel E1
(adapter t_r16_all ya entrenado) via kernel_sources + el dataset cognia3b-e1
(suites + e1_train.jsonl) y entrena u_r16_all_mb4 fresco.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.run_e2a
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_SLUG = "cognia-e2a-runtime"


def kaggle(*args, check=True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "kaggle"] + list(args),
                          check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main():
    user = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]
    ref = f"{user}/{KERNEL_SLUG}"
    staging = HERE / "_e2a_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "e2a_runtime_kernel.py", staging / "e2a_runtime_kernel.py")
    meta = {
        "id": ref, "title": KERNEL_SLUG,
        "code_file": "e2a_runtime_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"{user}/cognia3b-e1"],
        "kernel_sources": [f"{user}/cognia-e1-metodos"],
        "competition_sources": [],
        "model_sources": ["qwen-lm/qwen2.5-coder/transformers/3b-instruct/1"],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip() or r.stderr.strip())
    print(f"status:   .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
    print(f"download: .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} "
          f"-p {HERE / 'results_e2a'}")


if __name__ == "__main__":
    main()
