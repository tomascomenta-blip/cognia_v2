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
