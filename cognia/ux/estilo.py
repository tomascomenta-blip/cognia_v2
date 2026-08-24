"""
cognia/ux/estilo.py
===================
Capa de presentacion CONVERSACIONAL del REPL (2026-08-02).

Filosofia (pedida por el dueno, inspirada en el ritmo de interaccion de las
CLIs agenticas modernas, sin copiar a ninguna):

- Minimalismo: el espacio en blanco ES la jerarquia. Nada de paneles con borde
  alrededor de cada respuesta ni separadores ruidosos.
- La conversacion es el foco; la ejecucion de herramientas se ve como parte de
  la conversacion (una linea "· Leyendo motor.py" que al terminar queda como
  resumen compacto), nunca como un dashboard aparte.
- Lineas de largo comodo (tope ANCHO_MAX) en vez de estirar a toda la terminal.
- Streaming en trozos de palabra/frase, no caracter a caracter: se siente como
  alguien escribiendo, no como un teletipo.

El banner y los colores del producto NO viven aca y no se tocan: esta capa
solo da forma al flujo. Todo es best-effort y degradable: sin rich, cada
funcion cae a print() plano; ningun fallo de estilo puede romper un turno.
"""
from __future__ import annotations

import shutil
import textwrap
from contextlib import contextmanager

# Largo de linea comodo para leer prosa. Las terminales anchas NO se llenan.
ANCHO_MAX = 100
_SANGRIA = "  "

# Simbolos: pocos y quietos. El punto medio marca actividad; sin emojis.
_MARCA_ACTIVIDAD = "·"
_MARCA_HECHO = "⏺"
_MARCA_ERROR = "✗"


def ancho_comodo(console=None) -> int:
    """Ancho util para prosa: el de la terminal menos margen, con tope."""
    try:
        w = getattr(console, "width", None) or shutil.get_terminal_size().columns
    except Exception:
        w = 80
    return max(40, min(int(w) - len(_SANGRIA) * 2, ANCHO_MAX))


# Token del tema con el que se pinta lo que CONTESTA el modelo. Decision 17
# del dueno (2026-08-17): texto normal, no un color de acento -- el color es
# de la interfaz. Es un token y no un hex para que /tema lo pueda cambiar
# (en 'alto_contraste' la respuesta tambien sube).
ESTILO_RESPUESTA = "respuesta"


def estilo_seguro(console, nombre):
    """El token si la consola sabe resolverlo; si no, None (sin estilo).

    POR QUE: los tokens ('respuesta', 'info_dim') solo existen en las consolas
    que llevan el Theme del CLI. Una Console pelada -- un test, un embebedor,
    un script -- levanta MissingStyle y rompe el turno entero por un adorno.
    Esta capa es best-effort por contrato (ver el docstring del modulo)."""
    if console is None or not nombre:
        return None
    try:
        console.get_style(nombre)
        return nombre
    except Exception:
        return None


def respirar(console=None, n: int = 1) -> None:
    """Espacio vertical entre secciones logicas. Barato y deliberado."""
    for _ in range(max(1, n)):
        if console is not None:
            console.print()
        else:
            print()


def respuesta(texto: str, console=None, color: str = ESTILO_RESPUESTA) -> None:
    """Una respuesta de Cognia: aire arriba, sangria de 2, ancho comodo, aire
    abajo. Sin marco: el espacio en blanco delimita, no el borde.

    Las lineas largas de prosa se envuelven al ancho comodo; las lineas que
    parecen codigo/salida (empiezan con 4+ espacios o tab) NO se re-envuelven,
    para no romper indentacion.
    """
    texto = (texto or "").strip()
    if not texto:
        return
    ancho = ancho_comodo(console)
    salida: list[str] = []
    for linea in texto.split("\n"):
        if not linea.strip():
            salida.append("")
        elif linea.startswith(("    ", "\t")) or len(linea) <= ancho:
            salida.append(_SANGRIA + linea)
        else:
            salida.append(textwrap.fill(
                linea, width=ancho,
                initial_indent=_SANGRIA, subsequent_indent=_SANGRIA))
    cuerpo = "\n".join(salida)
    if console is not None:
        respirar(console)
        console.print(cuerpo, style=estilo_seguro(console, color),
                      markup=False, highlight=False)
        respirar(console)
    else:
        print("\n" + cuerpo + "\n")


