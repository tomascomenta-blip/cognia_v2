"""
exp137 — Profundidad ADAPTATIVA (PonderNet) vs FIJA: ¿ahorra cómputo?

CONTEXTO (no re-derivar): el A/B de arquitectura XARCH ya midió que un loop de
profundidad con nº de vueltas FIJO (looped2x4) NO ahorra cómputo — 4 vueltas ×
2 capas = mismo FLOP que 8 capas reales, mismo tok/s (H-LOOP "cae", el cuello es
cómputo no params). El prior dejó UNA puerta abierta: el loop de vueltas FIJAS
paga el máximo SIEMPRE; un loop ADAPTATIVO que corta temprano en inputs fáciles
usaría menos cómputo EN PROMEDIO. Este experimento testea exactamente eso.

TAREA (genuinamente secuencial, SIN forma cerrada de 1 paso — v2 tras
detectar que f^K(x)=(x+3K) mod 10 SÍ tenía forma cerrada y el modelo la
resolvía en 1 paso): leer una secuencia de dígitos [a_1..a_n, STOP, pad...]
UN TOKEN POR PASO y devolver Σa_i mod 10. La longitud n∈1..KMAX VARÍA y NO se
da como input: el modelo debe iterar leyendo tokens y HALTAR al ver STOP. Como
cada vuelta lee un token nuevo del stream, un MLP no puede atajar — necesita n
pasos reales. La profundidad necesaria = n (dificultad variable, input-dep).

MODELO: celda recurrente de pesos COMPARTIDOS que en el paso t lee el token t
del stream y acumula en el estado. Dos variantes:
  - fixed: siempre KMAX vueltas (lee todo el stream padded, paga el máximo).
  - ponder: cabeza de halting (PonderNet, Banino 2021) da prob de parar por
    paso; cómputo esperado = Σ prob-de-seguir; pérdida PonderNet (mezcla
    ponderada por la distribución de halting + reg λ hacia menos pasos).

PREDICCIÓN CONGELADA (antes de correr): ambas alcanzan alta accuracy; la ponder
usa un nº de pasos PROMEDIO < KMAX (ahorro de cómputo) Y correlaciona los pasos
con K (piensa más en lo difícil). Falsación: si ponder usa ~KMAX pasos igual, o
no correlaciona con K, el ahorro no se materializa y se reporta.

CPU-first, determinista (seed fija). Sin GPU. ~2-4 min en el i3.
"""
import json
import math
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

SEED = 137
KMAX = 8            # longitud maxima de la secuencia = profundidad maxima
VOCAB = 10          # digitos 0..9
STOP = 10           # token de fin de secuencia
PAD = 11            # relleno tras STOP
NTOK = 12           # tamaño del vocabulario (0..9 + STOP + PAD)
D = 48              # dim del estado
STEPS = 6000        # pasos de entreno
BATCH = 128
LR = 3e-3
PONDER_LAMBDA = 0.06   # reg hacia menos pasos (geometrica prior de halting)
torch.manual_seed(SEED)


def make_batch(n, kmax=KMAX, device="cpu", gen=None):
    """Devuelve (seq [n, kmax], length [n], target [n]).
    seq = a_1..a_L, STOP, PAD.. ; length=L∈1..kmax ; target = Σa_i mod 10."""
    L = torch.randint(1, kmax + 1, (n,), generator=gen)
    seq = torch.full((n, kmax), PAD, dtype=torch.long)
    y = torch.zeros(n, dtype=torch.long)
    for i in range(n):
        li = int(L[i])
        digits = torch.randint(0, VOCAB, (li,), generator=gen)
        seq[i, :li] = digits
        if li < kmax:
            seq[i, li] = STOP
        y[i] = int(digits.sum() % VOCAB)
    return seq.to(device), L.to(device), y.to(device)


class PonderCell(nn.Module):
    """Celda recurrente de pesos COMPARTIDOS que lee la secuencia un token por
    paso y acumula. En el paso t: estado' = MLP(estado, embed(seq[:,t])); una
    cabeza predice Σ mod 10 desde el estado; (ponder) otra da prob de parar.
    Como cada paso consume un token NUEVO, no hay atajo de 1 paso — hay que
    iterar hasta el STOP (profundidad = longitud, variable por input)."""

    def __init__(self, d=D, kmax=KMAX, ponder=True):
        super().__init__()
        self.ponder = ponder
        self.kmax = kmax
        self.emb = nn.Embedding(NTOK, d)
        self.cell = nn.Sequential(nn.Linear(2 * d, 2 * d), nn.GELU(),
                                  nn.Linear(2 * d, d))
        self.norm = nn.LayerNorm(d)
        self.out = nn.Linear(d, VOCAB)
        self.halt = nn.Linear(d, 1) if ponder else None

    def forward(self, seq, _len=None):
        B = seq.shape[0]
        h = torch.zeros(B, self.emb.embedding_dim)
        logits_steps, halt_steps = [], []
        for t in range(self.kmax):
            tok = self.emb(seq[:, t])                      # token del paso t
            h = self.norm(h + self.cell(torch.cat([h, tok], dim=-1)))
            logits_steps.append(self.out(h))
            if self.ponder:
                halt_steps.append(torch.sigmoid(self.halt(h)).squeeze(-1))
        return logits_steps, halt_steps


def ponder_halting_dist(halt_steps):
    """Distribucion p_n de parar EXACTAMENTE en el paso n (PonderNet):
    p_n = halt_n * Π_{j<n}(1 - halt_j); el ultimo paso absorbe el resto."""
    N = len(halt_steps)
    remain = torch.ones_like(halt_steps[0])
    p = []
    for n in range(N):
        if n < N - 1:
            pn = halt_steps[n] * remain
            remain = remain * (1 - halt_steps[n])
        else:
            pn = remain  # el ultimo paso se queda con toda la masa restante
        p.append(pn)
    return torch.stack(p, dim=1)   # (batch, N)


