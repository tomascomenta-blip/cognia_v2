"""
QLoRATrainer: fine-tunes Qwen2.5-Coder-3B on Cognia's distilled knowledge.
Creates a LoRA adapter — the base model weights are NEVER changed.

Requirements: pip install transformers peft trl bitsandbytes datasets torch
Hardware: bitsandbytes 4-bit requiere GPU CUDA. En CPU-only este trainer
reporta el bloqueo y NO intenta entrenar (3B en un i3 no es viable).

Run check: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.qlora_trainer
"""
import json
import os


class QLoRATrainer:

    def __init__(self,
                 model_name: str = "Qwen/Qwen2.5-Coder-3B-Instruct",
                 dataset_path: str = "cognia_v3/training/cognia_dataset.jsonl",
                 output_dir: str = "checkpoints/cognia_v1/"):
        self.model_name = model_name
        self.dataset_path = dataset_path
        self.output_dir = output_dir
        self.model = None
        self.tokenizer = None

    # ── Checks ──────────────────────────────────────────────────────────

    def _can_import(self, lib: str) -> bool:
        try:
            __import__(lib)
            return True
        except ImportError:
            return False

    def check_requirements(self) -> bool:
        required = ["torch", "transformers", "peft", "trl", "bitsandbytes", "datasets"]
        missing = [lib for lib in required if not self._can_import(lib)]
        if missing:
            print(f"[X] Missing: {missing}")
            print(f"    Install: pip install {' '.join(missing)}")
            return False
        import torch
        if not torch.cuda.is_available():
            print("[X] Sin GPU CUDA: QLoRA 4-bit (bitsandbytes) no puede correr. "
                  "Entrenar un 3B en CPU no es viable — bloqueado honestamente.")
            return False
        print("[OK] All requirements met (libs + CUDA)")
        return True

    def check_dataset(self) -> int:
        if not os.path.exists(self.dataset_path):
            print(f"[X] Dataset no encontrado: {self.dataset_path}")
            return 0
        with open(self.dataset_path, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        status = "OK" if n >= 50 else "INSUFICIENTE (<50)"
        print(f"[{status}] Dataset: {n} pares en {self.dataset_path}")
        return n

    # ── Entrenamiento (solo corre si check_requirements pasa) ───────────

    def load_model(self) -> bool:
        if not self.check_requirements():
            return False
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        bnb = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
        print(f"Loading {self.model_name} ...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name, quantization_config=bnb, device_map="auto", trust_remote_code=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        print("[OK] Model loaded")
        return True

    def setup_lora(self, r: int = 8, alpha: int = 16) -> None:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        self.model = prepare_model_for_kbit_training(self.model)
        cfg = LoraConfig(r=r, lora_alpha=alpha,
                         target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
                         lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
        self.model = get_peft_model(self.model, cfg)
        trainable = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in self.model.parameters())
        print(f"[OK] LoRA: {trainable:,} trainable / {total:,} total "
              f"({100 * trainable / total:.3f}%)")

    def load_dataset(self):
        from datasets import Dataset
        with open(self.dataset_path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f]

        def fmt(r):
            return (f"<|im_start|>user\n{r['prompt']}<|im_end|>\n"
                    f"<|im_start|>assistant\n{r['completion']}<|im_end|>")

        ds = Dataset.from_dict({"text": [fmt(r) for r in records]})
        split = ds.train_test_split(test_size=min(0.1, 50 / len(ds)))
        print(f"[OK] Dataset: {len(split['train'])} train, {len(split['test'])} eval")
        return split

    def train(self, num_epochs: int = 1, batch_size: int = 2) -> str:
        from trl import SFTTrainer
        from transformers import TrainingArguments

        if self.model is None and not self.load_model():
            raise RuntimeError("Requirements/hardware no cumplidos — ver check_requirements()")
        self.setup_lora()
        dataset = self.load_dataset()

        args = TrainingArguments(
            output_dir=self.output_dir, num_train_epochs=num_epochs,
            per_device_train_batch_size=batch_size, gradient_accumulation_steps=4,
            learning_rate=2e-4, bf16=True, fp16=False,
            logging_steps=10, save_steps=200, warmup_ratio=0.05,
            lr_scheduler_type="cosine", report_to="none",
        )
        trainer = SFTTrainer(
            model=self.model, tokenizer=self.tokenizer,
            train_dataset=dataset["train"], eval_dataset=dataset["test"],
            dataset_text_field="text", max_seq_length=512, args=args,
        )
        print("Starting training ...")
        trainer.train()

        adapter_path = os.path.join(self.output_dir, "final_adapter")
        self.model.save_pretrained(adapter_path)
        self.tokenizer.save_pretrained(adapter_path)
        print(f"[OK] Adapter saved: {adapter_path}")
        return adapter_path


if __name__ == "__main__":
    t = QLoRATrainer()
    t.check_dataset()
    t.check_requirements()
