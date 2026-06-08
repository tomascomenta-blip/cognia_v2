"""
cognia/doctor.py
================
Cognia diagnostics, as an IMPORTABLE package module so `/doctor` works both from
the repo and from a pip-installed wheel (the old scripts/cognia_doctor.py was not
shipped in the package, so the installed CLI crashed). Run via `cognia.doctor.run_all`.

Checks: Python version, required/optional packages, Ollama, config, DB, shards,
and a warm inference speed measurement when local shards are present.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import urllib.request

# Installed CLI has no "repo root"; use the current working directory for the
# file-presence checks (.env / db / model_shards), which are advisory anyway.
_ROOT = os.getcwd()

_REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "numpy", "requests", "pydantic", "cryptography",
]

_OPTIONAL_PACKAGES = [
    ("sentence_transformers", "mejores embeddings — pip install sentence-transformers"),
    ("numba", "kernels JIT mas rapidos — pip install numba"),
]


def _line(tag: str, label: str, detail: str = "") -> None:
    text = f"  {tag}  {label}"
    if detail:
        text += f"  -- {detail}"
    print(text)


def _ok(label: str, detail: str = "") -> bool:
    _line("[OK]  ", label, detail)
    return True


def _fail(label: str, detail: str = "") -> bool:
    _line("[FAIL]", label, detail)
    return False


def _warn(label: str, detail: str = "") -> bool:
    _line("[WARN]", label, detail)
    return True


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    ver = f"{major}.{minor}"
    if (major, minor) >= (3, 11):
        return _ok(f"Python {ver}")
    return _fail(f"Python {ver}", "se requiere 3.11+")


def check_packages() -> bool:
    all_ok = True
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg}")
        except ImportError:
            _fail(f"  {pkg}", "falta -- pip install -U cognia-ai")
            all_ok = False
    for pkg, hint in _OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg} (opcional)")
        except ImportError:
            _warn(f"  {pkg} (opcional)", hint)
    return all_ok


def check_ollama() -> bool:
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.urlopen(f"{url}/api/tags", timeout=3)
        if req.status == 200:
            return _ok(f"Ollama corriendo en {url}")
        return _warn("Ollama", f"estado inesperado {req.status}")
    except Exception:
        return _warn("Ollama no disponible (opcional)",
                     "Cognia usa los shards locales sin Ollama")


def check_env() -> bool:
    cfg = os.path.join(os.path.expanduser("~"), ".cognia", "config.env")
    if os.path.isfile(cfg):
        return _ok("config en ~/.cognia/config.env")
    return _warn("config", "no configurado -- ejecuta: cognia init")


def check_db() -> bool:
    home = os.path.join(os.path.expanduser("~"), ".cognia")
    db_path = os.path.join(home, "cognia_memory.db")
    if os.path.isfile(db_path):
        return _ok("cognia_memory.db encontrada")
    if os.path.isdir(home) or os.access(os.path.expanduser("~"), os.W_OK):
        return _ok("cognia_memory.db", "se crea en el primer uso")
    return _fail("cognia_memory.db", "el directorio no es escribible")


def _shard_dir() -> str:
    sd = os.environ.get("SHARD_WEIGHTS_DIR", "")
    if sd and os.path.isdir(sd):
        return sd
    # default install location
    cand = os.path.join(os.path.expanduser("~"), ".cognia", "shards", "qwen-coder-3b-q4")
    return cand if os.path.isdir(cand) else ""


def check_shards() -> bool:
    sd = _shard_dir()
    if not sd:
        return _warn("shards", "ausentes -- modo Local los descarga (cognia modo local)")
    present = [f for f in os.listdir(sd) if f.startswith("shard_")]
    if present:
        return _ok("shards INT4", f"{len(present)} en {sd}")
    return _warn("shards", f"directorio vacio: {sd}")


def _manifest_path() -> "str | None":
    try:
        import shattering
        base = os.path.join(os.path.dirname(shattering.__file__), "manifests")
        for c in ("cognia_qwen.json", "cognia_desktop.json"):
            p = os.path.join(base, c)
            if os.path.isfile(p):
                return p
    except Exception:
        pass
    return None


def check_inference_speed() -> bool:
    sd = _shard_dir()
    if not sd:
        return _warn("Inferencia", "sin shards -- omitido")
    manifest = _manifest_path()
    if manifest is None:
        return _warn("Inferencia", "sin manifest -- omitido")
    try:
        import time
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator(manifest_path=manifest, mode="local")
        if not orch._shards_available():
            return _warn("Inferencia", "shards no detectados -- omitido")
        _ = orch.infer("Hola")  # warm-up (descarta cold start)
        t0 = time.perf_counter()
        result = orch.infer("Escribe una funcion corta que sume dos numeros.")
        latency_ms = (time.perf_counter() - t0) * 1000
        real_tokens = getattr(result, "tokens_generated", 0) or 0
        if real_tokens > 0 and latency_ms > 0:
            tok_s = real_tokens / latency_ms * 1000
            return _ok(f"Inferencia: {tok_s:.1f} tok/s (warm) | backend={result.mode} | "
                       f"{real_tokens} tok en {latency_ms:.0f}ms")
        return _ok(f"Inferencia OK | backend={result.mode} | {latency_ms:.0f}ms")
    except Exception as e:
        return _warn("Inferencia fallo", str(e))


def run_all() -> int:
    sections = [
        ("Version de Python", check_python),
        ("Paquetes Python",   check_packages),
        ("Ollama (opcional)", check_ollama),
        ("Configuracion",     check_env),
        ("Base de datos",     check_db),
        ("Shards del modelo", check_shards),
        ("Velocidad inferencia", check_inference_speed),
    ]
    fails = 0
    for label, fn in sections:
        print(f"\n{label}:")
        try:
            if not fn():
                fails += 1
        except Exception as e:
            _fail(label, str(e))
            fails += 1
    print()
    if fails == 0:
        print("Todo en orden. Cognia esta lista.")
    else:
        print(f"{fails} chequeo(s) con problemas. Revisa los [FAIL] arriba.")
    print()
    return 0 if fails == 0 else 1


def main() -> int:
    print("\nCognia -- diagnostico\n")
    return run_all()


if __name__ == "__main__":
    sys.exit(main())
