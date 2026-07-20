# -*- coding: utf-8 -*-
"""
E2-FINAL - CORRIDA COLAPSADA (mezcla unica; decision E-MIX-B 2026-07-08).
Produce el CHECKPOINT CANDIDATO cognia-3b v1. Receta = brazo B de E-MIX +
2 fixes de G3: D1 x3 (antes 12% del corpus -> G3 70%) y 2 EPOCHS.
PRE-REGISTRO: P-FINAL-1 G3>=18/20; P-FINAL-2 G1>=85%; P-FINAL-3 G5>=60%;
P-FINAL-4 G2A>=95%. Pasa todo -> APTO_PARA_E5 (formato deploy via G4:
adapter-vivo vs merged Q5/Q6, hallazgo re-quant). Guarda replay.jsonl
reutilizable. ~7 GPU-h. [Derivado de emix_kernel.py, un solo brazo]

Kernel Kaggle (script, 1x T4, internet ON). Mismo metodo columna (E1/E2A:
unsloth + LoRA r16 a32 all-linear NF4, packing + completion-masking, mb4,
lr 1e-4 cosine, seed 20260707), mismo corpus total, 1 epoch por brazo:

  FASE 0  replay on-policy: el base NF4 genera respuestas greedy a 800
          prompts es (sample seed de d5_espanol); juez heuristico
          (es_espanol + 20..1200 chars + sin degeneracion) -> pares replay
          que van a AMBOS brazos por igual.
  BRAZO B (mezcla unica, estilo Tulu 3): train sobre TODO junto
          (e1_train + d5_espanol + replay + tooluse_v3, shuffle seed).
  BRAZO A (secuencial-con-merge, DC-4):
          etapa-1 = e1_train + d5_espanol + replay -> adapter
          merge DC-9: base NF4 (misma BitsAndBytesConfig) -> dequant fp16
          -> merge_and_unload -> merged fp16 en disco   [ensayo real de E5]
          etapa-2 = tooluse_v3 + 10% replay de etapa-1, entrenado SOBRE el
          merged (recuantizado NF4 al cargar).
  EVAL    instrumento E1b (system neutro pareado) sobre base / B / A-final:
          G1(100) G3(20) G5(25) + G2A(147, oraculo accion_pass primera
          ACCION + args_regex). Suites verificadas por sha256.

SEQ=2048 (los pares ACCION con TOOLS_DOC no entran en 1024, s4.6 E-SEQ);
si OOM -> mb2 (retry una vez, registrado).

PREDICCIONES PRE-REGISTRADAS (congeladas antes de correr):
  P-EMIX-1: A > B en el promedio (G1+G2A+G3)/3 por >1pp (la hipotesis DC-4:
            el rollback por etapa vale mas que el ahorro de una corrida).
            REGLA DE DECISION s7.3 (vinculante): si B >= A - 1pp o gana ->
            E2/E3/E4 COLAPSAN en una sola corrida de mezcla completa.
  P-EMIX-2: el replay es recupera G5 >= 60% en ambos brazos (E1: 56%).
  P-EMIX-3: el brazo final (A y B) mejora G2A vs base en >= +10pp con
            McNemar p<0.05 (N=147; primera medicion del gate ACCION real).
  P-EMIX-4: el merge dequant->fp16 no degrada identidad: G3 de A-final
            >= 18/20 (sanity del procedimiento DC-9 que E5 reusa).
  ABORTO s7.3: si NINGUNA rama pasa G1 (delta < -4pp) -> problema de
            datos/lr, no de topologia; se registra y NO se decide DC-4.

Presupuesto: ~6 GPU-h. Salida: /kaggle/working/emix_results.json (incremental)
+ adapters/ + merged fp16 de etapa-1 (NO se sube al output: se borra tras
etapa-2 para no exceder los 20 GB).
"""
import gc
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

