"""
CYCLE 16 — razonar SIN que te digan el tipo: rutear desde el TEXTO, no desde la etiqueta de tipo.

CYCLE 12–15 le PASABAN al router el `problem["type"]` como label (routeaba sobre la etiqueta). Era una
muleta: razonar de verdad es DARSE CUENTA qué clase de problema tenés enfrente leyendo el enunciado.
Acá la sacamos. El router solo ve `problem["text"]` (el string que ya producen los generadores) y debe
INFERIR cómo razonar.

Cómo (concreto y stdlib):
  1) features(text): extrae señales BARATAS y honestas del texto crudo (palabras clave "propina"/"$/g"/
     "viajes"/"km/h", si hay símbolos de %, $, etc., y cuántos números aparecen). Devuelve un dict.
     NO mira problem["type"] ni problem["answer"] — recibe SOLO el texto. (Auditá: la firma es features(text).)
  2) signature(text): discretiza esas señales en una TUPLA de flags (la "firma" del problema). Problemas del
     mismo tipo caen casi siempre en la misma firma, sin que nadie le haya dicho el tipo.
  3) TextRouter: un bandit por FIRMA (en vez de por tipo). Reusa exactamente la mecánica de CYCLE 12
     (epsilon-greedy + verificador real) pero indexado por signature(text). Así DESCUBRE la estructura de
     tipos a partir del texto y aprende qué cadena usar para cada firma — premiado por el verificador real.

El router base de CYCLE 12 (Router, routea por type) queda intacto y es ahora la REFERENCIA SUPERIOR
("si supiera el tipo"). El titular de CYCLE 16: el TextRouter se ACERCA a ese oráculo-de-tipo SIN que le
digan el tipo -> la brecha (router-de-tipo − router-de-texto) es chica = infirió bien la clase de problema.
"""
import re
from random import Random

from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.problems import is_correct
from cognia_x.reason.router import Router

# palabras clave honestas por familia de problema (se buscan en el TEXTO crudo, sin tocar el tipo).
# WHY: son las pistas que un humano usa para reconocer "ah, esto es una cuenta a dividir / una comparación
# por kilo / un presupuesto / un plazo". No son el tipo: varias podrían co-ocurrir o faltar (de ahí la
# ambigüedad honesta que reportamos).
_KW = {
    "propina": ["propina"],                 # split_bill / split_then_check
    "amigos": ["amigos comen"],             # split_bill / split_then_check
    "por_peso": ["por ", " g.", " g ", "kg"],   # cheaper_per_kg / afford_packs ("$X por N g")
    "paquete": ["paquete a", "paquete b"],  # cheaper_per_kg / afford_packs
    "mas_barato": ["más barato", "conviene"],
    "viajes": ["viaje", "tarjeta"],         # trips_within_budget
    "presupuesto": ["tenés $", "presupuesto"],
    "km_h": ["km/h", "km a "],              # arrive_on_time
    "a_tiempo": ["a tiempo", "llegar", "horas"],
    "descuento": ["descuento", "oferta", "ahorra"],  # discount_better
    "stock": ["stock", "consume", "por día"],        # stock_then_days
    "limite": ["supera", "límite"],                  # split_then_check
    "envio": ["envío"],                              # afford_packs
}

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def features(text):
    """
    Extrae señales BARATAS del texto CRUDO. Recibe SOLO el string del enunciado (jamás el tipo ni la
    respuesta). Devuelve un dict de flags 0/1 por palabra clave + algunos conteos honestos.
    Esta es la ÚNICA fuente de información del TextRouter -> acá se ve que no hay peeking.
    """
    low = text.lower()
    feats = {k: (1 if any(s in low for s in subs) else 0) for k, subs in _KW.items()}
    feats["has_pct"] = 1 if "%" in text else 0
    feats["has_dollar"] = 1 if "$" in text else 0
    feats["has_binary_choice"] = 1 if ("(0=a" in low or "(1=sí" in low or "(1=si" in low) else 0
    n_nums = len(_NUM_RE.findall(text))
    # bucket de cantidad de números (discreto y robusto): pocos / medios / muchos
    feats["nums_bucket"] = 0 if n_nums <= 2 else (1 if n_nums <= 4 else 2)
    return feats


# orden FIJO de las claves para que la firma sea una tupla estable y comparable.
_SIG_KEYS = list(_KW.keys()) + ["has_pct", "has_dollar", "has_binary_choice", "nums_bucket"]


def signature(text):
    """Firma DISCRETA del problema = tupla de los flags de features(text). Es la 'clase' que el router
    descubre por su cuenta (problemas del mismo tipo caen casi siempre en la misma firma)."""
    f = features(text)
    return tuple(f[k] for k in _SIG_KEYS)


