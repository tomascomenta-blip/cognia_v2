# -*- coding: utf-8 -*-
"""
E1b - RE-EVAL de los brazos de E1 con el instrumento CORREGIDO.

Fix del confound de E1: la eval llamaba apply_chat_template SIN system y el
template de Qwen2.5 inyecta el default "You are Qwen, created by Alibaba
Cloud" -> el oraculo G3 (not_any qwen/alibaba) quedaba amanado contra
cualquier adapter. E1b evalua con SYSTEM NEUTRO pareado por idioma (mismo
para base y brazos: la comparacion McNemar sigue siendo justa):
  es: "Eres un asistente util."   en: "You are a helpful assistant."

NO re-entrena: monta el output del kernel E1 (adapters/) via kernel_sources
y re-corre G1/G3/G5 + tooluse sobre base + 5 adapters. ~30-40 min.
Salida: /kaggle/working/e1b_results.json (incremental).
"""
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
OUT = "/kaggle/working"
RESULTS_PATH = os.path.join(OUT, "e1b_results.json")
SYSTEM_ES = "Eres un asistente útil."
SYSTEM_EN = "You are a helpful assistant."

RESULTS = {"exp": "E1b-eval-system-neutro",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "system_prompts": {"es": SYSTEM_ES, "en": SYSTEM_EN},
           "env": {}, "suites_hash_ok": None, "evals": {}, "veredictos": {}}


def dump():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, ensure_ascii=True)


def sh(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    print(f"[sh] {' '.join(cmd[:5])}... rc={r.returncode}", flush=True)
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
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import transformers
    import peft as peft_mod

    RESULTS["env"] = {"gpu": torch.cuda.get_device_name(0),
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

    # adapters del kernel E1 montado (kernel_sources)
    adapters = sorted({os.path.dirname(p) for p in
                       glob.glob("/kaggle/input/**/adapters/*/adapter_config.json",
                                 recursive=True)})
    print("adapters montados:", [os.path.basename(a) for a in adapters], flush=True)
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

    RESULTS["wall_total_min"] = round((time.time() - T0) / 60, 1)
    dump()
    print("E1b DONE en", RESULTS["wall_total_min"], "min", flush=True)


if __name__ == "__main__":
    main()
