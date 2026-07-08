
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
