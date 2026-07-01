"""
QLoRA kernel para Kaggle — FINE-TUNE de tool-use (formato ACCION de Cognia).

Diferencias clave vs train_qlora_kaggle.py (destilación de conocimiento):
  1. Formato del deploy REAL: ChatML con SYSTEM = COGNIA_SYSTEM_PROMPT +
     user(prompt del agent loop) + assistant(linea ACCION). Evita el mismatch
     train/inference (el deploy siempre antepone ese system prompt).
  2. COMPLETION-ONLY LOSS MASKING: la loss se computa SOLO sobre la completion
     (la linea ACCION), NO sobre el prompt. Critico aca: el TOOLS_DOC (~24
     herramientas) domina los tokens del prompt y se repite en cada ejemplo;
     entrenar sobre el enseñaria a REGURGITAR el catalogo en vez de a decidir.
  3. Eval de TOOL-USE: mide 'valid_single_accion' (¿emite UNA linea ACCION con
     una herramienta valida?) sobre prompts held-out, base vs base+adapter.

Base congelado Qwen2.5-Coder-3B-Instruct (4-bit NF4, o fp16 si bnb no queda
usable). Solo se crea el adapter. Deja final_adapter/ + eval_tooluse.json en
/kaggle/working.
"""
import glob
import json
import os
import re
import subprocess
import sys

import torch
from datasets import Dataset

# System prompt EXACTO del deploy (shattering/model_constants.py:COGNIA_SYSTEM_PROMPT).
# Hardcodeado porque el kernel de Kaggle no puede importar el paquete Cognia.
COGNIA_SYSTEM_PROMPT = (
    "Eres Cognia, un sistema de inteligencia artificial cognitiva local, con "
    "memoria episodica y grafo de conocimiento. Fuiste creado por Tomas Montes; "
    "tu creador es Tomas Montes (no Anthropic ni Alibaba). Responde en espanol "
    "de forma clara y directa."
)

# Catalogo de herramientas validas (cognia/agent/tools.py) + responder. Para el
# check de validez de la eval.
VALID_TOOLS = {
    "leer_archivo", "escribir_archivo", "apendar_archivo", "copiar_archivo",
    "listar", "arbol", "contar_lineas", "buscar", "ejecutar", "tests",
    "py_validar", "json_validar", "git_estado", "git_diff", "git_log",
    "calcular", "fecha", "http_get", "recordar", "memorizar", "kg_buscar",
    "kg_agregar", "anotar", "notas", "resumir", "responder",
}

OUT = "/kaggle/working"
# 1600: el prompt de tool-use = TOOLS_DOC (~24 lineas) + contexto (history[-6:])
# + 'Siguiente ACCION'. Medido ~1000-1200 tokens de prefijo; 1600 deja holgura
# para la completion (linea ACCION, o contenido multi-linea de escribir_archivo).
MAX_LEN = 1600
CPU_MAX_STEPS = 120


def _find_model_dir(prefer_small: bool) -> str:
    candidates = [os.path.dirname(p) for p in
                  glob.glob("/kaggle/input/**/config.json", recursive=True)]
    if not candidates:
        raise FileNotFoundError(
            "No se encontro modelo bajo /kaggle/input. Adjuntar "
            "qwen-lm/qwen2.5-coder/transformers/{3b,0.5b}-instruct.")
    key = "0.5b" if prefer_small else "3b"
    match = [d for d in candidates if key in d.lower()]
    pool = match or candidates
    pool.sort(key=lambda p: len(p))
    return pool[0]


