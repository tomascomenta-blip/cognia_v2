"""
cognia/bbrain.py
================
Generador autonomo de bbrain.md — el documento de contexto del repo.

Reemplaza la necesidad de mantener un CLAUDE.md a mano: introspecta EN VIVO
el entorno (Python, hardware, GPU), el backend LLM disponible (GGUF, shards
NPZ, Ollama) y el mapa del repo, y embebe las reglas duras del proyecto como
constante. El resultado es un bbrain.md autosuficiente y siempre actualizado.

Uso:
    cognia bbrain                  -- regenerar bbrain.md en la raiz del repo
    from cognia.bbrain import write_bbrain; write_bbrain(repo_root)

Diseno: funciones planas, cada sonda envuelta en try/except con timeout.
NADA aca puede colgarse ni tirar una excepcion no capturada — el REPL
regenera este archivo en el arranque y no puede romperse por esto.
"""

from __future__ import annotations

import datetime
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

# Raiz real del repo (donde vive este paquete), usada para importar `node`.
_PKG_ROOT = Path(__file__).resolve().parent.parent

# Directorio de modelos GGUF del usuario (instalados por el wizard/installer).
_MODELS_DIR = Path.home() / ".cognia" / "models"

# Subpaquetes principales que forman el mapa del repo.
_MAIN_PACKAGES = ("cognia", "node", "shattering", "coordinator", "storage", "security", "tests")


# ── Reglas del proyecto (antes en CLAUDE.md; ahora viven aca) ────────────────

_PROJECT_RULES = """\
## Reglas del proyecto

### Restricciones duras (no negociar)
- Entorno: usar SIEMPRE `venv312\\Scripts\\python.exe` (Python 3.12). El `venv/` del repo
  esta roto (Python 3.14, wheels faltantes). Nunca `python` pelado para tests o scripts.
- Sin PyTorch en nodos. Sin sharding WAN sincrono. Sin FedAvg. Sin draft model centralizado.
- Cero datos personales centralizados.
- Nada de mocks/stubs en produccion. Codigo que corre o no cuenta: cada subsistema
  cierra con prueba CLI real.
- Sin `sqlite3.connect()` directo -> usar `storage/db_pool.py`.
- Sin constantes de modelo hardcodeadas -> usar `shattering/model_constants.py`.
- Secretos NUNCA commiteados: `.env`, tokens y claves quedan fuera de git; cargar
  tokens por variable de entorno y redactar cualquier secreto del output.

### Metodo de trabajo esencial
1. Verificar antes de construir: leer el codigo real y ejecutar la pieza ANTES de
   construir encima; no confiar en docs viejas sin verificar la afirmacion clave.
2. Diagnostico antes que parche: encontrar la causa raiz (leer codigo, reproducir el
   bug) en vez de tapar el sintoma.
3. Verificacion REAL, no solo pytest: cerrar cada cambio corriendo el CLI / el modelo
   de verdad end-to-end y mostrando el output real. pytest es necesario pero no
   suficiente.
4. Test de regresion por cada bug/feature: un test que falle sin el fix y pase con el.
   Reportar el conteo real (N passed / M failed).
5. Codigo concreto, sin abstracciones de mas: funciones planas, dicts, registries
   simples; igualar estilo y densidad de comentarios del codigo vecino.
6. Honestidad: declarar limites y trade-offs; si algo queda a medias, decirlo.

### Verificacion rapida
```
.\\venv312\\Scripts\\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```
"""


# ── Sondas de entorno (cada una es best-effort y no puede explotar) ──────────

