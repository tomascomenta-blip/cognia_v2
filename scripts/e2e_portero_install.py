# -*- coding: utf-8 -*-
"""E2E de INSTALACIÓN del PORTERO (PREREG_PORTERO_FASE2, promoción):

  1. COGNIA_HOME TEMPORAL (simula máquina limpia; no toca ~/.cognia).
  2. install_portero() REAL: base 0.5B Q8_0 de HF (~644MB) + LoRA del
     release fleet-v1 de GitHub (asset recién publicado).
  3. Smoke con el camino del deploy: fast_speech_backend() (server b9391 +
     LoRA estática, puerto alterno) + classify_turn + portero_system →
     la respuesta de identidad debe decir "Cognia".

Uso:  .\\venv312\\Scripts\\python.exe scripts/e2e_portero_install.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

# COGNIA_HOME temporal ANTES de importar cognia.* (first_run lo lee al importar)
HOME = Path(tempfile.mkdtemp(prefix="portero_e2e_"))
os.environ["COGNIA_HOME"] = str(HOME)
os.environ["COGNIA_CASCADE_FAST_PORT"] = "8093"   # no chocar con un 8090 vivo
os.environ.pop("PORTERO_GGUF_PATH", None)
os.environ.pop("PORTERO_LORA_PATH", None)
os.environ.pop("COGNIA_PORTERO", None)

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:100]}" if detalle else ""), flush=True)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"== 1. install_portero REAL (HOME={HOME}) ==", flush=True)
    from cognia.model_install import install_portero, PORTERO_DIR, PORTERO_GGUF_FILE, PORTERO_LORA_FILE
    t0 = time.time()
    ok = install_portero()
    check(f"P1 install_portero ({time.time()-t0:.0f}s)", ok)
    base = PORTERO_DIR / PORTERO_GGUF_FILE
    lora = PORTERO_DIR / PORTERO_LORA_FILE
    check("P2 base Q8_0 en HOME temporal", base.is_file() and base.stat().st_size > 300 << 20,
          f"{base.stat().st_size // (1 << 20) if base.is_file() else 0} MB")
    check("P3 LoRA del release", lora.is_file() and lora.stat().st_size > 1 << 20,
          f"{lora.stat().st_size // (1 << 20) if lora.is_file() else 0} MB")

    print("== 2. smoke por el camino del deploy ==", flush=True)
    from node.speech_cascade import (fast_speech_backend, portero_activo,
                                     classify_turn, portero_system)
    check("P4 portero_activo por presencia", portero_activo() is True)
    check("P5 identidad rutea al portero",
          classify_turn("¿quién sos?", identidad=portero_activo()) == "fast")
    fb = fast_speech_backend()
    check("P6 server portero arranca", fb is not None)
    resp = ""
    if fb is not None:
        prompt = (f"<|im_start|>system\n{portero_system('¿quién sos?')}<|im_end|>\n"
                  f"<|im_start|>user\n¿quién sos?<|im_end|>\n<|im_start|>assistant\n")
        resp = (fb.generate(prompt, max_tokens=60, temperature=0.0) or "").strip()
        fb.stop()
    check("P7 responde como Cognia", "cognia" in resp.lower(), resp)

    fallos = [n for n, ok_ in CHECKS if not ok_]
    print(f"\nE2E PORTERO INSTALL: {len(CHECKS) - len(fallos)}/{len(CHECKS)} OK")
    if fallos:
        print("FALLARON:", fallos)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
