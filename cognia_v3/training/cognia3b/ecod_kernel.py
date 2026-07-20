# -*- coding: utf-8 -*-
"""
E-COD - EXPERTO DE CODIGO PYTHON para el fleet (fase 2, 2026-07-09).

DISENO (leccion E-RZN aplicada): NO auto-destilar greedy-correcto (capacidad
no transfiere: E-RZN v2 = 0.0pp). Aca se destila BUSQUEDA: BoN@8 a temp 0.8
verificado por EJECUCION real -> pares (prompt -> solucion que pasa tests)
-> el adapter comprime el hit de la busqueda en la politica greedy. El gap
greedy->BoN esta MEDIDO en este repo (+10pp, 40->50 pass@1 con juez).

Datos: MBPP (google-research, 974 tareas con tests). Train pool = task_id
601-974 + 11-510 parcial; EVAL SLICE = task_id 11-210 EXCLUIDO del train
(disjunto por construccion + decontaminacion por string). MBPP es publico
(riesgo de contaminacion del pretraining de Qwen) -> el numero ABSOLUTO no
se interpreta; el gate es el DELTA PAREADO base-vs-adapter (la contaminacion
afecta ambos brazos por igual). La suite custom del repo (tasks_hard) queda
como verificacion secundaria en deploy local.

PRE-REGISTRO (congelado antes de correr):
  P-COD-1: pass@1 del adapter >= base + 8pp en el eval slice (N=200),
           McNemar p<0.05, n01>n10.
  P-COD-2: yield de BoN@8 en banda [20%, 80%] (fuera -> ABORTA sin
           entrenar: <20% no hay hits que destilar; >80% demasiado facil).
  Gate del EXPERTO (fleet): solo pass@1 codigo. El router lo activara solo
  en tareas de codigo (anti-catastrofe = base por default).

Ejecucion de codigo generado: subprocess aislado + timeout 8s (regla 9 de
CLAUDE.md). ~4 GPU-h. [Deriva de erznv2_kernel.py]
"""
import gc
import glob
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

T0 = time.time()
BUDGET_S = int(8.5 * 3600)
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "ecod_results.json")
SEED = 20260709
SEQ = 1024
BON_K = 8
BON_TEMP = 0.8
N_EVAL = 200
EXEC_TIMEOUT = 8
MBPP_URL = ("https://raw.githubusercontent.com/google-research/google-research/"
            "master/mbpp/mbpp.jsonl")
SYSTEM_COD = ("You are an expert Python programmer. Reply with ONLY a Python "
              "code block containing the complete function. No explanations.")

RESULTS = {"exp": "E-COD-experto-codigo",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-COD-1": "pass@1 adapter >= base + 8pp (N=200), McNemar p<0.05",
               "P-COD-2": "yield BoN@8 en banda [20%,80%] (fuera, ABORTA)",
               "nota": "MBPP publico: solo se interpreta el DELTA pareado"},
           "env": {}, "datos": {}, "bon": {}, "train": {},
           "evals": {}, "veredictos": {}, "experto": None}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    print(f"[sh] {' '.join(cmd[:5])}... rc={r.returncode} ({tail[-1] if tail else ''})", flush=True)
    return r


def _find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)
             if "adapter" not in p.lower()]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    return pool[0]


def mcnemar_p(n01, n10):
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


# ---------------------------------------------------------------- codigo
_CODE_BLOCK_RX = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code(texto: str) -> str:
    m = _CODE_BLOCK_RX.search(texto or "")
    if m:
        return m.group(1)
    # sin bloque: si parece codigo pelado, usarlo
    t = (texto or "").strip()
    return t if ("def " in t or "return" in t) else ""


