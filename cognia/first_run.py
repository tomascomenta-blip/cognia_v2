"""
cognia/first_run.py
===================
First-run setup wizard. Runs once when no config exists at ~/.cognia/config.env.

Detects whether the user wants to run standalone or join the distributed network.
In network mode, downloads the shard assigned by the coordinator automatically.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

COGNIA_HOME  = Path.home() / ".cognia"
CONFIG_FILE  = COGNIA_HOME / "config.env"
SHARDS_DIR   = COGNIA_HOME / "shards"
DATA_DIR     = COGNIA_HOME / "data"
FIRST_RUN_OK = COGNIA_HOME / ".setup_done"

HF_REPO   = "Qwen/Qwen2.5-Coder-3B-Instruct"
MODEL_KEY = "qwen-coder-3b-q4"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer or default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    try:
        answer = input(f"{prompt} [{default_str}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if not answer:
        return default
    return answer in ("y", "yes", "si", "s")


def _http_get(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _coordinator_reachable(url: str) -> bool:
    try:
        _http_get(f"{url.rstrip('/')}/health", timeout=4)
        return True
    except Exception:
        try:
            _http_get(f"{url.rstrip('/')}/ready", timeout=4)
            return True
        except Exception:
            return False


def _hf_cli_available() -> bool:
    return shutil.which("huggingface-cli") is not None


def _safetensors_available() -> bool:
    try:
        import safetensors   # noqa: F401
        return True
    except ImportError:
        return False


# ── Weight download ────────────────────────────────────────────────────────────

def _download_weights(hf_token: str = "") -> Path:
    """Download Qwen2.5-Coder-3B from HuggingFace and convert to INT4 shards."""
    download_dir = COGNIA_HOME / "hf_cache" / "qwen"
    out_dir      = SHARDS_DIR / MODEL_KEY
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already converted
    if (out_dir / "shard_0.npz").exists():
        print(f"  Shards ya existen en {out_dir}")
        return out_dir

    # Need safetensors for conversion
    if not _safetensors_available():
        print("  Instalando safetensors...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "safetensors", "huggingface_hub", "-q"])

    # Download from HuggingFace
    download_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n  Descargando {HF_REPO} (~6GB)...")
    print("  Esto puede tardar varios minutos dependiendo de tu conexion.")

    cmd = [
        sys.executable, "-m", "huggingface_hub", "snapshot_download",
        "--repo-id", HF_REPO,
        "--local-dir", str(download_dir),
        "--repo-type", "model",
    ]
    if hf_token:
        cmd += ["--token", hf_token]

    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        # Fallback to huggingface-cli if available
        if _hf_cli_available():
            cli_cmd = ["huggingface-cli", "download", HF_REPO,
                       "--local-dir", str(download_dir)]
            if hf_token:
                cli_cmd += ["--token", hf_token]
            subprocess.check_call(cli_cmd)
        else:
            raise

    # Convert to INT4 shards
    print(f"\n  Convirtiendo a INT4 shards -> {out_dir}")
    print("  Esto puede tardar 5-15 minutos...")

    # Find the convert script relative to this file or installed package
    script = _find_convert_script()
    if script:
        subprocess.check_call([
            sys.executable, str(script),
            "--hf-dir",  str(download_dir),
            "--out-dir", str(out_dir),
        ])
    else:
        print("  [ERROR] No se encontro convert_hf_to_shards.py")
        print("  Ejecuta manualmente:")
        print(f"    python scripts/convert_hf_to_shards.py --hf-dir {download_dir} --out-dir {out_dir}")
        sys.exit(1)

    print(f"  Shards listos en {out_dir}")
    return out_dir


def _find_convert_script() -> Path | None:
    """Find convert_hf_to_shards.py relative to the package or installed location."""
    candidates = [
        Path(__file__).parent.parent / "scripts" / "convert_hf_to_shards.py",
        Path(sys.prefix) / "scripts" / "cognia_convert_shards.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ── Config file ───────────────────────────────────────────────────────────────

def _write_config(vars: dict[str, str]) -> None:
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}\n" for k, v in vars.items() if v]
    CONFIG_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"\n  Configuracion guardada en {CONFIG_FILE}")


def _load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    config = {}
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            config[k.strip()] = v.strip()
    return config


def apply_config() -> None:
    """Load ~/.cognia/config.env into os.environ (call at startup)."""
    for k, v in _load_config().items():
        if k not in os.environ:
            os.environ[k] = v


# ── Main wizard ───────────────────────────────────────────────────────────────

def run_wizard(force: bool = False) -> None:
    """
    Interactive first-run wizard.

    Asks the user for their setup mode and configures ~/.cognia/ accordingly.
    Safe to call every startup — skips if already configured unless force=True.
    """
    if FIRST_RUN_OK.exists() and not force:
        return

    print("\n" + "=" * 55)
    print("  Cognia -- Configuracion inicial")
    print("=" * 55)
    print("\nEste wizard configura Cognia en tu dispositivo.")
    print("Solo se ejecuta una vez. Puedes repetirlo con: cognia init\n")

    # ── Modo ──────────────────────────────────────────────────────────
    print("Modos disponibles:")
    print("  1. Standalone     - inferencia local con Ollama")
    print("  2. Nodo de red    - unirse al swarm distribuido")
    print("  3. Solo memoria   - sin LLM (solo memoria episodica y grafo)")
    print()

    mode = _ask("Selecciona modo", default="1")

    config: dict[str, str] = {}

    # Create dirs
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)

    config["COGNIA_DATA_DIR"] = str(DATA_DIR)

    # ── Modo 1: Standalone ─────────────────────────────────────────────
    if mode == "1":
        print("\n-- Modo Standalone --")
        print("Cognia usara Ollama local para inferencia.")
        print("Si Ollama no esta instalado: https://ollama.ai\n")

        ollama_url = _ask("URL de Ollama", default="http://localhost:11434")
        ollama_model = _ask("Modelo Ollama", default="llama3.2")
        config["OLLAMA_URL"]    = ollama_url
        config["COGNIA_MODEL"]  = ollama_model

        if _ask_yn("\nDescargar pesos Qwen2.5-Coder-3B (~1.2GB comprimidos) para inferencia local?",
                   default=False):
            hf_token = _ask("HuggingFace token (opcional, Enter para omitir)", default="")
            try:
                shard_dir = _download_weights(hf_token)
                config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
            except Exception as exc:
                print(f"\n  [ERROR] Descarga fallo: {exc}")
                print("  Puedes descargar los pesos manualmente luego con: cognia download-weights")

    # ── Modo 2: Nodo de red ────────────────────────────────────────────
    elif mode == "2":
        print("\n-- Modo Nodo de Red --")
        print("Cognia descargara el shard que le asigne el coordinador.")
        print("Solo necesitas la URL del coordinador.\n")

        coord_url = _ask("URL del coordinador")
        if not coord_url:
            print("  [ERROR] Se requiere la URL del coordinador.")
            sys.exit(1)

        print(f"\n  Verificando coordinador en {coord_url}...")
        if _coordinator_reachable(coord_url):
            print("  Coordinador accesible.")
        else:
            print("  [WARN] El coordinador no responde ahora. Se intentara al iniciar.")

        config["COGNIA_COORDINATOR_URL"] = coord_url

        # Download the shard assigned by coordinator
        if _ask_yn("\nDescargar ahora el shard asignado por el coordinador?", default=True):
            _download_shard_from_coordinator(coord_url, config)

    # ── Modo 3: Solo memoria ───────────────────────────────────────────
    elif mode == "3":
        print("\n-- Modo Solo Memoria --")
        print("Cognia funcionara sin LLM: aprendizaje, grafo y memoria activos.")

    else:
        print(f"  Modo '{mode}' no reconocido. Usando Standalone.")

    # ── Ollama model para modos 2 y 3 también ─────────────────────────
    if mode in ("2", "3") and "OLLAMA_URL" not in config:
        if _ask_yn("\nConfigurar Ollama como fallback?", default=True):
            config["OLLAMA_URL"]   = _ask("URL de Ollama", default="http://localhost:11434")
            config["COGNIA_MODEL"] = _ask("Modelo Ollama", default="llama3.2")

    # ── Guardar ────────────────────────────────────────────────────────
    _write_config(config)
    FIRST_RUN_OK.touch()

    print("\n" + "=" * 55)
    print("  Configuracion completa.")
    print("=" * 55)
    print(f"\n  Datos en:  {COGNIA_HOME}")
    print("  Comandos:")
    print("    cognia              -- iniciar REPL")
    print("    cognia server       -- servidor web (puerto 8000)")
    print("    cognia node         -- iniciar como nodo del swarm")
    print("    cognia coordinator  -- iniciar coordinador")
    print("    cognia init         -- repetir este wizard")
    print()


def _download_shard_from_coordinator(coord_url: str, config: dict) -> None:
    """Register with coordinator and download the assigned shard."""
    try:
        import platform

        hardware = platform.processor()[:40] or platform.machine()
        try:
            import psutil
            hardware += f" | {psutil.virtual_memory().total / 1e9:.1f}GB RAM"
        except ImportError:
            pass

        reg_url = f"{coord_url.rstrip('/')}/api/node/register"
        data    = json.dumps({"hardware_info": hardware, "model_name": MODEL_KEY}).encode()
        req     = urllib.request.Request(
            reg_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())

        shard     = result["shard"]
        node_id   = result["node_id"]
        contrib_t = result.get("contributor_token", "")

        print(f"  Registrado — shard asignado: {shard} (node_id: {node_id[:8]}...)")

        if contrib_t:
            config["COGNIA_CONTRIBUTOR_TOKEN"] = contrib_t
            print("  Contributor token guardado.")

        # Use the downloader if available
        shard_dir = SHARDS_DIR / MODEL_KEY
        shard_dir.mkdir(parents=True, exist_ok=True)

        # Check if shard already exists
        if (shard_dir / f"shard_{shard}.npz").exists():
            print(f"  Shard {shard} ya existe localmente.")
            config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
            config["COGNIA_NODE_SHARD"] = str(shard)
            return

        try:
            # Try the built-in downloader
            _root = Path(__file__).parent.parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            from node.downloader import ShardDownloader

            hf_token = _ask("HuggingFace token para descarga (Enter para omitir)", default="")
            dl = ShardDownloader(shard, MODEL_KEY, hf_token)

            def _progress(pct: float, msg: str):
                bar = "#" * int(pct * 30) + "-" * (30 - int(pct * 30))
                print(f"\r  [{bar}] {pct:5.1%} {msg[:40]}", end="", flush=True)

            print(f"\n  Descargando shard {shard}...")
            result_dl = dl.download(on_progress=_progress)
            print()

            if result_dl.ok:
                print(f"  Shard {shard} descargado ({result_dl.size_mb:.0f}MB)")
                config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
                config["COGNIA_NODE_SHARD"] = str(shard)
            else:
                print(f"  [WARN] Descarga fallo: {result_dl.error}")
                print("  El nodo arrancara en modo simulacion hasta que los pesos esten disponibles.")

        except ImportError:
            print("  [WARN] Downloader no disponible. Descarga los pesos manualmente.")

    except Exception as exc:
        print(f"  [WARN] No se pudo registrar con el coordinador: {exc}")
        print("  La configuracion se guardo. El nodo se registrara al arrancar.")


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    """Entry point for `cognia init` command."""
    run_wizard(force=True)


if __name__ == "__main__":
    main()
