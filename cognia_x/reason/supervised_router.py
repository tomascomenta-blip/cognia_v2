"""
CYCLE 21 — el encoder SUPERVISADO POR EL VERIFICADOR (brazo E), capstone del sub-arco de ruteo de texto.

El sub-arco 16->17->19->20 llego a esta leccion refinada (RESULTS.md, CYCLE 20): "entrenar el encoder cerca
de la tarea ayuda mucho (y gana con texto limpio), pero para BATIR a un discriminativo barato (Naive-Bayes)
BAJO RUIDO el encoder necesitaria senal SUPERVISADA (del verificador), no solo next-byte". O sea: el char-LM
in-domain (CYCLE 20, D) es UNSUPERVISED -> modela la superficie del texto, no QUE pistas discriminan la cadena
correcta; por eso bajo paraphrasis+distractores se ensucia mas que un NB que aprendio directo del verificador.

CYCLE 21 le da al encoder EXACTAMENTE esa senal que le faltaba: aprende la representacion DISCRIMINATIVAMENTE
del verificador real. Concretamente (approach (a) "chain-success supervision"):
  1) features del texto = lm_embed del char-LM IN-DOMAIN de CYCLE 20 (frozen, reusado/cacheado) -> vector
     fijo (2*d_model). UNICA lectura del problema: problem["text"] (via lm_embed).
  2) cabeza SUPERVISADA: una MLP chica que predice, por CADA cadena, si esa cadena ACIERTA este texto
     (multi-label). El TARGET de supervision se arma corriendo CADA cadena y mirando is_correct (el
     VERIFICADOR real) -> y[c]=1 si la cadena c acerto, 0 si no. JAMAS lee problem["type"] ni
     problem["answer"] directamente: la unica senal es is_correct sobre las cadenas probadas.
  3) ruteo en test: forward de la cabeza -> score por cadena -> argmax = cadena predicha-mejor.

Esto es el embodiment literal del objetivo del dueno ("evalua el resultado dentro del sistema"): el encoder
mismo aprende de si la forma de razonar elegida FUNCIONO. Es lo MISMO que hace el NB (aprender del
verificador), pero en una representacion RICA (las features aprendidas del char-LM) en vez de bag-of-words.

AUDITORIA (declarada y testeada): la supervision viene SOLO de is_correct sobre las cadenas; el input de la
cabeza es SOLO lm_embed(problem["text"]); problem["type"]/["answer"] no se tocan para entrenar ni rutear
(type se usa solo a posteriori para pureza/ceiling, igual que en todos los ciclos).

Usa torch. CPU-only, torch.set_num_threads(3) lo fija el runner. Determinista por seed. La cabeza es chica y
las features se CACHEAN (un forward del char-LM por texto) -> entrenar es rapido aun en CPU.
"""
import torch
import torch.nn as nn

from cognia_x.reason.chains import CHAINS
from cognia_x.reason.problems import is_correct
from cognia_x.reason.lm_router import lm_embed


def chain_success_target(problem, chain_names):
    """
    Arma el TARGET supervisado de un problema corriendo CADA cadena y premiando con el VERIFICADOR real.
    Devuelve un vector y de tamano len(chain_names): y[i]=1.0 si la cadena i ACERTO (is_correct), 0.0 si no.

    AUDITORIA: la UNICA senal es is_correct(problem, pred) — la realidad de si la cadena funciono. NUNCA lee
    problem["type"]; problem["answer"] solo lo consume is_correct adentro (igual que en CYCLE 12-20 el reward
    del verificador). El encoder/cabeza nunca ve type/answer: ve este vector de exitos-de-cadena.
    """
    y = []
    for c in chain_names:
        pred = CHAINS[c](problem)[0]
        y.append(1.0 if is_correct(problem, pred) else 0.0)   # realidad (verificador), NO la etiqueta de tipo
    return y