# solo las claves de PALABRA (sin los conteos numéricos / $ / %): esta es la "firma de keywords" pura,
# la que la paráfrasis + vocabulario ambiguo ATACAN directamente (CYCLE 17). El control de CYCLE 16
# (signature) mezclaba keywords con buckets numéricos que separan los tipos aun sin vocabulario; al
# aislar las keywords se ve la FRAGILIDAD honesta: sinónimos + distractores las hacen confundir tipos.
_KW_KEYS = list(_KW.keys())


def signature_keywords(text):
    """Firma de KEYWORDS pura: solo los flags de palabras clave de features(text) (sin nums/$/%).
    WHY: es la representación FRÁGIL que CYCLE 17 pone a prueba bajo paráfrasis. Recibe SOLO el texto."""
    f = features(text)
    return tuple(f[k] for k in _KW_KEYS)


def signature_blind(text):
    """
    CONTROL HONESTO (ablación): firma que IGNORA las palabras clave y usa SOLO el conteo de números +
    símbolos $/% . WHY: muestra que si el extractor de features es POBRE (no mira el vocabulario), las
    clases se MEZCLAN, sube la confusión y la brecha se ABRE -> prueba que son las features de texto
    (no la mecánica del bandit) las que recuperan la estructura. Sigue recibiendo SOLO el texto.
    """
    f = features(text)
    return (f["nums_bucket"], f["has_pct"], f["has_dollar"])


class TextRouter:
    """
    Bandit de CYCLE 12 pero indexado por la FIRMA inferida del TEXTO (no por el tipo). Internamente reusa
    Router tal cual, usando la firma como si fuera el "tipo" -> hereda epsilon-greedy + verificador real.
    Nunca lee problem["type"] ni problem["answer"]: solo problem["text"] (vía signature) y, para premiar,
    el verificador real is_correct (que es la realidad, no la etiqueta de tipo).
    """
    def __init__(self, chain_names, eps=0.15, seed=0, graded=False, sig_fn=signature):
        self.inner = Router(chain_names, mode="verifier", eps=eps, seed=seed, graded=graded)
        self.graded = graded
        self.chain_names = list(chain_names)
        self.sig_fn = sig_fn            # cómo discretizar el texto (signature normal o signature_blind para el control)

    def _sig(self, problem):
        return self.sig_fn(problem["text"])   # <- ÚNICA lectura del problema para rutear: el TEXTO

    def train_one(self, problem):
        """Un paso online: firma del texto -> elige cadena -> corre -> premia con el VERIFICADOR real."""
        sig = self._sig(problem)
        chain = self.inner.select(sig)
        pred, _ = self.inner.run_chain(chain, problem)
        reward = 1.0 if is_correct(problem, pred) else 0.0   # realidad, NO la etiqueta de tipo
        self.inner.update(sig, chain, reward)
        return chain, pred

    def select(self, problem):
        """Cadena desplegada para este problema, decidida SOLO por la firma de su texto."""
        return self.inner.select(self._sig(problem))

    def eval(self, problems):
        """Accuracy desplegando (exploración congelada): rutea por texto y corre la cadena elegida."""
        self.inner.explore = False
        ok = 0
        for p in problems:
            chain = self.select(p)
            pred = graded_chain(chain, p)[0] if self.graded else CHAINS[chain](p)[0]
            if is_correct(p, pred):
                ok += 1
        self.inner.explore = True
        return ok / len(problems)

    def signature_to_type_purity(self, problems):
        """
        AUDITORÍA de estructura: ¿la firma inferida del texto se alinea con el tipo verdadero? Para cada
        firma vista, miramos qué tipos cayeron en ella y calculamos la PUREZA (fracción del tipo mayoritario).
        El promedio ponderado = "qué tan bien recuperó la estructura de tipos SOLO desde el texto".
        (Acá SÍ leemos problem["type"], pero solo para EVALUAR la alineación a posteriori — el router nunca
        lo usó para decidir.)
        """
        buckets = {}
        for p in problems:
            sig = self._sig(p)
            buckets.setdefault(sig, {})
            buckets[sig][p["type"]] = buckets[sig].get(p["type"], 0) + 1
        total = sum(sum(d.values()) for d in buckets.values())
        pure = 0
        per_sig = {}
        for sig, d in buckets.items():
            n = sum(d.values())
            maj_type = max(d, key=d.get)
            pure += d[maj_type]
            per_sig[sig] = {"n": n, "maj_type": maj_type, "purity": round(d[maj_type] / n, 3), "mix": dict(d)}
        return pure / total if total else 0.0, len(buckets), per_sig