# ---------------------------------------------------------------------------
# Footer del turno: UNA forma para el chat y para el agente (2026-08-24)
# ---------------------------------------------------------------------------
# Antes el chat cerraba con '30.4s' pelado y el agente con '✓ 12.8s · 573
# tokens · 3 pasos': dos idiomas para el mismo cierre (juez 2026-08-24). Las
# dos vias construyen sus partes aca y las pintan con pintar_footer.
_GLIFO_OK = "\u2713"      # ✓
_GLIFO_FALLO = "\u2717"   # ✗
_PUNTO = " \u00b7 "       # ' · '


def footer_turno(ok: bool, segundos: float, tokens=None, pasos=None,
                 ctx_libre_pct=None, motivo: str = "",
                 ctx_estimado: bool = False) -> list:
    """Las partes del footer como [(texto, estilo)], listas para
    rich.Text.assemble: '✓ 30.4s · 412 tokens · 3 pasos · ctx 94% libre'
    y, si el turno se cerro por algo, ' · parado: 3 tools seguidas fallaron'
    en ambar. Solo datos REALES: sin usage no hay tokens (el len//4
    historico mentia), sin n_ctx no hay ctx."""
    try:
        seg = float(segundos)
    except (TypeError, ValueError):
        seg = 0.0
    partes = [f"{seg:.1f}s"]
    if tokens:
        partes.append(f"{int(tokens)} tokens")
    if pasos:
        partes.append(f"{int(pasos)} paso" + ("s" if int(pasos) != 1 else ""))
    if ctx_libre_pct is not None:
        # '~' cuando la ocupacion es ESTIMADA (chars/4, el camino de chat):
        # misma marca que la barra de estado, un numero estimado con aspecto
        # de medida es peor que decir que lo es.
        partes.append(f"ctx {'~' if ctx_estimado else ''}{int(ctx_libre_pct)}% libre")
    glifo, estilo = (_GLIFO_OK, "ok_cl") if ok else (_GLIFO_FALLO, "err_cl")
    trozos = [(_SANGRIA, ""), (glifo, estilo), (" ", ""),
              (_PUNTO.join(partes), "footer")]
    if (motivo or "").strip():
        trozos += [(_PUNTO, "footer"), (motivo.strip(), "warn_cl")]
    return trozos


def texto_footer(trozos: list) -> str:
    """El footer plano (sin estilos), p.ej. para stdout sin rich."""
    return "".join(t for t, _ in trozos)


