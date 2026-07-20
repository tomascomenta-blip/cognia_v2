"""exp049 — infraestructura común: datos, eval, batches. Ver README.md (protocolo pre-registrado)."""
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[3]
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# config canónica del protocolo (los módulos NO la cambian; desviaciones van en extra/README)
CFG = dict(hidden=[256, 128, 64, 32], n_classes=10, epochs=5, batch=64, device="cpu")


def load_mnist(device="cpu", n_train=None, n_test=None):
    """MNIST flatten 784, normalización estándar, tensores en device (una sola vez, sin DataLoader:
    en esta escala el overhead de workers supera al cómputo)."""
    from torchvision import datasets, transforms
    tf = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
    root = str(REPO / "data")
    tr = datasets.MNIST(root, train=True, download=True, transform=tf)
    te = datasets.MNIST(root, train=False, transform=tf)

    def to_tensors(ds, n):
        n = len(ds) if n is None else min(n, len(ds))
        x = torch.stack([ds[i][0] for i in range(n)]).view(n, -1)
        y = torch.tensor([ds[i][1] for i in range(n)], dtype=torch.long)
        return x.to(device), y.to(device)

    x_tr, y_tr = to_tensors(tr, n_train)
    x_te, y_te = to_tensors(te, n_test)
    return x_tr, y_tr, x_te, y_te


def batches(x, y, batch, seed_epoch):
    """Minibatches barajados (determinista por seed_epoch)."""
    g = np.random.default_rng(seed_epoch)
    idx = torch.from_numpy(g.permutation(len(x))).to(x.device)
    for i in range(0, len(x) - batch + 1, batch):
        j = idx[i:i + batch]
        yield x[j], y[j]


@torch.no_grad()
def accuracy(predict, x, y, batch=512):
    """predict(x_batch) -> logits/scores (B, n_classes)."""
    hits = 0
    for i in range(0, len(x), batch):
        hits += int((predict(x[i:i + batch]).argmax(-1) == y[i:i + batch]).sum())
    return hits / len(x)
