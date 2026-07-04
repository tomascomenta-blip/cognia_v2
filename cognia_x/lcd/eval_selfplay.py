"""
cognia_x/lcd/eval_selfplay.py — AUTO-PRUEBA e2e: la IA intenta reproducir
escenas objetivo con las tools reales de edicion y se mide el parecido.

Corre tres agentes sobre un set de escenas objetivo y reporta la similitud:
  1. SCRIPTED (techo): emite las ACCIONes exactas -> similitud ~1.0 (valida que
     las tools + la metrica cierran el lazo).
  2. HEURISTICO: reconstruye solo por el tipo de objeto (sin posiciones finas)
     -> mide cuanto aporta acertar el layout.
  3. (opcional) el 3B REAL: si hay orquestador, el modelo intenta reproducir la
     escena leyendo su resumen -> el numero honesto de "que tan bien una IA
     arma la escena con estas tools".

Tambien benchmarkea render/fisica/similitud (el eje 'super optimizado').

Uso: venv312\\Scripts\\python.exe -m cognia_x.lcd.eval_selfplay
"""
from __future__ import annotations

import sys
import time

import cognia_x.lcd.tools_lcd as _lcd   # noqa: F401 -- registra las tools base


def _targets():
    """Escenas objetivo (del planner de reglas: control conocido)."""
    from cognia_x.lcd.planner import plan
    prompts = [
        "a red cup on a blue table", "a green ball to the left of a yellow box",
        "a book on a table", "un plato sobre una mesa",
        "a lamp to the right of a chair", "a sun above a house",
    ]
    return [(p, plan(p)) for p in prompts]


def _heuristic_agent(target):
    """Agente que solo agrega los objetos por tipo en el centro (sin la posicion
    exacta del target): mide el piso de similitud (acierta objetos, no layout)."""
    objs = list(target.objects)
    it = iter([f"escena_agregar {o.name}" for o in objs] + ["FIN"])

    def agent_fn(desc, hist, summ):
        return next(it, "FIN")
    return agent_fn


def _real_3b_agent(orch, target):
    """El 3B intenta reproducir: se le da el resumen del objetivo y las tools, y
    en UNA pasada emite las ACCIONes de agregado (few-shot concreto). Se acota a
    tantas ACCIONes como objetos tenga el target (el 3B tiende a alucinar extras
    'asociados' — mesa->cuchillo/tenedor; el cap evita ese ruido)."""
    from cognia_x.lcd.selfplay import _summary
    n = len(target.objects)
    prompt = (
        f"Agrega EXACTAMENTE estos {n} objetos a la escena, ni uno mas, UNA "
        "ACCION por objeto, respetando su posicion.\n"
        "Formato EXACTO por linea: escena_agregar <objeto> | x=<0..1> y=<0..1>\n"
        "Ejemplo:\nescena_agregar mesa | x=0.5 y=0.7\nescena_agregar taza | x=0.5 y=0.56\n\n"
        f"Objetos a agregar (con su posicion): {_summary(target)}\n\n"
        f"Emiti SOLO {n} lineas escena_agregar, luego FIN:")
    try:
        raw = orch.infer(prompt, max_tokens=200, temperature=0.0).text
    except Exception:
        raw = ""
    lines = [l.strip() for l in raw.splitlines() if "escena_agregar" in l][:n]
    it = iter(lines + ["FIN"])

    def agent_fn(desc, hist, summ):
        return next(it, "FIN")
    return agent_fn


def _bench():
    from cognia_x.lcd.physics import settle
    from cognia_x.lcd.renderer import render
    from cognia_x.lcd.scene import Obj, Scene
    from cognia_x.lcd.selfplay import similarity

    def big():
        objs = [Obj(name="mesa", shape="rect", x=0.5, y=0.3, w=0.55, h=0.12)]
        for i in range(11):
            objs.append(Obj(name=["taza", "caja", "libro", "pelota", "plato"][i % 5],
                            shape="rect", x=0.1 + 0.07 * i, y=0.1 + 0.02 * i, w=0.1, h=0.1))
        return Scene(objects=objs)
    N = 100
    t = time.time()
    for _ in range(N):
        s = big(); settle(s)
    ms_settle = (time.time() - t) / N * 1000
    t = time.time()
    for _ in range(N):
        render(big())
    ms_render = (time.time() - t) / N * 1000
    a, b = big(), big()
    t = time.time()
    for _ in range(N * 3):
        similarity(a, b)
    ms_sim = (time.time() - t) / (N * 3) * 1000
    return ms_settle, ms_render, ms_sim


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    from cognia.agent.tools import run_tool
    from cognia_x.lcd.selfplay import attempt_reproduce, scripted_from_scene

    if "escena_agregar" not in __import__("cognia.agent.tools", fromlist=["TOOLS"]).TOOLS:
        print("[eval-selfplay] falta escena_agregar (tools de edicion no cargadas)", flush=True)
        return 1

    targets = _targets()
    print(f"[eval-selfplay] {len(targets)} escenas objetivo\n", flush=True)

    def avg(fn):
        scores = []
        for desc, tgt in targets:
            r = attempt_reproduce(tgt, desc, fn(tgt), run_tool)
            scores.append(r["similarity"]["score"])
        return sum(scores) / len(scores), scores

    s_scripted, _ = avg(scripted_from_scene)
    print(f"[scripted TECHO]   similitud media = {s_scripted:.3f}", flush=True)
    s_heur, heur_scores = avg(_heuristic_agent)
    print(f"[heuristico]       similitud media = {s_heur:.3f}  (solo tipos, sin layout)", flush=True)
    for (desc, _), sc in zip(targets, heur_scores):
        print(f"    {sc:.2f}  {desc[:45]}", flush=True)

    # 3B real (opcional)
    try:
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator(manifest_path="shattering/manifests/cognia_desktop.json")
        if callable(getattr(orch, "_try_load_llama", None)):
            orch._try_load_llama()
        scores = []
        for desc, tgt in targets:
            r = attempt_reproduce(tgt, desc, _real_3b_agent(orch, tgt), run_tool)
            scores.append(r["similarity"]["score"])
        print(f"\n[3B REAL]          similitud media = {sum(scores)/len(scores):.3f}", flush=True)
        for (desc, _), sc in zip(targets, scores):
            print(f"    {sc:.2f}  {desc[:45]}", flush=True)
    except Exception as e:
        print(f"\n[3B REAL] no disponible: {e}", flush=True)

    ms_settle, ms_render, ms_sim = _bench()
    print(f"\n[bench super-optimizado] settle {ms_settle:.2f}ms | render "
          f"{ms_render:.2f}ms | similarity {ms_sim:.3f}ms (12 objetos, CPU)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