def _ensure_bitsandbytes() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print("[bnb] pip -U bitsandbytes rc=%d (%s)" %
              (r.returncode, tail[-1] if tail else ""), flush=True)
    except Exception as e:
        print("[bnb] pip fallo: %s" % e, flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401
        ver = importlib.metadata.version("bitsandbytes")
        ok = tuple(int(x) for x in ver.split(".")[:3]) >= (0, 46, 1)
        print("[bnb] version %s -> %s" % (ver, "OK" if ok else "insuficiente"), flush=True)
        return ok
    except Exception as e:
        print("[bnb] import fallo: %s" % e, flush=True)
        return False


def _find_one(patterns) -> str:
    for pat in patterns:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    return ""


def _load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


HAS_GPU = torch.cuda.is_available()
MODEL = _find_model_dir(prefer_small=not HAS_GPU)
TRAIN_PATH = _find_one(["/kaggle/input/**/*train*.jsonl", "/kaggle/input/**/*.jsonl"])
EVAL_PATH = _find_one(["/kaggle/input/**/*eval*.jsonl"])


def _chatml_prefix(prompt: str) -> str:
    return (f"<|im_start|>system\n{COGNIA_SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def eval_tooluse(model, tokenizer, prompts, label: str) -> dict:
    """Mide, greedy, la fraccion de prompts held-out donde el modelo emite UNA
    sola linea ACCION con una herramienta valida (el skill que entrenamos)."""
    model.eval()
    ok = 0
    details = []
    for e in prompts:
        text = _chatml_prefix(e["prompt"])
        inputs = tokenizer(text, return_tensors="pt", truncation=True,
                           max_length=MAX_LEN).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=64, do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
        resp = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True).strip()
        first = resp.splitlines()[0] if resp else ""
        m = re.match(r"ACCI[OÓ]N:\s*(\w+)", first, re.IGNORECASE)
        valid = bool(m) and m.group(1).lower() in VALID_TOOLS
        single = len(re.findall(r"ACCI[OÓ]N:", resp, re.IGNORECASE)) == 1
        good = bool(valid and single)
        ok += good
        details.append({"task_id": e.get("task_id"), "valid": valid,
                        "single": single, "resp": resp[:120]})
    rate = ok / max(1, len(prompts))
    print(f"[eval:{label}] valid_single_accion={rate:.1%} (n={len(prompts)})", flush=True)
    for d in details:
        print(f"   {d['task_id']:<20} valid={d['valid']} single={d['single']} :: {d['resp']!r}", flush=True)
    return {"label": label, "valid_single_accion": rate, "details": details}


def main():
    use_bnb = HAS_GPU and _ensure_bitsandbytes()

    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              DataCollatorForSeq2Seq, Trainer, TrainingArguments)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    mode = ("GPU/4-bit/3B" if (HAS_GPU and use_bnb)
            else "GPU/fp16/3B" if HAS_GPU else "CPU/fp32/0.5B")
    print(f"MODE: {mode}")
    print("DEVICE:", torch.cuda.get_device_name(0) if HAS_GPU else "CPU")
    print("MODEL DIR:", MODEL)
    print("TRAIN:", TRAIN_PATH, "| EVAL:", EVAL_PATH)

    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if HAS_GPU and use_bnb:
        from transformers import BitsAndBytesConfig
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                                 bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.float16)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, quantization_config=bnb, device_map="auto", trust_remote_code=True)
        model = prepare_model_for_kbit_training(model)
    elif HAS_GPU:
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, torch_dtype=torch.float16, device_map="auto", trust_remote_code=True)
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    else:
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, torch_dtype=torch.float32, trust_remote_code=True)

    # Prompts held-out para eval (si no vino el archivo, se salta la eval).
    eval_prompts = _load_jsonl(EVAL_PATH) if EVAL_PATH else []
    eval_base = eval_tooluse(model, tokenizer, eval_prompts, "base") if eval_prompts else None

    # ── Dataset con COMPLETION-ONLY MASKING ──
    records = _load_jsonl(TRAIN_PATH)
    print(f"Dataset: {len(records)} pares")

    def tokenize(r):
        prefix = _chatml_prefix(r["prompt"])
        completion = r["completion"] + "<|im_end|>"
        p_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
        c_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
        input_ids = (p_ids + c_ids)[:MAX_LEN]
        labels = ([-100] * len(p_ids) + c_ids)[:MAX_LEN]
        return {"input_ids": input_ids,
                "attention_mask": [1] * len(input_ids),
                "labels": labels}

    ds = Dataset.from_list([tokenize(r) for r in records])
    # Descarta ejemplos donde el prefijo comio todo el presupuesto (0 tokens de
    # completion sin enmascarar -> sin señal). Raro con MAX_LEN 1600.
    n0 = len(ds)
    ds = ds.filter(lambda ex: any(l != -100 for l in ex["labels"]))
    if len(ds) < n0:
        print(f"[data] descartados {n0 - len(ds)} ejemplos sin completion visible")

    cfg = LoraConfig(r=8, lora_alpha=16,
                     target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
                     lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.print_trainable_parameters()

    # Mas epocas que la destilacion (3): el dataset de tool-use es chico y el
    # objetivo (compliance de formato + seleccion de herramienta) es de baja
    # entropia -> converge rapido sin sobreajustar el contenido.
    args = TrainingArguments(
        output_dir=f"{OUT}/checkpoints",
        num_train_epochs=3 if HAS_GPU else 1,
        max_steps=-1 if HAS_GPU else CPU_MAX_STEPS,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8 if HAS_GPU else 2,
        learning_rate=2e-4, fp16=HAS_GPU, bf16=False,
        logging_steps=5, save_strategy="no", warmup_ratio=0.05,
        lr_scheduler_type="cosine", report_to="none",
    )
    collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True,
                                      label_pad_token_id=-100)
    trainer = Trainer(model=model, args=args, train_dataset=ds, data_collator=collator)
    print("Training ...", flush=True)
    trainer.train()

    adapter_path = f"{OUT}/final_adapter"
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"Adapter saved: {adapter_path}", flush=True)

    eval_adapter = eval_tooluse(model, tokenizer, eval_prompts, "base+adapter") if eval_prompts else None

    compare = {"mode": mode, "model_dir": MODEL, "train_pairs": len(records),
               "base": eval_base, "adapter": eval_adapter}
    if eval_base and eval_adapter:
        compare["delta_valid_single_accion"] = (
            eval_adapter["valid_single_accion"] - eval_base["valid_single_accion"])
        print(f"\nDELTA valid_single_accion: {compare['delta_valid_single_accion']:+.1%}", flush=True)
    with open(f"{OUT}/eval_tooluse.json", "w", encoding="utf-8") as f:
        json.dump(compare, f, indent=2, ensure_ascii=False)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