def train(ponder=True):
    torch.manual_seed(SEED)
    gen = torch.Generator().manual_seed(SEED)
    model = PonderCell(ponder=ponder)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    # prior geometrica de halting para el reg KL (PonderNet): favorece parar pronto
    lam = 1.0 / (KMAX / 2)
    geom = torch.tensor([(1 - lam) ** n * lam for n in range(KMAX)])
    geom = geom / geom.sum()

    for step in range(STEPS):
        seq, L, y = make_batch(BATCH, gen=gen)
        logits_steps, halt_steps = model(seq)
        if ponder:
            p = ponder_halting_dist(halt_steps)              # (B, N)
            # perdida = Σ_n p_n * CE(logits_n, y)  (esperada sobre halting)
            ce = torch.stack([F.cross_entropy(logits_steps[n], y, reduction="none")
                              for n in range(KMAX)], dim=1)   # (B, N)
            loss_rec = (p * ce).sum(dim=1).mean()
            # reg KL(p || geom): empuja a parar pronto (menos computo)
            kl = (p * (torch.log(p + 1e-9) - torch.log(geom + 1e-9))).sum(dim=1).mean()
            loss = loss_rec + PONDER_LAMBDA * kl
        else:
            # fixed: usa SIEMPRE el ultimo paso (KMAX vueltas)
            loss = F.cross_entropy(logits_steps[-1], y)
        opt.zero_grad()
        loss.backward()
        opt.step()
    return model


@torch.no_grad()
def evaluate(model, n=4000):
    gen = torch.Generator().manual_seed(SEED + 1)
    seq, L, y = make_batch(n, gen=gen)
    logits_steps, halt_steps = model(seq)
    if model.ponder:
        p = ponder_halting_dist(halt_steps)          # (n, KMAX)
        step_idx = p.argmax(dim=1)                   # paso donde para (0-indexed)
        pred = torch.stack([logits_steps[step_idx[i]][i] for i in range(n)]).argmax(-1)
        steps_used = (step_idx + 1).float()          # 1-indexed
        exp_steps = (p * torch.arange(1, KMAX + 1).float()).sum(dim=1)  # esperado
    else:
        pred = logits_steps[-1].argmax(-1)
        steps_used = torch.full((n,), float(KMAX))
        exp_steps = steps_used
    acc = (pred == y).float().mean().item()
    # correlacion entre L (profundidad REAL necesaria) y pasos usados: la ponder
    # deberia usar mas pasos en secuencias mas largas (piensa mas en lo dificil).
    lf = L.float()
    corr = torch.corrcoef(torch.stack([lf, steps_used.float()]))[0, 1].item() \
        if model.ponder else 0.0
    # accuracy por longitud (que lo largo/dificil no se rompa)
    acc_by_k = {int(kk): round((pred[L == kk] == y[L == kk]).float().mean().item(), 3)
                for kk in range(1, KMAX + 1)}
    return {"acc": round(acc, 4),
            "avg_steps_used": round(steps_used.mean().item(), 3),
            "avg_exp_steps": round(exp_steps.mean().item(), 3),
            "corr_K_steps": round(corr, 3) if not math.isnan(corr) else None,
            "acc_by_k": acc_by_k}


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print(f"[exp137] adaptive ponder vs fixed depth | KMAX={KMAX} steps={STEPS}", flush=True)

    print("[exp137] entrenando FIXED (siempre KMAX vueltas)...", flush=True)
    m_fixed = train(ponder=False)
    r_fixed = evaluate(m_fixed)
    print("  fixed :", r_fixed, flush=True)

    print("[exp137] entrenando PONDER (halting adaptativo)...", flush=True)
    m_ponder = train(ponder=True)
    r_ponder = evaluate(m_ponder)
    print("  ponder:", r_ponder, flush=True)

    # veredicto vs prediccion congelada
    saving = KMAX - r_ponder["avg_steps_used"]
    verdict = {
        "acc_match": r_ponder["acc"] >= r_fixed["acc"] - 0.03,
        "compute_saved_pct": round(saving / KMAX * 100, 1),
        "ponders_more_on_hard": (r_ponder["corr_K_steps"] or 0) > 0.3,
    }
    print("\n[exp137] VEREDICTO (vs prediccion congelada):", flush=True)
    print(f"  accuracy: ponder {r_ponder['acc']:.1%} vs fixed {r_fixed['acc']:.1%} "
          f"(match={verdict['acc_match']})", flush=True)
    print(f"  computo: ponder usa {r_ponder['avg_steps_used']:.2f}/{KMAX} pasos "
          f"-> AHORRO {verdict['compute_saved_pct']:.0f}% vs fixed", flush=True)
    print(f"  piensa mas en lo dificil: corr(K, pasos)={r_ponder['corr_K_steps']} "
          f"(>{0.3}? {verdict['ponders_more_on_hard']})", flush=True)
    ok = (verdict["acc_match"] and verdict["compute_saved_pct"] > 10
          and verdict["ponders_more_on_hard"])
    print(f"\n[exp137] {'CONFIRMA' if ok else 'NO CONFIRMA'} que la profundidad "
          f"adaptativa ahorra computo a igual calidad.", flush=True)

    out = {"kmax": KMAX, "steps": STEPS, "seed": SEED,
           "fixed": r_fixed, "ponder": r_ponder, "verdict": verdict, "confirma": ok}
    (OUT / "results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[exp137] -> {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