# ============================================================================
# CYCLE 17 — router de TEXTO ROBUSTO: Naive-Bayes online palabra->cadena, tolera paráfrasis.
#
# El TextRouter de CYCLE 16 indexa por una FIRMA DISCRETA de keywords exactas. Eso es FRÁGIL: si los
# enunciados se parafrasean (sinónimos, cláusulas reordenadas) y comparten vocabulario (ambigüedad), la
# firma CONFUNDE tipos -> pureza firma->tipo CAE < 1.0 (CYCLE 17 lo demuestra). La cura es no depender de
# flags exactos sino de TODA la bolsa-de-palabras, con probabilidades APRENDIDAS del verificador real:
#
#   - Representación: bag-of-words del texto crudo (tokens alfabéticos en minúscula, sin números/símbolos).
#   - Modelo: Naive-Bayes multiclase con una clase por CADENA. Para cada cadena guarda conteos
#     count[chain][word] de cuántas veces ESA cadena ACERTÓ (verificador real) cuando esa palabra estaba en
#     el enunciado. Score(chain | texto) = sum_w log P(word|chain) con suavizado de Laplace (+1). Elige el
#     argmax. NO mira type/answer — solo problem["text"].
#   - Aprendizaje ONLINE, premiado por is_correct (la realidad): prueba la cadena de mayor score (epsilon-
#     greedy para explorar), corre, y SOLO si el verificador confirma acierto suma los conteos de sus
#     palabras. Así estima P(palabra | cadena-que-funciona). Como la decisión SUMA sobre muchas palabras y
#     las palabras compartidas (distractores) aparecen en TODAS las clases (no discriminan), un sinónimo o
#     un distractor nuevo no rompe la clasificación -> degrada SUAVE bajo paráfrasis/ambigüedad.
#
# Sigue siendo stdlib puro y CPU-only. Recibe SOLO el texto para rutear (igual que CYCLE 16).
# ============================================================================

import math

_WORD_RE = re.compile(r"[a-záéíóúñ]+", re.IGNORECASE)


def bag_of_words(text):
    """Tokeniza el texto CRUDO en palabras alfabéticas en minúscula (sin números/símbolos). Recibe SOLO
    el string del enunciado -> es la ÚNICA fuente de información del router robusto (no hay peeking)."""
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) >= 2]


class RobustTextRouter:
    """
    Router de texto ROBUSTO (CYCLE 17): Naive-Bayes multiclase sobre bag-of-words, aprendido ONLINE con el
    verificador real. Una clase por cadena; estima P(palabra | esta-cadena-acierta) contando las palabras
    de los enunciados que la cadena resolvió bien. Predice argmax_c sum_w log P(w|c). Tolera paráfrasis
    porque la decisión se reparte sobre TODAS las palabras (y las compartidas no discriminan).
    Nunca lee problem["type"] ni problem["answer"].
    """
    def __init__(self, chain_names, eps=0.15, seed=0, graded=False):
        self.chain_names = list(chain_names)
        self.graded = graded
        self.eps = eps
        self.rng = Random(seed)
        self.explore = True
        # count[chain][word] = veces que esa cadena ACERTÓ con esa palabra presente; tot[chain] = total
        # de tokens acumulados para la cadena (denominador del NB con Laplace). vocab = vocabulario visto.
        self.count = {c: {} for c in self.chain_names}
        self.tot = {c: 0 for c in self.chain_names}
        self.vocab = set()

    def _words(self, problem):
        return bag_of_words(problem["text"])   # <- ÚNICA lectura del problema para rutear: el TEXTO

    def _score(self, chain, words):
        """log P(texto | chain) con suavizado de Laplace; -inf efectivo si la cadena nunca acertó aún."""
        tot = self.tot[chain]
        if tot == 0:
            return -1e9
        v = max(1, len(self.vocab))
        cc = self.count[chain]
        return sum(math.log((cc.get(w, 0) + 1.0) / (tot + v)) for w in words)

    def _best(self, words):
        best, best_score = self.chain_names[0], None
        for c in self.chain_names:
            s = self._score(c, words)
            if best_score is None or s > best_score:
                best, best_score = c, s
        return best

    def select(self, problem):
        """Cadena desplegada para este problema, decidida SOLO por el bag-of-words de su texto."""
        return self._best(self._words(problem))

    def train_one(self, problem):
        """Un paso online: elige cadena (epsilon-greedy sobre el score NB), corre, y SOLO si el VERIFICADOR
        confirma acierto suma los conteos de sus palabras -> estima P(palabra | cadena-que-funciona)."""
        words = self._words(problem)
        if self.explore and self.rng.random() < self.eps:
            chain = self.rng.choice(self.chain_names)
        else:
            chain = self._best(words)
        pred, _ = (graded_chain(chain, problem) if self.graded else CHAINS[chain](problem))
        if is_correct(problem, pred):                    # realidad, NO la etiqueta de tipo
            cc = self.count[chain]
            for w in words:
                cc[w] = cc.get(w, 0) + 1
                self.tot[chain] += 1
                self.vocab.add(w)
        return chain, pred

    def eval(self, problems):
        """Accuracy desplegando (exploración congelada): rutea por texto (NB) y corre la cadena elegida."""
        self.explore = False
        ok = 0
        for p in problems:
            chain = self.select(p)
            pred = graded_chain(chain, p)[0] if self.graded else CHAINS[chain](p)[0]
            if is_correct(p, pred):
                ok += 1
        self.explore = True
        return ok / len(problems)