T0 = time.time()
BUDGET_S = int(8.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e2final_results.json")
SEED = 20260707
LR = 1e-4
SEQ = 2048
N_REPLAY = 800
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E2-FINAL-mezcla-unica",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-FINAL-1": "G3 >= 18/20 (D1 x3 + 2 epochs)",
               "P-FINAL-2": "G1 >= 85%",
               "P-FINAL-3": "G5 >= 60%",
               "P-FINAL-4": "G2A >= 95%",
               "regla": "pasa todo -> APTO_PARA_E5"},
           "env": {}, "suites_hash_ok": None, "replay": {}, "train": {},
           "evals": {}, "veredictos": {}, "checkpoint_candidato": None}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    print(f"[sh] {' '.join(cmd[:5])}... rc={r.returncode} ({tail[-1] if tail else ''})", flush=True)
    return r


def _find(patron):
    hits = glob.glob(f"/kaggle/input/**/{patron}", recursive=True)
    if not hits:
        raise FileNotFoundError(patron)
    hits.sort(key=len)
    return hits[0]


def _find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)
             if "adapter" not in p.lower()]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    return pool[0]


# ---------------------------------------------------------------- oraculos
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


_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)", re.IGNORECASE)


def accion_pass(respuesta, oracle):
    m = _ACCION_RE.search(respuesta)
    if not m:
        return False
    tool = m.group(1)
    if tool not in (oracle.get("accion_tools") or []):
        return False
    rx = oracle.get("args_regex")
    if rx:
        m2 = _ACCION_RE.search(respuesta, m.end())
        bloque = respuesta[m.end():m2.start()] if m2 else respuesta[m.end():]
        if not re.search(rx, bloque, re.IGNORECASE):
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
    with open(_find("SUITES_FROZEN.json"), encoding="utf-8") as f:
        frozen = json.load(f)["suites"]
    ok = True
    for nombre, meta in frozen.items():
        if nombre == "g2_razonamiento.jsonl":
            continue  # G2R es gate de E4, no se usa aca
        try:
            path = _find(nombre)
        except FileNotFoundError:
            ok = False
            print(f"SUITE FALTANTE: {nombre}", flush=True)
            continue
        if hashlib.sha256(open(path, "rb").read()).hexdigest() != meta["sha256"]:
            print(f"SUITE ALTERADA: {nombre}", flush=True)
            ok = False
    return ok


# ---------------------------------------------------------------- datos
def carga_jsonl(patron):
    path = _find(patron)
    filas = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                filas.append({"prompt": r["prompt"], "completion": r["completion"]})
    return filas


def tokeniza_pares(pares, tokenizer):
    ejemplos = []
    for r in pares:
        pre = f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n"
        full = pre + f"{r['completion']}<|im_end|>"
        ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
        ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
        ejemplos.append({"ids": ids_full, "prompt_len": len(ids_pre)})
    return ejemplos


def lotes_packed(ejemplos, seq, mb, seed=SEED):
    rng = random.Random(seed)
    ejemplos = list(ejemplos)
    rng.shuffle(ejemplos)
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


# ------------------------------------------------- train unsloth (subproceso)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; LR = 1e-4; SEQ = 2048
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from emix_shared import lotes_packed_json

cfg = json.load(open(sys.argv[1]))
model_dir = cfg["model_dir"]; mb = cfg["mb"]
torch.manual_seed(SEED); random.seed(SEED)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_dir, max_seq_length=SEQ, load_in_4bit=True, dtype=None)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=SEED)
ejemplos = []
with open(cfg["pares_tok"], encoding="utf-8") as f:
    for line in f:
        if line.strip():
            ejemplos.append(json.loads(line))
lotes = lotes_packed_json(ejemplos, SEQ, mb, SEED)
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR)
from torch.optim.lr_scheduler import CosineAnnealingLR
sched = CosineAnnealingLR(opt, T_max=2 * len(lotes))
model.train()
losses = []; t0 = time.time(); tok = 0
for ids, att, lab in lotes * 2:   # 2 EPOCHS (fix G3, pre-registro)
    x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
    y = torch.tensor(lab, device="cuda")
    loss = model(input_ids=x, attention_mask=a, labels=y).loss
    loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
    losses.append(loss.item()); tok += int(a.sum().item())
    if len(losses) % 100 == 0:
        print("step", len(losses), "/", len(lotes), "loss", round(losses[-1], 4), flush=True)
