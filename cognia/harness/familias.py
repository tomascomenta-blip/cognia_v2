# -*- coding: utf-8 -*-
"""
cognia/harness/familias.py — las capacidades del agente, visibles y encendibles.

EL PROBLEMA QUE RESUELVE (2026-08-18). Cognia tiene ~111 herramientas
registrables, pero por defecto sólo se anuncian 13. Las otras viven detrás de
nueve variables de entorno que NINGÚN comando enciende: hay que saber que
existen, saber cómo se llama su flag, y exportarlo ANTES de arrancar. Entre lo
que queda inalcanzable hay subsistemas enteros verificados en GPU — imágenes,
música, 3D, navegador, pantalla, escena LCD (37 tools).

El recorte en sí es correcto y está MEDIDO: el A/B del repo (2026-07-25) vio
que un catálogo de 46 tools baja el camino feliz de 4,25/5 a 2,5/5, y por eso
CORE_TOOLS son 13. Lo que estaba mal no es el recorte, es que no hubiera
manera de deshacerlo desde dentro. Aquí está la superficie: qué familias hay,
cuáles están encendidas, qué enciende cada una, y `activar()` para hacerlo en
caliente sin reiniciar.

Es el modo de fallo que el propio repo tiene nombrado — "capacidad construida
y desconectada" — atacado en su raíz.
"""
from __future__ import annotations

import importlib
import importlib.util
import os

_ENCENDIDO = ("1", "on", "true", "yes")


def _activo(flag: str) -> bool:
    return os.environ.get(flag, "").strip().lower() in _ENCENDIDO


def _carga_modulo(ruta: str):
    """Importa el módulo y llama a su register(tool). Idempotente."""
    def _cargar():
        from cognia.agent.tools import tool
        mod = importlib.import_module(ruta)
        reg = getattr(mod, "register", None)
        if reg is None:
            return 0
        antes = _n_registradas()
        reg(tool)
        return _n_registradas() - antes
    return _cargar


def _carga_lcd():
    """Las 37 de escena viven en tres cargadores distintos."""
    def _cargar():
        antes = _n_registradas()
        for ruta, fn in (("cognia.lcd.tools_lcd", "load_lcd_tools"),
                         ("cognia.lcd.tools_services", "load_service_tools"),
                         ("cognia.lcd.tools_modeling", "load_modeling_tools")):
            mod = importlib.import_module(ruta)
            getattr(mod, fn)()
        return _n_registradas() - antes
    return _cargar


def _ya_registradas():
    """Las del arnés ya están en el registro: su flag sólo gobierna el ANUNCIO."""
    def _cargar():
        importlib.import_module("cognia.harness.tools_harness")
        return 0
    return _cargar


def _n_registradas() -> int:
    from cognia.agent.tools import TOOLS
    return len(TOOLS)


# familia -> qué es, qué flag la enciende, cómo se carga, y cómo reconocer sus
# tools en el registro. `peligrosa` marca las que tocan la máquina del usuario
# fuera del workspace (la confirmación sigue siendo cosa del gate de cada tool).
FAMILIAS = {
    "pantalla": {
        "que": "ver la pantalla, mover el ratón, teclear y pulsar teclas",
        "flag": "COGNIA_SCREEN", "prefijo": "pantalla_",
        "cargar": _carga_modulo("cognia.agent.screen_tools"), "peligrosa": True,
    },
    "navegador": {
        "que": "abrir páginas, navegar y leer la web con Chromium",
        "flag": "COGNIA_BROWSER", "prefijo": "web_",
        "cargar": _carga_modulo("cognia.agent.browser_tool"), "peligrosa": True,
    },
    "imagen": {
        "que": "generar imágenes y verlas",
        "flag": "COGNIA_IMG_TOOLS", "prefijo": "imagen_",
        "cargar": _carga_modulo("cognia.agent.image_tools"), "peligrosa": False,
    },
    "musica": {
        "que": "componer y renderizar música",
        "flag": "COGNIA_MUSICA_TOOLS", "prefijo": "musica_",
        "cargar": _carga_modulo("cognia.agent.musica_tools"), "peligrosa": False,
    },
    "voz": {
        "que": "hablar y escuchar",
        "flag": "COGNIA_VOZ_TOOLS", "prefijo": "voz_",
        "cargar": _carga_modulo("cognia.agent.voz_tools"), "peligrosa": False,
    },
    "3d": {
        "que": "generar modelos 3D a partir de una imagen",
        "flag": "COGNIA_3D_TOOLS", "prefijo": "tresd_",
        "cargar": _carga_modulo("cognia.agent.tresd_tools"), "peligrosa": False,
    },
    "vlm": {
        "que": "mirar imágenes y juzgarlas con un modelo de visión",
        "flag": "COGNIA_VLM_TOOLS", "prefijo": "vlm_",
        "cargar": _carga_modulo("cognia.agent.vlm_tools"), "peligrosa": False,
    },
    "documento": {
        # El "Word para la IA": escribir y corregir los apuntes de una materia
        # por bloques (cognia/clases/documento.py). OPT-IN por lo de siempre
        # -- el techo del catálogo -- y además porque sólo tiene sentido con
        # un cuaderno abierto: sin materia, las siete tools no pueden ni
        # decidir dónde escriben.
        "que": "escribir y corregir el documento (los apuntes) de una materia",
        "flag": "COGNIA_DOC_TOOLS", "prefijo": "doc_",
        "cargar": _carga_modulo("cognia.agent.documento_tools"),
        "peligrosa": False,
    },
    "escena": {
        "que": "construir escenas 3D estructuradas (LCD)",
        "flag": "COGNIA_LCD", "prefijo": "escena_",
        "cargar": _carga_lcd(), "peligrosa": False,
    },
    "repo": {
        "que": "convertir un repositorio entero en un prompt",
        "flag": "COGNIA_REPO_REVERSE", "nombres": ("repo_a_prompt",),
        "cargar": _carga_modulo("cognia.agent.repo_reverse_tool"),
        "peligrosa": False,
    },
    "buscador-de-tools": {
        "que": "que el agente busque herramientas que no están en su lista",
        "flag": "COGNIA_TOOLSEARCH", "nombres": ("buscar_herramientas",),
        "cargar": _ya_registradas(), "peligrosa": False,
    },
    "workflows": {
        "que": "repartir el trabajo entre varias llamadas y juntar resultados",
        "flag": "COGNIA_WORKFLOW_TOOL", "nombres": ("workflow",),
        "cargar": _ya_registradas(), "peligrosa": False,
    },
    "offload": {
        "que": "descargar salidas grandes a disco y recuperarlas después",
        "flag": "COGNIA_OFFLOAD", "nombres": ("recuperar",),
        "cargar": _ya_registradas(), "peligrosa": False,
    },
    "oraculo": {
        "que": "preguntarle a un modelo más capaz de la flota",
        "flag": "COGNIA_ORACULO", "nombres": ("consultar_oraculo",),
        "cargar": _ya_registradas(), "peligrosa": False,
    },
    "deshacer": {
        "que": "deshacer la última edición de fichero",
        "flag": "COGNIA_UNDO_TOOL", "nombres": ("deshacer_edicion",),
        "cargar": _ya_registradas(), "peligrosa": False,
    },
}


