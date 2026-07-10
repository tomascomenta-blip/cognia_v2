r"""
node/speech_cascade.py — Cascada de habla + PORTERO 0.5B (F-SPEED; PREREG_PORTERO_FASE2)
========================================================================================
Para "hablar a velocidad alta": un 0.5B rápido (~28-36 tok/s, 4.3× el 3B en el i3
bandwidth-bound) atiende los turnos SOCIALES/triviales (saludos, charla corta,
backchannel); todo lo SUSTANTIVO escala al 3B (calidad). El 0.5B es fluido pero poco
fiable en hechos (exp021), por eso classify_turn() es CONSERVADOR: ante la duda → 3B.

Dos modos del fast-path (fast_speech_backend):
  1. PORTERO (default por PRESENCIA): 0.5B + LoRA de identidad
     (`cognia_portero05b_f16.gguf`, E-PORT: G3 0→95%) instalados en
     ~/.cognia/models/qwen-0.5b-portero/ (o PORTERO_GGUF_PATH/PORTERO_LORA_PATH).
     Atiende saludo/cortesía E IDENTIDAD (classify_turn(..., identidad=True)).
     Kill-switch: COGNIA_PORTERO=0. Ante CUALQUIER falla (archivos, arranque,
     server adoptado sin la LoRA) cae al 3B y no reintenta cada turno.
  2. Cascada legado (opt-in COGNIA_SPEECH_CASCADE=1): 0.5B pelado del repo,
     SOLO turnos sociales (sin identidad: la base dice "Qwen").

Reusa _LlamaServerBackend del backend real; NO usa draft model separado (mide 0.37× en
CPU) ni difusión (pierde por banda).

Auto-verificación REAL:  venv312\Scripts\python.exe -m node.speech_cascade
"""
from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

from node.llama_backend import _LlamaServerBackend

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_FAST_GGUF = _REPO / "model_shards" / "qwen-0.5b-instruct-q4" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_DEEP_GGUF = _REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
_FAST_PORT = int(os.environ.get("COGNIA_CASCADE_FAST_PORT", "8090"))
_DEEP_PORT = int(os.environ.get("COGNIA_CASCADE_DEEP_PORT", "8091"))

# Portero (PREREG_PORTERO_FASE2): base 0.5B Q4_K_M + LoRA identidad, instalados
# por `cognia install-model` (convención) o apuntados por env.
_PORTERO_GGUF_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_PORTERO_LORA_FILE = "cognia_portero05b_f16.gguf"
_PORTERO_CTX = int(os.environ.get("PORTERO_CTX_SIZE", "4096"))

_SYS_DEFAULT = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."

# señales de PROFUNDIDAD → 3B (la calidad gana ante la duda; el 0.5B inventa hechos)
_DEEP_RE = re.compile(
    r"\b(por\s?qu[eé]|c[oó]mo\s+funciona|expl[ií]ca\w*|calcul\w*|cu[aá]nto[s]?|qu[eé]\s+es|"
    r"defin\w*|demuestr\w*|resuelv\w*|c[oó]digo|programa\w*|funci[oó]n|algoritmo|compar\w*|"
    r"analiz\w*|diferencia|historia|cu[aá]ndo|d[oó]nde|enumera|lista de|pasos para|traduc\w*)\b",
    re.I)
# señales SOCIALES fuertes → 0.5B por substring (inequívocas en cualquier posición).
# Los acks DÉBILES («sí/no/ok/vale/...») salieron de acá: \bno\b matcheaba
# CUALQUIER prompt con la palabra "no" (p.ej. "escribí un poema que no rime")
# → FP dormido con la cascada OFF; ahora solo cuentan como TURNO COMPLETO.
_SOCIAL_RE = re.compile(
    r"\b(hola|buen(os)? d[ií]as?|buenas(\s+(tardes|noches))?|qu[eé] tal|c[oó]mo est[aá]s|"
    r"gracias|adi[oó]s|chau|hasta (luego|ma[ñn]ana|pronto)|encantad\w*|mucho gusto|"
    r"jaj\w*|hey|saludos|me alegro|qu[eé] bueno|buen[ií]simo)\b",
    re.I)
# acks débiles: SOLO como turno completo (sin puntuación, sin tildes)
_ACKS = {"si", "no", "ok", "okay", "vale", "dale", "listo", "genial", "perfecto",
         "de acuerdo", "entendido", "claro"}

# heurística léxica de inglés para el system del portero (mismo formato que el
# instrumento G3 del kernel: system neutro POR IDIOMA + turno crudo)
_EN_RE = re.compile(
    r"\b(you|your|yourself|who|what|which|are|is|hello|hi|thanks|thank|name)\b", re.I)


