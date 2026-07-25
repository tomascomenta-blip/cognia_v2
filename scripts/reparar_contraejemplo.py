"""
reparar_contraejemplo.py — reparar con el CONTRAEJEMPLO, no con la traza.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\reparar_contraejemplo.py --rondas 4

QUE ES. Un bucle generar -> ejecutar -> reparar donde lo que vuelve al modelo NO
es su codigo roto ni el stack trace ni una auto-critica, sino el CONTRAEJEMPLO
CONCRETO que produjo el verificador:

    "hice click en .tile[0] y esperaba 1 carta destapada; habia 16"

POR QUE ASI, Y NO COMO TODO EL MUNDO LO HACE.

  - Auto-corregirse SIN verificador externo EMPEORA. Huang et al. ICLR 2024
    (arXiv:2310.01798): GPT-3.5 en CommonSenseQA cae de 75.8 a 38.1. La revision
    TACL de Kamoi et al. (arXiv:2406.01297) no encontro NINGUNA demostracion de
    auto-correccion exitosa con feedback del propio LLM.
  - CON verificador externo el mismo paper mide lo contrario (columna oraculo):
    75.9 -> 84.3 en GSM8K.
  - Y el detalle que ahorra construir un modulo entero: Stechly, Valmeekam &
    Kambhampati (arXiv:2402.08115) encontraron que con un verificador solido
    el RE-PROMPTING SIMPLE captura casi todo el beneficio; el texto de critica
    del LLM aporta poco sobre el bit pass/fail.
  - Peor todavia para el enfoque habitual: un estudio PREREGISTRADO con control
    placebo sobre modelos chicos congelados (arXiv:2606.31511) encontro que
    pasar el codigo fallido y la traza de ejecucion EMPATA CON UN PLACEBO SIN
    CONTENIDO. Lo unico que cargo senal real fueron contrafactuales ejecutables
    producidos externamente. Que es exactamente lo que este juez ya produce.

Cognia tiene la pieza por accidente afortunado: juez_ejecutable ya devuelve
"visibles('.tile')=16, esperaba 0" — un contraejecutable, no una opinion.

TOPE DE RONDAS: 3-4. Convergencia entre fuentes independientes: 2 rondas
capturan el 76-95% de la ganancia (arXiv:2604.10508); TDDev, que es este mismo
dominio con Playwright, satura en k=4-5 (arXiv:2605.17242). La 5a ronda es gasto.

COMPARACION JUSTA: se mide contra best-of-N al MISMO compute. 4 rondas de
reparacion cuestan lo mismo que 4 muestras independientes; la pregunta es cual
de los dos rinde mas por segundo.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "reparacion")

_PROMPT_REPARAR = """\
Tu pagina NO cumple su especificacion. Un navegador real la abrio, interactuo
con ella y encontro esto:

{contraejemplos}

