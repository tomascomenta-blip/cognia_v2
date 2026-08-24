# -*- coding: utf-8 -*-
"""scripts/aspecto_snapshots.py -- el CONTRAFACTUAL del sistema de estilos.

QUE: genera (y regenera) los snapshots ANSI del aspecto ACTUAL de cada
elemento visual del CLI -- banner, marco del prompt, barra de estado, tools,
footer, avisos, diff, spinner, respuesta markdown, paneles, tokens del tema --
en tests/golden/aspecto/*.ansi. tests/test_ux_aspecto.py regenera cada uno con
las MISMAS funciones y lo compara byte a byte contra el fichero comiteado.

POR QUE: la regla numero uno del sistema de estilos (DISENO_ESTILOS.md, D4) es
que con ~/.cognia/estilo.json ausente la salida NO cambia ni un byte. Eso no se
protege con confianza: se protege con un snapshot tomado ANTES de tocar codigo
(paso P0) y comparado despues de cada paso. Es el contrafactual, no el
recuerdo de como se veia.

COMO (determinismo): todo lo que hoy mueve la salida se FIJA dentro de
`entorno_fijo()` y se lista aqui (enmienda E4 del critico):

  env     COGNIA_BANNER, COGNIA_THEME, COGNIA_REMOTO, NO_COLOR, COGNIA_ACCENT,
          COGNIA_SPINNER_INFO, LINES, COLUMNS   -> SIN definir
          COGNIA_ASCII=0 (glifos Unicode), COGNIA_ENLACES=0 (sin OSC-8),
          COGNIA_RENDER_COLAPSO=1 (o 0 en los snapshots '*_clasico'),
          COGNIA_SPINNER=1 solo en el snapshot del spinner
  cli     _theme_idx=0 (variante 'oscuro'), _load_config() = _CONFIG_DEFAULTS,
          _variante_banner() = 'completo', _arranque_ux() = no-op,
          _console = la Console grabadora del snapshot
  cognia  __version__ = VERSION_FIJA (el banner imprime 'v{ver}')
  backend backend_activo.estado() = {modelo, puerto, url} fijos
  shutil  get_terminal_size() = (ancho del snapshot, 40)
  time    solo en prompt_espera: cli.time.time() fijo (imprime '{N}s')

Consolas: rich -> Console(force_terminal=True, color_system='truecolor',
legacy_windows=False, width=W, theme=Theme(paleta.tema_cli(v))) sobre un
StringIO (se guarda lo que ESCRIBIO, no export_text). prompt_toolkit ->
Vt100_Output(..., default_color_depth=ColorDepth.DEPTH_24_BIT) sobre un pipe
(enmienda E5: con 'xterm-256color' salen 0 escapes '38;2;' y un hex vecino
cae en la misma celda del cubo).

QUE NO SE SNAPSHOTEA (enmienda E11): las 10 lineas [success_dim]/[bold] de los
listados de /agente (cli.py ~13700-14400); son sitios que P6 migra a tokens a
proposito y no son elementos del registro.

Uso:
    PYTHONUTF8=1 venv312/Scripts/python.exe scripts/aspecto_snapshots.py            # escribe todos
    PYTHONUTF8=1 venv312/Scripts/python.exe scripts/aspecto_snapshots.py --ver banner_80
    PYTHONUTF8=1 venv312/Scripts/python.exe scripts/aspecto_snapshots.py --comparar  # como el test
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

GOLDEN = RAIZ / "tests" / "golden" / "aspecto"

# Lo fijo de los snapshots. Cambiar cualquiera de estos = regenerar TODO.
VERSION_FIJA = "4.9.0"
MODELO_FIJO = "Qwen3.8-27B-Ridge-Q4_K_M.gguf"
PUERTO_FIJO = 8080
URL_FIJA = f"http://127.0.0.1:{PUERTO_FIJO}"
VARIANTES = ("oscuro", "claro", "alto_contraste")
# Datos de la barra de estado (los mismos de tests/test_marco_prompt.py):
# sin 'dir' ni 'rama' a proposito, para no depender del cwd ni de git.
DATOS_BARRA = {"modelo": "qwythos-9b", "tokens": 12400, "ventana": 131072,
               "modo": "chat"}

_ENV_SIN_DEFINIR = ("COGNIA_BANNER", "COGNIA_THEME", "COGNIA_REMOTO",
                    "NO_COLOR", "COGNIA_ACCENT", "COGNIA_SPINNER_INFO",
                    "COGNIA_SPINNER", "LINES", "COLUMNS", "COGNIA_PENSAR",
                    "COGNIA_EVENTS_JSONL", "FORCE_COLOR", "CLICOLOR_FORCE")
_ENV_FIJO = {"COGNIA_ASCII": "0", "COGNIA_ENLACES": "0",
             "COGNIA_RENDER_COLAPSO": "1"}


# ---------------------------------------------------------------------------
# Entorno fijo
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def entorno_fijo(ancho: int = 80, extra_env: dict | None = None):
    """Fija env + globales del CLI mientras dura el `with`; restaura todo al
    salir (tambien si el snapshot lanza). Devuelve el modulo cognia.cli."""
    import cognia
    import cognia.cli as C
    from cognia import backend_activo

    env_previo = {k: os.environ.get(k) for k in
                  list(_ENV_SIN_DEFINIR) + list(_ENV_FIJO) + list(extra_env or {})}
    for k in _ENV_SIN_DEFINIR:
        os.environ.pop(k, None)
    os.environ.update(_ENV_FIJO)
    os.environ.update(extra_env or {})

    guardado = {
        "cli._theme_idx": C._theme_idx,
        "cli._load_config": C._load_config,
        "cli._variante_banner": C._variante_banner,
        "cli._arranque_ux": C._arranque_ux,
        "cli._console": C._console,
        "cognia.__version__": getattr(cognia, "__version__", None),
        "backend.estado": backend_activo.estado,
        "shutil.get_terminal_size": shutil.get_terminal_size,
    }
    defaults = dict(C._CONFIG_DEFAULTS)
    C._theme_idx = 0
    C._load_config = lambda: dict(defaults)
    C._variante_banner = lambda: "completo"
    C._arranque_ux = lambda: None
    cognia.__version__ = VERSION_FIJA
    backend_activo.estado = lambda: {"url": URL_FIJA, "modelo": MODELO_FIJO,
                                     "puerto": PUERTO_FIJO, "avisos": []}
    shutil.get_terminal_size = lambda *a, **k: os.terminal_size((ancho, 40))
    try:
        yield C
    finally:
        C._theme_idx = guardado["cli._theme_idx"]
        C._load_config = guardado["cli._load_config"]
        C._variante_banner = guardado["cli._variante_banner"]
        C._arranque_ux = guardado["cli._arranque_ux"]
        C._console = guardado["cli._console"]
        cognia.__version__ = guardado["cognia.__version__"]
        backend_activo.estado = guardado["backend.estado"]
        shutil.get_terminal_size = guardado["shutil.get_terminal_size"]
        for k, v in env_previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def consola(ancho: int = 80, variante: str = "oscuro"):
    """Console de verdad (truecolor, ancho fijo) sobre un StringIO."""
    from rich.console import Console
    from rich.theme import Theme
    from cognia.ux import paleta
    return Console(file=io.StringIO(), width=ancho, force_terminal=True,
                   color_system="truecolor", legacy_windows=False,
                   theme=Theme(paleta.tema_cli(variante)), highlight=False)


def _salida(con) -> str:
    return con.file.getvalue()


def render_prompt(mensaje, pie, columnas: int = 100, teclas: str = "hola\r",
                  estilo=None) -> str:
    """Lo que la terminal recibiria de prompt_toolkit, en 24 bits (E5)."""
    import cognia.cli as C
    from prompt_toolkit import PromptSession
    from prompt_toolkit.data_structures import Size
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.color_depth import ColorDepth
    from prompt_toolkit.output.vt100 import Vt100_Output

    buf = io.StringIO()
    out = Vt100_Output(buf, lambda: Size(rows=30, columns=columnas),
                       term="xterm-256color",
                       default_color_depth=ColorDepth.DEPTH_24_BIT)
    with create_pipe_input() as inp:
        inp.send_text(teclas)
        s = PromptSession(input=inp, output=out, bottom_toolbar=pie,
                          style=estilo or C._estilo_prompt())

        def _pre():
            # Sobre un pipe no llega la respuesta CPR: prompt_toolkit no sabe
            # su altura y ESCONDE el bottom_toolbar. Se la damos.
            s.app.renderer._min_available_height = 6

        s.prompt(mensaje, pre_run=_pre)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Snapshots: cada funcion devuelve el TEXTO (con escapes) del elemento
# ---------------------------------------------------------------------------
def _banner(ancho: int) -> str:
    with entorno_fijo(ancho) as C:
        con = consola(ancho)
        C._console = con
        C._print_startup_panel()
        return _salida(con)


def snap_banner_80() -> str:
    """Banner a 80 columnas: arte + guia APILADOS (ancho < 100)."""
    return _banner(80)


def snap_banner_120() -> str:
    """Banner a 120 columnas: arte a la izquierda, 'Para empezar' a la
    derecha (E4: a 80 la guia va debajo y P7 podria romperla sin verse)."""
    return _banner(120)


def _prompt_marco(columnas: int) -> str:
    with entorno_fijo(columnas) as C:
        from cognia.harness.barra_estado import toolbar_prompt_toolkit
        pie = C._pie_prompt(toolbar_prompt_toolkit(
            lambda: DATOS_BARRA, contexto_atajos="repl", unicode_ok=True))
        return render_prompt(C._mensaje_prompt, pie, columnas=columnas)


def snap_prompt_marco_100() -> str:
    """Regla + 'cognia>' + regla + barra de estado + atajos, a 100 col."""
    return _prompt_marco(100)


def snap_prompt_marco_80() -> str:
    return _prompt_marco(80)


def snap_prompt_espera_100() -> str:
    """El prompt del carril de fondo (_mensaje_espera): 'jarvis 5s'."""
    with entorno_fijo(100) as C:
        import types

        class _Corrida:
            etiqueta = "corrida"
            t0 = 1000.0

        reloj_previo = C.time
        C.time = types.SimpleNamespace(time=lambda: 1005.0)
        try:
            return render_prompt(C._mensaje_espera(_Corrida()), C._pie_prompt(),
                                 columnas=100)
        finally:
            C.time = reloj_previo


def _renderer(con):
    from cognia.ux.renderer import Renderer
    return Renderer(console=con)


def _resultado_lectura(n: int = 46) -> str:
    cuerpo = "\n".join(f"linea {i + 1} de motor.py" for i in range(n))
    return f"RESULTADO leer_archivo motor.py:\n{cuerpo}"


def _tool_ok(colapso: str) -> str:
    with entorno_fijo(80, {"COGNIA_RENDER_COLAPSO": colapso}):
        from cognia.ux import events, tool_buffer
        con = consola(80)
        r = _renderer(con)
        tool_buffer.nuevo_turno()
        try:
            res = _resultado_lectura()
            tool_buffer.registrar("leer_archivo", "motor.py", res, ok=True)
            r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                             resumen=res[:200], paso=1))
        finally:
            tool_buffer.nuevo_turno()
        return _salida(con)


def snap_tool_ok_colapsado() -> str:
    """Tool terminada, render colapsado (vineta + cabeza + '... +N lineas')."""
    return _tool_ok("1")


def snap_tool_ok_clasico() -> str:
    """Tool terminada, render clasico (marca ⏺ + verbo + objeto + cabeza)."""
    return _tool_ok("0")


def _tool_error(colapso: str) -> str:
    with entorno_fijo(80, {"COGNIA_RENDER_COLAPSO": colapso}):
        from cognia.ux import events, tool_buffer
        con = consola(80)
        r = _renderer(con)
        tool_buffer.nuevo_turno()
        try:
            res = "RESULTADO leer_archivo no_existe.py: ERROR: no existe el archivo"
            tool_buffer.registrar("leer_archivo", "no_existe.py", res, ok=False)
            r(events.ToolFin(tool="leer_archivo", args="no_existe.py", ok=False,
                             resumen=res[:200], paso=2))
        finally:
            tool_buffer.nuevo_turno()
        return _salida(con)


def snap_tool_error_colapsado() -> str:
    return _tool_error("1")


def snap_tool_error_clasico() -> str:
    return _tool_error("0")


def snap_tool_intencion() -> str:
    """'  Voy a leer motor.py' en italica (token intencion)."""
    with entorno_fijo(80):
        from cognia.ux import events
        con = consola(80)
        r = _renderer(con)
        r(events.PasoIntencion(paso=1, intencion="Voy a leer motor.py para ver la firma"))
        return _salida(con)


def snap_diff_preview() -> str:
    """Preview de editar_archivo: bandas +/- del diff (render clasico: sin
    entrada en tool_buffer el colapsado no aplica y se pinta el preview)."""
    with entorno_fijo(80):
        from cognia.ux import events, tool_buffer
        tool_buffer.nuevo_turno()
        con = consola(80)
        r = _renderer(con)
        r(events.ToolFin(tool="editar_archivo",
                         args="app.py | <<<<<<< SEARCH\nviejo()\n=======\n"
                              "nuevo()\n>>>>>>> REPLACE",
                         ok=True, resumen="OK", paso=1))
        return _salida(con)


def snap_footer() -> str:
    """Footer del turno: ok y error, con tokens y pasos."""
    with entorno_fijo(80):
        from cognia.ux import events
        con = consola(80)
        r = _renderer(con)
        r._footer(events.TareaFin(ok=True, duracion_s=12.3,
                                  tokens_predichos=840, pasos=3))
        r._footer(events.TareaFin(ok=False, duracion_s=4.0,
                                  tokens_predichos=0, pasos=1))
        return _salida(con)


def snap_footer_cli() -> str:
    """El footer del fast-path de cli._show_footer (sin glifo)."""
    with entorno_fijo(80) as C:
        con = consola(80)
        C._console = con
        C._show_footer(12.3, "", tokens=840)
        C._show_footer(4.0, "")
        return _salida(con)


def snap_avisos() -> str:
    """Aviso tenue, degradado (con accion sugerida) y el error de un log."""
    with entorno_fijo(80) as C:
        from cognia.ux import events
        con = consola(80)
        r = _renderer(con)
        r(events.Aviso(texto="[backend] via=llama.cpp :8080", origen="llama_backend"))
        r(events.Degradado(donde="spinner", motivo="RuntimeError: sin tty",
                           accion_sugerida="COGNIA_SPINNER=0 lo apaga"))
        C._console = con
        con.print("[err_cl]ERROR: no se pudo abrir motor.py[/err_cl]", highlight=False)
        return _salida(con)


def snap_spinner() -> str:
    """El markup del status (tool y pensar), el nombre del spinner de rich y
    la linea viva de spinner_vivo con reloj FIJO (t0=0, ahora=12, 1360 chars)."""
    with entorno_fijo(80, {"COGNIA_SPINNER": "1"}):
        from cognia.ux import spinner_vivo
        from cognia.ux.renderer import Renderer

        class _Status:
            def __init__(self, texto, spinner=None):
                self.texto, self.spinner = texto, spinner

            def start(self):
                pass

            def stop(self):
                pass

            def update(self, texto):
                pass

        class _Consola:
            def __init__(self):
                self.statuses = []

            def status(self, texto, spinner=None):
                st = _Status(texto, spinner)
                self.statuses.append(st)
                return st

            def print(self, *a, **k):
                pass

        fake = _Consola()
        r = Renderer(console=fake)
        r._arrancar_status("Leyendo motor.py…", estilo="spinner")
        r._parar_status()
        r._arrancar_status("pensando…", estilo="pensar", rotar=True)
        r._parar_status()
        lineas = [f"status[{i}] spinner={st.spinner} markup={st.texto}"
                  for i, st in enumerate(fake.statuses)]
        viva_tool = spinner_vivo.linea_estado("Leyendo motor.py…", 0.0, 12.0,
                                              1360, ancho=94)
        viva_pensar = spinner_vivo.linea_estado(None, 0.0, 3.0, 0, ancho=94)
        lineas.append(f"tick_tool markup=[spinner]· {viva_tool}[/spinner]")
        lineas.append(f"tick_pensar markup=[pensar]· {viva_pensar}[/pensar]")
        lineas.append("componer_linea estrecha="
                      + spinner_vivo.componer_linea("Amasando la respuesta", 7,
                                                    tokens=120, ancho=30))
        return "\n".join(lineas) + "\n"


def snap_pensando() -> str:
    """La prosa del razonamiento en vivo (estilo pensar+dim+italic) y la
    linea plegada '∴ penso 4s (...)'."""
    with entorno_fijo(80):
        from rich.text import Text
        from cognia.harness import render_tools
        from cognia.ux import renderer as R
        con = consola(80)
        r = _renderer(con)
        con.print(Text(R._SANGRIA_PENSAR + "el modelo razona en voz baja",
                       style=r._estilo_pensar_stream()), highlight=False)
        con.print(render_tools.linea_razonamiento(4), style="pensar",
                  highlight=False)
        con.print(render_tools.linea_razonamiento(4, visible=True),
                  style="pensar", highlight=False)
        return _salida(con)


def snap_respuesta_md() -> str:
    """Respuesta final del modelo como markdown (cli._show_response).

    UNICA normalizacion de todos los snapshots: rich numera cada hyperlink
    OSC-8 con un id ALEATORIO ('\\x1b]8;id=13169578;https://...'); se fija a
    id=0 para que el snapshot sea reproducible. El resto del escape (el
    target y el subrayado azul del link) queda tal cual."""
    with entorno_fijo(80) as C:
        con = consola(80)
        C._console = con
        C._show_response(
            "# Titulo\n\nTexto con **negrita**, *italica* y `codigo`.\n\n"
            "- item uno\n- item dos\n\n"
            "```python\ndef hola():\n    return 1\n```\n\n"
            "Un [enlace](https://example.org) y una regla:\n\n---\n",
            respuesta_final=True)
        return re.sub(r"\x1b\]8;id=\d+;", "\x1b]8;id=0;", _salida(con))


def snap_respuesta_prosa() -> str:
    """Respuesta NO final (ux/estilo.respuesta: sangria, sin panel)."""
    with entorno_fijo(80) as C:
        con = consola(80)
        C._console = con
        C._show_response("Una respuesta corta de chrome, sin markdown.")
        return _salida(con)


def snap_panel_y_regla() -> str:
    """Panel de chrome (borde/titulo/listado) y las reglas (console.rule y
    la de /ayuda)."""
    with entorno_fijo(80) as C:
        from rich.panel import Panel
        from rich.text import Text
        from cognia.harness import ayuda
        con = consola(80)
        C._console = con
        con.print(Panel(Text.from_markup("[listado]  turnos      3\n  tokens      840[/listado]"),
                        title="[titulo]Stats de sesion[/titulo]",
                        border_style=C._estilo_tema("borde"), padding=(0, 1)))
        con.rule("[info_dim]Tema: oscuro (guardado)[/info_dim]")
        con.print(ayuda._regla(80, True), highlight=False)
        return _salida(con)


def _tokens(variante: str) -> str:
    with entorno_fijo(80):
        from cognia.ux import paleta
        con = consola(80, variante)
        for tok in paleta.TOKENS_CLI:
            con.print(f"[{tok}]{tok}: texto de muestra[/{tok}]", highlight=False)
        return _salida(con)


def snap_tokens_oscuro() -> str:
    """Una linea por token del Theme, en 'oscuro' (= tema_rich byte a byte)."""
    return _tokens("oscuro")


def snap_tokens_claro() -> str:
    return _tokens("claro")


def snap_tokens_alto_contraste() -> str:
    return _tokens("alto_contraste")


def _estilo_prompt_json(variante: str) -> str:
    with entorno_fijo(80) as C:
        reglas = list(C._estilo_prompt(variante).style_rules)
        return json.dumps(reglas, ensure_ascii=False, indent=1) + "\n"


def snap_estilo_prompt_oscuro() -> str:
    """Las reglas del PTStyle del prompt (clase -> estilo), en orden."""
    return _estilo_prompt_json("oscuro")


def snap_estilo_prompt_claro() -> str:
    return _estilo_prompt_json("claro")


def snap_estilo_prompt_alto_contraste() -> str:
    return _estilo_prompt_json("alto_contraste")


def snap_glifos() -> str:
    """Los glifos que hoy eligen 6 modulos por su cuenta (con stdout UTF-8)."""
    with entorno_fijo(80) as C:
        from cognia.harness import render_tools, barra_estado
        from cognia.ux import selector, renderer as R, estilo as E
        g = barra_estado._glifos(True)
        filas = {
            "cli._FLECHA": C._FLECHA,
            "cli._REGLA": C._REGLA,
            "renderer._MARCA_ACTIVIDAD": R._MARCA_ACTIVIDAD,
            "renderer._MARCA_HECHO": R._MARCA_HECHO,
            "renderer._MARCA_ERROR": R._MARCA_ERROR,
            "renderer._MARCA_AVISO": R._MARCA_AVISO,
            "renderer._MARCA_PENSAR": R._MARCA_PENSAR,
            "estilo._MARCA_HECHO": E._MARCA_HECHO,
            "render_tools.curso": render_tools.glifo_estado("curso"),
            "render_tools.ok": render_tools.glifo_estado("ok"),
            "render_tools.error": render_tools.glifo_estado("error"),
            "render_tools.conector": render_tools.conector(),
            "render_tools.colgante": render_tools.conector_colgante(),
            "selector._puntero": selector._puntero(),
            "barra_estado.sep": g["sep"],
        }
        return "".join(f"{k}={v!r}\n" for k, v in filas.items())


SNAPSHOTS = {
    "banner_80": snap_banner_80,
    "banner_120": snap_banner_120,
    "prompt_marco_100": snap_prompt_marco_100,
    "prompt_marco_80": snap_prompt_marco_80,
    "prompt_espera_100": snap_prompt_espera_100,
    "tool_ok_colapsado": snap_tool_ok_colapsado,
    "tool_ok_clasico": snap_tool_ok_clasico,
    "tool_error_colapsado": snap_tool_error_colapsado,
    "tool_error_clasico": snap_tool_error_clasico,
    "tool_intencion": snap_tool_intencion,
    "diff_preview": snap_diff_preview,
    "footer": snap_footer,
    "footer_cli": snap_footer_cli,
    "avisos": snap_avisos,
    "spinner": snap_spinner,
    "pensando": snap_pensando,
    "respuesta_md": snap_respuesta_md,
    "respuesta_prosa": snap_respuesta_prosa,
    "panel_y_regla": snap_panel_y_regla,
    "tokens_oscuro": snap_tokens_oscuro,
    "tokens_claro": snap_tokens_claro,
    "tokens_alto_contraste": snap_tokens_alto_contraste,
    "estilo_prompt_oscuro": snap_estilo_prompt_oscuro,
    "estilo_prompt_claro": snap_estilo_prompt_claro,
    "estilo_prompt_alto_contraste": snap_estilo_prompt_alto_contraste,
    "glifos": snap_glifos,
}


def ruta(nombre: str) -> Path:
    return GOLDEN / f"{nombre}.ansi"


def generar(nombre: str) -> bytes:
    """Los BYTES del snapshot `nombre`, recien calculados con el codigo actual."""
    import cognia.cli as C
    if C._FLECHA != "➤ ":
        # cli.py eligio los glifos ASCII al importar: la consola no es UTF-8.
        raise RuntimeError("stdout no es UTF-8 (cli._FLECHA cayo a ASCII): "
                           "corre con PYTHONUTF8=1")
    return SNAPSHOTS[nombre]().encode("utf-8")


def leer(nombre: str) -> bytes:
    return ruta(nombre).read_bytes()


def limpiar_ansi(texto: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", texto)


def describir_diferencia(nombre: str, esperado: bytes, obtenido: bytes) -> str:
    """Mensaje legible: primer byte distinto + contexto, y el diff del texto
    sin escapes (para ver si cambio el color o el contenido)."""
    import difflib
    n = next((i for i, (a, b) in enumerate(zip(esperado, obtenido)) if a != b),
             min(len(esperado), len(obtenido)))
    ini = max(0, n - 60)
    ctx_e = esperado[ini:n + 60].decode("utf-8", "replace")
    ctx_o = obtenido[ini:n + 60].decode("utf-8", "replace")
    plano_e = limpiar_ansi(esperado.decode("utf-8", "replace")).splitlines()
    plano_o = limpiar_ansi(obtenido.decode("utf-8", "replace")).splitlines()
    diff = "\n".join(difflib.unified_diff(plano_e, plano_o, "golden", "ahora",
                                          lineterm="", n=1))
    return (f"snapshot '{nombre}' cambio (byte {n} de {len(esperado)} -> "
            f"{len(obtenido)})\n  golden: {ctx_e!r}\n  ahora : {ctx_o!r}\n"
            + ("  diff del texto sin escapes:\n" + diff if diff else
               "  (el texto sin escapes es IDENTICO: cambio el color/estilo)"))


def escribir_todos() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for nombre in SNAPSHOTS:
        datos = generar(nombre)
        ruta(nombre).write_bytes(datos)
        print(f"  {nombre:32} {len(datos):6} bytes")


def comparar_todos() -> int:
    fallos = 0
    for nombre in SNAPSHOTS:
        if not ruta(nombre).exists():
            print(f"FALTA {nombre}")
            fallos += 1
            continue
        esperado, obtenido = leer(nombre), generar(nombre)
        if esperado != obtenido:
            print(describir_diferencia(nombre, esperado, obtenido))
            fallos += 1
        else:
            print(f"  ok {nombre}")
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ver", metavar="NOMBRE", help="imprime un snapshot (texto plano y crudo)")
    ap.add_argument("--comparar", action="store_true", help="compara contra los golden, como el test")
    args = ap.parse_args()
    if args.ver:
        datos = generar(args.ver).decode("utf-8")
        sys.stdout.write(limpiar_ansi(datos))
        sys.stdout.write("\n--- crudo ---\n" + repr(datos) + "\n")
        return 0
    if args.comparar:
        return 1 if comparar_todos() else 0
    escribir_todos()
    print(f"escritos en {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
