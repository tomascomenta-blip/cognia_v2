"""
Orquestador local del entrenamiento QLoRA en Kaggle (GPU gratis, todo por CLI).

Flujo completo:
  1. Verifica credenciales (~/.kaggle/kaggle.json) y verificación de teléfono.
  2. Sube cognia_dataset.jsonl como dataset PRIVADO (cognia-dataset).
  3. Pushea el kernel train_qlora_kaggle.py con GPU.
  4. Pollea el estado hasta complete/error.
  5. Descarga final_adapter/ + eval_compare.json a checkpoints/cognia_v1/.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.kaggle.run_kaggle_training
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATASET_JSONL = REPO / "cognia_v3" / "training" / "cognia_dataset.jsonl"
OUT_DIR = REPO / "checkpoints" / "cognia_v1"

KAGGLE_USER = None  # se lee de kaggle.json


def kaggle(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    return subprocess.run(cmd, check=check, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace")


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit(
            "FALTA ~/.kaggle/kaggle.json — generarlo en kaggle.com/settings "
            "('Create New Token') o correr la automatización del browser.")
    return json.loads(cred.read_text())["username"]


def ensure_dataset(user: str) -> str:
    """Crea o versiona el dataset privado con el JSONL. Devuelve la ref."""
    ref = f"{user}/cognia-dataset"
    staging = HERE / "_dataset_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(DATASET_JSONL, staging / "cognia_dataset.jsonl")
    meta = {"title": "cognia-dataset", "id": ref,
            "licenses": [{"name": "unknown"}]}
    (staging / "dataset-metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    r = kaggle("datasets", "status", ref, check=False)
    if r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower():
        print(f"[kaggle] dataset existente -> nueva versión: {ref}")
        kaggle("datasets", "version", "-p", str(staging), "-m", "update", "--dir-mode", "zip")
    else:
        print(f"[kaggle] creando dataset PRIVADO: {ref}")
        kaggle("datasets", "create", "-p", str(staging), "--dir-mode", "zip")
    return ref


def push_kernel(user: str, dataset_ref: str) -> str:
    ref = f"{user}/cognia-qlora-train"
    staging = HERE / "_kernel_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "train_qlora_kaggle.py", staging / "train_qlora_kaggle.py")
    meta = {
        "id": ref, "title": "cognia-qlora-train",
        "code_file": "train_qlora_kaggle.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        # GPU requiere verificación de teléfono; el kernel detecta CPU y cae al
        # 0.5B. Cuando el teléfono esté verificado, poner enable_gpu="true" y
        # corre el 3B en 4-bit sin cambiar código.
        "enable_gpu": "true", "enable_internet": "false",
        "dataset_sources": [dataset_ref], "kernel_sources": [],
        "competition_sources": [],
        # modelos base montados offline. Formato: {owner}/{slug}/{fw}/{inst}/{ver}
        "model_sources": [
            "qwen-lm/qwen2.5-coder/transformers/3b-instruct/1",
            "qwen-lm/qwen2.5-coder/transformers/0.5b-instruct/1",
        ],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (GPU)...")
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


def download_output(ref: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[kaggle] descargando output a {OUT_DIR} ...")
    kaggle("kernels", "output", ref, "-p", str(OUT_DIR))
    compare = OUT_DIR / "eval_compare.json"
    if compare.exists():
        data = json.loads(compare.read_text(encoding="utf-8"))
        print(f"\n=== RESULTADO ===")
        print(f"base:    {data['base']['avg_score']:.1%}")
        print(f"adapter: {data['adapter']['avg_score']:.1%}")
        print(f"delta:   {data['delta']:+.1%}")


def main():
    user = get_username()
    print(f"[kaggle] usuario: {user}")
    ds = ensure_dataset(user)
    ref = push_kernel(user, ds)
    status = wait_kernel(ref)
    print(f"[kaggle] estado final: {status}")
    if status == "complete":
        download_output(ref)
    else:
        log = kaggle("kernels", "output", ref, "-p", str(OUT_DIR), check=False)
        print("Revisar log del kernel:", log.stdout[-2000:] if log.stdout else log.stderr[-2000:])


if __name__ == "__main__":
    main()