def _fold_ack(t: str) -> str:
    """minúsculas + sin tildes + sin puntuación, para el match de turno completo."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                     if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", folded).strip()


def classify_turn(turn: str, identidad: bool = False) -> str:
    """'fast' (0.5B) SOLO para turnos sociales explícitos — y, con identidad=True
    (portero con LoRA instalado), también preguntas de identidad (is_identity_turn,
    cobertura G3 20/20 y 0 FP medidas en GATES_CLI_VNEXT); 'deep' (3B) para todo lo
    demás. Conservador por diseño (precisión > recall): el 0.5B no es fiable en
    hechos (exp021), así que las cortas-pero-sustantivas ('Resume esto', 'Capital
    de Francia?') van al 3B. Antes una regla 'words<=4 → fast' las ruteaba mal al
    0.5B; se quitó (consolidación F-SPEED)."""
    t = (turn or "").strip()
    if not t:
        return "deep"
    if identidad:
        # ANTES de los vetos: hay identidades largas o con señales tipo-deep
        # ("¿qué es Cognia?"); el patrón identidad es preciso (0 FP medido).
        try:
            from cognia.agent.fleet_router import is_identity_turn
            if is_identity_turn(t):
                return "fast"
        except Exception:
            pass
    if len(t) > 80:
        return "deep"
    if _DEEP_RE.search(t):
        return "deep"
    if "?" in t and len(t.split()) > 6:
        return "deep"
    if _SOCIAL_RE.search(t):
        return "fast"
    if _fold_ack(t) in _ACKS:
        return "fast"
    return "deep"


def portero_system(turn: str) -> str:
    """System mínimo del portero, por idioma — el MISMO formato del instrumento
    G3 del kernel (95% medido). Sin personalización: un system largo desalinea
    al 0.5B del instrumento y come el prefill que hace rápido al portero."""
    return ("You are a helpful assistant." if _EN_RE.search(turn or "")
            else "Eres un asistente útil.")


def _chatml(turn: str, system: Optional[str]) -> str:
    sys_p = system or _SYS_DEFAULT
    return (f"<|im_start|>system\n{sys_p}<|im_end|>\n<|im_start|>user\n{turn}<|im_end|>\n"
            f"<|im_start|>assistant\n")


# ── Portero: descubrimiento de archivos ──────────────────────────────────────

def _portero_dir() -> Path:
    try:
        from cognia.first_run import COGNIA_HOME   # stdlib puro, sin ciclos
        return COGNIA_HOME / "models" / "qwen-0.5b-portero"
    except Exception:
        return Path.home() / ".cognia" / "models" / "qwen-0.5b-portero"


def _portero_paths() -> tuple:
    """(gguf, lora) del portero instalado, o (None, None) si falta algo o está
    apagado (COGNIA_PORTERO=0). Ambos archivos deben existir: base sin LoRA
    contestaría como Qwen (identidad rota) → nunca se sirve a medias."""
    if os.environ.get("COGNIA_PORTERO", "").strip().lower() in ("0", "off", "false", "no"):
        return None, None
    g = os.environ.get("PORTERO_GGUF_PATH", "").strip()
    lo = os.environ.get("PORTERO_LORA_PATH", "").strip()
    gp = Path(g) if g else _portero_dir() / _PORTERO_GGUF_FILE
    lp = Path(lo) if lo else gp.parent / _PORTERO_LORA_FILE
    if gp.is_file() and lp.is_file():
        return gp, lp
    return None, None


def portero_activo() -> bool:
    """True si el fast-path es el PORTERO (0.5B+LoRA presente y sin falla previa):
    habilita rutear IDENTIDAD al 0.5B. La cascada legado (sin LoRA) NO califica."""
    if _FAST_FAILED:
        return False
    return _portero_paths()[0] is not None


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
_FAST_FAILED = False   # falla de arranque cacheada: no reintentar cada turno


def fast_speech_backend() -> Optional[_LlamaServerBackend]:
    """Backend del 0.5B para el fast-path de habla, o None (→ el turno va al 3B).

    Prioridad: PORTERO por presencia (0.5B + LoRA identidad, ctx 4096, LoRA
    estática verificada incluso en server adoptado) → cascada legado opt-in
    (COGNIA_SPEECH_CASCADE=1, 0.5B pelado del repo). Singleton lazy; una falla
    de arranque se cachea (_FAST_FAILED) y el chat sigue 100% en el 3B."""
    global _FAST_SINGLETON, _FAST_FAILED
    if _FAST_SINGLETON is not None:
        return _FAST_SINGLETON
    if _FAST_FAILED:
        return None
    gp, lp = _portero_paths()
    if gp is not None:
        try:
            _FAST_SINGLETON = _LlamaServerBackend(
                gp, port=_FAST_PORT, lora_path=lp, ctx_size=_PORTERO_CTX)
            return _FAST_SINGLETON
        except Exception as exc:
            logger.warning("[speech_cascade] portero no arrancó (%s); el chat "
                           "sigue 100%% en el 3B", exc)
            _FAST_FAILED = True
            return None
    flag = os.environ.get("COGNIA_SPEECH_CASCADE", "").strip().lower()
    if flag not in ("1", "true", "on", "yes"):
        return None
    if not _FAST_GGUF.is_file():
        logger.warning("[speech_cascade] fast-path pedido pero falta %s", _FAST_GGUF.name)
        return None
    try:
        _FAST_SINGLETON = _LlamaServerBackend(_FAST_GGUF, port=_FAST_PORT)
    except Exception as exc:
        logger.warning("[speech_cascade] cascada no arrancó (%s)", exc)
        _FAST_FAILED = True
        return None
    return _FAST_SINGLETON


def prewarm_fast_speech() -> None:
    """Si hay fast-path (portero presente o cascada ON), arranca y faultea el 0.5B
    en BACKGROUND (hilo daemon) para que el 1er turno trivial ya esté warm (~30
    tok/s en vez de ~18 cold). No bloquea ni rompe el arranque del REPL (todo en
    try/except). Sin portero y sin flag → no-op."""
    flag = os.environ.get("COGNIA_SPEECH_CASCADE", "").strip().lower()
    if not portero_activo() and flag not in ("1", "true", "on", "yes"):
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
