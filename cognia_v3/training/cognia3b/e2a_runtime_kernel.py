# -*- coding: utf-8 -*-
"""
E2A - A/B DE RUNTIME CON STEPS IGUALADOS (reabre el confound de E1).

En E1 la comparacion unsloth-vs-transformers quedo CONFUNDIDA por steps:
transformers uso mb4 = 92 steps y unsloth mb8 = 46 steps (mismo dataset).
El ganador t_r16_all (G3 100%) vio 2x gradientes (loss 0.877 vs 1.273), asi
que su ventaja puede ser "mas entrenamiento", no "transformers > unsloth"
(results_e1/ANALISIS_E1.md). E2A entrena UN brazo nuevo que iguala la unica
variable que faltaba:

  u_r16_all_mb4: unsloth, LoRA r16 a32 all-linear, mb=4 -> 92 steps,
                 EPOCHS=2, LR=1e-4, SEED=20260707 (identico a t_r16_all).

Eval con el instrumento CORREGIDO de E1b (system neutro pareado por idioma)
sobre base NF4 + t_r16_all (montado del kernel E1, NO se re-entrena) +
u_r16_all_mb4. G1/G3/G5 + tooluse (N=10 direccional). Greedy, McNemar.

PREDICCIONES PRE-REGISTRADAS (congeladas antes de correr):
  P-E2A-1: loss_fin de u_r16_all_mb4 en 0.877 +-10% (la brecha de loss de E1
           era steps, no runtime).
  P-E2A-2: G3 de u_r16_all_mb4 >= 18/20 (la brecha G3 50%<->100% era steps).
  P-E2A-3: tok/s train de u_r16_all_mb4 >= 413 (unsloth conserva ventaja
           de velocidad aun con mb4).

REGLA DE DECISION (vinculante para el runtime de E2..E5):
  unsloth se ADOPTA si (G3 >= 18/20) Y (G1 delta >= -4pp vs base) Y
  (G5 >= base-4pp) Y (tok/s >= 413). Si cualquiera falla -> el runtime
  queda transformers+PEFT (t_r16_all columna definitiva, DC-5).

Presupuesto: ~1 GPU-h (train ~15 min + 3 evals ~25 min).
Salida: /kaggle/working/e2a_results.json (incremental).
"""
import gc
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

T0 = time.time()
BUDGET_S = int(2.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e2a_results.json")
SEED = 20260707
EPOCHS = 2
LR = 1e-4
SEQ = 1024
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E2A-runtime-steps-igualados",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "system_prompts": {"es": SYSTEM_ES, "en": SYSTEM_EN},
           "pre_registro": {
               "P-E2A-1": "loss_fin u_r16_all_mb4 en 0.877+-10%",
               "P-E2A-2": "G3 u_r16_all_mb4 >= 18/20",
               "P-E2A-3": "tok/s train >= 413",
               "regla": "unsloth ADOPTADO si G3>=18/20 y G1>=-4pp y G5>=base-4pp y tok/s>=413"},
           "env": {}, "suites_hash_ok": None, "train": {}, "evals": {},
           "veredictos": {}, "decision_runtime": None}


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


# ---------------------------------------------------------------- oraculo
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
    with open(_find("SUITES_FROZEN.json"), encoding="utf-8") as f:
        frozen = json.load(f)["suites"]
    ok = True
    for nombre, meta in frozen.items():
        if nombre == "g2_razonamiento.jsonl":
            continue
        try:
            path = _find(nombre)
        except FileNotFoundError:
            ok = False
            continue
        if hashlib.sha256(open(path, "rb").read()).hexdigest() != meta["sha256"]:
            print(f"SUITE ALTERADA: {nombre}", flush=True)
            ok = False
    return ok


# ---------------------------------------------------------------- unsloth (subproceso)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; EPOCHS = 2; LR = 1e-4; SEQ = 1024; MB = 4  # mb4 -> 92 steps (igualado a t_r16_all)
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from e2a_shared import find_model_dir, carga_train_json, lotes_packed_json

model_dir = find_model_dir()
torch.manual_seed(SEED); random.seed(SEED)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_dir, max_seq_length=SEQ, load_in_4bit=True, dtype=None)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=SEED)
ejemplos = carga_train_json(tokenizer)
lotes = lotes_packed_json(ejemplos, SEQ, MB)
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR)
from torch.optim.lr_scheduler import CosineAnnealingLR
sched = CosineAnnealingLR(opt, T_max=len(lotes) * EPOCHS)
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
adir = "/kaggle/working/adapters/u_r16_all_mb4"
model.save_pretrained(adir); tokenizer.save_pretrained(adir)
out = {"u_r16_all_mb4": {"steps": len(losses), "tok_s_util": round(tok/dt, 1),
    "wall_s": round(dt, 1), "loss_ini": round(sum(losses[:5])/5, 4),
    "loss_fin": round(sum(losses[-5:])/5, 4),
    "nan": any(math.isnan(l) for l in losses)}}