def pintar_footer(trozos: list, console=None) -> None:
    """Pinta el footer con rich si hay consola (cada trozo con su token del
    tema, resueltos con estilo_seguro) o plano si no. Nunca lanza."""
    if console is not None:
        try:
            from rich.text import Text
            partes = [(t, estilo_seguro(console, e) or "") for t, e in trozos]
            console.print(Text.assemble(*partes), highlight=False)
            return
        except Exception:
            pass
    try:
        print(texto_footer(trozos), flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Actividad de herramientas: "· Leyendo motor.py" -> "⏺ Leyendo motor.py"
# ---------------------------------------------------------------------------
# tool del registry -> verbo en gerundio, en el vocabulario del producto.
# REGLA (2026-08-10): cada clave debe existir en agent/tools.py TOOLS (o en un
# modulo opt-in que registra via @tool al importarse: voz/musica/3d/vlm/imagen/
# browser/repo_a_prompt). Aqui vivieron 'listar_archivos'/'buscar_archivos',
# nombres que NUNCA existieron en el registry — esas tools salian como
# 'Trabajando' generico. Hay test de regresion parametrizado contra TOOLS
# (tests/test_renderer_estetica.py) para que no vuelva a pasar.
GERUNDIOS = {
    "leer_archivo":     "Leyendo",
    "escribir_archivo": "Escribiendo",
    "editar_archivo":   "Editando",
    "apendar_archivo":  "Escribiendo",
    "borrar_archivo":   "Borrando",
    "copiar_archivo":   "Copiando",
    "listar":           "Explorando",
    "arbol":            "Explorando",
    "contar_lineas":    "Contando lineas",
    "buscar":           "Buscando",
    "buscar_en_repo":   "Buscando",
    "repo_map":         "Mapeando el repo",
    "code_grafo":       "Mapeando el codigo",
    "docs_repo":        "Consultando docs",
    "docs_libreria":    "Consultando docs",
    "preguntar_repo":   "Consultando el repo",
    "abrir":            "Abriendo",
    "ejecutar":         "Ejecutando",
    "tests":            "Probando",
    "generar_codigo":   "Generando codigo",
    "py_validar":       "Validando",
    "json_validar":     "Validando",
    "calcular":         "Calculando",
    "resumir":          "Resumiendo",
    "recordar":         "Recordando",
    "memorizar":        "Memorizando",
    "cuaderno":         "Anotando",
    "kg_buscar":        "Consultando el grafo",
    "kg_agregar":       "Anotando en el grafo",
    "anotar":           "Anotando",
    "notas":            "Repasando notas",
    "web_buscar":       "Buscando en la web",
    "web_abrir":        "Leyendo la web",
    "http_get":         "Consultando",
    "git_estado":       "Mirando git",
    "git_diff":         "Mirando git",
    "git_log":          "Mirando git",
    "delegar_subtarea": "Delegando",
    "fecha":            "Consultando",
    "tarea_estado":     "Revisando la tarea",
    "bitacora_buscar":  "Consultando bitacora",
    "repo_a_prompt":    "Empaquetando el repo",
    # familias multimodales (opt-in por flag; el registry las registra al
    # importar su modulo, el gerundio esta listo desde ya)
    "voz_decir":          "Hablando",
    "voz_escuchar":       "Escuchando",
    "voz_clonar":         "Clonando voz",
    "musica_orquestar":   "Orquestando",
    "tresd_generar":      "Modelando 3D",
    "vlm_mirar":          "Mirando",
    "imagen_generar":     "Dibujando",
    "imagen_editar":      "Retocando",
    "imagen_quitar_fondo": "Recortando",
}


def verbo_de(tool: str) -> str:
    return GERUNDIOS.get((tool or "").strip(), "Trabajando")


def objeto_de(args: str, tope: int = 48) -> str:
    """Un objeto corto y legible para acompanar al verbo: el primer token de
    los args (tipicamente la ruta), sin el payload despues de '|'."""
    args = (args or "").split("|", 1)[0].strip()
    if not args:
        return ""
    primera = args.split()[0].replace("\\", "/").strip("'\"")
    if len(primera) > tope:
        primera = "…" + primera[-(tope - 1):]
    return primera


@contextmanager
def actividad(tool: str, args: str = "", console=None):
    """Mientras una herramienta corre: '· Leyendo motor.py…' (spinner efimero
    con rich; una linea quieta sin el). No imprime el resumen final: eso lo
    hace resumen_hecho(), con el resultado ya conocido.

    NO-LANZANTE por contrato: todo lo de estilo esta guardado, asi el caller
    puede envolver la ejecucion real de la tool sin logica de fallback (una
    tool con efectos jamas debe re-ejecutarse porque fallo el adorno)."""
    verbo, obj = verbo_de(tool), objeto_de(args)
    etiqueta = f"{verbo} {obj}…".replace("  ", " ").strip()
    status = None
    if console is not None:
        try:
            status = console.status(
                f"[spinner]{_MARCA_ACTIVIDAD} {etiqueta}[/spinner]",
                spinner="dots")
            status.start()
        except Exception:
            status = None    # consola no interactiva: cae a la linea quieta
    if status is None:
        try:
            print(f"{_SANGRIA}{_MARCA_ACTIVIDAD} {etiqueta}", flush=True)
        except Exception:
            pass
    try:
        yield
    finally:
        if status is not None:
            try:
                status.stop()
            except Exception:
                pass


def resumen_hecho(tool: str, args: str = "", ok: bool = True) -> str:
    """La linea de cierre compacta de una herramienta, LISTA para _print_fn
    (con markup rich). ok=False la marca como fallo visible."""
    verbo, obj = verbo_de(tool), objeto_de(args)
    etiqueta = f"{verbo} {obj}".replace("  ", " ").strip()
    if ok:
        return f"[info_dim]{_SANGRIA}{_MARCA_HECHO} {etiqueta}[/info_dim]"
    return f"[warn_cl]{_SANGRIA}{_MARCA_ERROR} {etiqueta} — fallo[/warn_cl]"


# ---------------------------------------------------------------------------
# Streaming suave: trozos de palabra, no teletipo caracter a caracter
# ---------------------------------------------------------------------------
class FlujoSuave:
    """Agrupa los tokens del stream y los emite en trozos medianos, cortando
    en limites de palabra. El texto se siente escrito por alguien que piensa,
    no gota a gota — y en terminales lentas ademas imprime MENOS veces.

    Uso:
        f = FlujoSuave(console=_console)          # respuesta = texto normal
        for tok in stream: f.escribir(tok)
        f.cerrar()          # vacia lo que quede (siempre, tambien en except)
    """

    def __init__(self, console=None, style: str = ESTILO_RESPUESTA,
                 umbral: int = 24, sangria: str = _SANGRIA):
        # ``sangria`` configurable (2026-08-10): el razonamiento en vivo del
        # renderer usa el MISMO flujo pero con su propio inicio de linea
        # ('    ∴ '); el default conserva la sangria de 2 de siempre.
        self._console = console
        # se resuelve UNA vez: si la consola no conoce el token, se pinta sin
        # estilo en vez de reventar en cada trozo del stream
        self._style = estilo_seguro(console, style)
        self._umbral = max(4, int(umbral))
        self._sangria = sangria
        self._buf = ""
        self._al_inicio_de_linea = True

    def _emitir(self, trozo: str) -> None:
        if not trozo:
            return
        # sangria al inicio de cada linea, para alinear con respuesta()
        if self._al_inicio_de_linea:
            trozo = self._sangria + trozo
        self._al_inicio_de_linea = trozo.endswith("\n")
        if self._al_inicio_de_linea:
            trozo = trozo[:-1].replace("\n", "\n" + self._sangria) + "\n"
        else:
            trozo = trozo.replace("\n", "\n" + self._sangria)
        if self._console is not None:
            self._console.print(trozo, end="", style=self._style,
                                markup=False, highlight=False)
        else:
            print(trozo, end="", flush=True)

    def escribir(self, token: str) -> None:
        self._buf += token or ""
        # un salto de linea siempre vacia (el ritmo del parrafo manda)
        if "\n" in self._buf:
            self._emitir(self._buf)
            self._buf = ""
            return
        if len(self._buf) < self._umbral:
            return
        # vaciar hasta el ULTIMO espacio: nunca se corta una palabra a la mitad
        corte = self._buf.rfind(" ")
        if corte <= 0:
            return    # una palabra larguisima: esperar a que termine
        self._emitir(self._buf[:corte + 1])
        self._buf = self._buf[corte + 1:]

    def cerrar(self) -> None:
        if self._buf:
            self._emitir(self._buf)
            self._buf = ""
