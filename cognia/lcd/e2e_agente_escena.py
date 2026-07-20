"""
e2e REAL (plan 12, CP5): el agente MoM (/hacer con el modelo 3B de verdad)
usando las herramientas AI-nativas de escena. Verifica que:
  1. las tools LCD estan en el registry y son invocables (deterministico);
  2. el pipeline completo crear -> corromper -> atribuir_fallo -> reejecutar
     repara la escena (el lazo del arbitro, cero-LLM);
  3. el modelo 3B, dado el prompt del loop con few-shot, ELIGE escena_crear
     (la parte que depende del modelo; se reporta honestamente si el 3B la
     elige o no, igual que el patron generar_codigo del CP2).

Cada paso cierra con un CHECK explicito (metodo del repo). Usa el llama-server
ya activo si lo hay.

Usage: venv312\\Scripts\\python.exe -m cognia.lcd.e2e_agente_escena
"""
import sys

import cognia.lcd.tools_lcd as lcd_tools   # noqa: F401 -- registra las tools
from cognia.agent.tools import TOOLS, run_tool


def _check(label, ok, detail=""):
    print(f"  [{'CHECK OK' if ok else 'CHECK FAIL'}] {label}"
          f"{' -- ' + detail if detail else ''}", flush=True)
    return ok


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("[e2e-escena] herramientas AI-nativas de escena LCD con el agente\n", flush=True)
    oks = []

    # 1. registro
    oks.append(_check("tools LCD en el registry",
                      all(t in TOOLS for t in ("escena_crear", "escena_editar",
                          "escena_consultar", "atribuir_fallo", "reejecutar_etapa")),
                      f"{lcd_tools.load_lcd_tools()} registradas"))

    # 2. pipeline determinista: crear -> corromper -> atribuir -> reparar
    ctx = {"working_memory": {}, "agent_state": {}}
    r_crear = run_tool("escena_crear", "una taza roja sobre una mesa azul", ctx)
    print("   >", r_crear, flush=True)
    oks.append(_check("escena_crear con control 3/3", "control 3/3" in r_crear))

    # corromper la escena viva (borrar un objeto = fallo de plan)
    scene = ctx["working_memory"]["_lcd_scene"]["escena"]
    scene.objects = scene.objects[:-1]
    r_atrib = run_tool("atribuir_fallo", "", ctx)
    print("   >", r_atrib, flush=True)
    oks.append(_check("atribuir_fallo señala 'plan'", "plan" in r_atrib))

    r_reejec = run_tool("reejecutar_etapa", "plan", ctx)
    print("   >", r_reejec, flush=True)
    oks.append(_check("reejecutar_etapa plan repara (control 3/3)",
                      "control 3/3" in r_reejec))

    r_final = run_tool("atribuir_fallo", "", ctx)
    oks.append(_check("tras reparar, todos los contratos pasan",
                      "todos los contratos pasan" in r_final))

    # edicion selectiva
    r_edit = run_tool("escena_editar", "taza | color=green", ctx)
    print("   >", r_edit, flush=True)
    oks.append(_check("escena_editar selectiva (resto intacto)",
                      "resto intacto=True" in r_edit))

    # 3. el modelo 3B elige la tool (depende del modelo, honesto)
    print("\n[e2e-escena] parte que depende del 3B: ¿elige escena_crear?", flush=True)
    try:
        from shattering.orchestrator import ShatteringOrchestrator
        # Sin manifest_path relativo: el default resuelve el manifest
        # EMPAQUETADO (funciona instalado y con cwd arbitrario).
        orch = ShatteringOrchestrator()
        _try = getattr(orch, "_try_load_llama", None)
        if callable(_try):
            _try()
        from cognia.agent.fewshot import fewshot_for
        from cognia.agent.tools import build_tools_doc
        doc = build_tools_doc({"escena_crear", "escena_consultar", "responder"})
        fs = fewshot_for("escena_crear")
        prompt = (
            "You are an autonomous agent. Start your reply with ACCION: on the first line.\n\n"
            "ACCION: <tool> <args>\n\nTools:\n" + doc + "\n  responder <respuesta>\n\n"
            + fs + "\n\nContexto de la tarea:\nTAREA: crea una escena con una pelota "
            "verde a la izquierda de una caja amarilla\n\nSiguiente ACCION:")
        raw = orch.infer(prompt, temperature=0.0, max_tokens=64).text.strip()
        print("   respuesta del 3B:", raw[:120], flush=True)
        chose = "escena_crear" in raw.split("\n")[0]
        _check("el 3B eligio escena_crear en el 1er paso", chose,
               "si no, la tool igual funciona pre-disparada (patron generar_codigo)")
        # nota: no cuenta para el veredicto (depende del modelo); es informativo
    except Exception as e:
        print(f"   (no se pudo probar el 3B: {e})", flush=True)

    print(f"\n[e2e-escena] {'TODOS OK' if all(oks) else 'HAY FALLOS'}: "
          f"{sum(oks)}/{len(oks)} checks deterministas.", flush=True)
    return 0 if all(oks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
