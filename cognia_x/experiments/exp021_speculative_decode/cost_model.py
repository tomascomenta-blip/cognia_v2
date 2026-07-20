r"""
exp021_speculative_decode / cost_model.py
==========================================
Modelo de coste *memory-bandwidth-bound* del decode, calibrado a:
  - exp004 (roofline CPU): decode satura el ancho de banda (~15-22 GB/s).
  - el tok/s baseline REAL medido por bench_real.py sobre el i3.

Idea (D-006 del lab): coste por token ~= bytes de pesos leidos de RAM ese paso.
  baseline_tps  = BW_efectivo / W_base_bytes
A partir de ahi, todo speculative se reduce a "cuantos tokens commiteo por cada
lectura completa de la base" (a_eff = aceptados por verificacion), menos el coste
de banda del drafter:

  speedup ≈ a_eff · W_base / (W_base + K_prop · W_draft) · (1 - overhead)

Estrategias proyectadas:
  - ngram-*  : W_draft = 0            (calibrado con la aceptacion REAL de bench_real)
  - MTP/EAGLE: W_draft ≈ pocos MB     (peldano 2, aceptacion de literatura)
  - draft 0.5B: W_draft ≈ 0.30 GB     (penalizacion de banda real)

Corre DESPUES de bench_real.py:
  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\cost_model.py
Solo stdlib.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results" / "results.json"

# ── constantes fisicas reales ──────────────────────────────────────────────
GB = 1024 ** 3
W_BASE_GGUF_BYTES = 1_929_903_360          # tamano real del Qwen3B Q4_K_M en disco
# exp004: ancho de banda efectivo de GEMV en este i3 (rango medido, float32)
EXP004_GBPS_RANGE = (15.6, 22.2)
# Peldano draft 0.5B (Qwen2.5-Coder-0.5B Q4 ~ 0.30-0.40 GB activos por token)
W_DRAFT_05B_BYTES = 0.34 * GB
# Peldano MTP/EAGLE head: pocos MB (comparte la lectura de la base)
W_HEAD_BYTES = 0.02 * GB
# Overhead de verificacion (atencion sobre K posiciones propuestas, barato en
# maquina bandwidth-bound; fraccion del tiempo de 1 lectura de base)
VERIFY_OVERHEAD = 0.08
# Aceptacion tipica de EAGLE-3 / MTP en modelos ~3-7B (literatura tier-1, rango)
EAGLE_ACCEPT_RANGE = (2.4, 3.4)   # tokens aceptados por verificacion


def speedup(a_eff: float, w_draft_bytes: float, k_prop: float) -> float:
    """Speedup de decode vs AR puro bajo el modelo de banda."""
    denom = W_BASE_GGUF_BYTES + k_prop * w_draft_bytes
    return a_eff * (W_BASE_GGUF_BYTES / denom) * (1.0 - VERIFY_OVERHEAD)


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def main() -> None:
    out = {"experiment": "exp021/cost_model", "calibration": {}, "projections": []}

    # ── 1. calibrar BW efectivo desde el baseline real (MEDIANA: robusta al
    #       artefacto cold-mmap del 1er prompt) ───────────────────────────────
    baseline_tps = None
    src_used = None
    # preferir bench_draft (warm, con warmup) sobre bench_real (1er prompt frio)
    for fname in ("results_draft.json", "results.json"):
        p = HERE / "results" / fname
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            tps = [r["decode_tps"] for r in data.get("runs", [])
                   if r["config"] == "baseline" and r.get("decode_tps")]
            if tps:
                baseline_tps = _median(tps)   # mediana ignora el cold outlier
                src_used = fname
                break

    if baseline_tps is None:
        baseline_tps = 7.52          # fallback: warm medido (speech/echo) bench_real
        out["calibration"]["note"] = "SIN bench; usando baseline warm=7.52 tok/s"

    bw_eff_gbps = baseline_tps * W_BASE_GGUF_BYTES / GB
    out["calibration"].update({
        "baseline_tps_mediana": round(baseline_tps, 3),
        "fuente": src_used,
        "W_base_GiB": round(W_BASE_GGUF_BYTES / GB, 3),
        "BW_efectivo_GiBps": round(bw_eff_gbps, 2),
        "exp004_GiBps_range": EXP004_GBPS_RANGE,
        # 'en la pared de memoria': en/cerca del rango de exp004; si queda algo por
        # debajo es por el overhead no-GEMV del decode (atencion, lm_head O(V),
        # sampling) -> sigue siendo bandwidth-bound.
        "en_pared_de_memoria": bw_eff_gbps >= 0.80 * EXP004_GBPS_RANGE[0],
    })

    # ── 2. proyecciones de peldanos (modelo de banda; literatura) ──────────
    # 3a. draft 0.5B (draft-simple): aceptacion plausible 2.0-3.0, K_prop=4
    for a in (2.0, 3.0):
        s = speedup(a_eff=a, w_draft_bytes=W_DRAFT_05B_BYTES, k_prop=4)
        out["projections"].append({
            "strategy": f"draft-0.5B (a={a})", "source": "PROYECTADO (modelo banda)",
            "speedup": round(s, 3), "tok_s_proyectado": round(baseline_tps * s, 2),
            "nota": "penalizado: el draft lee ~0.34GB extra/token propuesto",
        })

    # 3b. MTP / EAGLE head: aceptacion de literatura, W_draft ~ MB
    for a in EAGLE_ACCEPT_RANGE:
        s = speedup(a_eff=a, w_draft_bytes=W_HEAD_BYTES, k_prop=a + 1)
        out["projections"].append({
            "strategy": f"MTP/EAGLE-head (a={a})", "source": "PROYECTADO (modelo banda)",
            "speedup": round(s, 3), "tok_s_proyectado": round(baseline_tps * s, 2),
            "nota": "peldano 2: params entrenables sobre base congelada; banda ~0",
        })

    (HERE / "results" / "results_costmodel.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── reporte ────────────────────────────────────────────────────────────
    print("=== exp021 cost model (bandwidth-bound, calibrado a exp004) ===")
    c = out["calibration"]
    print(f"baseline(mediana)={c['baseline_tps_mediana']} tok/s | W_base={c['W_base_GiB']}GiB | "
          f"BW_eff={c['BW_efectivo_GiBps']} GiB/s | "
          f"en_pared_de_memoria={c['en_pared_de_memoria']}")
    print(f"\n{'estrategia':<24}{'fuente':<26}{'speedup':>9}{'tok/s':>9}")
    for p in out["projections"]:
        sp = p.get("speedup_medio", p.get("speedup"))
        print(f"{p['strategy']:<24}{p['source']:<26}{sp:>8}x{p['tok_s_proyectado']:>9}")
    print("\nresults_costmodel.json escrito.")


if __name__ == "__main__":
    main()
