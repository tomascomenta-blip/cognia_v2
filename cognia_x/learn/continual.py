"""
CYCLE 8 — Aprendizaje continuo Nivel 1: "el estudiante diligente".

La IA híbrida aprende texto REAL nuevo y SOLO fija el cambio si un examinador independiente
(eval determinista sobre held-out que nunca entrena) confirma que mejoró en lo NUEVO **sin olvidar
lo VIEJO**. Si no, hace ROLLBACK (rechaza la lección).

Transformación a problema cotidiano (método del lab) de los 3 problemas:
- OLVIDO CATASTRÓFICO  -> como estudiar el cap.2 y olvidar el cap.1. Solución: REPASAR mientras se
  aprende (replay de un buffer viejo) + COMPUERTA "do-no-harm" (no aceptar si el val viejo empeora).
- GOODHART (métrica engañable) -> como memorizar el solucionario. Solución: examinador EXTERNO con
  material NO VISTO (held-out que el modelo nunca entrena ni optimiza directo).
- COLAPSO (entrenarse con su propia salida) -> fotocopia de una fotocopia. Solución v1: aprender
  SOLO de datos reales externos (lo auto-generado se deja para Nivel 2, y solo si se VERIFICA antes).

Reutiliza la infra de char-LM (eval_loss determinista, get_batch, HybridLM). CPU-first.
"""
import copy
import statistics
import time

import torch
import torch.nn.functional as F

from cognia_x.train.charlm import eval_loss, get_batch


@torch.no_grad()
def eval_at(model, data_t, L, device, offset=0, max_windows=300):
    """eval_loss determinista pero con un OFFSET de inicio de ventanas; variar el offset da
    submuestras distintas del mismo set → sirve para estimar el RUIDO del examinador."""
    model.eval()
    n = data_t.numel()
    starts = list(range(offset, n - L - 1, L))
    if not starts:
        model.train()
        return float("nan")
    if len(starts) > max_windows:
        stride = len(starts) / max_windows
        starts = [starts[int(i * stride)] for i in range(max_windows)]
    tot, cnt = 0.0, 0
    for j in range(0, len(starts), 16):
        ch = starts[j:j + 16]
        x = torch.stack([data_t[s:s + L] for s in ch]).long().to(device)
        y = torch.stack([data_t[s + 1:s + 1 + L] for s in ch]).long().to(device)
        _, loss = model(x, y)
        tot += loss.item() * len(ch)
        cnt += len(ch)
    model.train()
    return tot / max(1, cnt)


