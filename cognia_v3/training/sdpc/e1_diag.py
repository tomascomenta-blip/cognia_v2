"""
Diagnóstico acotado del colapso de SDPC en E1 (no es tuning infinito).

Hipótesis a discriminar:
  H1: lr=0.02 demasiado alto -> divergencia -> ReLUs muertas -> azar.
  H2: init std=0.02 demasiado chica para 5 capas -> señal desvanecida.
  H3: la culpa por norma colapsa el update cuando las normas caen.

Corre 1 epoch sobre subset de 10k por config y reporta train_acc final,
fracción de unidades muertas por capa y norma de pesos.

Run: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.sdpc.e1_diag
"""
import math

import torch
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

from cognia_v3.training.sdpc.sdpc_mlp import SDPCMLP


def dead_fraction(model, loader) -> list[float]:
    """Fracción de unidades ReLU que NUNCA se activan sobre un batch grande."""
    x, _ = next(iter(loader))
    h = x.view(x.shape[0], -1)
    fracs = []
    with torch.no_grad():
        for layer in model.hidden_layers:
            h, _, _ = layer(h)
            fracs.append(float((h.sum(dim=0) == 0).float().mean()))
    return fracs


def run_config(label: str, lr: float, init_std: float | None, epochs: int = 1) -> dict:
    torch.manual_seed(42)
    tf = transforms.Compose([transforms.ToTensor(),
                             transforms.Normalize((0.1307,), (0.3081,))])
    train_set = Subset(datasets.MNIST("./data", train=True, download=True, transform=tf),
                       range(10_000))
    loader = DataLoader(train_set, batch_size=64, shuffle=True)
    probe = DataLoader(train_set, batch_size=1024)

    model = SDPCMLP()
    if init_std is not None:
        # He-init aproximada por capa en vez del std fijo 0.02
        with torch.no_grad():
            for layer in model.hidden_layers:
                std = math.sqrt(2.0 / layer.in_dim) if init_std == -1 else init_std
                layer.W.normal_(0, std)

    accs, guilts = [], []
    for _ in range(epochs):
        for i, (x, y) in enumerate(loader):
            r = model.train_step(x, y, lr)
            accs.append(r["acc"])
            guilts.append(r["avg_guilt"])

    last50 = sum(accs[-50:]) / 50
    dead = dead_fraction(model, probe)
    w_norms = [float(l.W.norm()) for l in model.hidden_layers]
    print(f"{label:28s} acc(últ.50)={last50:.3f}  guilt={sum(guilts[-50:])/50:.2f}  "
          f"dead={['%.2f' % d for d in dead]}  |W|={['%.1f' % n for n in w_norms]}")
    return {"label": label, "acc": last50, "dead": dead, "w_norms": w_norms}


if __name__ == "__main__":
    print("config                        resultado")
    print("-" * 100)
    results = [
        run_config("base lr=0.02 std=0.02", lr=0.02, init_std=None),
        run_config("H1 lr=0.005 std=0.02", lr=0.005, init_std=None),
        run_config("H1 lr=0.001 std=0.02", lr=0.001, init_std=None),
        run_config("H2 lr=0.02  He-init", lr=0.02, init_std=-1),
        run_config("H1+H2 lr=0.005 He-init", lr=0.005, init_std=-1),
    ]
    best = max(results, key=lambda r: r["acc"])
    print(f"\nMejor config: {best['label']} con acc={best['acc']:.3f}")
