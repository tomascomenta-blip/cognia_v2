"""exp049 — Forward-Forward (Hinton 2022): goodness local por capa, positivos vs negativos.

Regla LOCAL (por qué no viola la prohibición de backprop): cada capa entrena con autograd
de UNA sola Linear — su input llega .detach() y L2-normalizado, así el grafo del backward
nunca cruza capas. La normalización entre capas es parte del método: borra la magnitud
(= la goodness) de la capa anterior y obliga a la siguiente a encontrar evidencia nueva.

Etiqueta: overlay en los primeros 10 píxeles (fondo = negro normalizado, píxel y-ésimo =
intensidad máx del dataset). Positivos = etiqueta correcta; negativos = etiqueta INCORRECTA
aleatoria. Goodness g = mean(h²); loss = softplus(θ−g_pos) + softplus(g_neg−θ), θ=2.0.
Adam local por capa, lr=1e-3.

Predicción: se prueban las 10 etiquetas candidatas y se suma la goodness de TODAS las capas.
Hinton a veces excluye la primera, pero eso es para sus redes 4×2000 donde sobra capacidad;
en la pirámide angosta del protocolo [256,128,64,32] la primera capa concentra la mayor parte
de la capacidad y excluirla tira casi toda la señal.

Desviaciones documentadas:
- A la capa siguiente pasan las activaciones PRE-update (evita un forward extra por capa;
  con lr=1e-3 la diferencia por batch es ruido y el costo es métrica de primera clase).
- Además de la arquitectura común corre la variante ff_wide 784→500→500 (el método fue
  diseñado para capas anchas, ver README) con el mismo presupuesto de epochs; va en extra
  y su tiempo NO se suma al wall_s principal (para no ensuciar cost_vs_bp).
- updates cuenta pasos Adam de UNA capa (n_capas por batch), no batches.
"""
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy

THETA = 2.0   # umbral de goodness (Hinton 2022)
LR = 1e-3


def overlay(x, y, lo, hi):
    """Estampa la etiqueta en los primeros 10 píxeles (one-hot en el espacio normalizado)."""
    x = x.clone()
    x[:, :10] = lo
    x[torch.arange(len(x), device=x.device), y] = hi
    return x


def norm_l2(h):
    # borra la norma para que la capa siguiente no herede la goodness de la anterior
    return h / (h.norm(dim=1, keepdim=True) + 1e-8)


def ff_train(data, hidden, cfg, seed, tag, log):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    # intensidades del overlay tomadas del dataset ya normalizado (negro / blanco reales)
    lo, hi = float(x_tr.min()), float(x_tr.max())
    dims = [x_tr.shape[1]] + list(hidden)
    layers = [nn.Linear(dims[i], dims[i + 1]).to(device) for i in range(len(dims) - 1)]
    opts = [torch.optim.Adam(l.parameters(), lr=LR) for l in layers]
    n_classes = cfg["n_classes"]

    def predict(xb):
        scores = torch.zeros(len(xb), n_classes, device=device)
        for c in range(n_classes):
            h = overlay(xb, torch.full((len(xb),), c, dtype=torch.long, device=device), lo, hi)
            for lay in layers:
                h = F.relu(lay(h))
                scores[:, c] += h.pow(2).mean(1)   # votan todas las capas (ver docstring)
                h = norm_l2(h)
        return scores

    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            # negativo = etiqueta incorrecta uniforme (sumar 1..9 mod 10 nunca da la correcta)
            y_neg = (y + torch.randint(1, n_classes, y.shape, device=device)) % n_classes
            h_pos = overlay(x, y, lo, hi)
            h_neg = overlay(x, y_neg, lo, hi)
            for lay, opt in zip(layers, opts):
                a_pos = F.relu(lay(h_pos))
                a_neg = F.relu(lay(h_neg))
                loss = (F.softplus(THETA - a_pos.pow(2).mean(1))
                        + F.softplus(a_neg.pow(2).mean(1) - THETA)).mean()
                opt.zero_grad(set_to_none=True)
                loss.backward()   # LOCAL: el grafo es esta capa sola (input detached)
                opt.step()
                updates += 1
                h_pos = norm_l2(a_pos.detach())
                h_neg = norm_l2(a_neg.detach())
        acc = accuracy(predict, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [{tag} seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates}


def train(data, cfg, seed, log=print):
    torch.manual_seed(seed)
    r = ff_train(data, cfg["hidden"], cfg, seed, "ff", log)
    # variante ancha: FF fue diseñado para capas anchas (README); mismo presupuesto de epochs
    w = ff_train(data, [500, 500], cfg, seed, "ff_wide", log)
    r["extra"] = {"wide_test_acc": w["test_acc"], "wide_wall_s": w["wall_s"],
                  "wide_updates": w["updates"], "wide_epoch_log": w["epoch_log"],
                  "theta": THETA, "lr": LR, "vote_layers": "todas (no se excluye la primera)",
                  "updates_note": "1 update = 1 paso Adam de UNA capa (n_capas por batch)",
                  "wall_note": "wall_s NO incluye la variante wide (comparabilidad cost_vs_bp)"}
    return r
