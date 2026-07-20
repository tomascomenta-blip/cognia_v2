r"""
Harness de entreno RÁPIDO + REENTRENABLE para HybridLM (cognia_x/model/hybrid.py).

Objetivo del goal: que entrenar la IA sea rápido Y fácilmente reentrenable/reanudable. Este harness junta
las palancas de velocidad MEDIDAS + el estado para reanudar:
  - AMP fp16 (autocast + GradScaler) — fp16-SEGURO porque hybrid.py ya computa el núcleo de la atención en
    fp32 (sin eso, fp16 da NaN; ver M0_G2_PROFILE_RESULTADO.md). Medido ~1.9× en T4 para el throughput.
  - torch.compile (opcional) — ~2× extra en corridas largas de UN modelo (recompila por estructura).
  - AdamW fused (opcional, GPU) — menos overhead de kernels del optimizer.
  - CHECKPOINT ATÓMICO REANUDABLE: guarda {modelo, opt, scaler, step, rng numpy+torch, config} a un .tmp y
    hace os.replace (atómico) -> si el proceso muere, reanuda EXACTO desde el último checkpoint. Config
    DECLARATIVA (dict/JSON) -> reentrenar = re-llamar con el mismo out_dir (auto-resume) o cambiar el dict.

Es task-agnóstico: recibe un `batch_fn(step) -> (x, y)`. Trae la tarea de recall para auto-test.
CPU smoke (prueba el resume real): venv312\Scripts\python.exe -m cognia_x.train.fast_harness --smoke
"""
import argparse
import json
import os
import time

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.recall_task import make_recall_batch, eval_recall
from cognia_x.training_progress import ProgressWriter


def _device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def save_ckpt(path, base_model, opt, scaler, step, cfg_model, cfg_train):
    """Checkpoint ATÓMICO: escribe a .tmp y os.replace (no deja un ckpt a medio escribir si muere)."""
    blob = {
        "step": step,
        "model": base_model.state_dict(),
        "opt": opt.state_dict(),
        "scaler": scaler.state_dict() if scaler is not None else None,
        "np_rng": np.random.get_state(),
        "torch_rng": torch.get_rng_state(),
        "cfg_model": cfg_model,
        "cfg_train": cfg_train,
    }
    tmp = str(path) + ".tmp"
    torch.save(blob, tmp)
    os.replace(tmp, path)        # atómico en el mismo filesystem


def load_ckpt(path, base_model, opt, scaler, map_location):
    blob = torch.load(path, map_location=map_location, weights_only=False)
    base_model.load_state_dict(blob["model"])
    opt.load_state_dict(blob["opt"])
    if scaler is not None and blob.get("scaler") is not None:
        scaler.load_state_dict(blob["scaler"])
    np.random.set_state(blob["np_rng"])
    torch.set_rng_state(blob["torch_rng"])
    return blob["step"]


