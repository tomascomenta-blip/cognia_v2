# -*- coding: utf-8 -*-
"""
E-MIX-B - COMPLETA EL BRAZO A con el merge DC-9 ARREGLADO (arbitro DC-4, toma 2).

En E-MIX el brazo A-final evaluo EXACTAMENTE como la base en G1/G3/G5 (deltas
0.0pp, CERO items discordantes en 145) y solo G2A cambio: el merge manual de
etapa-1 (dequant in-place reemplazando modulos durante named_modules()) NO
aplico el adapter — el merged era la base pelada y etapa-2 entreno sobre nada.
El adapter a_etapa1 esta SANO (504 keys, norma 2.39): el bug es del merge.

Fix: merge canonico con model.dequantize() nativo de transformers (>=4.46)
sobre la carga NF4 (DC-9: mergear sobre la dequantizacion, no sobre fp16
original) + VERIFICACION DURA post-merge (in-kernel, aborta si falla):
  V1: la norma de >=3 tensores del merged difiere de la base (>1e-3).
  V2: eval G3 (20 items) del merged pelado se REGISTRA (ademas mide si
      etapa-1 aprendio identidad, dato que E-MIX no midio).

Reusa del kernel E-MIX montado (kernel_sources): adapter a_etapa1 entrenado,
tok_etapa2.jsonl (corpus etapa-2 ya tokenizado) y los binarios por item de
base y brazo_b (emix_results.json) para el McNemar pareado final (mismas
versiones pip fresh + mismo tipo de GPU; drift de runtime declarado como
supuesto).

PREDICCIONES PRE-REGISTRADAS (heredadas + nuevas):
  P-EMIXB-1: el merged (etapa-1 sola) da G3 >= 10/20 (la mezcla B con el
             mismo corpus dio 14/20; secuencial dedicado no deberia dar 0).
  P-EMIXB-2 (=P-EMIX-1): A-final > B en promedio (G1+G2A+G3)/3 por >1pp;
             si B >= A-1pp o gana -> E2/E3/E4 COLAPSAN en mezcla unica.
  P-EMIXB-3 (=P-EMIX-4): G3 de A-final >= 18/20.
Presupuesto: ~2 GPU-h. Salida: /kaggle/working/emixb_results.json.
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
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "emixb_results.json")
SEED = 20260707
SEQ = 2048
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E-MIX-B-brazo-A-fix",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-EMIXB-1": "merged etapa-1 da G3 >= 10/20",
               "P-EMIXB-2": "A > B en promedio(G1,G2A,G3) por >1pp; si no -> colapso E2-E4",
               "P-EMIXB-3": "G3 A-final >= 18/20",
               "supuesto": "binarios base/brazo_b reusados del kernel E-MIX montado (mismo tipo GPU + pip fresh)"},
           "env": {}, "suites_hash_ok": None, "merge": {}, "train": {},
           "evals": {}, "veredictos": {}, "decision_topologia": None}


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
             if "adapter" not in p.lower() and "/working/" not in p]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    return pool[0]


# ---------------------------------------------------------------- oraculos (= E-MIX)
def fold(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


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
        hits = _NUM_RE.findall(respuesta.replace("−", "-"))
        if not hits or abs(float(hits[-1].replace(",", ".")) - float(oracle["number"])) > 1e-6:
            return False
    return True


_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)", re.IGNORECASE)


def accion_pass(respuesta, oracle):
    m = _ACCION_RE.search(respuesta)
    if not m:
        return False
    if m.group(1) not in (oracle.get("accion_tools") or []):
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


# ---------------------------------------------------------------- merge DC-9 (fix)
def merge_canonico(model_dir, adapter_dir, merged_out):
    """base NF4 (misma BnB del training) -> model.dequantize() NATIVO ->
    PeftModel -> merge_and_unload -> save fp16. Con verificacion V1 in-situ."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    model = model.dequantize()          # transformers nativo: bnb -> fp16 limpio
    model = model.half()

    # normas ANTES del merge (V1)
    monitoreo = ["model.layers.0.self_attn.q_proj.weight",
                 "model.layers.17.mlp.down_proj.weight",
                 "model.layers.35.self_attn.v_proj.weight"]
    sd = model.state_dict()
    normas_pre = {k: float(sd[k].float().norm()) for k in monitoreo if k in sd}

    pm = PeftModel.from_pretrained(model, adapter_dir)
    merged = pm.merge_and_unload()

    sd2 = merged.state_dict()
    normas_post = {k: float(sd2[k].float().norm()) for k in normas_pre}
    diffs = {k: abs(normas_post[k] - normas_pre[k]) for k in normas_pre}
    aplicado = all(d > 1e-3 for d in diffs.values())
    print("V1 merge:", json.dumps({"pre": normas_pre, "post": normas_post,
                                   "aplicado": aplicado}), flush=True)
    if not aplicado:
        raise RuntimeError(f"MERGE NO APLICADO (diffs {diffs}) — abortando, "
                           "no se repite el bug de E-MIX")

    merged.save_pretrained(merged_out, safe_serialization=True)
    AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True).save_pretrained(merged_out)
    del model, pm, merged, sd, sd2
    gc.collect()
    import torch as _t
    _t.cuda.empty_cache()
    return {"normas_diff": diffs, "aplicado": True}


