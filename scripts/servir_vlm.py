"""
servir_vlm.py — Levanta el llama-server MULTIMODAL que el arbitro visual espera.

POR QUE EXISTE: arbitro_visual.py necesita un VLM (imagen+texto -> texto) para
MIRAR el screenshot de la pagina y compararlo con el mockup. En esta maquina el
backend real es llama-server (~/.cognia/llama/llama-server.exe), que soporta
vision con --mmproj (mtmd). No habia comando que lo sirviera con el proyector
multimodal ni en un puerto aparte del cerebro (8080).

    python scripts/servir_vlm.py                 # el VLM por defecto (Qwen2.5-VL)
    python scripts/servir_vlm.py --listar        # que VLM+mmproj hay instalado

Sirve en el puerto 8081 (COGNIA_VLM_URL apunta ahi por defecto), separado del
cerebro en 8080: asi conviven el coder-14b (genera/repara) y el VLM (arbitra).
Si ya hay algo respondiendo en 8081, no arranca otro.

Solo stdlib.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DIR_MODELOS = Path.home() / ".cognia" / "models"
DIR_LLAMA   = Path.home() / ".cognia" / "llama"
PUERTO      = 8081          # el que sondea arbitro_visual (COGNIA_VLM_URL)
CTX         = 8192
ESPERA_SEG  = 240

# Preferencia por defecto: el VLM que baja goal-assets (Qwen2.5-VL). Se casa el
# GGUF del modelo con su mmproj por el sufijo del nombre.
PREFERIDOS = ("qwen2.5-vl", "qwen2-vl", "minicpm-v", "llava")


def binario() -> Path | None:
    for nombre in ("llama-server.exe", "llama-server"):
        ruta = DIR_LLAMA / nombre
        if ruta.exists():
            return ruta
    return None


def _es_mmproj(nombre: str) -> bool:
    return "mmproj" in nombre.lower()


def modelos_vlm() -> list[Path]:
    """GGUF de VLM (no-mmproj) que tengan un mmproj hermano en el mismo dir."""
    if not DIR_MODELOS.is_dir():
        return []
    todos = list(DIR_MODELOS.glob("*.gguf"))
    mmprojs = [m for m in todos if _es_mmproj(m.name)]
    out = []
    for m in todos:
        if _es_mmproj(m.name):
            continue
        if "-of-" in m.name and "00001-of-" not in m.name:
            continue
        if _mmproj_de(m, mmprojs) is not None:
            out.append(m)
    return sorted(out)


def _mmproj_de(modelo: Path, mmprojs: list[Path]) -> Path | None:
    """Empareja un modelo con su mmproj por la parte comun del nombre.
    Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf  <->  mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf
    """
    base = modelo.name.lower()
    # Quita cuantizacion y extension para quedarnos con la familia.
    for corte in ("-q4", "-q5", "-q6", "-q8", "-f16", "-fp16", ".gguf"):
        i = base.find(corte)
        if i != -1:
            base = base[:i]
            break
    for mp in mmprojs:
        if base and base in mp.name.lower():
            return mp
    return None


def elegir(patron: str | None) -> tuple[Path, Path] | None:
    disponibles = modelos_vlm()
    if not disponibles:
        return None
    mmprojs = [m for m in DIR_MODELOS.glob("*.gguf") if _es_mmproj(m.name)]

    def con_mmproj(m: Path):
        mp = _mmproj_de(m, mmprojs)
        return (m, mp) if mp else None

    if patron:
        p = patron.lower()
        for m in disponibles:
            if p in m.name.lower():
                return con_mmproj(m)
        return None
    for pref in PREFERIDOS:
        for m in disponibles:
            if pref in m.name.lower():
                return con_mmproj(m)
    return con_mmproj(disponibles[0])


def responde(puerto: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", help="trozo del nombre del VLM a servir")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--ctx", type=int, default=CTX)
    ap.add_argument("--listar", action="store_true", help="ver VLMs y salir")
    args = ap.parse_args()

    if args.listar:
        disponibles = modelos_vlm()
        if not disponibles:
            print(f"No hay VLM (GGUF + mmproj hermano) en {DIR_MODELOS}")
            return 1
        mmprojs = [m for m in DIR_MODELOS.glob("*.gguf") if _es_mmproj(m.name)]
        print(f"VLMs en {DIR_MODELOS}:")
        for m in disponibles:
            mp = _mmproj_de(m, mmprojs)
            print(f"  {m.stat().st_size / 1e9:6.1f} GB  {m.name}")
            print(f"          + mmproj: {mp.name if mp else '??'}")
        return 0

    if responde(args.puerto):
        print(f"Ya hay un VLM respondiendo en :{args.puerto}. No arranco otro.")
        return 0

    exe = binario()
    if exe is None:
        print(f"No encuentro llama-server en {DIR_LLAMA}", file=sys.stderr)
        return 1

    elegido = elegir(args.modelo)
    if elegido is None:
        print(f"No encuentro un VLM con su mmproj en {DIR_MODELOS}. "
              f"Usa --listar para ver que hay.", file=sys.stderr)
        return 1
    modelo, mmproj = elegido

    orden = [str(exe), "--model", str(modelo), "--mmproj", str(mmproj),
             "--port", str(args.puerto), "--ctx-size", str(args.ctx),
             "--n-gpu-layers", "99", "--flash-attn", "on", "--jinja"]

    print(f"Sirviendo VLM {modelo.name}")
    print(f"  + mmproj: {mmproj.name}")
    print(f"  en :{args.puerto} (ctx {args.ctx})...")
    proceso = subprocess.Popen(
        orden, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    inicio = time.time()
    while time.time() - inicio < ESPERA_SEG:
        if responde(args.puerto):
            print(f"Listo en {time.time() - inicio:.0f}s. "
                  f"El arbitro visual ya lo detecta (COGNIA_VLM_URL=:{args.puerto}).")
            print(f"Para pararlo: taskkill /IM {exe.name} /F")
            return 0
        if proceso.poll() is not None:
            print(f"El VLM murio al arrancar (codigo {proceso.returncode}). "
                  f"¿Cabe el modelo + mmproj en la GPU?", file=sys.stderr)
            return 1
        time.sleep(2)

    print(f"No respondio en {ESPERA_SEG}s.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
