"""
CYCLE 19 — usar el char-LM ENTRENADO DE VERDAD como ENCODER del router.

Todo el pilar de meta-razonamiento (CYCLE 12-18) ruteo desde features HECHAS A MANO: keywords (16),
bag-of-words Naive-Bayes (17). El caveat de pie de pagina de todo el pilar: nunca toco el MODELO real;
las features eran sinteticas/artesanales. La frontera (reason/README.md, manager/future_work.md): usar
un ENCODER APRENDIDO de verdad. CYCLE 19 hace exactamente eso por PRIMERA VEZ:

  - Carga el char-LM hibrido de CYCLE 7 (cognia_x/runs/cycle7/charlm_best.pt, 6.3M params, entrenado
    sobre LIBROS en ingles/espanol — dominio AJENO a estos problemas de cuentas).
  - lm_embed(model, text): corre los BYTES del enunciado por el modelo y devuelve el estado oculto final
    (pre-lm_head) mean-pooled + last-token, concatenados -> un vector de features de tamano fijo.
  - LMRouter: un clasificador ONLINE diminuto (media-de-clase / nearest-class-mean sobre embeddings)
    aprendido SOLO con feedback del verificador real. Predice una CLASE latente para el texto y rutea con
    la maquinaria de bandit de CYCLE 12 indexada por esa clase predicha.

HONESTIDAD: el char-LM se entreno sobre PROSA, no sobre estas plantillas de problemas. Es totalmente
plausible que sus features NO separen bien estos tipos. Reportamos lo que pase con numeros — un
resultado negativo/mixto sobre un modelo chico fuera-de-dominio es en si mismo un hallazgo valioso.

Lee SOLO problem["text"] para rutear (jamas type/answer); la recompensa viene de is_correct (la realidad).
CPU-only, torch.set_num_threads(3), no_grad.
"""
import os
from random import Random

import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.problems import is_correct
from cognia_x.reason.router import Router

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CKPT = os.path.join(ROOT, "cognia_x", "runs", "cycle7", "charlm_best.pt")


def load_charlm(ckpt_path=CKPT, device="cpu"):
    """Carga el char-LM hibrido de CYCLE 7 desde el checkpoint. El formato (ver charlm.py) es
    {"step", "model": state_dict, "cfg": HybridConfig.__dict__, "val_loss"}. Reconstruye la config y
    carga los pesos. Devuelve (model, cfg). Si falla, la excepcion sube (el runner cae al fallback)."""
    ck = torch.load(ckpt_path, map_location=device)
    cfg = HybridConfig(**ck["cfg"])
    model = HybridLM(cfg).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, cfg


@torch.no_grad()
def lm_embed(model, text, max_len=None, device="cpu"):
    """
    Corre los BYTES del texto por el char-LM y devuelve un vector de features de tamano fijo (2*d_model):
    concatenacion de [mean-pool sobre las posiciones, estado del ULTIMO token] de los estados ocultos
    finales (pre-lm_head). Detach + no_grad + CPU. Es la representacion que el modelo de verdad le da al
    enunciado, sin tocar lm_head ni generar nada.
    """
    if max_len is None:
        max_len = model.cfg.max_seq_len
    b = text.encode("utf-8", errors="replace")[:max_len]
    if len(b) == 0:
        b = b" "
    idx = torch.tensor([list(b)], dtype=torch.long, device=device)
    h = model.forward_features(idx)          # (1, L, d_model)
    mean = h.mean(dim=1).squeeze(0)          # (d_model,)
    last = h[:, -1, :].squeeze(0)            # (d_model,)
    return torch.cat([mean, last], dim=0).detach()   # (2*d_model,)


