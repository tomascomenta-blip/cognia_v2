"""
Genera un notebook .ipynb AUTONOMO para Google Colab (GPU T4 gratis, sin
tarjeta ni numero — solo cuenta Google).

El dataset cognia (privado, derivado de memoria personal) se EMBEBE comprimido
en el notebook. El .ipynb resultante se sube directo a Colab (no pasa por
GitHub) → el dato personal nunca se publica.

El notebook:
  1. instala transformers/peft/bitsandbytes/accelerate/datasets (Colab tiene internet)
  2. decodifica el dataset embebido
  3. baja Qwen2.5-Coder-3B-Instruct de HF (congelado, 4-bit)
  4. evalua BASE con el baseline de 10 preguntas
  5. entrena adapter LoRA (1 epoch)
  6. evalua BASE+adapter, imprime DELTA, guarda y descarga eval_compare.json + adapter

Uso: python -m cognia_v3.training.colab.make_colab_notebook
"""
import base64
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATASET = REPO / "cognia_v3" / "training" / "cognia_dataset.jsonl"
OUT_IPYNB = HERE / "cognia_qlora_colab.ipynb"

BASELINE = [
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


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": src.splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}


def main():
    blob = base64.b64encode(gzip.compress(DATASET.read_bytes(), 9)).decode()
    baseline_json = json.dumps(BASELINE, ensure_ascii=False)

    setup = (
        "# Cognia QLoRA en Colab — instalar deps (Colab ya trae torch+CUDA)\n"
        "!pip -q install -U transformers peft bitsandbytes accelerate datasets\n"
        "import torch\n"
        "assert torch.cuda.is_available(), 'Runtime > Change runtime type > T4 GPU'\n"
        "print('GPU:', torch.cuda.get_device_name(0))\n"
    )

    data_cell = (
        "# Dataset cognia embebido (privado — no sale del runtime de Colab)\n"
        "import base64, gzip, json\n"
        f'_BLOB = "{blob}"\n'
        "_raw = gzip.decompress(base64.b64decode(_BLOB)).decode('utf-8')\n"
        "records = [json.loads(l) for l in _raw.splitlines() if l.strip()]\n"
        "print('pares:', len(records))\n"
        f"BASELINE = {baseline_json}\n"
    )

    train = (
        "import json, torch, unicodedata\n"
        "from datasets import Dataset\n"
        "from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,\n"
        "                          DataCollatorForLanguageModeling, Trainer, TrainingArguments)\n"
        "from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training\n"
        "\n"
        "MODEL = 'Qwen/Qwen2.5-Coder-3B-Instruct'\n"
        "MAX_LEN = 512\n"
        "\n"
        "def fold(t):\n"
        "    return ''.join(c for c in unicodedata.normalize('NFKD', t.lower()) if not unicodedata.combining(c))\n"
        "def score(resp, kws):\n"
        "    r = fold(resp); return sum(1 for k in kws if fold(k) in r)/len(kws)\n"
        "\n"
        "tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)\n"
        "if tok.pad_token is None: tok.pad_token = tok.eos_token\n"
        "bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,\n"
        "                         bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16)\n"
        "model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb,\n"
        "                                             device_map='auto', trust_remote_code=True)\n"
        "\n"
        "def run_eval(m, label):\n"
        "    m.eval(); res = []\n"
        "    for q in BASELINE:\n"
        "        msgs = [{'role':'user','content':q['prompt']}]\n"
        "        text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)\n"
        "        inp = tok(text, return_tensors='pt').to(m.device)\n"
        "        with torch.no_grad():\n"
        "            out = m.generate(**inp, max_new_tokens=200, do_sample=False, pad_token_id=tok.eos_token_id)\n"
        "        resp = tok.decode(out[0][inp['input_ids'].shape[1]:], skip_special_tokens=True)\n"
        "        res.append({'id':q['id'],'score':score(resp,q['keywords']),'response':resp[:200]})\n"
        "    avg = sum(r['score'] for r in res)/len(res)\n"
        "    print(f'[eval:{label}] avg={avg:.1%}  ' + ' '.join(f\"{r['id']}={r['score']:.0%}\" for r in res))\n"
        "    return {'label':label,'avg_score':avg,'results':res}\n"
        "\n"
        "eval_base = run_eval(model, 'base')\n"
        "\n"
        "def fmt(r):\n"
        "    return f\"<|im_start|>user\\n{r['prompt']}<|im_end|>\\n<|im_start|>assistant\\n{r['completion']}<|im_end|>\"\n"
        "ds = Dataset.from_dict({'text':[fmt(r) for r in records]})\n"
        "ds = ds.map(lambda b: tok(b['text'], truncation=True, max_length=MAX_LEN), batched=True, remove_columns=['text'])\n"
        "split = ds.train_test_split(test_size=min(0.05, 100/len(ds)), seed=42)\n"
        "\n"
        "model = prepare_model_for_kbit_training(model)\n"
        "cfg = LoraConfig(r=8, lora_alpha=16, target_modules=['q_proj','v_proj','k_proj','o_proj'],\n"
        "                 lora_dropout=0.05, bias='none', task_type='CAUSAL_LM')\n"
        "model = get_peft_model(model, cfg); model.print_trainable_parameters()\n"
        "\n"
        "args = TrainingArguments(output_dir='out', num_train_epochs=1, per_device_train_batch_size=4,\n"
        "    gradient_accumulation_steps=4, learning_rate=2e-4, fp16=True, logging_steps=10,\n"
        "    save_strategy='no', warmup_ratio=0.05, lr_scheduler_type='cosine', report_to='none')\n"
        "trainer = Trainer(model=model, args=args, train_dataset=split['train'],\n"
        "    data_collator=DataCollatorForLanguageModeling(tokenizer=tok, mlm=False))\n"
        "trainer.train()\n"
        "model.save_pretrained('final_adapter'); tok.save_pretrained('final_adapter')\n"
        "\n"
        "eval_adapter = run_eval(model, 'base+cognia_adapter')\n"
        "delta = eval_adapter['avg_score'] - eval_base['avg_score']\n"
        "json.dump({'base':eval_base,'adapter':eval_adapter,'delta':delta}, open('eval_compare.json','w'), indent=2, ensure_ascii=False)\n"
        "print(f'\\n=== DELTA base->adapter: {delta:+.1%} ===')\n"
    )

    download = (
        "# Empaquetar y descargar el adapter + comparacion\n"
        "import shutil\n"
        "shutil.make_archive('cognia_adapter', 'zip', 'final_adapter')\n"
        "try:\n"
        "    from google.colab import files\n"
        "    files.download('eval_compare.json')\n"
        "    files.download('cognia_adapter.zip')\n"
        "except Exception as e:\n"
        "    print('download manual desde el panel Files:', e)\n"
    )

    nb = {
        "cells": [
            md_cell("# Cognia QLoRA — Qwen2.5-Coder-3B en Colab (T4 gratis)\n"
                    "Runtime > Change runtime type > **T4 GPU**, luego Runtime > **Run all**.\n"
                    "El dataset va embebido (privado). Al final descarga el adapter + eval_compare.json."),
            code_cell(setup),
            code_cell(data_cell),
            code_cell(train),
            code_cell(download),
        ],
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "T4", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4, "nbformat_minor": 0,
    }

    OUT_IPYNB.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
    kb = OUT_IPYNB.stat().st_size / 1024
    print(f"Notebook escrito: {OUT_IPYNB} ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
