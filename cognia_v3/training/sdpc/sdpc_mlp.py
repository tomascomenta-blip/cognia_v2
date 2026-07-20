"""
SDPC MLP: 5-layer MLP trained with the Protocolo del Aula update rule (E1).
No backpropagation. No autograd. Manual weight updates.

Regla E1 simplificada (paper §4, sin corrección entre pares, r*=None):
  e        = softmax(ŷ) − y_onehot               (error global, una sola vez)
  ρ_ℓ      = relu(‖h_ℓ‖ − b_ℓ) / (‖h_ℓ‖ + ε)     (culpa por línea base móvil)
  δ_ℓ      = (1 − ρ_ℓ) · (B_ℓ · e) ⊙ f′(a_ℓ)     (B_ℓ fija aleatoria — sin
                                                   weight transport, estilo DFA)
  ΔW_ℓ     = −η · δ_ℓᵀ · h_{ℓ−1} / batch

Architecture for MNIST: 784 → 256 → 128 → 64 → 32 → 10
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class SDPCLayer(nn.Module):
    """Single SDPC layer with fixed random feedback matrix B."""

    def __init__(self, in_dim: int, out_dim: int, num_classes: int = 10):
        super().__init__()
        self.in_dim = in_dim
        self.out_dim = out_dim

        # Pesos entrenables (actualización manual — sin optimizer).
        # He-init: con std fija 0.02 la señal forward se desvanece con la
        # profundidad y SDPC colapsa a azar (diagnóstico e1_diag.py: 70.2%
        # vs 32% en 1 epoch/10k). La derivación DFA necesita señal viva.
        self.W = nn.Parameter(torch.randn(out_dim, in_dim) * math.sqrt(2.0 / in_dim))
        self.bias = nn.Parameter(torch.zeros(out_dim))

        # Matriz de feedback fija aleatoria: num_classes → out_dim.
        # Es la B_ℓ del paper — nunca se entrena, no hay weight transport.
        self.register_buffer("B", torch.randn(out_dim, num_classes) * 0.1)

        # Línea base móvil para la autodeclaración de culpa
        self.register_buffer("baseline", torch.tensor(0.01))
        self.alpha = 0.05   # tasa de actualización de la línea base
        self.eps = 1e-8

        # Momentos adaptativos LOCALES (estilo Adam) para el update SDPC.
        # Siguen siendo 100% libres de backprop: solo usan el dW local de la
        # capa, igual que la literatura DFA entrena con Adam. Cierran la
        # brecha de escala entre capas que el SGD crudo no maneja (E1: 92.2%
        # con SGD+clip vs umbral 95%).
        self.register_buffer("mW", torch.zeros(out_dim, in_dim))
        self.register_buffer("vW", torch.zeros(out_dim, in_dim))
        self.register_buffer("mb", torch.zeros(out_dim))
        self.register_buffer("vb", torch.zeros(out_dim))
        self.register_buffer("t_step", torch.tensor(0))
        self.beta1, self.beta2 = 0.9, 0.999

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns: (h, a, guilt)
          h     = ReLU(W·x + bias)   (batch, out_dim)
          a     = pre-activación      (batch, out_dim)
          guilt = ρ_ℓ ∈ [0, 0.99]    escalar
        """
        a = F.linear(x, self.W, self.bias)
        h = F.relu(a)

        # Culpa estimada desde la norma de activación (proxy del error local)
        with torch.no_grad():
            norm = h.norm(dim=-1).mean()
            self.baseline = (1 - self.alpha) * self.baseline + self.alpha * norm
            guilt = F.relu(norm - self.baseline) / (norm + self.eps)
            guilt = guilt.clamp(0.0, 0.99)

        return h, a, guilt

    # Estabilización (FIX 2 del E1): sin esto hay feedback positivo
    # |W|↑ → ‖h‖↑ → updates↑ → explosión → ReLUs muertas → colapso a azar
    # tras ~1 epoch de MNIST completo. Es la limitación #4 del paper
    # ("sin garantía de convergencia"); se mitiga con clip de norma del
    # update + weight decay suave, ambos locales a la capa (sin gradiente).
    MAX_UPDATE_NORM = 1.0
    WEIGHT_DECAY = 1e-4

    @torch.no_grad()
    def sdpc_update(self, h_prev: torch.Tensor, a: torch.Tensor,
                    global_error: torch.Tensor, guilt: float, lr: float) -> None:
        """
        δ_ℓ = (1 − ρ_ℓ) · (B_ℓ @ e) ⊙ f′(a_ℓ);  ΔW = −lr · (δᵀ @ h_prev) / batch
        """
        batch = h_prev.shape[0]

        projected = global_error @ self.B.T          # (batch, out_dim)
        f_prime = (a > 0).float()                    # derivada de ReLU
        delta = (1.0 - guilt) * projected * f_prime  # (batch, out_dim)

        dW = (delta.T @ h_prev) / batch
        norm = dW.norm()
        if norm > self.MAX_UPDATE_NORM:
            dW *= self.MAX_UPDATE_NORM / norm
        db = delta.mean(dim=0)

        # Adam local por capa (bias-corrected). Solo estado local: sin
        # transporte de pesos ni información de otras capas.
        self.t_step += 1
        t = int(self.t_step)
        self.mW.mul_(self.beta1).add_(dW, alpha=1 - self.beta1)
        self.vW.mul_(self.beta2).addcmul_(dW, dW, value=1 - self.beta2)
        self.mb.mul_(self.beta1).add_(db, alpha=1 - self.beta1)
        self.vb.mul_(self.beta2).addcmul_(db, db, value=1 - self.beta2)
        mW_hat = self.mW / (1 - self.beta1 ** t)
        vW_hat = self.vW / (1 - self.beta2 ** t)
        mb_hat = self.mb / (1 - self.beta1 ** t)
        vb_hat = self.vb / (1 - self.beta2 ** t)

        self.W -= lr * mW_hat / (vW_hat.sqrt() + self.eps) + lr * self.WEIGHT_DECAY * self.W
        self.bias -= lr * mb_hat / (vb_hat.sqrt() + self.eps)


