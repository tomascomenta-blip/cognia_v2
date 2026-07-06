# -*- coding: ascii -*-
"""
E0 - SMOKE + PERFIL del entrenamiento QLoRA 3B en Kaggle T4 (COGNIA 3B).

Kernel de Kaggle (script, GPU T4, internet ON). NO entrena nada util: MIDE.
Pre-registro (TEORIA_COGNIA3B.md Parte 7, E0):
  - Ancla [MEDIDO]: p2k2 dio ~424 tok/s (Qwen2.5-3B NF4 r16 all-linear seq1024
    mb4+GC AdamW fp32 sin packing). La config A reproduce ese regimen sobre
    Qwen2.5-Coder-3B: si A no cae en 300-550 tok/s, el harness esta mal.
  - Predicciones a falsar:
    P-E0a: pesos 3B NF4+DQ = 2.0-2.4 GB alocados tras el load.
    P-E0b: paged_adamw_8bit libera >=0.15 GB vs AdamW fp32 (estados 30M params)
           y permite subir micro-batch sin OOM.
    P-E0c: la mejor config util (packing + mb alto) alcanza >=800 tok/s UTILES
           (tokens no-pad); si <500, re-dimensionar corpora del programa.
    P-E0d: Unsloth instala y corre en T4/sm_75 y da >=1.3x vs la mejor config
           equivalente nuestra; si falla o <1.3x, runtime = transformers+PEFT.
  - Gate de exito del kernel: >=8 configs medidas sin colgarse + JSON completo.

Salida: /kaggle/working/e0_results.json (se reescribe tras CADA config:
descarga incremental, leccion del repo). Cada registro: config exacta,
tok/s seq, tok/s utiles, VRAM pico (allocated/reserved), loss inicial/final,
escala del GradScaler, steps salteados por inf/NaN, o el error si fallo.
"""
import gc
import glob
import json
import math
import os
import subprocess
import sys
import time

T0 = time.time()
BUDGET_S = 105 * 60          # presupuesto duro del kernel (sesion corta)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e0_results.json")
SEED = 20260706

RESULTS = {"exp": "E0-perfil", "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "env": {}, "dataset_stats": {}, "configs": [], "unsloth": None,
           "packing_masking_inspeccion": None}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    print(f"[sh] {' '.join(cmd[:6])}... rc={r.returncode} ({tail[-1] if tail else 'sin output'})", flush=True)
    return r


