"""
CP2 — demostracion e2e del ciclo HERMES de auto-herramientas (06_AGENTE_PLAN §3).

Corre el ciclo REAL crear->verificar->registrar->reusar->evolucionar con el
modelo 3B de verdad (llama.cpp), no con code enlatado:
  1. el modelo GENERA el codigo de una tool nivel-1 (funcion pura run()).
  2. se VERIFICA por ejecucion en sandbox (scan estatico + subprocess timeout).
  3. solo si pasa, se REGISTRA en el manifest como 'staged'.
  4. se REUSA (se carga al registry y se invoca) -> los usos suben el tier
     staged->verified (o retiran una que falla).
  5. el gate crear-vs-reusar RECHAZA un near-duplicado.
  6. se captura una SKILL nivel-2 (markdown) desde una traza con oraculo duro.

Cada paso cierra con un CHECK explicito (metodo del repo: "codigo que corre o
no cuenta"). Usa un GENERATED_DIR aislado bajo esta carpeta para no tocar el
registry real del agente.

Usage: venv312\\Scripts\\python.exe -m cognia_x.construccion.cp2_selftooling_demo
"""
import sys
from pathlib import Path

import cognia.agent.tool_synthesis as ts
from cognia.agent import skill_capture, skills
from cognia.agent.tool_synthesis import ToolSpec, synthesize_and_register


class _OrchAdapter:
    """Adapta LlamaBackend al contrato orch.infer(prompt).text que usa
    tool_synthesis. temp>0 para que el repair pueda divergir del intento fallido."""
    def __init__(self, backend, max_tokens=512):
        self.backend = backend
        self.max_tokens = max_tokens

    def infer(self, prompt, **kw):
        text = self.backend.generate(prompt, max_tokens=self.max_tokens,
                                     temperature=0.2, seed=42,
                                     cache_prompt=False) or ""
        class _R:
            pass
        r = _R()
        r.text = text
        return r


def _check(label, ok, detail=""):
    print(f"  [{'CHECK OK' if ok else 'CHECK FAIL'}] {label}"
          f"{' -- ' + detail if detail else ''}", flush=True)
    return ok


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # GENERATED_DIR aislado (no toca cognia/agent/generated_tools)
    demo_dir = Path(__file__).resolve().parent / "_cp2_demo_tools"
    ts.GENERATED_DIR = demo_dir
    ts.MANIFEST_PATH = demo_dir / "_manifest.json"
    if ts.MANIFEST_PATH.exists():
        ts.MANIFEST_PATH.unlink()
    print(f"[cp2-demo] generated_dir aislado: {demo_dir}", flush=True)

    from cognia_v3.eval.benchmark_code import make_backend
    backend, gguf = make_backend()
    if backend is None:
        print("ERROR: no backend"); sys.exit(1)
    orch = _OrchAdapter(backend)
    print(f"[cp2-demo] backend OK: {gguf}\n", flush=True)

    all_ok = True

    # ── 1-3. el modelo genera una tool, se verifica y registra ──────────
    print("[1-3] el modelo GENERA -> verifica en sandbox -> registra", flush=True)
    spec = ToolSpec(
        name="contar_palabras",
        doc="contar_palabras <texto> -- cuenta cuantas palabras tiene el texto",
        purpose=("Contar el numero de palabras en el string args (palabras "
                 "separadas por espacios). Devolver el numero como texto."),
        test_input="hola mundo cruel",
        expect_contains="3")
    res = synthesize_and_register(spec, orch=orch, max_attempts=4)
    all_ok &= _check("tool generada por el modelo y verificada por ejecucion",
                     res.get("ok"), res.get("reason", "") + f" (intentos={res.get('attempts')})")
    if not res.get("ok"):
        print("\n[cp2-demo] el modelo no logro una tool valida en 4 intentos; "
              "se reporta honestamente y se corta.", flush=True)
        sys.exit(1)
    entry = [e for e in ts._load_manifest() if e["name"] == "contar_palabras"][0]
    all_ok &= _check("nace en tier 'staged' con version", entry["tier"] == "staged",
                     f"tier={entry['tier']} v={entry.get('version')}")

    # ── 4. reusar: cargar al registry e invocar; el uso sube el tier ────
    print("\n[4] REUSAR: cargar al registry, invocar, subir tier", flush=True)
    reg = {}
    n = ts.load_generated_tools(reg)
    all_ok &= _check("tool cargada al registry", "contar_palabras" in reg, f"cargadas={n}")
    if "contar_palabras" in reg:
        out = reg["contar_palabras"]["fn"]("uno dos tres cuatro", {})
        all_ok &= _check("invocacion real devuelve resultado", "4" in out, out.strip()[:60])
    # 3 usos exitosos -> staged asciende a verified
    tier = ""
    for _ in range(ts.VERIFY_AFTER_OK):
        tier = ts.record_tool_use("contar_palabras", ok=True)
    all_ok &= _check("staged -> verified tras usos exitosos", tier == "verified", f"tier={tier}")

    # ── 5. gate crear-vs-reusar: near-duplicado rechazado ───────────────
    print("\n[5] gate CREAR-VS-REUSAR: un near-duplicado se rechaza", flush=True)
    dup = ToolSpec(name="contar_palabra", doc="contar_palabra <t> -- cuenta palabras",
                   purpose="Contar palabras.", test_input="a b", expect_contains="2")
    dres = synthesize_and_register(dup, code="def run(a):\n    return str(len(a.split()))\n")
    all_ok &= _check("near-duplicado 'contar_palabra' rechazado (reusar existente)",
                     not dres.get("ok") and dres.get("existing") == "contar_palabras",
                     dres.get("reason", "")[:60])

    # ── 6. skill nivel-2 desde traza con oraculo duro ───────────────────
    print("\n[6] captura de SKILL nivel-2 (markdown) con oraculo duro", flush=True)
    skill_dir = Path(__file__).resolve().parent / "_cp2_demo_skills"
    skills.AUTO_SKILL_DIR = skill_dir
    skills.SKILL_DIRS = [skill_dir]
    trace = [
        {"action": "leer_archivo", "ok": True, "args": "m.py", "result_head": "..."},
        {"action": "escribir_archivo", "ok": True, "args": "m.py | code", "result_head": "OK"},
        {"action": "escribir_archivo", "ok": True, "args": "test_m.py | asserts", "result_head": "OK"},
        {"action": "py_validar", "ok": True, "args": "m.py", "result_head": "sintaxis OK"},
        {"action": "tests", "ok": True, "args": "test_m.py",
         "result_head": "RESULTADO ejecutar: 4 passed in 0.1s"},
    ]
    cap = skill_capture.maybe_capture_skill("implementar y testear una funcion utilitaria", trace)
    all_ok &= _check("skill nivel-2 capturada (>=4 calls + oraculo duro)",
                     cap.get("captured"), cap.get("name") or cap.get("reason", ""))
    if cap.get("captured"):
        p = Path(cap["path"])
        all_ok &= _check("archivo de skill escrito y legible",
                         p.exists() and "Procedimiento verificado" in p.read_text(encoding="utf-8"),
                         p.name)

    print(f"\n[cp2-demo] {'TODOS LOS CHECKS OK' if all_ok else 'HUBO CHECKS FALLIDOS'}", flush=True)
    print(f"[cp2-demo] tool generada: {demo_dir / 'contar_palabras.py'}", flush=True)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
