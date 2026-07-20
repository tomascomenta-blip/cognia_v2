"""
servir_modelo.py — Levanta el llama-server que Cognia espera encontrar.

POR QUE EXISTE: sin backend, Cognia degrada a sus fallbacks en silencio — es el
modo de fallo que mas costo cazar la madrugada del 2026-07-20. El doctor y el
bucle del agente ya avisan ("arranca llama-server o configura COGNIA_LLM_URL"),
pero no habia ningun comando que lo hiciera: habia que recordar la ruta del
binario, el modelo y los flags.

    python scripts/servir_modelo.py                 # el modelo por defecto
    python scripts/servir_modelo.py --modelo UIGEN  # por trozo del nombre
    python scripts/servir_modelo.py --listar        # que hay instalado

Sirve en el puerto 8080, que es el que sondea cognia/llm_local.py. Si ya hay
algo respondiendo ahi, no arranca otro: avisa y sale.

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
PUERTO      = 8080          # el que sondea llm_local.py
CTX         = 8192
ESPERA_SEG  = 240

# Preferencia por defecto: el coder de 14B, que es con el que se midio todo.
PREFERIDOS = ("qwen2.5-coder-14b", "qwen2.5-coder", "qwen2.5")


def binario() -> Path | None:
    for nombre in ("llama-server.exe", "llama-server"):
        ruta = DIR_LLAMA / nombre
        if ruta.exists():
            return ruta
    return None


def modelos() -> list[Path]:
    if not DIR_MODELOS.is_dir():
        return []
    # De los ficheros partidos (-00001-of-0000N) solo interesa el primero:
    # llama.cpp carga el resto solo.
    return sorted(m for m in DIR_MODELOS.glob("*.gguf")
                  if "-of-" not in m.name or "00001-of-" in m.name)


def elegir(patron: str | None) -> Path | None:
    disponibles = modelos()
    if not disponibles:
        return None
    if patron:
        p = patron.lower()
        for m in disponibles:
            if p in m.name.lower():
                return m
        return None
    for pref in PREFERIDOS:
        for m in disponibles:
            if pref in m.name.lower():
                return m
    return disponibles[0]


def responde(puerto: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", help="trozo del nombre del .gguf a servir")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--ctx", type=int, default=CTX)
    ap.add_argument("--listar", action="store_true", help="ver modelos y salir")
    ap.add_argument("--sin-draft", action="store_true",
                    help="servir sin decodificacion especulativa")
    args = ap.parse_args()

    if args.listar:
        disponibles = modelos()
        if not disponibles:
            print(f"No hay .gguf en {DIR_MODELOS}")
            return 1
        print(f"Modelos en {DIR_MODELOS}:")
        for m in disponibles:
            print(f"  {m.stat().st_size / 1e9:6.1f} GB  {m.name}")
        return 0

    if responde(args.puerto):
        print(f"Ya hay un servidor respondiendo en :{args.puerto}. No arranco otro.")
        return 0

    exe = binario()
    if exe is None:
        print(f"No encuentro llama-server en {DIR_LLAMA}", file=sys.stderr)
        return 1

    modelo = elegir(args.modelo)
    if modelo is None:
        print(f"No encuentro modelo{' que case con ' + args.modelo if args.modelo else ''} "
              f"en {DIR_MODELOS}. Usa --listar para ver que hay.", file=sys.stderr)
        return 1

    orden = [str(exe), "--model", str(modelo), "--port", str(args.puerto),
             "--ctx-size", str(args.ctx), "--n-gpu-layers", "99",
             "--flash-attn", "on", "--jinja"]

    # Decodificacion especulativa: el 0.5B borra tokens y el 14B los verifica
    # y corrige — la salida es IDENTICA a la del 14B solo, pero mas rapida.
    # Medido el 2026-07-20 en esta maquina (300 tokens, mismas peticiones):
    #   codigo:  43.9 -> 107.4 tok/s (2.4x)
    #   espanol: 43.9 ->  47.8 tok/s
    # El p-min 0.6 es lo que evita el caso malo: sin el, en prosa espanola el
    # 0.5B (que es un coder) proponia basura, el 14B la rechazaba casi toda
    # (9% aceptado) y el total CAIA a 33 tok/s. Con p-min solo borra cuando
    # esta confiado: 66% de aceptacion en prosa y sin penalizacion.
    # OJO: --spec-type draft-simple es OBLIGATORIO — sin el, el server acepta
    # --spec-draft-model, lo ignora EN SILENCIO y sirve sin draft.
    draft = None
    if not args.sin_draft:
        preferido = modelo.name.lower()
        for m in modelos():
            if "0.5b" in m.name.lower() and m != modelo \
                    and preferido.split("-")[0] in m.name.lower():
                draft = m
                break
    if draft is not None:
        orden += ["--spec-draft-model", str(draft),
                  "--spec-type", "draft-simple",
                  "--spec-draft-ngl", "99",
                  "--spec-draft-n-max", "16",
                  "--spec-draft-p-min", "0.6"]
        print(f"  + draft especulativo: {draft.name} (2.4x medido en codigo)")

    print(f"Sirviendo {modelo.name} en :{args.puerto} (ctx {args.ctx})...")
    proceso = subprocess.Popen(
        orden,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    inicio = time.time()
    while time.time() - inicio < ESPERA_SEG:
        if responde(args.puerto):
            print(f"Listo en {time.time() - inicio:.0f}s. "
                  f"Cognia ya lo detecta (llm_local sondea :{PUERTO}).")
            print(f"Para pararlo: taskkill /IM {exe.name} /F")
            return 0
        if proceso.poll() is not None:
            print(f"El servidor murio al arrancar (codigo {proceso.returncode}). "
                  f"¿Cabe el modelo en la GPU?", file=sys.stderr)
            return 1
        time.sleep(2)

    print(f"No respondio en {ESPERA_SEG}s.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
