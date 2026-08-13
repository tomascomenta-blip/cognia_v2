# -*- coding: utf-8 -*-
"""Cuanta VRAM cuesta REALMENTE un token de contexto en el server que corre ahora.

La formula teorica (n_layer x n_head_kv x head_dim x 2 x bytes) da una cota que
NO siempre se cumple: llama.cpp puede reservar el KV de forma incremental, y las
arquitecturas hibridas (ventana deslizante, atencion lineal) no gastan KV denso
en todas las capas. Este script no discute: manda prompts cada vez mas largos al
server REAL y mide la VRAM antes y despues con nvidia-smi.

Uso:  venv312\\Scripts\\python.exe scripts\\medir_kv_real.py [url] [tokens...]

No escribe nada ni reinicia el servicio: solo hace peticiones.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8080"


def vram_mib() -> int:
    salida = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=30)
    return int(salida.stdout.strip().splitlines()[0])


def post(path: str, carga: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        URL + path, data=json.dumps(carga).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def tokenizar(texto: str) -> int:
    return len(post("/tokenize", {"content": texto}).get("tokens", []))


def main() -> int:
    global URL
    args = sys.argv[1:]
    if args and args[0].startswith("http"):
        URL = args.pop(0).rstrip("/")
    objetivos = [int(a) for a in args] or [4000, 16000, 48000]

    # Parrafo de relleno con contenido variado: un texto repetitivo se comprime
    # en el prefix-cache y falsea la medida.
    semilla = ("El sistema registro el evento numero %d en el modulo de "
               "verificacion, con una latencia de %d milisegundos y un estado "
               "de salida distinto del anterior. ")

    base = vram_mib()
    print(f"VRAM en reposo: {base} MiB")
    print(f"{'tokens':>9} {'VRAM MiB':>9} {'delta':>8} {'B/token':>9} {'prefill s':>10}")
    print("-" * 50)

    previo_tok, previo_vram = 0, base
    for objetivo in objetivos:
        texto = "".join(semilla % (i, i * 7 % 997) for i in range(objetivo // 4))
        n_tok = tokenizar(texto)
        t0 = time.time()
        # n_predict=1: interesa el PREFILL (llenar el KV), no la generacion.
        r = post("/completion", {"prompt": texto, "n_predict": 1,
                                 "temperature": 0, "cache_prompt": False})
        dt = time.time() - t0
        time.sleep(1.5)                      # que el allocador se asiente
        ahora = vram_mib()
        d_tok = n_tok - previo_tok
        d_vram = ahora - previo_vram
        b_tok = (d_vram * 1024**2 / d_tok) if d_tok > 0 else 0
        print(f"{n_tok:>9,} {ahora:>9,} {d_vram:>+8,} {b_tok:>8,.0f} {dt:>10.1f}")
        ts = (r.get("timings") or {})
        if ts:
            print(f"{'':>9} prefill {ts.get('prompt_per_second', 0):,.0f} tok/s "
                  f"| generacion {ts.get('predicted_per_second', 0):,.1f} tok/s")
        previo_tok, previo_vram = n_tok, ahora

    print(f"\nVRAM total de la tarjeta: 16311 MiB")
    print(f"margen libre ahora: {16311 - vram_mib():,} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
