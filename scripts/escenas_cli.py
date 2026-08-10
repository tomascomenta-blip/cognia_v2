# -*- coding: utf-8 -*-
"""Arnes de ESCENAS visuales del CLI (autoevaluacion estetica).

POR QUE: iterar estetica contra el modelo real es lento y no determinista.
Este arnes alimenta al Renderer REAL (cognia/ux/renderer.py) con eventos
sinteticos fijos y exporta cada escena a SVG con el tema REAL del CLI
(Console(record=True)). Las escenas son deterministas EN TEXTO: la misma
entrada produce el MISMO export_text; el SVG binario NO es reproducible
byte a byte (el spinner hornea 1-2 frames segun timing), asi que cualquier
gate de regresion compara export_text, nunca bytes del SVG.

FLUJO DE AUTOEVALUACION (escenas -> svg -> png -> mirar):
  1. venv312\\Scripts\\python.exe scripts\\escenas_cli.py --salida capturas_ui
     (--tema claro para la variante clara, --tema todos para las tres;
      --escena X para una sola; --png convierte al final si playwright esta)
  2. venv312\\Scripts\\python.exe scripts\\svg_a_png.py capturas_ui
     (paso aparte si no se uso --png)
  3. Mirar los PNG/SVG (humano u orquestador con vision) y decidir si la
     estetica mejoro; los cambios de TEXTO se cazan como regresion en
     tests/test_escenas_cli.py (export_text determinista).

Escenas: banner, chat (streaming), agente (tools ok/error), pensando,
degradado, archivos (escribir/editar/apendar/leer — "ver lo escrito"),
pensar_visible (razonamiento opt-in con COGNIA_PENSAR=ver), selector
(frame estatico del selector de flechas).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Constantes de las escenas, expuestas para que los tests no dupliquen
# literales (si cambia el guion, el test sigue apuntando a lo mismo).
ARCHIVO_DEMO = "notas/plan.md"
CONTENIDO_DEMO = ("# Plan\n"
                  "- paso 1: leer el codigo existente\n"
                  "- paso 2: escribir el modulo\n"
                  "- paso 3: verificar con tests")
BLOQUE_EDICION_DEMO = ("<<<<<<< SEARCH\n"
                       "- paso 2: escribir el modulo\n"
                       "=======\n"
                       "- paso 2: escribir el modulo con tests\n"
                       ">>>>>>> REPLACE")
FRAGMENTOS_PENSAR = [
    "Primero entiendo el problema: piden la suma de una serie aritmetica "
    "y conviene evitar el bucle explicito. ",
    "Hay dos caminos posibles: iterar de 1 a n, que es O(n), o usar la "
    "formula cerrada de Gauss n(n+1)/2, que es O(1). ",
    "La formula cerrada gana en claridad y en coste; el unico riesgo "
    "clasico es el overflow y en Python no aplica. ",
    "Verifico con n=10: 10*11/2 = 55, coincide con la suma manual. "
    "Respondo con la formula. ",
]
# Contrato de cognia/ux/selector.py: tuplas (valor, etiqueta, descripcion).
OPCIONES_SELECTOR = [
    ("qwythos-9b", "qwythos-9b   5.0G", "activo · cerebro por defecto"),
    ("gpt-oss-20b", "gpt-oss-20b  12.1G", "pensador (combo pensar)"),
    ("uigen-8b", "uigen-8b     4.7G", "constructor web"),
    ("unico", "modo unico", "solo este equipo"),
]


def consola_grabadora(tema: str):
    from rich.console import Console
    from cognia.cli import _THEMES
    return Console(theme=_THEMES[tema], record=True, width=100,
                   force_terminal=True, highlight=False)


def _eventos_chat(r):
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="hola, que sabes de mi?", modo="chat",
                     modelo="qwythos-9b"))
    for tick in range(3):
        e = ev.RazonamientoTick(chars=100 * (tick + 1), fragmento="analizo…")
        r(e)
    for trozo in ["Hola. ", "Se que estas construyendo ", "Cognia, ",
                  "un sistema cognitivo local ", "con memoria y agente.\n"]:
        r(ev.TokenTexto(texto=trozo))
    r(ev.TareaFin(ok=True, resumen="", pasos=0, tokens_predichos=182,
                  duracion_s=3.4))


def _eventos_agente(r):
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="crea datos.csv y analiza.py que lo lea",
                     modo="agente", modelo="qwythos-9b"))
    r(ev.PasoIntencion(paso=1, intencion="Voy a crear datos.csv con los datos"))
    r(ev.ToolInicio(tool="escribir_archivo", args="datos.csv | 10,20,30", paso=1))
    r(ev.ToolFin(tool="escribir_archivo", args="datos.csv | 10,20,30", ok=True,
                 resumen="OK escrito datos.csv (11 bytes)", duracion_s=0.1,
                 paso=1))
    r(ev.ToolInicio(tool="leer_archivo", args="datos.csv", paso=2))
    r(ev.ToolFin(tool="leer_archivo", args="datos.csv", ok=True,
                 resumen="3 lineas", duracion_s=0.05, paso=2))
    r(ev.ToolInicio(tool="ejecutar", args="python analiza.py", paso=3))
    r(ev.ToolFin(tool="ejecutar", args="python analiza.py", ok=False,
                 resumen="ERROR (exit 9009): Python was not found", paso=3,
                 duracion_s=0.4))
    r(ev.ToolInicio(tool="ejecutar", args="py analiza.py", paso=4))
    r(ev.ToolFin(tool="ejecutar", args="py analiza.py", ok=True,
                 resumen="60", duracion_s=0.3, paso=4))
    for trozo in ["Listo: ", "datos.csv y analiza.py creados. ",
                  "La suma verificada es 60.\n"]:
        r(ev.TokenTexto(texto=trozo))
    r(ev.TareaFin(ok=True, resumen="", pasos=4, tokens_predichos=1139,
                  duracion_s=18.2))


def _eventos_pensando(r):
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="problema dificil", modo="chat", modelo="qwythos-9b"))
    for tick in range(4):
        r(ev.RazonamientoTick(
            chars=300 * (tick + 1),
            fragmento=["Primero entiendo el problema. ",
                       "Hay dos caminos posibles: iterar o cerrar la formula. ",
                       "La formula cerrada es O(1), gana. ",
                       "Verifico con n=10: correcto. "][tick]))
    for trozo in ["La suma de 1 a n ", "es n(n+1)/2.\n"]:
        r(ev.TokenTexto(texto=trozo))
    r(ev.TareaFin(ok=True, resumen="", pasos=0, tokens_predichos=412,
                  duracion_s=7.9))


def _eventos_degradado(r):
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="tarea con avisos", modo="agente",
                     modelo="qwythos-9b"))
    r(ev.Aviso(texto="backend: qwythos :8080 via agente_chat",
               origen="backend_activo"))
    r(ev.Degradado(donde="cli.agente.horizonte", motivo="flag apagado",
                   accion_sugerida="COGNIA_HORIZONTE=1 para tareas largas"))
    r(ev.TareaFin(ok=False, resumen="", pasos=1, tokens_predichos=50,
                  duracion_s=2.0))


def _eventos_archivos(r):
    """La escena que demuestra "ver lo escrito": escribir con contenido
    multilinea en args (materia prima del preview '+ ' del renderer),
    editar con bloque SEARCH/REPLACE, apendar y releer."""
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="escribe el plan en notas/plan.md y ajustalo",
                     modo="agente", modelo="qwythos-9b"))
    r(ev.PasoIntencion(paso=1, intencion="Voy a escribir el plan inicial"))
    args_escribir = f"{ARCHIVO_DEMO} | {CONTENIDO_DEMO}"
    r(ev.ToolInicio(tool="escribir_archivo", args=args_escribir, paso=1))
    r(ev.ToolFin(tool="escribir_archivo", args=args_escribir, ok=True,
                 resumen=f"OK escrito {ARCHIVO_DEMO} "
                         f"({len(CONTENIDO_DEMO)} chars)",
                 duracion_s=0.1, paso=1))
    r(ev.PasoIntencion(paso=2, intencion="Ajusto el paso 2 del plan"))
    args_editar = f"{ARCHIVO_DEMO} | {BLOQUE_EDICION_DEMO}"
    r(ev.ToolInicio(tool="editar_archivo", args=args_editar, paso=2))
    r(ev.ToolFin(tool="editar_archivo", args=args_editar, ok=True,
                 resumen="1 bloque aplicado", duracion_s=0.1, paso=2))
    args_apendar = f"{ARCHIVO_DEMO} | - paso 4: publicar"
    r(ev.ToolInicio(tool="apendar_archivo", args=args_apendar, paso=3))
    r(ev.ToolFin(tool="apendar_archivo", args=args_apendar, ok=True,
                 resumen="OK apendado (1 linea)", duracion_s=0.05, paso=3))
    r(ev.ToolInicio(tool="leer_archivo", args=ARCHIVO_DEMO, paso=4))
    r(ev.ToolFin(tool="leer_archivo", args=ARCHIVO_DEMO, ok=True,
                 resumen="5 lineas", duracion_s=0.05, paso=4))
    for trozo in ["Plan escrito en ", "notas/plan.md ",
                  "con 4 pasos verificados.\n"]:
        r(ev.TokenTexto(texto=trozo))
    r(ev.TareaFin(ok=True, resumen="", pasos=4, tokens_predichos=640,
                  duracion_s=9.5))


def _renderer_muestra_fragmentos() -> bool:
    """True si el Renderer real ya honra COGNIA_PENSAR=ver (entrega E1).

    POR QUE por fuente y no por flag propio: el arnes no debe duplicar la
    logica del renderer; cuando E1 la cablee, el mock de abajo se apaga solo.
    """
    try:
        import inspect
        from cognia.ux import renderer as _r
        return "COGNIA_PENSAR" in inspect.getsource(_r)
    except Exception:
        return False


def _ticks_pensar(r):
    """Emite 4 ticks de razonamiento con fragmentos largos + respuesta.

    Si COGNIA_PENSAR=ver esta activo y el Renderer real aun no muestra los
    fragmentos, un mock fiel los pinta con la forma esperada (sangria 4,
    info_dim) para poder iterar la estetica YA.
    TODO(E1): borrar el mock cuando renderer._on_razonamiento_tick muestre
    ev.fragmento bajo COGNIA_PENSAR=ver.
    """
    from cognia.ux import events as ev
    r(ev.TareaInicio(tarea="suma de 1 a n sin bucle", modo="chat",
                     modelo="qwythos-9b"))
    ver = os.environ.get("COGNIA_PENSAR", "").strip() == "ver"
    mock = ver and not _renderer_muestra_fragmentos()
    total = 0
    for frag in FRAGMENTOS_PENSAR:
        total += len(frag)
        r(ev.RazonamientoTick(chars=total, fragmento=frag))
        if mock:
            r._parar_status()
            r._print(f"    {frag.strip()}", style="info_dim")
    for trozo in ["La suma de 1 a n ", "se calcula con la formula ",
                  "cerrada n(n+1)/2; ", "para n=10 da 55.\n"]:
        r(ev.TokenTexto(texto=trozo))
    r(ev.TareaFin(ok=True, resumen="", pasos=0, tokens_predichos=530,
                  duracion_s=6.1))


def _eventos_pensar_visible(r):
    """Demuestra el razonamiento OPCIONAL: COGNIA_PENSAR=ver se setea DENTRO
    de la escena y se restaura al final (la escena no contamina el proceso).

    POR QUE renderer fresco: si el Renderer cachea el flag en __init__ (como
    hace con COGNIA_REMOTO), el que llego construido no lo veria; se crea uno
    nuevo sobre la MISMA console para que el flag aplique seguro."""
    from cognia.ux.renderer import Renderer
    previo = os.environ.get("COGNIA_PENSAR")
    os.environ["COGNIA_PENSAR"] = "ver"
    try:
        r2 = Renderer(r._console)
        _ticks_pensar(r2)
        r2._parar_status()
    finally:
        if previo is None:
            os.environ.pop("COGNIA_PENSAR", None)
        else:
            os.environ["COGNIA_PENSAR"] = previo


def _escena_selector(con):
    """Frame ESTATICO del selector de flechas: sin tty no hay interaccion,
    asi que se pinta UN frame como lo haria elegir() con la opcion 0 activa.

    Usa cognia.ux.selector.render_frame si ya existe (funcion pura que
    devuelve lineas con estilos); mientras E2 no la exponga, un mock FIEL
    replica _elegir_flechas._fragmentos: titulo en bold, fila activa en
    video inverso con puntero, descripcion tenue a la derecha.
    TODO(E2): exponer render_frame(titulo, opciones, activa) en
    cognia/ux/selector.py y borrar el mock del else."""
    titulo = "Modelo para el cerebro"
    activa = 0
    try:
        from cognia.ux.selector import render_frame
    except Exception:
        render_frame = None
    if render_frame is not None:
        for item in render_frame(titulo, OPCIONES_SELECTOR, activa):
            if isinstance(item, (tuple, list)):
                texto = item[0]
                estilo = item[1] if len(item) > 1 else ""
                con.print(texto, style=estilo or None, markup=False,
                          highlight=False)
            else:
                con.print(item, highlight=False)
        return
    from rich.text import Text
    con.print(Text(titulo, style="bold"))
    for i, (_valor, etiqueta, desc) in enumerate(OPCIONES_SELECTOR):
        linea = Text()
        if i == activa:
            linea.append(f" ❯ {etiqueta} ", style="reverse")
        else:
            linea.append(f"   {etiqueta} ")
        if desc:
            linea.append(f"  {desc}", style="info_dim")
        con.print(linea)


def _escena_banner(con):
    try:
        import cognia.cli as _cli
        _con_previa = _cli._console
        _cli._console = con
        try:
            _cli._print_banner_completo()
        finally:
            _cli._console = _con_previa
    except Exception as exc:
        con.print(f"(banner no disponible: {exc})")


# Escenas que se guionan contra el Renderer real (reciben el renderer).
ESCENAS = {
    "chat": _eventos_chat,
    "agente": _eventos_agente,
    "pensando": _eventos_pensando,
    "degradado": _eventos_degradado,
    "archivos": _eventos_archivos,
    "pensar_visible": _eventos_pensar_visible,
}

# Escenas que pintan directo sobre la console (no pasan por el bus).
ESCENAS_CONSOLA = {
    "selector": _escena_selector,
}


def _a_png(carpeta: Path) -> None:
    """Convierte los SVG de la carpeta a PNG via scripts/svg_a_png.py.
    Solo si playwright esta instalado; si no, se avisa y se sigue (el SVG
    ya es mirable en un navegador)."""
    try:
        import playwright  # noqa: F401
    except Exception:
        print("(sin playwright: PNG omitido — el SVG se mira en navegador)")
        return
    import subprocess
    script = RAIZ / "scripts" / "svg_a_png.py"
    subprocess.run([sys.executable, str(script), str(carpeta)], check=False)


def exportar(salida: Path, temas=("oscuro",), escena: str = "",
             png: bool = False) -> list:
    """Exporta las escenas a SVG (una console fresca por escena) y devuelve
    las rutas generadas.

    POR QUE se limpia el env: COGNIA_REMOTO=1 y COGNIA_EVENTS_JSONL cambian
    los caminos de render (respuesta plana, prefijo @EV) y el Renderer cachea
    COGNIA_REMOTO en __init__ — una escena grabada bajo esos flags no es la
    estetica del terminal local. Se restauran al salir."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    from cognia.ux.renderer import Renderer

    previos = {v: os.environ.pop(v, None)
               for v in ("COGNIA_REMOTO", "COGNIA_EVENTS_JSONL")}
    generados = []
    try:
        if escena:
            nombres = [escena]
        else:
            nombres = ["banner"] + list(ESCENAS) + list(ESCENAS_CONSOLA)
        for tema in temas:
            for nombre in nombres:
                con = consola_grabadora(tema)
                if nombre == "banner":
                    _escena_banner(con)
                elif nombre in ESCENAS_CONSOLA:
                    ESCENAS_CONSOLA[nombre](con)
                elif nombre in ESCENAS:
                    r = Renderer(con)
                    ESCENAS[nombre](r)
                    r._parar_status()
                else:
                    print(f"escena desconocida: {nombre}")
                    continue
                ruta = salida / f"{nombre}_{tema}.svg"
                con.save_svg(str(ruta),
                             title=f"cognia — {nombre} ({tema})")
                print(f"escena {nombre} ->", ruta)
                generados.append(ruta)
    finally:
        for v, val in previos.items():
            if val is not None:
                os.environ[v] = val
    if png:
        _a_png(salida)
    return generados


def _resolver_temas(spec: str) -> tuple:
    from cognia.cli import _THEMES
    if spec.strip() == "todos":
        return tuple(_THEMES)
    temas = tuple(t.strip() for t in spec.split(",") if t.strip())
    for t in temas:
        if t not in _THEMES:
            raise SystemExit(f"tema desconocido: {t} "
                             f"(validos: {', '.join(_THEMES)} o 'todos')")
    return temas or ("oscuro",)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Exporta escenas visuales del CLI a SVG (y PNG opcional)")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--tema", default="oscuro",
                    help="oscuro|claro|alto_contraste, lista con comas, o "
                         "'todos'")
    ap.add_argument("--escena", default="",
                    help="una sola escena (default: todas)")
    ap.add_argument("--png", action="store_true",
                    help="convertir a PNG al final (requiere playwright)")
    args = ap.parse_args()
    exportar(Path(args.salida), temas=_resolver_temas(args.tema),
             escena=args.escena, png=args.png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
