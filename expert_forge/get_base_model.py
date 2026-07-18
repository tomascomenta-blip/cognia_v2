"""
expert_forge/get_base_model.py
==============================
Descarga Qwen2.5-0.5B-Instruct desde HuggingFace a
~/.cognia/models_hf/qwen2.5-0.5b-instruct/ y verifica que carga con
transformers (forward de 5 tokens).

IMPORTANTE (regla de esta red): hf-xet / huggingface_hub se cuelga, asi que
se baja con curl.exe -L --fail --retry 10 --retry-all-errors -C - contra
las URLs https://huggingface.co/<repo>/resolve/main/<file>. Archivos ya
presentes (tamano > 0) se saltean; un safetensors parcial se retoma con -C -.

Uso:
  .\\venv312\\Scripts\\python.exe -m expert_forge.get_base_model [--dest DIR]
      [--skip-verify]
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = "Qwen/Qwen2.5-0.5B-Instruct"
FILES = [
    "config.json",
    "generation_config.json",
    "merges.txt",
    "vocab.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "model.safetensors",
]
DEFAULT_DEST = Path.home() / ".cognia" / "models_hf" / "qwen2.5-0.5b-instruct"


def download_base_model(dest: Path | None = None) -> Path:
    """Baja los FILES de REPO a dest via curl.exe. Saltea los ya presentes
    (tamano > 0); retoma parciales con -C -. Devuelve dest."""
    dest = Path(dest) if dest else DEFAULT_DEST
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.is_file() and target.stat().st_size > 0:
            print("ya presente: %s (%d bytes)" % (name, target.stat().st_size))
            continue
        url = "https://huggingface.co/%s/resolve/main/%s" % (REPO, name)
        print("bajando %s ..." % name)
        cmd = ["curl.exe", "-L", "--fail", "--retry", "10",
               "--retry-all-errors", "-C", "-", "--no-progress-meter",
               "-o", str(target), url]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError("curl fallo (%d) bajando %s" %
                               (result.returncode, url))
    return dest


def verify_base_model(dest: Path | None = None) -> bool:
    """Carga tokenizer + modelo con transformers y corre un forward de 5
    tokens en CPU fp32. Imprime la shape de los logits. True si todo OK."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dest = Path(dest) if dest else DEFAULT_DEST
    tokenizer = AutoTokenizer.from_pretrained(str(dest))
    try:
        model = AutoModelForCausalLM.from_pretrained(str(dest),
                                                     dtype=torch.float32)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(str(dest),
                                                     torch_dtype=torch.float32)
    model.eval()
    ids = tokenizer("Hola, soy Cognia", return_tensors="pt")["input_ids"][:, :5]
    with torch.no_grad():
        out = model(input_ids=ids)
    print("forward OK: input %s -> logits %s" %
          (tuple(ids.shape), tuple(out.logits.shape)))
    return True


def main():
    ap = argparse.ArgumentParser(description="Descarga y verifica el modelo "
                                             "base Qwen2.5-0.5B-Instruct")
    ap.add_argument("--dest", default=None, help="directorio destino "
                    "(default: ~/.cognia/models_hf/qwen2.5-0.5b-instruct)")
    ap.add_argument("--skip-verify", action="store_true",
                    help="solo bajar, sin cargar con transformers")
    args = ap.parse_args()
    dest = download_base_model(args.dest)
    print("descarga completa en %s" % dest)
    if not args.skip_verify:
        verify_base_model(dest)


if __name__ == "__main__":
    sys.exit(main())
