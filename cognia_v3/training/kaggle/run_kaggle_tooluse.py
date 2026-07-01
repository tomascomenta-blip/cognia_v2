"""
Orquestador local del fine-tune de TOOL-USE en Kaggle (GPU T4 gratis, por CLI).

Pipeline paralelo al de destilacion (run_kaggle_training.py) con slugs propios,
para no pisar el dataset/kernel de conocimiento:
  dataset: {user}/cognia-tooluse-data   (sube train + eval jsonl)
  kernel:  {user}/cognia-tooluse-train  (corre train_tooluse_kaggle.py)

Flujo: credenciales -> sube dataset (train+eval) -> pushea kernel GPU -> pollea
-> descarga final_adapter/ + eval_tooluse.json a checkpoints/tooluse/.

Uso:
  venv312\\Scripts\\python.exe -m cognia_v3.training.kaggle.run_kaggle_tooluse
  ... --push-only     pushea y sale (monitoreo aparte)
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TRAIN_JSONL = REPO / "cognia_v3" / "training" / "tooluse" / "data" / "tooluse_train.jsonl"
EVAL_JSONL = REPO / "cognia_v3" / "training" / "tooluse" / "data" / "tooluse_eval.jsonl"
OUT_DIR = REPO / "checkpoints" / "tooluse"


def kaggle(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    return subprocess.run(cmd, check=check, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace")


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit("FALTA ~/.kaggle/kaggle.json — generarlo en kaggle.com/settings.")
    return json.loads(cred.read_text())["username"]


def ensure_dataset(user: str, train_file: Path, eval_file: Path) -> str:
    ref = f"{user}/cognia-tooluse-data"
    staging = HERE / "_tooluse_dataset_staging"
    staging.mkdir(exist_ok=True)
    for old in staging.glob("*.jsonl"):
        old.unlink()
    shutil.copy(train_file, staging / "tooluse_train.jsonl")
    if eval_file.is_file():
        shutil.copy(eval_file, staging / "tooluse_eval.jsonl")
    meta = {"title": "cognia-tooluse-data", "id": ref, "licenses": [{"name": "unknown"}]}
    (staging / "dataset-metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    r = kaggle("datasets", "status", ref, check=False)
    if r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower():
        print(f"[kaggle] dataset existente -> nueva version: {ref}")
        kaggle("datasets", "version", "-p", str(staging), "-m", "tooluse update")
    else:
        print(f"[kaggle] creando dataset PRIVADO: {ref}")
        kaggle("datasets", "create", "-p", str(staging))
    return ref


def push_kernel(user: str, dataset_ref: str) -> str:
    ref = f"{user}/cognia-tooluse-train"
    staging = HERE / "_tooluse_kernel_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "train_tooluse_kaggle.py", staging / "train_tooluse_kaggle.py")
    meta = {
        "id": ref, "title": "cognia-tooluse-train",
        "code_file": "train_tooluse_kaggle.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "true",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [dataset_ref], "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [
            "qwen-lm/qwen2.5-coder/transformers/3b-instruct/1",
            "qwen-lm/qwen2.5-coder/transformers/0.5b-instruct/1",
        ],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (GPU T4)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip())
    return ref


def wait_kernel(ref: str, poll_s: int = 60, max_h: float = 5.0) -> str:
    t0 = time.time()
    while time.time() - t0 < max_h * 3600:
        r = kaggle("kernels", "status", ref, check=False)
        line = (r.stdout + r.stderr).strip()
        print(f"[kaggle] {time.strftime('%H:%M:%S')} {line}")
        low = line.lower()
        if "complete" in low:
            return "complete"
        if "error" in low or "cancel" in low:
            return "error"
        time.sleep(poll_s)
    return "timeout"


def download_output(ref: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[kaggle] descargando output a {out_dir} ...")
    kaggle("kernels", "output", ref, "-p", str(out_dir))
    ev = out_dir / "eval_tooluse.json"
    if ev.exists():
        data = json.loads(ev.read_text(encoding="utf-8"))
        b = (data.get("base") or {}).get("valid_single_accion")
        a = (data.get("adapter") or {}).get("valid_single_accion")
        print("\n=== RESULTADO tool-use ===")
        if b is not None:
            print(f"base:    {b:.1%}")
        if a is not None:
            print(f"adapter: {a:.1%}")
        if "delta_valid_single_accion" in data:
            print(f"delta:   {data['delta_valid_single_accion']:+.1%}")


def main():
    ap = argparse.ArgumentParser(description="Fine-tune de tool-use en Kaggle")
    ap.add_argument("--train-file", type=Path, default=TRAIN_JSONL)
    ap.add_argument("--eval-file", type=Path, default=EVAL_JSONL)
    ap.add_argument("--push-only", action="store_true")
    args = ap.parse_args()

    train_file = args.train_file.resolve()
    if not train_file.is_file():
        raise SystemExit(f"No existe el train set: {train_file}")

    user = get_username()
    print(f"[kaggle] usuario: {user}")
    print(f"[kaggle] train: {train_file}")
    print(f"[kaggle] eval:  {args.eval_file}")
    ds = ensure_dataset(user, train_file, args.eval_file.resolve())
    ref = push_kernel(user, ds)
    if args.push_only:
        print(f"\n[kaggle] kernel pusheado: {ref}")
        print(f"  status:   python -m kaggle kernels status {ref}")
        print(f"  descarga: python -m kaggle kernels output {ref} -p {OUT_DIR}")
        return
    status = wait_kernel(ref)
    print(f"[kaggle] estado final: {status}")
    if status == "complete":
        download_output(ref, OUT_DIR)
    else:
        log = kaggle("kernels", "output", ref, "-p", str(OUT_DIR), check=False)
        print("Log:", (log.stdout or log.stderr or "")[-2000:])


if __name__ == "__main__":
    main()
