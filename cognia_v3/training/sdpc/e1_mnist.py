"""
SDPC E1: validate the Protocolo del Aula on MNIST (paper §8, experimento E1).

Question: Does SDPC reach >= 95% of backprop accuracy?
PASS -> method viable, proceed to E2.
FAIL -> investigate or archive; el sistema sigue con QLoRA.

Run: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.sdpc.e1_mnist
"""
import json
import datetime
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from cognia_v3.training.sdpc.sdpc_mlp import SDPCMLP
from cognia_v3.training.sdpc.bp_mlp import BPMLP

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def evaluate(model, loader: DataLoader) -> float:
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            correct += (model(x).argmax(-1) == y).sum().item()
            total += len(y)
    return correct / total


def run_e1(epochs: int = 5, batch_size: int = 64, sdpc_lr: float = 0.02) -> dict:
    torch.manual_seed(42)

    tf = transforms.Compose([transforms.ToTensor(),
                             transforms.Normalize((0.1307,), (0.3081,))])
    train_set = datasets.MNIST("./data", train=True, download=True, transform=tf)
    test_set = datasets.MNIST("./data", train=False, transform=tf)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_set, batch_size=256)

    results = {}

    for name, ModelClass, use_lr in [("SDPC", SDPCMLP, True), ("BP", BPMLP, False)]:
        print(f"\n{'=' * 40}")
        print(f"Training {name} for {epochs} epochs ...")
        model = ModelClass()
        epoch_log = []

        for ep in range(1, epochs + 1):
            model.train()
            total_loss = total_acc = n = 0
            # lr decay para SDPC: estabiliza las épocas tardías (FIX 2)
            lr_ep = sdpc_lr * (0.6 ** (ep - 1))
            for x, y in train_loader:
                r = model.train_step(x, y, lr_ep) if use_lr else model.train_step(x, y)
                total_loss += r["loss"]
                total_acc += r["acc"]
                n += 1

            test_acc = evaluate(model, test_loader)
            log = {"epoch": ep, "train_loss": round(total_loss / n, 4),
                   "train_acc": round(total_acc / n, 4), "test_acc": round(test_acc, 4)}
            epoch_log.append(log)
            print(f"  Epoch {ep}/{epochs} — train_acc={log['train_acc']:.3f}  "
                  f"test_acc={test_acc:.3f}")

        results[name] = epoch_log

    sdpc_acc = results["SDPC"][-1]["test_acc"]
    bp_acc = results["BP"][-1]["test_acc"]
    ratio = sdpc_acc / bp_acc if bp_acc > 0 else 0.0

    print(f"\n{'=' * 40}")
    print("RESULTS:")
    print(f"  BP   final test acc: {bp_acc:.4f}")
    print(f"  SDPC final test acc: {sdpc_acc:.4f}")
    print(f"  Ratio SDPC/BP:       {ratio:.4f}")
    print(f"  Target:              >= 0.9500")

    verdict = ("PASS — SDPC viable. Proceed to E2." if ratio >= 0.95
               else f"FAIL — SDPC = {ratio:.1%} of BP. Investigate sdpc_mlp.py before scaling.")
    print(f"\n  Verdict: {verdict}")

    output = {
        "timestamp": datetime.datetime.now().isoformat(),
        "config": {"epochs": epochs, "batch_size": batch_size, "sdpc_lr": sdpc_lr},
        "sdpc_final_test_acc": sdpc_acc, "bp_final_test_acc": bp_acc,
        "ratio": ratio, "verdict": verdict, "epoch_log": results,
    }
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    fname = EVAL_DIR / f"sdpc_e1_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved: {fname}")
    return output


if __name__ == "__main__":
    run_e1(epochs=5, batch_size=64, sdpc_lr=0.02)