class LMRouter:
    """
    Router que usa el char-LM como ENCODER. Pipeline:
      0) WHITENING: los embeddings crudos del char-LM tienen una componente comun GRANDE (coseno medio
         ~0.79 entre textos cualesquiera) que ahoga la senal de tipo. Estandarizamos por dimension
         (z-score con media/desvio corridos sobre el train) -> se quita esa componente comun y la
         estructura de TIPO (el residuo) domina el coseno (los tipos pasan a separarse fuerte). Esto NO
         mira el tipo: son solo estadisticas marginales del texto. Es lo que deja ver lo que el LM SABE.
      1) lm_embed(texto) -> vector fijo (2*d_model) -> whiten.
      2) clasificador NEAREST-CLASS-MEAN online: mantiene un prototipo (media de embeddings whitened) por
         CLASE latente. La clase de un texto = el prototipo mas cercano (coseno). Las clases se DESCUBREN
         online: si el texto esta lejos de todo prototipo conocido (o no hay ninguno), abre clase NUEVA.
      3) ruteo: un bandit de CYCLE 12 (Router) indexado por la CLASE predicha (no por el tipo). Aprende
         que cadena funciona para cada clase, premiado por el verificador real.

    Nunca lee problem["type"] ni problem["answer"]: solo problem["text"] (via lm_embed) y, para premiar,
    is_correct (la realidad). El feedback del verificador es la UNICA senal de entrenamiento.
    """
    def __init__(self, model, chain_names, eps=0.15, seed=0, graded=False,
                 max_classes=12, new_class_sim=0.2, device="cpu"):
        self.model = model
        self.device = device
        self.inner = Router(chain_names, mode="verifier", eps=eps, seed=seed, graded=graded)
        self.graded = graded
        self.chain_names = list(chain_names)
        self.rng = Random(seed)
        # estadisticas de whitening (media/desvio por dimension), estimadas online sobre el train.
        self._w_sum = None; self._w_sumsq = None; self._w_n = 0
        # prototipos: lista de tensores (suma de embeddings WHITENED) + conteos -> media incremental.
        self.proto_sum = []      # tensores (2*d_model,)
        self.proto_cnt = []      # ints
        self.max_classes = max_classes      # tope honesto de clases latentes (evita explosion)
        self.new_class_sim = new_class_sim  # umbral de coseno (post-whitening) para abrir clase nueva

    def _raw_embed(self, problem):
        return lm_embed(self.model, problem["text"], device=self.device)   # <- UNICA lectura: el TEXTO

    def _accum_whiten(self, raw):
        """Acumula estadisticas marginales (no mira el tipo) para el z-score por dimension."""
        if self._w_sum is None:
            self._w_sum = torch.zeros_like(raw); self._w_sumsq = torch.zeros_like(raw)
        self._w_sum += raw; self._w_sumsq += raw * raw; self._w_n += 1

    def _whiten(self, raw):
        """z-score por dimension con las estadisticas corridas; sin stats aun, devuelve el crudo."""
        if self._w_n < 2:
            return raw
        mu = self._w_sum / self._w_n
        var = self._w_sumsq / self._w_n - mu * mu
        sd = torch.sqrt(var.clamp_min(1e-8))
        return (raw - mu) / sd

    def _embed(self, problem):
        """Embedding usado para rutear: crudo del char-LM, luego whitened con las stats del train."""
        return self._whiten(self._raw_embed(problem))

    def _proto(self, i):
        return self.proto_sum[i] / max(1, self.proto_cnt[i])

    def _assign_class(self, emb, grow=True):
        """Clase = prototipo mas cercano por coseno. Si no hay prototipos o el mejor coseno < umbral y
        queda cupo, abre una clase NUEVA (solo cuando grow=True, p.ej. en entrenamiento)."""
        if not self.proto_sum:
            if grow:
                self.proto_sum.append(emb.clone()); self.proto_cnt.append(1)
                return 0
            return 0
        en = emb / (emb.norm() + 1e-8)
        best_i, best_sim = 0, -2.0
        for i in range(len(self.proto_sum)):
            p = self._proto(i)
            sim = float(torch.dot(en, p / (p.norm() + 1e-8)))
            if sim > best_sim:
                best_i, best_sim = i, sim
        if grow and best_sim < self.new_class_sim and len(self.proto_sum) < self.max_classes:
            self.proto_sum.append(emb.clone()); self.proto_cnt.append(1)
            return len(self.proto_sum) - 1
        return best_i

    def _update_proto(self, cls, emb):
        self.proto_sum[cls] = self.proto_sum[cls] + emb
        self.proto_cnt[cls] += 1

    def fit_whiten(self, problems):
        """PRIMER paso: estima las stats de whitening (media/desvio por dim) sobre los embeddings crudos del
        train ANTES de construir prototipos -> el espacio de whitening queda FIJO y estable para todo el
        ciclo (sin drift entre prototipos tempranos/tardios). Cachea el crudo para no re-correr el LM.
        Solo estadisticas marginales del texto: NO mira el tipo."""
        self._raw_cache = {}
        for p in problems:
            raw = self._raw_embed(p)
            self._accum_whiten(raw)
            self._raw_cache[id(p)] = raw

    def train_one(self, problem):
        """Un paso online: embed del texto -> clase (NCM, puede crecer) -> bandit elige cadena -> corre ->
        premia con el VERIFICADOR real. Actualiza el prototipo de la clase con este embedding."""
        cache = getattr(self, "_raw_cache", None)
        raw = cache[id(problem)] if cache is not None and id(problem) in cache else self._raw_embed(problem)
        emb = self._whiten(raw)
        cls = self._assign_class(emb, grow=True)
        self._update_proto(cls, emb)
        chain = self.inner.select(cls)
        pred, _ = self.inner.run_chain(chain, problem)
        reward = 1.0 if is_correct(problem, pred) else 0.0   # realidad, NO la etiqueta de tipo
        self.inner.update(cls, chain, reward)
        return chain, pred

    def select(self, problem):
        """Cadena desplegada: clase del texto (sin crecer prototipos en test) -> mejor cadena aprendida."""
        emb = self._embed(problem)
        cls = self._assign_class(emb, grow=False)
        return self.inner.select(cls)

    def eval(self, problems):
        """Accuracy desplegando (exploracion congelada): rutea por la clase-LM y corre la cadena elegida."""
        self.inner.explore = False
        ok = 0
        for p in problems:
            chain = self.select(p)
            pred = graded_chain(chain, p)[0] if self.graded else CHAINS[chain](p)[0]
            if is_correct(p, pred):
                ok += 1
        self.inner.explore = True
        return ok / len(problems)

    def class_to_type_purity(self, problems):
        """
        AUDITORIA de estructura (igual que TextRouter.signature_to_type_purity): para cada CLASE latente,
        que tipos verdaderos cayeron en ella -> PUREZA (fraccion del tipo mayoritario), promedio ponderado.
        Mide cuanto recupero la estructura de tipos SOLO desde la representacion del LM. Aca SI leemos
        problem["type"], pero solo para EVALUAR a posteriori — el router nunca lo uso para decidir.
        """
        buckets = {}
        for p in problems:
            emb = self._embed(p)
            cls = self._assign_class(emb, grow=False)
            buckets.setdefault(cls, {})
            buckets[cls][p["type"]] = buckets[cls].get(p["type"], 0) + 1
        total = sum(sum(d.values()) for d in buckets.values())
        pure = 0
        per_cls = {}
        for cls, d in buckets.items():
            n = sum(d.values())
            maj = max(d, key=d.get)
            pure += d[maj]
            per_cls[cls] = {"n": n, "maj_type": maj, "purity": round(d[maj] / n, 3), "mix": dict(d)}
        return (pure / total if total else 0.0), len(buckets), per_cls


