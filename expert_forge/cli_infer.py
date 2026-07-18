"""
expert_forge/cli_infer.py
=========================
Inferencia puntual del meta-modelo creador de expertos, pensada para ser
invocada por subprocess desde cognia/experts/meta_maker.py (cognia/ no puede
importar torch — regla dura del repo).

Imprime a stdout SOLO el JSON de la spec, o una linea 'ERROR: ...'.

Uso:
    .\\venv312\\Scripts\\python.exe -m expert_forge.cli_infer --peticion "quiero un experto chef"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from expert_forge.expert_maker_dataset import eval_json_validity  # noqa: F401 (contrato)
from expert_forge.lora_trainer import generate_with_adapter

MODEL_DIR = str(Path.home() / ".cognia" / "models_hf" / "qwen2.5-0.5b-instruct")
ADAPTER_DIR = str(Path.home() / ".cognia" / "experts" / "meta_maker_adapter")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--peticion", required=True)
    ap.add_argument("--max-new", type=int, default=120)
    args = ap.parse_args()

    if not Path(MODEL_DIR).is_dir():
        print("ERROR: modelo base 0.5B no instalado (expert_forge.get_base_model)")
        return
    adapter = ADAPTER_DIR if Path(ADAPTER_DIR).is_dir() else None

    prompt = f"Peticion: {args.peticion}\nSpec JSON:"
    text = generate_with_adapter(MODEL_DIR, adapter, prompt,
                                 max_new_tokens=args.max_new) or ""
    # extraer el primer objeto {...} balanceado
    try:
        start = text.index("{")
        depth, end = 0, None
        for j, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        spec = json.loads(text[start:end])
        print(json.dumps(spec, ensure_ascii=False))
    except (ValueError, TypeError):
        print(f"ERROR: salida no parseable: {text[:120]!r}")


if __name__ == "__main__":
    main()