def _tools_de(nombre: str) -> list:
    """Las tools de esa familia que están AHORA en el registro."""
    from cognia.agent.tools import TOOLS
    fam = FAMILIAS.get(nombre) or {}
    pref = fam.get("prefijo")
    exactos = set(fam.get("nombres") or ())
    return sorted(t for t in TOOLS
                  if (pref and t.startswith(pref)) or t in exactos)


def _instalable(nombre: str) -> bool:
    """¿Están las dependencias? Se mira con find_spec: NO ejecuta el paquete."""
    fam = FAMILIAS.get(nombre) or {}
    rutas = {
        "pantalla": "cognia.agent.screen_tools",
        "navegador": "cognia.agent.browser_tool",
        "imagen": "cognia.agent.image_tools",
        "musica": "cognia.agent.musica_tools",
        "voz": "cognia.agent.voz_tools",
        "3d": "cognia.agent.tresd_tools",
        "vlm": "cognia.agent.vlm_tools",
        "documento": "cognia.agent.documento_tools",
        "escena": "cognia.lcd.tools_lcd",
        "repo": "cognia.agent.repo_reverse_tool",
    }
    ruta = rutas.get(nombre)
    if ruta is None:
        return True                     # las del arnés viajan con el paquete
    try:
        return importlib.util.find_spec(ruta) is not None
    except Exception:
        return False


def estado() -> list:
    """Una fila por familia: nombre, qué hace, si está encendida y sus tools."""
    filas = []
    for nombre, fam in FAMILIAS.items():
        tools = _tools_de(nombre)
        filas.append({
            "familia": nombre,
            "que": fam["que"],
            "flag": fam["flag"],
            "encendida": _activo(fam["flag"]),
            "instalada": _instalable(nombre),
            "tools": tools,
            "n_tools": len(tools),
            "peligrosa": bool(fam.get("peligrosa")),
        })
    return filas


def activar(nombre: str) -> dict:
    """Enciende una familia EN CALIENTE. {'ok', 'familia', 'nuevas', 'detalle'}.

    Pone el flag y carga el módulo. No reinicia nada: las tools quedan en el
    registro vivo y el agente puede llamarlas en el paso siguiente.
    """
    nombre = (nombre or "").strip().lower()
    if nombre not in FAMILIAS:
        return {"ok": False, "familia": nombre,
                "detalle": f"no conozco la familia {nombre!r}. Hay: "
                           + ", ".join(sorted(FAMILIAS))}
    fam = FAMILIAS[nombre]
    antes = set(_tools_de(nombre))
    os.environ[fam["flag"]] = "1"
    try:
        fam["cargar"]()
    except Exception as exc:
        # Con el flag puesto y el import roto, callarse dejaría una capacidad
        # pedida y desconectada: exactamente el modo de fallo de la casa.
        return {"ok": False, "familia": nombre, "nuevas": [],
                "detalle": f"{fam['flag']}=1 puesto, pero el módulo no cargó: "
                           f"{type(exc).__name__}: {exc}"}
    ahora = set(_tools_de(nombre))
    nuevas = sorted(ahora - antes)
    return {"ok": True, "familia": nombre, "nuevas": nuevas,
            "total": len(ahora),
            "detalle": (f"{len(nuevas)} herramienta(s) nuevas disponibles"
                        if nuevas else
                        "ya estaban cargadas; el flag queda encendido")}


def desactivar(nombre: str) -> dict:
    """Apaga el flag. Las tools ya registradas siguen en memoria hasta reiniciar.

    Se dice CLARAMENTE, en vez de fingir una descarga que no ocurre: quitar del
    registro en caliente dejaría al modelo llamando a tools que desaparecen a
    mitad de tarea.
    """
    nombre = (nombre or "").strip().lower()
    if nombre not in FAMILIAS:
        return {"ok": False, "familia": nombre, "detalle": "no conozco esa familia"}
    os.environ[FAMILIAS[nombre]["flag"]] = "0"
    return {"ok": True, "familia": nombre,
            "detalle": "flag apagado; ya no se anuncian. Las que estén "
                       "cargadas se van del registro al reiniciar"}
