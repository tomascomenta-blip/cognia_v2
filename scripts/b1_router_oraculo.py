"""
b1_router_oraculo.py — el TECHO del pool con ruteo perfecto, y el desperdicio.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_router_oraculo.py
    ... --modelos construir,construir-ui,pensar   # subconjunto del pool
    ... --tareas memoria_4x4,contador             # subconjunto de tareas

QUE MIDE (FASE B, orden del dueno):

  B1. Para cada tarea del set, generar con TODOS los modelos del pool y quedarse
      a posteriori con la mejor segun el juez EJECUTABLE. Ese numero es el techo
      del pool con ruteo perfecto (un oraculo que siempre elige bien). Se compara
      contra lo que consigue el sistema real, que elige a ciegas y una sola vez.

  B2. Cuantas tareas resuelve correctamente AL MENOS UN modelo del pool y el
      sistema falla igual. Ese es el DESPERDICIO DE ORQUESTACION: capacidad ya
      pagada que no se esta cobrando.

METODO, y por que asi:

- Los contratos de scripts/b1_tareas.json estan escritos A MANO y ANTES de que
  exista ningun codigo. Un contrato escrito mirando la implementacion es un
  examen que el producto se pone a si mismo.
- Cada modelo genera por el MISMO camino que usa el sistema (generator._call_llm
  con lenguaje="html" contra COGNIA_CONSTRUCTOR_URL=:8080), asi que la
  comparacion es de modelos, no de andamiajes distintos.
- Cambiar de modelo obliga a descargar la GPU y cargar otro (16GB: la regla de
  servir_flota.py). El coste de cada swap se MIDE y se reporta: es el dato de la
  razon 5.6 ("la VRAM serializa lo que un MoE paraleliza"), que hasta ahora era
  una afirmacion sin numero.

Todo lo que devuelve es APROBADO/FALLIDO por ejecucion. No hay puntajes de
opinion en este script.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas.json"
SALIDA = RAIZ / "cognia" / "program_creator" / "generated_programs" / "b1_oraculo"
# Cada banco escribe en su propio directorio: mezclarlos haria que --reanudar
# reusara HTML de otro set con el mismo id de tarea.
SALIDA_POR_BANCO = {"b1_tareas_duras.json": "b1_duras"}

# Pool: combo de servir_flota.py -> etiqueta legible del modelo que sirve.
POOL = {
    "construir":      "qwen2.5-coder-14b",
    "construir-ui":   "UIGEN-X-8B",
    "pensar":         "gpt-oss-20b",
    "pensar-en-lazo": "OpenReasoning-Nemotron-14B",
    # Laguna XS 2.1 (33B-A3B) NO lo sirve servir_flota: llama.cpp b10066 no lo
    # soporta (hace falta el PR ggml-org/llama.cpp#25165, y en esta maquina no
    # hay cmake/CUDA/MSVC para compilarlo). Va por Ollama, que trae su propio
    # runtime y expone API OpenAI en :11434/v1. Se mide por el MISMO camino y
    # con los MISMOS contratos que los demas: la comparacion es limpia.
    "laguna":         "Laguna-XS-2.1 (33B-A3B, via ollama)",
}

# Combos que NO se sirven con servir_flota.py: {combo: url del backend}.
EXTERNOS = {"laguna": "http://127.0.0.1:11434"}


def _flota(modo: str) -> float:
    """Cambia el combo servido. Devuelve los segundos que costo el swap."""
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "servir_flota.py"), modo],
        capture_output=True, text=True)
    coste = time.time() - t0
    if r.returncode != 0:
        print(f"  [!] servir_flota {modo} fallo: {r.stderr[-300:]}",
              file=sys.stderr)
    return coste


def generar_html(idea: str, url: str = "http://127.0.0.1:8080",
                 modelo: str | None = None) -> str | None:
    """El camino real del constructor web del sistema."""
    import os
    from cognia.program_creator.generator import (_SISTEMA_WEB, _call_llm,
                                                  _parse_response)
    os.environ["COGNIA_CONSTRUCTOR_URL"] = url
    # Ollama exige el nombre EXACTO del modelo en el payload; llama-server
    # acepta cualquiera ("local"). Sin esto, Ollama responde 404 y el harness
    # lo leeria como "el modelo no devolvio HTML" — un falso KILL.
    if modelo:
        os.environ["COGNIA_CONSTRUCTOR_MODELO"] = modelo
    else:
        os.environ.pop("COGNIA_CONSTRUCTOR_MODELO", None)
    from cognia import backend_activo
    backend_activo.resetear_cache()      # el modelo del puerto cambio
    crudo = _call_llm(idea, "html", temperature=0.2)
    if not crudo:
        return None
    try:
        prog = _parse_response(crudo, lenguaje="html")
        html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
    except Exception:
        html = None
    if not html:
        # _parse_response cambia de forma entre versiones; el fence es el dato.
        if "```" in crudo:
            trozo = crudo.split("```")[1]
            html = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
        else:
            html = crudo
    return html if html and "<" in html else None


def juzgar(dir_prod: Path, contrato: dict):
    from cognia.program_creator import juez_ejecutable
    html = dir_prod / "index.html"
    return juez_ejecutable.juzgar_web(html, contrato)


def main(argv: list) -> int:
    # --tareas-json permite cambiar de banco. Hizo falta porque el set de 6
    # quedo SATURADO (gpt-oss-20b: 6/6) y un banco sin cabecera no puede medir
    # progreso hacia un modelo mas grande: no hay hueco donde verlo.
    fichero = TAREAS
    if "--tareas-json" in argv:
        fichero = Path(argv[argv.index("--tareas-json") + 1])
        if not fichero.is_absolute():
            fichero = RAIZ / fichero
    datos = json.loads(fichero.read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    modelos = list(POOL)
    print(f"banco: {fichero.name} ({len(tareas)} tareas)", flush=True)
    global SALIDA
    if fichero.name in SALIDA_POR_BANCO:
        SALIDA = SALIDA.parent / SALIDA_POR_BANCO[fichero.name]

    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]
    if "--modelos" in argv:
        modelos = argv[argv.index("--modelos") + 1].split(",")
    # n repeticiones por celda. Con n=1 no se distingue regresion de ruido —
    # es la regla propia del proyecto (gate e2e flaky, n>=6). Cada repeticion
    # es una generacion NUEVA del mismo modelo para la misma tarea.
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 1

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"Tareas: {len(tareas)}  ×  Modelos: {len(modelos)} "
          f"= {len(tareas) * len(modelos)} generaciones\n", flush=True)

    # resultados[tarea_id][modelo] = {"aprobado":bool, "motivo":str, "gen_s":float}
    resultados: dict = {t["id"]: {} for t in tareas}
    swaps: list = []
    if n > 1:
        print(f"  n={n} repeticiones por celda "
              f"({len(tareas) * len(modelos) * n} generaciones en total). "
              f"'aprobado' = mayoria de las {n}.\n", flush=True)

    for modo in modelos:
        etiqueta = POOL.get(modo, modo)
        print(f"\n{'=' * 70}\nMODELO: {etiqueta}  (combo '{modo}')\n{'=' * 70}",
              flush=True)

        # Si TODO lo de este modelo ya esta en disco, no se cambia de combo.
        # Ademas de ahorrar el swap, evita matar un llama-server que otra
        # medicion pueda estar usando: servir_flota mata antes de levantar.
        completo = all(
            (SALIDA / f"{t['id']}__{modo}"
             f"{'' if n == 1 else f'__r{rep}'}" / "index.html").is_file()
            for t in tareas for rep in range(1, n + 1))

        url_modelo = EXTERNOS.get(modo, "http://127.0.0.1:8080")
        nombre_ollama = "laguna-xs-2.1" if modo == "laguna" else None

        if modo in EXTERNOS:
            # Backend externo (Ollama): no hay combo que servir. Pero SI hay que
            # dejarle la GPU: llama-server tiene los 16GB tomados y Laguna XS
            # necesita ~20GB con los expertos en RAM.
            print(f"  backend externo en {url_modelo}: paro la flota para "
                  f"liberar GPU y RAM", flush=True)
            _flota("parar")
            time.sleep(3)
        elif "--reanudar" in argv and completo:
            print("  ya estaba completo en disco: no cambio de combo, "
                  "solo re-juzgo", flush=True)
        else:
            coste = _flota(modo)
            swaps.append({"modo": modo, "modelo": etiqueta, "segundos": coste})
            print(f"  swap de modelo: {coste:.1f}s", flush=True)

        for t in tareas:
            pasadas = []
            for rep in range(1, n + 1):
                sufijo = "" if n == 1 else f"__r{rep}"
                d = SALIDA / f"{t['id']}__{modo}{sufijo}"
                d.mkdir(parents=True, exist_ok=True)

                # Reanudacion: una corrida de 72 generaciones se corta por
                # cualquier motivo (paso el 2026-07-25 a mitad de un swap de
                # flota) y repetir lo ya generado es tirar GPU. Se rejuzga el
                # HTML guardado, que ademas es gratis y correcto: el veredicto
                # depende del juez actual, no de cuando se genero.
                if "--reanudar" in argv and (d / "index.html").is_file():
                    v = juzgar(d, t["contrato"])
                    pasadas.append({
                        "aprobado": v.aprobado, "motivo": v.motivo[:120],
                        "gen_s": 0.0, "reusado": True,
                        "checks_ok": sum(1 for c in v.checks if c.ok),
                        "checks": len(v.checks)})
                    print(f"  {t['id']:<16} r{rep} "
                          f"{'APROBADO' if v.aprobado else 'FALLIDO '} "
                          f"(reusado de disco)", flush=True)
                    continue

                t0 = time.time()
                try:
                    html = generar_html(t["idea"], url_modelo, nombre_ollama)
                except Exception as exc:
                    html = None
                    print(f"  {t['id']}: EXCEPCION al generar: {exc}",
                          flush=True)
                gen_s = time.time() - t0

                if not html:
                    pasadas.append({"aprobado": False, "gen_s": gen_s,
                                    "motivo": "el modelo no devolvio HTML"})
                    print(f"  {t['id']:<16} r{rep} SIN HTML ({gen_s:.0f}s)",
                          flush=True)
                    continue

                (d / "index.html").write_text(html, encoding="utf-8")
                v = juzgar(d, t["contrato"])
                pasadas.append({
                    "aprobado": v.aprobado, "motivo": v.motivo[:120],
                    "gen_s": gen_s,
                    "checks_ok": sum(1 for c in v.checks if c.ok),
                    "checks": len(v.checks)})
                print(f"  {t['id']:<16} r{rep} "
                      f"{'APROBADO' if v.aprobado else 'FALLIDO '} "
                      f"({sum(1 for c in v.checks if c.ok)}/"
                      f"{len(v.checks)} checks, {gen_s:.0f}s)", flush=True)

            exitos = sum(1 for p in pasadas if p["aprobado"])
            # `aprobado` con n>1 = MAYORIA. Un unico acierto de 3 no es "el
            # modelo resuelve la tarea": es que a veces le sale. Se guarda la
            # tasa entera para poder leerlo de las dos formas.
            resultados[t["id"]][modo] = {
                "aprobado": exitos * 2 > n,
                "exitos": exitos, "n": n,
                "tasa": exitos / n if n else 0.0,
                "motivo": pasadas[-1].get("motivo", "") if pasadas else "",
                "gen_s": (sum(p["gen_s"] for p in pasadas) / len(pasadas)
                          if pasadas else 0.0),
                "pasadas": pasadas}
            if n > 1:
                print(f"  {t['id']:<16} ---> {exitos}/{n}", flush=True)

    # ── B1: techo del pool con ruteo perfecto ────────────────────────────
    print(f"\n\n{'=' * 92}")
    print("B1 — TECHO DEL POOL CON RUTEO PERFECTO (oraculo a posteriori)")
    print("=" * 92)
    cab = f"{'TAREA':<16}" + "".join(f"{POOL.get(m, m)[:14]:>16}" for m in modelos)
    print(cab + f"{'ORACULO':>10}")
    print("-" * 92)
    resuelve_alguno = []
    for t in tareas:
        fila = f"{t['id']:<16}"
        alguno = False
        for m in modelos:
            r = resultados[t["id"]].get(m, {})
            celda = (f"{r.get('exitos', 0)}/{r.get('n', 1)}" if n > 1
                     else ("OK" if r.get("aprobado") else "falla"))
            fila += f"{celda:>16}"
            alguno = alguno or bool(r.get("aprobado"))
        resuelve_alguno.append(alguno)
        print(fila + f"{('RESUELTA' if alguno else 'NADIE'):>10}")
    print("-" * 92)
    n = len(tareas)
    techo = sum(resuelve_alguno)
    print(f"\nTECHO DEL POOL (ruteo perfecto): {techo}/{n} tareas")
    for m in modelos:
        indiv = sum(1 for t in tareas if resultados[t["id"]].get(m, {}).get("aprobado"))
        print(f"  {POOL.get(m, m):<30} solo: {indiv}/{n}")
    mejor = max((sum(1 for t in tareas
                     if resultados[t["id"]].get(m, {}).get("aprobado"))
                 for m in modelos), default=0)
    print(f"\n  Mejor modelo INDIVIDUAL: {mejor}/{n}")
    print(f"  Ganancia del ruteo perfecto sobre el mejor solo: "
          f"+{techo - mejor} tarea(s)")
    print("  (esa diferencia es TODO lo que el ruteo puede aportar: por encima "
          "del oraculo no hay nada que rutear)")

    # ── coste de serializar la VRAM (razon 5.6) ──────────────────────────
    if swaps:
        tot = sum(s["segundos"] for s in swaps)
        print(f"\nCOSTE DE CAMBIAR DE MODELO (razon 5.6, medido):")
        for s in swaps:
            print(f"  {s['modelo']:<30} {s['segundos']:>6.1f}s")
        print(f"  {'TOTAL':<30} {tot:>6.1f}s en {len(swaps)} swaps "
              f"({tot / len(swaps):.1f}s de media)")

    salida = SALIDA / "resultados.json"
    salida.write_text(json.dumps(
        {"resultados": resultados, "swaps": swaps,
         "techo": techo, "mejor_individual": mejor, "n_tareas": n},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    print("\nB2 (desperdicio de orquestacion) necesita la corrida del SISTEMA "
          "REAL sobre el mismo set: scripts/b2_sistema_real.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
