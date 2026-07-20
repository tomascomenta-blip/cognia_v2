"""exp049 — DFA: Direct Feedback Alignment (Lillicrap 2016 / Nøkland 2016).

Regla LOCAL, sin transporte de pesos: el error de salida e = softmax(logits) - onehot(y) se
proyecta DIRECTO a cada capa oculta con matrices aleatorias FIJAS B_l (jamás entrenadas), en vez
de retro-propagarlo por W^T capa a capa. delta_l = (e @ B_l) * relu'(z_l); grad W_l = delta_l^T
@ h_{l-1}. El alineamiento emerge porque W se acomoda al feedback fijo, no al revés. CERO
autograd (ni end-to-end ni local): los gradientes se computan a mano bajo torch.no_grad() y se
asignan a p.grad para un Adam estándar.

Pase de tuning (permitido por protocolo, 1 solo; medido en esta máquina, seeds 42/7/123):
  1. Capa de salida inicializada en CERO (no He). Con He en la salida los logits arrancan
     grandes y confiados, e satura, y el lazo DFA+Adam explota (loss 2.8 -> 80 en 30 updates,
     acc 0.05 = bajo azar) — el mismo feedback positivo |W|↑→‖h‖↑ que documentó el FIX 2 del
     SDPC. Con salida en cero, e es informativo desde el paso 1. Las ocultas siguen He (spec).
  2. B_l con filas ORTONORMALES (QR de una gaussiana, sigue siendo aleatoria fija por seed):
     10 vectores gaussianos en R^32 se solapan mucho y mezclan el crédito entre clases en las
     capas angostas; ortonormalizar sube el arranque en las 3 seeds (~+0.05 acc en epoch 1).
  3. lr=2e-3 ocultas / 1e-2 salida (la spec pedía 1e-3 parejo). Con 1e-3 parejo el arranque es
     lento (epoch 1 con 2000 muestras: 0.44-0.58 según el draw de B; el smoke pide >=0.50) y la
     única config cuyo MIN sobre 6 draws cruza 0.50 es esta (min 0.517). La salida es la única
     capa con gradiente exacto: dársela más rápida hace que e sea útil antes y frena la deriva
     ciega de las ocultas (‖h1‖ 86 -> 69 en epoch 1). Costo medido en la corrida completa
     (60k x 5 epochs, seeds 42/7): 0.9385/0.9426 vs 0.9531 con 1e-3 parejo (~-0.01, el ratio
     vs BP queda ~0.96 > umbral 0.95); se paga transitorio más rápido con final apenas menor.
"""
import time

import torch
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    torch.manual_seed(seed)
    dims = [784] + list(cfg["hidden"]) + [cfg["n_classes"]]

    # ocultas He-init (ReLU); salida en cero (ver docstring, punto 1). Tensores planos: el
    # update lo hace Adam vía .grad asignado a mano.
    Ws = [torch.randn(dims[i + 1], dims[i], device=device) * (2.0 / dims[i]) ** 0.5
          for i in range(len(dims) - 2)]
    Ws.append(torch.zeros(dims[-1], dims[-2], device=device))
    bs = [torch.zeros(dims[i + 1], device=device) for i in range(len(dims) - 1)]
    # feedback aleatorio FIJO por seed, filas ortonormalizadas (docstring, punto 2)
    Bs = [torch.linalg.qr(torch.randn(dims[i + 1], cfg["n_classes"], device=device))[0].t().contiguous()
          for i in range(len(dims) - 2)]
    opt = torch.optim.Adam([{"params": Ws[:-1] + bs[:-1], "lr": 2e-3},
                            {"params": [Ws[-1], bs[-1]], "lr": 1e-2}])

    @torch.no_grad()
    def forward(x):
        """Forward manual guardando pre-activaciones z_l (para relu') y activaciones h_l."""
        hs, zs = [x], []
        for i, (W, b) in enumerate(zip(Ws, bs)):
            z = hs[-1] @ W.t() + b
            zs.append(z)
            hs.append(torch.relu(z) if i < len(Ws) - 1 else z)  # la salida queda en logits
        return zs, hs

    def predict(x):
        return forward(x)[1][-1]

    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            with torch.no_grad():
                zs, hs = forward(x)
                # error exacto de CE+softmax, ÷ batch para que el lr no dependa del batch
                e = (F.softmax(hs[-1], dim=1) - F.one_hot(y, cfg["n_classes"]).to(x.dtype)) / len(x)
                # capa de salida: gradiente local exacto (el error le llega directo, sin feedback)
                Ws[-1].grad = e.t() @ hs[-2]
                bs[-1].grad = e.sum(0)
                # capas ocultas: error proyectado con B_l fija, gateado por relu'(z_l)
                for l in range(len(Ws) - 1):
                    delta = (e @ Bs[l]) * (zs[l] > 0).to(x.dtype)
                    Ws[l].grad = delta.t() @ hs[l]
                    bs[l].grad = delta.sum(0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            updates += 1
        acc = accuracy(predict, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [dfa seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates,
            "extra": {"feedback": "B_l gaussiana ortonormalizada (QR), fija por seed",
                      "opt": "Adam lr=2e-3 ocultas / 1e-2 salida",
                      "tuning_pass": "salida zero-init + B ortonormal + lrs 2e-3/1e-2 (docstring)"}}
