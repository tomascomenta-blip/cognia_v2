r"""
XOLMO BASELINE — OLMo-1B tal cual en Kaggle T4: la línea base MEDIDA, no asumida (goal OLMo).

Qué mide (todo con verificación determinista):
  1. PPL en ventana NATIVA (OLMo-1B-hf: max_position_embeddings=2048, RoPE) a ctx 512/1024/2048
     sobre wikitext-2 (inglés = distribución de entreno de OLMo).
  2. COLAPSO fuera de ventana: PPL por bucket de posición en ventanas de 4096 tokens (la teoría
     CogniaX dice: RoPE OOD >ventana nativa = la raíz del muro de contexto — acá se mide en OLMo).
  3. PASSKEY retrieval (código de 5 dígitos a 3 profundidades) dentro y fuera de ventana.
  4. RoPE scaling ZERO-SHOT (sin entrenar): linear/PI factor 2 y dynamic-NTK factor 2 —
     ¿recuperan PPL/passkey a 3-4k? (hipótesis: NTK aguanta mejor que linear en zero-shot).

Self-contained, kernel "script" de Kaggle con INTERNET (baja allenai/OLMo-1B-hf ~2.5GB fp16 + wikitext).
Resultados incrementales a xolmo_results.json.

USO Kaggle:  push via cognia_x/construccion/run_kaggle_xolmo.py
USO local:   venv312\Scripts\python.exe cognia_x/construccion/xolmo_kernel.py --smoke
             (smoke = modelo tiny RANDOM local, verifica la plomería de medición sin bajar nada)
"""
import argparse
import json
import time

import torch

RESULTS_PATH = "xolmo_results.json"
TIME_BUDGET_MIN = 40.0
MODEL_ID = "allenai/OLMo-1B-hf"
PASSKEY = "48291"
FILLER = ("The grass is green. The sky is blue. The sun is yellow. Here we go. "
          "There and back again. ")
NEEDLE = f"The secret code is {PASSKEY}. Remember it. "
QUESTION = "\nWhat is the secret code? The secret code is"


def save(out):
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def apply_rope_scaling(cfg, kind, factor):
    """Setea el scaling de RoPE cubriendo AMBAS APIs de transformers:
    <5.x: cfg.rope_scaling = {"type"/"rope_type", "factor"};
    >=5.x: cfg.rope_parameters = {..., "rope_type", "factor", "rope_theta"} (si falta rope_theta
    el rope init hace base**exponente con base=None -> TypeError, visto en el smoke)."""
    theta = getattr(cfg, "rope_theta", None) or 10000.0
    if hasattr(cfg, "rope_parameters"):
        rp = dict(getattr(cfg, "rope_parameters", None) or {})
        rp.update({"rope_type": kind, "factor": float(factor), "rope_theta": float(theta)})
        cfg.rope_parameters = rp
        return cfg
    try:
        cfg.rope_scaling = {"rope_type": kind, "factor": float(factor)}
    except Exception:  # noqa: BLE001
        cfg.rope_scaling = {"type": kind, "factor": float(factor)}
    return cfg


def load_model(rope_scaling=None, smoke=False, device="cuda"):
    """Carga OLMo-1B (o un tiny random en smoke). rope_scaling: None | (kind, factor)."""
    if smoke:
        try:
            from transformers import OlmoConfig, OlmoForCausalLM
            cfg = OlmoConfig(vocab_size=256, hidden_size=64, intermediate_size=128,
                             num_hidden_layers=2, num_attention_heads=4,
                             max_position_embeddings=64)
            if rope_scaling:
                apply_rope_scaling(cfg, *rope_scaling)
            torch.manual_seed(0)
            return OlmoForCausalLM(cfg).to(device).eval(), 64
        except Exception:  # noqa: BLE001 — fallback si la versión local no trae Olmo
            from transformers import LlamaConfig, LlamaForCausalLM
            cfg = LlamaConfig(vocab_size=256, hidden_size=64, intermediate_size=128,
                              num_hidden_layers=2, num_attention_heads=4,
                              num_key_value_heads=4, max_position_embeddings=64)
            if rope_scaling:
                apply_rope_scaling(cfg, *rope_scaling)
            torch.manual_seed(0)
            return LlamaForCausalLM(cfg).to(device).eval(), 64
    from transformers import AutoConfig, AutoModelForCausalLM
    cfg = AutoConfig.from_pretrained(MODEL_ID)
    if rope_scaling:
        apply_rope_scaling(cfg, *rope_scaling)
    m = AutoModelForCausalLM.from_pretrained(MODEL_ID, config=cfg, torch_dtype=torch.float16,
                                             attn_implementation="sdpa")
    m = m.to("cuda").eval()
    return m, m.config.max_position_embeddings


