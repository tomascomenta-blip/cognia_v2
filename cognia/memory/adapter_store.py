"""
cognia/memory/adapter_store.py
==============================
LRU file-backed store for per-user ELC adapters (node/local_adapter.py).
Max 5 adapters in memory (LRU eviction); max 50 MB per adapter on disk.
Path traversal prevented via pathlib.is_relative_to.
"""

from __future__ import annotations

import pathlib
from collections import OrderedDict
from typing import Optional

_MAX_ADAPTERS = 5
_MAX_BYTES    = 50 * 1024 * 1024  # 50 MB


class AdapterStore:
    """
    Lazy-loaded LRU cache for LoRAAdapter objects.
    Disk layout: {base_dir}/{sanitized_user_id}.npz
    Memory eviction removes only the in-memory entry; disk file is kept.
    """

    def __init__(self, base_dir: str = "model_shards/adapters"):
        self._base  = pathlib.Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict = OrderedDict()

    def _safe_path(self, user_id: str) -> pathlib.Path:
        safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in user_id)
        p    = (self._base / f"{safe}.npz").resolve()
        if not p.is_relative_to(self._base):
            raise ValueError(f"Invalid user_id: {user_id!r}")
        return p

    def get(self, user_id: str) -> Optional[object]:
        """Returns LoRAAdapter from cache or disk, or None if not present."""
        if user_id in self._cache:
            self._cache.move_to_end(user_id)
            return self._cache[user_id]
        p = self._safe_path(user_id)
        if not p.exists():
            return None
        try:
            from node.local_adapter import LoRAAdapter
            adapter = LoRAAdapter.load(str(p))
            self._insert(user_id, adapter)
            return adapter
        except Exception:
            return None

    def put(self, user_id: str, adapter: object) -> bool:
        """Saves adapter to disk and caches it. Returns False if over size limit."""
        if adapter.size_bytes() > _MAX_BYTES:
            return False
        p = self._safe_path(user_id)
        try:
            adapter.save(str(p))
        except Exception:
            return False
        self._insert(user_id, adapter)
        return True

    def _insert(self, user_id: str, adapter: object) -> None:
        if user_id in self._cache:
            self._cache.move_to_end(user_id)
        else:
            self._cache[user_id] = adapter
            if len(self._cache) > _MAX_ADAPTERS:
                self._cache.popitem(last=False)  # evict oldest; disk file retained

    def remove(self, user_id: str) -> None:
        """Removes from cache and deletes the disk file."""
        self._cache.pop(user_id, None)
        try:
            self._safe_path(user_id).unlink(missing_ok=True)
        except Exception:
            pass
