r"""
XH-P2K2 — Fase 2: QLoRA del nicho matemático-es sobre Qwen2.5-3B-Instruct (NF4) + eval del
adapter con EL MISMO harness de P2-K1, según 02_FASE2_PLAN.md §3/§5 (pre-registrado).

Train: Danielbrdz/gsm8k-ES (~85%, GSM8K TRAIN traducido, MIT) + Iker/OpenHermes-2.5-Spanish
(~15%, muestra seed=1234, ≤512 tok) → chat template Qwen (user = pregunta tal cual; assistant =
CoT terminando en '#### <número>'), packing en bloques de 1024, QLoRA r=16 α=32 dropout 0.05
all-linear, lr 2e-4 cosine warmup 3%, b4×accum4 (efectivo 16) SIN gradient checkpointing,
CORTE DURO POR RELOJ a 45 min (schedule recalculado al tok/s real). Higiene train/test §3:
decontaminación por hash normalizado contra las 3 suites (assert=0) + exclusión de exemplars.

Eval: misma batería que P2-K1 sobre base+adapter; deltas contra eval_p2_base.json (attacheado
como kernel source) con las reglas de interpretación pre-registradas (§4 P1-P5).
Salidas: final_adapter/ (solo adapter, licencia §6) + eval_p2_compare.json.
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_p2k2_qlora.py --smoke
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import unicodedata

RESULTS_PATH = "eval_p2_compare.json"
ADAPTER_DIR = "final_adapter"
TRAIN_WALL_S = 45 * 60.0
BUDGET_MIN = 118.0
SEQ = 1024
MICRO_B = 4
ACCUM = 4
LR = 2e-4
HERMES_N = 1500
MGSM_PROMPT = ("Resuelve el siguiente problema paso a paso y termina tu respuesta "
               "con la línea '#### <número>'.\n\n{q}")
FEWSHOT_IDX = (0, 1, 2)


# ───────────────────────── util compartido con P2-K1 (extracción/normalización) ────────────────────


def norm_number(s):
    if s is None:
        return None
    s = str(s).strip().rstrip(".")
    s = re.sub(r"[.,](?=\d{3}(\D|$))", "", s)
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group())
    return int(v) if v == int(v) else v


def extract_strict(text):
    hits = re.findall(r"####\s*([^\n]*)", text)
    return norm_number(hits[-1]) if hits else None


def extract_lax(text):
    for line in reversed([ln for ln in text.split("\n") if ln.strip()]):
        nums = re.findall(r"[-+]?\d[\d.,]*", line)
        if nums:
            return norm_number(nums[-1])
    return None


def norm_hash(text):
    """lowercase + sin acentos + sin espacios → md5 (decontaminación §3)."""
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c) and not c.isspace())
    return hashlib.md5(t.encode("utf-8", "ignore")).hexdigest()


def num_multiset(text):
    return tuple(sorted(re.findall(r"\d+", text)))


def _ensure_bitsandbytes():
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print(f"[bnb] pip -> rc={r.returncode} ({tail[-1] if tail else 'sin output'})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[bnb] pip fallo: {e}", flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401
        ver = importlib.metadata.version("bitsandbytes")
        ok = tuple(int(x) for x in ver.split(".")[:3]) >= (0, 46, 1)
        print(f"[bnb] {ver} -> {'OK' if ok else 'insuficiente'}", flush=True)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[bnb] import fallo: {e}", flush=True)
        return False


def _disable_torchao():
    """torchao 0.10 del image rompe peft (is_torchao_available LANZA). Port de
    train_tooluse_kaggle.py — sin esto get_peft_model crashea."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"],
                           capture_output=True, text=True, timeout=300)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print(f"[torchao] uninstall -> rc={r.returncode} ({tail[-1] if tail else '-'})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[torchao] uninstall fallo: {e}", flush=True)


def find_model_dir():
    import glob
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [c for c in cands if "3b-instruct" in c.lower()] or cands
    if not pool:
        raise FileNotFoundError("sin modelo bajo /kaggle/input")
    pool.sort(key=len)
    print(f"[model] {pool[0]}", flush=True)
    return pool[0]