# ---------------------------------------------------------------- entorno
def prepara_entorno():
    # 1) torchao del image ROMPE peft (is_torchao_available lanza ImportError)
    #    -> desinstalar ANTES de importar peft (leccion train_tooluse_kaggle).
    sh([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"])
    # 2) bitsandbytes del image es viejo; el load 4-bit muere sin >=0.46.1
    #    (fix 8b67ac3). Hacerlo ANTES de importar transformers (cachea).
    sh([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"])


def _find_model_dir() -> str:
    cands = [os.path.dirname(p) for p in
             glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    if not pool:
        raise FileNotFoundError("No hay modelo montado bajo /kaggle/input")
    pool.sort(key=len)
    return pool[0]


def _find_dataset() -> str:
    hits = glob.glob("/kaggle/input/**/cognia_dataset.jsonl", recursive=True) or \
           glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
    if not hits:
        raise FileNotFoundError("No hay JSONL bajo /kaggle/input")
    return hits[0]


# ---------------------------------------------------------------- datos
def carga_pares(path, tokenizer, max_pares=1200):
    """Pares {prompt, completion} -> dicts tokenizados ChatML con span del prompt."""
    pares = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "prompt" in r and "completion" in r:
                pares.append(r)
            if len(pares) >= max_pares:
                break
    ejemplos = []
    for r in pares:
        pre = f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n"
        full = pre + f"{r['completion']}<|im_end|>"
        ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
        ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
        ejemplos.append({"ids": ids_full, "prompt_len": len(ids_pre)})
    return ejemplos


def stats_longitudes(ejemplos, seqs=(1024, 2048)):
    lens = sorted(len(e["ids"]) for e in ejemplos)
    n = len(lens)
    st = {"n": n, "len_p50": lens[n // 2], "len_p90": lens[int(n * 0.9)],
          "len_max": lens[-1], "len_mean": round(sum(lens) / n, 1)}
    for s in seqs:
        # utilizacion si se padea cada ejemplo a seq s (sin packing)
        util = sum(min(l, s) for l in lens) / (n * s)
        st[f"util_pad_seq{s}"] = round(util, 3)
    return st


def lotes_padded(ejemplos, seq, mb, pad_id, masking):
    """Batches (input_ids, attention_mask, labels) padeados a seq fijo."""
    lotes = []
    for i in range(0, len(ejemplos) - mb + 1, mb):
        chunk = ejemplos[i:i + mb]
        ids, att, lab = [], [], []
        for e in chunk:
            x = e["ids"][:seq]
            pad = seq - len(x)
            ids.append(x + [pad_id] * pad)
            att.append([1] * len(x) + [0] * pad)
            y = list(x)
            if masking:
                pl = min(e["prompt_len"], len(x))
                y[:pl] = [-100] * pl
            lab.append(y + [-100] * pad)
        lotes.append((ids, att, lab))
    return lotes


def lotes_packed(ejemplos, seq, mb, masking):
    """Packing greedy: concatena ejemplos hasta llenar seq (sin cruzar el limite).

    v0 SIN mascara de atencion por documento (contaminacion cross-doc posible):
    para PERFIL de throughput es representativo; la correccion de calidad se
    decide en E1. Labels: si masking, -100 sobre el span de prompt de CADA doc.
    """
    filas, fila, lab, restante = [], [], [], seq
    for e in ejemplos:
        x = e["ids"]
        if len(x) > seq:
            x = x[:seq]
        if len(x) > restante:
            if fila:
                filas.append((fila, lab))
            fila, lab, restante = [], [], seq
        y = list(x)
        if masking:
            pl = min(e["prompt_len"], len(x))
            y[:pl] = [-100] * pl
        fila += x
        lab += y
        restante -= len(x)
    if fila:
        filas.append((fila, lab))
    lotes = []
    for i in range(0, len(filas) - mb + 1, mb):
        chunk = filas[i:i + mb]
        ids, att, labs = [], [], []
        for fila, lab in chunk:
            pad = seq - len(fila)
            ids.append(fila + [0] * pad)
            att.append([1] * len(fila) + [0] * pad)
            labs.append(lab + [-100] * pad)
        lotes.append((ids, att, labs))
    return lotes


# ---------------------------------------------------------------- medicion
def mide_config(cfg, base_model, tokenizer, ejemplos):
    """Corre warmup + steps cronometrados de una config. Devuelve registro."""
    import torch
    from bitsandbytes.optim import PagedAdamW8bit

    reg = dict(cfg)
    seq, mb, ga = cfg["seq"], cfg["mb"], cfg.get("ga", 1)
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    if cfg["packing"]:
        lotes = lotes_packed(ejemplos, seq, mb, cfg["masking"])
    else:
        lotes = lotes_padded(ejemplos, seq, mb, pad_id, cfg["masking"])
    # steps para ~80k tokens cronometrados (acota el tiempo por config)
    steps_timed = max(6, math.ceil(80_000 / (mb * seq)))
    warmup = 3
    total_steps = warmup + steps_timed
    if len(lotes) < total_steps:
        reg["error"] = f"dataset corto: {len(lotes)} lotes < {total_steps}"
        return reg

    params = [p for p in base_model.parameters() if p.requires_grad]
    if cfg["optim"] == "paged8bit":
        opt = PagedAdamW8bit(params, lr=1e-4)
    else:
        opt = torch.optim.AdamW(params, lr=1e-4)
    scaler = torch.amp.GradScaler("cuda")
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()

    losses, skipped = [], 0
    t_start = None
    tok_seq = tok_util = 0
    try:
        base_model.train()
        for step, (ids, att, lab) in enumerate(lotes[:total_steps]):
            if step == warmup:
                torch.cuda.synchronize()
                t_start = time.time()
            x = torch.tensor(ids, dtype=torch.long, device="cuda")
            a = torch.tensor(att, dtype=torch.long, device="cuda")
            y = torch.tensor(lab, dtype=torch.long, device="cuda")
            with torch.autocast("cuda", dtype=torch.float16):
                out = base_model(input_ids=x, attention_mask=a, labels=y)
            loss = out.loss / ga
            scaler.scale(loss).backward()
            if (step + 1) % ga == 0:
                old_scale = scaler.get_scale()
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)
                if scaler.get_scale() < old_scale:
                    skipped += 1
            losses.append(out.loss.item())
            if step >= warmup:
                tok_seq += mb * seq
                tok_util += int(a.sum().item())
        torch.cuda.synchronize()
        dt = time.time() - t_start
        reg.update({
            "steps_timed": steps_timed, "wall_s": round(dt, 1),
            "tok_s_seq": round(tok_seq / dt, 1),
            "tok_s_util": round(tok_util / dt, 1),
            "vram_alloc_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
            "vram_reserved_gb": round(torch.cuda.max_memory_reserved() / 1e9, 2),
            "loss_ini": round(sum(losses[:3]) / 3, 3),
            "loss_fin": round(sum(losses[-3:]) / 3, 3),
            "nan": any(math.isnan(l) for l in losses),
            "scaler_final": scaler.get_scale(), "steps_skipped_inf": skipped,
        })
    except torch.cuda.OutOfMemoryError as e:
        reg["error"] = f"OOM: {str(e)[:200]}"
        reg["vram_reserved_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
    finally:
        opt.zero_grad(set_to_none=True)
        del opt
        gc.collect()
        torch.cuda.empty_cache()
    return reg


def construye_modelo(model_dir, lora_r, targets):
    """Carga la base NF4 + adapter LoRA. Devuelve el peft model (GC ON)."""
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map="auto",
        attn_implementation="sdpa", trust_remote_code=True)
    import torch as _t
    peso_gb = round(_t.cuda.memory_allocated() / 1e9, 2)
    # GC ON obligatorio: mb4 sin GC OOMeo en p2k2 [MEDIDO 01_DESVIOS.md]
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    cfg = LoraConfig(r=lora_r, lora_alpha=2 * lora_r, lora_dropout=0.05,
                     bias="none", task_type="CAUSAL_LM", target_modules=targets)
    model = get_peft_model(model, cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.print_trainable_parameters()
    return model, peso_gb


QKVO = ["q_proj", "k_proj", "v_proj", "o_proj"]
ALL_LIN = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

# Grilla fraccionada pre-registrada (orden = importancia; el budget corta la cola).
# Grupos por forma del adapter para minimizar recargas del 3B.
GRUPOS = [
    {"r": 16, "targets": ALL_LIN, "configs": [
        # A: reproduce el regimen p2k2 (ancla 424 tok/s) sobre Coder-3B
        {"nombre": "A_control_p2k2", "seq": 1024, "mb": 4, "ga": 4, "optim": "adamw_fp32", "packing": False, "masking": False},
        {"nombre": "B_paged8bit",    "seq": 1024, "mb": 4, "ga": 1, "optim": "paged8bit",  "packing": False, "masking": False},
        {"nombre": "C_mb8",          "seq": 1024, "mb": 8, "ga": 1, "optim": "paged8bit",  "packing": False, "masking": False},
        {"nombre": "D_mb8_pack",     "seq": 1024, "mb": 8, "ga": 1, "optim": "paged8bit",  "packing": True,  "masking": False},
        {"nombre": "G_mb8_mask",     "seq": 1024, "mb": 8, "ga": 1, "optim": "paged8bit",  "packing": False, "masking": True},
        {"nombre": "E_mb16_pack",    "seq": 1024, "mb": 16, "ga": 1, "optim": "paged8bit", "packing": True,  "masking": False},
        {"nombre": "F_seq2048_mb4_pack", "seq": 2048, "mb": 4, "ga": 1, "optim": "paged8bit", "packing": True, "masking": False},
        {"nombre": "J_mb2",          "seq": 1024, "mb": 2, "ga": 1, "optim": "paged8bit",  "packing": False, "masking": False},
    ]},
    {"r": 8, "targets": QKVO, "configs": [
        {"nombre": "H_r8_qkvo_mb8_pack", "seq": 1024, "mb": 8, "ga": 1, "optim": "paged8bit", "packing": True, "masking": False},
    ]},
    {"r": 32, "targets": ALL_LIN, "configs": [
        {"nombre": "I_r32_mb8_pack", "seq": 1024, "mb": 8, "ga": 1, "optim": "paged8bit", "packing": True, "masking": False},
    ]},
]

UNSLOTH_PROBE = r'''
import json, math, time, sys, glob, os
res = {"instalado": True}
try:
    from unsloth import FastLanguageModel
    import torch
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    model_dir = pool[0]
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_dir, max_seq_length=1024, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
        use_gradient_checkpointing="unsloth", random_state=20260706)
    hits = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
    pares = []
    with open(hits[0], encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if "prompt" in r and "completion" in r:
                    pares.append(r)
            except Exception:
                pass
            if len(pares) >= 400:
                break
    textos = ["<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s<|im_end|>" % (r["prompt"], r["completion"]) for r in pares]
    for mb in (4, 8):
        enc = [tokenizer(t, truncation=True, max_length=1024)["input_ids"] for t in textos]
        pad = tokenizer.pad_token_id or tokenizer.eos_token_id
        lotes = []
        for i in range(0, len(enc) - mb + 1, mb):
            chunk = enc[i:i+mb]
            ids = [x + [pad]*(1024-len(x)) for x in chunk]
            att = [[1]*len(x) + [0]*(1024-len(x)) for x in chunk]
            lab = [x + [-100]*(1024-len(x)) for x in chunk]
            lotes.append((ids, att, lab))
        params = [p for p in model.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(params, lr=1e-4)
        torch.cuda.reset_peak_memory_stats()
        steps = max(6, math.ceil(80000 / (mb*1024)))
        model.train()
        t0 = None; tok = 0; util = 0
        for step, (ids, att, lab) in enumerate(lotes[:3+steps]):
            if step == 3:
                torch.cuda.synchronize(); t0 = time.time()
            x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
            y = torch.tensor(lab, device="cuda")
            out = model(input_ids=x, attention_mask=a, labels=y)
            out.loss.backward()
            opt.step(); opt.zero_grad(set_to_none=True)
            if step >= 3:
                tok += mb*1024; util += int(a.sum().item())
        torch.cuda.synchronize()
        dt = time.time() - t0
        res["mb%d" % mb] = {"tok_s_seq": round(tok/dt, 1), "tok_s_util": round(util/dt, 1),
                            "vram_alloc_gb": round(torch.cuda.max_memory_allocated()/1e9, 2)}
        del opt
except Exception as e:
    res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
with open("/kaggle/working/unsloth_probe.json", "w") as f:
    json.dump(res, f)
print("UNSLOTH_PROBE_DONE", json.dumps(res)[:400])
'''


def prueba_unsloth():
    """Instala unsloth y corre el probe en SUBPROCESO (aisla sus parches)."""
    reg = {"pip_ok": False}
    t_ins = time.time()
    r = sh([sys.executable, "-m", "pip", "install", "unsloth"], timeout=1200)
    reg["pip_s"] = round(time.time() - t_ins, 1)
    reg["pip_ok"] = r.returncode == 0
    if not reg["pip_ok"]:
        reg["error"] = (r.stderr or "")[-400:]
        return reg
    probe_path = os.path.join(OUT, "unsloth_probe.py")
    with open(probe_path, "w", encoding="utf-8") as f:
        f.write(UNSLOTH_PROBE)
    try:
        r = subprocess.run([sys.executable, probe_path], capture_output=True,
                           text=True, timeout=1800)
        print((r.stdout or "")[-2000:], flush=True)
        out_json = os.path.join(OUT, "unsloth_probe.json")
        if os.path.exists(out_json):
            with open(out_json, encoding="utf-8") as f:
                reg["probe"] = json.load(f)
        else:
            reg["error"] = "probe sin JSON: " + (r.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        reg["error"] = "probe timeout 30 min"
    return reg


def main():
    import random
    random.seed(SEED)
    prepara_entorno()

    import torch
    from transformers import AutoTokenizer
    import transformers
    import peft
    import bitsandbytes as bnb_mod

    RESULTS["env"] = {
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "gpu_count": torch.cuda.device_count(),
        "vram_total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
                         if torch.cuda.is_available() else 0,
        "torch": torch.__version__, "transformers": transformers.__version__,
        "peft": peft.__version__, "bitsandbytes": bnb_mod.__version__,
    }
    print("ENV:", json.dumps(RESULTS["env"]), flush=True)
    if not torch.cuda.is_available():
        RESULTS["error"] = "SIN GPU: revisar machine_shape en metadata"
        dump()
        return

    model_dir = _find_model_dir()
    RESULTS["env"]["model_dir"] = model_dir
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    ejemplos = carga_pares(_find_dataset(), tokenizer)
    random.shuffle(ejemplos)
    RESULTS["dataset_stats"] = stats_longitudes(ejemplos)
    print("DATASET:", json.dumps(RESULTS["dataset_stats"]), flush=True)
    dump()

    # Inspeccion de labels packed+masking (pregunta abierta pre-registrada):
    # el primer lote packed con masking, decodificado por spans de labels.
    lote = lotes_packed(ejemplos, 1024, 1, True)[0]
    ids, att, lab = lote
    spans, dentro = [], False
    for i, l in enumerate(lab[0]):
        if l != -100 and not dentro:
            spans.append([i, i])
            dentro = True
        elif l != -100:
            spans[-1][1] = i
        else:
            dentro = False
    RESULTS["packing_masking_inspeccion"] = {
        "n_spans_entrenables": len(spans),
        "spans_primeros3_decodificados": [
            tokenizer.decode(ids[0][a:b + 1])[:120] for a, b in spans[:3]],
        "frac_tokens_entrenables": round(
            sum(b - a + 1 for a, b in spans) / sum(att[0]), 3),
    }
    dump()

    for grupo in GRUPOS:
        if time.time() - T0 > BUDGET_S:
            print("BUDGET agotado antes del grupo r=%d" % grupo["r"], flush=True)
            break
        print(f"== GRUPO r={grupo['r']} targets={len(grupo['targets'])} ==", flush=True)
        try:
            model, peso_gb = construye_modelo(model_dir, grupo["r"], grupo["targets"])
        except Exception as e:
            RESULTS["configs"].append({"grupo_r": grupo["r"],
                                       "error": f"load: {str(e)[:300]}"})
            dump()
            continue
        RESULTS.setdefault("peso_base_gb", peso_gb)
        for cfg in grupo["configs"]:
            if time.time() - T0 > BUDGET_S:
                print("BUDGET agotado en", cfg["nombre"], flush=True)
                break
            cfg = dict(cfg, r=grupo["r"], targets="all" if len(grupo["targets"]) == 7 else "qkvo")
            print(f"-- {cfg['nombre']} --", flush=True)
            reg = mide_config(cfg, model, tokenizer, ejemplos)
            print(json.dumps(reg), flush=True)
            RESULTS["configs"].append(reg)
            dump()
        del model
        gc.collect()
        torch.cuda.empty_cache()

    # Unsloth al FINAL (sus parches no contaminan las mediciones baseline)
    if time.time() - T0 < BUDGET_S - 10 * 60:
        RESULTS["unsloth"] = prueba_unsloth()
        dump()
    else:
        RESULTS["unsloth"] = {"skip": "sin budget"}
        dump()

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E0 DONE en", RESULTS["wall_total_min"], "min", flush=True)


if __name__ == "__main__":
    main()
