"""exp049 — ES: OpenAI Evolution Strategies antitético (Salimans et al. 2017).

Método de CAJA NEGRA, cero gradiente (ni autograd end-to-end ni local: TODO corre bajo
torch.no_grad()). La red entera vive como un vector plano θ. Por generación: N=30 pares
antitéticos ε_i ~ N(0, I); fitness f = -CE(model(x; θ ± σ·ε_i), y) evaluada sobre EL MISMO
minibatch para las 2N corridas (common random numbers: el ruido del minibatch se cancela en
la diferencia antitética y solo queda la señal direccional). Rank-shaping: las 2N fitness se
convierten a utilidades centradas en [-0.5, 0.5] (invariante a la escala de la CE, robusto a
outliers). Gradiente estimado g = Σ_i (u_i⁺ - u_i⁻)·ε_i / (2Nσ) con σ=0.02, y el update lo
aplica Adam(lr=α=0.01) sobre -g (la spec permite Adam sobre el update estimado; Salimans
también lo usa — estabiliza la escala del paso cuando ‖g‖ varía entre generaciones).

Decisiones documentadas (spec exp049):
- minibatch = batch del cfg (64), no 256: con common random numbers el tamaño del minibatch
  casi no cambia el ruido del RANKING (se cancela en la resta antitética); el error dominante
  es proyectar el gradiente a solo N=30 direcciones en D≈245k. A igual presupuesto de
  muestras/reloj, minibatch chico = ~4× más generaciones (updates), que es lo que a ES le
  falta a esta escala de parámetros.
- init: ocultas He (ReLU), capa de salida en CERO — mismo precedente que dfa.py: con salida
  He los logits arrancan grandes y confiados, la CE satura y el ranking pierde información;
  con salida cero la primera generación ya ordena direcciones útiles del readout.
- presupuesto: si cfg trae "wall_budget_s" (run_bench lo fija a 3× el wall de BP), corta por
  reloj y reporta lo alcanzado en extra["generations"]; si no (smoke), corre
  ceil(epochs·n_train/minibatch) generaciones (1 minibatch consumido por generación) con
  tope duro de 60 s.
- epoch_log: un punto por época-equivalente (samples/n_train) y, en modo presupuesto, también
  cada ~20% del reloj; "epoch" es fraccional (2 decimales) porque ES no tiene épocas reales.
"""
import math
import time

import torch
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy

N_PAIRS = 30        # spec: 30 pares antitéticos = 60 evaluaciones por generación
SIGMA = 0.02        # spec
ALPHA = 0.01        # spec
SMOKE_MAX_S = 60.0  # tope duro cuando no hay wall_budget_s


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    torch.manual_seed(seed)
    dims = [784] + list(cfg["hidden"]) + [cfg["n_classes"]]
    n_layers = len(dims) - 1
    mb = min(cfg["batch"], len(x_tr))  # batch del cfg (docstring: más generaciones > batch grande)

    # θ plano: ocultas He, salida cero (docstring). slots = (offset, shape) para re-armar
    # cada W/b como VISTA del vector perturbado, sin copias dentro del forward.
    pieces, slots, off = [], [], 0
    for i in range(n_layers):
        W = (torch.randn(dims[i + 1], dims[i], device=device) * (2.0 / dims[i]) ** 0.5
             if i < n_layers - 1 else torch.zeros(dims[i + 1], dims[i], device=device))
        for t in (W, torch.zeros(dims[i + 1], device=device)):
            pieces.append(t.reshape(-1))
            slots.append((off, t.shape))
            off += t.numel()
    theta = torch.cat(pieces)
    opt = torch.optim.Adam([theta], lr=ALPHA)

    def forward(x, flat):
        # matmuls por perturbación completa (todo el minibatch de una), como pide la spec
        h = x
        for i in range(n_layers):
            (ow, sw), (ob, sb) = slots[2 * i], slots[2 * i + 1]
            z = h @ flat[ow:ow + sw.numel()].view(sw).t() + flat[ob:ob + sb.numel()]
            h = torch.relu(z) if i < n_layers - 1 else z
        return h

    def predict(x):
        return forward(x, theta)

    n_train = len(x_tr)
    budget = cfg.get("wall_budget_s") or None
    g_target = None if budget else math.ceil(cfg["epochs"] * n_train / mb)
    max_s = float(budget) if budget else SMOKE_MAX_S

    epoch_log, gen, samples, data_pass, logged_at = [], 0, 0, 0, -1
    it = iter(())
    next_epoch = n_train
    tick = max_s / 5 if budget else None  # en modo presupuesto, log cada ~20% del reloj
    next_tick = tick if budget else float("inf")
    t0 = t_seg = time.time()
    with torch.no_grad():
        while (time.time() - t0) < max_s and (g_target is None or gen < g_target):
            try:
                xb, yb = next(it)
            except StopIteration:  # se agotó la pasada: re-barajar determinista (como bp)
                data_pass += 1
                it = batches(x_tr, y_tr, mb, seed * 1000 + data_pass)
                xb, yb = next(it)

            # población antitética: misma E para ± (mirrored) y mismo minibatch para las 2N
            E = torch.randn(N_PAIRS, theta.numel(), device=device)
            fit = torch.empty(2 * N_PAIRS, device=device)
            for i in range(N_PAIRS):
                fit[2 * i] = -F.cross_entropy(forward(xb, torch.add(theta, E[i], alpha=SIGMA)), yb)
                fit[2 * i + 1] = -F.cross_entropy(forward(xb, torch.sub(theta, E[i], alpha=SIGMA)), yb)
            # utilidades centradas por rango (suma cero): mayor fitness → mayor utilidad
            u = fit.argsort().argsort().to(theta.dtype) / (2 * N_PAIRS - 1) - 0.5
            g = ((u[0::2] - u[1::2]) @ E) / (2 * N_PAIRS * SIGMA)
            theta.grad = -g  # Adam MINIMIZA; ascendemos el fitness
            opt.step()
            opt.zero_grad(set_to_none=True)
            gen += 1
            samples += len(xb)

            elapsed = time.time() - t0
            if samples >= next_epoch or elapsed >= next_tick:
                acc = accuracy(predict, x_te, y_te)
                epoch_log.append({"epoch": round(samples / n_train, 2), "test_acc": round(acc, 4),
                                  "wall_s": round(time.time() - t_seg, 1)})
                log(f"  [es seed={seed}] gen={gen} epoch~{samples / n_train:.2f} test_acc={acc:.4f}")
                t_seg = time.time()
                logged_at = gen
                next_epoch = (samples // n_train + 1) * n_train
                next_tick = (elapsed // tick + 1) * tick if budget else float("inf")

        if logged_at != gen:  # punto final en el corte (garantiza >=1 entrada en epoch_log)
            acc = accuracy(predict, x_te, y_te)
            epoch_log.append({"epoch": round(samples / n_train, 2), "test_acc": round(acc, 4),
                              "wall_s": round(time.time() - t_seg, 1)})
            log(f"  [es seed={seed}] gen={gen} (corte) test_acc={acc:.4f}")

    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": gen,
            "extra": {"generations": gen, "evals_forward": 2 * N_PAIRS * gen, "minibatch": mb,
                      "n_pairs": N_PAIRS, "sigma": SIGMA, "alpha": ALPHA, "params": theta.numel(),
                      "opt": "Adam(lr=0.01) sobre -g estimado (permitido por spec)",
                      "budget": (f"wall_budget_s={max_s:.1f}" if budget
                                 else f"{g_target} generaciones (= {cfg['epochs']} epoch-equiv), tope {SMOKE_MAX_S:.0f}s")}}
