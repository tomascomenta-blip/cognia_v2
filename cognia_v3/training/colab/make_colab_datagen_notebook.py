"""
Genera un notebook .ipynb AUTONOMO para Google Colab (GPU T4 gratis, sin
telefono — plan B mientras Kaggle deniega GPU a la cuenta).

El notebook ejecuta el datagen sintetico de CODIGO completo (CYCLE 8): embebe
el codigo real de cognia_v3/training/kaggle/datagen_kernel.py leido en
build-time, con el MINIMO diff de adaptacion a Colab (reemplazos textuales
verificados: cada `old` debe aparecer exactamente 1 vez o el build falla):

  1. modelo: "Qwen/Qwen2.5-Coder-7B-Instruct" desde HF Hub en 4-bit nf4
     (Colab tiene internet libre, no hay /kaggle/input). Fallback a
     "Qwen/Qwen2.5-Coder-3B-Instruct" fp16 si OOM o si no hay GPU.
  2. paths de salida: /content en vez de /kaggle/working.
  3. TIME_BUDGET_S = 3.5h (limite de sesion de Colab free < 4h de Kaggle).
  4. GEN_BATCH = 8 (T4 real banca el lote grande; en Kaggle era 4).

Familias de templates, gate de ejecucion (subprocess -I + timeout), allowlist,
dedup y checkpoints quedan INTACTOS. El payload adaptado se valida con
ast.parse en build-time.

Uso: python -m cognia_v3.training.colab.make_colab_datagen_notebook [out.ipynb]
"""
import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
KERNEL = REPO / "cognia_v3" / "training" / "kaggle" / "datagen_kernel.py"
OUT_IPYNB = HERE / "cognia_datagen_colab.ipynb"

# ---------------------------------------------------------------------------
# Adaptaciones Colab: pares (old, new). Cada old debe matchear EXACTAMENTE una
# vez en el source del kernel; si el kernel cambia y un reemplazo deja de
# aplicar, el build rompe ruidosamente en vez de emitir un notebook corrupto.
# ---------------------------------------------------------------------------

REPLACEMENTS = [
    # 1. Paths + fuentes de modelo: Colab no monta /kaggle/input, baja de HF Hub.
    (
        'OUT = "/kaggle/working"\n',
        'OUT = "/content"\n'
        'MODEL_SOURCE = "Qwen/Qwen2.5-Coder-7B-Instruct"    # HF Hub (Colab tiene internet)\n'
        'FALLBACK_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"  # fp16 si OOM o sin GPU\n',
    ),
    # 2. Presupuesto: sesion Colab free se corta antes que las 4h de Kaggle.
    (
        "TIME_BUDGET_S = 4 * 3600\n",
        "TIME_BUDGET_S = int(3.5 * 3600)   # sesion Colab free: cortar antes del limite\n",
    ),
    # 3. Lote de generacion: con T4 real el batch grande rinde.
    (
        "GEN_BATCH = 4               # prompts por lote de generacion (left-padding)\n",
        "GEN_BATCH = 8               # prompts por lote de generacion (left-padding); T4 real banca 8\n",
    ),
    # 4. Eleccion de modelo: id de HF Hub en vez de glob sobre /kaggle/input.
    (
        '''def _pick_model_dir() -> str:
    """Dir del modelo montado bajo /kaggle/input. Con GPU -> 7B 4-bit (teacher
    correcto: acceptance 40% vs 14.6% del 3B); sin GPU -> 3B (en CPU solo el
    3b es viable). Los fallbacks fp16 -> 3b quedan como red de seguridad."""
    import torch
    candidates = sorted({os.path.dirname(p) for p in
                         glob.glob("/kaggle/input/**/config.json", recursive=True)})
    if not candidates:
        raise FileNotFoundError(
            "No hay modelos montados bajo /kaggle/input. Adjuntar "
            "qwen-lm/qwen2.5-coder/transformers/{7b,14b}-instruct.")
    gpus = list(range(torch.cuda.device_count())) if torch.cuda.is_available() else []
    vrams = [torch.cuda.get_device_properties(i).total_memory / 1e9 for i in gpus]
    for i, v in enumerate(vrams):
        print("[gpu] device %d: %s %.1f GB" % (i, torch.cuda.get_device_name(i), v))
    # v3 (2026-06-12): la historia real de v1/v2 lentos NO era fp16 shardeado:
    # los kernels corrieron en CPU porque kernel-metadata no llevaba
    # machine_shape (el backend nuevo ignora enable_gpu; gpu_quota.time_used=0
    # lo confirma). Con T4 real (~15.8GB) el 7b 4-bit es el teacher correcto
    # (acceptance 40% vs 14.6% del 3B); sin GPU solo el 3b es viable en CPU.
    key = "7b" if vrams else "3b"
    match = [d for d in candidates if key in d.lower()]
    pool = match or candidates
    pool.sort(key=len)
    print("[model] eleccion: %s -> %s" % (key, pool[0]))
    return pool[0]
''',
        '''def _pick_model_dir() -> str:
    """Colab: id de HF Hub en vez de dir montado. Con GPU -> 7B 4-bit (teacher
    correcto: acceptance 40% vs 14.6% del 3B); sin GPU -> 3B fp16 (en CPU solo
    el 3b es viable). El fallback por OOM en main() tambien degrada al 3B."""
    import torch
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            v = torch.cuda.get_device_properties(i).total_memory / 1e9
            print("[gpu] device %d: %s %.1f GB" % (i, torch.cuda.get_device_name(i), v))
        print("[model] eleccion: %s" % MODEL_SOURCE)
        return MODEL_SOURCE
    print("[model] SIN GPU -> %s (fp16, CPU)" % FALLBACK_MODEL)
    return FALLBACK_MODEL
''',
    ),
    # 5. Degradacion por OOM: en Colab no hay /kaggle/input que globear; el
    #    ultimo recurso es bajar el 3B de HF Hub.
    (
        '''        dirs3 = sorted((d for d in {os.path.dirname(p) for p in glob.glob(
            "/kaggle/input/**/config.json", recursive=True)}
            if "3b" in d.lower()), key=len)
        if not dirs3:
            raise
        model_dir = dirs3[0]
''',
        '''        model_dir = FALLBACK_MODEL
''',
    ),
]


