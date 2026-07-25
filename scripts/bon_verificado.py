"""
bon_verificado.py — convertir COMPUTE en CAPACIDAD con un verificador que ejecuta.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\bon_verificado.py --n 8

LA IDEA, y por que ahora se puede.

B1 midio un router ORACULO sobre 4 modelos distintos: ganancia **+0** sobre
correr solo el mejor. Elegir ENTRE MODELOS no crea capacidad — el techo es
max(), no sum(). Ese resultado parecia cerrar la puerta.

No la cierra: la mueve. Ese oraculo era sobre MODELOS. Con
cognia/program_creator/juez_ejecutable.py existe ahora un oraculo sobre
MUESTRAS del mismo modelo — y a diferencia del de modelos, este NO es
hipotetico: se puede COMPROBAR cual muestra sirve, porque se ejecuta el producto
contra su contrato. Un oraculo realizable deja de ser un techo teorico y pasa a
ser un algoritmo.

QUE MIDE:
  pass@1          la tasa de una sola muestra (lo que hace el sistema hoy)
  pass@k          la probabilidad de que AL MENOS UNA de k muestras pase
  coste           cuantos segundos cuesta cada punto de mejora

pass@k con verificador NO es la metrica optimista de siempre: aqui se puede
ENTREGAR la muestra que pasa, porque el juez dice cual es. La diferencia entre
pass@1 y pass@k es capacidad realmente cobrable.

DONDE SATURA es el dato que decide si esto sustituye a un modelo grande. Si
pass@k se aplana en k=4 muy por debajo de 1.0, hay tareas que el modelo NO
resuelve nunca y ninguna cantidad de muestreo las salva: eso SI seria un techo
de capacidad, y ahi si hace falta mas conocimiento en los pesos.

Se estima pass@k con el estimador insesgado de Chen et al. 2021 (Codex,
arXiv:2107.03374) sobre las n muestras, no con una sola tirada de k.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "bon_verificado")


def pass_at_k(n: int, c: int, k: int) -> float:
    """
    Estimador insesgado de pass@k (Chen et al. 2021): 1 - C(n-c, k)/C(n, k).

    n = muestras generadas, c = cuantas pasaron, k = presupuesto.
    Usarlo en vez de "de mis n primeras k, ¿paso alguna?" evita el sesgo de
    tirar los datos que no entran en la ventana.
    """
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


def generar(idea: str, url: str, modelo: str | None, temperatura: float) -> str | None:
    import os
    from cognia.program_creator.generator import _call_llm, _parse_response
    os.environ["COGNIA_CONSTRUCTOR_URL"] = url
    if modelo:
        os.environ["COGNIA_CONSTRUCTOR_MODELO"] = modelo
    else:
        os.environ.pop("COGNIA_CONSTRUCTOR_MODELO", None)
    crudo = _call_llm(idea, "html", temperature=temperatura)
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

    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 8
    # Temperatura ALTA a proposito: best-of-N necesita DIVERSIDAD. Con temp
    # baja las n muestras son casi la misma y el muestreo no compra nada — es
    # el error clasico al montar esto.
    temp = float(argv[argv.index("--temp") + 1]) if "--temp" in argv else 0.9
    banco = (argv[argv.index("--tareas-json") + 1] if "--tareas-json" in argv
             else "scripts/b1_tareas_duras.json")
    url = argv[argv.index("--url") + 1] if "--url" in argv else "http://127.0.0.1:8080"
    modelo = argv[argv.index("--modelo") + 1] if "--modelo" in argv else None
    etiqueta = argv[argv.index("--etiqueta") + 1] if "--etiqueta" in argv else "modelo"

    datos = json.loads((RAIZ / banco).read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    if "--tareas" in argv:
        ped = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in ped]

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"BEST-OF-N VERIFICADO — {etiqueta}\n"
          f"  banco: {Path(banco).name} ({len(tareas)} tareas)\n"
          f"  n={n} muestras por tarea, temperatura={temp}\n", flush=True)

    filas = []
    for t in tareas:
        exitos, tiempos = 0, []
        for i in range(1, n + 1):
            d = SALIDA / f"{etiqueta}__{t['id']}__s{i}"
            d.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            if (d / "index.html").is_file() and "--reanudar" in argv:
                html = (d / "index.html").read_text(encoding="utf-8")
                segs = 0.0
            else:
                html = generar(t["idea"], url, modelo, temp)
                segs = time.time() - t0
                if html:
                    (d / "index.html").write_text(html, encoding="utf-8")
            tiempos.append(segs)
            if not html:
                print(f"  {t['id']:<18} s{i} SIN HTML", flush=True)
                continue
            v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
            exitos += 1 if v.aprobado else 0
            print(f"  {t['id']:<18} s{i} "
                  f"{'PASA ' if v.aprobado else 'falla'} "
                  f"({sum(1 for c in v.checks if c.ok)}/{len(v.checks)}, "
                  f"{segs:.0f}s)", flush=True)
        filas.append({"tarea": t["id"], "n": n, "exitos": exitos,
                      "segundos_medios": sum(tiempos) / len(tiempos) if tiempos else 0})
        print(f"  {t['id']:<18} ---> {exitos}/{n}\n", flush=True)

    # ── curva pass@k ─────────────────────────────────────────────────────
    KS = [k for k in (1, 2, 4, 8, 16) if k <= n]
    print(f"\n{'=' * 78}")
    print(f"CURVA pass@k CON VERIFICADOR EJECUTABLE — {etiqueta}")
    print("=" * 78)
    print(f"{'TAREA':<20}{'exitos':>9}" + "".join(f"{'@'+str(k):>9}" for k in KS))
    print("-" * 78)
    for f in filas:
        fila = f"{f['tarea']:<20}{f'{f[chr(101)+chr(120)+chr(105)+chr(116)+chr(111)+chr(115)]}/{f['n']}':>9}"
        for k in KS:
            fila += f"{pass_at_k(f['n'], f['exitos'], k):>8.0%} "
        print(fila)
    print("-" * 78)
    medias = {k: sum(pass_at_k(f["n"], f["exitos"], k) for f in filas) / len(filas)
              for k in KS}
    fila = f"{'MEDIA':<20}{'':>9}"
    for k in KS:
        fila += f"{medias[k]:>8.0%} "
    print(fila)
    print("=" * 78)

    p1, pmax = medias[KS[0]], medias[KS[-1]]
    seg = sum(f["segundos_medios"] for f in filas) / len(filas)
    print(f"\n  pass@1  = {p1:.0%}   (lo que entrega el sistema HOY)")
    print(f"  pass@{KS[-1]} = {pmax:.0%}   (lo que se puede COBRAR con el juez)")
    print(f"  ganancia realizable: +{pmax - p1:.0%} por {KS[-1]}x de compute")
    print(f"  coste: ~{seg:.0f}s por muestra -> ~{seg * KS[-1]:.0f}s por tarea")

    nunca = [f["tarea"] for f in filas if f["exitos"] == 0]
    if nunca:
        print(f"\n  TECHO DURO: {len(nunca)}/{len(filas)} tareas no salen NUNCA "
              f"en {n} muestras:")
        for x in nunca:
            print(f"    - {x}")
        print("  Ahi el muestreo no compra nada. Eso SI es falta de capacidad,")
        print("  y es lo unico que justifica mas conocimiento en los pesos.")
    else:
        print(f"\n  Ninguna tarea es imposible para este modelo: todas salen")
        print(f"  alguna vez en {n} muestras. El limite es de MUESTREO, no de")
        print(f"  capacidad — y el muestreo se compra con compute.")

    salida = SALIDA / f"resultados_{etiqueta}.json"
    salida.write_text(json.dumps(
        {"etiqueta": etiqueta, "banco": banco, "n": n, "temp": temp,
         "filas": filas, "pass_at_k": medias}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
