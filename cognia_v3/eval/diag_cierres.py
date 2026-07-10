# -*- coding: utf-8 -*-
"""Diagnóstico CIERRES (G6): cuando una tool PRODUCE UNA SALIDA (ejecutar
python, calcular, leer, contar), ¿el modelo la REPORTA en su respuesta final
o cierra con un "Listo, tarea completada" vacío?

50 tareas de agente es+en (suite congelada g6_cierres.jsonl) con clasificación
determinista del fallo:
  - vacio      : cierra sin reportar la salida ("listo", "completada")  -> FORMATO
  - parcial    : menciona que hubo salida/fallo pero no el valor        -> FORMATO
  - incorrecto : reporta un valor concreto pero está MAL                -> CAPACIDAD
  - pasa       : la respuesta final contiene la salida esperada
Mismo patrón que diag_json.py: medir el gap ANTES de construir el experto
accion v3 (PLAN_MOM_GLM52 §2 fila 2).

PARCHE DESACTIVADO (crítico — si se mide con el parche puesto, se mide el
parche y la señal es CERO):
  hoy el hábito está TAPADO por el "cierre informativo E8" (determinista):
    (1) nudge en cierre-por-prosa    cognia/cli.py ~7636
    (2) nudge en cierre-por-responder cognia/cli.py ~7679
    (3) anexo post-loop de la salida real cognia/cli.py ~7778
        (usa salida_de_ejecucion(history) y pega "Salida de la ejecución: ...")
  Los TRES sitios están gateados por cognia.agent.loop.task_pide_ejecucion,
  y cli.py la importa DENTRO de _run_agent_task (import en tiempo de llamada),
  así que monkeypatchear el atributo del módulo (desactivar_parche_cierre)
  apaga el parche completo sin tocar producción. salida_de_ejecucion también
  se anula como cinturón-y-tiradores. Test de regresión del mecanismo en
  tests/test_suite_cierres.py.

SUITE CONGELADA (freeze pre-medición, anti-Goodhart):
  g6_cierres.jsonl  50 ítems  2026-07-10
  sha256 = 59d53ec8ca9c3bb0a25ca6851c4c4166ca3b3195c8da9fc694194bc84bdea33f
  main() ABORTA si el hash del archivo no coincide (una suite congelada no se
  edita: cambio = suite nueva con otro nombre).

BANDAS PRE-REGISTRADAS (se imprimen como veredicto, no se ajustan después):
  - pasa >= 85%                        -> gap chico: línea CERRADA, nada que entrenar
  - FORMATO (vacio+parcial) >= 60% de los fallos -> gap de FORMATO: apto experto accion v3
  - si no                              -> CAPACIDAD dominante: NO fine-tune (E-RZN/E-COD)

Uso (lo corre el ORQUESTADOR, con el modelo real serializado — no correr en
paralelo con otro consumidor del server :8088):
  .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.diag_cierres [N_LIMIT]
No setea LLAMA_GGUF_PATH/LLAMA_*: el stack instalado resuelve el modelo por
config.env y setear esas env vars mata el fleet (lección 2026-07-09).
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "cognia_v3" / "eval" / "suites"))
from suite_oracle import carga_suite, cierre_pass, fold, numeros_todos  # noqa: E402

SUITE = REPO / "cognia_v3" / "eval" / "suites" / "g6_cierres.jsonl"
SUITE_SHA256 = "59d53ec8ca9c3bb0a25ca6851c4c4166ca3b3195c8da9fc694194bc84bdea33f"

RESULTS = REPO / "cognia_v3" / "eval" / "results_diag_cierres.json"
PROGRESS = REPO / "cognia_v3" / "eval" / "results_diag_cierres.progress.jsonl"


# ── clasificador determinista (puro, testeable sin modelo) ──────────────────

# menciona salida O fallo sin dar el valor/causa -> parcial (FORMATO)
_MENCION_SALIDA = ("salida", "output", "resultado", "imprim", "print",
                   "devolv", "devuelve", "return", "stdout", "arroj",
                   "produjo", "produce",
                   # fallo mencionado sin detalle accionable
                   "error", "fallo", "falla", "exception", "no pude",
                   "no se pudo", "failed")


def menciona_salida_o_fallo(respuesta: str) -> bool:
    r = fold(respuesta or "")
    return any(k in r for k in _MENCION_SALIDA)


# span citado 'corto y sin espacios/puntuación' = contenido CONCRETO afirmado.
# Deliberadamente estricto: "doesn't exist, I couldn't" produce pseudo-spans
# entre apóstrofes que NO deben contar como valor afirmado (la atribución a
# CAPACIDAD exige evidencia fuerte; el default de un fallo es FORMATO).
_QUOTE_RX = re.compile(r"['\"]([a-z0-9_.-]{3,30})['\"]")
# token raro con guiones (sandia-7717, mango-4411): patrón de los valores G6
_TOKEN_RX = re.compile(r"(?<![a-z0-9-])[a-z0-9]+(?:-[a-z0-9]+)+(?![a-z0-9-])")


def reporta_valor_ajeno(respuesta: str, prompt: str) -> bool:
    """¿La respuesta AFIRMA un valor concreto que NO viene del enunciado?
    (Si viniera del enunciado sería eco, no reporte.) Señales, en orden:
      a) número |n|>=10 que no aparece en el prompt (los <10 son ruido de
         prosa: 'en 3 pasos', 'los 2 archivos');
      b) span citado corto sin espacios que no está en el prompt;
      c) token con guiones (estilo de los valores G6) que no está en el prompt.
    Se usa DESPUÉS de cierre_pass: si el valor fuera el correcto ya habría
    pasado, así que un valor ajeno aquí es un valor INCORRECTO."""
    r, p = fold(respuesta or ""), fold(prompt or "")
    nums_p = numeros_todos(prompt or "")
    for n in numeros_todos(respuesta or ""):
        if abs(n) >= 10 and not any(abs(n - q) <= 1e-6 for q in nums_p):
            return True
    for m in _QUOTE_RX.finditer(r):
        if m.group(1) not in p:
            return True
    for m in _TOKEN_RX.finditer(r):
        if m.group(0) not in p:
            return True
    return False


def clasificar_cierre(respuesta: str, oracle: dict, prompt: str = "") -> str:
    """pasa / incorrecto / parcial / vacio (ver docstring del módulo).
    El orden importa: valor-correcto > valor-equivocado > mención-sin-valor >
    nada. El sesgo es deliberado: CAPACIDAD (incorrecto) solo con evidencia
    fuerte de un valor afirmado; la duda cae en FORMATO (vacio/parcial)."""
    if not (respuesta or "").strip():
        return "vacio"
    if cierre_pass(respuesta, oracle):
        return "pasa"
    if reporta_valor_ajeno(respuesta, prompt):
        return "incorrecto"
    if menciona_salida_o_fallo(respuesta):
        return "parcial"
    return "vacio"


# ── desactivación del parche + espía de tools (monkeypatch documentado) ─────

def desactivar_parche_cierre():
    """Apaga el 'cierre informativo E8' completo monkeypatcheando
    cognia.agent.loop (los 3 sitios de cli.py gatean por task_pide_ejecucion,
    importada en tiempo de llamada -> el patch del atributo alcanza).
    Devuelve una función restore()."""
    import cognia.agent.loop as loop_mod
    orig_tpe = loop_mod.task_pide_ejecucion
    orig_sde = loop_mod.salida_de_ejecucion
    loop_mod.task_pide_ejecucion = lambda task: False
    loop_mod.salida_de_ejecucion = lambda history: ""

    def restore():
        loop_mod.task_pide_ejecucion = orig_tpe
        loop_mod.salida_de_ejecucion = orig_sde
    return restore


def espiar_run_tool(traza: list):
    """Envuelve cognia.agent.tools.run_tool para registrar qué tools corrió el
    agente en el ítem (cli.py también la importa en tiempo de llamada). El
    registro alimenta el flag `ejecuto`: un 'incorrecto' SIN ejecución es
    adivinanza/alucinación (hábito), no error de transcripción. Devuelve
    restore()."""
    import cognia.agent.tools as tools_mod
    real = tools_mod.run_tool

    def spy(name, args, ctx):
        out = real(name, args, ctx)
        traza.append({"tool": name,
                      "ok": not re.search(r"\bERROR\b", out[:120]),
                      "head": out[:200]})
        return out
    tools_mod.run_tool = spy
    return lambda: setattr(tools_mod, "run_tool", real)


# ── corrida real (SOLO el orquestador; serializa el server :8088) ───────────

def main():
    try:  # consola Windows cp1252: no morir imprimiendo respuestas del modelo
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None

    h = hashlib.sha256(SUITE.read_bytes()).hexdigest()
    if h != SUITE_SHA256:
        print(f"[diag-cierres] ABORT: sha256 de {SUITE.name} = {h[:16]}… no "
              f"coincide con el freeze {SUITE_SHA256[:16]}…. Una suite "
              "congelada NO se edita (cambio = suite nueva).")
        sys.exit(1)
    items = carga_suite(str(SUITE))
    if limit:
        items = items[:limit]

    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:  # mínimo que _run_agent_task necesita (mismo patrón que la batería)
        pass
    ai = _AI()
    ai._orchestrator = orch

    restaurar_parche = desactivar_parche_cierre()
    # verificación de que el patch tomó (si cli.py cambia el gating, esto avisa)
    import cognia.agent.loop as _lm
    assert not _lm.task_pide_ejecucion("ejecutá el script x.py"), \
        "el parche E8 NO quedó desactivado"
    print(f"[diag-cierres] parche E8 DESACTIVADO — {len(items)} ítems, "
          f"suite sha256={h[:16]}…", flush=True)

    res = {"pasa": [], "vacio": [], "parcial": [], "incorrecto": []}
    t0 = time.time()
    try:
        for it in items:
            ws = Path(tempfile.mkdtemp(prefix="g6_")).resolve()
            for s in it.get("setup") or []:
                p = ws / s["path"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(s["content"], encoding="utf-8")
            traza = []
            restaurar_espia = espiar_run_tool(traza)
            prev_cwd = os.getcwd()
            prev_root = dev_tools.AGENT_WORKSPACE_ROOT
            dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
            os.chdir(ws)
            t_it = time.time()
            try:
                resp = _cli._run_agent_task(ai, it["prompt"], lambda s: None,
                                            max_steps=8)
            except Exception as exc:
                resp = f"(EXCEPTION del loop: {exc})"
            finally:
                os.chdir(prev_cwd)
                dev_tools.AGENT_WORKSPACE_ROOT = prev_root
                restaurar_espia()
            resp = str(resp or "")
            clase = clasificar_cierre(resp, it["oracle"], it["prompt"])
            rec = {"id": it["id"], "dominio": it["dominio"],
                   "idioma": it["idioma"], "clase": clase,
                   "ejecuto": bool(traza),
                   "tools": [t["tool"] for t in traza][:12],
                   "secs": round(time.time() - t_it, 1),
                   "resp": resp[:300]}
            res[clase].append(rec)
            with open(PROGRESS, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  [{clase:10s}] {it['id']} ({it['dominio'][:12]}) "
                  f"ejecuto={'si' if traza else 'NO'} "
                  f"{rec['secs']:6.1f}s : {resp[:60]!r}", flush=True)
    finally:
        restaurar_parche()

    n = sum(len(v) for v in res.values())
    n_pasa = len(res["pasa"])
    fallos = n - n_pasa
    formato = len(res["vacio"]) + len(res["parcial"])
    adivino = sum(1 for r in res["incorrecto"] if not r["ejecuto"])
    por_dom = {}
    for clase, recs in res.items():
        for r in recs:
            d = por_dom.setdefault(r["dominio"], {"pasa": 0, "vacio": 0,
                                                  "parcial": 0, "incorrecto": 0})
            d[clase] += 1

    RESULTS.write_text(json.dumps(
        {"suite_sha256": SUITE_SHA256, "n": n, "clases": res,
         "por_dominio": por_dom, "mins": round((time.time() - t0) / 60, 1)},
        indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"\n[diag-cierres] pasa={n_pasa}/{n}  "
          f"vacio(FORMATO)={len(res['vacio'])}  "
          f"parcial(FORMATO)={len(res['parcial'])}  "
          f"incorrecto(CAPACIDAD)={len(res['incorrecto'])} "
          f"(de los cuales SIN ejecutar/adivinanza={adivino})  "
          f"({(time.time() - t0) / 60:.1f} min)")
    for d, c in sorted(por_dom.items()):
        tot = sum(c.values())
        print(f"    {d:18s} pasa={c['pasa']}/{tot}  vacio={c['vacio']}  "
              f"parcial={c['parcial']}  incorrecto={c['incorrecto']}")

    # veredicto por bandas PRE-REGISTRADAS (docstring; no ajustar post-hoc)
    if n and n_pasa / n >= 0.85:
        print("[veredicto] GAP CHICO (pasa>=85%): línea CERRADA, nada que entrenar.")
    elif fallos and formato / fallos >= 0.60:
        print(f"[veredicto] GAP DE FORMATO ({formato}/{fallos} de los fallos): "
              "apto para experto accion v3 (cierre-con-salida).")
    else:
        print("[veredicto] CAPACIDAD dominante en los fallos: NO fine-tune "
              "(3ra negativa E-RZN/E-COD aplica).")


if __name__ == "__main__":
    main()
