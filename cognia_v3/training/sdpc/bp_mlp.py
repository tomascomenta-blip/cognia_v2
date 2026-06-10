"""
BP MLP: identical architecture to SDPCMLP, trained with standard backpropagation.
This is the baseline that SDPC must reach >= 95% of (criterio E1 del paper).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class BPMLP(nn.Module):
    """Standard 5-layer MLP trained with Adam + cross-entropy backprop."""

    DEFAULT_DIMS = [784, 256, 128, 64, 32, 10]

    def __init__(self, dims: list[int] = None):
        super().__init__()
        dims = dims or self.DEFAULT_DIMS
        layers = []
        for i in range(len(dims) - 2):
            layers += [nn.Linear(dims[i], dims[i + 1]), nn.ReLU()]
        layers.append(nn.Linear(dims[-2], dims[-1]))
        self.net = nn.Sequential(*layers)
        self.optimizer = torch.optim.Adam(self.parameters(), lr=1e-3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x.view(x.shape[0], -1))

    def train_step(self, x: torch.Tensor, y: torch.Tensor) -> dict[str, float]:
        self.optimizer.zero_grad()
        logits = self.forward(x)
        loss = F.cross_entropy(logits, y)
        loss.backward()
        self.optimizer.step()
        acc = (logits.argmax(-1) == y).float().mean().item()
        return {"loss": loss.item(), "acc": acc}