def ejecuta_tests(code: str, task: dict) -> bool:
    """True si el codigo + setup + asserts corren con exit 0 (subprocess
    aislado, timeout). Es el MISMO criterio del benchmark local."""
    if not code.strip():
        return False
    src = (task.get("test_setup_code") or "") + "\n" + code + "\n" + \
          "\n".join(task.get("test_list") or [])
    path = os.path.join(OUT, "probe_exec.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           timeout=EXEC_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def prompt_de(task: dict) -> str:
    """Prompt del deploy: enunciado MBPP + firma del primer assert (el
    formato de MBPP: el nombre/firma solo se conoce por los tests)."""
    firma = (task.get("test_list") or [""])[0]
    return (f"{task['text']}\n"
            f"Your function must satisfy tests like: {firma}")


# ---------------------------------------------------------------- datos
def carga_mbpp() -> list:
    path = os.path.join(OUT, "mbpp.jsonl")
    if not os.path.exists(path):
        print("descargando MBPP...", flush=True)
        urllib.request.urlretrieve(MBPP_URL, path)
    tareas = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tareas.append(json.loads(line))
    return tareas


# ------------------------------------------------- train unsloth (E-GROK)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260709; LR = 3e-4; SEQ = 1024; WARMUP = 0.10
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
from torch.optim.lr_scheduler import LambdaLR
total = len(lotes)
w = max(1, int(total * WARMUP))
sched = LambdaLR(opt, lambda s: (s+1)/w if s < w else
                 0.5*(1+math.cos(math.pi*(s-w)/max(1, total-w))))
model.train()
losses = []; t0 = time.time(); tok = 0
for ids, att, lab in lotes:
    x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
    y = torch.tensor(lab, device="cuda")
    loss = model(input_ids=x, attention_mask=a, labels=y).loss
    loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
    losses.append(loss.item()); tok += int(a.sum().item())
    if len(losses) % 50 == 0:
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


def entrena_subproceso(nombre, model_dir, pares_tok_path, mb=8):
    cfg = {"model_dir": model_dir, "pares_tok": pares_tok_path, "mb": mb,
           "adapter_out": f"{OUT}/adapters/{nombre}",
           "stats_out": f"{OUT}/train_{nombre}.json"}
    cfg_path = f"{OUT}/cfg_{nombre}.json"
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    probe = os.path.join(OUT, "unsloth_train_ecod.py")
    with open(probe, "w") as f:
        f.write(UNSLOTH_TRAIN)
    r = subprocess.run([sys.executable, probe, cfg_path], capture_output=True,
                       text=True, timeout=3 * 3600)
    print((r.stdout or "")[-1200:], flush=True)
    if os.path.exists(cfg["stats_out"]):
        return json.load(open(cfg["stats_out"]))
    err = (r.stderr or "")[-600:]
    if "out of memory" in err.lower() and mb > 2:
        print(f"[{nombre}] OOM con mb={mb} -> retry mb={mb//2}", flush=True)
        return entrena_subproceso(nombre, model_dir, pares_tok_path, mb=mb // 2)
    return {"error": err}


# ---------------------------------------------------------------- generacion
def genera_batch(model, tokenizer, prompts, max_new, temperature=0.0):
    import torch
    tokenizer.padding_side = "left"
    textos = [tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_COD},
         {"role": "user", "content": p}],
        tokenize=False, add_generation_prompt=True) for p in prompts]
    enc = tokenizer(textos, return_tensors="pt", padding=True,
                    add_special_tokens=False).to("cuda")
    kwargs = dict(max_new_tokens=max_new, pad_token_id=tokenizer.eos_token_id)
    if temperature > 0:
        kwargs.update(do_sample=True, temperature=temperature, top_p=0.95)
    else:
        kwargs.update(do_sample=False)
    with torch.no_grad():
        out = model.generate(**enc, **kwargs)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True) for i in range(len(prompts))]


