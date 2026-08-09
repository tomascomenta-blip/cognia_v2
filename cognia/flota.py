"""
cognia/flota.py — la logica de servir_flota como modulo DEL PAQUETE.

POR QUE EXISTE (WP6 2026-08-09): scripts/ no viaja en el wheel, asi que un
`pip install cognia-ai` dejaba al usuario sin manera de levantar la flota que
el propio doctor le pedia arrancar. La logica de combos vive aca (importable
tanto instalado como en el repo) y scripts/servir_flota.py DELEGA en este
modulo — sin duplicar, que era como el :8088 sirvio un modelo retirado
durante semanas (dos fuentes de verdad, memoria del repo 2026-07-25).

    cognia flota arrancar [combo] [patron]   # levanta el combo (default: pensar)
    cognia flota estado                      # que GGUF REAL sirve cada puerto
    cognia flota parar                       # detiene todos los llama-server

Los combos reusan scripts/servir_modelo.py y servir_vlm.py (eleccion de
binario/modelo NO duplicada). Esos scripts solo existen en un checkout del
repo o un editable install: si no estan, arrancar falla con la explicacion
honesta en vez de degradar en silencio.

Solo stdlib + cognia.backend_activo (que tambien es solo stdlib).
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# combo -> lista de (script, args). El orden importa: el cerebro primero.
# Regla de VRAM (16GB): en el lazo conviven a lo sumo un 14B-clase (~9GB) +
# VL-3B (~3.2GB). gpt-oss-20b (13.7GB) y VL-7B corren SOLOS.
COMBOS = {
    "construir": [
        ("servir_modelo.py", []),                             # coder-14b + draft
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "construir-ui": [
        # UIGEN como cerebro TOTAL del lazo (vision + html + reparaciones).
        # ctx 12288 y no 8192: UIGEN piensa largo ANTES del HTML y con 8k el
        # fence salia truncado aunque max_tokens fuera 12000 (medido
        # 2026-07-25). KV a 12k ~2.2GB: cabe con VL-3B (~14GB).
        ("servir_modelo.py", ["--modelo", "UIGEN", "--sin-draft",
                              "--ctx", "12288"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "pensar": [
        # ctx 16384 y no 8192: gpt-oss-20b es un modelo de RAZONAMIENTO y con
        # 8192 cortaba tareas reales por la mitad (finish_reason='length' a
        # los 7931 tokens, medido 2026-07-25: pass@1 25% con 8192 contra 100%
        # con 16384 en el mismo banco). Cabe: 12.2 GB de 16.3, corre solo.
        ("servir_modelo.py", ["--modelo", "gpt-oss", "--sin-draft",
                              "--ctx", "16384"]),
    ],
    "pensar-qwythos": [
        # CEREBRO PRINCIPAL desde 2026-08-09 (pedido del dueño). Qwythos-9B
        # (Qwen2.5 abliterado, 1M ctx) hace tool-calling NATIVO servido con
        # --jinja — verificado a mano: finish_reason=tool_calls, arguments
        # JSON. ctx 32768 y no el 8192 default: es un razonador (piensa fuerte
        # antes de responder) y 8192 lo cortaba; a 8192 usa 6.75 GB de 16.3,
        # asi que 32768 (~4 GB mas de KV) cabe holgado y corre SOLO.
        ("servir_modelo.py", ["--modelo", "qwythos", "--sin-draft",
                              "--ctx", "32768"]),
    ],
    "pensar-en-lazo": [
        ("servir_modelo.py", ["--modelo", "OpenReasoning", "--sin-draft"]),
        ("servir_vlm.py", ["--modelo", "VL-3B"]),
    ],
    "juzgar": [
        ("servir_vlm.py", ["--modelo", "VL-7B"]),
    ],
    # Modo MODELO UNICO: un solo GGUF en :8080 hace todo. El patron del
    # modelo se agrega en main() (argv extra); --sin-draft porque el draft
    # 0.5b solo ayuda a la familia coder.
    "solo": [
        ("servir_modelo.py", ["--sin-draft"]),
    ],
}

# El combo que arranca `cognia flota arrancar` sin argumento: el CEREBRO
# PRINCIPAL. Desde 2026-08-09 es Qwythos-9B (pedido del dueño); gpt-oss-20b
# sigue disponible como combo 'pensar' para quien lo quiera o para reproducir
# los bancos b1_* que lo mapean por nombre.
COMBO_DEFAULT = "pensar-qwythos"

PUERTOS = ((8080, "cerebro/pensador"), (8081, "VLM/arbitro"))

# Trozo (en minusculas) del nombre del GGUF -> combo que lo sirve en :8080.
# Para que el doctor/estado puedan decir no solo QUE modelo responde sino a
# QUE combo esperado corresponde (o que no corresponde a ninguno: la averia
# historica del :8088 era exactamente un server rancio con otro modelo).
CEREBROS = {
    "qwythos": "pensar-qwythos",
    "gpt-oss": "pensar",
    "uigen": "construir-ui",
    "openreasoning": "pensar-en-lazo",
    "nemotron": "pensar-en-lazo",
    "qwen2.5-coder-14b": "construir",
}


def combo_de_modelo(nombre_gguf: str) -> Optional[str]:
    """A que combo pertenece el GGUF servido en :8080, o None si a ninguno."""
    bajo = (nombre_gguf or "").lower()
    for trozo, combo in CEREBROS.items():
        if trozo in bajo:
            return combo
    return None


def _scripts_dir() -> Optional[Path]:
    """Donde viven servir_modelo.py / servir_vlm.py.

    Solo en un checkout del repo (o editable install, que apunta al repo):
    cognia/ y scripts/ son hermanos. En un wheel normal no estan — se
    devuelve None y arrancar() lo explica en vez de reventar con un
    FileNotFoundError criptico."""
    candidato = Path(__file__).resolve().parent.parent / "scripts"
    if (candidato / "servir_modelo.py").is_file():
        return candidato
    return None


def _responde(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def props_puerto(puerto: int) -> dict:
    """{'modelo', 'n_ctx', 'puerto'} del server en ese puerto, {} si no
    responde. forzar=True: el cache de backend_activo miente tras un
    reinicio en el mismo puerto, y estado/doctor quieren el AHORA."""
    from cognia import backend_activo
    return backend_activo.props(f"http://127.0.0.1:{puerto}", forzar=True)


def parar() -> int:
    """Detiene todos los llama-server (Windows: taskkill; POSIX: pkill)."""
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"],
                           capture_output=True, text=True)
    else:
        r = subprocess.run(["pkill", "-f", "llama-server"],
                           capture_output=True, text=True)
    print("Detenidos." if r.returncode == 0 else "No habia llama-server vivo.")
    return 0


def estado() -> int:
    """Que responde en cada puerto y QUE GGUF sirve de verdad (via /props).

    Antes solo decia RESPONDE/no responde: un server rancio sirviendo otro
    modelo era invisible — la averia del :8088 con el 7B retirado."""
    for puerto, rol in PUERTOS:
        p = props_puerto(puerto)
        if not p:
            print(f"  :{puerto} ({rol}): no responde")
            continue
        modelo = p.get("modelo") or "desconocido"
        combo = combo_de_modelo(modelo)
        extra = f" [combo '{combo}']" if combo else ""
        ctx = p.get("n_ctx")
        ctx_txt = f", ctx {ctx}" if ctx else ""
        print(f"  :{puerto} ({rol}): RESPONDE — {modelo}{ctx_txt}{extra}")
    return 0


def arrancar(modo: str, patron: str = "") -> int:
    """Levanta el combo `modo`. `patron` solo aplica al modo 'solo'."""
    if modo not in COMBOS:
        print(f"Combo desconocido: {modo!r}. Validos: "
              f"{sorted(COMBOS) + ['parar', 'estado']}", file=sys.stderr)
        return 1
    if patron and modo != "solo":
        print(f"El combo {modo!r} no lleva argumentos extra.", file=sys.stderr)
        return 1

    scripts = _scripts_dir()
    if scripts is None:
        print("No encuentro scripts/servir_modelo.py: los combos se sirven "
              "desde un checkout del repo (o un editable install: "
              "pip install -e <repo>). En una instalacion pip normal arranca "
              "el server a mano o fija COGNIA_LLM_URL.", file=sys.stderr)
        return 1

    combo = COMBOS[modo]
    if modo == "solo" and patron:
        # patron de modelo elegido por el usuario (match por substring en
        # servir_modelo.elegir): "solo qwythos", "solo gpt-oss", etc.
        combo = [(script, ["--modelo", patron] + args)
                 for script, args in combo]

    # Cambiar de combo con restos del anterior = OOM confuso. Se para primero.
    if _responde(8080) or _responde(8081):
        print("Habia servidores vivos: los detengo antes del combo nuevo.")
        parar()

    for script, args in combo:
        orden = [sys.executable, str(scripts / script)] + args
        print(f"-> {script} {' '.join(args)}")   # ascii: la consola es cp1252
        r = subprocess.run(orden)
        if r.returncode != 0:
            print(f"{script} fallo (codigo {r.returncode}); no sigo con el "
                  f"combo a medias.", file=sys.stderr)
            return r.returncode
    print(f"\nCombo '{modo}' listo.")
    estado()
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: acepta tanto `cognia flota <accion>` como la forma historica del
    script (`servir_flota.py <combo>`), para no romper la memoria muscular."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1
    accion = argv[0]
    if accion == "parar":
        return parar()
    if accion == "estado":
        return estado()
    if accion == "arrancar":
        modo = argv[1] if len(argv) > 1 else COMBO_DEFAULT
        if len(argv) == 1:
            print(f"(combo por defecto: {COMBO_DEFAULT})")
        return arrancar(modo, patron=argv[2] if len(argv) > 2 else "")
    # Forma historica: el combo directo como primer argumento.
    if accion in COMBOS:
        return arrancar(accion, patron=argv[1] if len(argv) > 1 else "")
    print(f"Accion desconocida: {accion!r}. Usa: arrancar [combo] | estado | "
          f"parar  (combos: {sorted(COMBOS)})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
