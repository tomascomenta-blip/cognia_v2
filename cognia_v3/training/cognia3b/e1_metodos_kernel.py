# -*- coding: utf-8 -*-
# (UTF-8: el runner setea PYTHONUTF8=1 para el CLI de Kaggle, que es el fix
#  real de la leccion cp1252 de run_kaggle_xspeed.py)
"""
E1 - ABLACION DE METODO (COGNIA 3B, TEORIA Parte 7 s7.2 + decision E0).

Kernel de Kaggle (script, 1x T4, internet ON). Entrena 5 brazos de METODO
sobre el MISMO dataset (e1_train.jsonl: D1 identidad + tool-use ACCION),
misma seed, mismos epochs, y los evalua TODOS sobre la misma base NF4 con
las suites CONGELADAS (hash verificado contra SUITES_FROZEN.json).

Brazos (pre-registrados):
  u_r8_qkvo   unsloth, LoRA r=8  a=16, q/k/v/o          (control historico)
  u_r16_all   unsloth, LoRA r=16 a=32, all-linear        (candidata)
  u_r16_neft  unsloth, r=16 all-linear + NEFTune alfa=5  (ruido en embeddings)
  t_r16_all   transformers+PEFT, r=16 all-linear         (loss-equivalence vs u_r16_all)
  t_dora_r16  transformers+PEFT, DoRA r=16 all-linear    (unsloth no soporta DoRA)

Runtime de referencia (decision E0, ANALISIS_E0.md): packing + completion-
masking + GC ON + paged/8-bit; unsloth mb8, transformers mb4 (mb8 OOM logits).

Eval in-kernel (base + 5 brazos, MISMO runtime de eval para justicia):
  G1 (100, no-regresion) / G3 (20, identidad) / G5 (25, espanol) +
  tooluse_eval (10, direccional). Greedy. McNemar exacto base-vs-brazo.
Gate de decision (pre-registrado): entre los brazos que PASAN G1+G3+G5,
gana el de mayor correct_tool; empate -> mayor tok/s de training.

Predicciones a falsar (TEORIA s7.2):
  P-E1a: u_r16_all > u_r8_qkvo en tool-use held-out (senal direccional N=10).
  P-E1b: DoRA cuesta >=15% tok/s y no supera a u_r16_all en estos gates.
  P-E1c: NEFTune ayuda <=2pp (indistinguible a este N).
  P-E1d: loss final t_r16_all vs u_r16_all dentro de +-1% (equivalencia).

Salida: /kaggle/working/e1_results.json (incremental) + adapters/<brazo>/.
"""
import gc
import glob
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

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

