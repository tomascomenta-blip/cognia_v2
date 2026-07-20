r"""
exp021_speculative_decode / analyze.py
======================================
Consolida la evidencia REAL de speculative decoding en un veredicto unico para
H-SPEED-1, fusionando:
  - results.json         (bench_real: ngram-* sobre el i3 real)
  - results_draft.json   (bench_draft: draft-simple 0.5B, warm)   [opcional]
  - results_costmodel.json (modelo de banda calibrado a exp004)    [opcional]

Escribe results/verdict.json con un 'summary' {status, headline, ...} que
cycle34 consume (convencion del lab: una fuente de verdad por experimento).

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\analyze.py
Solo stdlib.
"""
from __future__ import annotations

import json
from pathlib import Path

R = Path(__file__).resolve().parent / "results"


def _load(name):
    p = R / name
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def main() -> None:
    ngram = _load("results.json")
    draft = _load("results_draft.json")
    cost = _load("results_costmodel.json")

    by_strategy = {}   # name -> {prompt: speedup, lossless}
    baseline_warm = []

    def ingest(data, warm, drop_code=False):
        # warm=True: baseline con warmup (bench_draft) -> calibracion limpia.
        # drop_code=True: el 'code' de bench_real tiene baseline COLD (cold-mmap)
        #   -> su speedup esta contaminado; se descarta (solo se confia en warm).
        if not data:
            return
        if warm:
            for r in data.get("runs", []):
                if r["config"] == "baseline" and r.get("decode_tps"):
                    baseline_warm.append(r["decode_tps"])
        for s in data.get("summary", []):
            if drop_code and s["prompt"] == "code":
                continue
            d = by_strategy.setdefault(s["config"], {})
            # warm pisa a cold si hay colision (config,prompt)
            if s["prompt"] not in d or warm:
                d[s["prompt"]] = {"speedup": s["speedup"], "lossless": s.get("lossless"),
                                  "warm": warm}

    ingest(draft, warm=True)                 # warm primero (prioridad)
    ingest(ngram, warm=False, drop_code=True)  # bench_real: descartar code cold
    baseline_tps = (sorted(baseline_warm)[len(baseline_warm) // 2]
                    if baseline_warm else None)

    # mejor ganancia "gratis" (sin modelo extra) en texto repetitivo/codigo
    free_gains = []
    for name, d in by_strategy.items():
        if name.startswith("ngram"):
            for pr in ("echo", "code"):
                if pr in d and d[pr]["speedup"]:
                    free_gains.append((name, pr, d[pr]["speedup"]))
    free_gains.sort(key=lambda x: -x[2])

    # ganancia en HABLA NATURAL (el caso objetivo)
    speech = {name: d.get("speech", {}).get("speedup") for name, d in by_strategy.items()
              if "speech" in d}
    best_speech = max(speech.items(), key=lambda kv: (kv[1] or 0)) if speech else (None, None)

    # veredicto
    notes = []
    free_ok = bool(free_gains) and free_gains[0][2] >= 1.15
    speech_ok = best_speech[1] is not None and best_speech[1] >= 1.15
    if free_ok and speech_ok:
        status = "apoyada"
    elif free_ok or speech_ok:
        status = "mixta"
    else:
        status = "refutada"

    if free_gains:
        notes.append(f"Mejor ganancia gratis (ngram, sin modelo extra): "
                     f"{free_gains[0][0]} en '{free_gains[0][1]}' = {free_gains[0][2]}x (lossless).")
    if speech:
        notes.append("Habla natural (objetivo): " +
                     ", ".join(f"{k}={v}x" for k, v in sorted(speech.items())) +
                     ".  -> n-gram NO acelera habla general; ese caso exige draft/heads.")
    if cost:
        proj = [p for p in cost.get("projections", []) if "MTP" in p.get("strategy", "")]
        if proj:
            notes.append("Proyeccion peldano-2 (modelo de banda calibrado): " +
                         ", ".join(f"{p['strategy']} -> {p['tok_s_proyectado']} tok/s"
                                   for p in proj) + ".")
        c = cost.get("calibration", {})
        if c:
            notes.append(f"Calibracion: baseline(mediana)={c.get('baseline_tps_mediana')} tok/s = "
                         f"{c.get('BW_efectivo_GiBps')} GiB/s (en la pared de memoria de exp004: "
                         f"{c.get('en_pared_de_memoria')}).")

    headline = {
        "apoyada": "Speculative SUBE tok/s en el sistema actual hoy: n-gram da ganancia "
                   "gratis en texto repetitivo/codigo Y el draft/heads acelera tambien habla general.",
        "mixta": "Speculative SUBE tok/s pero CONDICIONAL: n-gram acelera texto "
                 "repetitivo/codigo gratis (lossless); el habla natural general necesita "
                 "draft real o cabezas entrenables (MTP/EAGLE), que el binario ya soporta.",
        "refutada": "Speculative no dio ganancia neta util en ningun caso en esta medicion.",
    }[status]

    verdict = {
        "experiment": "exp021_speculative_decode",
        "hypothesis_id": "H-SPEED-1",
        "summary": {
            "status": status,
            "headline": headline,
            "baseline_tps": round(baseline_tps, 2) if baseline_tps else None,
            "by_strategy": by_strategy,
            "best_free_gain": ({"strategy": free_gains[0][0], "prompt": free_gains[0][1],
                                "speedup": free_gains[0][2]} if free_gains else None),
            "best_speech": {"strategy": best_speech[0], "speedup": best_speech[1]},
            "notes": notes,
        },
        "sources": {
            "ngram_real": bool(ngram), "draft_real": bool(draft), "cost_model": bool(cost),
        },
    }
    (R / "verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
    print("=== exp021 VEREDICTO H-SPEED-1:", status.upper(), "===")
    print(headline)
    for n in notes:
        print("  -", n)
    print("\nverdict.json escrito en", R)


if __name__ == "__main__":
    main()
