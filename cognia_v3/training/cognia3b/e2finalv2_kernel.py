# -*- coding: utf-8 -*-
"""
E2-FINAL-v2 - segundo intento de CHECKPOINT CANDIDATO (receta E-GROK).
v1 (lr 1e-4, D1 x3, 2 EPOCHS) logro G3 100% y G2A 96.6% pero FALLO G1
(81% < 85%, -8pp p=0.039): los 2 epochs duplican la exposicion y erosionan
capacidad general. Fix v2 = receta E-GROK medida (lr 3e-4 + warmup 10%
logra el grokking de identidad en 151.6s SIN regresion G1/G5-mini) con
1 SOLO epoch: misma mezcla D1 x3, mitad de exposicion.

PRE-REGISTRO (congelado antes de correr):
  P-V2-1: G3 >= 18/20  (grokking por lr alto + D1 x3 compensa 1 epoch)
  P-V2-2: G1 >= 85%    (mitad de exposicion -> menos olvido)
  P-V2-3: G5 >= 60%    (replay presente)
  P-V2-4: G2A >= 95%   (E-MIX B ya lo logro con 1 epoch)
  Regla: pasa todo -> APTO_PARA_E5 (candidato unico v2).

Diferencias vs e2final_kernel.py:
  - SIN FASE 0: reusa replay.jsonl cacheado de v1 (dataset), ahorra ~94 min.
  - Train: 1 epoch, LR=3e-4, warmup 10% + cosine (LambdaLR de egrok_kernel).
  - Adapter out: cognia3b_v2.
~3 GPU-h. [Derivado de e2final_kernel.py]
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
BUDGET_S = int(8.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e2finalv2_results.json")
SEED = 20260707
SEQ = 2048
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E2-FINAL-v2-egrok",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-V2-1": "G3 >= 18/20 (lr 3e-4 + D1 x3, 1 epoch)",
               "P-V2-2": "G1 >= 85% (mitad de exposicion vs v1)",
               "P-V2-3": "G5 >= 60%",
               "P-V2-4": "G2A >= 95%",
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


# ------------------------------------------------- train unsloth (subproceso)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; LR = 3e-4; SEQ = 2048; WARMUP = 0.10
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
# warmup 10% + cosine (receta E-GROK grok_lr3, codigo de egrok_kernel.py)
from torch.optim.lr_scheduler import LambdaLR
total = len(lotes)   # 1 EPOCH (fix G1: mitad de exposicion vs v1)
w = max(1, int(total * WARMUP))
sched = LambdaLR(opt, lambda s: (s+1)/w if s < w else
                 0.5*(1+math.cos(math.pi*(s-w)/max(1, total-w))))
model.train()
losses = []; t0 = time.time(); tok = 0
for ids, att, lab in lotes:   # 1 EPOCH
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
    replay = carga_jsonl("replay.jsonl")   # cacheado de v1 (sin FASE 0)
    RESULTS["replay"] = {"cacheado_de": "e2final-v1", "aceptados": len(replay)}
    print(f"datos: d1={len(d1)} d5={len(d5)} accion={len(accion)} replay={len(replay)}", flush=True)
    dump()

    # ── eval del base (baseline pareado, mismas suites congeladas) ──
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    base.eval()

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

    # corpus FINAL: mezcla unica con D1 x3 (identica a v1)
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
    print("== TRAIN FINAL v2 (mezcla unica, 1 epoch, lr 3e-4 + warmup 10%) ==", flush=True)
    RESULTS["train"]["final"] = entrena_subproceso("cognia3b_v2", model_dir,
                                                   f"{OUT}/tok_final.jsonl")
    dump()

    from peft import PeftModel
    model_f = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    pm_f = PeftModel.from_pretrained(model_f, f"{OUT}/adapters/cognia3b_v2")
    pm_f.eval()
    print("== eval checkpoint candidato v2 ==", flush=True)
    ev_f = eval_todo(pm_f, tokenizer, suites, "cognia3b_v2")
    RESULTS["evals"]["cognia3b_v2"] = ev_f
    RESULTS["veredictos"]["cognia3b_v2"] = compara(base_ev["items"], ev_f["items"])
    dump()
    del model_f, pm_f
    gc.collect()
    torch.cuda.empty_cache()

    try:
        v = RESULTS["veredictos"]["cognia3b_v2"]
        checks = {"P-V2-1_g3": [v["g3"]["acc_brazo"], v["g3"]["acc_brazo"] >= 0.90],
                  "P-V2-2_g1": [v["g1"]["acc_brazo"], v["g1"]["acc_brazo"] >= 0.85],
                  "P-V2-3_g5": [v["g5"]["acc_brazo"], v["g5"]["acc_brazo"] >= 0.60],
                  "P-V2-4_g2a": [v["g2a"]["acc_brazo"], v["g2a"]["acc_brazo"] >= 0.95]}
        checks["APTO_PARA_E5"] = all(x[1] for x in checks.values())
        RESULTS["checkpoint_candidato"] = checks
    except Exception as e:
        RESULTS["checkpoint_candidato"] = {"error": str(e)[:300]}

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E2-FINAL-v2 DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["checkpoint_candidato"]), flush=True)


if __name__ == "__main__":
    main()