def eval_pass1(model, tokenizer, tareas, etiqueta):
    binarios = {}
    for i in range(0, len(tareas), 8):
        chunk = tareas[i:i + 8]
        outs = genera_batch(model, tokenizer, [prompt_de(t) for t in chunk], 512)
        for t, o in zip(chunk, outs):
            binarios[str(t["task_id"])] = ejecuta_tests(extract_code(o), t)
        if (i // 8) % 5 == 0:
            acc = sum(binarios.values()) / len(binarios)
            print(f"  [{etiqueta}] {len(binarios)}/{len(tareas)} pass@1={acc:.1%}", flush=True)
            dump()
    acc = sum(binarios.values()) / len(binarios)
    print(f"  [{etiqueta}] pass@1 FINAL: {acc:.1%}", flush=True)
    return binarios


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
    dump()

    with open(os.path.join(OUT, "emix_shared.py"), "w") as f:
        f.write(EMIX_SHARED)

    tareas = carga_mbpp()
    # split disjunto POR ID: eval = 11..210 (los canonicos de test de MBPP),
    # train pool = todo lo demas. Decontaminacion extra por texto exacto.
    ev = [t for t in tareas if 11 <= t["task_id"] <= 210][:N_EVAL]
    ev_txt = {t["text"].strip() for t in ev}
    pool = [t for t in tareas if not (11 <= t["task_id"] <= 210)
            and t["text"].strip() not in ev_txt]
    RESULTS["datos"] = {"total": len(tareas), "eval": len(ev), "pool": len(pool)}
    print(f"datos: total={len(tareas)} eval={len(ev)} pool={len(pool)}", flush=True)
    dump()

    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    base.eval()

    # ── BoN@8 verificado por ejecucion sobre el train pool ──
    pares, con_hit = [], 0
    t0 = time.time()
    for i, t in enumerate(pool):
        hit = None
        # ronda greedy primero (barata y determinista), luego sampling
        outs = genera_batch(base, tokenizer, [prompt_de(t)], 512)
        if ejecuta_tests(extract_code(outs[0]), t):
            hit = outs[0]
        else:
            for j in range(0, BON_K - 1, 4):
                k = min(4, BON_K - 1 - j)
                outs = genera_batch(base, tokenizer, [prompt_de(t)] * k, 512,
                                    temperature=BON_TEMP)
                for o in outs:
                    if ejecuta_tests(extract_code(o), t):
                        hit = o
                        break
                if hit:
                    break
        if hit:
            con_hit += 1
            code = extract_code(hit)
            pares.append({"prompt": prompt_de(t),
                          "completion": f"```python\n{code}```"})
        if i % 25 == 0:
            print(f"  bon {i}/{len(pool)} hits={con_hit} "
                  f"({(time.time()-t0)/60:.0f} min)", flush=True)
            RESULTS["bon"] = {"procesadas": i + 1, "hits": con_hit}
            dump()
        if time.time() - T0 > BUDGET_S * 0.55:   # presupuesto: dejar 45% p/ train+eval
            print(f"  bon CORTADO por presupuesto en {i+1}/{len(pool)}", flush=True)
            break
    procesadas = min(i + 1, len(pool))
    yield_pct = con_hit / max(1, procesadas)
    RESULTS["bon"] = {"procesadas": procesadas, "hits": con_hit,
                      "yield": round(yield_pct, 3),
                      "wall_min": round((time.time() - t0) / 60, 1)}
    print("BON:", json.dumps(RESULTS["bon"]), flush=True)
    dump()

    if not (0.20 <= yield_pct <= 0.80):
        motivo = "no hay hits que destilar" if yield_pct < 0.20 else "demasiado facil"
        RESULTS["experto"] = {"P-COD-2": [round(yield_pct, 3), False],
                              "veredicto": f"ABORTADO: yield fuera de banda ({motivo})"}
        dump()
        print("ABORT P-COD-2:", json.dumps(RESULTS["experto"]), flush=True)
        return

    # ── eval base pass@1 (baseline pareado) ──
    print("== eval base pass@1 ==", flush=True)
    base_bin = eval_pass1(base, tokenizer, ev, "base")
    RESULTS["evals"]["base"] = base_bin
    dump()
    del base
    gc.collect()
    torch.cuda.empty_cache()

    # dataset reutilizable
    with open(os.path.join(OUT, "d_cod.jsonl"), "w", encoding="utf-8") as f:
        for r in pares:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── train E-GROK ──
    def escribe_tok(pares_, path):
        ej = []
        for r in pares_:
            pre = (f"<|im_start|>system\n{SYSTEM_COD}<|im_end|>\n"
                   f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n")
            full = pre + f"{r['completion']}<|im_end|>"
            ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
            ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
            ej.append({"ids": ids_full, "prompt_len": len(ids_pre)})
        with open(path, "w", encoding="utf-8") as f:
            for e in ej:
                f.write(json.dumps(e) + "\n")

    escribe_tok(pares, f"{OUT}/tok_cod.jsonl")
    print("== TRAIN E-COD (BoN destilado, 1 epoch, lr 3e-4 + warmup) ==", flush=True)
    RESULTS["train"] = entrena_subproceso("cognia3b_cod", model_dir, f"{OUT}/tok_cod.jsonl")
    dump()

    # ── eval adapter pass@1 ──
    from peft import PeftModel
    model_f = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    pm = PeftModel.from_pretrained(model_f, f"{OUT}/adapters/cognia3b_cod")
    pm.eval()
    print("== eval experto pass@1 ==", flush=True)
    cod_bin = eval_pass1(pm, tokenizer, ev, "cognia3b_cod")
    RESULTS["evals"]["cognia3b_cod"] = cod_bin

    n01 = sum(1 for k in base_bin if not base_bin[k] and cod_bin[k])
    n10 = sum(1 for k in base_bin if base_bin[k] and not cod_bin[k])
    acc_b = sum(base_bin.values()) / len(base_bin)
    acc_c = sum(cod_bin.values()) / len(cod_bin)
    p = mcnemar_p(n01, n10)
    RESULTS["veredictos"]["pass1"] = {"acc_base": round(acc_b, 3),
                                      "acc_experto": round(acc_c, 3),
                                      "delta_pp": round((acc_c - acc_b) * 100, 1),
                                      "n01": n01, "n10": n10, "p": round(p, 4)}
    RESULTS["experto"] = {
        "P-COD-1": [round((acc_c - acc_b) * 100, 1),
                    (acc_c - acc_b) >= 0.08 and p < 0.05 and n01 > n10],
        "P-COD-2": [RESULTS["bon"]["yield"], True],
        "APTO_FLEET": (acc_c - acc_b) >= 0.08 and p < 0.05 and n01 > n10}
    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E-COD DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["experto"]), flush=True)


if __name__ == "__main__":
    main()
