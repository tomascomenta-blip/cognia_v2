"""
servir_flota.py — levanta el COMBO de modelos correcto para cada tarea.

POR QUE EXISTE (reformulacion de flota 2026-07-24, planes/FLOTA_ROLES_2026-07.md):
la flota aproxima a un frontier (GLM 5.2) por RUTEO DE ROLES, y cada tarea
necesita un combo distinto que quepa en los 16GB de la 5060 Ti. Servir el combo
a mano (que modelo, que puerto, que cabe con que) era propenso a error — y el
modo de fallo de Cognia es degradar en silencio cuando falta un backend.

    python scripts/servir_flota.py construir       # coder-14b(+draft) :8080 + VL-3B :8081
    python scripts/servir_flota.py construir-ui    # UIGEN-X-8B :8080 + VL-3B :8081
    python scripts/servir_flota.py pensar          # gpt-oss-20b :8080 (GPU entera)
    python scripts/servir_flota.py pensar-en-lazo  # OpenReasoning-Nemotron-14B :8080 + VL-3B :8081
    python scripts/servir_flota.py juzgar          # VL-7B :8081 (juez fino, solo)
    python scripts/servir_flota.py parar           # detiene todos los llama-server
    python scripts/servir_flota.py estado          # que responde en 8080/8081

Regla de VRAM (16GB): en el lazo conviven a lo sumo un 14B-clase (~9GB) + VL-3B
(~3.2GB). gpt-oss-20b (13.7GB) y VL-7B corren SOLOS. SDXL corre solo (los
mockups/sprites se generan en fase previa: mockup_path/assets del lazo).

Solo stdlib. Reusa servir_modelo.py y servir_vlm.py (no duplica la eleccion de
binario/modelo).
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# modo -> lista de (script, args). El orden importa: el cerebro primero.
COMBOS = {
    "construir": [
        ("servir_modelo.py", []),                             # coder-14b + draft
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "construir-ui": [
        # UIGEN como cerebro TOTAL del lazo (vision + html + reparaciones):
        # llm_local sondea :8080 y lo encuentra a el.
        ("servir_modelo.py", ["--modelo", "UIGEN", "--sin-draft"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "pensar": [
        ("servir_modelo.py", ["--modelo", "gpt-oss", "--sin-draft"]),
    ],
    "pensar-en-lazo": [
        ("servir_modelo.py", ["--modelo", "OpenReasoning", "--sin-draft"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "juzgar": [
        ("servir_vlm.py", ["--modelo", "VL-7B"]),
    ],
}


def _responde(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def parar() -> int:
    """Windows: taskkill de todos los llama-server."""
    r = subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"],
                       capture_output=True, text=True)
    print("Detenidos." if r.returncode == 0 else "No habia llama-server vivo.")
    return 0


def estado() -> int:
    for puerto, rol in ((8080, "cerebro/pensador"), (8081, "VLM/arbitro")):
        print(f"  :{puerto} ({rol}): "
              f"{'RESPONDE' if _responde(puerto) else 'no responde'}")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 1
    modo = sys.argv[1]
    if modo == "parar":
        return parar()
    if modo == "estado":
        return estado()
    if modo not in COMBOS:
        print(f"Modo desconocido: {modo!r}. Validos: "
              f"{sorted(COMBOS) + ['parar', 'estado']}", file=sys.stderr)
        return 1

    # Cambiar de combo con restos del anterior = OOM confuso. Se para primero.
    if _responde(8080) or _responde(8081):
        print("Habia servidores vivos: los detengo antes del combo nuevo.")
        parar()

    for script, args in COMBOS[modo]:
        orden = [sys.executable, str(AQUI / script)] + args
        print(f"-> {script} {' '.join(args)}")   # ascii: la consola es cp1252
        r = subprocess.run(orden)
        if r.returncode != 0:
            print(f"{script} fallo (codigo {r.returncode}); no sigo con el "
                  f"combo a medias.", file=sys.stderr)
            return r.returncode
    print(f"\nCombo '{modo}' listo.")
    estado()
    return 0


if __name__ == "__main__":
    sys.exit(main())
