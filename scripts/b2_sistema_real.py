"""
b2_sistema_real.py — el DESPERDICIO DE ORQUESTACION.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_sistema_real.py

QUE MIDE (FASE B2, orden del dueno): cuantas tareas resuelve correctamente AL
MENOS UN modelo del pool y el SISTEMA falla igual. Esa es capacidad ya pagada
que no se esta cobrando.

Corre el MISMO set de scripts/b1_tareas.json por el camino REAL del sistema
(Cognia.construir_web -> diseno_a_codigo, que es el lazo de produccion para web:
ruteo, mockup, arbitro y reparacion incluidos) y juzga con el MISMO contrato
pre-escrito. Despues cruza con los resultados de b1_router_oraculo.py.

La diferencia entre las dos corridas NO es de modelos: en las dos generan los
mismos pesos. Es de orquestacion. Por eso lo que salga es atribuible al lazo.

Requiere haber corrido antes:  scripts/b1_router_oraculo.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas.json"
BASE = RAIZ / "cognia" / "program_creator" / "generated_programs"
# El re-juzgado manda si existe: es el mismo HTML con el juez ya corregido.
ORACULO_REJUZGADO = BASE / "b1_oraculo" / "resultados_rejuzgado.json"
ORACULO = BASE / "b1_oraculo" / "resultados.json"
SALIDA = BASE / "b2_sistema_real"


def correr_sistema(idea: str, destino: Path, *, candidatos: int = 1,
                   rondas_progreso: int | None = None,
                   max_rondas: int | None = None
                   ) -> tuple[str | None, float, str, dict]:
    """
    El camino de produccion para web. Devuelve (html, segundos, como).

    Se intenta primero el lazo completo (diseno_a_codigo.construir_para_mockup,
    que es lo que usa /construir); si no esta disponible se cae al camino de
    create_program, y se DICE cual se uso — no se finge que corrio el lazo.
    """
    import os
    t0 = time.time()
    os.environ.pop("COGNIA_CONSTRUCTOR_URL", None)   # que rutee EL sistema
    from cognia import backend_activo
    backend_activo.resetear_cache()

    # La meta del lazo se conserva AUNQUE el lazo no produzca HTML: en esas
    # filas es donde el A/B necesita ver cuantos candidatos quemo el BoN y
    # por que corto (hallazgo del revisor 2026-07-26).
    meta: dict = {}

    try:
        from cognia.program_creator import diseno_a_codigo
        # llm=None: cada pieza usa llm_local (/v1/chat/completions, auditado).
        # La version anterior inyectaba LlamaBackend.generate (/completion con
        # prompt CRUDO) y con gpt-oss de cerebro eso hacia que el razonamiento
        # saliera en texto plano y agotara max_tokens antes del HTML: el lazo
        # rechazaba la generacion inicial ("no es un documento HTML completo")
        # y caia al camino corto en 5 de 6 tareas — o sea que este script no
        # media el lazo. Probe medido 2026-07-26: mismo prompt, /completion
        # stop_type=limit con el pensamiento como contenido; chat, limpio.
        llm = None
        # Firma real (diseno_a_codigo.py:183): idea posicional y el RESTO
        # keyword-only. Llamarla con destino posicional lanzaba TypeError y el
        # script caia al camino corto SIN decir que no habia medido el lazo:
        # exactamente el degradado que la Fase A2 existe para impedir. Corregido.
        # usar_mockup_imagen=False: el mockup con SDXL exige la GPU entera y
        # aqui la ocupa el cerebro; se mide el lazo de construccion+arbitro.
        res = diseno_a_codigo.construir_para_mockup(
            idea, llm=llm, usar_mockup_imagen=False, verbose=False,
            candidatos_iniciales=candidatos,
            max_rondas_progreso=rondas_progreso,
            **({"max_rondas": max_rondas} if max_rondas else {}))
        # html_entregable() es lo que el sistema ENTREGA (sprites embebidos);
        # .html es el fuente limpio que ve el LLM al reparar. Se prefiere el
        # entregable: es el producto, no el intermedio.
        html = None
        try:
            html = res.html_entregable()
        except Exception:
            pass
        html = html or getattr(res, "html", None)
        # Meta del lazo para la salida: sello interno, rondas y BoN. Permite
        # atribuir el resultado (¿lo salvo el BoN? ¿remato una ronda extra?)
        # sin re-leer logs.
        meta = {"rondas": res.rondas, "sello_lazo": res.sello,
                "motivo_corte": res.motivo_corte, "bon": res.bon}
        if html:
            return (html, time.time() - t0,
                    f"diseno_a_codigo ({res.rondas} rondas, "
                    f"nota_visual={res.nota_visual})", meta)
        # Si el lazo no produjo programa, decir POR QUE en vez de caer mudo.
        print(f"    el lazo completo no produjo programa "
              f"(rondas={getattr(res, 'rondas', '?')}, "
              f"motivo_corte={getattr(res, 'motivo_corte', '?')!r}, "
              f"defectos={len(getattr(res, 'defectos', []))}); cae al corto",
              flush=True)
    except Exception as exc:
        print(f"    lazo completo no disponible: {type(exc).__name__}: {exc}",
              flush=True)

    # Camino de create_program (el que produjo los productos del index).
    try:
        from cognia.program_creator.generator import _call_llm, _parse_response
        crudo = _call_llm(idea, "html", temperature=0.2)
        if not crudo:
            return (None, time.time() - t0,
                    "create_program (sin respuesta)", meta)
        html = None
        try:
            prog = _parse_response(crudo, lenguaje="html")
            html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
        except Exception:
            pass
        if not html and "```" in crudo:
            trozo = crudo.split("```")[1]
            html = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
        return (html or None), time.time() - t0, "create_program", meta
    except Exception as exc:
        return (None, time.time() - t0,
                f"ERROR {type(exc).__name__}: {exc}", meta)


def main(argv: list) -> int:
    # Igual que el CLI real: sin apply_config(), LLAMA_SERVER_PATH y
    # LLAMA_GGUF_PATH no estan en el entorno y LlamaBackend elige un GGUF al
    # azar. El aviso ruidoso de la Fase A2 lo delato en la primera corrida.
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    datos = json.loads(TAREAS.read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]
    # Brazos del A/B de PREREG_BON_RONDAS_20260726.md. Sin flags = config final.
    def _flag_entero(nombre: str):
        if nombre not in argv:
            return None
        try:
            return int(argv[argv.index(nombre) + 1])
        except (IndexError, ValueError):
            print(f"uso: {nombre} <entero>", file=sys.stderr)
            raise SystemExit(2)

    candidatos = _flag_entero("--candidatos") or 1
    rondas_progreso = _flag_entero("--rondas-progreso")
    max_rondas = _flag_entero("--max-rondas")
    if candidatos > 1 or rondas_progreso or max_rondas:
        print(f"  config: candidatos={candidatos}, "
              f"rondas_progreso={rondas_progreso}, "
              f"max_rondas={max_rondas}\n", flush=True)

    fuente = ORACULO_REJUZGADO if ORACULO_REJUZGADO.is_file() else ORACULO
    if not fuente.is_file():
        print(f"Falta {fuente}. Corre antes scripts/b1_router_oraculo.py",
              file=sys.stderr)
        return 1
    print(f"  oraculo leido de: {fuente.name}\n", flush=True)
    oraculo = json.loads(fuente.read_text(encoding="utf-8"))

    SALIDA.mkdir(parents=True, exist_ok=True)
    reales: dict = {}

    print(f"Sistema REAL sobre {len(tareas)} tareas\n", flush=True)
    for t in tareas:
        d = SALIDA / t["id"]
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {t['id']} ...", flush=True)
        html, segs, como, meta = correr_sistema(
            t["idea"], d, candidatos=candidatos,
            rondas_progreso=rondas_progreso, max_rondas=max_rondas)
        if not html:
            reales[t["id"]] = {"aprobado": False, "motivo": "sin HTML",
                               "segundos": segs, "como": como, **meta}
            print(f"    SIN HTML ({segs:.0f}s, via {como})", flush=True)
            continue
        (d / "index.html").write_text(html, encoding="utf-8")
        v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
        reales[t["id"]] = {"aprobado": v.aprobado, "motivo": v.motivo[:120],
                           "segundos": segs, "como": como,
                           "checks_ok": sum(1 for c in v.checks if c.ok),
                           "checks": len(v.checks), **meta}
        print(f"    {'APROBADO' if v.aprobado else 'FALLIDO '} "
              f"({segs:.0f}s, via {como})", flush=True)

    # ── el cruce ──────────────────────────────────────────────────────────
    res_or = oraculo["resultados"]
    print(f"\n\n{'=' * 84}")
    print("B2 — DESPERDICIO DE ORQUESTACION")
    print("=" * 84)
    print(f"{'TAREA':<18}{'ORACULO (algun modelo)':>26}{'SISTEMA REAL':>18}"
          f"{'':>4}{'DESPERDICIO':>16}")
    print("-" * 84)
    desperdicio = []
    for t in tareas:
        tid = t["id"]
        alguno = any(r.get("aprobado")
                     for r in res_or.get(tid, {}).values())
        real = reales.get(tid, {}).get("aprobado", False)
        malo = alguno and not real
        if malo:
            desperdicio.append(tid)
        print(f"{tid:<18}{('RESUELTA' if alguno else 'nadie la resuelve'):>26}"
              f"{('OK' if real else 'falla'):>18}{'':>4}"
              f"{('<-- DESPERDICIADA' if malo else ''):>16}")
    print("-" * 84)
    n = len(tareas)
    techo = sum(1 for t in tareas
                if any(r.get("aprobado") for r in res_or.get(t["id"], {}).values()))
    real_n = sum(1 for t in tareas if reales.get(t["id"], {}).get("aprobado"))
    print(f"\n  Techo del pool (ruteo perfecto) : {techo}/{n}")
    print(f"  Sistema real                    : {real_n}/{n}")
    print(f"  DESPERDICIO DE ORQUESTACION     : {len(desperdicio)}/{n}"
          f"  {desperdicio}")
    print("\n  Esas son tareas que el hardware YA resuelve y el lazo pierde. "
          "No hacen falta pesos nuevos para ganarlas.")

    salida = SALIDA / "resultados.json"
    salida.write_text(json.dumps(
        {"config": {"candidatos": candidatos,
                    "rondas_progreso": rondas_progreso,
                    "max_rondas": max_rondas},
         "sistema_real": reales, "techo": techo, "real": real_n,
         "desperdicio": desperdicio, "n_tareas": n},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
