"""
Orquestador local del entrenamiento QLoRA en Kaggle (GPU gratis, todo por CLI).

Flujo completo:
  1. Verifica credenciales (~/.kaggle/kaggle.json) y verificación de teléfono.
  2. Sube el JSONL elegido (--dataset-file) como dataset PRIVADO (cognia-dataset).
  3. Pushea el kernel train_qlora_kaggle.py con GPU.
  4. Pollea el estado hasta complete/error (o sale antes con --push-only).
  5. Descarga final_adapter/ + eval_compare.json a checkpoints/qlora_<dataset>/.

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.training.kaggle.run_kaggle_training
  ... --dataset-file cognia_v3/training/synthetic/synthetic_code_dataset.jsonl
                    sube ESE archivo como nueva version del dataset
  ... --push-only   pushea dataset+kernel, imprime slug y comandos de
                    status/descarga, y sale (sin poll de 5h; el monitoreo
                    lo hace el manager aparte)
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
DATASET_JSONL = REPO / "cognia_v3" / "training" / "cognia_dataset.jsonl"

KAGGLE_USER = None  # se lee de kaggle.json


def out_dir_for(dataset_file: Path) -> Path:
    """Dir de descarga derivado del dataset entrenado.

    El viejo checkpoints/cognia_v1 era un nombre fijo que no existe en el repo;
    derivarlo del stem separa cada run: cognia_dataset.jsonl ->
    checkpoints/qlora_cognia_dataset/, synthetic_code_dataset.jsonl ->
    checkpoints/qlora_synthetic_code_dataset/.
    """
    return REPO / "checkpoints" / f"qlora_{dataset_file.stem}"


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


def ensure_dataset(user: str, dataset_file: Path) -> str:
    """Crea o versiona el dataset privado con el JSONL elegido. Devuelve la ref."""
    ref = f"{user}/cognia-dataset"
    staging = HERE / "_dataset_staging"
    staging.mkdir(exist_ok=True)
    # staging persiste entre runs: limpiar JSONLs viejos para que la nueva
    # version contenga SOLO el archivo elegido (el kernel toma el primer
    # *.jsonl que encuentra bajo /kaggle/input, ver _find_dataset).
    for old in staging.glob("*.jsonl"):
        old.unlink()
    shutil.copy(dataset_file, staging / dataset_file.name)
    meta = {"title": "cognia-dataset", "id": ref,
            "licenses": [{"name": "unknown"}]}
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
    ref = f"{user}/cognia-qlora-train"
    staging = HERE / "_kernel_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(HERE / "train_qlora_kaggle.py", staging / "train_qlora_kaggle.py")
    meta = {
        "id": ref, "title": "cognia-qlora-train",
        "code_file": "train_qlora_kaggle.py", "language": "python",
        "kernel_type": "script", "is_private": "true",
        # GPU requiere verificación de teléfono; el kernel detecta CPU y cae al
        # 0.5B. enable_internet=true: el image de Kaggle NO trae
        # bitsandbytes>=0.46.1 (run 1 del datagen murio en el load 4-bit, fix
        # 8b67ac3) y el kernel hace pip install -U bitsandbytes guardado.
        "enable_gpu": "true", "enable_internet": "true",
        # machine_shape: el backend nuevo de Kaggle IGNORA enable_gpu; sin este
        # campo el kernel corre en CPU (causa raiz de v1/v2 lentos:
        # gpu_quota.time_used=0 tras 2 runs de 4h).
        "machine_shape": "NvidiaTeslaT4",
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


def download_output(ref: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[kaggle] descargando output a {out_dir} ...")
    kaggle("kernels", "output", ref, "-p", str(out_dir))
    compare = out_dir / "eval_compare.json"
    if compare.exists():
        data = json.loads(compare.read_text(encoding="utf-8"))
        print(f"\n=== RESULTADO ===")
        print(f"base:    {data['base']['avg_score']:.1%}")
        print(f"adapter: {data['adapter']['avg_score']:.1%}")
        print(f"delta:   {data['delta']:+.1%}")


def main():
    ap = argparse.ArgumentParser(
        description="Orquestador local del entrenamiento QLoRA en Kaggle")
    ap.add_argument("--dataset-file", type=Path, default=DATASET_JSONL,
                    help="JSONL {prompt, completion} a subir como nueva "
                         "version del dataset (default: cognia_dataset.jsonl)")
    ap.add_argument("--push-only", action="store_true",
                    help="pushea dataset+kernel, imprime slug y comandos, y "
                         "sale sin pollear")
    args = ap.parse_args()

    dataset_file = args.dataset_file.resolve()
    if not dataset_file.is_file():
        raise SystemExit(f"No existe el dataset: {dataset_file}")
    out_dir = out_dir_for(dataset_file)

    user = get_username()
    print(f"[kaggle] usuario: {user}")
    print(f"[kaggle] dataset file: {dataset_file}")
    ds = ensure_dataset(user, dataset_file)
    ref = push_kernel(user, ds)
    if args.push_only:
        print(f"\n[kaggle] kernel pusheado: {ref}")
        print("[kaggle] status manual:")
        print(f"  .\\venv312\\Scripts\\python.exe -m kaggle kernels status {ref}")
        print("[kaggle] descarga manual al terminar:")
        print(f"  .\\venv312\\Scripts\\python.exe -m kaggle kernels output {ref} -p {out_dir}")
        return
    status = wait_kernel(ref)
    print(f"[kaggle] estado final: {status}")
    if status == "complete":
        download_output(ref, out_dir)
    else:
        log = kaggle("kernels", "output", ref, "-p", str(out_dir), check=False)
        print("Revisar log del kernel:", log.stdout[-2000:] if log.stdout else log.stderr[-2000:])


if __name__ == "__main__":
    main()
