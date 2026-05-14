"""
scripts/cognia_doctor.py
=========================
Cognia diagnostics -- verifies that the local environment is correctly
configured. Run before launching Cognia for the first time or after
any dependency change.

Usage:
    python scripts/cognia_doctor.py
"""
from __future__ import annotations

import importlib
import os
import sys
import json
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_REQUIRED_PACKAGES = [
    "fastapi",
    "uvicorn",
    "numpy",
    "requests",
    "pydantic",
    "sentence_transformers",
    "cryptography",
]

_OPTIONAL_PACKAGES = [
    ("faiss", "faster episodic search — install faiss-cpu"),
    ("torch", "real shard inference — install torch"),
    ("transformers", "real shard inference — install transformers"),
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
    return _fail(f"Python {ver}", "3.11+ required")


def check_packages() -> bool:
    all_ok = True
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg}")
        except ImportError:
            _fail(f"  {pkg}", "missing -- run: pip install -r requirements.txt")
            all_ok = False
    for pkg, hint in _OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg} (optional)")
        except ImportError:
            _warn(f"  {pkg} (optional)", hint)
    return all_ok


def check_ollama() -> bool:
    try:
        req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        if req.status == 200:
            return _ok("Ollama running at localhost:11434")
        return _warn("Ollama", f"unexpected status {req.status}")
    except Exception:
        return _warn("Ollama not reachable",
                     "start Ollama or install from https://ollama.ai")


def check_ollama_model() -> bool:
    model = os.environ.get("COGNIA_OLLAMA_MODEL", "llama3.2")
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        names = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
        if model.split(":")[0] in names:
            return _ok(f"Modelo '{model}' disponible")
        return _warn(f"Modelo '{model}' NO descargado",
                     f"ejecuta: ollama pull {model}")
    except Exception as e:
        return _warn(f"No se pudo verificar modelos: {e}")


def check_env() -> bool:
    env_path = os.path.join(_ROOT, ".env")
    if os.path.isfile(env_path):
        return _ok(".env file present")
    return _warn(".env file", "missing -- copy .env.example to .env")


def check_db() -> bool:
    db_path = os.path.join(_ROOT, "cognia_memory.db")
    if os.path.isfile(db_path):
        return _ok("cognia_memory.db found")
    if os.access(_ROOT, os.W_OK):
        return _ok("cognia_memory.db", "not created yet -- will be initialized on first run")
    return _fail("cognia_memory.db", "project directory is not writable")


def check_shards() -> bool:
    shards_dir = os.path.join(_ROOT, "model_shards")
    if not os.path.isdir(shards_dir):
        return _warn("model_shards/",
                     "directory absent -- shards are downloaded on first inference request")
    entries = [d for d in os.listdir(shards_dir)
               if os.path.isdir(os.path.join(shards_dir, d))]
    if entries:
        return _ok("model_shards/", f"{len(entries)} sub-model(s) present")
    return _warn("model_shards/",
                 "empty -- shards are downloaded on first inference request")


def run_all() -> int:
    sections = [
        ("Python version",    check_python),
        ("Python packages",   check_packages),
        ("Ollama",            check_ollama),
        ("Ollama model",      check_ollama_model),
        ("Configuration",     check_env),
        ("Database",          check_db),
        ("Model shards",      check_shards),
    ]

    fails = 0
    for label, fn in sections:
        print(f"\n{label}:")
        if not fn():
            fails += 1

    print()
    if fails == 0:
        print("All checks passed. Cognia is ready.")
    else:
        print(f"{fails} check(s) failed. Review [FAIL] items above.")
    print()
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    print("\nCognia -- diagnostics\n")
    sys.exit(run_all())
