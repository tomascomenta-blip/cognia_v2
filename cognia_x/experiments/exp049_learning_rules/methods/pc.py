"""exp049 — PC: Predictive coding / inference learning (Rao & Ballard 1999; Whittington & Bogacz 2017).

Cada capa tiene NODOS DE VALOR v_l (acá: pre-activaciones, así el forward puro coincide con el
MLP de bp.py) y errores de predicción eps_{l+1} = v_{l+1} - W_l·f(v_l) - b_l. Por batch:
(1) init v_l = forward puro (todos los eps quedan en 0), (2) clamp del target en la salida,
(3) T iteraciones de inferencia = descenso sobre la energía E = ½Σ|eps_l|² SOLO en los nodos
ocultos: dv_l = -eps_l + f'(v_l)⊙(eps_{l+1}@W_l), (4) update de pesos LOCAL con los eps
finales: grad W_l = -eps_{l+1}^T f(v_l). El crédito NO llega por un backward diferenciando la
red end-to-end sino por la dinámica recurrente de los nodos; cada ΔW_l usa solo cantidades de
las capas l y l+1. Honesto: PC SÍ usa W^T en la inferencia (conectividad simétrica top-down,
a diferencia de DFA) — lo que elimina es el pase backward global, no el transporte de pesos.
TUNING (1 pase, documentado): el clamp one-hot con energía MSE quedó a 0.52× de BP en el smoke
(0.344 vs 0.661) — MSE-a-logits aprende lento en pocas updates. Se pasó al equivalente CE que
el protocolo permite: la salida no es un nodo libre, su error es eps_L = onehot - softmax(mu_L)
(el gradiente de CE con el signo de la convención local); el resto de las ecuaciones no cambia.
CERO autograd (ni end-to-end ni local): todo bajo torch.no_grad(), gradientes asignados a
p.grad para un Adam estándar (receta He-init + Adam local que ya funcionó en SDPC y DFA).
El costo esperado es ~T× BP (T pases de eps por batch) — ESE es el dato que H-BIO-3 tenía
solo de literatura (~100×) y acá se mide de verdad.
"""
import time

import torch
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy

T_INFER = 16   # iteraciones de inferencia por batch: cota directa del sobrecosto vs BP
LR_X = 0.1     # paso de los nodos de valor (Whittington & Bogacz usan este orden)


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    torch.manual_seed(seed)
    dims = [784] + list(cfg["hidden"]) + [cfg["n_classes"]]
    L = len(dims) - 1

    # He-init (ReLU) como tensores planos; el update lo hace Adam vía .grad asignado a mano
    Ws = [torch.randn(dims[i + 1], dims[i], device=device) * (2.0 / dims[i]) ** 0.5
          for i in range(L)]
    bs = [torch.zeros(dims[i + 1], device=device) for i in range(L)]
    opt = torch.optim.Adam(Ws + bs, lr=1e-3)

    # f=ReLU en ocultas, identidad en la entrada: los v_l son pre-activaciones, así la
    # predicción v_{l+1} = W_l·f(v_l)+b_l reproduce exactamente el MLP del baseline
    def f(v, l):
        return v if l == 0 else torch.relu(v)

    @torch.no_grad()
    def forward(x):
        vs = [x]
        for l in range(L):
            vs.append(f(vs[l], l) @ Ws[l].t() + bs[l])
        return vs

    def predict(x):
        return forward(x)[-1]

    @torch.no_grad()
    def errores(vs, mu1, y1h):
        # eps[l] = error de la capa l+1; mu1 se precomputa porque v_0 (entrada) está clampeada
        # y recalcular su predicción T veces sería inflar el costo artificialmente.
        # Capa de salida: error CE (onehot - softmax) en vez de nodo libre clampeado — ver TUNING
        eps = [vs[1] - mu1] + [vs[l + 1] - (f(vs[l], l) @ Ws[l].t() + bs[l])
                               for l in range(1, L - 1)]
        mu_out = f(vs[L - 1], L - 1) @ Ws[L - 1].t() + bs[L - 1]
        eps.append(y1h - F.softmax(mu_out, dim=1))
        return eps

    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            with torch.no_grad():
                vs = forward(x)                                            # (1) init: eps = 0
                y1h = F.one_hot(y, cfg["n_classes"]).to(x.dtype)           # (2) target en salida
                mu1 = x @ Ws[0].t() + bs[0]
                for _ in range(T_INFER):                                   # (3) inferencia
                    eps = errores(vs, mu1, y1h)
                    for l in range(1, L):                                  # solo nodos ocultos
                        vs[l] += LR_X * (-eps[l - 1] + (vs[l] > 0).to(x.dtype) * (eps[l] @ Ws[l]))
                eps = errores(vs, mu1, y1h)                                # (4) update LOCAL
                # ÷ batch para que el lr no dependa del batch (mismo criterio que dfa.py)
                for l in range(L):
                    Ws[l].grad = -eps[l].t() @ f(vs[l], l) / len(x)
                    bs[l].grad = -eps[l].sum(0) / len(x)
            opt.step()
            opt.zero_grad(set_to_none=True)
            updates += 1
        acc = accuracy(predict, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [pc seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates,
            "extra": {"T_infer": T_INFER, "lr_x": LR_X, "f": "relu (identidad en la entrada)",
                      "salida": "error CE: onehot - softmax(mu_L) (tuning 1: el clamp one-hot/MSE "
                                "dio 0.344 vs 0.661 de bp en smoke)",
                      "opt": "Adam lr=1e-3",
                      "nota": "v_l = pre-activaciones; prediccion = forward puro"}}
