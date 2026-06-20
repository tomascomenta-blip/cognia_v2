"""
Tarea de recall asociativo (estilo MQAR) para CERRAR el eje recall del hibrido (H-MEZ-4).

exp002 mostro (sin entrenar) que el recall de un mezclador de estado fijo esta acotado por su
estado. exp005 midio que un hibrido cuesta ~12-15% del full puro. Lo que faltaba: ENTRENAR y
verificar que un hibrido (mayoria lineal + pocas capas de atencion) RECUPERA el recall que el
lineal puro no tiene. Este modulo entrena 3 configuraciones y compara su accuracy de recall.

Tarea: secuencia de pares (clave, valor) seguida de consultas (claves vistas); en la posicion de
cada clave-consulta el target es su valor asociado. Requiere recall asociativo en-contexto.
vocab = 1 (pad) + n_keys + n_vals.  Atencion GLOBAL (window>=L) para el test de recall.
"""
import time

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM


def make_recall_batch(rng, batch, n_pairs, n_queries, n_keys, n_vals, device):
    KEY0 = 1
    VAL0 = 1 + n_keys
    seqs, tgts = [], []
    for _ in range(batch):
        keys = rng.choice(n_keys, size=n_pairs, replace=False)
        vals = rng.integers(0, n_vals, size=n_pairs)
        kv = {int(k): int(v) for k, v in zip(keys, vals)}
        seq, tgt = [], []
        for k, v in zip(keys, vals):
            seq += [KEY0 + int(k), VAL0 + int(v)]
            tgt += [-100, -100]
        qk = rng.choice(keys, size=n_queries, replace=True)
        for k in qk:
            seq.append(KEY0 + int(k))
            tgt.append(VAL0 + kv[int(k)])   # predecir el valor EN la posicion de la clave-consulta
        seqs.append(seq)
        tgts.append(tgt)
    x = torch.tensor(seqs, dtype=torch.long, device=device)
    y = torch.tensor(tgts, dtype=torch.long, device=device)
    return x, y


def train_and_eval(name, attn_every, steps, log, device="cpu", seed=0, deadline=None,
                   min_steps=0, warmup=0, early_stop=1.01,
                   d_model=96, n_layers=4, n_heads=4,
                   n_keys=96, n_vals=32, n_pairs=48, n_queries=8,
                   batch=32, lr=3e-4, abs_pos=False, linear_feature_mult=1):
    rng = np.random.default_rng(seed)
    eval_rng = np.random.default_rng(seed + 10**6)   # eval aislado: reproducible sin importar #pasos
    torch.manual_seed(seed)
    L = 2 * n_pairs + n_queries
    vocab = 1 + n_keys + n_vals
    chance = 1.0 / n_vals    # azar REAL: el modelo aprende que la respuesta es un token-valor
    cfg = HybridConfig(vocab_size=vocab, d_model=d_model, n_layers=n_layers, n_heads=n_heads,
                       window=L + 1, attn_every=attn_every, max_seq_len=L + 1, abs_pos_emb=abs_pos,
                       linear_feature_mult=linear_feature_mult)
    model = HybridLM(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    types = cfg.layer_types()
    log(f"[recall:{name}] params={model.num_params():,} L={L} vocab={vocab} ae={attn_every} "
        f"capas={types.count('linear')}lin/{types.count('attn')}attn azar={chance:.3f}")

    model.train()
    for step in range(1, steps + 1):
        if warmup > 0 and step <= warmup:        # warmup lineal de LR (forma la cabeza de induccion)
            for g in opt.param_groups:
                g["lr"] = lr * step / warmup
        x, y = make_recall_batch(rng, batch, n_pairs, n_queries, n_keys, n_vals, device)
        _, loss = model(x, y)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        # Piso de pasos: no cortar por deadline antes de min_steps (si no, la atencion a np alto
        # se corta antes de cruzar la transicion -> falso plateau). Ver workflow CYCLE 6.
        if deadline is not None and step >= min_steps and time.time() > deadline:
            log(f"[recall:{name}] deadline alcanzado en step {step} (min_steps={min_steps})")
            break
        if step % max(1, steps // 20) == 0 or step == steps:
            acc = eval_recall(model, eval_rng, n_pairs, n_queries, n_keys, n_vals, device, batches=8)
            log(f"[recall:{name}] step {step}/{steps} loss {loss.item():.4f} acc {acc:.3f} (azar {chance:.3f})")
            if acc >= early_stop and step >= warmup:   # resuelto: cortar (independiente de min_steps)
                log(f"[recall:{name}] early-stop en step {step} (acc {acc:.3f} >= {early_stop})")
                break

    acc = eval_recall(model, eval_rng, n_pairs, n_queries, n_keys, n_vals, device, batches=20)
    log(f"[recall:{name}] FINAL acc {acc:.3f} (azar {chance:.3f})")
    return {"name": name, "attn_every": attn_every, "final_acc": acc, "chance": chance,
            "n_pairs": n_pairs, "n_queries": n_queries, "params": model.num_params(),
            "layers": {"linear": types.count("linear"), "attn": types.count("attn")}}


@torch.no_grad()
def eval_recall(model, rng, n_pairs, n_queries, n_keys, n_vals, device, batches=10, batch=32):
    model.eval()
    hits = total = 0
    for _ in range(batches):
        x, y = make_recall_batch(rng, batch, n_pairs, n_queries, n_keys, n_vals, device)
        logits, _ = model(x)
        pred = logits.argmax(-1)
        m = y != -100
        hits += int((pred[m] == y[m]).sum())
        total += int(m.sum())
    model.train()
    return hits / max(1, total)


def run_comparison(steps, log, device="cpu", seed=0, deadline=None):
    """Compara lineal-puro vs hibrido vs atencion-pura en recall. Cierra H-MEZ-4 end-to-end.
    Con deadline global, reparte el tiempo restante en partes iguales entre las 3 configs."""
    configs = [("lineal_puro", 0), ("hibrido_3to1", 3), ("atencion_pura", 1)]
    results = []
    for i, (name, ae) in enumerate(configs):
        per = None
        if deadline:
            per = time.time() + max(60.0, (deadline - time.time()) / (len(configs) - i))
        try:
            results.append(train_and_eval(name, ae, steps, log, device=device, seed=seed, deadline=per))
        except Exception as e:  # noqa: BLE001
            log(f"[recall:{name}] ERROR: {e!r}")
            results.append({"name": name, "attn_every": ae, "error": repr(e)})
    return results
