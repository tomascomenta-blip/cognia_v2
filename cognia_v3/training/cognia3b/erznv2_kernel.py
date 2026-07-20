# -*- coding: utf-8 -*-
"""
E-RZN - EXPERTO DE RAZONAMIENTO para el fleet (fase 2, 2026-07-08).
La receta E-GROK quedo validada a corpus completo (E2-FINAL-v2: G2A 98%);
este kernel la aplica al nicho razonamiento con dataset D4 generado por
STaR in-kernel: problemas PROGRAMATICOS con respuesta verificable por
construccion (plantillas ORIGINALES, no de benchmarks publicos), el base
NF4 genera CoT greedy, y solo se conservan las cadenas cuya respuesta
final es CORRECTA (juez = ultimo_numero / keyword exacta).

Formato de train = el del deploy: user = problema PELADO (como los items
G2R), assistant = CoT + respuesta. El adapter aprende a razonar
espontaneamente sin instruccion CoT (la instruccion solo se usa al GENERAR).

V2 (leccion de E-RZN v1, ANALISIS_ERZN.md): el generador v1 era demasiado
FACIL (yield 86% vs G2R base 57% -> cero senal, G2R -4pp n.s.). v2 endurece:
composicion multi-paso encadenada, numeros DISTRACTORES irrelevantes, orden
con 5-6 entidades preguntando por el 2do, division con resto.

PRE-REGISTRO (congelado antes de correr):
  P-RZN2-1: G2R del adapter >= base + 10pp con McNemar p<0.05 (N=100).
  P-RZN2-2: yield STaR en BANDA [15%, 65%]. Fuera de banda ABORTA sin
            entrenar EN AMBAS DIRECCIONES (<15% demasiado dificil, >65%
            demasiado facil = leccion v1: el modelo ya lo sabe).
  Gate del EXPERTO (fleet): solo G2R. G1/G3/G5 no juegan (el router nunca
  activa este experto en esas rutas; anti-catastrofe = base por default).

Descontaminacion in-kernel: ningun problema generado comparte prompt
(folded, substring bidireccional) con g2_razonamiento.jsonl; se registra
el conteo de colisiones descartadas.

~3.5 GPU-h (gen ~2h + train ~40min + eval ~30min). [Deriva de e2finalv2_kernel.py]
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
RESULTS_PATH = os.path.join(OUT, "erznv2_results.json")
SEED = 20260708
SEQ = 1024          # CoT de matematica corta: 1024 alcanza y duplica el packing
N_PROBLEMAS = 1400  # objetivo de generacion (yield esperado 40-60% -> ~600-800 pares)
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E-RZN-v2-dificil",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "pre_registro": {
               "P-RZN2-1": "G2R adapter >= base + 10pp, McNemar p<0.05",
               "P-RZN2-2": "yield STaR en banda [15%,65%] (fuera, ABORTA)",
               "gate_experto": "solo G2R (fleet: el router no lo activa en G1/G3/G5)"},
           "env": {}, "suites_hash_ok": None, "star": {}, "train": {},
           "evals": {}, "veredictos": {}, "experto": None}


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
    nombre = "g2_razonamiento.jsonl"   # la unica suite que usa este kernel
    meta = frozen[nombre]
    path = _find(nombre)
    return hashlib.sha256(open(path, "rb").read()).hexdigest() == meta["sha256"]


# ------------------------------------------- generador programatico (D4 src)
# Plantillas ORIGINALES (regla 5 del SPEC: nada de GSM8K/MMLU). Cada problema
# lleva su oracle POR CONSTRUCCION. 6 familias numericas + 2 logicas, es+en.
_NOMBRES = ["Lucía", "Mateo", "Sofía", "Tomás", "Valentina", "Bruno", "Camila",
            "Diego", "Elena", "Franco", "Irene", "Julián", "Karen", "Leo",
            "Marta", "Nico", "Olivia", "Pablo", "Rocío", "Simón"]
_COSAS = [("libros", "books"), ("tornillos", "screws"), ("caramelos", "candies"),
          ("botellas", "bottles"), ("semillas", "seeds"), ("ladrillos", "bricks"),
          ("monedas", "coins"), ("clavos", "nails"), ("globos", "balloons"),
          ("tazas", "cups")]


def _gen_problemas(rng, n):
    """[{prompt, oracle, familia, idioma}] con respuesta por construccion.

    V2 DIFICIL: cada problema encadena 2-3 operaciones y lleva un numero
    DISTRACTOR irrelevante en el enunciado (la falla tipica del 3B es usar
    todos los numeros que ve). Objetivo: base acc 30-60% (banda de senal STaR).
    """
    out = []
    while len(out) < n:
        familia = rng.randrange(8)
        es = rng.random() < 0.5
        nom = rng.choice(_NOMBRES)
        nom2 = rng.choice([x for x in _NOMBRES if x != nom])
        cosa_es, cosa_en = rng.choice(_COSAS)
        dx = rng.randint(3, 90)   # distractor
        if familia == 0:   # inventario encadenado: S - a + 2a - b
            s0, a, b = rng.randint(80, 400), rng.randint(15, 60), rng.randint(20, 70)
            ans = s0 - a + 2 * a - b
            p_ = (f"Un deposito guarda {s0} {cosa_es} y tiene {dx} estantes vacios. "
                  f"El lunes salen {a} {cosa_es}; el martes entra el DOBLE de lo que "
                  f"salio el lunes; el miercoles salen {b}. "
                  f"Cuantos {cosa_es} quedan al final del miercoles?") if es else (
                  f"A warehouse stores {s0} {cosa_en} and has {dx} empty shelves. "
                  f"On Monday {a} {cosa_en} leave; on Tuesday TWICE what left on "
                  f"Monday comes in; on Wednesday {b} leave. "
                  f"How many {cosa_en} are left at the end of Wednesday?")
            oracle = {"number": ans}
        elif familia == 1:   # vuelto: B - n*p (distractor: plata del hermano)
            n_, pr = rng.randint(3, 9), rng.randint(12, 45)
            billete = ((n_ * pr) // 100 + rng.randint(1, 3)) * 100
            ans = billete - n_ * pr
            p_ = (f"{nom} compra {n_} {cosa_es} a {pr} pesos cada uno. Su hermano "
                  f"tiene {dx} pesos. {nom} paga con un billete de {billete}. "
                  f"Cuanto recibe de vuelto?") if es else (
                  f"{nom} buys {n_} {cosa_en} at {pr} dollars each. Their brother "
                  f"has {dx} dollars. {nom} pays with a {billete} bill. "
                  f"How much change do they get?")
            oracle = {"number": ans}
        elif familia == 2:   # descuento + segundo articulo sin descuento
            d = rng.choice([10, 20, 25, 50])
            p1 = rng.randint(4, 30) * 100
            p2 = rng.randint(1, 15) * 10
            ans = p1 - p1 * d // 100 + p2
            p_ = (f"Una campera cuesta {p1} pesos con {d}% de descuento; un gorro "
                  f"cuesta {p2} pesos sin descuento. {nom} tiene ahorrados {dx * 100} "
                  f"pesos. Cuanto paga en total por la campera y el gorro?") if es else (
                  f"A jacket costs {p1} dollars with a {d}% discount; a hat costs "
                  f"{p2} dollars with no discount. {nom} has {dx * 100} saved. "
                  f"How much do they pay in total for the jacket and the hat?")
            oracle = {"number": ans}
        elif familia == 3:   # tres tramos + distractor consumo
            v1, t1 = rng.randint(40, 90), rng.randint(2, 4)
            v2, t2 = rng.randint(50, 100), rng.randint(1, 3)
            v3, t3 = rng.randint(30, 70), rng.randint(2, 5)
            ans = v1 * t1 + v2 * t2 + v3 * t3
            p_ = (f"Un camion que consume {dx} litros por dia viaja {t1} horas a "
                  f"{v1} km/h, luego {t2} horas a {v2} km/h y por ultimo {t3} horas "
                  f"a {v3} km/h. Cuantos kilometros recorre en total?") if es else (
                  f"A truck that burns {dx} liters per day drives {t1} hours at "
                  f"{v1} km/h, then {t2} hours at {v2} km/h, and finally {t3} hours "
                  f"at {v3} km/h. How many kilometers does it travel in total?")
            oracle = {"number": ans}
        elif familia == 4:   # edades: hace n anios A tenia x; B hoy triple de A hoy
            x, na, m = rng.randint(5, 18), rng.randint(2, 8), rng.randint(3, 9)
            a_hoy = x + na
            ans = (a_hoy + m) + (3 * a_hoy + m)
            p_ = (f"Hace {na} anios {nom} tenia {x} anios. Hoy {nom2} tiene el "
                  f"TRIPLE de la edad actual de {nom}. Dentro de {m} anios, "
                  f"cuanto sumaran sus edades?") if es else (
                  f"{na} years ago {nom} was {x} years old. Today {nom2} is THREE "
                  f"times {nom}'s current age. In {m} years, what will their ages "
                  f"add up to?")
            oracle = {"number": ans}
        elif familia == 5:   # division con resto (no divisible garantizado)
            k = rng.randint(3, 9)
            t = k * rng.randint(8, 40) + rng.randint(1, k - 1)
            ans = t % k
            p_ = (f"{nom} tiene {t} {cosa_es} y {dx} cajas viejas. Reparte los "
                  f"{cosa_es} en partes iguales entre {k} amigos. "
                  f"Cuantos {cosa_es} le sobran?") if es else (
                  f"{nom} has {t} {cosa_en} and {dx} old boxes. They split the "
                  f"{cosa_en} equally among {k} friends. "
                  f"How many {cosa_en} are left over?")
            oracle = {"number": ans}
        elif familia == 6:   # orden 5 entidades, pregunta por el SEGUNDO
            noms = rng.sample(_NOMBRES, 5)
            orden = list(noms)
            rng.shuffle(orden)   # orden[0] < ... < orden[4]
            rels = [(orden[i + 1], orden[i]) for i in range(4)]
            rng.shuffle(rels)
            frases = ([f"{a} es mas alta/o que {b}" for a, b in rels] if es
                      else [f"{a} is taller than {b}" for a, b in rels])
            ans_nom = orden[3]   # el SEGUNDO mas alto
            p_ = ("; ".join(frases) + (". Quien es la SEGUNDA persona mas alta?"
                                       if es else ". Who is the SECOND tallest person?"))
            # el mas alto NO debe aparecer en la respuesta (error tipico)
            oracle = {"must_any": [ans_nom], "not_any": [orden[4]]}
        else:              # deduccion negativa: que color NO puede ser
            colores = [("negro", "black"), ("blanco", "white"),
                       ("gris", "gray"), ("marron", "brown")]
            rng.shuffle(colores)
            (proh_es, proh_en) = colores[0]
            p_ = (f"En el edificio de {nom} viven {dx} personas. Ningun gato del "
                  f"edificio es {proh_es}. Miso es un gato del edificio. "
                  f"De que color es IMPOSIBLE que sea Miso?") if es else (
                  f"{dx} people live in {nom}'s building. No cat in the building "
                  f"is {proh_en}. Miso is a cat in the building. "
                  f"What color is it IMPOSSIBLE for Miso to be?")
            oracle = {"must_any": [proh_es if es else proh_en]}
        out.append({"prompt": p_, "oracle": oracle, "familia": familia,
                    "idioma": "es" if es else "en"})
    return out


# ------------------------------------------------- train unsloth (E-GROK)
UNSLOTH_TRAIN = r'''
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260708; LR = 3e-4; SEQ = 1024; WARMUP = 0.10
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
total = len(lotes)   # 1 EPOCH (receta E-GROK validada en E2-FINAL-v2)
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
    probe = os.path.join(OUT, "unsloth_train_erzn2.py")
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
    import torch as _t
    with _t.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return [tokenizer.decode(out[i][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True) for i in range(len(items))]


def eval_g2r(model, tokenizer, items, etiqueta):
    binarios = {}
    for i in range(0, len(items), 8):
        chunk = items[i:i + 8]
        outs = genera_batch(model, tokenizer,
                            [(it["prompt"], it["idioma"]) for it in chunk],
                            max(it["max_new_tokens"] for it in chunk))
        for it, o in zip(chunk, outs):
            binarios[it["id"]] = bool(oracle_pass(o, it["oracle"]))
    acc = sum(binarios.values()) / len(binarios)
    print(f"  [{etiqueta}] g2r: {acc:.1%}", flush=True)
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
    RESULTS["suites_hash_ok"] = verifica_suites()
    print("SUITE G2R HASH OK:", RESULTS["suites_hash_ok"], flush=True)
    dump()
    if not RESULTS["suites_hash_ok"]:
        print("ABORT: suite alterada", flush=True)
        return

    with open(os.path.join(OUT, "emix_shared.py"), "w") as f:
        f.write(EMIX_SHARED)

    model_dir = _find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    with open(_find("g2_razonamiento.jsonl"), encoding="utf-8") as f:
        g2r = [json.loads(l) for l in f if l.strip()]

    # ── generar problemas + descontaminar contra la suite ──
    rng = random.Random(SEED)
    problemas = _gen_problemas(rng, N_PROBLEMAS)
    suite_folded = [fold(it["prompt"]) for it in g2r]
    limpios = []
    colisiones = 0
    for pb in problemas:
        pf = fold(pb["prompt"])
        if any(pf in sf or sf in pf for sf in suite_folded):
            colisiones += 1
            continue
        limpios.append(pb)
    RESULTS["star"]["generados"] = len(problemas)
    RESULTS["star"]["colisiones_suite"] = colisiones
    print(f"problemas: {len(limpios)} limpios ({colisiones} colisiones descartadas)", flush=True)
    dump()

    # ── STaR: el base genera CoT; se conserva solo lo CORRECTO ──
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                             bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    base.eval()

    HINT_ES = " Pensá paso a paso y terminá con la respuesta."
    HINT_EN = " Think step by step and end with the answer."
    pares = []
    t0 = time.time()
    for i in range(0, len(limpios), 8):
        chunk = limpios[i:i + 8]
        prompts_gen = [(pb["prompt"] + (HINT_ES if pb["idioma"] == "es" else HINT_EN),
                        pb["idioma"]) for pb in chunk]
        outs = genera_batch(base, tokenizer, prompts_gen, 280)
        for pb, o in zip(chunk, outs):
            o = o.strip()
            if o and oracle_pass(o, pb["oracle"]) and len(o) > 30:
                # train = problema PELADO -> CoT correcto (STaR clasico)
                pares.append({"prompt": pb["prompt"], "completion": o})
        if i % 200 == 0:
            print(f"  star {i}/{len(limpios)} pares={len(pares)} "
                  f"({(time.time()-t0)/60:.0f} min)", flush=True)
            RESULTS["star"]["pares"] = len(pares)
            dump()
    yield_pct = len(pares) / max(1, len(limpios))
    RESULTS["star"].update({"pares": len(pares), "yield": round(yield_pct, 3),
                            "wall_min": round((time.time() - t0) / 60, 1)})
    print("STAR:", json.dumps(RESULTS["star"]), flush=True)
    dump()

    if not (0.15 <= yield_pct <= 0.65):
        motivo = ("demasiado dificil, no hay cadenas que destilar" if yield_pct < 0.15
                  else "demasiado facil, el modelo ya lo sabe (leccion v1)")
        RESULTS["experto"] = {"P-RZN2-2": [round(yield_pct, 3), False],
                              "veredicto": f"ABORTADO: yield fuera de banda ({motivo})"}
        dump()
        print("ABORT P-RZN-2:", json.dumps(RESULTS["experto"]), flush=True)
        return

    # ── eval base en G2R (baseline pareado) ──
    print("== eval base g2r ==", flush=True)
    base_bin = eval_g2r(base, tokenizer, g2r, "base")
    RESULTS["evals"]["base"] = {"g2r": base_bin}
    dump()
    del base
    gc.collect()
    torch.cuda.empty_cache()

    # D4 reutilizable
    with open(os.path.join(OUT, "d4_star.jsonl"), "w", encoding="utf-8") as f:
        for r in pares:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── train: experto puro D4, receta E-GROK ──
    def escribe_tok(pares_, path):
        ej = []
        for r in pares_:
            pre = f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n"
            full = pre + f"{r['completion']}<|im_end|>"
            ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
            ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
            ej.append({"ids": ids_full, "prompt_len": len(ids_pre)})
        with open(path, "w", encoding="utf-8") as f:
            for e in ej:
                f.write(json.dumps(e) + "\n")

    escribe_tok(pares, f"{OUT}/tok_d4.jsonl")
    print("== TRAIN E-RZN (D4 puro, 1 epoch, lr 3e-4 + warmup 10%) ==", flush=True)
    RESULTS["train"] = entrena_subproceso("cognia3b_rzn2", model_dir, f"{OUT}/tok_d4.jsonl")
    dump()

    # ── eval adapter en G2R ──
    from peft import PeftModel
    model_f = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map={"": 0},
        attn_implementation="sdpa", trust_remote_code=True)
    pm = PeftModel.from_pretrained(model_f, f"{OUT}/adapters/cognia3b_rzn2")
    pm.eval()
    print("== eval experto g2r ==", flush=True)
    rzn_bin = eval_g2r(pm, tokenizer, g2r, "cognia3b_rzn2")
    RESULTS["evals"]["cognia3b_rzn2"] = {"g2r": rzn_bin}

    n01 = sum(1 for k in base_bin if not base_bin[k] and rzn_bin[k])
    n10 = sum(1 for k in base_bin if base_bin[k] and not rzn_bin[k])
    acc_b = sum(base_bin.values()) / len(base_bin)
    acc_r = sum(rzn_bin.values()) / len(rzn_bin)
    p = mcnemar_p(n01, n10)
    RESULTS["veredictos"]["g2r"] = {"acc_base": round(acc_b, 3), "acc_experto": round(acc_r, 3),
                                    "delta_pp": round((acc_r - acc_b) * 100, 1),
                                    "n01": n01, "n10": n10, "p": round(p, 4)}
    RESULTS["experto"] = {
        "P-RZN2-1": [round((acc_r - acc_b) * 100, 1),
                     (acc_r - acc_b) >= 0.10 and p < 0.05 and n01 > n10],
        "P-RZN2-2": [RESULTS["star"]["yield"], True],
        "APTO_FLEET": (acc_r - acc_b) >= 0.10 and p < 0.05 and n01 > n10}
    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E-RZN DONE en", RESULTS["wall_total_min"], "min ->",
          json.dumps(RESULTS["experto"]), flush=True)


if __name__ == "__main__":
    main()
