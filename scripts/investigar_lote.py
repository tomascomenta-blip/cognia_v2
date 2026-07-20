"""
investigar_lote.py — Cognia investiga una tanda de preguntas y deja los informes.

POR QUE EXISTE: la noche del 2026-07-20 las 11 investigaciones se lanzaron a
mano, una por una. Un tema que reventaba se llevaba la sesion por delante y no
quedaba rastro de cual fue. Aqui cada tema esta aislado: si uno falla se anota
el error y la tanda sigue.

    python scripts/investigar_lote.py --temas temas.txt
    python scripts/investigar_lote.py --temas temas.txt --salida planes/x/
    python scripts/investigar_lote.py --tema "how agents do web search"

Formato de temas.txt: una linea por tema, `slug: pregunta`. Las lineas vacias y
las que empiezan por # se ignoran.

Solo stdlib + el research_engine del repo.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.research_engine.web_research import investigar  # noqa: E402

SALIDA_DEF = Path("planes") / "investigacion_nocturna"


def leer_temas(ruta: Path) -> list[tuple[str, str]]:
    temas: list[tuple[str, str]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        slug, _, pregunta = linea.partition(":")
        if not pregunta.strip():
            print(f"[aviso] linea sin ':' ignorada -> {linea[:60]}", file=sys.stderr)
            continue
        temas.append((slug.strip(), pregunta.strip()))
    return temas


def investigar_uno(slug: str, pregunta: str, salida: Path, **kw) -> dict:
    """Investiga un tema y escribe el informe. Nunca lanza: devuelve el estado."""
    inicio = time.time()
    try:
        digest = investigar(pregunta, **kw)
    except Exception as e:                      # un tema roto no mata la tanda
        print(f"[FALLO] {slug}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"slug": slug, "ok": False, "error": str(e),
                "segundos": time.time() - inicio}

    destino = salida / f"{slug}.md"
    destino.write_text(digest.to_markdown(), encoding="utf-8")
    return {
        "slug":      slug,
        "ok":        True,
        "hallazgos": len(digest.hallazgos),
        "contra":    len(digest.contraevidencia),
        "resumen":   bool(digest.resumen_llm),
        "kb":        destino.stat().st_size / 1024,
        "segundos":  time.time() - inicio,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--temas", type=Path, help="fichero `slug: pregunta` por linea")
    ap.add_argument("--tema", help="un solo tema, como pregunta suelta")
    ap.add_argument("--salida", type=Path, default=SALIDA_DEF)
    ap.add_argument("--queries", type=int, default=4)
    ap.add_argument("--por-fuente", type=int, default=4)
    ap.add_argument("--sin-arxiv", action="store_true",
                    help="saltar arXiv (3 s de cortesia por peticion)")
    args = ap.parse_args()

    if args.temas:
        if not args.temas.is_file():
            print(f"No existe {args.temas}", file=sys.stderr)
            return 1
        temas = leer_temas(args.temas)
    elif args.tema:
        temas = [(args.tema.lower().replace(" ", "_")[:40], args.tema)]
    else:
        print("Hace falta --temas o --tema", file=sys.stderr)
        return 1

    if not temas:
        print("No hay temas que investigar", file=sys.stderr)
        return 1

    args.salida.mkdir(parents=True, exist_ok=True)
    print(f"{len(temas)} temas -> {args.salida}\n")

    resultados = []
    for i, (slug, pregunta) in enumerate(temas, 1):
        print(f"[{i}/{len(temas)}] {slug}: {pregunta}")
        r = investigar_uno(slug, pregunta, args.salida,
                           n_queries=args.queries,
                           max_por_fuente=args.por_fuente,
                           usar_arxiv=not args.sin_arxiv)
        resultados.append(r)
        if r["ok"]:
            print(f"    {r['hallazgos']} hallazgos, {r['contra']} contra, "
                  f"resumen={'si' if r['resumen'] else 'NO'}, "
                  f"{r['kb']:.0f} KB, {r['segundos']:.0f}s\n")
        else:
            print(f"    FALLO en {r['segundos']:.0f}s\n")

    ok = [r for r in resultados if r["ok"]]
    print("=" * 60)
    print(f"{len(ok)}/{len(resultados)} temas con informe "
          f"({sum(r['segundos'] for r in resultados):.0f}s en total)")
    # Un informe sin resumen es senal de backend caido: el motor degrada a
    # listar hallazgos sin decir nada sobre ellos, y no avisa.
    sin_resumen = [r["slug"] for r in ok if not r["resumen"]]
    if sin_resumen:
        print(f"AVISO sin resumen del LLM ({len(sin_resumen)}): "
              f"{', '.join(sin_resumen)}")
        print("  -> comprueba el backend: python scripts/servir_modelo.py")
    for r in resultados:
        if not r["ok"]:
            print(f"FALLO {r['slug']}: {r['error']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
