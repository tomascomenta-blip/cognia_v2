"""exp049 — DTP: Difference Target Propagation (Lee et al. 2015).

En vez de retro-propagar gradientes, cada capa recibe un TARGET de actividad y aprende con una
pérdida puramente LOCAL ||f_l(h_{l-1}) - t_l||². El target de la salida es un paso de gradiente
del CE respecto de los logits SOLAMENTE (t_L = h_L - η·(softmax-onehot): cantidad local de la
capa de salida, sin backward por la red); hacia abajo los targets se traducen con INVERSAS
APRENDIDAS g_l más la corrección de diferencia t_{l-1} = h_{l-1} + g_l(t_l) - g_l(h_l), que
cancela el sesgo de una inversa imperfecta (g_l(h_l) ≈ h_{l-1}) — la marca de DTP vs target-prop
vainilla. Las inversas se entrenan por reconstrucción DENOISING local: g_l(f_l(h+ruido)) ≈ h+ruido.

Ocultas con tanh, NO ReLU como el protocolo (desviación documentada): ReLU mata la mitad del
dominio y una inversa aprendida no puede reconstruirla — DTP se desestabiliza; tanh es biyectiva
y acotada, que es lo que usa la literatura DTP (Lee et al. usan tanh/sigmoid). Salida lineal (logits).

Autograd LOCAL por capa (permitido por el protocolo cuando la regla es local — este es el caso):
cada pérdida se computa recreando SOLO su capa sobre entradas SIN historia (hs y targets se
calculan bajo no_grad), así backward() no tiene ningún camino inter-capa que cruzar — sumar las
pérdidas locales y hacer un backward es idéntico a un backward por capa. Forward e inversas se
entrenan AMBAS en cada batch: inversas primero (con los pesos forward frescos), luego targets y
update forward.

TUNING (1 pase, documentado): con lr forward 1e-3 DTP arranca en frío (epoch 1 del smoke = 0.067:
las inversas nacen aleatorias y los targets ocultos son ruido las primeras ~30 updates; el
diagnóstico con 5 epochs mostró que SÍ aprende, 0.80, solo que tarde). Se probaron 4 variantes
un-knob (lr_f 3e-3 / warm-up de inversas / η=1.0 / lr ambas 3e-3): lr_f=3e-3 domina en TODOS los
horizontes (0.368/0.709/0.819 en epochs 1-3 vs 0.067/0.356/0.538 del baseline) y es estable a 10
epochs (0.85 sin oscilar) — es un fix de velocidad de convergencia, no sobre-ajuste del smoke.
Las inversas quedan en lr=1e-3 (subirlas a 3e-3 empeoró el horizonte largo: targets más ruidosos).
"""
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

from cognia_x.experiments.exp049_learning_rules.common import batches, accuracy

ETA = 0.5     # paso del target en la salida (spec 0.5-1.0; chico = targets alcanzables = estable)
SIGMA = 0.2   # ruido del denoising: cubre un entorno de h sin salirse del rango útil de tanh
LR_F = 3e-3   # Adam forward: 1e-3 arranca en frío — ver TUNING en el docstring
LR_G = 1e-3   # Adam inversas: subirlo hace targets más ruidosos (empeoró el horizonte largo)


def train(data, cfg, seed, log=print):
    x_tr, y_tr, x_te, y_te = data
    device = x_tr.device
    torch.manual_seed(seed)
    dims = [784] + list(cfg["hidden"]) + [cfg["n_classes"]]
    L = len(dims) - 1

    # forward f_l con el init default de nn.Linear (~U(±1/sqrt(fan_in)): la escala correcta para
    # tanh; He es para ReLU). Inversas g_l solo para las capas 1..L-1 — la capa 0 no la necesita
    # porque la entrada no recibe target. gs[l-1] invierte la capa l (dims[l+1] -> dims[l]) con
    # salida tanh, porque lo que aproxima (una h oculta) es tanh-acotada.
    fs = [nn.Linear(dims[l], dims[l + 1]).to(device) for l in range(L)]
    gs = [nn.Linear(dims[l + 1], dims[l]).to(device) for l in range(1, L)]
    opt_f = torch.optim.Adam([p for m in fs for p in m.parameters()], lr=LR_F)
    opt_g = torch.optim.Adam([p for m in gs for p in m.parameters()], lr=LR_G)

    def f_l(l, h):
        z = fs[l](h)
        return z if l == L - 1 else torch.tanh(z)   # ocultas tanh, salida en logits

    def g_l(l, v):
        return torch.tanh(gs[l - 1](v))

    @torch.no_grad()
    def forward(x):
        hs = [x]
        for l in range(L):
            hs.append(f_l(l, hs[l]))
        return hs

    def predict(x):
        return forward(x)[-1]

    epoch_log, updates = [], 0
    t0 = time.time()
    for ep in range(1, cfg["epochs"] + 1):
        te0 = time.time()
        for x, y in batches(x_tr, y_tr, cfg["batch"], seed * 1000 + ep):
            hs = forward(x)   # sin historia de autograd: las pérdidas locales no pueden cruzar capas

            # (1) inversas: denoising local g_l(f_l(h+ruido)) ≈ h+ruido. El paso por f_l va bajo
            # no_grad — el error de reconstrucción entrena SOLO a g, nunca al forward.
            loss_g = 0.0
            for l in range(1, L):
                hn = hs[l] + SIGMA * torch.randn_like(hs[l])
                with torch.no_grad():
                    fwd = f_l(l, hn)
                loss_g = loss_g + F.mse_loss(g_l(l, fwd), hn)
            opt_g.zero_grad(set_to_none=True)
            loss_g.backward()
            opt_g.step()

            # (2) targets de arriba hacia abajo (constantes: sin grafo)
            with torch.no_grad():
                y1h = F.one_hot(y, cfg["n_classes"]).to(x.dtype)
                ts = [None] * (L + 1)
                ts[L] = hs[L] - ETA * (F.softmax(hs[L], dim=1) - y1h)   # grad CE de la salida SOLO
                for l in range(L - 1, 0, -1):
                    ts[l] = hs[l] + g_l(l, ts[l + 1]) - g_l(l, hs[l + 1])   # corrección de diferencia

            # (3) forward: pérdida local por capa hacia su target
            loss_f = 0.0
            for l in range(L):
                loss_f = loss_f + F.mse_loss(f_l(l, hs[l]), ts[l + 1])
            opt_f.zero_grad(set_to_none=True)
            loss_f.backward()
            opt_f.step()
            updates += 2   # por batch: un step de Adam forward + uno de inversas

        acc = accuracy(predict, x_te, y_te)
        epoch_log.append({"epoch": ep, "test_acc": round(acc, 4), "wall_s": round(time.time() - te0, 1)})
        log(f"  [dtp seed={seed}] epoch {ep}/{cfg['epochs']} test_acc={acc:.4f}")
    return {"test_acc": epoch_log[-1]["test_acc"], "epoch_log": epoch_log,
            "wall_s": round(time.time() - t0, 1), "updates": updates,
            "extra": {"eta": ETA, "sigma": SIGMA,
                      "opt": "Adam lr_f=3e-3 / lr_g=1e-3 (tuning 1: lr_f 1e-3 arranca en frio, "
                             "0.067 en el smoke; 3e-3 domina en todos los horizontes)",
                      "f": "tanh en ocultas (ReLU no invertible — ver docstring), salida lineal",
                      "updates_nota": "2 steps por batch: forward + inversas (ambas cada batch)"}}