def adapt_kernel_source(src: str) -> str:
    """Aplica los reemplazos Colab; cada old debe aparecer exactamente una vez."""
    for old, new in REPLACEMENTS:
        n = src.count(old)
        if n != 1:
            raise SystemExit("Reemplazo no aplica (%d matches, esperado 1): %r..."
                             % (n, old[:60]))
        src = src.replace(old, new)
    return src


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": src.splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_IPYNB
    payload = adapt_kernel_source(KERNEL.read_text(encoding="utf-8"))
    ast.parse(payload)  # gate de build: el codigo adaptado debe compilar

    setup = (
        "# Cognia datagen en Colab — instalar deps (Colab ya trae torch+CUDA)\n"
        "!pip -q install -U bitsandbytes transformers accelerate\n"
        "import torch\n"
        "if torch.cuda.is_available():\n"
        "    print('GPU:', torch.cuda.get_device_name(0))\n"
        "else:\n"
        "    print('AVISO: sin GPU -> el payload degrada a 3B fp16 en CPU (lentisimo).')\n"
        "    print('Runtime > Change runtime type > T4 GPU para el camino normal.')\n"
    )

    download = (
        "# Empaquetar outputs + descargar + imprimir el reporte\n"
        "import json, shutil, os\n"
        "os.makedirs('/content/datagen_out', exist_ok=True)\n"
        "for name in ('synthetic_code_dataset.jsonl', 'datagen_report.json'):\n"
        "    src = os.path.join('/content', name)\n"
        "    if os.path.exists(src):\n"
        "        shutil.copy(src, os.path.join('/content/datagen_out', name))\n"
        "shutil.make_archive('/content/cognia_datagen', 'zip', '/content/datagen_out')\n"
        "with open('/content/datagen_report.json', encoding='utf-8') as f:\n"
        "    print(json.dumps(json.load(f), indent=2))\n"
        "try:\n"
        "    from google.colab import files\n"
        "    files.download('/content/cognia_datagen.zip')\n"
        "except Exception as e:\n"
        "    print('download manual desde el panel Files:', e)\n"
    )

    nb = {
        "cells": [
            md_cell("# Cognia datagen sintetico de codigo — Colab (T4 gratis)\n"
                    "Runtime > Change runtime type > **T4 GPU**, luego Runtime > **Run all**.\n"
                    "Genera pares verificados por ejecucion (gate subprocess -I + asserts).\n"
                    "Corte: 500 pares o 3.5h. Al final descarga cognia_datagen.zip\n"
                    "(synthetic_code_dataset.jsonl + datagen_report.json)."),
            code_cell(setup),
            code_cell(payload),
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

    out_path.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
    kb = out_path.stat().st_size / 1024
    print("Notebook escrito: %s (%.0f KB)" % (out_path, kb))


if __name__ == "__main__":
    main()
