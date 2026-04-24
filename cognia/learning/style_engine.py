"""
cognia/learning/style_engine.py
================================
StyleEngine -- Fase 6: aprende el estilo de escritura y preferencias del usuario.
Detecta idioma, nivel tecnico, tono y longitud de respuesta preferida de forma autonoma.
"""
from __future__ import annotations
import re, json, time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from logger_config import get_logger
logger = get_logger(__name__)

_TECHNICAL_TERMS = frozenset([
    "api","endpoint","backend","frontend","async","await","thread","proceso","funcion","clase",
    "objeto","variable","algoritmo","database","query","index","vector","embedding","modelo",
    "inference","pipeline","dataset","tensor","gradiente","epoch","batch","protocolo","socket",
    "request","response","token","cifrado","hash","clave","encriptar","deploy","docker",
    "container","nodo","cluster","latencia","throughput","memoria","cpu","gpu","ram",
])
_CASUAL_MARKERS = frozenset([
    "bueno","pues","o sea","digamos","tipo","igual","ok","oye","mira","dale","chevere",
    "ahi","ya","listo","venga","claro","okey","hey","nah","exacto","genial","cool",
])
_FORMAL_MARKERS = frozenset([
    "por favor","podria","seria posible","le agradezco","en consecuencia","no obstante",
    "sin embargo","ademas","asimismo","por consiguiente","segun","mediante","cabe destacar",
])
_LANG_HINTS = {
    "es": frozenset(["el","la","los","las","un","una","que","de","en","es","por"]),
    "en": frozenset(["the","is","are","was","were","have","has","do","does","it"]),
    "pt": frozenset(["o","a","os","as","um","uma","que","de","em","para","com"]),
    "fr": frozenset(["le","la","les","un","une","que","de","en","est","pour"]),
    "de": frozenset(["der","die","das","ein","eine","und","ist","fur","mit","von"]),
}

@dataclass
class StyleHint:
    language:         str   = "es"
    technical_level:  float = 0.5
    preferred_length: str   = "medium"
    tone:             str   = "neutral"
    top_domains:      list  = field(default_factory=list)

    def to_prompt_instruction(self) -> str:
        parts = []
        if self.tone == "casual":
            parts.append("Responde de forma cercana y conversacional.")
        elif self.tone == "formal":
            parts.append("Responde de forma formal y precisa.")
        if self.technical_level > 0.7:
            parts.append("El usuario es tecnico, usa terminologia especializada.")
        elif self.technical_level < 0.3:
            parts.append("El usuario prefiere explicaciones simples.")
        if self.preferred_length == "short":
            parts.append("Responde concisamente, maximo 2-3 oraciones.")
        elif self.preferred_length == "long":
            parts.append("El usuario aprecia respuestas detalladas.")
        if self.top_domains:
            parts.append(f"El usuario tiene interes en: {', '.join(self.top_domains[:3])}.")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {"language": self.language, "technical_level": self.technical_level,
                "preferred_length": self.preferred_length, "tone": self.tone,
                "top_domains": self.top_domains}

    @classmethod
    def from_dict(cls, d: dict) -> "StyleHint":
        return cls(language=d.get("language","es"),
                   technical_level=float(d.get("technical_level",0.5)),
                   preferred_length=d.get("preferred_length","medium"),
                   tone=d.get("tone","neutral"),
                   top_domains=list(d.get("top_domains",[])))


class StyleEngine:
    WINDOW = 50

    def __init__(self, user_id: str = "default"):
        self.user_id     = user_id
        self._messages:  list  = []
        self._word_freq: Counter = Counter()
        self._hint:      StyleHint = StyleHint()

    def observe(self, text: str) -> None:
        if not text or not text.strip(): return
        clean  = text.strip()
        tokens = re.findall(r"\b\w+\b", clean.lower())
        self._messages.append({"text": clean, "length": len(clean), "tokens": len(tokens), "ts": time.time()})
        if len(self._messages) > self.WINDOW:
            self._messages = self._messages[-self.WINDOW:]
        self._word_freq.update(tokens)
        if len(self._messages) % 5 == 0:
            self._recompute()

    def _recompute(self) -> None:
        if not self._messages: return
        words      = set(self._word_freq.keys())
        tech_hits  = len(words & _TECHNICAL_TERMS)
        tech_level = min(1.0, tech_hits / max(len(words), 1) * 8)
        recent_text = " ".join(m["text"].lower() for m in self._messages[-10:])
        casual_hits = sum(1 for m in _CASUAL_MARKERS if m in recent_text)
        formal_hits = sum(1 for m in _FORMAL_MARKERS if m in recent_text)
        if casual_hits > formal_hits + 1: tone = "casual"
        elif formal_hits > casual_hits + 1: tone = "formal"
        else: tone = "neutral"
        avg_tokens = sum(m["tokens"] for m in self._messages) / len(self._messages)
        if avg_tokens < 8: preferred_length = "short"
        elif avg_tokens > 25: preferred_length = "long"
        else: preferred_length = "medium"
        scores = {lang: len(words & hints) for lang, hints in _LANG_HINTS.items()}
        lang   = max(scores, key=scores.get) if any(scores.values()) else "es"
        top_domains = [w for w, _ in self._word_freq.most_common(20) if w in _TECHNICAL_TERMS][:5]
        self._hint = StyleHint(language=lang, technical_level=round(tech_level,3),
                               preferred_length=preferred_length, tone=tone, top_domains=top_domains)

    @property
    def hint(self) -> StyleHint: return self._hint

    def get_prompt_instruction(self) -> str: return self._hint.to_prompt_instruction()

    def stats(self) -> dict:
        return {"messages_observed": len(self._messages), "unique_words": len(self._word_freq),
                "hint": self._hint.to_dict(), "top_words": self._word_freq.most_common(10)}

    def save(self, db_path: str) -> bool:
        import datetime
        key = f"style_engine:{self.user_id}"
        value = json.dumps({"user_id": self.user_id, "messages": self._messages[-self.WINDOW:],
                            "word_freq": dict(self._word_freq.most_common(500)), "hint": self._hint.to_dict()})
        now = datetime.datetime.now().isoformat()
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(db_path)
            conn.execute("""INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, value, now))
            conn.close()
            return True
        except Exception as exc:
            logger.warning("StyleEngine.save error: %s", exc)
            return False

    @classmethod
    def load(cls, user_id: str, db_path: str) -> "StyleEngine":
        key = f"style_engine:{user_id}"
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(db_path)
            row = conn.execute("SELECT value FROM user_profile WHERE key=?", (key,)).fetchone()
            conn.close()
            if row and row[0]:
                data   = json.loads(row[0])
                engine = cls(user_id=user_id)
                engine._messages  = list(data.get("messages", []))
                engine._word_freq = Counter(data.get("word_freq", {}))
                engine._hint      = StyleHint.from_dict(data.get("hint", {}))
                return engine
        except Exception as exc:
            logger.warning("StyleEngine.load error: %s", exc)
        return cls(user_id=user_id)
