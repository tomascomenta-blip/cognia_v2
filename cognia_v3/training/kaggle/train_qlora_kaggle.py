"""
QLoRA training kernel para Kaggle (GPU T4/P100, gratis, sin tarjeta).

Corre COMO KERNEL DE KAGGLE (script kernel):
  - enable_internet: TRUE — el image de Kaggle NO trae bitsandbytes>=0.46.1
    (run 1 del datagen murio en el load 4-bit, fix 8b67ac3) y el kernel hace
    pip install -U bitsandbytes guardado; si bnb sigue inusable cae a fp16.
  - modelo base montado como model source: Kaggle Models
    qwen-lm/qwen2.5-coder/transformers/3b-instruct → /kaggle/input/...
  - dataset privado adjunto: cognia-dataset (un JSONL {prompt, completion};
    campos extra como `source` se ignoran).

Hace 3 cosas y deja todo en /kaggle/working (descargable por CLI):
  1. Entrena un adapter LoRA sobre Qwen2.5-Coder-3B-Instruct CONGELADO (4-bit,
     o fp16 si bitsandbytes no quedo usable).
  2. Evalúa base vs base+adapter con el baseline de 10 preguntas de Cognia.
  3. Guarda final_adapter/ + eval_compare.json.

El modelo base NUNCA se modifica: solo se crea el adapter.
"""
import glob
import json
import os
import subprocess
import sys

import torch
from datasets import Dataset

# transformers/peft se importan DENTRO de main(), DESPUES del pip upgrade de
# bitsandbytes: transformers cachea la deteccion de bnb al primer import
# (leccion del fix 8b67ac3 en datagen_kernel).


def _find_model_dir(prefer_small: bool) -> str:
    """
    Ruta de un modelo Qwen montado bajo /kaggle/input (config.json presente).
    Con GPU preferimos el 3B; en CPU el 0.5B (entrenable sin 4-bit).
    """
    candidates = [d for d in (os.path.dirname(p) for p in
                  glob.glob("/kaggle/input/**/config.json", recursive=True))]
    if not candidates:
        raise FileNotFoundError(
            "No se encontró ningún modelo montado bajo /kaggle/input. "
            "Adjuntar qwen-lm/qwen2.5-coder/transformers/{3b,0.5b}-instruct.")
    key = "0.5b" if prefer_small else "3b"
    match = [d for d in candidates if key in d.lower()]
    pool = match or candidates
    pool.sort(key=lambda p: len(p))
    return pool[0]


