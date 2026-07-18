"""
expert_forge/cli_train.py
=========================
Entrada por subprocess para cognia/experts (que NO puede importar torch):

  .\\venv312\\Scripts\\python.exe -m expert_forge.cli_train
      --model-dir C:\\...\\qwen2.5-0.5b-instruct
      --dataset-json C:\\...\\dataset.json
      --out-dir C:\\...\\adapter
      [--steps 200] [--rank 8] [--lr 2e-4] [--seq-len 512]

dataset-json: lista JSON de {"prompt": str, "completion": str}.
stdout: UNA linea JSON con el resultado de train_lora
        {final_loss, initial_loss, steps, rank, adapter_dir}.
stderr: progreso (step N/M loss X) cada 10 steps; ruido de libs.
Exit code 0 si entreno y guardo el adapter; != 0 con el error en stderr.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="Entrena un adapter LoRA "
                                             "(expert_forge.train_lora)")
    ap.add_argument("--model-dir", required=True,
                    help="directorio HF del modelo base")
    ap.add_argument("--dataset-json", required=True,
                    help="JSON con lista de {prompt, completion}")
    ap.add_argument("--out-dir", required=True,
                    help="directorio destino del adapter")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--rank", type=int, default=None,
                    help="rank LoRA; sin valor -> adaptativo por RAM")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--seq-len", type=int, default=512)
    args = ap.parse_args()

    dataset = json.loads(Path(args.dataset_json).read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        print("dataset-json debe ser una lista de {prompt, completion}",
              file=sys.stderr)
        return 2

    from expert_forge.lora_trainer import train_lora

    def progress(step, total, loss):
        if step % 10 == 0 or step == total:
            print("step %d/%d loss %.4f" % (step, total, loss),
                  file=sys.stderr, flush=True)

    try:
        result = train_lora(args.model_dir, dataset, args.out_dir,
                            rank=args.rank, steps=args.steps, lr=args.lr,
                            seq_len=args.seq_len, progress_fn=progress)
    except Exception as exc:  # el caller parsea stdout: errores a stderr
        print("train_lora fallo: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