def get_tokenizer(smoke=False):
    if smoke:
        class ByteTok:                                  # byte-level trivial para el smoke
            def __call__(self, s):
                return list(s.encode("utf-8", "ignore"))

            def decode(self, ids):
                return bytes(int(i) % 256 for i in ids).decode("utf-8", "ignore")
        return ByteTok()
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(MODEL_ID)


def get_corpus_ids(tok, smoke=False, max_tokens=400_000, device="cuda"):
    if smoke:
        text = ("el zorro salta sobre el perro. " * 2000)
        return torch.tensor(tok(text)[:20_000], dtype=torch.long, device=device)
    from datasets import load_dataset
    ds = load_dataset("wikitext", "wikitext-2-raw-v1", split="test")
    text = "\n\n".join(t for t in ds["text"] if t.strip())
    ds2 = load_dataset("wikitext", "wikitext-2-raw-v1", split="validation")
    text += "\n\n" + "\n\n".join(t for t in ds2["text"] if t.strip())
    ids = tok(text, return_tensors="pt").input_ids[0][:max_tokens]
    return ids.to(device)


@torch.no_grad()
def ppl_at_ctx(model, ids, ctx, max_eval_tokens=60_000):
    """PPL con ventanas disjuntas de largo ctx (NLL promedio de las predicciones)."""
    device = ids.device
    nll, n = 0.0, 0
    for i in range(0, len(ids) - ctx, ctx):
        if n >= max_eval_tokens:
            break
        w = ids[i:i + ctx].unsqueeze(0)
        out = model(w, labels=w)
        nll += float(out.loss) * (ctx - 1)
        n += ctx - 1
    return round(float(torch.exp(torch.tensor(nll / max(1, n)))), 3), n


