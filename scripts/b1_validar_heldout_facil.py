"""
b1_validar_heldout_facil.py — valida la suite held-out del banco FACIL contra
paginas ya juzgadas por el contrato original (memoria fp-heldout-por-modelo:
validar SIEMPRE contra referencia antes de usar un held-out en un veredicto).

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_validar_heldout_facil.py
        [--dir <carpeta de corrida>] [--solo-aprobadas]

Recorre las paginas guardadas de corridas previas del banco facil
(b2_ab_lazo_facil por defecto), re-juzga cada una con su contrato ORIGINAL
(el veredicto guardado puede venir de otro commit del juez) y luego corre el
held-out. La tabla de salida separa los cuatro cuadrantes; los desacuerdos
(original OK ∧ held-out NO) son la cola a adjudicar A MANO leyendo el HTML:
o es un FP del original (pagina rota que paso el examen) o es un bug del
held-out (se corrige el JSON, como la fe de erratas de buscaminas).

Solo CPU/Playwright: no toca la GPU ni el backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout_facil.json"
DIR_DEFECTO = (RAIZ / "cognia" / "program_creator" / "generated_programs"
               / "b2_ab_lazo_facil")


def main(argv: list) -> int:
    from cognia.program_creator import juez_ejecutable

    base = (Path(argv[argv.index("--dir") + 1])
            if "--dir" in argv else DIR_DEFECTO)
    solo_aprobadas = "--solo-aprobadas" in argv
    originales = {t["id"]: t["contrato"]
                  for t in json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}

    paginas = sorted(base.glob("*__*/index.html"))
    if not paginas:
        sys.exit(f"sin paginas en {base}")

    filas = []
    for p in paginas:
        tid = p.parent.name.split("__")[0]
        if tid not in heldout:
            continue
        try:
            vo = juez_ejecutable.juzgar_web(p, originales[tid])
            ok_orig = vo.aprobado
        except Exception as exc:
            filas.append({"pagina": p.parent.name, "tarea": tid,
                          "error": f"original crasheo: {exc}"[:120]})
            continue
        if solo_aprobadas and not ok_orig:
            continue
        try:
            vh = juez_ejecutable.juzgar_web(p, heldout[tid])
            fallos = [c.nombre for c in vh.checks if not c.ok]
            filas.append({"pagina": p.parent.name, "tarea": tid,
                          "original": ok_orig, "heldout": vh.aprobado,
                          "heldout_fallos": fallos[:6]})
        except Exception as exc:
            filas.append({"pagina": p.parent.name, "tarea": tid,
                          "original": ok_orig,
                          "error": f"heldout crasheo: {exc}"[:120]})
        estado = filas[-1]
        print(f"  {estado['pagina']:<34} orig={estado.get('original')} "
              f"heldout={estado.get('heldout', 'ERR')} "
              f"{'; '.join(estado.get('heldout_fallos', []))[:70]}",
              flush=True)

    con_veredicto = [f for f in filas if "error" not in f]
    desacuerdos = [f for f in con_veredicto
                   if f["original"] and not f["heldout"]]
    print(f"\n{'=' * 70}")
    print(f"  paginas juzgadas: {len(con_veredicto)} "
          f"(errores: {len(filas) - len(con_veredicto)})")
    for tid in sorted({f['tarea'] for f in con_veredicto}):
        fs = [f for f in con_veredicto if f["tarea"] == tid]
        n11 = sum(1 for f in fs if f["original"] and f["heldout"])
        n10 = sum(1 for f in fs if f["original"] and not f["heldout"])
        n01 = sum(1 for f in fs if not f["original"] and f["heldout"])
        n00 = sum(1 for f in fs if not f["original"] and not f["heldout"])
        print(f"  {tid:<14} orig+held {n11:>2}  SOLO-orig {n10:>2}  "
              f"SOLO-held {n01:>2}  ninguno {n00:>2}")
    print(f"\n  A ADJUDICAR A MANO (original OK, held-out NO): "
          f"{len(desacuerdos)}")
    for f in desacuerdos:
        print(f"    {f['pagina']}: {'; '.join(f['heldout_fallos'])[:90]}")
    print(f"{'=' * 70}")

    salida = base / "validacion_heldout.json"
    salida.write_text(json.dumps(
        {"filas": filas, "desacuerdos": [f["pagina"] for f in desacuerdos]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
