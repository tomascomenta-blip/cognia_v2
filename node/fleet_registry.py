r"""
node/fleet_registry.py — Registry N-modelos del FLEET-30 (MoM fase 5)
=====================================================================
Generaliza el patrón heavy_code (singleton lazy + falla cacheada + kill-switch)
a N modelos declarados en un manifest JSON, con presupuesto de RAM y evicción
LRU. Los 3 servers históricos NO pasan por acá (3B fleet :8088, portero :8090,
heavy 7B :8092 siguen en sus módulos, intactos); este registry gestiona SOLO
los miembros nuevos del FLEET-30 (mandato del dueño 2026-07-11).

Manifest (primero que exista):
  1. COGNIA_FLEET30_MANIFEST (env, para tests/overrides)
  2. ~/.cognia/models/fleet30.json (instalación de producto)
  3. <repo>/shattering/manifests/fleet30.json (modo dev)

Formato de entrada del manifest:
  {"members": [{"key": "coder15b", "role": "codigo-rapido",
                "gguf": "ruta/relativa/o/absoluta.gguf", "port": 8093,
                "ctx": 4096, "ram_gb": 1.2, "template": "chatml",
                "lora": null}, ...]}
  - "gguf" relativa se resuelve contra el dir del manifest (portable).
  - "port" fijo por entrada (evita adopción de un server equivocado).
  - "ram_gb" = estimación (tamaño GGUF + KV) para el presupuesto.

Política de RAM (medida en el i3 ~12GB: 3B+0.5B+7B = 7.8GB pico):
  presupuesto COGNIA_FLEET_RAM_GB (default 3.0 GB) SOLO para los servers de
  este registry — el trío histórico ya consume lo suyo por fuera. Antes de
  arrancar un modelo que no entra, se evicta el menos recientemente usado.

Kill-switch: COGNIA_FLEET30=0 apaga todo el registry (fleet_backend → None).

Auto-verificación REAL:  venv312\Scripts\python.exe -m node.fleet_registry <key>
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from node.llama_backend import _LlamaServerBackend

logger = logging.getLogger(__name__)

_RAM_BUDGET_GB_DEFAULT = 3.0

# Templates de prompt por familia (el .generate() del backend recibe prompt
# crudo; cada familia formatea distinto). Concreto: format-strings, no clases.
PROMPT_TEMPLATES = {
    "chatml": ("<|im_start|>system\n{system}<|im_end|>\n"
               "<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"),
    # Gemma no tiene rol system: se antepone al turno de usuario (doc oficial).
    "gemma": ("<start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n"
              "<start_of_turn>model\n"),
    "llama3": ("<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
               "<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\n"),
    # Phi-4 family
    "phi": ("<|system|>{system}<|end|><|user|>{user}<|end|><|assistant|>"),
}

# Estado del registry: singletons por key + fallas cacheadas + orden LRU.
_SERVERS: dict = {}          # key -> _LlamaServerBackend
_FAILED: set = set()         # keys cuyo arranque falló (no reintentar)
_LRU: list = []              # keys en orden de uso (último = más reciente)
_MANIFEST_CACHE: Optional[dict] = None


def _habilitado() -> bool:
    return os.environ.get("COGNIA_FLEET30", "").strip().lower() not in (
        "0", "off", "false", "no")


def _ram_budget_gb() -> float:
    try:
        return float(os.environ.get("COGNIA_FLEET_RAM_GB", "") or
                     _RAM_BUDGET_GB_DEFAULT)
    except ValueError:
        return _RAM_BUDGET_GB_DEFAULT


def _manifest_path() -> Optional[Path]:
    env = os.environ.get("COGNIA_FLEET30_MANIFEST", "").strip()
    if env and Path(env).is_file():
        return Path(env)
    home = Path.home() / ".cognia" / "models" / "fleet30.json"
    if home.is_file():
        return home
    repo = Path(__file__).resolve().parent.parent / "shattering" / "manifests" / "fleet30.json"
    if repo.is_file():
        return repo
    return None


def load_manifest(force: bool = False) -> dict:
    """Manifest del FLEET-30 como dict {key: entrada} (gguf ya resuelto a Path
    absoluto). Cacheado; force=True relee (tests / tras instalar un modelo)."""
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None and not force:
        return _MANIFEST_CACHE
    path = _manifest_path()
    members: dict = {}
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for m in data.get("members", []):
                key = m.get("key")
                gguf = m.get("gguf", "")
                if not key or not gguf:
                    continue
                g = Path(gguf)
                if not g.is_absolute():
                    g = path.parent / g
                m = dict(m, gguf=g)
                members[key] = m
        except Exception as exc:
            logger.warning("[fleet_registry] manifest ilegible %s (%s)", path, exc)
    _MANIFEST_CACHE = members
    return members


def _ram_en_uso_gb() -> float:
    manifest = load_manifest()
    return sum(float(manifest.get(k, {}).get("ram_gb", 1.0))
               for k in _SERVERS)


def _evict_hasta_que_entre(ram_gb: float) -> None:
    """Para servers LRU hasta que `ram_gb` entre en el presupuesto."""
    budget = _ram_budget_gb()
    while _SERVERS and _ram_en_uso_gb() + ram_gb > budget:
        victima = _LRU[0] if _LRU else next(iter(_SERVERS))
        logger.info("[fleet_registry] evict LRU '%s' (presupuesto %.1fGB)",
                    victima, budget)
        close_fleet_member(victima)


def _touch_lru(key: str) -> None:
    if key in _LRU:
        _LRU.remove(key)
    _LRU.append(key)


def fleet_backend(key: str) -> Optional[_LlamaServerBackend]:
    """Backend del miembro `key` del FLEET-30, o None (caller cae a su fallback,
    normalmente el 3B). Singleton lazy por key; falla cacheada; RAM-aware:
    si el modelo no entra en el presupuesto se evicta el LRU primero."""
    if not _habilitado():
        return None
    if key in _SERVERS:
        _touch_lru(key)
        return _SERVERS[key]
    if key in _FAILED:
        return None
    entry = load_manifest().get(key)
    if entry is None:
        logger.warning("[fleet_registry] key desconocida '%s' (no está en el "
                       "manifest fleet30.json)", key)
        _FAILED.add(key)
        return None
    gguf: Path = entry["gguf"]
    if not gguf.is_file():
        logger.warning("[fleet_registry] GGUF de '%s' no existe: %s (instalá "
                       "con: cognia install-model --fleet30 %s)", key, gguf, key)
        _FAILED.add(key)
        return None
    ram = float(entry.get("ram_gb", 1.0))
    if ram > _ram_budget_gb():
        logger.warning("[fleet_registry] '%s' (%.1fGB) excede el presupuesto "
                       "total %.1fGB; no se arranca", key, ram, _ram_budget_gb())
        _FAILED.add(key)
        return None
    _evict_hasta_que_entre(ram)
    lora = entry.get("lora")
    try:
        backend = _LlamaServerBackend(
            gguf,
            port=int(entry.get("port", 8093)),
            ctx_size=int(entry.get("ctx", 4096)),
            lora_path=Path(lora) if lora else None,
        )
    except Exception as exc:
        logger.warning("[fleet_registry] '%s' no arrancó (%s); fallback al "
                       "camino base", key, exc)
        _FAILED.add(key)
        return None
    _SERVERS[key] = backend
    _touch_lru(key)
    return backend


def format_prompt(key: str, system: str, user: str) -> str:
    """Prompt crudo para `key` según su template de familia (default chatml)."""
    entry = load_manifest().get(key) or {}
    tpl = PROMPT_TEMPLATES.get(entry.get("template", "chatml"),
                               PROMPT_TEMPLATES["chatml"])
    return tpl.format(system=system, user=user)


def close_fleet_member(key: str) -> None:
    """Para el server de `key` y libera su RAM. No-op si no corre."""
    backend = _SERVERS.pop(key, None)
    if key in _LRU:
        _LRU.remove(key)
    if backend is None:
        return
    try:
        backend.stop()
    except Exception:
        pass


def close_fleet30() -> None:
    """Para TODOS los servers del registry (cierre de sesión / tests)."""
    for key in list(_SERVERS):
        close_fleet_member(key)


def reset_failures() -> None:
    """Limpia las fallas cacheadas (tras instalar un GGUF que faltaba)."""
    _FAILED.clear()


def _self_check(key: str) -> int:
    """Verificación REAL: arranca `key`, genera y cierra."""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    b = fleet_backend(key)
    if b is None:
        print(f"CHECK FALLO: fleet_backend('{key}') devolvió None "
              f"(manifest: {_manifest_path()})")
        return 1
    try:
        prompt = format_prompt(key, "Eres un asistente util.",
                               "Responde SOLO con la palabra: hola")
        txt = (b.generate(prompt, max_tokens=16, temperature=0.0) or "").strip()
        ok = bool(txt)
        print(f"CHECK [{'OK' if ok else 'FALLO'}] '{key}' genero: {txt[:80]!r}")
        return 0 if ok else 1
    finally:
        close_fleet30()
        print("[fleet_registry] servers cerrados (RAM liberada)")


if __name__ == "__main__":
    import sys
    sys.exit(_self_check(sys.argv[1] if len(sys.argv) > 1 else "coder15b"))