@torch.no_grad()
def ppl_by_position(model, ids, total_len=4096, bucket=512, n_windows=6):
    """NLL por bucket de posición en ventanas largas: muestra DÓNDE colapsa fuera de ventana."""
    device = ids.device
    sums = torch.zeros(total_len // bucket)
    cnts = torch.zeros(total_len // bucket)
    done = 0
    for i in range(0, len(ids) - total_len, total_len):
        if done >= n_windows:
            break
        w = ids[i:i + total_len].unsqueeze(0)
        logits = model(w).logits.float()
        logp = torch.log_softmax(logits[0, :-1], dim=-1)
        tok_nll = -logp[torch.arange(total_len - 1), w[0, 1:]]
        for b in range(total_len // bucket):
            lo, hi = b * bucket, min((b + 1) * bucket, total_len - 1)
            if hi > lo:
                sums[b] += float(tok_nll[lo:hi].sum())
                cnts[b] += hi - lo
        done += 1
    return {f"pos_{b * bucket}-{(b + 1) * bucket}": round(float(torch.exp(sums[b] / max(1, cnts[b]))), 2)
            for b in range(total_len // bucket)}, done


def _encode(tok, text, smoke):
    if smoke:
        return list(tok(text))
    return tok(text, add_special_tokens=False).input_ids


@torch.no_grad()
def passkey_eval(model, tok, target_len_tokens, depths=(0.2, 0.5, 0.8), smoke=False):
    """v2 (fix): construye la secuencia POR TOKENS — bloques de filler + needle ENTERO insertado a la
    profundidad pedida + pregunta al final. El v1 truncaba del medio y podía CORTAR el needle
    (por eso el 0/3 era no concluyente). Devuelve hits/total."""
    device = next(model.parameters()).device
    fill_ids = _encode(tok, FILLER, smoke)
    needle_ids = _encode(tok, NEEDLE, smoke)
    q_ids = _encode(tok, QUESTION, smoke)
    budget = target_len_tokens - len(needle_ids) - len(q_ids)
    n_fill = max(2, budget // len(fill_ids))
    hits = 0
    for d in depths:
        k = max(1, min(n_fill - 1, int(n_fill * d)))
        ids_list = (fill_ids * k) + needle_ids + (fill_ids * (n_fill - k)) + q_ids
        ids = torch.tensor(ids_list, dtype=torch.long, device=device).unsqueeze(0)
        gen = model.generate(ids, max_new_tokens=8, do_sample=False, pad_token_id=0)
        txt = tok.decode(gen[0, ids.shape[1]:].tolist())
        if PASSKEY in txt:
            hits += 1
    return hits, len(depths)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--v2", action="store_true",
                    help="ronda 2: passkey ARREGLADO + NTK x4 hasta 8192 (salta lo ya medido en v1)")
    args = ap.parse_args()
    smoke = args.smoke
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if smoke and device == "cpu":
        torch.set_num_threads(3)
    t0 = time.time()
    out = {"experiment": "xolmo_baseline", "model": MODEL_ID if not smoke else "tiny-random-smoke",
           "torch": torch.__version__, "device": device}
    print(f"[xolmo] smoke={smoke} device={device} torch={torch.__version__}", flush=True)

    def over():
        return (time.time() - t0) / 60 > TIME_BUDGET_MIN

    tok = get_tokenizer(smoke)
    model, native = load_model(smoke=smoke, device=device)
    out["native_window"] = int(native)
    print(f"[xolmo] ventana nativa = {native}", flush=True)
    ids = get_corpus_ids(tok, smoke, device=device if smoke else "cuda")
    out["corpus_tokens"] = int(len(ids))
    save(out)

    # ── 1) PPL en ventana nativa (v2 la salta: ya medida en v1) ──
    ctxs = [16, 32, 64] if smoke else [512, 1024, 2048]
    if args.v2 and not smoke:
        out["ppl_native"] = "medida en v1 (results_xolmo v1: 17.3@512, 14.7@1024, 13.1@2048)"
    else:
        out["ppl_native"] = {}
        for c in ctxs:
            p, n = ppl_at_ctx(model, ids, c, max_eval_tokens=2000 if smoke else 60_000)
            out["ppl_native"][f"ctx_{c}"] = {"ppl": p, "tokens": n}
            print(f"  [ppl] ctx={c}: {p} ({n} toks)", flush=True)
            save(out)

    # ── 2) plan por config de RoPE: (nombre, scaling, total_posppl|None, largos de passkey) ──
    bucket = 32 if smoke else 512
    if smoke:
        plan = [("base", None, 128, [64, 96]), ("linear_x2", ("linear", 2.0), 128, [64, 96])]
    elif args.v2:
        plan = [("base", None, None, [1024, 1792]),
                ("ntk_dynamic_x2", ("dynamic", 2.0), None, [3072, 4096]),
                ("ntk_dynamic_x4", ("dynamic", 4.0), 8192, [6144, 8192])]
    else:
        pk = [1024, 1792, 3072, 4096]
        plan = [("base", None, 4096, pk), ("linear_x2", ("linear", 2.0), 4096, pk),
                ("ntk_dynamic_x2", ("dynamic", 2.0), 4096, pk)]
    out["rope"] = {}
    for name, rs, total, pk_lens in plan:
        if over():
            out["rope"][name] = {"skipped": "budget"}
            save(out)
            continue
        print(f"\n==== rope: {name} ====", flush=True)
        try:
            if rs is not None:
                del model
                if device == "cuda":
                    torch.cuda.empty_cache()
                model, _ = load_model(rope_scaling=rs, smoke=smoke, device=device)
            r = {}
            if total:
                pos_ppl, nw = ppl_by_position(model, ids, total_len=total, bucket=bucket,
                                              n_windows=2 if smoke else (3 if total > 4096 else 6))
                r["ppl_by_position"] = pos_ppl
                r["windows"] = nw
                print(f"  [pos-ppl] {pos_ppl}", flush=True)
            r["passkey"] = {}
            for L in pk_lens:
                h, t = passkey_eval(model, tok, L, smoke=smoke)
                r["passkey"][f"len_{L}"] = f"{h}/{t}"
                print(f"  [passkey] len={L}: {h}/{t}", flush=True)
            if rs is not None:
                p, n = ppl_at_ctx(model, ids, ctxs[-1], max_eval_tokens=2000 if smoke else 30_000)
                r["ppl_in_window"] = p                      # costo del scaling DENTRO de la ventana
                print(f"  [ppl in-window ctx={ctxs[-1]}] {p}", flush=True)
            out["rope"][name] = r
        except Exception as e:  # noqa: BLE001
            out["rope"][name] = {"error": repr(e)[:300]}
            print(f"  ERROR {e!r}", flush=True)
        save(out)

    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(f"\n[xolmo] LISTO en {out['minutes_total']} min", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
