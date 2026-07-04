"""
Eval del PLANNER-LLM del LCD (paper §4.1 mod 1 = LLM produce el layout).

Compara el planner de REGLAS (determinista, control 8/8) contra el planner-LLM
(el 3B produce la escena JSON). Mide: ¿el 3B produce JSON valido? ¿la escena
tiene los objetos pedidos? Es el test de "puede el modelo hacer la etapa de
planificación de LCD" — el paper propone un LLM ahí (LayoutGPT-like), y el
patrón medido en corrida-1 (BFCL) es que el 3B necesita ejemplos concretos.

Usage: venv312\\Scripts\\python.exe -m cognia_x.lcd.eval_llm_planner
"""
import json
import sys
from pathlib import Path

from cognia_x.lcd.eval import SPECS
from cognia_x.lcd.planner import plan, plan_with_llm
from cognia_x.lcd.renderer import render_to
from cognia_x.lcd.scene import SHAPES

OUT = Path(__file__).resolve().parent / "out"


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    from shattering.orchestrator import ShatteringOrchestrator
    try:
        orch = ShatteringOrchestrator(manifest_path="shattering/manifests/cognia_desktop.json")
        orch._try_load_llama()
    except Exception:
        # fallback: el orch del CLI (ai._orchestrator) ya trae el backend
        from cognia.cognia import Cognia
        orch = Cognia()._orchestrator

    print("[llm-planner] planner-LLM (3B) vs planner-reglas sobre las specs LCD",
          flush=True)
    rows = []
    n_valid = n_objs_ok = 0
    for prompt, expected, _ in SPECS:
        scene, raw = plan_with_llm(prompt, orch)
        valid = scene is not None
        objs_ok = False
        n = 0
        if valid:
            names = [o.name.lower() for o in scene.objects]
            n = len(scene.objects)
            # ¿tiene al menos tantos objetos como se pidieron?
            objs_ok = n >= len(expected)
            if objs_ok:
                render_to(scene, OUT / f"llm_{expected[0]}.png")
        n_valid += valid
        n_objs_ok += objs_ok
        rows.append({"prompt": prompt, "json_valid": valid, "n_objs": n,
                     "objs_ok": objs_ok, "raw": raw[:120]})
        print(f"   [{'JSON-OK' if valid else 'JSON-NO'}] {prompt[:42]:<42} "
              f"objs={n} {'ok' if objs_ok else '--'}", flush=True)

    n = len(SPECS)
    print(f"\n[llm-planner] JSON valido: {n_valid}/{n} | objetos suficientes: "
          f"{n_objs_ok}/{n}", flush=True)
    print(f"[llm-planner] (reglas: 8/8 control exacto — referencia)", flush=True)
    print("[llm-planner] Veredicto: si el 3B da JSON pobre, el planner de reglas "
          "es el camino v1; el LLM-planner del paper necesita fine-tune/few-shot "
          "(mismo patron que BFCL: concreto > abstracto para modelos chicos).",
          flush=True)
    out = {"n": n, "json_valid": n_valid, "objs_ok": n_objs_ok, "rows": rows,
           "rule_based_reference": "8/8"}
    (OUT / "llm_planner_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
