"""
cognia_setup.py — Setup engine for Cognia Desktop.

Modes:
  --mode cli   Human-readable output to terminal.
  --mode ipc   Newline-delimited JSON on stdout (consumed by Electron via spawn).
  --check      Exit 0 if setup is complete, exit 1 otherwise.

Shard strategy:
  local mode  — downloads all 4 shards; this machine runs inference end-to-end.
  swarm mode  — registers with coordinator, gets 1 shard assigned, downloads only that.
"""

import argparse
import json
import platform
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

HF_BASE = (
    "https://huggingface.co/datasets/Acua124298042/cognia-shards/resolve/main"
)
N_SHARDS = 4
SETUP_DONE_MARKER = "COGNIA_SETUP_DONE=1"


@dataclass
class PhaseResult:
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)


# ── Emitter ───────────────────────────────────────────────────────────────────

def make_emitter(mode: str) -> Callable:
    def emit(obj: dict) -> None:
        if mode == "ipc":
            print(json.dumps(obj), flush=True)
        else:
            phase  = obj.get("phase", "")
            status = obj.get("status", "")
            detail = obj.get("detail", "")
            shard  = obj.get("shard")
            done   = obj.get("bytes_done")
            total  = obj.get("bytes_total")

            if status == "progress" and done is not None and total and total > 0:
                pct = int(done / total * 100)
                bar = ("=" * (pct // 5)).ljust(20)
                label = f"shard {shard}" if shard is not None else ""
                print(f"\r  [{bar}] {pct}%  {label}", end="", flush=True)
                return
            if status == "progress":
                return

            prefix = "[ok]  " if status == "ok" else \
                     "[--]  " if status in ("running", "skip") else \
                     "[!!]  "
            parts = [phase]
            if shard is not None:
                parts.append(f"shard {shard}")
            if detail:
                parts.append(detail)
            print(f"{prefix}{' / '.join(parts)}")

    return emit


# ── Phase functions ────────────────────────────────────────────────────────────

def check_python(emit: Callable) -> PhaseResult:
    vi = sys.version_info
    if vi < (3, 11):
        detail = (
            f"Python 3.11+ requerido, encontrado {vi.major}.{vi.minor}. "
            "Instalalo desde https://python.org/downloads"
        )
        emit({"phase": "check_python", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)

    emit({"phase": "check_python", "status": "ok",
          "detail": f"{vi.major}.{vi.minor}.{vi.micro}"})
    return PhaseResult(ok=True)


def install_deps(root: Path, emit: Callable) -> PhaseResult:
    emit({"phase": "install_deps", "status": "running", "detail": ""})
    req_file = root / "requirements.txt"
    if not req_file.exists():
        emit({"phase": "install_deps", "status": "error",
              "detail": f"requirements.txt no encontrado en {root}", "fatal": True})
        return PhaseResult(ok=False, detail="requirements.txt missing")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[:200]
        emit({"phase": "install_deps", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)

    emit({"phase": "install_deps", "status": "ok", "detail": ""})
    return PhaseResult(ok=True)


def generate_keys(
    env_path: Path,
    coordinator_url: str,
    shards_dir: Path,
    is_local: bool,
    emit: Callable,
) -> PhaseResult:
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    updates: dict[str, str] = {
        "COGNIA_ADMIN_KEY":       existing.get("COGNIA_ADMIN_KEY") or secrets.token_hex(32),
        "COGNIA_COORDINATOR_URL": coordinator_url,
        "COGNIA_NODE_MODE":       "swarm",
        "SHARD_WEIGHTS_DIR":      str(shards_dir),
        "COGNIA_SWARM_MODEL":     "qwen-coder-3b-q4",
        "COGNIA_DESKTOP_PORT":    "8765",
    }

    # COORDINATOR_KEY is only meaningful when running the coordinator locally
    if is_local:
        updates["COORDINATOR_KEY"] = existing.get("COORDINATOR_KEY") or secrets.token_hex(32)

    existing.update(updates)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in existing.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    emit({"phase": "generate_keys", "status": "ok", "detail": ""})
    emit({"phase": "write_env", "status": "ok", "detail": str(env_path)})
    return PhaseResult(ok=True)


def register_with_coordinator(
    coordinator_url: str,
    env_path: Path,
    emit: Callable,
) -> PhaseResult:
    """Register this node with the coordinator and get a shard assignment."""
    emit({"phase": "register_node", "status": "running", "detail": ""})

    hardware_info = f"{platform.processor()} | {_ram_gb():.1f}GB RAM"
    payload = json.dumps({
        "hardware_info": hardware_info,
        "model_name": "qwen-coder-3b-q4",
    }).encode()

    url = f"{coordinator_url.rstrip('/')}/api/node/register"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        detail = f"No se pudo conectar al coordinador: {exc.reason}"
        emit({"phase": "register_node", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)
    except Exception as exc:
        detail = str(exc)
        emit({"phase": "register_node", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)

    node_id = body.get("node_id") or body.get("id")
    shard   = body.get("shard")

    if node_id is None or shard is None:
        detail = f"Respuesta inesperada del coordinador: {body}"
        emit({"phase": "register_node", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)

    # Persist node identity so heartbeat can reuse it across restarts
    _append_env(env_path, {
        "COGNIA_NODE_ID":    str(node_id),
        "COGNIA_NODE_SHARD": str(shard),
    })

    emit({"phase": "register_node", "status": "ok",
          "detail": f"shard {shard} asignado", "shard": shard})
    return PhaseResult(ok=True, data={"shard": shard, "node_id": node_id})


def download_shards(
    shards_dir: Path,
    shard_indices: List[int],
    emit: Callable,
) -> PhaseResult:
    shards_dir.mkdir(parents=True, exist_ok=True)

    for i in shard_indices:
        dest = shards_dir / f"shard_{i}.npz"
        if dest.exists() and dest.stat().st_size > 0:
            emit({"phase": "download_shards", "status": "skip", "shard": i})
            continue

        url = f"{HF_BASE}/shard_{i}.npz"
        tmp = dest.with_suffix(".part")

        def make_hook(shard_idx: int) -> Callable:
            def hook(count: int, block_size: int, total_size: int) -> None:
                emit({
                    "phase": "download_shards",
                    "status": "progress",
                    "shard": shard_idx,
                    "bytes_done": count * block_size,
                    "bytes_total": total_size if total_size > 0 else 0,
                })
            return hook

        try:
            urllib.request.urlretrieve(url, str(tmp), reporthook=make_hook(i))
            tmp.rename(dest)
            emit({"phase": "download_shards", "status": "ok", "shard": i})
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            detail = str(exc)
            emit({"phase": "download_shards", "status": "error",
                  "shard": i, "detail": detail, "fatal": False})
            return PhaseResult(ok=False, detail=detail)

    # Download tokenizer.json alongside shards so local BPE works without network
    tok_dest = shards_dir / "tokenizer.json"
    if not tok_dest.exists():
        tok_url = "https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct/resolve/main/tokenizer.json"
        tok_tmp = tok_dest.with_suffix(".part")
        try:
            urllib.request.urlretrieve(tok_url, str(tok_tmp))
            tok_tmp.rename(tok_dest)
        except Exception:
            if tok_tmp.exists():
                tok_tmp.unlink()
            # Non-fatal: inference falls back to HF tokenizer

    return PhaseResult(ok=True)


def verify_shards(
    shards_dir: Path,
    shard_indices: List[int],
    emit: Callable,
) -> PhaseResult:
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        emit({"phase": "verify_shards", "status": "error",
              "detail": "numpy no instalado", "fatal": True})
        return PhaseResult(ok=False, detail="numpy missing")

    missing = []
    for i in shard_indices:
        path = shards_dir / f"shard_{i}.npz"
        if not path.exists():
            missing.append(i)
            continue
        try:
            arr = np.load(str(path), allow_pickle=False)
            if len(arr.files) == 0:
                missing.append(i)
        except Exception:
            missing.append(i)

    if missing:
        detail = f"Shards faltantes o corruptos: {missing}"
        emit({"phase": "verify_shards", "status": "error",
              "detail": detail, "fatal": True})
        return PhaseResult(ok=False, detail=detail)

    emit({"phase": "verify_shards", "status": "ok",
          "detail": f"{len(shard_indices)}/{N_SHARDS} shards verificados"})
    return PhaseResult(ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ram_gb() -> float:
    try:
        import os
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / (1024 ** 2)
    except Exception:
        pass
    return 0.0


def _append_env(env_path: Path, kv: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(kv)
    env_path.write_text(
        "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n",
        encoding="utf-8",
    )


def _mark_done(env_path: Path) -> None:
    _append_env(env_path, {"COGNIA_SETUP_DONE": "1"})


# ── Setup complete check ───────────────────────────────────────────────────────

def is_setup_complete(env_path: Path) -> bool:
    if not env_path.exists():
        return False
    content = env_path.read_text(encoding="utf-8")
    return any(line.strip() == SETUP_DONE_MARKER for line in content.splitlines())


# ── Main orchestrator ──────────────────────────────────────────────────────────

def run_setup(
    mode: str,
    coordinator: str,
    shards_dir: Path,
    env_path: Path,
) -> int:
    emit = make_emitter(mode)
    root = Path(__file__).resolve().parent.parent
    is_local = coordinator == "local"
    coordinator_url = "http://localhost:8001" if is_local else coordinator

    # Phases 1-3: always the same
    for phase_fn in [
        lambda: check_python(emit),
        lambda: install_deps(root, emit),
        lambda: generate_keys(env_path, coordinator_url, shards_dir, is_local, emit),
    ]:
        result = phase_fn()
        if not result.ok:
            return 1

    if is_local:
        # Local mode: this machine runs all 4 shards sequentially
        shard_indices = list(range(N_SHARDS))
        emit({"phase": "download_shards", "status": "info",
              "detail": "modo local — descargando los 4 shards"})
    else:
        # Swarm mode: get shard assignment from coordinator, download only that one
        reg = register_with_coordinator(coordinator_url, env_path, emit)
        if not reg.ok:
            return 1
        shard_indices = [reg.data["shard"]]

    for phase_fn in [
        lambda: download_shards(shards_dir, shard_indices, emit),
        lambda: verify_shards(shards_dir, shard_indices, emit),
    ]:
        result = phase_fn()
        if not result.ok:
            return 1

    _mark_done(env_path)
    emit({"phase": "done", "status": "ok", "detail": ""})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Cognia setup engine")
    parser.add_argument("--mode", choices=["cli", "ipc"], default="cli")
    parser.add_argument("--coordinator", default="local",
                        help="'local' or a coordinator URL")
    parser.add_argument("--shards-dir", type=Path, default=None)
    parser.add_argument("--env-path",   type=Path, default=None)
    parser.add_argument("--check", action="store_true",
                        help="Exit 0 if setup is complete, 1 otherwise")
    args = parser.parse_args()

    default_data = Path.home() / ".cognia"
    shards_dir = args.shards_dir or (default_data / "shards" / "qwen-coder-3b-q4")
    env_path   = args.env_path   or (default_data / ".env")

    if args.check:
        sys.exit(0 if is_setup_complete(env_path) else 1)

    sys.exit(run_setup(args.mode, args.coordinator, shards_dir, env_path))


if __name__ == "__main__":
    main()