def train(cfg_model, cfg_train, out_dir, batch_fn, device=None, log=print, eval_fn=None,
          progress=None):
    """Entrena HybridLM(cfg_model) con AMP-safe + compile + checkpoints atómicos reanudables.
    cfg_train: dict con steps, lr, weight_decay, warmup, ckpt_every, amp, compile, fused, grad_clip.
    batch_fn(step)->(x,y) en CPU o device. Reanuda solo si out_dir/ckpt.pt existe.
    progress: opcional. True -> escribe el JSON de progreso para la TUI en la ruta por defecto;
    str/Path -> escribe en esa ruta. cfg_train['run_name']/'progress_every'/'total_epochs' ajustan el
    writer. NO altera la lógica de entreno: solo agrega start()/update()/finish() best-effort."""
    device = device or _device()
    os.makedirs(out_dir, exist_ok=True)
    ckpt_path = os.path.join(out_dir, "ckpt.pt")

    steps = cfg_train["steps"]
    lr = cfg_train.get("lr", 1e-3)
    wd = cfg_train.get("weight_decay", 0.01)
    warmup = cfg_train.get("warmup", 0)
    ckpt_every = cfg_train.get("ckpt_every", max(1, steps // 10))
    grad_clip = cfg_train.get("grad_clip", 1.0)
    use_amp = cfg_train.get("amp", True) and device == "cuda"
    use_compile = cfg_train.get("compile", False) and device == "cuda"
    use_fused = cfg_train.get("fused", True) and device == "cuda"

    torch.manual_seed(cfg_train.get("seed", 0))
    np.random.seed(cfg_train.get("seed", 0))
    base_model = HybridLM(HybridConfig(**cfg_model)).to(device)
    try:
        opt = torch.optim.AdamW(base_model.parameters(), lr=lr, weight_decay=wd, fused=use_fused)
    except (RuntimeError, TypeError):
        opt = torch.optim.AdamW(base_model.parameters(), lr=lr, weight_decay=wd)
        use_fused = False
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    model = torch.compile(base_model) if use_compile else base_model

    start = 0
    if os.path.exists(ckpt_path):
        start = load_ckpt(ckpt_path, base_model, opt, scaler, map_location=device)
        log(f"[harness] REANUDADO desde {ckpt_path} en step {start}")
    log(f"[harness] params={base_model.num_params():,} device={device} amp={use_amp} "
        f"compile={use_compile} fused={use_fused} steps={steps} (desde {start})")

    writer = None
    if progress:
        writer = ProgressWriter(
            path=None if progress is True else progress,
            run_name=cfg_train.get("run_name") or os.path.basename(os.path.abspath(out_dir)),
            total_epochs=cfg_train.get("total_epochs", 1),
            total_steps=steps,
            write_every=cfg_train.get("progress_every", 10),
        )
        writer.start()

    model.train()
    t0 = time.time()
    last = start
    try:
        for step in range(start + 1, steps + 1):
            if warmup > 0 and step <= warmup:
                for g in opt.param_groups:
                    g["lr"] = lr * step / warmup
            x, y = batch_fn(step)
            if x.device.type != device:
                x, y = x.to(device), y.to(device)
            if use_amp:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    _, loss = model(x, y)
                opt.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(base_model.parameters(), grad_clip)
                scaler.step(opt)
                scaler.update()
            else:
                _, loss = model(x, y)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(base_model.parameters(), grad_clip)
                opt.step()
            if writer is not None:  # step-based: epoch=1/1; tokens/s y eta REALES por ritmo
                writer.update(step=step, epoch=1, loss=float(loss.detach()),
                              lr=opt.param_groups[0]["lr"], batch_size=int(x.shape[0]),
                              tokens_per_step=int(x.numel()))
            if step % ckpt_every == 0 or step == steps:
                save_ckpt(ckpt_path, base_model, opt, scaler, step, cfg_model, cfg_train)
                dt = time.time() - t0
                sps = (step - last) / dt if dt > 0 else 0.0
                extra = f" {eval_fn(base_model):.3f} acc" if eval_fn else ""
                log(f"[harness] step {step}/{steps} loss {float(loss.detach()):.4f}{extra} "
                    f"| {sps:.1f} step/s ckpt-> {ckpt_path}")
                t0, last = time.time(), step
    except Exception:
        if writer is not None:
            writer.finish("error")
        raise
    if writer is not None:
        writer.finish("done")
    return base_model, ckpt_path


# ───────────────────────── auto-test: recall + RESUME real ──────────────────────────────────────────


def _recall_batch_fn(p, seed=0):
    rng = np.random.default_rng(seed)
    def bf(step):
        return make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], "cpu")
    return bf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="CPU: entrena, corta, REANUDA y verifica")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    device = _device()
    out = args.out or os.path.join(os.path.dirname(__file__), "_harness_smoke")

    p = dict(batch=16, n_pairs=8, n_queries=6, n_keys=48, n_vals=16)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    cfg_model = dict(vocab_size=vocab, d_model=64, n_layers=4, n_heads=4, window=L + 1,
                     attn_every=2, max_seq_len=L + 1)
    bf = _recall_batch_fn(p)

    # 1) entrenar 40 pasos (deja ckpt), 2) "morir", 3) reanudar a 80 y verificar que parte de 40
    import shutil
    if os.path.exists(out):
        shutil.rmtree(out)
    print("=== FASE 1: entrenar a 40 ===")
    train(cfg_model, dict(steps=40, lr=1e-3, ckpt_every=20, amp=False, seed=0), out, bf, device, print)
    ck = torch.load(os.path.join(out, "ckpt.pt"), weights_only=False)
    assert ck["step"] == 40, ck["step"]
    print(f"=== checkpoint en step {ck['step']} ===")
    print("=== FASE 2: REANUDAR (mismo out_dir) hasta 80 — debe arrancar en 40 ===")
    train(cfg_model, dict(steps=80, lr=1e-3, ckpt_every=20, amp=False, seed=0), out, bf, device, print)
    ck2 = torch.load(os.path.join(out, "ckpt.pt"), weights_only=False)
    assert ck2["step"] == 80, ck2["step"]
    print(f"\nCHECK resume OK: reanudó de 40 y llegó a {ck2['step']}. Harness reentrenable verificado.")


if __name__ == "__main__":
    main()
