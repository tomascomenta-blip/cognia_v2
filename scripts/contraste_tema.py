# -*- coding: utf-8 -*-
"""Contraste WCAG de CADA token del tema del CLI, en las tres variantes.

POR QUE: "se ve apagado" no es un dato. El juicio visual del dueno (2026-08-17)
midio hex por hex y encontro que el ROJO del tema por defecto (3.12:1) era lo
mas tenue de la pantalla mientras todo lo verde estaba entre 5.5 y 15.4. Este
script convierte esa medicion en algo que se puede REPETIR antes y despues de
cada cambio de paleta.

COMO resuelve un color: los tokens del tema son en parte nombres ANSI
('green', 'bright_red') y en parte hex. Un nombre NO tiene color propio: lo
pone el emulador. Se resuelve con la MISMA tabla que usa scripts/
captura_terminal_png.py -- CAMPBELL (Windows Terminal, lo que ve el dueno)
para los temas oscuros y CLARO (terminal de fondo blanco) para 'claro'.

'dim' se modela como lo hace el export SVG de rich (console.py:
blend_rgb(color, bgcolor, 0.4)); es una aproximacion declarada, no una medida
del pixel. Los tokens SIN dim son exactos: reproducen los numeros del juicio
visual al segundo decimal (marco 9.34, '+' 5.53, ok 7.45, rojo 3.12,
banner 1.33 -> 13.86).

Uso:
    venv312\\Scripts\\python.exe scripts/contraste_tema.py
    venv312\\Scripts\\python.exe scripts/contraste_tema.py --json antes.json
    venv312\\Scripts\\python.exe scripts/contraste_tema.py --diff antes.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cognia.ux import paleta  # noqa: E402  (necesita el sys.path de arriba)

# Fondos reales contra los que se lee cada variante. Salen de la paleta: eran
# una copia aca y el piso de contraste por variante no puede medirse contra un
# fondo que la paleta no conoce.
FONDO = dict(paleta.FONDO_VARIANTE)
# Que tabla de 16 colores ANSI aplica a cada variante.
TERMINAL = {
    "oscuro":         "campbell",
    "alto_contraste": "campbell",
    "claro":          "claro",
}
# Piso de legibilidad de texto normal (WCAG 2.1 AA).
MINIMO_AA = 4.5


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminancia(hexa: str) -> float:
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contraste(fg: str, bg: str) -> float:
    a, b = luminancia(fg), luminancia(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _mezclar(hex_a: str, hex_b: str, f: float) -> str:
    """blend_rgb de rich: a + (b - a) * f."""
    va = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    vb = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(a + (b - a) * f):02x}" for a, b in zip(va, vb))


def resolver(estilo: str, variante: str) -> str:
    """Estilo de rich ('bold bright_green', '#4fd010', 'dim white') -> hex."""
    from rich.style import Style
    from scripts.captura_terminal_png import TEMAS_TERMINAL
    tema = TEMAS_TERMINAL[TERMINAL[variante]]
    st = Style.parse(estilo)
    if st.color is None or st.color.is_default:
        trip = tema.foreground_color
    else:
        trip = st.color.get_truecolor(tema)
    hexa = f"#{trip.red:02x}{trip.green:02x}{trip.blue:02x}"
    if st.dim:
        bg = f"#{tema.background_color.red:02x}{tema.background_color.green:02x}" \
             f"{tema.background_color.blue:02x}"
        hexa = _mezclar(hexa, bg, 0.4)
    return hexa


def medir() -> dict:
    """{variante: {token: {estilo, hex, contraste}}} + las piezas fijas."""
    salida = {}
    for variante in paleta.ORDEN_VARIANTES:
        bg = FONDO[variante]
        fila = {}
        for token, estilo in sorted(paleta.tema_cli(variante).items()):
            hexa = resolver(estilo, variante)
            fila[token] = {"estilo": estilo, "hex": hexa,
                           "contraste": round(contraste(hexa, bg), 2)}
        # Piezas que NO pasan por el tema de rich: el marco del prompt (lo
        # pinta prompt_toolkit) y los extremos del degradado del banner. Van en
        # la tabla porque el ojo las ve en la MISMA pantalla que los tokens, y
        # desde 2026-08-17 salen de la rampa de SU variante: eran hex fijos y
        # por eso '/tema claro' dejaba el prompt en 1,19:1.
        verde = paleta.rampa(variante)
        for nombre, hexa in (("~marco_prompt", verde["marco"]),
                             ("~prompt_cognia", verde["prompt"]),
                             ("~texto_escrito", verde["texto"]),
                             ("~barra_estado", verde["estado"]),
                             ("~banner_inicio", verde["profundo"]),
                             ("~banner_fin", verde["matrix"])):
            fila[nombre] = {"estilo": "(fijo)", "hex": hexa,
                            "contraste": round(contraste(hexa, bg), 2)}
        # Las bandas del diff son FONDOS, no texto: lo que se mide es cuanto se
        # despegan del fondo del tema (criterio: menos de 2:1, o dejan de ser
        # un realce y son una isla). El texto de encima se mide aparte, abajo.
        for nombre, hexa in sorted(paleta.diff_fondos(variante).items()):
            fila[f"=diff_{nombre}"] = {
                "estilo": "(banda)", "hex": hexa,
                "contraste": round(contraste(hexa, bg), 2)}
        salida[variante] = fila
    return salida


def imprimir(datos: dict, previo: dict | None = None) -> None:
    for variante, fila in datos.items():
        print(f"\n### {variante}  (fondo {FONDO[variante]}, "
              f"ANSI {TERMINAL[variante]})")
        print(f"{'token':16} {'estilo':26} {'hex':9} {'contr':>6}  ", end="")
        print("antes" if previo else "")
        for token in sorted(fila):
            d = fila[token]
            if token.startswith("=diff_"):
                # Una banda es fondo: el criterio es el CONTRARIO (no puede
                # despegarse mas de 2:1 del fondo del tema). Las '_intra' son
                # el realce del span cambiado y estan exentas a proposito.
                tope = 2.0
                marca = ("" if d["contraste"] < tope or "intra" in token
                         else f"  >{tope}")
            else:
                marca = "" if d["contraste"] >= MINIMO_AA else "  <AA"
            col = ""
            if previo and token in previo.get(variante, {}):
                ant = previo[variante][token]
                if ant["hex"] != d["hex"]:
                    col = f"   {ant['hex']} {ant['contraste']:.2f}"
            print(f"{token:16} {d['estilo']:26} {d['hex']:9} "
                  f"{d['contraste']:6.2f}{marca}{col}")


# ---------------------------------------------------------------------------
# Los 104 colores que cli.py escribia A MANO (2026-08-17, segunda pasada)
# ---------------------------------------------------------------------------
# El juicio visual arreglo el marco, el prompt, el banner y el diff -- las
# superficies que nombro -- y dejo intacta la MAS GRANDE del producto: lo que
# imprimen los ~30 comandos slash. Estos son los literales que estaban y el
# token que los reemplaza. La tabla vive aca y no en el test porque es la
# MEDICION: el token nuevo aparece en medir() como cualquier otro, pero su
# 'antes' no, porque un literal nunca estuvo en el tema.
MIGRADOS = [
    # (literal que habia, usos, token nuevo, donde se veia)
    ("cyan",         79, "listado", "cuerpo de ~30 comandos (/sesiones, /kg *, /stats...)"),
    ("cyan",          5, "titulo",  "titulos de panel (/costo, /stats, /modulos...)"),
    ("cyan",          4, "borde",   "bordes de esos mismos paneles"),
    ("cyan",          1, "mod",     "nombre del modelo en el arranque compacto"),
    ("cyan",          4, "respuesta", "respuesta FINAL del modelo (ahora el acento de /color)"),
    ("magenta",       7, "respuesta", "/narrativa /explicar /evaluar /alternativas /comparar /inferir /skill-cargar"),
    ("bright_cyan",   2, "listado", "/plan y /template"),
    ("yellow",        2, "listado", "/seguridad y /contradicciones (son informes)"),
    ("yellow",        4, "warn_cl", "/olvidar-ciclo, lock/unlock, /plan-borrar"),
    ("yellow",        1, "detail",  "la sugerencia tras un comando desconocido"),
    ("dim cyan",      1, "info_dim", "la linea 'modelo ... (:8080) modo ... tema ...'"),
    ("dim",           1, "marca_dim", "'v4.8.0 - sistema cognitivo local'"),
    ("dim",           4, "info_dim", "cwd, la guia del arranque y el rule de /tema"),
]


def imprimir_migracion() -> None:
    """ANTES (el literal) vs DESPUES (el token) en las tres variantes."""
    print("\n### migracion de los literales de cognia/cli.py")
    print(f"{'literal':13} {'usos':>4} -> {'token':10}", end="")
    for v in paleta.ORDEN_VARIANTES:
        print(f"{v[:8]:>17}", end="")
    print()
    peor_antes = peor_despues = 999.0
    for literal, usos, token, donde in MIGRADOS:
        print(f"{literal:13} {usos:>4} -> {token:10}", end="")
        for v in paleta.ORDEN_VARIANTES:
            bg = FONDO[v]
            a = contraste(resolver(literal, v), bg)
            d = contraste(resolver(paleta.tema_cli(v)[token], v), bg)
            peor_antes = min(peor_antes, a)
            peor_despues = min(peor_despues, d)
            print(f"{a:7.2f} ->{d:7.2f}", end="")
        print(f"   {donde}")
    total = sum(u for _, u, _, _ in MIGRADOS)
    print(f"\n{total} usos migrados. Lo PEOR de la tabla: "
          f"{peor_antes:.2f} antes -> {peor_despues:.2f} despues "
          f"(piso AA {MINIMO_AA}).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="", help="guardar la medicion a un JSON")
    ap.add_argument("--diff", default="", help="comparar contra un JSON previo")
    ap.add_argument("--migracion", action="store_true",
                    help="antes/despues de los literales que tenia cli.py")
    args = ap.parse_args()
    if args.migracion:
        imprimir_migracion()
        return 0
    datos = medir()
    previo = json.loads(Path(args.diff).read_text()) if args.diff else None
    imprimir(datos, previo)
    if args.json:
        Path(args.json).write_text(json.dumps(datos, indent=1))
        print(f"\nguardado -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
