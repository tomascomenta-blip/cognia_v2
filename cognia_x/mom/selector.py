"""Selector del MoM — router n-grams de caracteres (ganador X4: 96.7% acc, ≈oracle en 2/3
dominios, <5ms CPU) con umbral de confianza y fallback al generalista.

X4 midió que el especialista fuera de nicho se derrumba (+0.9..+3.5 bpb): el costo de rutear
mal es asimétrico, por eso bajo ambigüedad se cae al generalista (nunca a otro experto)."""
import json
import re
from collections import Counter

TOP_GRAMS = 400
NGRAM = 3


def tri_profile(text, k=NGRAM, top=TOP_GRAMS):
    """Perfil de frecuencias de trigramas de caracteres (se persiste en el manifest)."""
    t = re.sub(r"\s+", " ", text.lower())
    c = Counter(t[i:i + k] for i in range(len(t) - k))
    tot = sum(c.values()) or 1
    return {g: n / tot for g, n in c.most_common(top)}


class Selector:
    def __init__(self, profiles, threshold=0.45, fallback="gen"):
        """profiles: {dominio: {trigram: freq}}. threshold: si el posterior máximo no llega,
        se rutea al fallback (asimetría medida en X4)."""
        self.profiles = profiles
        self.threshold = threshold
        self.fallback = fallback

    def posterior(self, text, k=NGRAM):
        t = re.sub(r"\s+", " ", text.lower())
        if len(t) < k + 1:
            return {d: 1.0 / len(self.profiles) for d in self.profiles}
        scores = {}
        for d, p in self.profiles.items():
            scores[d] = sum(p.get(t[i:i + k], 0.0) for i in range(len(t) - k)) / (len(t) - k)
        tot = sum(scores.values())
        if tot <= 0:
            return {d: 1.0 / len(self.profiles) for d in self.profiles}
        return {d: s / tot for d, s in scores.items()}

    def select(self, text):
        """→ (destino, posterior). destino = dominio ganador o fallback si hay ambigüedad."""
        post = self.posterior(text)
        best = max(post, key=post.get)
        if post[best] < self.threshold:
            return self.fallback, post
        return best, post

    def to_dict(self):
        return {"profiles": self.profiles, "threshold": self.threshold,
                "fallback": self.fallback}

    @classmethod
    def from_dict(cls, d):
        return cls(d["profiles"], d.get("threshold", 0.45), d.get("fallback", "gen"))

    @classmethod
    def from_texts(cls, dom_texts, threshold=0.45, fallback="gen"):
        return cls({d: tri_profile(t) for d, t in dom_texts.items()}, threshold, fallback)


def eval_selector(selector, dom_texts, chunk=400, max_chunks=40):
    """Accuracy del ruteo + tasa de fallback sobre trozos held-out (por dominio)."""
    ok = tot = fb = 0
    per_dom = {}
    for d, text in dom_texts.items():
        k = n = 0
        for i in range(0, min(len(text) - chunk, max_chunks * chunk), chunk):
            dest, _ = selector.select(text[i:i + chunk])
            if dest == selector.fallback:
                fb += 1
            k += int(dest == d)
            n += 1
        per_dom[d] = round(k / max(1, n), 4)
        ok += k
        tot += n
    return {"acc": round(ok / max(1, tot), 4), "fallback_rate": round(fb / max(1, tot), 4),
            "per_dom": per_dom, "n": tot}


def save_selector(selector, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(selector.to_dict(), f, ensure_ascii=False)


def load_selector(path):
    with open(path, encoding="utf-8") as f:
        return Selector.from_dict(json.load(f))
