"""Captura la salida real de un comando de terminal y la renderiza a PNG.

Sirve para juzgar visualmente el CLI de Cognia contra las capturas de otros harnesses:
corre el comando con color forzado, interpreta el ANSI con rich y lo rasteriza con
Playwright (Chromium) sobre un fondo de terminal.

Uso:
    python scripts/captura_terminal_png.py --salida out.png -- python -m cognia --help
    python scripts/captura_terminal_png.py --salida out.png --ansi captura.txt
    python scripts/captura_terminal_png.py --salida out.png --stdin "hola\n/salir\n" -- python -m cognia

No usa mocks: lo que se ve en el PNG es exactamente lo que el proceso escribio en stdout.
"""

from __future__ import annotations

import argparse
import html as html_mod
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.text import Text

# Paleta oscura tipo terminal moderna (fondo/foreground del contenedor HTML).
FONDO = "#0d1117"
TEXTO = "#e6edf3"

PLANTILLA = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin:0; padding:0; background:{fondo}; }}
  body {{ padding:22px 24px; }}
  pre {{ margin:0; font-family: "Cascadia Mono", "JetBrains Mono", "DejaVu Sans Mono", Consolas, monospace;
        font-size:{fuente}px; line-height:1.34; color:{texto}; white-space:pre; }}
  .marco {{ display:inline-block; }}
</style></head>
<body><div class="marco"><pre>{cuerpo}</pre></div></body></html>
"""


def correr(cmd: list[str], stdin_texto: str | None, timeout: int, columnas: int, cwd: str | None,
           filas: int = 0) -> str:
    """Ejecuta el comando con color forzado y devuelve su stdout+stderr crudo (con ANSI)."""
    env = dict(os.environ)
    env["FORCE_COLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = str(columnas)
    if filas:
        # shutil.get_terminal_size y rich respetan LINES: así se puede probar
        # el banner adaptativo sin una terminal de verdad de ese tamaño.
        env["LINES"] = str(filas)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(
            cmd,
            input=stdin_texto,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        salida = p.stdout or ""
        if p.stderr and not salida.strip():
            salida = p.stderr
        return salida
    except subprocess.TimeoutExpired as exc:
        parcial = exc.stdout or ""
        if isinstance(parcial, bytes):
            parcial = parcial.decode("utf-8", "replace")
        return parcial + "\n[timeout]"


def ansi_a_html(ansi: str, columnas: int) -> str:
    """Convierte texto con secuencias ANSI en HTML con <span style=...> por tramo."""
    consola = Console(record=True, width=columnas, file=open(os.devnull, "w", encoding="utf-8"),
                      force_terminal=True, color_system="truecolor", legacy_windows=False)
    texto = Text.from_ansi(ansi)
    consola.print(texto, end="")
    piezas: list[str] = []
    for segmento in consola._record_buffer:
        crudo = segmento.text
        if not crudo:
            continue
        escapado = html_mod.escape(crudo)
        estilo = segmento.style
        if estilo is None:
            piezas.append(escapado)
            continue
        css: list[str] = []
        if estilo.color and estilo.color.triplet:
            css.append(f"color:{estilo.color.triplet.hex}")
        if estilo.bgcolor and estilo.bgcolor.triplet:
            css.append(f"background:{estilo.bgcolor.triplet.hex}")
        if estilo.bold:
            css.append("font-weight:700")
        if estilo.italic:
            css.append("font-style:italic")
        if estilo.underline:
            css.append("text-decoration:underline")
        if estilo.dim:
            css.append("opacity:.6")
        piezas.append(f'<span style="{";".join(css)}">{escapado}</span>' if css else escapado)
    return "".join(piezas)


def html_a_png(ruta_html: Path, destino: Path, escala: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(device_scale_factor=escala)
        pagina.goto(ruta_html.as_uri())
        pagina.wait_for_timeout(220)
        marco = pagina.query_selector("body")
        marco.screenshot(path=str(destino))
        navegador.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", required=True, help="ruta del PNG de salida")
    ap.add_argument("--ansi", help="archivo con ANSI ya capturado (en vez de correr un comando)")
    ap.add_argument("--stdin", help="texto a enviar por stdin al comando (usa \\n)")
    ap.add_argument("--columnas", type=int, default=100)
    ap.add_argument("--filas", type=int, default=0, help="filas simuladas (LINES)")
    ap.add_argument("--fuente", type=int, default=14)
    ap.add_argument("--escala", type=int, default=2, help="device scale factor (nitidez)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--guardar-ansi", default=None, help="volcar el ANSI capturado a este archivo")
    ap.add_argument("cmd", nargs="*", help="comando tras --")
    args = ap.parse_args()

    if args.ansi:
        crudo = Path(args.ansi).read_text(encoding="utf-8", errors="replace")
    else:
        if not args.cmd:
            print("falta el comando (tras --) o --ansi", file=sys.stderr)
            return 2
        entrada = args.stdin.replace("\\n", "\n") if args.stdin else None
        crudo = correr(args.cmd, entrada, args.timeout, args.columnas, args.cwd, args.filas)

    if args.guardar_ansi:
        Path(args.guardar_ansi).write_text(crudo, encoding="utf-8")

    cuerpo = ansi_a_html(crudo, args.columnas)
    documento = PLANTILLA.format(fondo=FONDO, texto=TEXTO, fuente=args.fuente, cuerpo=cuerpo)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(documento)
        ruta_html = Path(fh.name)
    destino = Path(args.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    html_a_png(ruta_html, destino, args.escala)
    ruta_html.unlink(missing_ok=True)
    print(f"PNG: {destino}  ({destino.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
