# -*- coding: utf-8 -*-
"""AUDIT DEL ORÁCULO (PREREG_AUDIT_COLONIA.md): perfil de skill por miembro
de la flota en razonamiento (G2R primeros 40) y español (G5 completo), con
oráculo determinista. Espera a que E1 termine (no compite por CPU) si se
lanza con --wait-e1. Persistencia incremental.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_audit_colonia [--wait-e1]
"""
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_audit_colonia.json"
E1 = REPO / "cognia_v3" / "eval" / "results_e1_qwen35_hard.json"
NOTHINK = "<think>\n\n</think>\n\n"

# (key, usa_prefill_nothink, deja_pensar_budget)
MIEMBROS = [
    ("3b", False, 0),
    ("qwen3_4b", False, 0),
    ("qwen35_4b", True, 0),
    ("vibethinker15b", False, 640),   # su skill ES pensar; se strippea <think>
    ("lfm25_12b", False, 0),
]


def chatml(system, user):
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")


def strip_think(t):
    return re.sub(r"<think>.*?</think>", "", t or "", flags=re.DOTALL).strip()


def backend_for(key):
    """Backend del miembro: el 3B va directo (no está en fleet30)."""
    if key == "3b":
        from node.llama_backend import _LlamaServerBackend
        from shattering.model_constants import resolve_gguf_path
        return _LlamaServerBackend(resolve_gguf_path("3b"), port=8188,
                                   ctx_size=4096), True
    from node.fleet_registry import fleet_backend
    return fleet_backend(key), False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import os
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")
    from cognia_v3.eval.suites.suite_oracle import oracle_pass

    if "--wait-e1" in sys.argv:
        print("esperando a que E1 termine...", flush=True)
        while True:
            try:
                if "veredictos" in json.loads(E1.read_text(encoding="utf-8")):
                    break
            except Exception:
                pass
            time.sleep(60)
        print("E1 listo; arranca el audit", flush=True)

    suites_dir = REPO / "cognia_v3" / "eval" / "suites"
    g2r = [json.loads(l) for l in
           open(suites_dir / "g2_razonamiento.jsonl", encoding="utf-8")
           if l.strip()][:40]                      # PRIMEROS 40 (prereg)
    g5 = [json.loads(l) for l in
          open(suites_dir / "g5_espanol.jsonl", encoding="utf-8") if l.strip()]
    ejes = {"g2r": g2r, "g5": g5}

    res = {"prereg": "PREREG_AUDIT_COLONIA.md", "miembros": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))

    for key, nothink, think_budget in MIEMBROS:
        hecho = res["miembros"].get(key, {})
        if all(e in hecho for e in ejes):
            print(f"[{key}] ya auditado", flush=True)
            continue
        b, directo = backend_for(key)
        if b is None:
            print(f"[{key}] NO ARRANCO — se omite (declarado)", flush=True)
            res["miembros"].setdefault(key, {})["error"] = "no_arranco"
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            continue
        try:
            for eje, items in ejes.items():
                if eje in hecho:
                    continue
                binarios, t0 = {}, time.time()
                for it in items:
                    sys_p = ("Eres un asistente útil."
                             if it.get("idioma", "es") == "es"
                             else "You are a helpful assistant.")
                    p = chatml(sys_p, it["prompt"])
                    if nothink:
                        p += NOTHINK
                    mx = max(it.get("max_new_tokens", 96), think_budget)
                    raw = b.generate(p, max_tokens=mx, temperature=0.0,
                                     cache_prompt=False) or ""
                    binarios[it["id"]] = bool(
                        oracle_pass(strip_think(raw), it["oracle"]))
                acc = sum(binarios.values()) / max(1, len(binarios))
                res["miembros"].setdefault(key, {})[eje] = {
                    "acc": round(acc, 3), "binarios": binarios,
                    "secs_total": round(time.time() - t0, 1)}
                OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
                print(f"[{key}] {eje}: {acc:.1%} "
                      f"({res['miembros'][key][eje]['secs_total']}s)", flush=True)
        finally:
            if directo:
                b.stop()
            else:
                from node.fleet_registry import close_fleet30
                close_fleet30()

    # ── AUD-1: unión-oráculo vs mejor único por eje ──
    veredictos = {}
    for eje in ejes:
        cols = {k: v[eje]["binarios"] for k, v in res["miembros"].items()
                if eje in v and "binarios" in v.get(eje, {})}
        if not cols:
            continue
        ids = list(next(iter(cols.values())).keys())
        union = sum(1 for i in ids if any(c.get(i) for c in cols.values()))
        mejor = max(sum(c.values()) for c in cols.values())
        n = len(ids)
        veredictos[eje] = {
            "mejor_unico": [mejor, n, round(mejor / n, 3)],
            "union_oraculo": [union, n, round(union / n, 3)],
            "delta_pp": round((union - mejor) / n * 100, 1),
            "AUD-1_router_paga(>=3pp)": (union - mejor) / n * 100 >= 3.0,
            "por_miembro": {k: round(sum(c.values()) / n, 3)
                            for k, c in cols.items()}}
    res["veredictos"] = veredictos
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTOS:", json.dumps(veredictos, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