# ---------------------------------------------------------------- train (= E-MIX)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; LR = 1e-4; SEQ = 2048
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from emixb_shared import lotes_packed_json

cfg = json.load(open(sys.argv[1]))
torch.manual_seed(SEED); random.seed(SEED)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=cfg["model_dir"], max_seq_length=SEQ, load_in_4bit=True, dtype=None)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=SEED)
ejemplos = []
with open(cfg["pares_tok"], encoding="utf-8") as f:
    for line in f:
        if line.strip():
            ejemplos.append(json.loads(line))
lotes = lotes_packed_json(ejemplos, SEQ, cfg["mb"], SEED)
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR)
from torch.optim.lr_scheduler import CosineAnnealingLR
sched = CosineAnnealingLR(opt, T_max=len(lotes))
model.train()
losses = []; t0 = time.time(); tok = 0
for ids, att, lab in lotes:
    x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
    y = torch.tensor(lab, device="cuda")
    loss = model(input_ids=x, attention_mask=a, labels=y).loss
    loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
    losses.append(loss.item()); tok += int(a.sum().item())
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

EMIXB_SHARED = r'''
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


# ---------------------------------------------------------------- eval (= E-MIX)
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


def eval_suites(model, tokenizer, suites, etiqueta, solo=None):
    res = {"items": {}}
    for nombre, items in suites.items():
        if solo and nombre not in solo:
            continue
        binarios = {}
        bs = 4 if nombre == "g2a" else 8
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
        if suite not in brazo_items:
            continue
        a = brazo_items[suite]
        n01 = sum(1 for k in b if not b[k] and a.get(k))
        n10 = sum(1 for k in b if b[k] and not a.get(k))
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
        return

    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # insumos del kernel E-MIX montado
    adapter_e1 = os.path.dirname(_find("a_etapa1/adapter_config.json"))
    tok_etapa2 = _find("tok_etapa2.jsonl")
    emix_prev = json.load(open(_find("emix_results.json"), encoding="utf-8"))
    base_items = emix_prev["evals"]["base"]["items"]
    print(f"insumos: adapter={adapter_e1} tok_etapa2={tok_etapa2}", flush=True)

    suites = {}
    for nombre, clave in (("g1_general.jsonl", "g1"), ("g3_identidad.jsonl", "g3"),
                          ("g5_espanol.jsonl", "g5"), ("g2_accion.jsonl", "g2a")):
        with open(_find(nombre), encoding="utf-8") as f:
            suites[clave] = [json.loads(l) for l in f if l.strip()]

    # 1) merge canonico con verificacion V1
    print("== merge canonico etapa-1 ==", flush=True)
    merged_dir = f"{OUT}/merged_etapa1"
    t0 = time.time()
    RESULTS["merge"] = merge_canonico(model_dir, adapter_e1, merged_dir)
    RESULTS["merge"]["wall_min"] = round((time.time() - t0) / 60, 1)
    dump()

    # 2) V2: eval del merged pelado (G3 completo + G1 para no-regresion)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model_m = AutoModelForCausalLM.from_pretrained(
        merged_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    model_m.eval()
    print("== eval merged etapa-1 (V2) ==", flush=True)
    ev_m = eval_suites(model_m, tokenizer, suites, "merged_e1", solo=("g3", "g5"))
    RESULTS["evals"]["merged_etapa1"] = ev_m
    RESULTS["veredictos"]["merged_etapa1"] = compara(base_items, ev_m["items"])
    dump()
    del model_m
    gc.collect()
    torch.cuda.empty_cache()

    # 3) etapa-2 sobre el merged (mismo corpus tokenizado de E-MIX)
    with open(os.path.join(OUT, "emixb_shared.py"), "w") as f:
        f.write(EMIXB_SHARED)
    probe = os.path.join(OUT, "unsloth_train_emixb.py")
    with open(probe, "w") as f:
        f.write(UNSLOTH_TRAIN)
    cfg = {"model_dir": merged_dir, "pares_tok": tok_etapa2, "mb": 4,
           "adapter_out": f"{OUT}/adapters/a2_etapa2",
           "stats_out": f"{OUT}/train_a2_etapa2.json"}
    cfg_path = f"{OUT}/cfg_a2.json"
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    print("== etapa-2 sobre merged (fix) ==", flush=True)
    r = subprocess.run([sys.executable, probe, cfg_path], capture_output=True,
                       text=True, timeout=2 * 3600)
    print((r.stdout or "")[-1200:], flush=True)
    if os.path.exists(cfg["stats_out"]):
        RESULTS["train"]["a2_etapa2"] = json.load(open(cfg["stats_out"]))
    else:
        RESULTS["train"]["a2_etapa2"] = {"error": (r.stderr or "")[-600:]}
        dump()
        raise RuntimeError("etapa-2 fallo")
    dump()

    # 4) eval final del brazo A arreglado
    from peft import PeftModel
    model_a = AutoModelForCausalLM.from_pretrained(
        merged_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    pm_a = PeftModel.from_pretrained(model_a, f"{OUT}/adapters/a2_etapa2")
    pm_a.eval()
    print("== eval brazo A (fix) ==", flush=True)
    ev_a = eval_suites(pm_a, tokenizer, suites, "brazo_a_fix")
    RESULTS["evals"]["brazo_a_fix"] = ev_a
    RESULTS["veredictos"]["brazo_a_fix"] = compara(base_items, ev_a["items"])
    dump()
    del model_a, pm_a
    gc.collect()
    torch.cuda.empty_cache()
    shutil.rmtree(merged_dir, ignore_errors=True)

    # 5) decision §7.3 con A valido vs B (binarios de E-MIX montado)
    try:
        va = RESULTS["veredictos"]["brazo_a_fix"]
        vb = emix_prev["veredictos"]["brazo_b"]
        g3_merged = RESULTS["veredictos"]["merged_etapa1"]["g3"]["acc_brazo"]
        prom_a = (va["g1"]["acc_brazo"] + va["g2a"]["acc_brazo"] + va["g3"]["acc_brazo"]) / 3
        prom_b = (vb["g1"]["acc_brazo"] + vb["g2a"]["acc_brazo"] + vb["g3"]["acc_brazo"]) / 3
        colapsa = prom_b >= prom_a - 0.01
        RESULTS["decision_topologia"] = {
            "prom_a_fix": round(prom_a, 4), "prom_b": round(prom_b, 4),
            "resultado": "mezcla_unica_colapsa_E2-E4" if colapsa else "secuencial",
            "P-EMIXB-1_g3_merged": g3_merged,
            "P-EMIXB-3_g3_a_final": va["g3"]["acc_brazo"]}
    except Exception as e:
        RESULTS["decision_topologia"] = {"error": str(e)[:300]}

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E-MIX-B DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["decision_topologia"]), flush=True)


if __name__ == "__main__":
    main()