dt = time.time() - t0
model.save_pretrained(cfg["adapter_out"]); tokenizer.save_pretrained(cfg["adapter_out"])
reg = {"steps": len(losses), "tok_s_util": round(tok/dt, 1), "wall_s": round(dt, 1),
       "loss_ini": round(sum(losses[:5])/max(1,len(losses[:5])), 4),
       "loss_fin": round(sum(losses[-5:])/max(1,len(losses[-5:])), 4),
       "nan": any(math.isnan(l) for l in losses)}
with open(cfg["stats_out"], "w") as f:
    json.dump(reg, f)
print("TRAIN_DONE", json.dumps(reg), flush=True)
'''

EMIX_SHARED = r'''
import random
def lotes_packed_json(ejemplos, seq, mb, seed):
    rng = random.Random(seed)
    ejemplos = list(ejemplos); rng.shuffle(ejemplos)
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


def entrena_subproceso(nombre, model_dir, pares_tok_path, mb=4):
    """Lanza el train unsloth en subproceso; si OOM, retry con mb=2."""
    cfg = {"model_dir": model_dir, "pares_tok": pares_tok_path, "mb": mb,
           "adapter_out": f"{OUT}/adapters/{nombre}",
           "stats_out": f"{OUT}/train_{nombre}.json"}
    cfg_path = f"{OUT}/cfg_{nombre}.json"
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    probe = os.path.join(OUT, "unsloth_train_emix.py")
    with open(probe, "w") as f:
        f.write(UNSLOTH_TRAIN)
    r = subprocess.run([sys.executable, probe, cfg_path], capture_output=True,
                       text=True, timeout=4 * 3600)
    print((r.stdout or "")[-1500:], flush=True)
    if os.path.exists(cfg["stats_out"]):
        return json.load(open(cfg["stats_out"]))
    err = (r.stderr or "")[-600:]
    if "out of memory" in err.lower() and mb > 2:
        print(f"[{nombre}] OOM con mb={mb} -> retry mb=2", flush=True)
        return entrena_subproceso(nombre, model_dir, pares_tok_path, mb=2)
    return {"error": err}


