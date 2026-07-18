"""
expert_forge/lora_trainer.py
============================
Entrenamiento LoRA fp32 sobre CPU para crear expertos Cognia a partir de
un modelo base HF (Qwen2.5-0.5B-Instruct via expert_forge/get_base_model.py).

Patron de entrenamiento: loop manual con AdamW sobre los params entrenables
(como bdraft/train.py), NADA del Trainer de HF. Objetivo: cross-entropy de
LM causal con masking de prompt: los tokens del prompt llevan label -100
(ignore_index), la loss solo se computa sobre los tokens del completion.

Rank adaptativo por RAM disponible (psutil): >16GB -> 16, >8GB -> 8, sino 4.
Targets q_proj/k_proj/v_proj/o_proj con alpha = 2*rank ("no muy grande pero
que se note").
"""

from pathlib import Path

import psutil
import torch
import torch.nn.functional as F
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj"]


def _adaptive_rank() -> int:
    """Rank LoRA segun RAM disponible: >16GB -> 16, >8GB -> 8, sino 4."""
    avail_gb = psutil.virtual_memory().available / (1024 ** 3)
    if avail_gb > 16:
        return 16
    if avail_gb > 8:
        return 8
    return 4


def _build_labels(prompt_ids: list[int], completion_ids: list[int]) -> list[int]:
    """Labels para LM causal con masking de prompt: -100 (ignore_index) en
    cada token del prompt, el id real en cada token del completion."""
    return [-100] * len(prompt_ids) + list(completion_ids)


def _encode_example(tokenizer, prompt: str, completion: str,
                    seq_len: int) -> tuple[list[int], list[int]] | None:
    """Tokeniza un ejemplo {prompt, completion} -> (input_ids, labels)
    truncados a seq_len, con EOS al final del completion. None si tras
    truncar no queda ningun token de completion con label valido."""
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        completion_ids = completion_ids + [tokenizer.eos_token_id]
    input_ids = (prompt_ids + completion_ids)[:seq_len]
    labels = _build_labels(prompt_ids, completion_ids)[:seq_len]
    # El shift causal descarta el primer label: hace falta al menos un label
    # valido en labels[1:] para que el ejemplo aporte loss.
    if all(l == -100 for l in labels[1:]):
        return None
    return input_ids, labels


def _load_base(model_dir: str):
    """Carga el modelo base en float32 CPU. transformers 5.x usa dtype=,
    versiones previas torch_dtype= -> se intentan ambas."""
    try:
        return AutoModelForCausalLM.from_pretrained(model_dir, dtype=torch.float32)
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(model_dir,
                                                    torch_dtype=torch.float32)


def _example_loss(model, input_ids: list[int], labels: list[int]) -> torch.Tensor:
    """Cross-entropy causal (shift de 1) de un ejemplo, ignorando -100.
    Batch de 1: sin padding ni attention_mask que complicar."""
    ids = torch.tensor([input_ids], dtype=torch.long)
    labs = torch.tensor([labels], dtype=torch.long)
    logits = model(input_ids=ids).logits            # [1, T, V]
    shift_logits = logits[:, :-1, :].reshape(-1, logits.shape[-1])
    shift_labels = labs[:, 1:].reshape(-1)
    return F.cross_entropy(shift_logits, shift_labels, ignore_index=-100)


def _dataset_loss(model, encoded: list[tuple[list[int], list[int]]]) -> float:
    """Loss promedio (por ejemplo) sobre todo el dataset, sin gradientes.
    Se usa para initial_loss/final_loss: mas estable que la loss de un step."""
    model.eval()
    total = 0.0
    with torch.no_grad():
        for input_ids, labels in encoded:
            total += _example_loss(model, input_ids, labels).item()
    model.train()
    return total / len(encoded)


def train_lora(model_dir: str, dataset: list[dict], out_dir: str,
               rank: int | None = None, steps: int = 200, lr: float = 2e-4,
               seq_len: int = 512, progress_fn=None) -> dict:
    """Entrena un adapter LoRA fp32 en CPU sobre el modelo base de model_dir.

    dataset: lista de dicts {'prompt': str, 'completion': str}. La loss se
    computa SOLO sobre los tokens del completion (labels -100 en el prompt).
    rank=None -> rank adaptativo por RAM (_adaptive_rank). progress_fn, si se
    pasa, se llama como progress_fn(step, steps, loss) en cada step.

    Devuelve {'final_loss', 'initial_loss', 'steps', 'rank', 'adapter_dir'};
    initial/final son la loss promedio del dataset completo antes y despues
    de entrenar (evaluada sin gradientes).
    """
    if not dataset:
        raise ValueError("dataset vacio: hacen falta ejemplos {prompt, completion}")
    if rank is None:
        rank = _adaptive_rank()

    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = _load_base(model_dir)

    lora_cfg = LoraConfig(r=rank, lora_alpha=2 * rank,
                          target_modules=LORA_TARGETS, lora_dropout=0.0,
                          bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora_cfg)

    encoded = []
    for ex in dataset:
        pair = _encode_example(tokenizer, ex["prompt"], ex["completion"], seq_len)
        if pair is not None:
            encoded.append(pair)
    if not encoded:
        raise ValueError("ningun ejemplo quedo con tokens de completion "
                         "tras truncar a seq_len=%d" % seq_len)

    initial_loss = _dataset_loss(model, encoded)

    # Loop manual AdamW (patron bdraft/train.py): params entrenables solamente
    # (los LoRA A/B; el base queda congelado por peft). Un ejemplo por step,
    # orden barajado por epoca.
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr)
    g = torch.Generator().manual_seed(1234)
    order: list[int] = []
    model.train()
    for step in range(steps):
        if not order:
            order = torch.randperm(len(encoded), generator=g).tolist()
        input_ids, labels = encoded[order.pop()]
        loss = _example_loss(model, input_ids, labels)
        opt.zero_grad()
        loss.backward()
        opt.step()
        if progress_fn is not None:
            progress_fn(step + 1, steps, loss.item())

    final_loss = _dataset_loss(model, encoded)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_path))   # adapter_model.safetensors + config

    return {"final_loss": final_loss, "initial_loss": initial_loss,
            "steps": steps, "rank": rank, "adapter_dir": str(out_path)}


def generate_with_adapter(model_dir: str, adapter_dir: str | None, prompt: str,
                          max_new_tokens: int = 200) -> str:
    """Carga base + adapter LoRA con peft y genera greedy en CPU.
    Con adapter_dir=None genera con el base pelado (para evals A/B).
    Devuelve solo el texto generado (sin el prompt)."""
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    base = _load_base(model_dir)
    model = PeftModel.from_pretrained(base, adapter_dir) if adapter_dir else base
    model.eval()
    ids = tokenizer(prompt, return_tensors="pt")["input_ids"]
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens,
                             do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    return tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