Corrige el codigo para que esos hechos se cumplan. Devuelve la pagina COMPLETA
en un unico bloque ```html. No expliques nada.

PAGINA ACTUAL:
```html
{codigo}
```
"""


def contraejemplos_de(veredicto) -> str:
    """
    Los checks que FALLARON, como hechos observados. Nada de opiniones.

    Se pasan solo los fallidos: mandarle los que pasaron gasta contexto y lo
    invita a "arreglar" lo que ya funciona (medido en este repo el 2026-07-20:
    a temperatura alta el modelo reescribia media pagina al reparar).
    """
    malos = [c for c in veredicto.checks if not c.ok]
    if not malos:
        return ""
    lineas = []
    for c in malos:
        marca = "OBLIGATORIO" if c.critico else "esperado"
        lineas.append(f"  - [{marca}] {c.nombre}\n      observado: {c.detalle}")
    return "\n".join(lineas)


def generar(idea: str, url: str, modelo: str | None, temp: float) -> str | None:
    import os
    from cognia.program_creator.generator import _call_llm, _parse_response
    os.environ["COGNIA_CONSTRUCTOR_URL"] = url
    if modelo:
        os.environ["COGNIA_CONSTRUCTOR_MODELO"] = modelo
    else:
        os.environ.pop("COGNIA_CONSTRUCTOR_MODELO", None)
    crudo = _call_llm(idea, "html", temperature=temp)
    if not crudo:
        return None
    html = None
    try:
        prog = _parse_response(crudo, lenguaje="html")
        html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
    except Exception:
        pass
    if not html and "```" in crudo:
        trozo = crudo.split("```")[1]
        html = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
    return html if html and "<" in html else None


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    rondas = int(argv[argv.index("--rondas") + 1]) if "--rondas" in argv else 4
    url = argv[argv.index("--url") + 1] if "--url" in argv else "http://127.0.0.1:8080"
    modelo = argv[argv.index("--modelo") + 1] if "--modelo" in argv else None
    etiqueta = argv[argv.index("--etiqueta") + 1] if "--etiqueta" in argv else "modelo"
    banco = (argv[argv.index("--tareas-json") + 1] if "--tareas-json" in argv
             else "scripts/b1_tareas_duras.json")

    datos = json.loads((RAIZ / banco).read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    if "--tareas" in argv:
        ped = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in ped]

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"REPARACION CON CONTRAEJEMPLO — {etiqueta}\n"
          f"  banco: {Path(banco).name} ({len(tareas)} tareas), "
          f"tope {rondas} rondas\n", flush=True)

    filas = []
    for t in tareas:
        d = SALIDA / f"{etiqueta}__{t['id']}"
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        # Ronda 0: generacion normal. Temperatura 0.2 porque aqui NO se busca
        # diversidad (eso es best-of-N): se busca la mejor primera tirada.
        html = generar(t["idea"], url, modelo, 0.2)
        historia = []
        aprobado_en = None

        for r in range(0, rondas + 1):
            if not html:
                historia.append({"ronda": r, "aprobado": False,
                                 "checks_ok": 0, "checks": 0,
                                 "nota": "sin HTML"})
                break
            (d / "index.html").write_text(html, encoding="utf-8")
            v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
            ok = sum(1 for c in v.checks if c.ok)
            historia.append({"ronda": r, "aprobado": v.aprobado,
                             "checks_ok": ok, "checks": len(v.checks)})
            print(f"  {t['id']:<18} r{r} "
                  f"{'PASA ' if v.aprobado else 'falla'} ({ok}/{len(v.checks)})",
                  flush=True)
            if v.aprobado:
                aprobado_en = r
                break
            if r == rondas:
                break
            ce = contraejemplos_de(v)
            if not ce:
                break
            # Temperatura BAJA al reparar: a 0.9 el modelo "repara"
            # reescribiendo media pagina (medido en este repo 2026-07-20,
            # 3 rondas descartadas con "no mejoraba").
            import os
            from cognia.program_creator.generator import _call_llm, _parse_response
            os.environ["COGNIA_CONSTRUCTOR_URL"] = url
            if modelo:
                os.environ["COGNIA_CONSTRUCTOR_MODELO"] = modelo
            crudo = _call_llm(
                _PROMPT_REPARAR.format(contraejemplos=ce, codigo=html),
                "html", temperature=0.2)
            nuevo = None
            if crudo:
                try:
                    p = _parse_response(crudo, lenguaje="html")
                    nuevo = getattr(p, "code", None) or getattr(p, "codigo", None)
                except Exception:
                    pass
                if not nuevo and "```" in crudo:
                    tr = crudo.split("```")[1]
                    nuevo = tr[4:] if tr.lstrip()[:4].lower() == "html" else tr
            if not nuevo or "<" not in nuevo:
                print(f"  {t['id']:<18} r{r} la reparacion no devolvio HTML",
                      flush=True)
                break
            html = nuevo

        filas.append({"tarea": t["id"], "aprobado": aprobado_en is not None,
                      "aprobado_en_ronda": aprobado_en,
                      "rondas_usadas": len(historia) - 1,
                      "segundos": time.time() - t0, "historia": historia})
        print(f"  {t['id']:<18} ---> "
              f"{'PASA en ronda ' + str(aprobado_en) if aprobado_en is not None else 'NO PASA'}"
              f"  ({time.time() - t0:.0f}s)\n", flush=True)

    # ── curva de ganancia por ronda ──────────────────────────────────────
    n = len(filas)
    print(f"\n{'=' * 70}")
    print(f"GANANCIA POR RONDA DE REPARACION — {etiqueta}")
    print("=" * 70)
    acum = 0
    for r in range(0, rondas + 1):
        nuevos = sum(1 for f in filas if f["aprobado_en_ronda"] == r)
        acum += nuevos
        etq = "sin reparar (r0)" if r == 0 else f"tras {r} reparacion(es)"
        print(f"  {etq:<26} {acum}/{n}  ({acum / n:>4.0%})"
              + (f"   +{nuevos}" if nuevos else ""))
    print("=" * 70)
    p0 = sum(1 for f in filas if f["aprobado_en_ronda"] == 0) / n
    pf = acum / n
    seg = sum(f["segundos"] for f in filas) / n
    print(f"\n  pass@1 sin reparar : {p0:.0%}")
    print(f"  tras {rondas} rondas      : {pf:.0%}")
    print(f"  GANANCIA           : +{(pf - p0) * 100:.0f} puntos")
    print(f"  coste medio        : {seg:.0f}s por tarea")
    nunca = [f["tarea"] for f in filas if not f["aprobado"]]
    if nunca:
        print(f"\n  NO se reparan en {rondas} rondas ({len(nunca)}/{n}): "
              f"{', '.join(nunca)}")
        print("  Reparar no las compra. Si tampoco salen con best-of-N, eso SI")
        print("  es falta de capacidad y no se arregla con mas compute.")

    salida = SALIDA / f"resultados_{etiqueta}.json"
    salida.write_text(json.dumps(
        {"etiqueta": etiqueta, "banco": banco, "rondas": rondas,
         "filas": filas, "pass_r0": p0, "pass_final": pf},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