def eval_noise(model, data_t, L, device):
    """Media y desviación (ruido) del examinador sobre un set, midiendo con varios offsets.
    El umbral de la compuerta se calibra contra ESTE ruido, no contra un epsilon mágico fijo."""
    offs = [0, L // 5, (2 * L) // 5, (3 * L) // 5, (4 * L) // 5]
    vals = [eval_at(model, data_t, L, device, offset=o) for o in offs]
    vals = [v for v in vals if v == v]  # filtra nan
    if not vals:
        return float("nan"), 0.0
    return statistics.mean(vals), (statistics.pstdev(vals) if len(vals) > 1 else 0.0)


def snapshot_model(model):
    """Copia barata del estado (modelo chico en CPU) para poder hacer rollback de una lección."""
    return copy.deepcopy(model.state_dict())


def restore_model(model, snap):
    model.load_state_dict(snap)


def learn_steps(model, opt, new_t, steps, L, batch, device, replay_t=None, replay_ratio=0.5,
                warmup=0, base_lr=None):
    """Aprende `steps` pasos sobre `new_t`. Si hay `replay_t`, intercala batches del buffer VIEJO
    (replay/rehearsal) en una fracción `replay_ratio` de los pasos — repasar mientras se aprende."""
    model.train()
    last = float("nan")
    for s in range(1, steps + 1):
        if warmup > 0 and s <= warmup and base_lr is not None:
            for g in opt.param_groups:
                g["lr"] = base_lr * s / warmup
        use_replay = replay_t is not None and replay_t.numel() > L + 1 and (s % max(1, round(1 / max(1e-6, replay_ratio))) == 0)
        src = replay_t if use_replay else new_t
        x, y = get_batch(src, batch, L, device)
        _, loss = model(x, y)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        last = loss.item()
    return last


def freeze_recall_trunk(model):
    """Congela las partes caras de RECORDAR — embeddings atados (= lm_head) + las capas de ATENCIÓN
    softmax (recall exacto, escasas) — dejando PLÁSTICAS las capas LINEALES + MLP + norms. El
    conocimiento viejo guardado en el tronco congelado queda protegido por construcción; lo nuevo
    entra por las capas baratas. Análogo: escribir lo nuevo en una hoja aparte sin tachar el cuaderno.
    Devuelve la lista de params entrenables (para pasársela al optimizer)."""
    for p in model.parameters():
        p.requires_grad = True
    for p in model.embed.parameters():     # embeddings atados (= lm_head)
        p.requires_grad = False
    for b in model.blocks:
        if b.kind == "attn":               # capas de atención softmax: recall exacto
            for p in b.mixer.parameters():
                p.requires_grad = False
    return [p for p in model.parameters() if p.requires_grad]


def learn_steps_surprise(model, opt, new_t, steps, L, batch, device, low_q=0.5, high_q=0.95,
                         replay_t=None, replay_ratio=0.5, warmup=0, base_lr=None):
    """CURIOSIDAD: aprende los bytes de una BANDA de sorpresa — pérdida por-byte entre los cuantiles
    [low_q, high_q]. Excluye el fácil/redundante (bajo low_q, de donde viene el daño a lo viejo) Y el
    EXTREMO superior (sobre high_q), que suele ser RUIDO (caracteres raros/formato), no novedad
    aprendible. Concentra el gradiente en lo novel-pero-aprendible. Una sola forward (reduction='none').
    Lección del smoke de CYCLE 9: el top-k absoluto entrena el ruido y EMPEORA; la banda lo evita."""
    model.train()
    V = model.cfg.vocab_size
    last = float("nan")
    for s in range(1, steps + 1):
        if warmup > 0 and s <= warmup and base_lr is not None:
            for g in opt.param_groups:
                g["lr"] = base_lr * s / warmup
        use_replay = (replay_t is not None and replay_t.numel() > L + 1
                      and (s % max(1, round(1 / max(1e-6, replay_ratio))) == 0))
        src = replay_t if use_replay else new_t
        x, y = get_batch(src, batch, L, device)
        logits, _ = model(x)
        lf = F.cross_entropy(logits.view(-1, V), y.view(-1), reduction="none")  # (B*L,)
        with torch.no_grad():
            lo = torch.quantile(lf, low_q)
            hi = torch.quantile(lf, high_q) if high_q < 1.0 else lf.max() + 1.0
            keep = ((lf >= lo) & (lf <= hi)).float()
        loss = (lf * keep).sum() / keep.sum().clamp(min=1.0)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        last = loss.item()
    return last


def gated_learn(model, new_train_t, new_val_t, old_val_t, log, *, replay_t=None,
                steps=300, lr=3e-4, L=192, batch=16, device="cpu", eps=0.02, warmup=50,
                name="lección"):
    """Intenta aprender `new_train_t`. Mide el examinador (eval determinista held-out) ANTES y
    DESPUÉS en dominio NUEVO y VIEJO. ACEPTA el update SOLO si:
        - aprendió: new_val bajó (mejora real en lo nuevo), y
        - no dañó: old_val no subió más de `eps` (do-no-harm sobre lo viejo).
    Si no cumple, ROLLBACK al snapshot. Devuelve el veredicto + métricas.
    """
    new_before = eval_loss(model, new_val_t, L, device)
    old_before = eval_loss(model, old_val_t, L, device)
    snap = snapshot_model(model)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    t0 = time.time()
    learn_steps(model, opt, new_train_t, steps, L, batch, device, replay_t=replay_t,
                warmup=warmup, base_lr=lr)

    new_after = eval_loss(model, new_val_t, L, device)
    old_after = eval_loss(model, old_val_t, L, device)
    learned = new_after < new_before - 1e-3            # mejora real en lo nuevo
    no_harm = old_after <= old_before + eps            # no empeoró lo viejo más de eps
    accept = bool(learned and no_harm)
    if not accept:
        restore_model(model, snap)

    res = {
        "name": name, "accepted": accept, "learned": bool(learned), "no_harm": bool(no_harm),
        "new_before": round(new_before, 4), "new_after": round(new_after, 4),
        "new_delta": round(new_after - new_before, 4),
        "old_before": round(old_before, 4), "old_after": round(old_after, 4),
        "old_delta": round(old_after - old_before, 4),
        "replay": replay_t is not None, "steps": steps, "eps": eps,
        "secs": round(time.time() - t0, 1),
    }
    verdict = "ACEPTADA" if accept else ("RECHAZADA (rollback)")
    log(f"[continual:{name}] {verdict} | nuevo {new_before:.3f}->{new_after:.3f} "
        f"({res['new_delta']:+.3f}) | viejo {old_before:.3f}->{old_after:.3f} "
        f"({res['old_delta']:+.3f}) | replay={res['replay']} eps={eps} ({res['secs']}s)")
    return res


def gated_learn_domains(model, new_train_t, new_val_t, old_domains, log, *, replay_t=None,
                        steps=400, lr=5e-4, L=160, batch=16, device="cpu", k=2.0, eps_floor=0.01,
                        warmup=50, name="lección", aggregate=False):
    """Compuerta ROBUSTA (cierra el fallo H-SELF-2: 'evaluador circular/agregado'):
    - examinador NO circular: held-out cross-book REAL para lo nuevo (new_val_t) y por dominio viejo.
    - POR-DOMINIO: do-no-harm exige que NINGÚN dominio viejo empeore (peor-caso, no promedio). El
      modo `aggregate=True` reproduce el gate viejo (promedio) para DEMOSTRAR que es ciego al daño.
    - BANDA DE INCERTIDUMBRE: umbrales = k·sigma del propio examinador (medido con eval_noise), no
      un epsilon mágico. `learned` exige bajar > k·sigma en lo nuevo; `harm` = subir > max(eps_floor,
      k·sigma) en algún dominio viejo.
    old_domains: lista de (nombre, val_tensor). Devuelve veredicto + deltas por dominio.
    """
    new_m0, new_s = eval_noise(model, new_val_t, L, device)
    olds0 = {nm: eval_noise(model, vt, L, device) for nm, vt in old_domains}
    snap = snapshot_model(model)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    t0 = time.time()
    learn_steps(model, opt, new_train_t, steps, L, batch, device, replay_t=replay_t,
                warmup=warmup, base_lr=lr)
    new_m1 = eval_at(model, new_val_t, L, device)
    olds1 = {nm: eval_at(model, vt, L, device) for nm, vt in old_domains}

    learned = bool(new_m1 < new_m0 - k * new_s)
    per = {}
    for nm, (m0, s0) in olds0.items():
        d = olds1[nm] - m0
        thr = max(eps_floor, k * s0)
        per[nm] = {"before": round(m0, 4), "after": round(olds1[nm], 4), "delta": round(d, 4),
                   "thr": round(thr, 4), "harm": bool(d > thr)}
    if aggregate:
        agg0 = sum(m0 for m0, _ in olds0.values()) / len(olds0)
        agg1 = sum(olds1[nm] for nm in olds0) / len(olds0)
        no_harm = bool((agg1 - agg0) <= eps_floor)
        gate_kind = "AGREGADO"
        harm_info = f"agg {agg0:.3f}->{agg1:.3f} ({agg1-agg0:+.3f})"
    else:
        no_harm = not any(per[nm]["harm"] for nm in per)
        gate_kind = "POR-DOMINIO"
        harm_info = " ".join(f"{nm.split('.')[0]}{per[nm]['delta']:+.3f}{'!' if per[nm]['harm'] else ''}"
                             for nm in per)

    accept = bool(learned and no_harm)
    if not accept:
        restore_model(model, snap)
    res = {"name": name, "gate": gate_kind, "accepted": accept, "learned": learned,
           "no_harm": bool(no_harm), "new_before": round(new_m0, 4), "new_after": round(new_m1, 4),
           "new_delta": round(new_m1 - new_m0, 4), "new_sigma": round(new_s, 4),
           "replay": replay_t is not None, "per_domain": per, "secs": round(time.time() - t0, 1)}
    log(f"[continual:{name}] gate={gate_kind} {'ACEPTADA' if accept else 'RECHAZADA(rollback)'} | "
        f"nuevo {new_m0:.3f}->{new_m1:.3f}({res['new_delta']:+.3f},sig{new_s:.3f}) | "
        f"viejo[{harm_info}] | learned={learned} no_harm={no_harm} replay={res['replay']} ({res['secs']}s)")
    return res