def _gpu_info() -> str:
    """GPU NVIDIA via nvidia-smi; 'sin GPU NVIDIA detectada' si no hay o falla."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return "sin GPU NVIDIA detectada"


def _hardware_lines() -> list[str]:
    """CPU / cores / RAM via platform + psutil (opcional), GPU via nvidia-smi."""
    lines = [
        f"- Python: {sys.version.split()[0]} ({sys.executable})",
        f"- SO: {platform.platform()}",
        f"- CPU: {platform.processor() or platform.machine()}",
    ]
    try:
        import psutil
        lines.append(f"- Cores: {psutil.cpu_count(logical=False)} fisicos / {psutil.cpu_count()} logicos")
        lines.append(f"- RAM: {psutil.virtual_memory().total / 1e9:.1f} GB")
    except Exception:
        lines.append(f"- Cores: {os.cpu_count()} logicos (psutil no disponible)")
    lines.append(f"- GPU: {_gpu_info()}")
    return lines


def _ollama_status() -> str:
    """Ping a Ollama con timeout corto; nunca cuelga ni explota."""
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        urllib.request.urlopen(f"{url}/api/tags", timeout=2)
        return f"disponible en {url}"
    except Exception:
        return f"no disponible en {url}"


def _backend_lines() -> list[str]:
    """Backend LLM detectado: GGUF activo, modelos instalados, shards NPZ, Ollama."""
    lines: list[str] = []

    # GGUF que usaria el backend llama.cpp (mismo resolutor que en produccion)
    gguf = None
    try:
        if str(_PKG_ROOT) not in sys.path:
            sys.path.insert(0, str(_PKG_ROOT))
        from node.llama_backend import _find_gguf
        gguf = _find_gguf()
    except Exception:
        pass
    lines.append(f"- GGUF activo (node.llama_backend): {gguf if gguf else 'no encontrado'}")

    # Modelos GGUF instalados en ~/.cognia/models
    try:
        if _MODELS_DIR.is_dir():
            ggufs = sorted(p.name for p in _MODELS_DIR.glob("*.gguf"))
            lines.append(f"- Modelos en {_MODELS_DIR}: {', '.join(ggufs) if ggufs else '(vacio)'}")
        else:
            lines.append(f"- Modelos en {_MODELS_DIR}: (directorio no existe)")
    except Exception:
        lines.append(f"- Modelos en {_MODELS_DIR}: (no legible)")

    # Shards NPZ del swarm (SHARD_WEIGHTS_DIR)
    shard_dir_raw = os.environ.get("SHARD_WEIGHTS_DIR", "")
    if shard_dir_raw:
        try:
            shard_dir = Path(shard_dir_raw)
            if shard_dir.is_dir():
                npz = sorted(p.name for p in shard_dir.glob("*.npz"))
                lines.append(f"- Shards NPZ en {shard_dir}: {', '.join(npz) if npz else '(vacio)'}")
            else:
                lines.append(f"- Shards NPZ: SHARD_WEIGHTS_DIR apunta a dir inexistente ({shard_dir})")
        except Exception:
            lines.append("- Shards NPZ: (no legible)")
    else:
        lines.append("- Shards NPZ: SHARD_WEIGHTS_DIR no configurado")

    lines.append(f"- Ollama: {_ollama_status()}")
    return lines


def _repo_map_lines(repo_root: Path) -> list[str]:
    """Conteo de modulos top-level, subpaquetes principales y tests."""
    lines: list[str] = []
    try:
        n_top = len(list(repo_root.glob("*.py")))
        lines.append(f"- Modulos .py top-level: {n_top}")
    except Exception:
        lines.append("- Modulos .py top-level: (no legible)")

    for pkg in _MAIN_PACKAGES:
        try:
            pkg_dir = repo_root / pkg
            if pkg_dir.is_dir():
                n = sum(1 for p in pkg_dir.rglob("*.py") if "__pycache__" not in p.parts)
                lines.append(f"- {pkg}/: {n} archivos .py")
        except Exception:
            continue

    try:
        tests_dir = repo_root / "tests"
        n_tests = len(list(tests_dir.glob("test_*.py"))) if tests_dir.is_dir() else 0
        lines.append(f"- Archivos de test (tests/test_*.py): {n_tests}")
    except Exception:
        lines.append("- Archivos de test: (no legible)")
    return lines


# ── API publica ──────────────────────────────────────────────────────────────

def generate_bbrain(repo_root: Path) -> str:
    """Arma el markdown completo de bbrain.md introspectando el entorno vivo."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections = [
        "# bbrain.md — Cerebro del repo Cognia",
        "",
        "> AUTOGENERADO por cognia/bbrain.py — no editar a mano; regenerar con `cognia bbrain`.",
        f"> Generado: {now}",
        "",
        "## Entorno",
        *_hardware_lines(),
        "",
        "## Backend LLM",
        *_backend_lines(),
        "",
        "## Mapa del repo",
        *_repo_map_lines(repo_root),
        "",
        _PROJECT_RULES,
    ]
    return "\n".join(sections)


def write_bbrain(repo_root: Path) -> Path:
    """Escribe bbrain.md (UTF-8) en la raiz dada y devuelve la ruta."""
    path = Path(repo_root) / "bbrain.md"
    path.write_text(generate_bbrain(Path(repo_root)), encoding="utf-8")
    return path
