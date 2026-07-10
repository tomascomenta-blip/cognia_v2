# -*- coding: utf-8 -*-
"""
E-PORT - PORTERO 0.5B del MoM (PLAN_MOM_GLM52 #5, PREREG_PORTERO.md).

Entrena LoRA r16 (receta E-GROK) sobre Qwen2.5-0.5B-Instruct con e1_train
(general+identidad, dataset emix) y evalua PAREADO base-vs-adapter:
  P-PORT-1 (gate): G3 identidad >= 90% con adapter
  P-PORT-2 (info): G1 general reportado (para el umbral del router)

0.5B en fp16 pelado (entra sobrado en T4; sin unsloth: el modelo es tan
chico que el overhead no importa). <1 GPU-h. [Esqueleto de ecod_kernel]
"""
import json
import math
import os
import random
import time

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

T0 = time.time()
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "eport_results.json")
SEED = 20260710
SEQ = 1024
LR = 3e-4
WARMUP = 0.10
MB = 8
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

RESULTS = {"exp": "E-PORT-portero-0.5B",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {"P-PORT-1": "G3 adapter >= 90% (gate)",
                            "P-PORT-2": "G1 adapter reportado (info router)"},
           "env": {}, "datos": {}, "train": {}, "evals": {}, "veredictos": {}}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def busca_input(nombre):
    for raiz, _dirs, files in os.walk("/kaggle/input"):
        if nombre in files:
            return os.path.join(raiz, nombre)
    raise FileNotFoundError(nombre)


def carga_jsonl(nombre):
    out = []
    with open(busca_input(nombre), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def mcnemar_p(n01, n10):
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


# ── oraculo (mismo contrato que suite_oracle, embebido: sin repo en kernel) ──
import re
import unicodedata


def fold(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


def ultimo_numero(t):
    hits = re.findall(r"-?\d+(?:[.,]\d+)?", t.replace("−", "-"))
    return float(hits[-1].replace(",", ".")) if hits else None


def oracle_pass(respuesta, oracle):
    r = fold(respuesta)
    if any(fold(k) not in r for k in (oracle.get("must_all") or [])):
        return False
    ma = oracle.get("must_any") or []
    if ma and not any(fold(k) in r for k in ma):
        return False
    if any(fold(k) in r for k in (oracle.get("not_any") or [])):
        return False
    if oracle.get("number") is not None:
        n = ultimo_numero(respuesta)
        if n is None or abs(n - float(oracle["number"])) > 1e-6:
            return False
    return True


SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."


def genera_batch(model, tokenizer, prompts, idiomas, max_new):
    import torch
    tokenizer.padding_side = "left"
    textos = [tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_ES if i == "es" else SYSTEM_EN},
         {"role": "user", "content": p}],
        tokenize=False, add_generation_prompt=True)
        for p, i in zip(prompts, idiomas)]
    enc = tokenizer(textos, return_tensors="pt", padding=True,
                    add_special_tokens=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True) for i in range(len(prompts))]


def eval_suite(model, tokenizer, items, etiqueta):
    binarios = {}
    for i in range(0, len(items), 16):
        chunk = items[i:i + 16]
        outs = genera_batch(model, tokenizer, [t["prompt"] for t in chunk],
                            [t.get("idioma", "es") for t in chunk],
                            max(t["max_new_tokens"] for t in chunk))
        for t, o in zip(chunk, outs):
            binarios[t["id"]] = bool(oracle_pass((o or "").strip(), t["oracle"]))
    acc = sum(binarios.values()) / len(binarios)
    print(f"  [{etiqueta}] {acc:.1%}", flush=True)
    return binarios


def lotes_packed(ejemplos, tokenizer):
    random.seed(SEED)
    random.shuffle(ejemplos)
    filas, fila, lab, restante = [], [], [], SEQ
    for e in ejemplos:
        pre = tokenizer.apply_chat_template(
            [{"role": "user", "content": e["prompt"]}],
            tokenize=False, add_generation_prompt=True)
        full = pre + e["completion"] + "<|im_end|>"
        ids = tokenizer(full, add_special_tokens=False)["input_ids"][:SEQ]
        pl = min(len(tokenizer(pre, add_special_tokens=False)["input_ids"]), len(ids))
        if len(ids) > restante:
            if fila:
                filas.append((fila, lab))
            fila, lab, restante = [], [], SEQ
        y = list(ids)
        y[:pl] = [-100] * pl
        fila += ids
        lab += y
        restante -= len(ids)
    if fila:
        filas.append((fila, lab))
    lotes = []
    for i in range(0, len(filas), MB):
        chunk = filas[i:i + MB]
        if len(chunk) < MB:
            break
        ids = [f + [0] * (SEQ - len(f)) for f, _ in chunk]
        att = [[1] * len(f) + [0] * (SEQ - len(f)) for f, _ in chunk]
        labs = [l + [-100] * (SEQ - len(l)) for _, l in chunk]
        lotes.append((ids, att, labs))
    return lotes


