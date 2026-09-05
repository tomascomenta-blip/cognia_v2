# -*- coding: utf-8 -*-
"""Estimación de tokens FIABLE para el contexto activo.

Auditoría 2026-09-04 (`scratchpad/auditoria_memoria/02_contexto.md` §6): el
arnés contaba chars/4 en todas partes y el tokenizer real del Qwen3.8-27B da
3,71 chars/token de media, 2,5 en salidas de tools con números de línea y JSON:
la compactación disparaba con 55–63k reales cuando creía 51,6k.

Tres fuentes, de más a menos exacta, todas con la misma moneda:
1. `usage.prompt_tokens` del server tras cada respuesta → `calibrar()` ajusta
   la ratio chars/token con una media móvil (la ratio real de ESTA tarea).
2. `/tokenize` del backend (`exacto()`), con caché por sha1 y timeout corto:
   se usa para dimensionar el bloque reconstruido, no en cada mensaje.
3. Ratios por clase (prosa 3.7, tool 3.0, json 2.9) para el estimado por
   mensaje, corregidas por la calibración de (1).
Nunca lanza; sin server, (2) devuelve None y manda (3).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from collections import OrderedDict

RATIOS = {"prosa": 3.7, "tool": 3.0, "json": 2.9, "codigo": 2.7}
_CACHE_MAX = 512


def url_backend() -> str:
    for var in ("COGNIA_LLM_URL", "LLAMA_SERVER_URL"):
        v = os.environ.get(var, "").strip()
        if v:
            return v.rstrip("/")
    return "http://127.0.0.1:8080"


class Estimador:
    def __init__(self, url: str | None = None, factor: float = 1.0):
        self.url = url or url_backend()
        self.factor = float(factor)          # multiplicador calibrado sobre RATIOS
        self._cache: OrderedDict[str, int] = OrderedDict()
        self._tokenize_roto = False
        self.calibraciones = 0

    # ── estimación por clase ────────────────────────────────────────────────
    def texto(self, s, clase: str = "prosa") -> int:
        if not s:
            return 0
        ratio = RATIOS.get(clase, RATIOS["prosa"]) * self.factor
        return int(len(str(s)) / max(ratio, 1.0)) + 1

    def mensaje(self, m: dict) -> int:
        rol = m.get("role") or ""
        clase = "tool" if rol == "tool" else "prosa"
        t = self.texto(m.get("content"), clase) + self.texto(m.get("reasoning_content"), "prosa")
        for tc in (m.get("tool_calls") or ()):
            f = tc.get("function") if isinstance(tc, dict) else None
            if isinstance(f, dict):
                t += self.texto(f.get("arguments"), "json") + 8
        return t + 4          # tokens de plantilla por turno (role, separadores)

    def mensajes(self, mensajes, peso_schemas: int = 0) -> int:
        return sum(self.mensaje(m) for m in (mensajes or ())) + int(peso_schemas or 0)

    # ── calibración con el usage real ───────────────────────────────────────
    def calibrar(self, mensajes, prompt_tokens_real: int, peso_schemas: int = 0) -> float | None:
        """Ajusta `factor` con el prompt_tokens REAL del server para estos mensajes."""
        try:
            real = int(prompt_tokens_real or 0) - int(peso_schemas or 0)
            if real <= 200:
                return None
            estimado = self.mensajes(mensajes, 0)
            if estimado <= 0:
                return None
            nuevo = self.factor * (estimado / real)    # si estimé de más, factor sube (más chars por token)
            nuevo = min(2.0, max(0.5, nuevo))
            self.factor = 0.5 * self.factor + 0.5 * nuevo
            self.calibraciones += 1
            return self.factor
        except Exception:
            return None

    # ── exacto por /tokenize ────────────────────────────────────────────────
    def exacto(self, s: str, timeout: float = 2.0) -> int | None:
        if not s or self._tokenize_roto:
            return None
        clave = hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()
        if clave in self._cache:
            self._cache.move_to_end(clave)
            return self._cache[clave]
        try:
            req = urllib.request.Request(self.url + "/tokenize", data=json.dumps({"content": s}).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                n = len(json.load(r).get("tokens") or [])
        except Exception:
            self._tokenize_roto = True       # no insistir en esta sesión
            return None
        self._cache[clave] = n
        if len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        return n

    def mejor(self, s: str, clase: str = "prosa") -> int:
        """Exacto si el server contesta rápido; si no, estimado."""
        n = self.exacto(s) if len(s or "") < 40000 else None
        return n if n is not None else self.texto(s, clase)


__all__ = ["Estimador", "RATIOS", "url_backend"]
