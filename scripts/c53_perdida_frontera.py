"""
c53_perdida_frontera.py — ¿cuanta capacidad se pierde al cuantizar a TEXTO?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\c53_perdida_frontera.py

LA AFIRMACION A FALSEAR (razon 5.3 del informe): "cada frontera entre roles
cuantiza a texto; el pensador no le pasa al constructor su estado latente, le
pasa un parrafo". Se presenta como ley; es una hipotesis medible.

EL EXPERIMENTO, exactamente como lo pidio el dueno: el MISMO modelo haciendo
diseno+codigo en UN SOLO contexto, contra el mismo trabajo PARTIDO en dos
llamadas con handoff de texto.

  A) JUNTO   — una sola llamada: "disena y despues implementa".
               El razonamiento del diseno queda en el contexto al escribir el
               codigo. No hay frontera.
  B) PARTIDO — llamada 1: solo el diseno, en prosa (lo que cruzaria la frontera).
               llamada 2: contexto NUEVO, solo recibe ese texto, e implementa.
               Es la frontera, aislada.

Mismo modelo, misma temperatura, mismas tareas, mismo juez ejecutable con el
contrato pre-escrito de scripts/b1_tareas.json. Lo unico que cambia es si hay
frontera. Si A y B empatan, la razon 5.3 no se sostiene EN ESTE SET.

n repeticiones por celda (default 3) porque una sola corrida no distingue
regresion de ruido — la regla de [[gate-e2e-flaky]] del propio proyecto.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "c53_frontera")

_SYS_DISENO = (
    "Eres un disenador de producto. Describes en prosa como debe funcionar y "
    "verse una pagina web: estructura, elementos, estados y comportamiento al "
    "interactuar. NO escribes codigo."
)

_PROMPT_JUNTO = """\
{idea}

Primero razona el diseno: que elementos hay, en que estado arrancan y que pasa
al interactuar. Despues, en el MISMO mensaje, escribe el HTML completo en un
unico bloque ```html.
"""

_PROMPT_DISENO = """\
{idea}

Describe en prosa el diseno y el COMPORTAMIENTO de esta pagina: que elementos
hay, en que estado arrancan y que ocurre en cada interaccion. No escribas codigo.
"""

_PROMPT_DESDE_TEXTO = """\
Implementa esta especificacion como un unico archivo HTML completo, en un bloque
```html. Respeta EXACTAMENTE los ids y clases que se mencionan.

ESPECIFICACION:
{diseno}
"""


def _html_de(crudo: str | None) -> str | None:
    if not crudo:
        return None
    if "```" in crudo:
        trozo = crudo.split("```")[1]
        trozo = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
        return trozo if "<" in trozo else None
    return crudo if "<" in crudo else None


def _pedir(prompt: str, system: str, max_tokens: int, via: str) -> str | None:
    from cognia.llm_local import generar
    return generar(prompt, system=system, temperature=0.2,
                   max_tokens=max_tokens, via=via, timeout=400)


def junto(idea: str) -> tuple[str | None, float]:
    from cognia.program_creator.generator import _SISTEMA_WEB
    t0 = time.time()
    crudo = _pedir(_PROMPT_JUNTO.format(idea=idea), _SISTEMA_WEB, 6000,
                   "c53.junto")
    return _html_de(crudo), time.time() - t0


def partido(idea: str) -> tuple[str | None, float, str]:
    """
    Dos llamadas SIN estado compartido. Lo unico que cruza es el texto del
    diseno: eso es exactamente la frontera que la razon 5.3 acusa.
    """
    from cognia.program_creator.generator import _SISTEMA_WEB
    t0 = time.time()
    diseno = _pedir(_PROMPT_DISENO.format(idea=idea), _SYS_DISENO, 1200,
                    "c53.partido.diseno")
    if not diseno:
        return None, time.time() - t0, ""
    crudo = _pedir(_PROMPT_DESDE_TEXTO.format(diseno=diseno), _SISTEMA_WEB,
                   6000, "c53.partido.codigo")
    return _html_de(crudo), time.time() - t0, diseno


def main(argv: list) -> int:
    from cognia.program_creator import juez_ejecutable

    n = 3
    if "--n" in argv:
        n = int(argv[argv.index("--n") + 1])
    datos = json.loads(TAREAS.read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"5.3 — {len(tareas)} tareas x 2 condiciones x n={n} "
          f"= {len(tareas) * 2 * n} generaciones\n", flush=True)

    filas = []
    for t in tareas:
        for rep in range(1, n + 1):
            for cond in ("junto", "partido"):
                d = SALIDA / f"{t['id']}__{cond}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                if cond == "junto":
                    html, segs = junto(t["idea"])
                    diseno = ""
                else:
                    html, segs, diseno = partido(t["idea"])
                    if diseno:
                        (d / "diseno.txt").write_text(diseno, encoding="utf-8")

                if not html:
                    filas.append({"tarea": t["id"], "cond": cond, "rep": rep,
                                  "aprobado": False, "segundos": segs,
                                  "motivo": "sin HTML"})
                    print(f"  {t['id']:<14} {cond:<8} r{rep}  SIN HTML "
                          f"({segs:.0f}s)", flush=True)
                    continue
                (d / "index.html").write_text(html, encoding="utf-8")
                v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
                filas.append({"tarea": t["id"], "cond": cond, "rep": rep,
                              "aprobado": v.aprobado, "segundos": segs,
                              "checks_ok": sum(1 for c in v.checks if c.ok),
                              "checks": len(v.checks),
                              "motivo": v.motivo[:110]})
                print(f"  {t['id']:<14} {cond:<8} r{rep}  "
                      f"{'APROBADO' if v.aprobado else 'FALLIDO '} "
                      f"({sum(1 for c in v.checks if c.ok)}/{len(v.checks)} "
                      f"checks, {segs:.0f}s)", flush=True)

    # ── tabla ─────────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 76}")
    print("5.3 — PERDIDA EN LA FRONTERA (mismo modelo, con y sin handoff)")
    print("=" * 76)
    print(f"{'TAREA':<16}{'JUNTO (1 contexto)':>22}{'PARTIDO (handoff)':>22}")
    print("-" * 76)
    tot_j = tot_p = 0
    for t in tareas:
        j = [f for f in filas if f["tarea"] == t["id"] and f["cond"] == "junto"]
        p = [f for f in filas if f["tarea"] == t["id"] and f["cond"] == "partido"]
        oj = sum(1 for f in j if f["aprobado"])
        op = sum(1 for f in p if f["aprobado"])
        tot_j += oj
        tot_p += op
        print(f"{t['id']:<16}{f'{oj}/{len(j)}':>22}{f'{op}/{len(p)}':>22}")
    print("-" * 76)
    total = len(tareas) * n
    print(f"{'TOTAL':<16}{f'{tot_j}/{total}':>22}{f'{tot_p}/{total}':>22}")
    print(f"\n  tasa JUNTO   : {tot_j / total:.0%}")
    print(f"  tasa PARTIDO : {tot_p / total:.0%}")
    delta = (tot_j - tot_p) / total
    print(f"  DELTA        : {delta:+.0%} "
          f"({'a favor de un solo contexto' if delta > 0 else 'sin perdida medible' if delta == 0 else 'a favor del handoff (!)'} )")
    print(f"\n  n={n} por celda. Con n chico esto NO separa regresion de ruido: "
          f"leerlo como tendencia, no como veredicto.")

    salida = SALIDA / "resultados.json"
    salida.write_text(json.dumps({"filas": filas, "n": n,
                                  "junto": tot_j, "partido": tot_p,
                                  "total": total}, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