def main():
    import subprocess
    import sys
    # el torchao 0.10 preinstalado en Kaggle rompe el import de peft
    # (mismo workaround que ecod/erzn: desinstalar antes)
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"],
                   check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "peft"],
                   check=False)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model
    torch.manual_seed(SEED)

    RESULTS["env"] = {"gpu": torch.cuda.get_device_name(0),
                      "torch": torch.__version__, "model": MODEL_ID}
    dump()

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, torch_dtype=torch.float16, device_map={"": 0},
        attn_implementation="sdpa")
    base.eval()

    g1 = carga_jsonl("g1_general.jsonl")
    g3 = carga_jsonl("g3_identidad.jsonl")
    e1 = carga_jsonl("e1_train.jsonl")
    RESULTS["datos"] = {"e1_train": len(e1), "g1": len(g1), "g3": len(g3)}
    dump()

    print("== eval BASE 0.5B (pareado) ==", flush=True)
    RESULTS["evals"]["base"] = {"g3": eval_suite(base, tokenizer, g3, "base g3"),
                                "g1": eval_suite(base, tokenizer, g1, "base g1")}
    dump()

    # ── train E-GROK (LoRA r16 all-linear, 1 epoch) ──
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"],
                      task_type="CAUSAL_LM")
    model = get_peft_model(base, lora)
    model.train()
    lotes = lotes_packed(list(e1), tokenizer)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR)
    from torch.optim.lr_scheduler import LambdaLR
    total = len(lotes)
    w = max(1, int(total * WARMUP))
    sched = LambdaLR(opt, lambda s: (s + 1) / w if s < w else
                     0.5 * (1 + math.cos(math.pi * (s - w) / max(1, total - w))))
    losses = []
    t0 = time.time()
    for ids, att, labs in lotes:
        x = torch.tensor(ids, device="cuda")
        a = torch.tensor(att, device="cuda")
        y = torch.tensor(labs, device="cuda")
        loss = model(input_ids=x, attention_mask=a, labels=y).loss
        loss.backward()
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        losses.append(loss.item())
        if len(losses) % 20 == 0:
            print(f"  step {len(losses)}/{total} loss={losses[-1]:.4f}", flush=True)
    RESULTS["train"] = {"steps": len(losses), "wall_s": round(time.time() - t0, 1),
                        "loss_ini": round(sum(losses[:5]) / max(1, len(losses[:5])), 4),
                        "loss_fin": round(sum(losses[-5:]) / max(1, len(losses[-5:])), 4),
                        "nan": any(math.isnan(x) for x in losses)}
    model.save_pretrained(f"{OUT}/adapters/cognia_portero05b")
    tokenizer.save_pretrained(f"{OUT}/adapters/cognia_portero05b")
    print("TRAIN:", json.dumps(RESULTS["train"]), flush=True)
    dump()

    # ── eval adapter (pareado) ──
    model.eval()
    print("== eval PORTERO 0.5B + adapter ==", flush=True)
    RESULTS["evals"]["portero"] = {"g3": eval_suite(model, tokenizer, g3, "port g3"),
                                   "g1": eval_suite(model, tokenizer, g1, "port g1")}

    vb, vp = RESULTS["evals"]["base"], RESULTS["evals"]["portero"]
    for suite in ("g3", "g1"):
        b, p = vb[suite], vp[suite]
        n01 = sum(1 for k in b if not b[k] and p[k])
        n10 = sum(1 for k in b if b[k] and not p[k])
        RESULTS["veredictos"][suite] = {
            "acc_base": round(sum(b.values()) / len(b), 3),
            "acc_portero": round(sum(p.values()) / len(p), 3),
            "n01": n01, "n10": n10, "p": round(mcnemar_p(n01, n10), 4)}
    g3_acc = RESULTS["veredictos"]["g3"]["acc_portero"]
    RESULTS["veredictos"]["P-PORT-1"] = [g3_acc, g3_acc >= 0.90]
    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E-PORT DONE", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["veredictos"], indent=1), flush=True)


if __name__ == "__main__":
    main()
