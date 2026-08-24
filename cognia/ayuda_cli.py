# -*- coding: utf-8 -*-
"""
cognia/ayuda_cli.py — `cognia --help` con jerarquía, no una lista plana.

POR QUE EXISTE (2026-08-18). La ayuda era un string plano impreso con print():
24 comandos en una sola lista, todos con el mismo peso visual y sin una gota de
color. Es la PRIMERA pantalla del producto, y en la captura se ve exactamente
como lo que era — un volcado. El usuario que llega no tiene forma de saber por
dónde empezar, ni qué es lo que va a usar todos los días frente a lo que va a
usar una vez en la vida.

Lo que cambia: los comandos se agrupan por LO QUE QUIERES HACER, el que hay que
correr primero va primero y destacado, y el color separa comando de explicación.
El contenido no se recorta — los 24 comandos siguen estando, porque quitarle
capacidades a la ayuda es mentir sobre lo que el producto sabe hacer.

Degrada bien: sin rich, o con NO_COLOR, sale el mismo texto sin adornos.
"""
from __future__ import annotations

import os
import sys

# (comando, argumentos, que hace). El orden DENTRO de cada grupo es el orden en
# que un usuario nuevo se los encuentra, no el alfabético.
GRUPOS = [
    ("Empezar aquí", [
        ("empezar", "", "instala lo que falte, verifica el backend y abre el REPL"),
        ("(sin comando)", "", "abre el REPL (lanza el asistente en el primer uso)"),
        ("doctor", "", "diagnóstico: backend, flota, velocidad"),
    ]),
    ("Trabajar", [
        ("hacer", '"<tarea>"', "el agente hace la tarea y sale — sirve en tuberías "
                               "y scripts  [--pasos N] [--json] [-s]"),
        ("responder", '"<pregunta>"', "responde con CONFIANZA; si no le alcanza, "
                                      "investiga y cita  [--segundos N]"),
        ("rlm", '<ruta> "<pregunta>"', "pregunta sobre un contexto más grande que "
                                       "la ventana del modelo"),
        ("tutor", "", "tutor web que enseña cualquier tema (localhost:8899)  [--lan]"),
    ]),
    ("Modelos y máquina", [
        ("install-model", "", "descarga el GGUF, llama-server y los expertos"),
        ("status", "", "estado del backend local, el swarm y Ollama"),
        ("fleet", "", "los modelos GGUF que tienes instalados"),
        ("flota", "[combo]", "flota por roles: arrancar | estado | parar"),
        ("modo", "", "modo local/compartido/memoria y personalización"),
        ("init", "", "vuelve a lanzar el asistente de configuración"),
    ]),
    ("Interfaces", [
        ("tui", "", "interfaz a pantalla completa"),
        ("voz", "", "asistente de voz Jarvis (requiere el extra [voz])"),
        ("remoto", "", "control remoto desde el móvil"),
        ("server", "", "servidor web FastAPI (puerto 8000)"),
    ]),
    ("Red distribuida", [
        ("install-weights", "", "descarga shards y deja este equipo como nodo  "
                                "[--coordinator URL] [--standalone]"),
        ("node", "", "arranca como nodo del swarm"),
        ("coordinator", "", "arranca el coordinador del swarm (puerto 8001)"),
        ("contribucion", "", "tu ledger en la economía del enjambre"),
        ("leave", "", "sal de la red y libera el fragmento alojado"),
    ]),
    ("Otros", [
        ("bbrain", "", "regenera bbrain.md (doc viva del repo)"),
        ("--version", "", "la versión instalada"),
        ("help", "", "esta ayuda"),
    ]),
]

PIE = [
    ("~/.cognia/config.env", "la configuración: LLAMA_GGUF_PATH, LLAMA_SERVER_PATH… "
                             "(las variables del sistema mandan sobre este fichero)"),
    ("LLAMA_GGUF_PATH", "ruta directa a un GGUF, por encima de la detección"),
    ("COGNIA_COORDINATOR_URL", "URL del coordinador (swarm opcional)"),
    ("OLLAMA_URL", "URL de Ollama (respaldo opcional)"),
    ("HF_TOKEN", "token de HuggingFace para descargas privadas"),
]


def _sin_color() -> bool:
    """NO_COLOR manda (no-color.org), y una tubería tampoco quiere ANSI."""
    if os.environ.get("NO_COLOR"):
        return True
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return False
    return not sys.stdout.isatty()


def texto_plano() -> str:
    """La ayuda sin una sola secuencia de escape. Es lo que ve una tubería."""
    fuera = ["Uso: cognia [comando] [opciones]", ""]
    for titulo, filas in GRUPOS:
        fuera.append(f"{titulo}:")
        for cmd, args, que in filas:
            izq = f"  {cmd} {args}".rstrip()
            fuera.append(f"{izq:<28} {que}")
        fuera.append("")
    fuera.append("Configuracion:")
    for clave, que in PIE:
        fuera.append(f"  {clave:<26} {que}")
    return "\n".join(fuera)


def imprimir() -> None:
    """Pinta la ayuda. Con color y jerarquía si se puede; plana si no."""
    if _sin_color():
        print(texto_plano())
        return
    try:
        from rich.console import Console
        from rich.text import Text
    except Exception:
        print(texto_plano())
        return
    try:
        # P6 (2026-08-24): el Theme con los overrides de /estilo (sin fichero
        # de estilo es paleta.tema_cli tal cual). Antes: tema_cli() SIN la
        # variante -> TypeError -> la ayuda salia con la consola neutra.
        from rich.theme import Theme
        from cognia.ux.aspecto import tema_rich
        consola = Console(theme=Theme(tema_rich()), highlight=False)
        marca, tenue, acento = "mod", "info_dim", "ok_cl"
    except Exception:
        # Sin la paleta del proyecto seguimos pintando, con estilos neutros:
        # perder el tema no puede costar la jerarquía, que es el punto.
        consola = Console(highlight=False)
        marca, tenue, acento = "bold cyan", "dim", "bold green"

    ancho = min(consola.size.width, 100)
    consola.print(Text("cognia", style=acento).append(
        "  [comando] [opciones]", style=tenue))
    for titulo, filas in GRUPOS:
        consola.print()
        consola.print(f"[{tenue}]{titulo}[/{tenue}]")
        for cmd, args, que in filas:
            izq = Text("  ")
            izq.append(cmd, style=marca)
            if args:
                izq.append(" " + args, style=tenue)
            relleno = max(1, 26 - len(izq.plain))
            izq.append(" " * relleno)
            # La descripción se envuelve INDENTADA bajo su columna: sin esto,
            # la segunda línea vuelve al margen y la tabla deja de leerse.
            izq.append(_envuelto(que, ancho - 26, 26))
            consola.print(izq)
    consola.print()
    consola.print(f"[{tenue}]Configuración[/{tenue}]")
    for clave, que in PIE:
        linea = Text("  ")
        linea.append(clave, style=marca)
        linea.append(" " * max(1, 26 - len(clave) - 2))
        linea.append(_envuelto(que, ancho - 26, 26), style=tenue)
        consola.print(linea)


def _envuelto(texto: str, ancho: int, sangria: int) -> str:
    """Envuelve `texto` a `ancho`, sangrando las líneas siguientes."""
    if ancho <= 10 or len(texto) <= ancho:
        return texto
    palabras, lineas, actual = texto.split(), [], ""
    for palabra in palabras:
        if len(actual) + len(palabra) + 1 > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    lineas.append(actual)
    return ("\n" + " " * sangria).join(lineas)