class SupervisedHead(nn.Module):
    """MLP chica: features del char-LM (2*d_model) -> logit por cadena (multi-label chain-success).
    Una sola capa oculta; suficiente para una representacion ya rica y un problema de 4 tipos."""
    def __init__(self, in_dim, n_chains, hidden=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, n_chains),
        )

    def forward(self, x):
        return self.net(x)            # (B, n_chains) logits; sigmoid afuera para multi-label


class SupervisedLMRouter:
    """
    Brazo E (CYCLE 21): encoder SUPERVISADO POR EL VERIFICADOR. Usa el char-LM in-domain (CYCLE 20) FROZEN
    como encoder de features y aprende una cabeza que predice exito-por-cadena directo del verificador. Rutea
    al argmax del score predicho.

    Pipeline:
      - _features(problem) = lm_embed(char-LM in-domain, problem["text"]) -> (2*d_model). UNICA lectura: el TEXTO.
      - WHITENING: z-score por dimension con stats del train (igual que LMRouter de CYCLE 19): quita la
        componente comun grande de los embeddings crudos del char-LM. Solo estadisticas marginales del texto.
      - cabeza SupervisedHead entrenada con BCE multi-label contra chain_success_target (del VERIFICADOR).
      - select(problem) = argmax_c sigmoid(head(feat))[c] -> cadena predicha-mejor.

    Nunca lee problem["type"]/["answer"] para entrenar ni rutear. La supervision es is_correct sobre cadenas.
    """
    def __init__(self, encoder, chain_names, hidden=64, lr=3e-3, epochs=40, seed=0, device="cpu"):
        self.encoder = encoder              # char-LM in-domain FROZEN (CYCLE 20), solo forward_features
        self.chain_names = list(chain_names)
        self.device = device
        self.hidden = hidden
        self.lr = lr
        self.epochs = epochs
        self.seed = seed
        # stats de whitening (media/desvio por dim), estimadas sobre el train (no miran el tipo).
        self._w_mu = None
        self._w_sd = None
        self.head = None                    # se crea al conocer in_dim (primer fit)
        self._raw_cache = {}                # cachea lm_embed crudo por id(problema) -> 1 forward del LM

    @torch.no_grad()
    def _raw_embed(self, problem):
        """Embedding crudo del char-LM in-domain. UNICA lectura del problema: problem['text']."""
        return lm_embed(self.encoder, problem["text"], device=self.device)   # <- SOLO el TEXTO

    def _cached_raw(self, problem):
        key = id(problem)
        if key not in self._raw_cache:
            self._raw_cache[key] = self._raw_embed(problem)
        return self._raw_cache[key]

    def _fit_whiten(self, problems):
        """Estima media/desvio por dimension sobre los embeddings crudos del train. Solo estadisticas
        marginales del texto (NO mira el tipo) -> deja ver la senal que el char-LM puso en la representacion."""
        raws = torch.stack([self._cached_raw(p) for p in problems])   # (N, 2*d)
        self._w_mu = raws.mean(dim=0)
        self._w_sd = raws.std(dim=0).clamp_min(1e-6)

    def _whiten(self, raw):
        if self._w_mu is None:
            return raw
        return (raw - self._w_mu) / self._w_sd

    def _feat(self, problem):
        return self._whiten(self._cached_raw(problem))

    def fit(self, problems, log=None):
        """
        Entrena la cabeza supervisada. Para cada problema arma el target chain-success (del VERIFICADOR) y
        ajusta la cabeza con BCE multi-label sobre las features whitened del char-LM. Devuelve la loss final.

        AUDITORIA: el TARGET sale de chain_success_target (solo is_correct); el INPUT son features de
        lm_embed(problem["text"]). En ningun punto se lee problem["type"]/["answer"].
        """
        torch.manual_seed(self.seed)
        self._fit_whiten(problems)
        X = torch.stack([self._feat(p) for p in problems])                          # (N, 2*d) features del texto
        Y = torch.tensor([chain_success_target(p, self.chain_names) for p in problems],
                         dtype=torch.float32)                                       # (N, n_chains) del verificador
        in_dim = X.shape[1]
        self.head = SupervisedHead(in_dim, len(self.chain_names), hidden=self.hidden).to(self.device)
        opt = torch.optim.Adam(self.head.parameters(), lr=self.lr)
        loss_fn = nn.BCEWithLogitsLoss()
        self.head.train()
        last = float("nan")
        for ep in range(self.epochs):
            opt.zero_grad()
            logits = self.head(X)
            loss = loss_fn(logits, Y)
            loss.backward()
            opt.step()
            last = loss.item()
            if log is not None and (ep % 10 == 0 or ep == self.epochs - 1):
                # accuracy de ruteo en train = cuantas veces la cadena argmax-predicha realmente acierta.
                with torch.no_grad():
                    pred_chain = logits.argmax(dim=1)
                train_route_acc = float((Y[torch.arange(len(Y)), pred_chain] > 0.5).float().mean())
                log(f"[cycle21]   epoch {ep} bce {last:.4f}  train_route_acc {train_route_acc:.3f}")
        self.head.eval()
        return last

    @torch.no_grad()
    def _score(self, problem):
        feat = self._feat(problem).unsqueeze(0)
        return torch.sigmoid(self.head(feat)).squeeze(0)        # (n_chains,) prob de exito por cadena

    def select(self, problem):
        """Cadena desplegada = argmax del exito-de-cadena predicho. Decidida SOLO desde problem['text']."""
        scores = self._score(problem)
        return self.chain_names[int(scores.argmax())]

    @torch.no_grad()
    def eval(self, problems):
        """Accuracy held-out: rutea por la cabeza (argmax) y corre la cadena; premia con el verificador real."""
        ok = 0
        for p in problems:
            pred = CHAINS[self.select(p)](p)[0]
            if is_correct(p, pred):
                ok += 1
        return ok / len(problems)

    @torch.no_grad()
    def class_to_type_purity(self, problems):
        """
        AUDITORIA de estructura (igual que LMRouter): agrupa por la CADENA predicha y mira que tipos
        verdaderos cayeron en cada grupo -> pureza (fraccion del tipo mayoritario), promedio ponderado.
        Aca SI leemos problem["type"], pero SOLO para evaluar a posteriori — el router nunca lo uso.
        """
        buckets = {}
        for p in problems:
            c = self.select(p)
            buckets.setdefault(c, {})
            buckets[c][p["type"]] = buckets[c].get(p["type"], 0) + 1
        total = sum(sum(d.values()) for d in buckets.values())
        pure = 0
        for d in buckets.values():
            pure += d[max(d, key=d.get)]
        return (pure / total if total else 0.0), len(buckets)


def save_head(router, path):
    """Guarda la cabeza supervisada + las stats de whitening (para recargar y rutear sin re-entrenar)."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({
        "head_state": router.head.state_dict(),
        "in_dim": router.head.net[0].in_features,
        "n_chains": len(router.chain_names),
        "hidden": router.hidden,
        "chain_names": router.chain_names,
        "w_mu": router._w_mu,
        "w_sd": router._w_sd,
    }, path)


def load_head(encoder, path, chain_names=None, device="cpu"):
    """Recarga un SupervisedLMRouter (cabeza + whitening) listo para rutear (sin re-entrenar)."""
    ck = torch.load(path, map_location=device)
    names = chain_names if chain_names is not None else ck["chain_names"]
    r = SupervisedLMRouter(encoder, names, hidden=ck["hidden"], device=device)
    r.head = SupervisedHead(ck["in_dim"], ck["n_chains"], hidden=ck["hidden"]).to(device)
    r.head.load_state_dict(ck["head_state"])
    r.head.eval()
    r._w_mu = ck["w_mu"]
    r._w_sd = ck["w_sd"]
    return r