def _ensure_bitsandbytes() -> bool:
    """El image de Kaggle trae bitsandbytes viejo y el load 4-bit muere:
    transformers exige bitsandbytes>=0.46.1 (run 1 del datagen, 2026-06-11).
    Intento guardado de upgrade por pip (necesita enable_internet=true) y
    chequeo de version; si devuelve False, main() carga el 3B en fp16.
    Misma cascada que datagen_kernel._ensure_bitsandbytes (fix 8b67ac3)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U",
                            "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print("[bnb] pip install -U bitsandbytes -> rc=%d (%s)"
              % (r.returncode, tail[-1] if tail else "sin output"), flush=True)
    except Exception as e:
        print("[bnb] pip install fallo: %s" % e, flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401  (importable = sus libs CUDA cargan)
        ver = importlib.metadata.version("bitsandbytes")
        ok = tuple(int(x) for x in ver.split(".")[:3]) >= (0, 46, 1)
        print("[bnb] version instalada: %s -> %s"
              % (ver, "OK" if ok else "insuficiente (<0.46.1)"), flush=True)
        return ok
    except Exception as e:
        print("[bnb] import fallo: %s" % e, flush=True)
        return False


def _find_dataset() -> str:
    """Ruta del cognia_dataset.jsonl montado (el ZIP se extrae con estructura variable)."""
    hits = glob.glob("/kaggle/input/**/cognia_dataset.jsonl", recursive=True)
    if not hits:
        hits = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
    if not hits:
        raise FileNotFoundError(
            "No se encontró cognia_dataset.jsonl bajo /kaggle/input. "
            f"Contenido: {glob.glob('/kaggle/input/*')}")
    return hits[0]


HAS_GPU = torch.cuda.is_available()
MODEL = _find_model_dir(prefer_small=not HAS_GPU)
DATASET_PATH = _find_dataset()
OUT = "/kaggle/working"
# 1024: el codigo sintetico (syn_long: clases de 40-80 lineas + prompt) excede
# largo los 512 tokens que alcanzaban para los kg_triples — truncar a 512
# cortaria la mayoria de las completions a mitad de funcion. Presupuesto de
# memoria T4 16GB con el 3B en 4-bit (~2GB de pesos): duplicar seq_len duplica
# la memoria de activaciones, asi que el batch GPU baja 4->2 y grad_accum sube
# 4->8 (batch efectivo 16 igual; activaciones ~constantes vs 512x4).
MAX_LEN = 1024
# En CPU acotamos los pasos para garantizar terminación dentro del límite de Kaggle.
CPU_MAX_STEPS = 150

BASELINE_QUESTIONS = [
    {"id": "R1", "prompt": "If a dog is a mammal and all mammals are warm-blooded, is a dog warm-blooded? Answer yes or no and explain.", "keywords": ["yes", "warm"]},
    {"id": "R2", "prompt": "If it rains the ground gets wet. The ground is wet. Did it necessarily rain?", "keywords": ["not necessarily", "maybe", "could"]},
    {"id": "F1", "prompt": "What causes rain?", "keywords": ["water", "evaporation", "cloud"]},
    {"id": "F2", "prompt": "What is the capital of France?", "keywords": ["paris"]},
    {"id": "F3", "prompt": "What is machine learning?", "keywords": ["data", "model", "learn", "pattern"]},
    {"id": "M1", "prompt": "What is 15% of 200?", "keywords": ["30"]},
    {"id": "C1", "prompt": "Write a Python function that reverses a string.", "keywords": ["def", "return"]},
    {"id": "C2", "prompt": "In Python, what is the difference between a list and a tuple?", "keywords": ["mutable", "immutable"]},
    {"id": "C3", "prompt": "Write Python code to iterate a list printing index and value.", "keywords": ["enumerate", "for"]},
    {"id": "C4", "prompt": "Name 3 common sorting algorithms.", "keywords": ["sort"]},
]


def fold(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


def score(resp: str, kws: list) -> float:
    r = fold(resp)
    return sum(1 for k in kws if fold(k) in r) / len(kws)


def run_eval(model, tokenizer, label: str) -> dict:
    model.eval()
    results = []
    for q in BASELINE_QUESTIONS:
        msgs = [{"role": "user", "content": q["prompt"]}]
        text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=200, do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
        resp = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        results.append({"id": q["id"], "score": score(resp, q["keywords"]),
                        "response": resp[:200]})
    avg = sum(r["score"] for r in results) / len(results)
    print(f"[eval:{label}] avg={avg:.1%}  " +
          " ".join(f"{r['id']}={r['score']:.0%}" for r in results))
    return {"label": label, "avg_score": avg, "results": results}


def main():
    # pip upgrade de bnb ANTES de importar transformers: transformers cachea
    # la deteccion de bitsandbytes al primer import (fix 8b67ac3).
    use_bnb = HAS_GPU and _ensure_bitsandbytes()

    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              DataCollatorForLanguageModeling, Trainer,
                              TrainingArguments)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    if HAS_GPU:
        mode = "GPU/4-bit/3B" if use_bnb else "GPU/fp16-fallback/3B"
    else:
        mode = "CPU/fp32/0.5B"
    print(f"MODE: {mode}")
    print("DEVICE:", torch.cuda.get_device_name(0) if HAS_GPU else "CPU")
    print("MODEL DIR:", MODEL)

    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if HAS_GPU and use_bnb:
        from transformers import BitsAndBytesConfig
        # T4 es Turing: sin bf16 -> compute dtype float16
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                                 bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.float16)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, quantization_config=bnb, device_map="auto", trust_remote_code=True)
        model = prepare_model_for_kbit_training(model)
    elif HAS_GPU:
        # FALLBACK sin bnb usable: 3B en fp16 (~6GB) entra en una T4 de 16GB
        # con LoRA encima igual que en 4-bit. Gradient checkpointing manual
        # (prepare_model_for_kbit_training es solo para modelos cuantizados).
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, torch_dtype=torch.float16, device_map="auto",
            trust_remote_code=True)
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    else:
        # CPU: sin bitsandbytes (4-bit necesita CUDA). 0.5B en fp32, LoRA igual.
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, torch_dtype=torch.float32, trust_remote_code=True)

    # ── Eval del modelo BASE (antes de tocar nada) ──
    eval_base = run_eval(model, tokenizer, "base")

    # ── Dataset ──
    with open(DATASET_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    print(f"Dataset: {len(records)} pares")

    def fmt(r):
        # Solo {prompt, completion}: campos extra del datagen (p.ej.
        # source: syn_long|syn_spec) se ignoran — NO hay filtro por source,
        # se entrena con todos los pares del JSONL.
        return (f"<|im_start|>user\n{r['prompt']}<|im_end|>\n"
                f"<|im_start|>assistant\n{r['completion']}<|im_end|>")

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=MAX_LEN)

    ds = Dataset.from_dict({"text": [fmt(r) for r in records]})
    ds = ds.map(tokenize, batched=True, remove_columns=["text"])
    split = ds.train_test_split(test_size=min(0.05, 100 / len(ds)), seed=42)

    # ── LoRA ──
    cfg = LoraConfig(r=8, lora_alpha=16,
                     target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
                     lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, cfg)
    # LoRA en fp32: con la base fp16 (fallback sin bnb) el GradScaler rechaza
    # params entrenables en half ("Attempting to unscale FP16 gradients").
    # En el camino 4-bit prepare_model_for_kbit_training ya lo dejo asi (no-op).
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir=f"{OUT}/checkpoints",
        num_train_epochs=1,
        max_steps=-1 if HAS_GPU else CPU_MAX_STEPS,
        # GPU: batch 2 + accum 8 (no 4+4) para compensar MAX_LEN 512->1024
        # manteniendo batch efectivo 16 y memoria de activaciones ~constante.
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8 if HAS_GPU else 2,
        learning_rate=2e-4, fp16=HAS_GPU, bf16=False,
        logging_steps=10, save_strategy="no", warmup_ratio=0.05,
        lr_scheduler_type="cosine", report_to="none", eval_strategy="no",
    )
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    trainer = Trainer(model=model, args=args, train_dataset=split["train"],
                      data_collator=collator)
    print("Training ...")
    trainer.train()

    adapter_path = f"{OUT}/final_adapter"
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"Adapter saved: {adapter_path}")

    # ── Eval con adapter ──
    eval_adapter = run_eval(model, tokenizer, "base+cognia_adapter")

    delta = eval_adapter["avg_score"] - eval_base["avg_score"]
    compare = {"mode": mode, "model_dir": MODEL,
               "base": eval_base, "adapter": eval_adapter, "delta": delta}
    with open(f"{OUT}/eval_compare.json", "w", encoding="utf-8") as f:
        json.dump(compare, f, indent=2, ensure_ascii=False)
    print(f"\nDELTA base->adapter: {delta:+.1%}")
    print("DONE")


if __name__ == "__main__":
    main()
