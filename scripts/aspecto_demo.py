# -*- coding: utf-8 -*-
"""Demo del MOTOR de glow/barrido (cognia/ux/glow) sin tocar el CLI: la puerta
visible del paso P3 del sistema de estilos por elemento.

Muestra las tres zonas vivas con el mismo motor que usara el REPL:
  1. banner con barrido (BannerVivo dentro de UNA Live, antes de cualquier
     prompt; termina en frame estatico),
  2. la linea del spinner (LineaViva DENTRO de console.status: la Live que
     el renderer ya tiene; sin abrir otra),
  3. el prompt de prompt_toolkit animado por PULSO finito (pulso_prompt: un
     hilo daemon de app.invalidate() acotado a 3 s; refresh_interval no se
     toca).
Al final imprime frames y CPU medidos (process_time / pared) de cada zona.

Por un PIPE (echo | python scripts/aspecto_demo.py > salida.txt) capacidades()
apaga la animacion y todo sale ESTATICO: sin cursor-up, un frame por zona, y
el prompt no se abre si stdin no es tty.

Uso:
    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\aspecto_demo.py [--segundos 2] [--fps 12]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognia.ux import glow, paleta  # noqa: E402

# El gato Braille + logotipo, 4 filas (recorte del banner real, solo demo).
BANNER = [
    "  ⠀⠀⣠⣤⣤⣄⠀⠀  ██████╗ ██████╗  ██████╗ ███╗   ██╗██╗ █████╗ ",
    "  ⠀⣾⣿⣿⣿⣿⣷⠀  ██╔════╝██╔═══██╗██╔════╝ ████╗  ██║██║██╔══██╗",
    "  ⠀⣿⣿⣿⣿⣿⣿⠀  ██║     ██║   ██║██║  ███╗██╔██╗ ██║██║███████║",
    "  ⠀⠻⣿⣿⣿⣿⠟⠀  ╚██████╗╚██████╔╝╚██████╔╝██║ ╚████║██║██║  ██║",
]


def _estilos(variante: str, fps: int) -> dict:
    """Los EstiloGlow de la demo: colores de la rampa de la variante (lo que
    P1 resolvera desde el registro), glow y barrido encendidos a proposito."""
    r = paleta.rampa(variante)
    return {
        "banner.arte": glow.EstiloGlow(glow_intensidad=1, anim_activa=True, anim_velocidad=3,
                                       anim_ancho=8, anim_solo_al_llegar=True),
        "spinner.pensar": glow.EstiloGlow(color=r["solido"], anim_activa=True, anim_velocidad=2,
                                          anim_ancho=5),
        "prompt.marco": glow.EstiloGlow(color=r["marco"], anim_activa=True, anim_velocidad=2,
                                        anim_ancho=10),
        "prompt.etiqueta": glow.EstiloGlow(color=r["prompt"], negrita=True, glow_intensidad=1,
                                           anim_activa=True, anim_velocidad=3, anim_ancho=3),
        "prompt.flecha": glow.EstiloGlow(color=r["texto"], negrita=True),
    }


def _medir(nombre, fn):
    cpu0, t0 = time.process_time(), time.perf_counter()
    extra = fn()
    wall = time.perf_counter() - t0
    cpu = time.process_time() - cpu0
    return f"{nombre:8} {extra}  cpu={cpu:.3f}s/{wall:.2f}s ({100 * cpu / max(wall, 1e-6):.1f}%)"


def demo_banner(console, estilos, segundos, fps):
    bv = glow.BannerVivo(BANNER, estilos["banner.arte"], fps=fps)
    animado = bv.mostrar(console, tope_s=segundos)
    return f"frames={bv.frames} animado={animado} filas={bv.filas}"


def demo_spinner(console, estilos, segundos, fps):
    lv = glow.LineaViva("Maullando ideas… (0s · ctrl+c corta)", estilos["spinner.pensar"], fps=fps)
    if not lv.animar or not sys.stdout.isatty():
        console.print(lv.frame_final())
        return f"frames={lv.frames} animado=False"
    t0 = time.perf_counter()
    with console.status(lv, spinner="dots", refresh_per_second=lv.fps) as st:
        s = 0
        while time.perf_counter() - t0 < segundos:
            time.sleep(1.0)
            s += 1
            lv.set(f"Maullando ideas… ({s}s · ~{s * 40} tok · ctrl+c corta)")
            st.update(lv)
    console.print(lv.frame_final())
    return f"frames={lv.frames} animado=True"


def demo_prompt(estilos, segundos, fps, variante):
    """El prompt REAL de prompt_toolkit con message/bottom_toolbar animados por
    el pulso; en un pipe (stdin sin tty) solo imprime los fragmentos
    estaticos como ANSI."""
    marco, etiqueta, flecha = estilos["prompt.marco"], estilos["prompt.etiqueta"], estilos["prompt.flecha"]
    ancho = 60
    if not sys.stdin.isatty() or not glow.capacidades().animar:
        frags = (glow.frame_estatico_pt(marco, "─" * ancho) + [("", "\n")]
                 + glow.frame_estatico_pt(etiqueta, " cognia") + glow.frame_estatico_pt(flecha, "➤ "))
        from rich.text import Text
        # se pinta por rich para que el ANSI salga igual que el resto de la demo
        t = Text()
        for st, tr in frags:
            t.append(tr, _rich_de_pt(st))
        from rich.console import Console
        Console(force_terminal=sys.stdout.isatty(), legacy_windows=False).print(t)
        return "renders=0 animado=False (stdin sin tty o sin capacidad)"
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.styles import Style
    llamadas = {"msg": 0}

    def mensaje():
        llamadas["msg"] += 1
        return FormattedText(glow.estilizar_pt(marco, "─" * ancho, fps=fps) + [("", "\n")]
                             + glow.estilizar_pt(etiqueta, " cognia", fps=fps)
                             + glow.estilizar_pt(flecha, "➤ ", fps=fps))

    def pie():
        return FormattedText(glow.estilizar_pt(marco, "─" * ancho, fps=fps)
                             + [("class:estado", "\n qwythos-27b · ctx 12% · demo (Enter sale)")])

    s = PromptSession(message=mensaje, bottom_toolbar=pie, style=Style.from_dict({
        "": f"{glow.clase_pt(flecha)}", "bottom-toolbar": "noreverse bg:default",
        "estado": f"fg:{paleta.rampa(variante)['estado']}"}))
    renders = {"n": 0}
    flush = s.app.output.flush

    def _flush():
        renders["n"] += 1
        return flush()
    s.app.output.flush = _flush
    dur = glow.duracion_pulso([marco, etiqueta], tope_s=segundos)
    glow.pulso_prompt(s.app, dur, fps)
    with patch_stdout(raw=True):
        r = s.prompt()
    glow.parar_pulso()
    return (f"renders={renders['n']} msg_calls={llamadas['msg']} calc={glow.CALCULOS} "
            f"pulso={dur:.1f}s respuesta={r!r} refresh_interval={s.refresh_interval}")


def _rich_de_pt(st: str):
    """'fg:#hex bold' -> Style de rich (solo para pintar el prompt estatico)."""
    from rich.style import Style
    kw = {}
    for tok in st.split():
        if tok.startswith("fg:"):
            kw["color"] = tok[3:].replace("ansi", "")
        elif tok.startswith("bg:"):
            kw["bgcolor"] = tok[3:].replace("ansi", "")
        elif tok in ("bold", "italic", "underline"):
            kw[tok] = True
    try:
        return Style(**kw)
    except Exception:
        return Style()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--segundos", type=float, default=2.0, help="duracion de cada zona (tope 3 s)")
    ap.add_argument("--fps", type=int, default=glow.FPS)
    ap.add_argument("--variante", default=(os.environ.get("COGNIA_THEME") or "oscuro"))
    args = ap.parse_args()
    from rich.console import Console
    console = Console(legacy_windows=False)
    caps = glow.capacidades()
    estilos = _estilos(args.variante, args.fps)
    console.print(f"capacidades: nivel={caps.nivel} animar={caps.animar}"
                  + (f" motivo={caps.motivo}" if caps.motivo else "")
                  + f" tty={sys.stdout.isatty()} fps={args.fps}")
    lineas = [_medir("banner", lambda: demo_banner(console, estilos, args.segundos, args.fps)),
              _medir("spinner", lambda: demo_spinner(console, estilos, args.segundos, args.fps)),
              _medir("prompt", lambda: demo_prompt(estilos, args.segundos, args.fps, args.variante))]
    console.print("\n".join(lineas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
