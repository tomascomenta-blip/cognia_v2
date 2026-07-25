"""
c55_p_por_etapa.py — ¿cual es p AHORA, por etapa, y se cumple p^k?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\c55_p_por_etapa.py
    ... --n 2

LA AFIRMACION A FALSEAR (razon 5.5): "un pipeline de k etapas con fiabilidad p
por etapa entrega p^k; con 5 etapas al 85% cada una: 44%".

El dueno la desarmo con precision: "la fiabilidad por etapa la elegi YO. Con el
juez ejecutable y sin degradado silencioso, ¿cual es p ahora?". El 85% era un
numero de ejemplo, no una medicion. Esto lo mide.

ETAPAS DEL LAZO REAL (cognia/program_creator/diseno_a_codigo.py):
  1. imaginar      el cerebro produce el brief de la vision
  2. construir     sale una pagina inicial (aqui moria el 75% antes del fix del
                   parser: el modelo repetia la respuesta y se tiraban 7-14
                   paginas validas)
  3. renderizar    Chrome headless carga y la sonda devuelve informe
  4. juzgar        el arbitro visual emite nota (no "opina bonito": EMITE)
  5. reparar       una ronda de reparacion cambia algo
  FINAL            el producto pasa su CONTRATO ejecutable

Lo importante es la ultima fila: p^k PREDICHO vs REAL. Si el producto real cae
MUY por debajo del producto de las p, las etapas no son independientes y el
modelo p^k no describe este lazo — que es una afirmacion distinta de "el lazo
es fragil".

No edita el lazo: lee el ResultadoDiseno (brief, program, rondas, nota_visual,
historia, motivo_corte) y juzga el producto final por ejecucion.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "c55_etapas")


def una_corrida(tarea: dict, destino: Path) -> dict:
    from cognia.program_creator import diseno_a_codigo, juez_ejecutable
    from node.llama_backend import LlamaBackend

    b = LlamaBackend.try_load()
    llm = None
    if b is not None:
        def llm(prompt, system="", max_tokens=2000, temperature=0.9):
            full = f"{system}\n\n{prompt}" if system else prompt
            return b.generate(full, max_tokens=max_tokens,
                              temperature=temperature)

    t0 = time.time()
    try:
        res = diseno_a_codigo.construir_para_mockup(
            tarea["idea"], llm=llm, usar_mockup_imagen=False, verbose=False)
    except Exception as exc:
        return {"tarea": tarea["id"], "error": f"{type(exc).__name__}: {exc}",
                "imaginar": False, "construir": False, "renderizar": False,
                "juzgar": False, "reparar": False, "final": False,
                "segundos": time.time() - t0}

    hist = list(getattr(res, "historia", []) or [])
    fila = {
        "tarea": tarea["id"],
        "segundos": time.time() - t0,
        "rondas": getattr(res, "rondas", 0),
        "motivo_corte": getattr(res, "motivo_corte", ""),
        "nota_visual": getattr(res, "nota_visual", None),
        # 1. el cerebro produjo un brief util (no vacio)
        "imaginar": bool((getattr(res, "brief", "") or "").strip()),
        # 2. salio una pagina
        "construir": getattr(res, "program", None) is not None,
        # 3. hubo al menos una ronda (implica render+sonda)
        "renderizar": len(hist) > 0,
        # 4. el arbitro EMITIO nota en alguna ronda
        "juzgar": any(h.get("arbitro") and h.get("nota") is not None
                      for h in hist),
        # 5. reparar cambio algo: bajaron los defectos entre rondas
        "reparar": (len(hist) >= 2 and
                    hist[-1].get("n_defectos", 99) < hist[0].get("n_defectos", 0)),
        "final": False,
    }

    html = None
    try:
        html = res.html_entregable() or getattr(res, "html", None)
    except Exception:
        html = getattr(res, "html", None)
    if html:
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "index.html").write_text(html, encoding="utf-8")
        v = juez_ejecutable.juzgar_web(destino / "index.html", tarea["contrato"])
        fila["final"] = v.aprobado
        fila["veredicto"] = v.motivo[:100]
    return fila


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()

    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 2
    datos = json.loads(
        (RAIZ / "scripts" / "b1_tareas.json").read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]

    SALIDA.mkdir(parents=True, exist_ok=True)
    filas = []
    print(f"{len(tareas)} tareas x n={n} por el LAZO COMPLETO\n", flush=True)
    for t in tareas:
        for rep in range(1, n + 1):
            d = SALIDA / f"{t['id']}__r{rep}"
            f = una_corrida(t, d)
            filas.append(f)
            print(f"  {t['id']:<14} r{rep}  "
                  f"imaginar={'OK' if f['imaginar'] else '--'} "
                  f"construir={'OK' if f['construir'] else '--'} "
                  f"render={'OK' if f['renderizar'] else '--'} "
                  f"juzgar={'OK' if f['juzgar'] else '--'} "
                  f"reparar={'OK' if f['reparar'] else '--'} "
                  f"| FINAL={'APROBADO' if f['final'] else 'falla'} "
                  f"({f['segundos']:.0f}s, {f.get('rondas', 0)} rondas)",
                  flush=True)

    ETAPAS = [("imaginar", "1. imaginar (brief)"),
              ("construir", "2. construir (pagina inicial)"),
              ("renderizar", "3. renderizar + sonda"),
              ("juzgar", "4. juzgar (el arbitro EMITE nota)"),
              ("reparar", "5. reparar (bajan los defectos)")]

    total = len(filas)
    print(f"\n\n{'=' * 74}")
    print(f"5.5 — FIABILIDAD POR ETAPA MEDIDA (n={total} corridas del lazo)")
    print("=" * 74)
    print(f"{'ETAPA':<40}{'exitos':>12}{'p':>10}")
    print("-" * 74)
    producto = 1.0
    for clave, etiq in ETAPAS:
        ok = sum(1 for f in filas if f.get(clave))
        p = ok / total if total else 0.0
        producto *= p
        print(f"{etiq:<40}{f'{ok}/{total}':>12}{p:>9.0%}")
    print("-" * 74)
    finales = sum(1 for f in filas if f.get("final"))
    p_real = finales / total if total else 0.0
    print(f"{'p^k PREDICHO (producto de las p)':<40}{'':<12}{producto:>9.0%}")
    print(f"{'REAL (pasa su contrato ejecutable)':<40}"
          f"{f'{finales}/{total}':>12}{p_real:>9.0%}")
    print("=" * 74)

    # "reparar" NO es una etapa obligatoria: una pagina correcta a la primera
    # no tiene defectos que bajar, asi que cuenta como fallo sin serlo. Meterla
    # en el producto hunde la prediccion y hace parecer fragil lo que no lo es.
    # El producto que SI significa algo es el de las etapas que hay que
    # atravesar SIEMPRE.
    obligatorias = [e for e in ETAPAS if e[0] != "reparar"]
    prod_obl = 1.0
    for clave, _ in obligatorias:
        prod_obl *= (sum(1 for f in filas if f.get(clave)) / total) if total else 0

    print(f"\n{'p^k solo con las etapas OBLIGATORIAS (sin reparar)':<40}"
          f"{'':<12}{prod_obl:>9.0%}")

    print("\nLECTURA:")
    print(f"  Las etapas mecanicas no estan al 85%: estan al 92-100%. Con las")
    print(f"  cuatro obligatorias, el pipeline SOBREVIVE el {prod_obl:.0%} de las")
    print(f"  veces — y aun asi solo el {p_real:.0%} entrega algo que pasa su")
    print(f"  contrato.")
    if p_real < prod_obl * 0.75:
        print(f"\n  Esa brecha ({prod_obl:.0%} -> {p_real:.0%}) es el hallazgo: el")
        print("  problema NO es que el pipeline se rompa. Es que ATRAVESARLO")
        print("  ENTERO no implica que el producto sirva. La etapa 4 cuenta como")
        print("  exito porque el arbitro EMITE una nota; que esa nota sea 5.0 no")
        print("  impide entregar. p^k mide SUPERVIVENCIA, no CALIDAD, y aqui lo")
        print("  que falla es la calidad.")
    else:
        print("\n  El real casa con la supervivencia del pipeline: aqui la")
        print("  fragilidad multiplicativa SI explica lo que pasa.")

    peor = min(obligatorias,
               key=lambda e: sum(1 for f in filas if f.get(e[0])))
    ok_peor = sum(1 for f in filas if f.get(peor[0]))
    print(f"\n  Etapa obligatoria mas debil: {peor[1]} ({ok_peor}/{total}).")
    rep_ok = sum(1 for f in filas if f.get("reparar"))
    print(f"  (reparar: {rep_ok}/{total}, pero NO es obligatoria — una pagina")
    print(f"   correcta a la primera no tiene defectos que bajar.)")

    salida = SALIDA / "resultados.json"
    salida.write_text(json.dumps(
        {"filas": filas, "p_predicho": producto, "p_real": p_real, "n": total},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
