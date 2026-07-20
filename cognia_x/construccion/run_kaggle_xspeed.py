r"""
Orquestador local del XSPEED BENCH en Kaggle (GPU 2x T4 gratis, por CLI).

Patrón de cognia_v3/training/kaggle/run_kaggle_tooluse.py pero SIN dataset (la tarea de recall es
sintética y se genera en el kernel): staging -> kernel-metadata.json -> push -> poll -> download.
Lección dura del MANAGER_LOG: el backend nuevo IGNORA enable_gpu; el campo efectivo es
machine_shape=NvidiaTeslaT4. Internet OFF (no hace falta pip: torch ya viene en el image).

Uso:
  venv312\Scripts\python.exe cognia_x/construccion/run_kaggle_xspeed.py
  ... --push-only     pushea y sale (monitoreo aparte)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_FILE = HERE / "xspeed_bench_kernel.py"
OUT_DIR = HERE / "results_xspeed"
SLUG = "cognia-xspeed-bench"


def kaggle(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "kaggle"] + list(args)
    # PYTHONUTF8: el CLI lee code_file con la encoding por defecto de Windows (cp1252) y revienta
    # con UTF-8 (visto: "'charmap' codec can't decode byte 0x81"); forzamos UTF-8 en el hijo.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, check=check, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace", env=env)


def get_username() -> str:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        raise SystemExit("FALTA ~/.kaggle/kaggle.json — generarlo en kaggle.com/settings.")
    return json.loads(cred.read_text())["username"]


def push_kernel(user: str) -> str:
    ref = f"{user}/{SLUG}"
    staging = HERE / "_xspeed_staging"
    staging.mkdir(exist_ok=True)
    shutil.copy(KERNEL_FILE, staging / KERNEL_FILE.name)
    meta = {
        "id": ref, "title": SLUG,
        "code_file": KERNEL_FILE.name, "language": "python",
        "kernel_type": "script", "is_private": "true",
        "enable_gpu": "true", "enable_internet": "false",
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [], "kernel_sources": [],
        "competition_sources": [], "model_sources": [],
    }
    (staging / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[kaggle] pusheando kernel {ref} (T4)...")
    r = kaggle("kernels", "push", "-p", str(staging))
    print(r.stdout.strip())
    return ref


def wait_kernel(ref: str, poll_s: int = 60, max_h: float = 2.5) -> str:
    t0 = time.time()
    while time.time() - t0 < max_h * 3600:
        r = kaggle("kernels", "status", ref, check=False)
        line = (r.stdout + r.stderr).strip()
        print(f"[kaggle] {time.strftime('%H:%M:%S')} {line}", flush=True)
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
    res = out_dir / "xspeed_results.json"
    if not res.exists():
        print("[kaggle] SIN xspeed_results.json — revisar el log del kernel")
        return
    data = json.loads(res.read_text(encoding="utf-8"))
    print("\n=== XSPEED — PALANCAS (tok/s) ===")
    base = (data.get("levers") or {}).get("baseline_fp32_b64", {}).get("tok_per_s")
    for name, r in (data.get("levers") or {}).items():
        if "tok_per_s" in r:
            x = f"  x{r['tok_per_s'] / base:.2f}" if base else ""
            print(f"  {name:36} {r['tok_per_s']:>9} tok/s{x}  finite={r.get('loss_finite')}")
        else:
            print(f"  {name:36} {r}")
    if "parity" in data:
        print("\n=== PARIDAD DE LOSS ===")
        for k, v in data["parity"].items():
            print(f"  {k}: {v if not isinstance(v, dict) else {kk: v[kk] for kk in ('final_loss', 'eval_acc') if kk in v}}")
    if "grok_quality" in data:
        print("\n=== GROKKING E2E ===")
        for k, v in data["grok_quality"].items():
            print(f"  {k}: {v}")


def main():
    ap = argparse.ArgumentParser(description="XSPEED bench en Kaggle T4")
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--download-only", action="store_true", help="solo bajar el output existente")
    ap.add_argument("--wait-only", action="store_true", help="poll+download de un kernel ya pusheado")
    args = ap.parse_args()

    user = get_username()
    print(f"[kaggle] usuario: {user}")
    ref = f"{user}/{SLUG}"
    if args.download_only:
        download_output(ref, OUT_DIR)
        return
    if args.wait_only:
        status = wait_kernel(ref)
        print(f"[kaggle] estado final: {status}")
        if status == "complete":
            download_output(ref, OUT_DIR)
        return
    ref = push_kernel(user)
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
