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

from rich.color_triplet import ColorTriplet
from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

# Paleta oscura tipo terminal moderna (fondo/foreground del contenedor HTML).
FONDO = "#0d1117"
TEXTO = "#e6edf3"


def _t(hexa: str) -> ColorTriplet:
    return ColorTriplet(int(hexa[1:3], 16), int(hexa[3:5], 16), int(hexa[5:7], 16))


# POR QUE hay que declarar la paleta de los 16 colores: rich guarda los colores
# ANSI por NUMERO (green=2, bright_green=10, cyan=6...), no por triplete. Sin un
# TerminalTheme, Style.color.triplet es None para todos ellos y el HTML salia
# SIN color: el tema del CLI (verde/cyan/rojo) se rasterizaba en blanco y el PNG
# mentia sobre la estetica. Solo sobrevivian los truecolor (marco, gradiente).
# CAMPBELL es la paleta por defecto de Windows Terminal, que es lo que ve el
# dueno; CLARO es la de una terminal de fondo blanco, para juzgar el tema
# 'claro' donde corresponde.
CAMPBELL = TerminalTheme(
    (12, 12, 12), (204, 204, 204),
    [_t(c) for c in ("#0c0c0c", "#c50f1f", "#13a10e", "#c19c00",
                     "#0037da", "#881798", "#3a96dd", "#cccccc")],
    [_t(c) for c in ("#767676", "#e74856", "#16c60c", "#f9f1a5",
                     "#3b78ff", "#b4009e", "#61d6d6", "#f2f2f2")],
)
CLARO = TerminalTheme(
    (251, 251, 250), (34, 34, 31),
    [_t(c) for c in ("#000000", "#c01c28", "#26a269", "#a2734c",
                     "#12488b", "#a347ba", "#2aa1b3", "#5e5c64")],
    [_t(c) for c in ("#5e5c64", "#f66151", "#33d17a", "#e9ad0c",
                     "#2a7bde", "#c061cb", "#33c7de", "#000000")],
)
TEMAS_TERMINAL = {"campbell": CAMPBELL, "claro": CLARO}

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


# El shim que hace que el HIJO escriba ANSI en un pipe de Windows.
#
# POR QUE (medido 2026-08-17, con este mismo script): la captura salia con CERO
# secuencias ANSI -- 0 escapes en 3.495 bytes -- y el PNG mostraba TODO el tema
# en el color de texto por defecto. O sea: el instrumento decia "el tema no se
# ve" pasara lo que pasara con el tema, que es la peor clase de medicion.
#
# La causa NO es FORCE_COLOR (que si llega y pone is_terminal=True): en Windows
# rich pregunta GetConsoleMode() sobre el handle de stdout; con un PIPE eso
# falla, detect_legacy_windows() devuelve True y el color system pasa a
# 'windows' -- que pinta llamando a la API Win32 del CONSOLE, no escribiendo
# escapes. En un pipe esas llamadas no escriben nada.
#
# El hijo es un proceso ajeno (python -m cognia): no se le puede pasar
# legacy_windows=False, porque la Console la construye el. Se le inyecta por
# PYTHONPATH un sitecustomize que le dice a rich que la consola SI habla VT.
# Solo afecta al proceso capturado.
_SITECUSTOMIZE = '''# generado por scripts/captura_terminal_png.py -- efimero
try:
    import rich._windows as _w
    _feat = _w.WindowsConsoleFeatures(vt=True, truecolor=True)
    _w.get_windows_console_features = lambda: _feat
    import rich.console as _c
    # los DOS nombres: console.py hizo `from ._windows import
    # get_windows_console_features`, asi que parchear solo el modulo origen no
    # toca el nombre que ya quedo ligado en console.
    _c.detect_legacy_windows = lambda: False
    _c.get_windows_console_features = lambda: _feat
except Exception:
    pass
'''


def correr(cmd: list[str], stdin_texto: str | None, timeout: int, columnas: int, cwd: str | None,
           filas: int = 0) -> str:
    """Ejecuta el comando con color forzado y devuelve su stdout+stderr crudo (con ANSI)."""
    env = dict(os.environ)
    # NO_COLOR (no-color.org) GANA sobre FORCE_COLOR en rich, y basta que este
    # puesta en el entorno de quien corre la captura -- un CI, un agente, una
    # terminal configurada asi -- para que el PNG salga entero en el color de
    # texto por defecto SIN avisar. Medido 2026-08-17: el entorno tenia
    # NO_COLOR=1 y las capturas del tema claro salieron todas en negro; el
    # instrumento decia "el tema no se ve" pasara lo que pasara con el tema.
    # Una herramienta cuyo unico trabajo es rasterizar color no puede obedecer
    # una variable que lo apaga.
    for apaga_color in ("NO_COLOR", "ANSI_COLORS_DISABLED"):
        env.pop(apaga_color, None)
    env["FORCE_COLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = str(columnas)
    shim = Path(tempfile.mkdtemp(prefix="captura_shim_"))
    (shim / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    env["PYTHONPATH"] = str(shim) + os.pathsep + env.get("PYTHONPATH", "")
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


def ansi_a_html(ansi: str, columnas: int, tema: TerminalTheme = CAMPBELL) -> str:
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
        # get_truecolor(tema) resuelve TAMBIEN los colores por numero (los 16
        # ANSI y los 256), no solo los truecolor. Con .triplet a secas se
        # perdian todos los nombres ('green', 'bright_green', 'cyan'...).
        if estilo.color:
            css.append(f"color:{estilo.color.get_truecolor(tema).hex}")
        if estilo.bgcolor:
            css.append(
                f"background:{estilo.bgcolor.get_truecolor(tema, foreground=False).hex}")
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
    ap.add_argument("--tema-terminal", default="campbell",
                    choices=sorted(TEMAS_TERMINAL),
                    help="paleta de los 16 colores ANSI (campbell=Windows Terminal)")
    ap.add_argument("--fondo", default=None, help="color de fondo del PNG")
    ap.add_argument("--texto", default=None, help="color de texto por defecto")
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

    tema = TEMAS_TERMINAL[args.tema_terminal]
    cuerpo = ansi_a_html(crudo, args.columnas, tema)
    # El fondo por defecto sigue siendo el de siempre (FONDO) para no cambiar
    # las capturas ya existentes; con otra paleta ANSI manda el fondo del tema.
    por_defecto = args.tema_terminal == "campbell"
    fondo = args.fondo or (FONDO if por_defecto else tema.background_color.hex)
    texto = args.texto or (TEXTO if por_defecto else tema.foreground_color.hex)
    documento = PLANTILLA.format(fondo=fondo, texto=texto, fuente=args.fuente, cuerpo=cuerpo)
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