class SDPCMLP(nn.Module):
    """5-layer SDPC MLP. Trained with manual SDPC updates — no loss.backward()."""

    DEFAULT_DIMS = [784, 256, 128, 64, 32, 10]

    def __init__(self, dims: list[int] = None):
        super().__init__()
        dims = dims or self.DEFAULT_DIMS
        num_classes = dims[-1]
        self.hidden_layers = nn.ModuleList([
            SDPCLayer(dims[i], dims[i + 1], num_classes)
            for i in range(len(dims) - 2)
        ])
        # Capa de salida: lineal estándar actualizada con regla delta (tampoco usa BP)
        self.output = nn.Linear(dims[-2], dims[-1])
        nn.init.normal_(self.output.weight, std=0.02)
        # Adam local también para la capa de salida (mismo criterio que SDPCLayer)
        self.register_buffer("out_mW", torch.zeros(dims[-1], dims[-2]))
        self.register_buffer("out_vW", torch.zeros(dims[-1], dims[-2]))
        self.register_buffer("out_mb", torch.zeros(dims[-1]))
        self.register_buffer("out_vb", torch.zeros(dims[-1]))
        self.register_buffer("out_t", torch.tensor(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Inference only — returns logits."""
        h = x.view(x.shape[0], -1)
        for layer in self.hidden_layers:
            h, _, _ = layer(h)
        return self.output(h)

    @torch.no_grad()
    def train_step(self, x: torch.Tensor, y: torch.Tensor,
                   lr: float = 0.01) -> dict[str, float]:
        """One training step using SDPC rules. No autograd."""
        x = x.view(x.shape[0], -1)
        batch = x.shape[0]

        # ── Forward: colectar activaciones ──
        hiddens = [x]
        pre_acts = []
        guilts = []

        h = x
        for layer in self.hidden_layers:
            h, a, g = layer(h)
            hiddens.append(h)
            pre_acts.append(a)
            guilts.append(g.item())

        logits = self.output(h)

        # ── Error global (one-hot) ──
        y_hot = F.one_hot(y, num_classes=logits.shape[-1]).float()
        global_error = F.softmax(logits, dim=-1) - y_hot  # (batch, 10)

        # ── Update capas ocultas: SDPC ──
        for i, layer in enumerate(self.hidden_layers):
            layer.sdpc_update(h_prev=hiddens[i], a=pre_acts[i],
                              global_error=global_error, guilt=guilts[i], lr=lr)

        # ── Update capa de salida: regla delta + Adam local ──
        dW = (global_error.T @ hiddens[-1]) / batch
        db = global_error.mean(dim=0)
        self.out_t += 1
        t = int(self.out_t)
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.out_mW.mul_(b1).add_(dW, alpha=1 - b1)
        self.out_vW.mul_(b2).addcmul_(dW, dW, value=1 - b2)
        self.out_mb.mul_(b1).add_(db, alpha=1 - b1)
        self.out_vb.mul_(b2).addcmul_(db, db, value=1 - b2)
        self.output.weight -= lr * (self.out_mW / (1 - b1 ** t)) / \
            ((self.out_vW / (1 - b2 ** t)).sqrt() + eps)
        self.output.bias -= lr * (self.out_mb / (1 - b1 ** t)) / \
            ((self.out_vb / (1 - b2 ** t)).sqrt() + eps)

        # ── Métricas ──
        loss = F.cross_entropy(logits, y).item()
        acc = (logits.argmax(-1) == y).float().mean().item()
        return {"loss": loss, "acc": acc, "avg_guilt": sum(guilts) / len(guilts)}
