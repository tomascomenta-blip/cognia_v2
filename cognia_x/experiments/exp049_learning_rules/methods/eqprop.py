"""exp049 — EqProp: Equilibrium Propagation (Scellier & Bengio 2017).

Red de ENERGÍA tipo Hopfield por capas: E = Σ_l ||s_l||²/2 − Σ_l ρ(s_l)^T W_l ρ(s_{l+1}) − Σ b·ρ(s),
con ρ = hard-sigmoid (clamp(x,0,1)) y estados s_l ∈ [0,1]. Dos fases por batch:
(1) LIBRE: relajar ds = −∂E/∂s (T1 pasos, dt=0.5) con la entrada clampeada a x;
(2) NUDGED: seguir relajando desde ese equilibrio agregando −β·∂C/∂s_out en la salida
(C = ½||s_out − onehot||², T2 pasos, β=0.5). El update es LOCAL — teorema del paper: el
contraste de co-activaciones entre las dos fases aproxima el gradiente de C sin ningún
backward global: ΔW_l ∝ (ρ(s_l^β)^T ρ(s_{l+1}^β) − ρ(s_l^0)^T ρ(s_{l+1}^0))/β. Cada peso solo
ve la actividad de SUS dos capas. CERO autograd (ni local): la "derivada" ES la diferencia
entre fases; todo corre bajo torch.no_grad().

DESVIACIÓN DE TOPOLOGÍA (documentada acá y en README): 784→256→10 (una oculta) en vez del MLP
común 784→256→128→64→32→10 — el settling multi-capa profundo no converge en un T1 razonable
(Scellier & Bengio necesitan T1=500 para 3 ocultas; con este presupuesto es inviable).

Implementación: como los estados viven clampeados en [0,1], ρ(s)=s y ρ'(s)=1 dentro de la caja,
así que la dinámica −∂E/∂s se reduce a s ← clamp(s + dt·(presión − s), 0, 1) con
presión_l = ρ(s_{l-1})@W_{l-1} + s_{l+1}@W_l^T + b_l (misma reducción que la implementación de
referencia del paper; los W son SIMÉTRICOS: la misma matriz empuja hacia arriba y hacia abajo).
SGD con lr por capa 0.1/0.05 (los del paper para 1 oculta) — no hizo falta el pase de tuning.
El COSTO honesto: cada batch paga (T1+T2) pasadas de settling en vez de 1 forward, y la
PREDICCIÓN también paga T1 (hay que relajar la red para poder leer s_out).
"""
import time

import torch
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy

HIDDEN = [256]     # desviación de topología documentada arriba (una sola capa oculta)
T1, T2 = 25, 8     # pasos de settling libre / nudged: cota directa del sobrecosto vs BP
DT = 0.5           # paso de integración de ds = −∂E/∂s
BETA = 0.5         # fuerza del nudge hacia el target
LRS = [0.1, 0.05]  # lr por capa (EqProp clásico usa lr distintos por capa; estos son del paper)


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    torch.manual_seed(seed)
    dims = [784] + HIDDEN + [cfg["n_classes"]]
    L = len(dims) - 1  # número de matrices W_l (conectan capa l ↔ capa l+1)

    # Glorot uniforme: los W son conexiones simétricas de una red de energía (empujan en ambas
    # direcciones durante el settling), no un forward ReLU — He-init no aplica acá
    Ws, bs = [], []
    for i in range(L):
        lim = (6.0 / (dims[i] + dims[i + 1])) ** 0.5
        Ws.append((torch.rand(dims[i], dims[i + 1], device=device) * 2 - 1) * lim)
        bs.append(torch.zeros(dims[i + 1], device=device))

    @torch.no_grad()
    def settle(x, T, beta=0.0, y1h=None, ss=None):
        """Relaja los estados libres hacia el mínimo de E (+β·C si nudged). Devuelve [ρ(s_0),...,s_L].
        Barrido secuencial (Gauss-Seidel: cada capa ve al vecino ya actualizado) porque converge
        en menos pasos que el update síncrono."""
        rx = x.clamp(0, 1)  # ρ de la entrada clampeada: fija, se computa UNA vez fuera del loop
        if ss is None:
            ss = [torch.zeros(len(x), d, device=device) for d in dims[1:]]
        acts = [rx] + ss    # acts[l] = ρ(s_l); en las capas libres ρ(s)=s porque viven en [0,1]
        for _ in range(T):
            for l in range(1, L + 1):
                p = acts[l - 1] @ Ws[l - 1] + bs[l - 1]
                if l < L:
                    p = p + acts[l + 1] @ Ws[l].t()      # presión top-down por el MISMO W (simetría)
                if beta and l == L:
                    p = p + beta * (y1h - acts[l])       # nudge: −β·∂C/∂s_out = β(onehot − s_out)
                acts[l] = (acts[l] + DT * (p - acts[l])).clamp_(0, 1)
        return acts

    def predict(x):
        return settle(x, T1)[-1]  # leer s_out del equilibrio libre: la inferencia cuesta T1 pasadas

    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            with torch.no_grad():
                y1h = F.one_hot(y, cfg["n_classes"]).to(x.dtype)
                free = settle(x, T1)
                # la fase nudged ARRANCA del equilibrio libre (clone: hay que conservar ambos)
                nud = settle(x, T2, beta=BETA, y1h=y1h, ss=[a.clone() for a in free[1:]])
                # update LOCAL: contraste de co-activaciones ÷β (estimador) ÷batch (como dfa/pc)
                for l in range(L):
                    k = LRS[l] / (BETA * len(x))
                    Ws[l] += k * (nud[l].t() @ nud[l + 1] - free[l].t() @ free[l + 1])
                    bs[l] += k * (nud[l + 1] - free[l + 1]).sum(0)
            updates += 1
        acc = accuracy(predict, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [eqprop seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates,
            "extra": {"topologia": "784->256->10 (desviación documentada: el settling profundo "
                                   "no converge con T1 presupuestable)",
                      "T1": T1, "T2": T2, "dt": DT, "beta": BETA, "lrs": LRS,
                      "opt": "SGD lr por capa (paper, 1 oculta)",
                      "costo": f"cada batch paga T1+T2={T1 + T2} pasadas de settling y la "
                               f"predicción paga T1={T1} (vs 1 forward de BP)"}}
