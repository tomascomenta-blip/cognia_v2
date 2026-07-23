# -*- coding: utf-8 -*-
"""LoRA de tooling para MiniCPM5-1B en el formato REAL de Cognia (ACCION: ...).

F3 del goal assets IA (PLAN_ASSETS_IA.md, subsistema B): la flota = 1 base
MiniCPM5-1B (Apache-2.0) + N LoRAs por rol. Este entrena el rol "tooling": dado el
prompt del agente (TOOLS_DOC + contexto) emitir `ACCION: <tool> <args>`.

REUSA el dataset SFT VERIFICADO del repo (data/tooluse_train_v3.jsonl, generado por
gen_trajectories.py corriendo el loop real contra tools reales) — NO se inventa
formato: el agente parsea ACCION con regex, no JSON/XML. El prompt del dataset es
crudo (sin templar), así se re-templa a la plantilla de MiniCPM.

Diseño de memoria (aprendido midiendo): bf16 + peft LoRA, SIN QLoRA (el 1B cabe en
16GB). El vocab de MiniCPM es enorme (~130K) -> los logits [bs, seqlen, vocab] son el
sumidero; con bs=4 desbordaba a shared memory (thrashing, ~55s/paso). bs=2 +
gradient_checkpointing -> VRAM ~7GB, 0.67s/paso.

Held-out por task_id (tareas NO vistas) + gate PRE-REGISTRADO: LoRA > base en
tool-match. Resultado medido (2026-07-22): base 0% -> LoRA 97% tool-match / 77% exact.

Uso (venv312gpu):
  python -m cognia_v3.training.tooluse.train_minicpm_lora train
  python -m cognia_v3.training.tooluse.train_minicpm_lora eval
"""
import os
import sys
import json
import random
import re

MODELO = os.environ.get("COGNIA_MINICPM_MODEL", "openbmb/MiniCPM5-1B")
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(_HERE, "data", "tooluse_train_v3.jsonl")
ADAPTER_DIR = os.environ.get(
    "COGNIA_MINICPM_TOOLING_ADAPTER",
    os.path.expanduser("~/.cognia/loras/minicpm_tooling"))
IM_END = 130073        # <|im_end|> de MiniCPM5 (fin de turno del assistant)
SEED = 20260722
HOLDOUT_FRAC = 0.15

_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", re.IGNORECASE | re.DOTALL)


def _system():
    from shattering.model_constants import COGNIA_SYSTEM_PROMPT
    return COGNIA_SYSTEM_PROMPT


def cargar_split():
    """Separa train/held-out POR task_id (tareas de eval no vistas en train), con
    anti-fuga de prompts byte-identicos. Devuelve (train, held) de {prompt, completion, tool}."""
    rows = [json.loads(l) for l in open(DATA, encoding="utf-8")]
    ids = sorted({r["task_id"] for r in rows})
    rnd = random.Random(SEED)
    rnd.shuffle(ids)
    hold_ids = set(ids[:max(1, int(len(ids) * HOLDOUT_FRAC))])
    train = [r for r in rows if r["task_id"] not in hold_ids]
    held = [r for r in rows if r["task_id"] in hold_ids]
    tp = {r["prompt"] for r in train}
    held = [r for r in held if r["prompt"] not in tp]
    return train, held


def _tok():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(MODELO, trust_remote_code=True)


def _ids(tok, system, prompt, completion):
    """prompt (system+user, con loss enmascarada) + completion (ACCION + im_end)."""
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": prompt}]
    enc = tok.apply_chat_template(
        msgs, tokenize=True, add_generation_prompt=True, enable_thinking=False,
        return_dict=True)
    prompt_ids = list(enc["input_ids"])
    comp_ids = tok(completion, add_special_tokens=False)["input_ids"] + [IM_END]
    return prompt_ids + comp_ids, [-100] * len(prompt_ids) + comp_ids


