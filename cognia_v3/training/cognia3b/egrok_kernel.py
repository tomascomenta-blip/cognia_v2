# -*- coding: utf-8 -*-
"""
E-GROK - ACELERAR EL GROKKING: GPU-min A GATE FIJO (goal expertos MoM, obj. 5).

Grokking operacionalizado como COSTO DE CONVERGENCIA (memoria
cognia-x-velocidad-entreno: data-efficiency es la palanca de velocidad).
Metrica primaria: GPU-min de TRAIN hasta el PRIMER checkpoint que pasa
G3 >= 18/20 (gate fijo congelado, eval intermedia in-loop cada 10 steps).
Nada de "loss suelta": el reloj para cuando el GATE pasa.

Dataset: D1 identidad puro (la habilidad mas limpia con gate binario).
Runtime columna (E2A): unsloth + LoRA r16 a32 all-linear NF4, packing +
completion-masking, mb4, seq 1024, seed 20260707.

Brazos (mismos steps maximos = 2 epochs; solo cambia la palanca):
  grok_base   shuffle uniforme, lr 1e-4 cosine       (receta actual, control)
  grok_lr3    lr 3e-4, warmup 10% + cosine           (mas señal por step)
  grok_cortos anti-curriculum: pares CORTOS primero  (señal densa temprana)
  grok_denso  primer 25% del shuffle repetido 4x     (densidad > diversidad
              (mismo n de steps)                      para habilidad estrecha)

PREDICCIONES PRE-REGISTRADAS (congeladas antes de correr):
  P-GROK-1: grok_base pasa G3 antes de terminar el epoch 1 (la identidad
            es plantillosa; 2 epochs de E1 estaban sobre-presupuestados).
  P-GROK-2: grok_lr3 alcanza el gate en <= 0.6x los GPU-min de grok_base
            SIN romper G5-mini al final (riesgo medido: lr 2e-4 derivo a
            chino en otro regimen; con masking se re-testea).
  P-GROK-3: grok_denso alcanza el gate antes que grok_base (densidad gana
            para UNA habilidad estrecha) pero su G1-mini final es <= que el
            de grok_base (el costo de la diversidad perdida).
  P-GROK-4: grok_cortos no difiere de grok_base en >20% (la longitud no es
            la palanca dominante aca) — falsable en ambas direcciones.
REGLA DE ADOPCION: la palanca ganadora (menor GPU-min-a-gate con G1-mini
dentro de -4pp del control) se adopta para los trains de expertos del fleet.
G1-mini/G5-mini = primeros 40/25 items de las suites congeladas (smoke de
no-regresion por brazo; el gate G1 completo lo corre el kernel de la etapa
real, no este).

Presupuesto: ~2 GPU-h. Salida: /kaggle/working/egrok_results.json.
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
BUDGET_S = int(3.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "egrok_results.json")
SEED = 20260707
SEQ = 1024
EPOCHS = 2
EVAL_CADA = 10          # steps entre evals G3 intermedias
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E-GROK-gate-fijo",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-GROK-1": "grok_base pasa G3 antes de fin de epoch 1",
               "P-GROK-2": "grok_lr3 gate en <=0.6x GPU-min de base sin romper G5-mini",
               "P-GROK-3": "grok_denso gate antes que base; G1-mini <= base",
               "P-GROK-4": "grok_cortos == base +-20%",
               "regla": "gana menor GPU-min-a-gate con G1-mini >= control-4pp"},
           "env": {}, "suites_hash_ok": None, "brazos": {}}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    print(f"[sh] {' '.join(cmd[:4])}... rc={r.returncode} ({tail[-1] if tail else ''})", flush=True)
    return r


def _find(patron):
    hits = glob.glob(f"/kaggle/input/**/{patron}", recursive=True)
    if not hits:
        raise FileNotFoundError(patron)
    hits.sort(key=len)
    return hits[0]


def verifica_suites():
    with open(_find("SUITES_FROZEN.json"), encoding="utf-8") as f:
        frozen = json.load(f)["suites"]
    ok = True
    for nombre, meta in frozen.items():
        if nombre in ("g2_razonamiento.jsonl", "g2_accion.jsonl"):
            continue  # no se usan aca
        try:
            path = _find(nombre)
        except FileNotFoundError:
            ok = False
            continue
        if hashlib.sha256(open(path, "rb").read()).hexdigest() != meta["sha256"]:
            print(f"SUITE ALTERADA: {nombre}", flush=True)
            ok = False
    return ok


# El train + eval intermedia corren en UN subproceso por brazo (aisla los
# parches de unsloth y libera VRAM entre brazos).
BRAZO_TRAIN = r'''
import json, math, os, random, re, sys, time, unicodedata
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; SEQ = 1024; EPOCHS = 2; EVAL_CADA = 10
SYSTEM_ES = "Eres un asistente útil."; SYSTEM_EN = "You are a helpful assistant."
cfg = json.load(open(sys.argv[1]))

from unsloth import FastLanguageModel
import torch

def fold(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

def oracle_pass(respuesta, oracle):
    r = fold(respuesta)
    if any(fold(k) not in r for k in (oracle.get("must_all") or [])): return False
    ma = oracle.get("must_any") or []
    if ma and not any(fold(k) in r for k in ma): return False
    if any(fold(k) in r for k in (oracle.get("not_any") or [])): return False
    if oracle.get("number") is not None:
        hits = _NUM_RE.findall(respuesta.replace("−", "-"))
        if not hits or abs(float(hits[-1].replace(",", ".")) - float(oracle["number"])) > 1e-6:
            return False
    return True

_ES = {"el","la","los","las","de","que","y","en","un","una","es","por","con",
       "para","del","se","no","su","al","como","mas","pero","este","esta","son","hay","muy"}
_EN = {"the","of","and","to","in","is","that","it","for","on","with","as","are",
       "this","was","be","by","an","not","or"}

def es_espanol(r):
    ps = re.findall(r"[a-záéíóúñü]+", r.lower())
    if not ps: return False
    return sum(1 for p in ps if fold(p) in _ES) > sum(1 for p in ps if p in _EN)

def genera(model, tokenizer, items, max_new):
    tokenizer.padding_side = "left"
    textos = [tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_ES if it["idioma"]=="es" else SYSTEM_EN},
         {"role": "user", "content": it["prompt"]}],
        tokenize=False, add_generation_prompt=True) for it in items]
    enc = tokenizer(textos, return_tensors="pt", padding=True,
                    add_special_tokens=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            for i in range(len(items))]

def eval_suite(model, tokenizer, items, g5_extra=False):
    ok = 0
    for i in range(0, len(items), 8):
        chunk = items[i:i+8]
        outs = genera(model, tokenizer, chunk, max(it["max_new_tokens"] for it in chunk))
        for it, o in zip(chunk, outs):
            hit = oracle_pass(o, it["oracle"])
            if g5_extra and it["gate"] == "G5":
                hit = hit and es_espanol(o)
            ok += bool(hit)
    return ok

# datos
d1 = []
with open(cfg["d1"], encoding="utf-8") as f:
    for line in f:
        if line.strip():
            r = json.loads(line)
            d1.append({"prompt": r["prompt"], "completion": r["completion"]})
g3 = [json.loads(l) for l in open(cfg["g3"], encoding="utf-8") if l.strip()]
g1m = [json.loads(l) for l in open(cfg["g1"], encoding="utf-8") if l.strip()][:40]
g5m = [json.loads(l) for l in open(cfg["g5"], encoding="utf-8") if l.strip()][:25]

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=cfg["model_dir"], max_seq_length=SEQ, load_in_4bit=True, dtype=None)
torch.manual_seed(SEED); random.seed(SEED)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=SEED)

def tokeniza(pares):
    ej = []
    for r in pares:
        pre = "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n" % r["prompt"]
        full = pre + "%s<|im_end|>" % r["completion"]
        a = tokenizer(pre, add_special_tokens=False)["input_ids"]
        b = tokenizer(full, add_special_tokens=False)["input_ids"]
        ej.append({"ids": b, "prompt_len": len(a)})
    return ej

# ── orden segun brazo ──
rng = random.Random(SEED)
pares = list(d1)
rng.shuffle(pares)
brazo = cfg["brazo"]
if brazo == "grok_cortos":
    pares.sort(key=lambda r: len(r["prompt"]) + len(r["completion"]))
elif brazo == "grok_denso":
    n4 = len(pares) // 4
    pares = (pares[:n4] * 4)[:len(pares)]

ejemplos = tokeniza(pares)
filas, fila, lab, restante = [], [], [], SEQ
for e in ejemplos:
    x = e["ids"][:SEQ]
    if len(x) > restante:
        if fila: filas.append((fila, lab))
        fila, lab, restante = [], [], SEQ
    y = list(x); pl = min(e["prompt_len"], len(x)); y[:pl] = [-100]*pl
    fila += x; lab += y; restante -= len(x)
if fila: filas.append((fila, lab))
MB = 4
lotes = []
for i in range(0, len(filas), MB):
    ch = filas[i:i+MB]
    if len(ch) < MB: break
    lotes.append(([f + [0]*(SEQ-len(f)) for f, _ in ch],
                  [[1]*len(f) + [0]*(SEQ-len(f)) for f, _ in ch],
                  [l + [-100]*(SEQ-len(l)) for _, l in ch]))

lr = cfg["lr"]
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=lr)
total = len(lotes) * EPOCHS
if cfg.get("warmup", 0) > 0:
    from torch.optim.lr_scheduler import LambdaLR
    w = max(1, int(total * cfg["warmup"]))
    sched = LambdaLR(opt, lambda s: (s+1)/w if s < w else
                     0.5*(1+math.cos(math.pi*(s-w)/max(1, total-w))))
else:
    from torch.optim.lr_scheduler import CosineAnnealingLR
    sched = CosineAnnealingLR(opt, T_max=total)

reg = {"brazo": brazo, "lr": lr, "steps_total": total, "evals": [],
       "gate_step": None, "gate_train_s": None}
train_s = 0.0
step = 0
model.train()
for ep in range(EPOCHS):
    for ids, att, labs in lotes:
        t0 = time.time()
        x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
        y = torch.tensor(labs, device="cuda")
        loss = model(input_ids=x, attention_mask=a, labels=y).loss
        loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
        train_s += time.time() - t0
        step += 1
        if step % EVAL_CADA == 0 and reg["gate_step"] is None:
            FastLanguageModel.for_inference(model)
            g3_ok = eval_suite(model, tokenizer, g3)
            FastLanguageModel.for_training(model)
            model.train()
            reg["evals"].append({"step": step, "train_s": round(train_s, 1),
                                 "loss": round(loss.item(), 4), "g3": g3_ok})
            print("eval", brazo, "step", step, "g3", g3_ok, "/", len(g3), flush=True)
            if g3_ok >= 18:
                reg["gate_step"] = step
                reg["gate_train_s"] = round(train_s, 1)
                print("GATE G3 PASADO en step", step, "train_s", round(train_s,1), flush=True)
    if reg["gate_step"] is not None:
        break

# no-regresion mini al final (comparable entre brazos, no gate)
FastLanguageModel.for_inference(model)
reg["g1_mini_final"] = eval_suite(model, tokenizer, g1m)
reg["g5_mini_final"] = eval_suite(model, tokenizer, g5m, g5_extra=True)
reg["g3_final"] = eval_suite(model, tokenizer, g3)
with open(cfg["out"], "w") as f:
    json.dump(reg, f)
print("BRAZO_DONE", json.dumps(reg)[:400], flush=True)
'''


def main():
    sh([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"])
    sh([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"])
    sh([sys.executable, "-m", "pip", "install", "unsloth"])
    import torch
    RESULTS["env"] = {"gpu": torch.cuda.get_device_name(0),
                      "torch": torch.__version__}
    RESULTS["suites_hash_ok"] = verifica_suites()
    print("SUITES HASH OK:", RESULTS["suites_hash_ok"], flush=True)
    dump()
    if not RESULTS["suites_hash_ok"]:
        return

    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)
             if "adapter" not in p.lower()]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    model_dir = pool[0]

    # D1 puro: e1_train.jsonl MENOS los pares tooluse (heuristica: los pares
    # tooluse llevan el TOOLS_DOC con "ACCION:").
    d1_path = os.path.join(OUT, "d1_puro.jsonl")
    n_d1 = 0
    with open(_find("e1_train.jsonl"), encoding="utf-8") as f, \
         open(d1_path, "w", encoding="utf-8") as g:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "ACCION:" in r["prompt"] or "ACCION:" in r["completion"]:
                continue
            g.write(json.dumps({"prompt": r["prompt"], "completion": r["completion"]},
                               ensure_ascii=False) + "\n")
            n_d1 += 1
    print(f"D1 puro: {n_d1} pares", flush=True)
    RESULTS["n_d1"] = n_d1

    probe = os.path.join(OUT, "egrok_brazo.py")
    with open(probe, "w") as f:
        f.write(BRAZO_TRAIN)

    brazos = [
        {"brazo": "grok_base", "lr": 1e-4, "warmup": 0.0},
        {"brazo": "grok_lr3", "lr": 3e-4, "warmup": 0.10},
        {"brazo": "grok_cortos", "lr": 1e-4, "warmup": 0.0},
        {"brazo": "grok_denso", "lr": 1e-4, "warmup": 0.0},
    ]
    for b in brazos:
        if time.time() - T0 > BUDGET_S:
            RESULTS["brazos"][b["brazo"]] = {"skip": "budget"}
            continue
        cfg = dict(b, model_dir=model_dir, d1=d1_path,
                   g3=_find("g3_identidad.jsonl"), g1=_find("g1_general.jsonl"),
                   g5=_find("g5_espanol.jsonl"),
                   out=os.path.join(OUT, f"brazo_{b['brazo']}.json"))
        cfg_path = os.path.join(OUT, f"cfg_{b['brazo']}.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        print(f"== {b['brazo']} ==", flush=True)
        r = subprocess.run([sys.executable, probe, cfg_path], capture_output=True,
                           text=True, timeout=2 * 3600)
        print((r.stdout or "")[-1200:], flush=True)
        if os.path.exists(cfg["out"]):
            RESULTS["brazos"][b["brazo"]] = json.load(open(cfg["out"]))
        else:
            RESULTS["brazos"][b["brazo"]] = {"error": (r.stderr or "")[-500:]}
        dump()

    # veredicto pre-registrado
    try:
        base = RESULTS["brazos"]["grok_base"]
        candidatos = {}
        for nombre, r in RESULTS["brazos"].items():
            if r.get("gate_train_s") is not None and \
               r.get("g1_mini_final", 0) >= base.get("g1_mini_final", 0) - 1.6:  # -4pp de 40
                candidatos[nombre] = r["gate_train_s"]
        ganador = min(candidatos, key=candidatos.get) if candidatos else None
        RESULTS["veredicto"] = {
            "gate_train_s": {n: r.get("gate_train_s") for n, r in RESULTS["brazos"].items()},
            "g1_mini": {n: r.get("g1_mini_final") for n, r in RESULTS["brazos"].items()},
            "g5_mini": {n: r.get("g5_mini_final") for n, r in RESULTS["brazos"].items()},
            "ganador": ganador,
            "speedup_vs_base": (round(base["gate_train_s"] / candidatos[ganador], 2)
                                if ganador and base.get("gate_train_s") else None)}
    except Exception as e:
        RESULTS["veredicto"] = {"error": str(e)[:300]}

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E-GROK DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS.get("veredicto", {}))[:400], flush=True)


if __name__ == "__main__":
    main()