def train_indomain_encoder(texts, d_model=96, n_layers=3, n_heads=4, window=64, attn_every=2,
                           max_seq_len=192, L=128, batch=16, steps=2000, lr=1e-3,
                           device="cpu", seed=0, log=print):
    """
    CYCLE 20 — entrena un char-LM CHICO IN-DOMAIN como ENCODER del router. UNSUPERVISED: el unico dato
    que ve es la concatenacion de los TEXTOS de los enunciados (bytes); JAMAS lee problem["type"] ni
    problem["answer"] (recibe `texts`, una lista de strings ya extraidos -> no hay acceso al label). Es
    next-byte prediction puro (modela P(byte siguiente | bytes previos)), igual que charlm.train pero
    chico y rapido en CPU. Determinista por `seed`. Devuelve (model, cfg).

    WHY: CYCLE 19 uso un char-LM entrenado sobre LIBROS (off-domain) y su representacion recuperaba la
    estructura de tipo pero perdia con un Naive-Bayes in-domain. La leccion: "un encoder generico no
    domina features baratas in-domain salvo que este entrenado CERCA de la tarea". CYCLE 20 entrena el
    encoder EXACTAMENTE sobre estos textos para testear esa leccion de frente.
    """
    torch.manual_seed(seed)
    cfg = HybridConfig(vocab_size=256, d_model=d_model, n_layers=n_layers, n_heads=n_heads,
                       window=window, attn_every=attn_every, max_seq_len=max_seq_len)
    model = HybridLM(cfg).to(device)
    # corpus = SOLO los textos (bytes), separados por \n. Nunca toca type/answer.
    corpus = b"\n".join(t.encode("utf-8", errors="replace") for t in texts)
    data = torch.frombuffer(bytearray(corpus), dtype=torch.uint8)
    if data.numel() <= L + 1:
        raise ValueError(f"corpus in-domain muy chico ({data.numel()}B) para L={L}")
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    last_loss = float("nan")
    log(f"[cycle20] entreno encoder IN-DOMAIN: d={d_model} layers={n_layers} params={model.num_params():,} "
        f"corpus={data.numel():,}B steps={steps}")
    for s in range(steps):
        ix = torch.randint(0, data.numel() - L - 1, (batch,))
        x = torch.stack([data[i:i + L] for i in ix]).long().to(device)
        y = torch.stack([data[i + 1:i + 1 + L] for i in ix]).long().to(device)
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        last_loss = loss.item()
        if s % 200 == 0 or s == steps - 1:
            log(f"[cycle20]   step {s} loss {last_loss:.4f}")
    model.eval()
    return model, cfg, last_loss


