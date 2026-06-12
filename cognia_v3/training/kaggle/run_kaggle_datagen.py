"""
Orquestador local del datagen sintetico de codigo en Kaggle (GPU gratis, por CLI).

Calcado del patron de run_kaggle_training.py, con dos diferencias:
  - NO sube dataset: el kernel genera desde plantillas, no necesita input propio.
  - Monta los modelos 7B y 14B instruct (el kernel elige por VRAM en runtime).

Flujo completo:
  1. Verifica credenciales (~/.kaggle/kaggle.json).
  2. Pushea el kernel datagen_kernel.py con GPU (enable_internet=false).
  3. Pollea el estado cada 120s hasta complete/error (max 5h).
  4. Descarga synthetic_code_dataset.jsonl + datagen_report.json a
     cognia_v3/training/synthetic/.

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.kaggle.run_kaggle_datagen
  ... --push-only   pushea, imprime el slug y los comandos de status/output, y sale
                    (el monitoreo lo hace el manager aparte).
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT_DIR = REPO / "cognia_v3" / "training" / "synthetic"

# Instancias oficiales verificadas con la API (2026-06-11): ambas version 1.
# El kernel usa el 7B salvo que un device tenga >= 20 GB de VRAM (ver
# datagen_kernel._pick_model_dir).
MODEL_SOURCES = [
    "qwen-lm/qwen2.5-coder/transformers/7b-instruct/1",
    "qwen-lm/qwen2.5-coder/transformers/14b-instruct/1",
]


def kaggle(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    return subprocess.run(cmd, check=check, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace")


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit(
            "FALTA ~/.kaggle/kaggle.json — generarlo en kaggle.com/settings "
            "('Create New Token').")
    return json.loads(cred.read_text())["username"]


def push_kernel(user: str) -> str:
    ref = f"{user}/cognia-code-datagen"
    staging = HERE / "_datagen_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "datagen_kernel.py", staging / "datagen_kernel.py")
    meta = {
        "id": ref, "title": "cognia-code-datagen",
        "code_file": "datagen_kernel.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "false",
        "dataset_sources": [], "kernel_sources": [], "competition_sources": [],
        "model_sources": MODEL_SOURCES,
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (GPU)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip())
    return ref


def wait_kernel(ref: str, poll_s: int = 120, max_h: float = 5.0) -> str:
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
    report = OUT_DIR / "datagen_report.json"
    if report.exists():
        data = json.loads(report.read_text(encoding="utf-8"))
        print("\n=== DATAGEN ===")
        print(f"modelo:      {data.get('model_dir', '?')}")
        print(f"generados:   {data.get('generated', 0)}")
        print(f"verificados: {data.get('accepted', 0)}")
        print(f"aceptacion:  {data.get('acceptance_rate', 0):.1%}")
        print(f"por banda:   {data.get('by_band', {})}")


def main():
    push_only = "--push-only" in sys.argv
    user = get_username()
    print(f"[kaggle] usuario: {user}")
    ref = push_kernel(user)
    if push_only:
        print(f"\n[kaggle] kernel pusheado: {ref}")
        print("[kaggle] status manual:")
        print(f"  .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
        print("[kaggle] descarga manual al terminar:")
        print(f"  .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {OUT_DIR}")
        return
    status = wait_kernel(ref)
    print(f"[kaggle] estado final: {status}")
    if status == "complete":
        download_output(ref)
    else:
        log = kaggle("kernels", "output", ref, "-p", str(OUT_DIR), check=False)
        print("Revisar log del kernel:", log.stdout[-2000:] if log.stdout else log.stderr[-2000:])


if __name__ == "__main__":
    main()