def entrenar(epochs=3, bs=2, lr=2e-4, r=16):
    import time
    import torch
    from transformers import AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model
    random.seed(SEED)
    torch.manual_seed(SEED)
    tok = _tok()
    system = _system()
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    train, held = cargar_split()
    print(f"train={len(train)} pares | held-out={len(held)} pares (tareas no vistas)")
    ejs = [_ids(tok, system, r["prompt"], r["completion"]) for r in train]
    lens = [len(e[0]) for e in ejs]
    print(f"long. secuencia: min={min(lens)} med={sum(lens)//len(lens)} max={max(lens)}")

    model = AutoModelForCausalLM.from_pretrained(
        MODELO, trust_remote_code=True, dtype=torch.bfloat16).to("cuda")
    model.config.use_cache = False
    cfg = LoraConfig(r=r, lora_alpha=2 * r, lora_dropout=0.05, bias="none",
                     task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                     "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    model.train()
    for ep in range(epochs):
        random.shuffle(ejs)
        tot, n, t0 = 0.0, 0, time.time()
        for i in range(0, len(ejs), bs):
            chunk = ejs[i:i + bs]
            maxlen = max(len(x[0]) for x in chunk)
            ii, ll, am = [], [], []
            for input_ids, labels in chunk:
                pad = maxlen - len(input_ids)
                ii.append(input_ids + [pad_id] * pad)
                ll.append(labels + [-100] * pad)
                am.append([1] * len(input_ids) + [0] * pad)
            ii = torch.tensor(ii).to("cuda")
            ll = torch.tensor(ll).to("cuda")
            am = torch.tensor(am).to("cuda")
            out = model(input_ids=ii, attention_mask=am, labels=ll)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step()
            opt.zero_grad()
            tot += float(out.loss)
            n += 1
            if n % 50 == 0:
                print(f"  ep{ep+1} paso {n}/{(len(ejs)+bs-1)//bs}  loss={tot/n:.4f}  "
                      f"VRAM={torch.cuda.max_memory_allocated()/1e9:.1f}GB  "
                      f"{(time.time()-t0)/n:.2f}s/paso", flush=True)
        print(f"epoch {ep+1}/{epochs}  loss={tot/max(1,n):.4f}  "
              f"{time.time()-t0:.0f}s", flush=True)
    os.makedirs(ADAPTER_DIR, exist_ok=True)
    model.save_pretrained(ADAPTER_DIR)
    print("adapter ->", ADAPTER_DIR)


def _predecir(model, tok, system, prompt):
    import torch
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": prompt}]
    inp = tok.apply_chat_template(
        msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt",
        return_dict=True, enable_thinking=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=200, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0, inp["input_ids"].shape[1]:],
                      skip_special_tokens=True).strip()


def _tool_de(texto):
    m = _ACCION_RE.search(texto)
    return m.group(1).lower().strip() if m else None


def evaluar():
    import torch
    from transformers import AutoModelForCausalLM
    from peft import PeftModel
    tok = _tok()
    system = _system()
    _, held = cargar_split()
    vistos, casos = set(), []
    for r in held:
        if r["prompt"] not in vistos:
            vistos.add(r["prompt"])
            casos.append(r)
    print(f"held-out (prompts unicos): {len(casos)}")
    base = AutoModelForCausalLM.from_pretrained(
        MODELO, trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()

    def medir(model, etq):
        tool_ok = exact_ok = 0
        for r in casos:
            pred = _predecir(model, tok, system, r["prompt"])
            tool_ok += _tool_de(pred) == r["tool"]
            exact_ok += pred.strip() == r["completion"].strip()
        print(f"[{etq}] tool-match {tool_ok}/{len(casos)} ({100*tool_ok/len(casos):.0f}%) "
              f"| exact {exact_ok}/{len(casos)} ({100*exact_ok/len(casos):.0f}%)")
        return tool_ok / len(casos)

    ab = medir(base, "BASE")
    lora = PeftModel.from_pretrained(base, ADAPTER_DIR).eval()
    al = medir(lora, "LoRA")
    print(f"\nGATE (pre-registrado: LoRA > BASE en tool-match): "
          f"base={ab:.2f} lora={al:.2f} -> {'PASA' if al > ab else 'NO PASA'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    {"train": entrenar, "eval": evaluar}.get(cmd, entrenar)()