def find_base_eval():
    for root, _d, files in os.walk("/kaggle/input"):
        if "eval_p2_base.json" in files:
            print(f"[base-eval] {root}", flush=True)
            return json.loads(open(f"{root}/eval_p2_base.json", encoding="utf-8").read())
    print("[base-eval] NO encontrado — deltas quedan sin calcular en kernel", flush=True)
    return None


def save(out):
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


# ───────────────────────── datos de fine-tune (§3) ─────────────────────────


def pick_field(row, names):
    for n in names:
        if n in row and row[n]:
            return row[n]
    return None


def load_train_messages(out):
    """→ lista de messages (chat) con higiene verificada por asserts."""
    from datasets import load_dataset
    gsm = load_dataset("Danielbrdz/gsm8k-ES", split="train")
    print(f"[data] gsm8k-ES: {len(gsm)} items, campos {gsm.column_names}", flush=True)
    items = []
    for r in gsm:
        q = pick_field(r, ("question", "pregunta", "instruction", "input"))
        a = pick_field(r, ("answer", "respuesta", "output", "response"))
        if not q or not a:
            continue
        if "####" not in a:                       # preservar la convención de extracción
            continue
        items.append((q.strip(), a.strip()))
    assert len(items) > 6000, f"gsm8k-ES sospechoso: {len(items)} items válidos"

    # GP2-3 (auditoría automatizable): en 20 items muestreados, el número final parsea y hay CoT
    rng = random.Random(1234)
    bad = 0
    for q, a in rng.sample(items, 20):
        if extract_strict(a) is None or len(a) < 40:
            bad += 1
    out["gates"]["GP2_3_calidad_gsm"] = {"bad_of_20": bad, "pass": bad <= 2}
    print(f"[GP2-3] {bad}/20 items malos -> {'PASS' if bad <= 2 else 'FAIL'}", flush=True)
    assert bad <= 2, "GP2-3 FAIL: gsm8k-ES corrupto — abortar y re-planear (02_FASE2 §3.4)"

    # exclusión de exemplars MGSM (por respuesta final + multiconjunto de números de la pregunta)
    mg_tr = load_dataset("juletxara/mgsm", "es", split="train")
    ex_keys = {(norm_number(str(r["answer_number"])), num_multiset(r["question"])) for r in mg_tr}
    before = len(items)
    items = [(q, a) for q, a in items
             if (extract_strict(a), num_multiset(q)) not in ex_keys]
    print(f"[decontam] exemplars excluidos: {before - len(items)}", flush=True)

    hermes_msgs = []
    try:
        oh = load_dataset("Iker/OpenHermes-2.5-Spanish", split="train", streaming=True)
        role_map = {"human": "user", "gpt": "assistant", "system": "system"}
        for r in oh:
            conv = r.get("conversations")
            if conv:
                msgs = [{"role": role_map.get(t.get("from", ""), "user"),
                         "content": t.get("value", "")} for t in conv]
            else:
                q = pick_field(r, ("instruction", "prompt", "question"))
                a = pick_field(r, ("output", "response", "answer"))
                if not q or not a:
                    continue
                msgs = [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
            if sum(len(m["content"]) for m in msgs) <= 2000:   # ~≤512 tok
                hermes_msgs.append(msgs)
            if len(hermes_msgs) >= HERMES_N:
                break
        print(f"[data] hermes-es: {len(hermes_msgs)} convs", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[data] hermes-es fallo ({e!r}) -> sigue solo gsm (se declara)", flush=True)
        out["desvios"] = out.get("desvios", []) + ["hermes-es no cargó; train solo gsm8k-ES"]

    gsm_msgs = [[{"role": "user", "content": q}, {"role": "assistant", "content": a}]
                for q, a in items]

    # decontaminación §3-2: hash normalizado de las 3 suites vs TODO el train (assert = 0)
    mg_te = load_dataset("juletxara/mgsm", "es", split="test")
    bele = load_dataset("facebook/belebele", "spa_Latn", split="test")
    xsc = load_dataset("juletxara/xstory_cloze", "es", split="eval")
    test_hashes = ({norm_hash(r["question"]) for r in mg_te}
                   | {norm_hash(r["flores_passage"] + r["question"]) for r in bele}
                   | {norm_hash(" ".join(r[f"input_sentence_{k}"] for k in (1, 2, 3, 4)))
                      for r in xsc})
    train_hashes = {norm_hash(m["content"]) for conv in gsm_msgs + hermes_msgs
                    for m in conv if m["role"] == "user"}
    inter = test_hashes & train_hashes
    out["gates"]["decontaminacion"] = {"interseccion": len(inter), "pass": len(inter) == 0}
    print(f"[decontam] intersección train∩test = {len(inter)}", flush=True)
    assert not inter, f"CONTAMINACIÓN: {len(inter)} hashes compartidos — abortar"
    return gsm_msgs, hermes_msgs, (mg_te, mg_tr, bele, xsc)


def build_token_stream(tokenizer, gsm_msgs, hermes_msgs, epochs=2):
    """Stream de tokens chat-formateados, barajado por época, para packing en bloques SEQ."""
    import numpy as np
    parts = []
    for ep in range(epochs):
        rng = random.Random(ep)
        epoch = gsm_msgs + hermes_msgs
        rng.shuffle(epoch)
        for msgs in epoch:
            txt = tokenizer.apply_chat_template(msgs, tokenize=False)
            ids = tokenizer(txt, add_special_tokens=False)["input_ids"]
            parts.append(np.asarray(ids, dtype=np.int32))
    stream = np.concatenate(parts)
    print(f"[pack] stream: {len(stream):,} tokens ({epochs} épocas)", flush=True)
    return stream


# ───────────────────────── eval (idéntica a P2-K1 — copiada, kernels self-contained) ───────────────


def build_nll_scorer(model, tokenizer, device):
    import torch
    import torch.nn.functional as F

    @torch.no_grad()
    def score_options(prompt, options, batch=8):
        pre = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                            tokenize=False, add_generation_prompt=True)
        pre_ids = tokenizer(pre, add_special_tokens=False)["input_ids"]
        nlls = []
        for i in range(0, len(options), batch):
            chunk = options[i:i + batch]
            seqs = [pre_ids + tokenizer(o, add_special_tokens=False)["input_ids"] for o in chunk]
            maxlen = max(len(s) for s in seqs)
            pad = tokenizer.pad_token_id or tokenizer.eos_token_id
            inp = torch.full((len(seqs), maxlen), pad, dtype=torch.long)
            att = torch.zeros((len(seqs), maxlen), dtype=torch.long)
            for j, s in enumerate(seqs):
                inp[j, :len(s)] = torch.tensor(s)
                att[j, :len(s)] = 1
            inp, att = inp.to(device), att.to(device)
            logits = model(input_ids=inp, attention_mask=att).logits.float()
            logp = F.log_softmax(logits, dim=-1)
            for j, s in enumerate(seqs):
                n_opt = len(s) - len(pre_ids)
                pos = torch.arange(len(pre_ids) - 1, len(s) - 1, device=device)
                tgt = inp[j, len(pre_ids):len(s)]
                lp = logp[j, pos, :].gather(1, tgt[:, None])
                nlls.append(-float(lp.mean()) if n_opt > 0 else float("inf"))
        return nlls

    return score_options


def run_mc_suite(name, items, score_options, out, t0, budget_min, log_every=100):
    correct = n = 0
    t_suite = time.time()
    for k, (prompt, opts, ans) in enumerate(items):
        nlls = score_options(prompt, opts)
        correct += int(min(range(len(nlls)), key=lambda i: nlls[i]) == ans)
        n += 1
        if (k + 1) % log_every == 0:
            print(f"[{name}] {k + 1}/{len(items)} acc={correct / n:.3f}", flush=True)
            out["suites"][name] = {"acc": round(correct / n, 4), "n": n, "partial": True}
            save(out)
            if (time.time() - t0) / 60 > budget_min:
                print(f"[{name}] BUDGET — corto con n={n}", flush=True)
                break
    se = (correct / n * (1 - correct / n) / n) ** 0.5 if n else 0.0
    out["suites"][name] = {"acc": round(correct / n, 4), "n": n, "se": round(se, 4),
                           "minutes": round((time.time() - t_suite) / 60, 1), "partial": False}
    print(f"[{name}] FINAL acc={correct / n:.4f} (n={n})", flush=True)
    save(out)


def run_mgsm(tag, items, fewshot, model, tokenizer, device, out, t0, budget_min,
             batch=16, max_new=384):
    import torch
    strict_ok = lax_ok = trunc = n = 0
    t_suite = time.time()
    tokenizer.padding_side = "left"
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        prompts = []
        for q, _a in chunk:
            msgs = []
            for fq, fa in fewshot:
                msgs += [{"role": "user", "content": MGSM_PROMPT.format(q=fq)},
                         {"role": "assistant", "content": fa}]
            msgs.append({"role": "user", "content": MGSM_PROMPT.format(q=q)})
            prompts.append(tokenizer.apply_chat_template(msgs, tokenize=False,
                                                         add_generation_prompt=True))
        enc = tokenizer(prompts, return_tensors="pt", padding=True,
                        add_special_tokens=False).to(device)
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
        for j, (_q, ans) in enumerate(chunk):
            txt = tokenizer.decode(gen[j, enc["input_ids"].shape[1]:], skip_special_tokens=True)
            trunc += int(len(tokenizer(txt, add_special_tokens=False)["input_ids"]) >= max_new - 2)
            strict_ok += int(extract_strict(txt) == ans)
            lax_ok += int(extract_lax(txt) == ans)
            n += 1
        print(f"[{tag}] {n}/{len(items)} estricta={strict_ok / n:.3f} laxa={lax_ok / n:.3f} "
              f"trunc={trunc}", flush=True)
        out["suites"][tag] = {"acc_strict": round(strict_ok / n, 4),
                              "acc_lax": round(lax_ok / n, 4), "n": n,
                              "truncated": trunc, "partial": True}
        save(out)
        if (time.time() - t0) / 60 > budget_min:
            print(f"[{tag}] BUDGET — corto con n={n}", flush=True)
            break
    se = (lax_ok / n * (1 - lax_ok / n) / n) ** 0.5 if n else 0.0
    out["suites"][tag] = {"acc_strict": round(strict_ok / n, 4), "acc_lax": round(lax_ok / n, 4),
                          "n": n, "se": round(se, 4), "truncated": trunc,
                          "minutes": round((time.time() - t_suite) / 60, 1), "partial": False}
    save(out)


# ───────────────────────── main ─────────────────────────


def _smoke():
    assert norm_number("1.234") == 1234 and norm_number("12,5") == 12.5
    assert extract_strict("x\n#### 42") == 42 and extract_lax("son 72.") == 72
    assert norm_hash("  ÁRBOL verde ") == norm_hash("arbolverde")
    assert num_multiset("tiene 3 peras y 12 manzanas") == ("12", "3")
    ex_keys = {(42, ("12", "3"))}
    assert (extract_strict("bla #### 42"), num_multiset("3 y 12")) in ex_keys
    print("[smoke] p2k2 utils: OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        _smoke()
        return
    t0 = time.time()
    out = {"experiment": "xh_p2k2_qlora", "suites": {}, "gates": {},
           "config": {"lora_r": 16, "lora_alpha": 32, "dropout": 0.05, "lr": LR,
                      "seq": SEQ, "micro_b": MICRO_B, "accum": ACCUM,
                      "train_wall_s": TRAIN_WALL_S,
                      "targets": "q,k,v,o,gate,up,down_proj"}}

    use_bnb = _ensure_bitsandbytes()
    _disable_torchao()                      # ANTES de importar peft
    import numpy as np
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    device = "cuda"
    model_dir = find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.float16,
                               bnb_4bit_use_double_quant=True) if use_bnb else None
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=quant, torch_dtype=torch.float16,
        device_map={"": 0}, trust_remote_code=True)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
    model.config.use_cache = False
    lcfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                      task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lcfg)
    for n_, p in model.named_parameters():     # LoRA en fp32 (lección del pipeline, GradScaler)
        if p.requires_grad:
            p.data = p.data.float()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[lora] trainable={trainable / 1e6:.1f}M", flush=True)
    out["config"]["trainable_params"] = trainable

    gsm_msgs, hermes_msgs, (mg_te, mg_tr, bele, xsc) = load_train_messages(out)
    stream = build_token_stream(tokenizer, gsm_msgs, hermes_msgs, epochs=2)
    out["train_tokens_available"] = int(len(stream))
    save(out)

    # ── train con corte por reloj (el wall manda) ──
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                            lr=LR, betas=(0.9, 0.95), weight_decay=0.0)
    # micro-desvío declarado: AdamW fp32 sobre ~30M params LoRA (~0.5GB) en vez de
    # paged_adamw_8bit del plan — misma matemática, sin dependencia extra; se anota.
    out.setdefault("desvios", []).append("optimizer=AdamW fp32 (no paged_8bit): estados ~0.5GB")
    scaler = torch.amp.GradScaler("cuda")
    n_blocks = (len(stream) - 1) // SEQ
    order = list(range(n_blocks))
    total_micro_planned = n_blocks // MICRO_B * MICRO_B
    warmup_micro = max(8, int(0.03 * total_micro_planned))
    model.train()
    t_train = time.time()
    micro = 0
    tokens_seen = 0
    losses = []
    out["curve"] = []
    stream_t = torch.from_numpy(stream.astype(np.int64))
    while micro < total_micro_planned and (time.time() - t_train) < TRAIN_WALL_S:
        rows = [stream_t[order[(micro + j) % n_blocks] * SEQ:
                         order[(micro + j) % n_blocks] * SEQ + SEQ]
                for j in range(MICRO_B)]
        micro += MICRO_B
        x = torch.stack(rows).to(device)
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            loss = model(input_ids=x, labels=x).loss / ACCUM   # media sobre la acumulación
        scaler.scale(loss).backward()
        tokens_seen += MICRO_B * SEQ
        losses.append(float(loss.detach()) * ACCUM)
        if micro % (MICRO_B * ACCUM) == 0:
            step = micro // (MICRO_B * ACCUM)
            progress = (time.time() - t_train) / TRAIN_WALL_S
            f = (step / max(1, warmup_micro // ACCUM) if step <= warmup_micro // ACCUM
                 else 0.5 * (1 + math.cos(math.pi * min(1.0, progress))))
            for gr in opt.param_groups:
                gr["lr"] = LR * f
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            if step % 20 == 0:
                mean_l = sum(losses[-80:]) / len(losses[-80:])
                el = time.time() - t_train
                print(f"[train] step {step} loss {mean_l:.4f} lr_f {f:.3f} "
                      f"{tokens_seen / el:.0f} tok/s ({el / 60:.1f} min)", flush=True)
                out["curve"].append({"step": step, "loss": round(mean_l, 4),
                                     "tokens": tokens_seen, "s": round(el)})
                save(out)
    out["train"] = {"micro_batches": micro, "tokens_seen": tokens_seen,
                    "epochs_done": round(tokens_seen / max(1, len(stream) / 2), 2),
                    "minutes": round((time.time() - t_train) / 60, 1),
                    "loss_final": round(sum(losses[-80:]) / max(1, len(losses[-80:])), 4)}
    print(f"[train] FIN: {out['train']}", flush=True)
    model.eval()
    model.config.use_cache = True
    try:
        model.save_pretrained(ADAPTER_DIR)
        print(f"[adapter] -> {ADAPTER_DIR}/", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[adapter] save fallo: {e!r}", flush=True)
    save(out)

    # ── eval (mismo harness que P2-K1) ──
    bele_items = [(f"Pasaje: {r['flores_passage']}\n\nPregunta: {r['question']}\nRespuesta:",
                   [" " + r[f"mc_answer{k}"] for k in (1, 2, 3, 4)],
                   int(r["correct_answer_num"]) - 1) for r in bele]
    xsc_items = [((r["input_sentence_1"] + " " + r["input_sentence_2"] + " "
                   + r["input_sentence_3"] + " " + r["input_sentence_4"]
                   + "\n\n¿Cómo termina la historia?"),
                  [" " + r["sentence_quiz1"], " " + r["sentence_quiz2"]],
                  int(r["answer_right_ending"]) - 1) for r in xsc]
    mgsm_items = [(r["question"], norm_number(str(r["answer_number"]))) for r in mg_te]
    fewshot = [(mg_tr[i]["question"],
                (mg_tr[i]["answer"] or "") + f"\n#### {mg_tr[i]['answer_number']}")
               for i in FEWSHOT_IDX]
    base_eval = find_base_eval()
    # espejo de recortes GP2-2 del base: mismas suites y tamaños que P2-K1 haya corrido
    if base_eval:
        n_bele = base_eval["suites"].get("belebele", {}).get("n", len(bele_items))
        bele_items = bele_items[:n_bele]
        ran_3shot = "mgsm_3shot" in base_eval["suites"]
    else:
        ran_3shot = False

    score_options = build_nll_scorer(model, tokenizer, device)
    run_mgsm("mgsm_0shot", mgsm_items, [], model, tokenizer, device, out, t0, BUDGET_MIN)
    run_mc_suite("xstorycloze", xsc_items, score_options, out, t0, BUDGET_MIN * 0.85)
    run_mc_suite("belebele", bele_items, score_options, out, t0, BUDGET_MIN * 0.95)
    if ran_3shot and (time.time() - t0) / 60 < BUDGET_MIN * 0.85:
        run_mgsm("mgsm_3shot", mgsm_items, fewshot, model, tokenizer, device, out, t0, BUDGET_MIN)

    # ── deltas + reglas pre-registradas (§4) ──
    if base_eval:
        b, f = base_eval["suites"], out["suites"]
        d = {}
        if "mgsm_0shot" in b and "mgsm_0shot" in f:
            d["P1_mgsm_strict"] = round((f["mgsm_0shot"]["acc_strict"]
                                         - b["mgsm_0shot"]["acc_strict"]) * 100, 1)
            d["P2_mgsm_lax"] = round((f["mgsm_0shot"]["acc_lax"]
                                      - b["mgsm_0shot"]["acc_lax"]) * 100, 1)
        if "mgsm_3shot" in b and "mgsm_3shot" in f:
            d["P3_mgsm3_lax"] = round((f["mgsm_3shot"]["acc_lax"]
                                       - b["mgsm_3shot"]["acc_lax"]) * 100, 1)
        if "xstorycloze" in b and "xstorycloze" in f:
            d["P4_xsc"] = round((f["xstorycloze"]["acc"] - b["xstorycloze"]["acc"]) * 100, 1)
        if "belebele" in b and "belebele" in f:
            d["P5_belebele"] = round((f["belebele"]["acc"] - b["belebele"]["acc"]) * 100, 1)
        out["deltas_pts"] = d
        out["veredicto"] = {
            "gana_nicho": bool(d.get("P1_mgsm_strict", -99) >= 6 and d.get("P2_mgsm_lax", -99) >= 4),
            "solo_formato": bool(d.get("P1_mgsm_strict", 0) >= 6 and d.get("P2_mgsm_lax", 0) < 4),
            "no_catastrofe": bool(d.get("P4_xsc", 0) >= -3 and d.get("P5_belebele", 0) >= -4),
            "sospecha_harness": bool(d.get("P4_xsc", 0) > 2.4 or d.get("P5_belebele", 0) > 3.0),
        }
        print(f"[deltas] {d}", flush=True)
        print(f"[veredicto] {out['veredicto']}", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(f"[p2k2] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()
