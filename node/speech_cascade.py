r"""
node/speech_cascade.py — Cascada de habla (F-SPEED, exp021/cycle34/37)
=====================================================================
Para "hablar a velocidad alta": un 0.5B rápido (~28-36 tok/s, 4.3× el 3B en el i3
bandwidth-bound) atiende los turnos SOCIALES/triviales (saludos, charla corta,
backchannel); todo lo SUSTANTIVO escala al 3B (calidad). El 0.5B es fluido pero poco
fiable en hechos (exp021), por eso classify_turn() es CONSERVADOR: ante la duda → 3B.

Opt-in: COGNIA_SPEECH_CASCADE=1 (default OFF → el chat usa el 3B de siempre, sin cambios).
Reusa _LlamaServerBackend del backend real; NO usa draft model separado (mide 0.37× en
CPU) ni difusión (pierde por banda).

Auto-verificación REAL:  venv312\Scripts\python.exe -m node.speech_cascade
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from node.llama_backend import _LlamaServerBackend

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_FAST_GGUF = _REPO / "model_shards" / "qwen-0.5b-instruct-q4" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_DEEP_GGUF = _REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
_FAST_PORT = int(os.environ.get("COGNIA_CASCADE_FAST_PORT", "8090"))
_DEEP_PORT = int(os.environ.get("COGNIA_CASCADE_DEEP_PORT", "8091"))

_SYS_DEFAULT = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."

# señales de PROFUNDIDAD → 3B (la calidad gana ante la duda; el 0.5B inventa hechos)
_DEEP_RE = re.compile(
    r"\b(por\s?qu[eé]|c[oó]mo\s+funciona|expl[ií]ca\w*|calcul\w*|cu[aá]nto[s]?|qu[eé]\s+es|"
    r"defin\w*|demuestr\w*|resuelv\w*|c[oó]digo|programa\w*|funci[oó]n|algoritmo|compar\w*|"
    r"analiz\w*|diferencia|historia|cu[aá]ndo|d[oó]nde|enumera|lista de|pasos para|traduc\w*)\b",
    re.I)
# señales SOCIALES/triviales → 0.5B (rápido, bajo riesgo)
_SOCIAL_RE = re.compile(
    r"\b(hola|buenos d[ií]as|buenas|qu[eé] tal|c[oó]mo est[aá]s|gracias|adi[oó]s|chau|"
    r"hasta (luego|ma[ñn]ana)|encantado|mucho gusto|s[ií]|no|ok|vale|genial|perfecto|"
    r"jaj\w*|hey|saludos|buenas noches)\b", re.I)


def classify_turn(turn: str) -> str:
    """'fast' (0.5B) para turnos sociales/triviales; 'deep' (3B) para sustancia.
    Conservador: ante la duda → 'deep' (calidad). Ver exp021 (el 0.5B no es fiable en hechos)."""
    t = (turn or "").strip()
    words = len(t.split())
    if _DEEP_RE.search(t):
        return "deep"
    if "?" in t and words > 6:
        return "deep"
    if _SOCIAL_RE.search(t) or words <= 4:
        return "fast"
    return "deep"


def _chatml(turn: str, system: Optional[str]) -> str:
    sys_p = system or _SYS_DEFAULT
    return (f"<|im_start|>system\n{sys_p}<|im_end|>\n<|im_start|>user\n{turn}<|im_end|>\n"
            f"<|im_start|>assistant\n")


class CascadeBackend:
    """Enruta cada turno al 0.5B (social) o al 3B (sustancia). Servers lazy: el deep
    no arranca hasta que llega el 1er turno sustantivo. Una sola generación a la vez."""

    def __init__(self, fast_gguf: Path, deep_gguf: Path) -> None:
        self._fast_gguf = fast_gguf
        self._deep_gguf = deep_gguf
        self._fast: Optional[_LlamaServerBackend] = None
        self._deep: Optional[_LlamaServerBackend] = None
        # telemetría del último generate()
        self.last_route: Optional[str] = None
        self.last_model: Optional[str] = None
        self.last_tok_s: Optional[float] = None

    @classmethod
    def try_load(cls) -> Optional["CascadeBackend"]:
        """Devuelve una CascadeBackend si COGNIA_SPEECH_CASCADE está activo y ambos
        GGUF existen; None si no (el caller hace fallback al backend normal del 3B)."""
        flag = os.environ.get("COGNIA_SPEECH_CASCADE", "").strip().lower()
        if flag not in ("1", "true", "on", "yes"):
            return None
        if not (_FAST_GGUF.is_file() and _DEEP_GGUF.is_file()):
            logger.warning("[speech_cascade] COGNIA_SPEECH_CASCADE activo pero falta un GGUF "
                           "(%s / %s); cascada deshabilitada", _FAST_GGUF.name, _DEEP_GGUF.name)
            return None
        return cls(_FAST_GGUF, _DEEP_GGUF)

    def _backend(self, route: str) -> _LlamaServerBackend:
        if route == "fast":
            if self._fast is None:
                self._fast = _LlamaServerBackend(self._fast_gguf, port=_FAST_PORT)
            return self._fast
        if self._deep is None:
            self._deep = _LlamaServerBackend(self._deep_gguf, port=_DEEP_PORT)
        return self._deep

    def generate(self, turn: str, max_tokens: int = 160, temperature: float = 0.7,
                 system: Optional[str] = None) -> Optional[str]:
        route = classify_turn(turn)
        b = self._backend(route)
        t0 = time.time()
        txt = b.generate(_chatml(turn, system), max_tokens=max_tokens, temperature=temperature)
        dt = time.time() - t0
        n = getattr(b, "last_tokens_predicted", None) or 0
        self.last_route = route
        self.last_model = (self._fast_gguf if route == "fast" else self._deep_gguf).name
        self.last_tok_s = round(n / dt, 1) if dt > 0 and n else None
        return txt

    def close(self) -> None:
        for b in (self._fast, self._deep):
            proc = getattr(b, "_proc", None)
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()


# ── Fast-path reutilizable para el chat (reusa el 3B existente como 'deep') ──
_FAST_SINGLETON: Optional[_LlamaServerBackend] = None


def fast_speech_backend() -> Optional[_LlamaServerBackend]:
    """Backend del 0.5B para el fast-path de habla, o None si COGNIA_SPEECH_CASCADE está
    OFF o falta el GGUF. Singleton lazy (arranca el server 0.5B una sola vez). Pensado
    para que un chat que YA tiene el 3B solo añada el 0.5B en turnos sociales
    (classify_turn=='fast'), SIN duplicar el 3B."""
    global _FAST_SINGLETON
    flag = os.environ.get("COGNIA_SPEECH_CASCADE", "").strip().lower()
    if flag not in ("1", "true", "on", "yes"):
        return None
    if not _FAST_GGUF.is_file():
        logger.warning("[speech_cascade] fast-path pedido pero falta %s", _FAST_GGUF.name)
        return None
    if _FAST_SINGLETON is None:
        _FAST_SINGLETON = _LlamaServerBackend(_FAST_GGUF, port=_FAST_PORT)
    return _FAST_SINGLETON


def prewarm_fast_speech() -> None:
    """Si la cascada está ON, arranca y faultea el 0.5B en BACKGROUND (hilo daemon) para
    que el 1er turno social ya esté warm (~30 tok/s en vez de ~18 cold). No bloquea ni
    rompe el arranque del REPL (todo en try/except). OFF → no-op."""
    flag = os.environ.get("COGNIA_SPEECH_CASCADE", "").strip().lower()
    if flag not in ("1", "true", "on", "yes"):
        return
    import threading

    def _warm():
        try:
            fb = fast_speech_backend()
            if fb is not None:
                fb.generate(_chatml("Hola.", None), max_tokens=8, temperature=0.0)
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()


def _self_check() -> int:
    """Verificación REAL: enruta y genera un turno social (→0.5B) y uno sustantivo (→3B)."""
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ["COGNIA_SPEECH_CASCADE"] = "1"
    c = CascadeBackend.try_load()
    if c is None:
        print("CHECK FALLO: try_load() devolvió None (¿faltan GGUF?)")
        return 1
    try:
        for turn, expect in [("Hola, ¿cómo estás?", "fast"),
                             ("¿Por qué el cielo es azul?", "deep")]:
            txt = c.generate(turn, max_tokens=48)
            ok = (c.last_route == expect) and bool(txt and txt.strip())
            print(f"CHECK [{c.last_route} esperado={expect}] ({c.last_tok_s} tok/s, {c.last_model})")
            print(f"   {turn} -> {(txt or '').strip()[:120]}")
            assert ok, f"ruta o salida incorrecta para: {turn}"
        print("CHECK OK: cascada enruta social→0.5B y sustancia→3B, y genera texto real.")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    import sys
    sys.exit(_self_check())