T0 = time.time()
BUDGET_S = int(5.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e1_results.json")
SEED = 20260707
EPOCHS = 2
LR = 1e-4
SEQ = 1024

RESULTS = {"exp": "E1-metodos", "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "env": {}, "suites_hash_ok": None, "train": {}, "evals": {}, "veredictos": {}}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    print(f"[sh] {' '.join(cmd[:5])}... rc={r.returncode} ({tail[-1] if tail else ''})", flush=True)
    return r


def prepara_entorno():
    sh([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"])
    sh([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"])
    sh([sys.executable, "-m", "pip", "install", "unsloth"])


def _find(patron):
    hits = glob.glob(f"/kaggle/input/**/{patron}", recursive=True)
    if not hits:
        raise FileNotFoundError(patron)
    hits.sort(key=len)
    return hits[0]


def _find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    return pool[0]


# ---------------------------------------------------------------- oraculo
# (copia minima de cognia_v3/eval/suites/suite_oracle.py — el kernel es
# autocontenido; la integridad de las SUITES se verifica por sha256)
def fold(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def ultimo_numero(t):
    hits = _NUM_RE.findall(t.replace("−", "-"))
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


_ES_STOP = {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "es",
            "por", "con", "para", "del", "se", "no", "su", "al", "como", "mas",
            "pero", "este", "esta", "son", "hay", "muy"}
_EN_STOP = {"the", "of", "and", "to", "in", "is", "that", "it", "for", "on",
            "with", "as", "are", "this", "was", "be", "by", "an", "not", "or"}


def es_espanol(respuesta):
    palabras = re.findall(r"[a-záéíóúñü]+", respuesta.lower())
    if not palabras:
        return False
    es = sum(1 for p in palabras if fold(p) in _ES_STOP)
    en = sum(1 for p in palabras if p in _EN_STOP)
    return es > en


def mcnemar_p(n01, n10):
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


def verifica_suites():
    frozen_path = _find("SUITES_FROZEN.json")
    with open(frozen_path, encoding="utf-8") as f:
        frozen = json.load(f)["suites"]
    ok = True
    for nombre, meta in frozen.items():
        try:
            path = _find(nombre)
        except FileNotFoundError:
            if nombre == "g2_razonamiento.jsonl":
                continue  # G2R no se usa en E1 (gate de E4)
            ok = False
            continue
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if h != meta["sha256"]:
            print(f"SUITE ALTERADA: {nombre} {h[:12]} != {meta['sha256'][:12]}", flush=True)
            ok = False
    return ok


# ---------------------------------------------------------------- datos
def carga_train(tokenizer):
    path = _find("e1_train.jsonl")
    ejemplos = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            pre = f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n"
            full = pre + f"{r['completion']}<|im_end|>"
            ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
            ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
            ejemplos.append({"ids": ids_full, "prompt_len": len(ids_pre)})
    rng = random.Random(SEED)
    rng.shuffle(ejemplos)
    return ejemplos


def lotes_packed(ejemplos, seq, mb):
    """Packing greedy con completion-masking (runtime ganador de E0)."""
    filas, fila, lab, restante = [], [], [], seq
    for e in ejemplos:
        x = e["ids"][:seq]
        if len(x) > restante:
            if fila:
                filas.append((fila, lab))
            fila, lab, restante = [], [], seq
        y = list(x)
        pl = min(e["prompt_len"], len(x))
        y[:pl] = [-100] * pl
        fila += x
        lab += y
        restante -= len(x)
    if fila:
        filas.append((fila, lab))
    lotes = []
    for i in range(0, len(filas), mb):
        chunk = filas[i:i + mb]
        if len(chunk) < mb:
            break
        ids = [f + [0] * (seq - len(f)) for f, _ in chunk]
        att = [[1] * len(f) + [0] * (seq - len(f)) for f, _ in chunk]
        labs = [l + [-100] * (seq - len(l)) for _, l in chunk]
        lotes.append((ids, att, labs))
    return lotes


# ---------------------------------------------------------------- unsloth (subproceso)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; EPOCHS = 2; LR = 1e-4; SEQ = 1024; MB = 8
BRAZOS = [
    {"nombre": "u_r8_qkvo",  "r": 8,  "targets": ["q_proj","k_proj","v_proj","o_proj"], "neft": 0.0},
    {"nombre": "u_r16_all",  "r": 16, "targets": ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], "neft": 0.0},
    {"nombre": "u_r16_neft", "r": 16, "targets": ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], "neft": 5.0},
]
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from e1_shared import find_model_dir, carga_train_json, lotes_packed_json

model_dir = find_model_dir()
out = {}
for brazo in BRAZOS:
    torch.manual_seed(SEED); random.seed(SEED)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_dir, max_seq_length=SEQ, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=brazo["r"], lora_alpha=2*brazo["r"], lora_dropout=0.05,
        target_modules=brazo["targets"], use_gradient_checkpointing="unsloth",
        random_state=SEED)
    ejemplos = carga_train_json(tokenizer)
    lotes = lotes_packed_json(ejemplos, SEQ, MB)
    hook = None
    if brazo["neft"] > 0:
        emb = model.get_input_embeddings()
        alpha = brazo["neft"]
        def neft_hook(mod, inp, salida):
            if mod.training:
                dims = salida.shape[-2] * salida.shape[-1]
                mag = alpha / (dims ** 0.5)
                return salida + torch.empty_like(salida).uniform_(-mag, mag)
            return salida
        hook = emb.register_forward_hook(neft_hook)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR)
    from torch.optim.lr_scheduler import CosineAnnealingLR
    total_steps = len(lotes) * EPOCHS
    sched = CosineAnnealingLR(opt, T_max=total_steps)
    model.train()
    losses = []; t0 = time.time(); tok = 0
    for ep in range(EPOCHS):
        for ids, att, lab in lotes:
            x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
            y = torch.tensor(lab, device="cuda")
            loss = model(input_ids=x, attention_mask=a, labels=y).loss
            loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            losses.append(loss.item()); tok += int(a.sum().item())
    dt = time.time() - t0
    if hook: hook.remove()
    adir = "/kaggle/working/adapters/%s" % brazo["nombre"]
    model.save_pretrained(adir); tokenizer.save_pretrained(adir)
    out[brazo["nombre"]] = {"steps": len(losses), "tok_s_util": round(tok/dt, 1),
        "wall_s": round(dt, 1), "loss_ini": round(sum(losses[:5])/5, 4),
        "loss_fin": round(sum(losses[-5:])/5, 4),
        "nan": any(math.isnan(l) for l in losses)}
    print("BRAZO", brazo["nombre"], json.dumps(out[brazo["nombre"]]), flush=True)
    del model, opt; torch.cuda.empty_cache()
with open("/kaggle/working/unsloth_train.json", "w") as f:
    json.dump(out, f)
print("UNSLOTH_TRAIN_DONE", flush=True)
'''

E1_SHARED = r'''
import glob, json, os, random
SEED = 20260707
def find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len); return pool[0]
def carga_train_json(tokenizer):
    hits = glob.glob("/kaggle/input/**/e1_train.jsonl", recursive=True)
    hits.sort(key=len)
    ejemplos = []
    with open(hits[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            pre = "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n" % r["prompt"]
            full = pre + "%s<|im_end|>" % r["completion"]
            ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
            ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
            ejemplos.append({"ids": ids_full, "prompt_len": len(ids_pre)})
    rng = random.Random(SEED); rng.shuffle(ejemplos)
    return ejemplos
def lotes_packed_json(ejemplos, seq, mb):
    filas, fila, lab, restante = [], [], [], seq
    for e in ejemplos:
        x = e["ids"][:seq]
        if len(x) > restante:
            if fila: filas.append((fila, lab))
            fila, lab, restante = [], [], seq
        y = list(x); pl = min(e["prompt_len"], len(x)); y[:pl] = [-100]*pl
        fila += x; lab += y; restante -= len(x)
    if fila: filas.append((fila, lab))
    lotes = []
    for i in range(0, len(filas), mb):
        chunk = filas[i:i+mb]
        if len(chunk) < mb: break
        ids = [f + [0]*(seq-len(f)) for f, _ in chunk]
        att = [[1]*len(f) + [0]*(seq-len(f)) for f, _ in chunk]
        labs = [l + [-100]*(seq-len(l)) for _, l in chunk]
        lotes.append((ids, att, labs))
    return lotes
'''


# ---------------------------------------------------------------- transformers (main)
def entrena_transformers(brazo, model_dir, tokenizer, ejemplos):
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from bitsandbytes.optim import PagedAdamW8bit

    torch.manual_seed(SEED)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    cfg = LoraConfig(r=brazo["r"], lora_alpha=2 * brazo["r"], lora_dropout=0.05,
                     bias="none", task_type="CAUSAL_LM",
                     target_modules=brazo["targets"], use_dora=brazo.get("dora", False))
    model = get_peft_model(model, cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()

    mb = 4  # mb8 OOM en el path transformers (E0: logits fp32)
    lotes = lotes_packed(ejemplos, SEQ, mb)
    opt = PagedAdamW8bit([p for p in model.parameters() if p.requires_grad], lr=LR)
    from torch.optim.lr_scheduler import CosineAnnealingLR
    sched = CosineAnnealingLR(opt, T_max=len(lotes) * EPOCHS)
    scaler = torch.amp.GradScaler("cuda")
    model.train()
    losses, t0, tok = [], time.time(), 0
    for ep in range(EPOCHS):
        for ids, att, lab in lotes:
            x = torch.tensor(ids, device="cuda")
            a = torch.tensor(att, device="cuda")
            y = torch.tensor(lab, device="cuda")
            with torch.autocast("cuda", dtype=torch.float16):
                loss = model(input_ids=x, attention_mask=a, labels=y).loss
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            opt.zero_grad(set_to_none=True)
            losses.append(loss.item())
            tok += int(a.sum().item())
    dt = time.time() - t0
    adir = f"{OUT}/adapters/{brazo['nombre']}"
    model.save_pretrained(adir)
    reg = {"steps": len(losses), "tok_s_util": round(tok / dt, 1),
           "wall_s": round(dt, 1), "loss_ini": round(sum(losses[:5]) / 5, 4),
           "loss_fin": round(sum(losses[-5:]) / 5, 4),
           "nan": any(math.isnan(x) for x in losses)}
    del model, opt
    gc.collect()
    import torch as _t
    _t.cuda.empty_cache()
    return reg


# ---------------------------------------------------------------- eval
def genera_batch(model, tokenizer, prompts, max_new):
    import torch
    tokenizer.padding_side = "left"
    enc = tokenizer([tokenizer.apply_chat_template(
        [{"role": "user", "content": p}], tokenize=False,
        add_generation_prompt=True) for p in prompts],
        return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True) for i in range(len(prompts))]


def eval_suites(model, tokenizer, suites, tooluse, etiqueta):
    res = {"items": {}}
    for nombre, items in suites.items():
        binarios = {}
        for i in range(0, len(items), 8):
            chunk = items[i:i + 8]
            outs = genera_batch(model, tokenizer, [it["prompt"] for it in chunk],
                                max(it["max_new_tokens"] for it in chunk))
            for it, o in zip(chunk, outs):
                ok = oracle_pass(o, it["oracle"])
                if it["gate"] == "G5":
                    ok = ok and es_espanol(o)
                binarios[it["id"]] = bool(ok)
        res["items"][nombre] = binarios
        acc = sum(binarios.values()) / len(binarios)
        print(f"  [{etiqueta}] {nombre}: {acc:.1%}", flush=True)
    # tool-use direccional (N=10): primera linea ACCION con tool esperada
    tu = {}
    for i in range(0, len(tooluse), 5):
        chunk = tooluse[i:i + 5]
        outs = genera_batch(model, tokenizer, [t["prompt"] for t in chunk], 200)
        for t, o in zip(chunk, outs):
            m = re.search(r"ACCION:\s*(\w+)", o)
            tu[t["id"]] = bool(m and m.group(1) in t["expected_tools"])
    res["items"]["tooluse"] = tu
    print(f"  [{etiqueta}] tooluse: {sum(tu.values())}/{len(tu)}", flush=True)
    return res


def compara(base_items, brazo_items):
    out = {}
    for suite, b in base_items.items():
        a = brazo_items[suite]
        n01 = sum(1 for k in b if not b[k] and a[k])   # base falla, brazo acierta
        n10 = sum(1 for k in b if b[k] and not a[k])
        acc_b = sum(b.values()) / len(b)
        acc_a = sum(a.values()) / len(a)
        out[suite] = {"acc_base": round(acc_b, 3), "acc_brazo": round(acc_a, 3),
                      "delta_pp": round((acc_a - acc_b) * 100, 1),
                      "n01": n01, "n10": n10, "p": round(mcnemar_p(n01, n10), 4)}
    return out


def main():
    prepara_entorno()
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import transformers
    import peft

    RESULTS["env"] = {"gpu": torch.cuda.get_device_name(0),
                      "torch": torch.__version__,
                      "transformers": transformers.__version__,
                      "peft": peft.__version__}
    RESULTS["suites_hash_ok"] = verifica_suites()
    print("SUITES HASH OK:", RESULTS["suites_hash_ok"], flush=True)
    dump()
    if not RESULTS["suites_hash_ok"]:
        print("ABORT: suites alteradas", flush=True)
        return

    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    ejemplos = carga_train(tokenizer)
    print(f"train: {len(ejemplos)} pares", flush=True)

    # compartido para el subproceso unsloth
    with open(os.path.join(OUT, "e1_shared.py"), "w") as f:
        f.write(E1_SHARED)

    # 1) brazos unsloth en subproceso (aisla los parches de unsloth)
    probe = os.path.join(OUT, "unsloth_train_arms.py")
    with open(probe, "w") as f:
        f.write(UNSLOTH_TRAIN)
    r = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                       timeout=3 * 3600)
    print((r.stdout or "")[-3000:], flush=True)
    ustats = os.path.join(OUT, "unsloth_train.json")
    if os.path.exists(ustats):
        RESULTS["train"].update(json.load(open(ustats)))
    else:
        RESULTS["train"]["unsloth_error"] = (r.stderr or "")[-800:]
    dump()

    # 2) brazos transformers en el proceso principal
    for brazo in [
        {"nombre": "t_r16_all", "r": 16, "targets": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]},
        {"nombre": "t_dora_r16", "r": 16, "dora": True, "targets": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]},
    ]:
        if time.time() - T0 > BUDGET_S * 0.55:
            RESULTS["train"][brazo["nombre"]] = {"skip": "budget"}
            continue
        print(f"== entrena {brazo['nombre']} ==", flush=True)
        try:
            RESULTS["train"][brazo["nombre"]] = entrena_transformers(
                brazo, model_dir, tokenizer, ejemplos)
        except Exception as e:
            RESULTS["train"][brazo["nombre"]] = {"error": str(e)[:300]}
        dump()

    # 3) eval uniforme: base NF4 + cada adapter guardado
    suites = {}
    for nombre in ("g1_general.jsonl", "g3_identidad.jsonl", "g5_espanol.jsonl"):
        with open(_find(nombre), encoding="utf-8") as f:
            suites[nombre.split("_")[0]] = [json.loads(l) for l in f if l.strip()]
    tooluse = []
    with open(_find("tooluse_eval.jsonl"), encoding="utf-8") as f:
        for i, l in enumerate(f):
            if l.strip():
                r0 = json.loads(l)
                tooluse.append({"id": f"TU-{i:02d}", "prompt": r0["prompt"],
                                "expected_tools": r0.get("expected_tools", [])})

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    model.eval()

    print("== eval base ==", flush=True)
    base_ev = eval_suites(model, tokenizer, suites, tooluse, "base")
    RESULTS["evals"]["base"] = base_ev
    dump()

    from peft import PeftModel
    adapters = sorted(d for d in glob.glob(f"{OUT}/adapters/*") if os.path.isdir(d))
    peft_model = None
    for adir in adapters:
        nombre = os.path.basename(adir)
        if time.time() - T0 > BUDGET_S:
            RESULTS["evals"][nombre] = {"skip": "budget"}
            continue
        print(f"== eval {nombre} ==", flush=True)
        try:
            if peft_model is None:
                peft_model = PeftModel.from_pretrained(model, adir, adapter_name=nombre)
            else:
                peft_model.load_adapter(adir, adapter_name=nombre)
            peft_model.set_adapter(nombre)
            peft_model.eval()
            ev = eval_suites(peft_model, tokenizer, suites, tooluse, nombre)
            RESULTS["evals"][nombre] = ev
            RESULTS["veredictos"][nombre] = compara(base_ev["items"], ev["items"])
        except Exception as e:
            RESULTS["evals"][nombre] = {"error": str(e)[:300]}
        dump()

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E1 DONE en", RESULTS["wall_total_min"], "min", flush=True)


if __name__ == "__main__":
    main()