def save_encoder(model, cfg, path):
    """Guarda el encoder in-domain (mismo formato que charlm.py) para reproducibilidad/reuso."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({"model": model.state_dict(), "cfg": cfg.__dict__}, path)


def load_encoder(path, device="cpu"):
    """Recarga el encoder in-domain guardado por save_encoder. Devuelve (model, cfg)."""
    ck = torch.load(path, map_location=device)
    cfg = HybridConfig(**ck["cfg"])
    model = HybridLM(cfg).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, cfg


def train_tiny_charlm_fallback(device="cpu", steps=400, seed=0, log=print):
    """
    FALLBACK honesto: si el checkpoint no carga, entrena IN-SCRIPT un char-LM diminuto y determinista
    sobre un mini-corpus (los mismos enunciados parafraseados) para que el ciclo IGUAL corra. Se DECLARA
    como fallback en el reporte (no es el modelo de CYCLE 7). Devuelve (model, cfg).
    """
    from cognia_x.reason.problems import gen_paraphrased
    torch.manual_seed(seed)
    cfg = HybridConfig(vocab_size=256, d_model=64, n_layers=4, n_heads=4, window=64,
                       attn_every=2, max_seq_len=192)
    model = HybridLM(cfg).to(device)
    corpus = b"\n".join(p["text"].encode("utf-8", errors="replace")
                        for p in gen_paraphrased(600, seed=seed, ambiguity=0.5))
    data = torch.frombuffer(bytearray(corpus), dtype=torch.uint8)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    L = 128
    model.train()
    for s in range(steps):
        ix = torch.randint(0, max(1, data.numel() - L - 1), (16,))
        x = torch.stack([data[i:i + L] for i in ix]).long().to(device)
        y = torch.stack([data[i + 1:i + 1 + L] for i in ix]).long().to(device)
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward(); opt.step()
        if s % 100 == 0:
            log(f"[fallback] step {s} loss {loss.item():.4f}")
    model.eval()
    return model, cfg
