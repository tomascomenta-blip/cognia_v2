r"""Orquestador de la familia XHUNDRED en Kaggle. Patrón de run_kaggle_xfinal.py, generalizado.
Uso: venv312\Scripts\python.exe cognia_x/construccion/xhundred/run_kaggle_xh.py <accion> <kernel>
  accion: push | status | download
  kernel: data | bench | ablate | final
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

KERNELS = {
    "data":   {"file": "xh_data_kernel.py",   "slug": "cognia-xh-data",   "gpu": False, "sources": []},
    "bench":  {"file": "xh_bench_kernel.py",  "slug": "cognia-xh-bench",  "gpu": True,  "sources": ["cognia-xh-data"]},
    "ablate": {"file": "xh_ablate_kernel.py", "slug": "cognia-xh-ablate", "gpu": True,  "sources": ["cognia-xh-data"]},
    "final":  {"file": "xh_final_kernel.py",  "slug": "cognia-xh-final",  "gpu": True,  "sources": ["cognia-xh-data"]},
}


def kaggle(*args, check=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("push", "status", "download") or sys.argv[2] not in KERNELS:
        print(__doc__)
        sys.exit(2)
    action, name = sys.argv[1], sys.argv[2]
    spec = KERNELS[name]
    user = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]
    ref = f"{user}/{spec['slug']}"

    if action == "status":
        r = kaggle("kernels", "status", ref, check=False)
        print(r.stdout.strip() or r.stderr.strip())
        return
    if action == "download":
        out_dir = HERE / f"results_{name}"
        out_dir.mkdir(parents=True, exist_ok=True)
        r = kaggle("kernels", "output", ref, "-p", str(out_dir), check=False)
        print(r.stdout.strip() or r.stderr.strip())
        for p in sorted(out_dir.glob("*.json")):
            print(f"--- {p.name} ---")
            print(p.read_text(encoding="utf-8")[:4000])
        return

    kernel_file = HERE / spec["file"]
    staging = HERE / f"_staging_{name}"
    staging.mkdir(exist_ok=True)
    shutil.copy(kernel_file, staging / kernel_file.name)
    meta = {
        "id": ref, "title": spec["slug"],
        "code_file": kernel_file.name, "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true" if spec["gpu"] else "false",
        "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [], "model_sources": [],
        "kernel_sources": [f"{user}/{s}" for s in spec["sources"]],
    }
    if spec["gpu"]:
        meta["machine_shape"] = "NvidiaTeslaT4"
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main()
