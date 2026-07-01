"""exp049 — BASELINE: backprop clásico (Adam + cross-entropy). El denominador de todos los ratios."""
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy


def build_mlp(hidden, n_classes):
    dims = [784] + list(hidden) + [n_classes]
    layers = []
    for i in range(len(dims) - 1):
        layers.append(nn.Linear(dims[i], dims[i + 1]))
        if i < len(dims) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    torch.manual_seed(seed)
    model = build_mlp(cfg["hidden"], cfg["n_classes"]).to(x_tr.device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        model.train()
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            loss = F.cross_entropy(model(x), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            updates += 1
        model.eval()
        acc = accuracy(model, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [bp seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates, "extra": {}}
