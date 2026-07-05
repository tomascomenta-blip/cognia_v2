"""
cognia_v3/eval/bfcl_split.py
============================
Split DETERMINISTA dev/test de la slice congelada de BFCL (slice_200.json).

Por que existe: el lazo de auto-prompting / RSI (cognia/agent/prompt_evolution.py)
OPTIMIZA el andamiaje (system prompt, few-shot, repair) contra un puntaje medido
por el modelo. Si optimiza y reporta sobre las MISMAS 200 items, el numero final
esta contaminado (overfitting a la slice -- la trampa #1 de la literatura de
prompt-optimization). La cura estandar: partir en

  DEV  -- el optimizador SOLO ve estas; sobre estas itera y elige candidatos.
  TEST -- held-out; NUNCA se toca durante la optimizacion; sobre estas se
          reporta la mejora HONESTA antes/despues.

Ademas la eval es CARA en CPU (~34 s/item, ~112 min las 200): el dev-slice chico
hace factible iterar (8/categoria = 40 items ~= 22 min por pasada) mientras el
test grande (32/categoria = 160 items) da una medicion final de baja varianza.

Determinismo: se lee slice_200.json (ya congelada) y se muestrea por categoria
con random.Random(SPLIT_SEED) sobre los ids ORDENADOS de esa categoria. Correr
esto dos veces da SIEMPRE el mismo dev/test. SPLIT_SEED != SLICE_SEED (42) del
harness: son sorteos independientes.

Uso:
    from cognia_v3.eval.bfcl_split import load_split
    dev, test = load_split()               # listas de {"id","category"}
    dev, test = load_split(dev_per_cat=6)   # dev mas chico aun (~12 min/pasada)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SLICE_PATH = EVAL_DIR / "data" / "bfcl" / "slice_200.json"

# Sorteo del split, INDEPENDIENTE del SLICE_SEED=42 del harness (que fija QUE 200
# items entran). Cambiar este numero re-baraja dev/test; dejarlo fijo mantiene el
# held-out estable entre corridas (comparabilidad antes/despues).
SPLIT_SEED = 1234
DEFAULT_DEV_PER_CAT = 8   # 8 x 5 categorias = 40 dev; 32 x 5 = 160 test

CATEGORIES = ["simple", "multiple", "parallel", "parallel_multiple", "live_simple"]


def load_slice() -> list[dict]:
    """La slice congelada tal cual (lista de {"id","category"})."""
    with open(SLICE_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_split(dev_per_cat: int = DEFAULT_DEV_PER_CAT) -> tuple[list[dict], list[dict]]:
    """
    (dev, test): para cada categoria, dev_per_cat ids al DEV (muestreo
    determinista con Random(SPLIT_SEED) sobre los ids ORDENADOS de la categoria)
    y el resto al TEST. El orden de salida respeta CATEGORIES (bloques por
    categoria), igual que la slice original.

    dev y test son DISJUNTOS por construccion (test = ids de la categoria menos
    los de dev). dev_per_cat se clampea a [0, tamano de la categoria].
    """
    slice_items = load_slice()
    by_cat: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for it in slice_items:
        by_cat.setdefault(it["category"], []).append(it["id"])

    dev, test = [], []
    for cat in CATEGORIES:
        ids = sorted(by_cat.get(cat, []))
        k = max(0, min(dev_per_cat, len(ids)))
        # Un Random NUEVO por categoria -> el split de una categoria no depende
        # de cuantas categorias se recorrieron antes (reproducible por-categoria).
        chosen = set(random.Random(SPLIT_SEED).sample(ids, k)) if k else set()
        for item_id in ids:
            entry = {"id": item_id, "category": cat}
            (dev if item_id in chosen else test).append(entry)
    return dev, test


def split_summary(dev_per_cat: int = DEFAULT_DEV_PER_CAT) -> dict:
    """Conteos por categoria (para logs / tests)."""
    dev, test = load_split(dev_per_cat)
    from collections import Counter
    dc, tc = Counter(x["category"] for x in dev), Counter(x["category"] for x in test)
    return {
        "dev_per_cat": dev_per_cat,
        "n_dev": len(dev), "n_test": len(test),
        "dev_by_cat": {c: dc.get(c, 0) for c in CATEGORIES},
        "test_by_cat": {c: tc.get(c, 0) for c in CATEGORIES},
    }


if __name__ == "__main__":
    import pprint
    pprint.pprint(split_summary())