# ---------------------------------------------------------------- merge DC-9
def merge_etapa1(model_dir, adapter_dir, merged_out):
    """base NF4 (misma BitsAndBytesConfig del training) -> dequant fp16 ->
    merge_and_unload -> save fp16. Es el MISMO procedimiento que E5 (DC-9)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    # dequant NF4 -> fp16 (patron Kaitchup/ChrisHayduk, peft #2321)
    import bitsandbytes as bnb_mod
    import torch.nn as nn
    for name, module in model.named_modules():
        if isinstance(module, bnb_mod.nn.Linear4bit):
            w = bnb_mod.functional.dequantize_4bit(
                module.weight.data, module.weight.quant_state).to(torch.float16)
            nuevo = nn.Linear(module.in_features, module.out_features,
                              bias=module.bias is not None, dtype=torch.float16)
            nuevo.weight = nn.Parameter(w, requires_grad=False)
            if module.bias is not None:
                nuevo.bias = nn.Parameter(module.bias.data.to(torch.float16),
                                          requires_grad=False)
            padre = model
            partes = name.split(".")
            for p in partes[:-1]:
                padre = getattr(padre, p)
            setattr(padre, partes[-1], nuevo)
    if hasattr(model.config, "quantization_config"):
        try:
            delattr(model.config, "quantization_config")
        except AttributeError:
            model.config.quantization_config = None
    pm = PeftModel.from_pretrained(model, adapter_dir)
    merged = pm.merge_and_unload()
    merged.save_pretrained(merged_out, safe_serialization=True)
    AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True).save_pretrained(merged_out)
    del model, pm, merged
    gc.collect()
    import torch as _t
    _t.cuda.empty_cache()


# ---------------------------------------------------------------- eval
def genera_batch(model, tokenizer, items, max_new):
    import torch
    tokenizer.padding_side = "left"
    textos = []
    for prompt, idioma in items:
        sistema = SYSTEM_ES if idioma == "es" else SYSTEM_EN
        textos.append(tokenizer.apply_chat_template(
            [{"role": "system", "content": sistema},
             {"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True))
    enc = tokenizer(textos, return_tensors="pt", padding=True,
                    add_special_tokens=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True) for i in range(len(items))]


def eval_todo(model, tokenizer, suites, etiqueta):
    res = {"items": {}}
    for nombre, items in suites.items():
        binarios = {}
        bs = 4 if nombre == "g2a" else 8   # prompts G2A largos (TOOLS_DOC)
        for i in range(0, len(items), bs):
            chunk = items[i:i + bs]
            outs = genera_batch(model, tokenizer,
                                [(it["prompt"], it["idioma"]) for it in chunk],
                                max(it["max_new_tokens"] for it in chunk))
            for it, o in zip(chunk, outs):
                if it["gate"] == "G2A":
                    ok = accion_pass(o, it["oracle"])
                else:
                    ok = oracle_pass(o, it["oracle"])
                    if it["gate"] == "G5":
                        ok = ok and es_espanol(o)
                binarios[it["id"]] = bool(ok)
        res["items"][nombre] = binarios
        print(f"  [{etiqueta}] {nombre}: {sum(binarios.values())/len(binarios):.1%}", flush=True)
        dump()
    return res


def compara(base_items, brazo_items):
    out = {}
    for suite, b in base_items.items():
        a = brazo_items[suite]
        n01 = sum(1 for k in b if not b[k] and a[k])
        n10 = sum(1 for k in b if b[k] and not a[k])
        out[suite] = {"acc_base": round(sum(b.values()) / len(b), 3),
                      "acc_brazo": round(sum(a.values()) / len(a), 3),
                      "delta_pp": round((sum(a.values()) - sum(b.values())) / len(b) * 100, 1),
                      "n01": n01, "n10": n10, "p": round(mcnemar_p(n01, n10), 4)}
    return out


def main():
    sh([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"])
    sh([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"])
    sh([sys.executable, "-m", "pip", "install", "unsloth"])
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import transformers
    import peft as peft_mod

    RESULTS["env"] = {"gpu": torch.cuda.get_device_name(0),
                      "torch": torch.__version__,
                      "transformers": transformers.__version__,
                      "peft": peft_mod.__version__}
    RESULTS["suites_hash_ok"] = verifica_suites()
    print("SUITES HASH OK:", RESULTS["suites_hash_ok"], flush=True)
    dump()
    if not RESULTS["suites_hash_ok"]:
        print("ABORT: suites alteradas", flush=True)
        return

    with open(os.path.join(OUT, "emix_shared.py"), "w") as f:
        f.write(EMIX_SHARED)

    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    d1 = carga_jsonl("e1_train.jsonl")
    d5 = carga_jsonl("d5_espanol.jsonl")
    accion = carga_jsonl("tooluse_train_v3.jsonl")
    print(f"datos: d1={len(d1)} d5={len(d5)} accion={len(accion)}", flush=True)

    # ── FASE 0: replay on-policy con el base NF4 ──
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    base.eval()

    rng = random.Random(SEED)
    prompts_replay = [r["prompt"] for r in rng.sample(d5, min(N_REPLAY, len(d5)))]
    replay, rechazados = [], 0
    t0 = time.time()
    for i in range(0, len(prompts_replay), 8):
        chunk = prompts_replay[i:i + 8]
        outs = genera_batch(base, tokenizer, [(p, "es") for p in chunk], 300)
        for p, o in zip(chunk, outs):
            o = o.strip()
            palabras = o.split()
            degenerado = (len(palabras) >= 12 and
                          len(set(palabras[-12:])) <= 3)
            if 20 <= len(o) <= 1200 and es_espanol(o) and not degenerado:
                replay.append({"prompt": p, "completion": o})
            else:
                rechazados += 1
        if i % 200 == 0:
            print(f"  replay {i}/{len(prompts_replay)}", flush=True)
    RESULTS["replay"] = {"generados": len(prompts_replay), "aceptados": len(replay),
                         "rechazados": rechazados,
                         "wall_min": round((time.time() - t0) / 60, 1)}
    print("REPLAY:", json.dumps(RESULTS["replay"]), flush=True)
    dump()

    # ── eval del base (todas las suites, sirve de baseline pareado) ──
    suites = {}
    for nombre, clave in (("g1_general.jsonl", "g1"), ("g3_identidad.jsonl", "g3"),
                          ("g5_espanol.jsonl", "g5"), ("g2_accion.jsonl", "g2a")):
        with open(_find(nombre), encoding="utf-8") as f:
            suites[clave] = [json.loads(l) for l in f if l.strip()]
    print("== eval base ==", flush=True)
    base_ev = eval_todo(base, tokenizer, suites, "base")
    RESULTS["evals"]["base"] = base_ev
    dump()
    del base
    gc.collect()
    torch.cuda.empty_cache()

    # replay reutilizable
    with open(os.path.join(OUT, "replay.jsonl"), "w", encoding="utf-8") as f:
        for r in replay:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # corpus FINAL: mezcla unica con D1 x3
    d1_puro = [r for r in d1 if "ACCION:" not in r["prompt"] and "ACCION:" not in r["completion"]]
    mezcla = d1 + d1_puro + d1_puro + d5 + replay + accion
    RESULTS["train"]["corpus"] = {"total": len(mezcla), "d1_extra": 2 * len(d1_puro),
                                  "replay": len(replay)}
    dump()

    def escribe_tok(pares, path):
        ej = tokeniza_pares(pares, tokenizer)
        with open(path, "w", encoding="utf-8") as f:
            for e in ej:
                f.write(json.dumps(e) + "\n")
        return len(ej)

    escribe_tok(mezcla, f"{OUT}/tok_final.jsonl")
    print("== TRAIN FINAL (mezcla unica, 2 epochs) ==", flush=True)
    RESULTS["train"]["final"] = entrena_subproceso("cognia3b_v1", model_dir,
                                                   f"{OUT}/tok_final.jsonl")
    dump()

    from peft import PeftModel
    model_f = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    pm_f = PeftModel.from_pretrained(model_f, f"{OUT}/adapters/cognia3b_v1")
    pm_f.eval()
    print("== eval checkpoint candidato ==", flush=True)
    ev_f = eval_todo(pm_f, tokenizer, suites, "cognia3b_v1")
    RESULTS["evals"]["cognia3b_v1"] = ev_f
    RESULTS["veredictos"]["cognia3b_v1"] = compara(base_ev["items"], ev_f["items"])
    dump()
    del model_f, pm_f
    gc.collect()
    torch.cuda.empty_cache()

    try:
        v = RESULTS["veredictos"]["cognia3b_v1"]
        checks = {"P-FINAL-1_g3": [v["g3"]["acc_brazo"], v["g3"]["acc_brazo"] >= 0.90],
                  "P-FINAL-2_g1": [v["g1"]["acc_brazo"], v["g1"]["acc_brazo"] >= 0.85],
                  "P-FINAL-3_g5": [v["g5"]["acc_brazo"], v["g5"]["acc_brazo"] >= 0.60],
                  "P-FINAL-4_g2a": [v["g2a"]["acc_brazo"], v["g2a"]["acc_brazo"] >= 0.95]}
        checks["APTO_PARA_E5"] = all(x[1] for x in checks.values())
        RESULTS["checkpoint_candidato"] = checks
    except Exception as e:
        RESULTS["checkpoint_candidato"] = {"error": str(e)[:300]}

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E2-FINAL DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["checkpoint_candidato"]), flush=True)


if __name__ == "__main__":
    main()