print("BRAZO u_r16_all_mb4", json.dumps(out["u_r16_all_mb4"]), flush=True)
with open("/kaggle/working/unsloth_train.json", "w") as f:
    json.dump(out, f)
print("UNSLOTH_TRAIN_DONE", flush=True)
'''

E2A_SHARED = r'''
import glob, json, os, random
SEED = 20260707
def find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)
             if "adapter" not in p.lower()]
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


# ---------------------------------------------------------------- eval (instrumento E1b)
def genera_batch(model, tokenizer, items, max_new):
    """items: [(prompt, idioma)] -> respuestas. System neutro por idioma."""
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


def eval_todo(model, tokenizer, suites, tooluse, etiqueta):
    res = {"items": {}}
    for nombre, items in suites.items():
        binarios = {}
        for i in range(0, len(items), 8):
            chunk = items[i:i + 8]
            outs = genera_batch(model, tokenizer,
                                [(it["prompt"], it["idioma"]) for it in chunk],
                                max(it["max_new_tokens"] for it in chunk))
            for it, o in zip(chunk, outs):
                ok = oracle_pass(o, it["oracle"])
                if it["gate"] == "G5":
                    ok = ok and es_espanol(o)
                binarios[it["id"]] = bool(ok)
        res["items"][nombre] = binarios
        print(f"  [{etiqueta}] {nombre}: {sum(binarios.values())/len(binarios):.1%}", flush=True)
    tu = {}
    for i in range(0, len(tooluse), 5):
        chunk = tooluse[i:i + 5]
        outs = genera_batch(model, tokenizer,
                            [(t["prompt"], "en") for t in chunk], 200)
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

    # 1) entrena u_r16_all_mb4 en subproceso (aisla parches unsloth)
    with open(os.path.join(OUT, "e2a_shared.py"), "w") as f:
        f.write(E2A_SHARED)
    probe = os.path.join(OUT, "unsloth_train_mb4.py")
    with open(probe, "w") as f:
        f.write(UNSLOTH_TRAIN)
    r = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                       timeout=2 * 3600)
    print((r.stdout or "")[-2000:], flush=True)
    ustats = os.path.join(OUT, "unsloth_train.json")
    if os.path.exists(ustats):
        RESULTS["train"].update(json.load(open(ustats)))
    else:
        RESULTS["train"]["unsloth_error"] = (r.stderr or "")[-800:]
    dump()

    # 2) suites + tooluse
    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
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

    # adapters: t_r16_all montado del kernel E1 + el nuevo u_r16_all_mb4
    adapters = []
    montados = sorted({os.path.dirname(p) for p in
                       glob.glob("/kaggle/input/**/adapters/*/adapter_config.json",
                                 recursive=True)})
    for a in montados:
        if os.path.basename(a) == "t_r16_all":
            adapters.append(a)
    nuevo = os.path.join(OUT, "adapters", "u_r16_all_mb4")
    if os.path.isdir(nuevo):
        adapters.append(nuevo)
    print("adapters a evaluar:", [os.path.basename(a) for a in adapters], flush=True)
    RESULTS["adapters"] = [os.path.basename(a) for a in adapters]
    dump()

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    model.eval()

    print("== eval base (system neutro) ==", flush=True)
    base_ev = eval_todo(model, tokenizer, suites, tooluse, "base")
    RESULTS["evals"]["base"] = base_ev
    dump()

    from peft import PeftModel
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
            ev = eval_todo(peft_model, tokenizer, suites, tooluse, nombre)
            RESULTS["evals"][nombre] = ev
            RESULTS["veredictos"][nombre] = compara(base_ev["items"], ev["items"])
        except Exception as e:
            RESULTS["evals"][nombre] = {"error": str(e)[:300]}
        dump()

    # 3) decision automatica pre-registrada
    try:
        v = RESULTS["veredictos"]["u_r16_all_mb4"]
        tr = RESULTS["train"]["u_r16_all_mb4"]
        g3_ok = v["g3"]["acc_brazo"] >= 0.90
        g1_ok = v["g1"]["delta_pp"] >= -4.0
        g5_ok = v["g5"]["acc_brazo"] >= v["g5"]["acc_base"] - 0.04 - 1e-9
        tok_ok = tr["tok_s_util"] >= 413
        RESULTS["decision_runtime"] = {
            "g3_ok": g3_ok, "g1_ok": g1_ok, "g5_ok": g5_ok, "tok_ok": tok_ok,
            "runtime": "unsloth" if (g3_ok and g1_ok and g5_ok and tok_ok)
                       else "transformers"}
    except Exception as e:
        RESULTS["decision_runtime"] = {"error": str(e)[:200]}

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E2A DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["decision_runtime"]), flush=True)


if __name__ == "__main__":
    main()
