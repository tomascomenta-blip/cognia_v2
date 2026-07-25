"""
bateria_verificada.py — la tabla: score viejo vs score verificado POR EJECUCION.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\bateria_verificada.py
    ... --solo web        # solo los productos HTML (juez ejecutable)
    ... --limite 10       # los N mas recientes
    ... --json salida.json

QUE HACE: para cada producto de generated_programs/ (mas pulidos/ y construidos/)
pone en una fila tres cosas distintas que hasta hoy se confundian:

  1. score viejo (total_score) — lo que el sistema se puso A SI MISMO. Sale de
     evaluator.py: regex + AST sobre su propio codigo. Le dio 7.8/10 a un
     random-walk de 71 lineas sin input del jugador.
  2. puntaje_real del sello (.verificacion.json) — cognia/autoprueba.py, que SI
     ejecuta, pero mide LIVENESS: compila 3.0 + arranca 3.0 + sin_stubs 2.0 +
     doc 1.0 + palabras de la descripcion 1.0. Un programa que arranca e imprime
     saca 9.5 aunque no haga lo que se pidio. No es correccion.
  3. VEREDICTO EJECUTABLE — cognia/program_creator/juez_ejecutable.py: abre el
     producto en Chromium real, interactua y comprueba el estado. Si falla un
     check critico: FALLIDO y SIN PUNTAJE.

REGLA (FASE A4): ningun score sin verificacion por ejecucion se imprime como
numero. Se imprime "sin verificar".

Se espera que muchos BAJEN. Eso es la senal de que ahora se esta midiendo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

BASE = RAIZ / "cognia" / "program_creator" / "generated_programs"
INDICE = BASE / "index.json"
SELLO = ".verificacion.json"


def leer_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def productos() -> list:
    """Todo directorio con un producto dentro, incluidos pulidos/ y construidos/."""
    fuera = []
    for d in sorted(BASE.iterdir()):
        if not d.is_dir():
            continue
        if d.name in ("pulidos", "construidos"):
            fuera += [x for x in sorted(d.iterdir()) if x.is_dir()]
        else:
            fuera.append(d)
    return fuera


def tipo(d: Path) -> str:
    if (d / "index.html").is_file() or list(d.glob("*.html")):
        return "web"
    if list(d.glob("*.py")):
        return "python"
    return "?"


def fila(d: Path, indice_por_id: dict, solo_web: bool) -> dict:
    from cognia.program_creator import juez_ejecutable

    entrada = indice_por_id.get(d.name, {})
    sello = leer_json(d / SELLO) or {}
    t = tipo(d)
    f = {
        "producto": d.name,
        "tipo": t,
        "score_viejo": entrada.get("total_score", sello.get("score_juez")),
        "puntaje_sello": sello.get("puntaje_real"),
        "veredicto": None,
        "puntaje_nuevo": None,
        "motivo": "",
        "con_contrato": False,
    }

    if t != "web":
        f["veredicto"] = "NO EVALUADO"
        f["motivo"] = ("producto Python: el juez ejecutable es web. Lo unico "
                       "que lo toco fue autoprueba (liveness), no correccion")
        return f
    if solo_web is False and t != "web":
        return f

    try:
        v = juez_ejecutable.juzgar(d)
    except Exception as exc:
        f["veredicto"] = "ERROR"
        f["motivo"] = f"{type(exc).__name__}: {exc}"
        return f

    f["veredicto"] = v.estado          # APROBADO exige contrato; sin el, VIVO
    f["puntaje_nuevo"] = v.puntaje_ejecucion
    f["motivo"] = v.motivo[:150]
    f["con_contrato"] = v.con_contrato
    return f


def fmt(x, sufijo="/10") -> str:
    return f"{x:.1f}{sufijo}" if isinstance(x, (int, float)) else "sin verificar"


def main(argv: list) -> int:
    solo_web = "--solo" in argv and "web" in argv
    limite = None
    if "--limite" in argv:
        limite = int(argv[argv.index("--limite") + 1])

    idx = leer_json(INDICE) or []
    indice_por_id = {e.get("directory") or e.get("id"): e for e in idx}

    dirs = productos()
    if solo_web:
        dirs = [d for d in dirs if tipo(d) == "web"]
    if limite:
        dirs = dirs[-limite:]

    print(f"Productos a evaluar: {len(dirs)}\n", flush=True)
    filas = []
    for i, d in enumerate(dirs, 1):
        print(f"[{i}/{len(dirs)}] {d.name} ...", flush=True)
        filas.append(fila(d, indice_por_id, solo_web))

    # ── tabla ────────────────────────────────────────────────────────────
    print("\n" + "=" * 118)
    print(f"{'PRODUCTO':<46} {'TIPO':<7} {'VIEJO':>12} {'SELLO':>14} "
          f"{'VEREDICTO':>11} {'NUEVO':>14}")
    print("=" * 118)
    for f in filas:
        print(f"{f['producto'][:45]:<46} {f['tipo']:<7} "
              f"{fmt(f['score_viejo']):>12} {fmt(f['puntaje_sello']):>14} "
              f"{(f['veredicto'] or '-'):>11} {fmt(f['puntaje_nuevo']):>14}")
    print("=" * 118)

    web = [f for f in filas if f["tipo"] == "web"]
    aprob = [f for f in web if f["veredicto"] == "APROBADO"]
    vivo = [f for f in web if f["veredicto"] == "VIVO"]
    fall = [f for f in web if f["veredicto"] == "FALLIDO"]
    print(f"\nWEB abiertos en Chromium real : {len(web)}")
    print(f"  APROBADO (paso su contrato) : {len(aprob)}")
    print(f"  FALLIDO  (sin puntaje)      : {len(fall)}")
    print(f"  VIVO     (carga y reacciona, pero NADIE verifico su mecanica "
          f"porque no tiene contrato): {len(vivo)}")
    print(f"\n  Lo unico que este juez puede AFIRMAR hoy es sobre "
          f"{len(aprob) + len(fall)} de {len(web)} productos.")
    no_web = [f for f in filas if f["tipo"] != "web"]
    print(f"NO evaluados (python/otro)  : {len(no_web)}")

    if "--json" in argv:
        salida = Path(argv[argv.index("--json") + 1])
        salida.write_text(json.dumps(filas, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
