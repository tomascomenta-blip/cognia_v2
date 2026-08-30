# -*- coding: utf-8 -*-
"""
cognia/cli_visibilidad.py
=========================
Que comandos VE el dueno por defecto, y cuales existen pero no se anuncian.

POR QUE EXISTE (2026-08-29)
---------------------------
`_CMD_DESCRIPTIONS` de `cognia/cli.py` tiene 278 entradas (280 cuando
aterricen `/avanzado` y `/sesion-a-workflow`). Un catalogo de 280 comandos
no es una funcion: es un muro. El autocompletado escupe
decenas de candidatos por letra, `/ayuda` es ilegible y `/comandos` no
distingue lo que se usa a diario de lo que se escribio para un experimento
de una tarde.

Este modulo parte el catalogo en tres cubos (NUCLEO / AVANZADO /
LABORATORIO) y expone el filtro que los consumidores aplican. Nada mas.

LA DECISION IMPORTANTE: OCULTAR NO ES DESACTIVAR
------------------------------------------------
El filtro se aplica en los CONSUMIDORES (autocompletado, `/ayuda` portada,
`/comandos`, catalogo del enrutador, `/api/comandos` del remoto) y JAMAS en
el despachador `if/elif` de cli.py. Un comando de LABORATORIO tecleado a
mano en modo sencillo sigue funcionando exactamente igual.

Motivo duro: si el filtro entrara en el despachador, un comando que hoy
funciona respondera "Comando desconocido" en el modo por defecto, y eso es
indistinguible de una errata. Precedente de la casa: `_filtro_tools_agente`
(cli.py:22190) oculta tools del anuncio sin quitarlas de `run_tool`.

Tampoco se filtra en `mensaje_desconocido` (para que `/gaf` siga sugiriendo
`/grafo`), ni en `/ayuda todo`, ni en `scripts/e2e_goal_hibrido.py`.

EJE PROPIO, NO ALIAS DE /modo
-----------------------------
Clave nueva `COGNIA_CMD_NIVEL` con valores "nucleo" (default) | "todo".
NO es un alias de `/modo avanzado` porque `/pensar` sin argumento
(cli.py:19314-19336) reescribe `COGNIA_UI_MODE` como efecto lateral: si
`/avanzado` fuese un alias, pedir "ver el razonamiento" revelaria 198
comandos que nadie pidio.

La implicacion va en UNA sola direccion: `/modo avanzado` implica nivel
"todo"; `/modo sencillo` NO fuerza "nucleo" (no deshace un `/avanzado on`
explicito del dueno).

CRITICO DE RENDIMIENTO
----------------------
`_CogniaCompleter.get_completions` (cli.py:3858) corre con CADA pulsacion y
con `complete_in_thread=True`. `get_nivel_cmds()` no puede tocar disco por
tecla: de ahi el cache global `_CACHE`, y de ahi que `/avanzado` y `/modo`
tengan que llamar a `invalidar_cache()` (y a
`enrutador.invalidar_catalogo()`) cuando cambian el nivel.

Y la clave TIENE que darse de alta en `cognia/user_prefs.py` (`K_CMD_NIVEL`
en la tupla de `load_prefs()`): sin eso, `/avanzado` funciona en la sesion y
se olvida al reiniciar SIN NINGUN ERROR, que es exactamente el bug vivo de
`COGNIA_UI_MODE`.

CONTRATO (copiado del plan, FASE 0 y PEDIDO 1)
----------------------------------------------
Firmas publicas:

    NUCLEO: frozenset
    AVANZADO: frozenset
    LABORATORIO: frozenset
    nivel(cmd) -> str
    visibles(cmd_descriptions: dict, *, avanzado: bool) -> dict
    contar_ocultos(cmd_descriptions: dict) -> int
    get_nivel_cmds(override=None) -> str
    set_nivel_cmds(v: str) -> str
    es_avanzado(override=None) -> bool
    invalidar_cache() -> None

Invariantes que los tests fijan:

  - `set(_CMD_DESCRIPTIONS) == (NUCLEO | AVANZADO | LABORATORIO) - PENDIENTES`
    y los tres cubos son disjuntos dos a dos (guardian contra la
    desincronizacion). `PENDIENTES` son las claves ya clasificadas aqui que
    todavia no existen en el fuente porque las registra F-CABLE.
  - `len(NUCLEO) <= 85`; "/avanzado" pertenece a NUCLEO.
  - `visibles(d, avanzado=True)` devuelve `d` tal cual; con `avanzado=False`
    devuelve solo las claves de NUCLEO.
  - 500 llamadas a `get_nivel_cmds()` tocan disco como mucho UNA vez.
  - `/sesion-a-workflow` y `/session-to-workflow` van a AVANZADO;
    `/flujoteca` y `/biblioteca` van a NUCLEO.

Esqueleto de la FASE 0: firmas y contrato. La implementacion es del agente A.
"""
from __future__ import annotations

import os
from typing import Optional

__all__ = [
    "NUCLEO", "AVANZADO", "LABORATORIO", "PENDIENTES",
    "K_CMD_NIVEL", "NIVELES",
    "nivel", "visibles", "contar_ocultos", "get_nivel_cmds",
    "set_nivel_cmds", "es_avanzado", "invalidar_cache",
]

# ---------------------------------------------------------------------------
# LOS TRES CUBOS
# ---------------------------------------------------------------------------
# Reparto por COMANDO, no por categoria: los cajones de harness/ayuda.py son
# mixtos (el de "Memoria y notas" tiene /notas, que es de diario, junto a
# /contexto-semantico, que es un experimento). Un corte por categoria dejaria
# fuera comandos de uso diario o dentro subsistemas enteros de laboratorio.
#
# La union de los tres es EXACTAMENTE el catalogo de cli.py mas PENDIENTES, y
# `tests/test_cli_visibilidad.py::test_los_tres_cubos_particionan_el_catalogo`
# lo comprueba contra el fuente leido con ast: si alguien registra un comando
# nuevo y no lo clasifica aqui, ese test se pone rojo el mismo dia.

#: Lo que un consumidor final usa a diario: chat, archivos, agente, memoria,
#: sesiones, modelos, configuracion visual, ayuda. Visible SIEMPRE.
NUCLEO: frozenset = frozenset({
    "/avanzado", "/ayuda", "/biblioteca", "/bots", "/buscar", "/buscar-historial", "/cancelar",
    "/capacidades", "/cat", "/cognia-aprende", "/cognia-info", "/cognia-olvida", "/cognia-sabe",
    "/color", "/comandos", "/compactar", "/confianza", "/config", "/construir",
    "/contexto-vivo", "/costo", "/crear", "/deshacer", "/deshacer-borrado", "/diff", "/doctor",
    "/editar", "/ejecutar", "/escribir", "/esfuerzo", "/estado", "/estilo", "/exportar",
    "/flota", "/flujoteca", "/hacer", "/historial", "/imagenes", "/largo", "/leer", "/limpiar",
    "/limpiar-sesion", "/listar", "/mejorar", "/memoria", "/memorias", "/modelo", "/modelos",
    "/modo", "/modo-permiso", "/nota-agregar", "/notas", "/notas-buscar", "/notificar",
    "/pensar", "/permisos", "/plan-modo", "/proyecto", "/recordar", "/recordar-cancelar",
    "/recordatorios", "/remoto", "/resume", "/resumen-sesion", "/resumir", "/rutinas", "/salir",
    "/sesiones", "/skill", "/skills", "/tarea-borrar", "/tarea-crear", "/tarea-lista",
    "/tarea-ok", "/tareas", "/tema", "/tutor", "/update", "/ver", "/web-buscar", "/web-fetch",
    "/yo",
})

#: Util de verdad, pero de nicho: perfiles de maquina, planes y metas, grafo,
#: aprendizaje, arnes de consola, cifrado, reportes. Lo revela `/avanzado`.
AVANZADO: frozenset = frozenset({
    "/activar", "/agente estado", "/analiticas", "/aprende-repo", "/aprender", "/aprendiendo",
    "/aprendiendo-buscar", "/autoprueba", "/backup", "/bloquear", "/buscar-memoria",
    "/buscar-web", "/centinela", "/conceptos", "/config-resuelta", "/contexto",
    "/contexto-mapa", "/cpu", "/debug", "/decirle", "/deliberar", "/desbloquear", "/encuestas",
    "/enlaces", "/enrutador", "/expandir", "/exportar-todo", "/features", "/feedback",
    "/flujo", "/gpu",
    "/grafo", "/grafo-html", "/historial-limpiar", "/indexar-codigo", "/investigar", "/lazo",
    "/mapa-codigo", "/markdown", "/mcp", "/memoria-limite", "/memoria-stats", "/meta",
    "/meta-borrar", "/meta-ok", "/meta-prog", "/metas", "/mi-uso", "/modo rapido", "/modulos",
    "/monitor", "/monitores", "/nota-fijar", "/notif", "/notif-leer", "/notif-limpiar",
    "/notif-todas", "/offload", "/oficina", "/pegado", "/plan", "/plan-borrar", "/plan-ok",
    "/plan-ver", "/powershell", "/prompt", "/proyectos", "/pulir", "/quiz", "/razonar",
    "/recap", "/repasar", "/reporte", "/reporte-completo", "/revisar", "/rlm", "/seguridad",
    "/sesion-a-workflow", "/sesion-ver", "/session-to-workflow", "/shell-kill", "/shells",
    "/skill-cargar", "/skill-nuevo", "/spinner", "/stats", "/usuario", "/usuarios",
    "/ver-contexto", "/vram", "/workflow", "/worktree", "/yo-actualizar",
})

#: Experimentos, instrumentacion de investigacion del dueno, alias redundantes
#: y subsistemas sin producto todavia. Ocultos por defecto; `/avanzado` los
#: revela. Ocultos NO es desactivados: siguen despachando si se teclean.
LABORATORIO: frozenset = frozenset({
    "/abstraer", "/analogia", "/arbitro", "/argumento", "/atencion", "/autopsia", "/bucle",
    "/buscar-kg", "/cadena-causal", "/calidad-respuestas", "/camino-avanzar", "/camino-nuevo",
    "/caminos", "/chimera", "/conflictos-kg", "/conocimiento-ver", "/contexto-auto",
    "/contexto-semantico", "/contexto-stats", "/contradicciones", "/corregir", "/cristalizar",
    "/debate", "/digest", "/distill", "/distill run", "/diversidad", "/dormir", "/encolar",
    "/escalar", "/estilo_info", "/etiquetar", "/evaluar-idea", "/experimento", "/explicar",
    "/explorar", "/exportar-stats", "/fatiga", "/feedback-sesion", "/grabar", "/hecho",
    "/hechos-solidos", "/hermes", "/hibrido", "/hipotesis", "/horizonte", "/ideas",
    "/indice_add", "/indice_personal", "/inferir", "/inicio-dia", "/kg-agregar", "/kg-camino",
    "/kg-exportar", "/kg-inferir", "/kg-predicados", "/kg-relacionar", "/kg-responder",
    "/kg-stats", "/libro", "/logros", "/mapa", "/mesh_estado", "/mesh_iniciar", "/mesh_peer",
    "/mesh_publicar", "/meta-prioridad", "/meta-prioridad-ver", "/metas-alta", "/metas-ordenar",
    "/metas-pendientes", "/mi-cognia", "/mi-uso-detalle", "/multiverso", "/narrativa",
    "/notas-stats", "/objetivos", "/observar", "/olvido", "/patrones", "/perfil-completo",
    "/predecir", "/proximos-pasos", "/quiz-stats", "/receta", "/recomendar",
    "/reflexion-profunda", "/reporte-json", "/reporte-semanal", "/resolver-conflicto",
    "/sesion-stats", "/sintetizar", "/sugerir", "/temas", "/template", "/template-guia",
    "/templates", "/transferir", "/tx", "/velocidad", "/ver-criticas", "/verificar-kg",
    "/vigilar", "/vocabulario", "/vocabulario-guardar", "/y-si",
})

#: Claves ya clasificadas aqui que TODAVIA no existen en `_CMD_DESCRIPTIONS`
#: porque las registra la fase de cableado (F-CABLE) sobre `cognia/cli.py`.
#: El test de particion las descuenta, asi que este modulo puede aterrizar
#: antes que el cableado sin dejar la suite roja, y sigue siendo un guardian:
#: cualquier OTRA clave descolgada rompe el test.
PENDIENTES: frozenset = frozenset({"/avanzado", "/sesion-a-workflow"})

# ---------------------------------------------------------------------------
# NIVEL PERSISTIDO
# ---------------------------------------------------------------------------

#: Eje PROPIO, separado de COGNIA_UI_MODE. "nucleo" (default) | "todo".
K_CMD_NIVEL = "COGNIA_CMD_NIVEL"
NIVELES = ("nucleo", "todo")

_TODO = "todo"
_NUCLEO = "nucleo"

# `get_completions` corre en CADA TECLA (cli.py:3858, complete_in_thread=True):
# ni el nivel ni el modo de UI pueden costar una lectura de disco por
# pulsacion. De ahi este cache, y de ahi que `/avanzado` y `/modo` tengan que
# llamar a `invalidar_cache()`.
_CACHE = {"nivel": None, "ui_simple": None}

#: Sinonimos que se leen como "todo". Un valor sin sentido cae a "nucleo": el
#: default es siempre el catalogo corto (fallar hacia lo simple, no hacia el
#: muro de 280 comandos).
_SINONIMOS_TODO = frozenset({
    "todo", "todos", "all", "avanzado", "advanced", "on", "1", "true", "si", "yes", "full",
})


def _normalizar(valor) -> str:
    """Cualquier cosa -> "todo" | "nucleo". Nunca lanza."""
    s = ("" if valor is None else str(valor)).strip().lower()
    if not s:
        return _NUCLEO
    if s in _SINONIMOS_TODO or s.startswith("tod") or s.startswith("avan"):
        return _TODO
    return _NUCLEO


def _leer_nivel_persistido() -> str:
    """UNA lectura de disco: las preferencias de ~/.cognia/config.env y, si ahi
    no esta la clave, el respaldo por `os.environ` (que `first_run.apply_config`
    rellena al arrancar). Cualquier fallo cae al default "nucleo"."""
    val = None
    try:
        from cognia.user_prefs import load_prefs
        val = load_prefs().get(K_CMD_NIVEL)
    except Exception:
        val = None
    if not val:
        val = os.environ.get(K_CMD_NIVEL)
    return _normalizar(val)


def _ui_simple() -> bool:
    """`simple_mode.is_simple()` cacheado. Sin el cache, cada pulsacion de
    tecla acabaria en `load_prefs()` -> `first_run._load_config()` -> disco."""
    if _CACHE["ui_simple"] is None:
        try:
            from cognia.simple_mode import is_simple
            _CACHE["ui_simple"] = bool(is_simple())
        except Exception:
            _CACHE["ui_simple"] = True
    return bool(_CACHE["ui_simple"])


def get_nivel_cmds(override: Optional[str] = None) -> str:
    """Nivel efectivo del catalogo: "nucleo" (default) | "todo".

    `override` no None manda y no toca ni el cache ni el disco (es la puerta
    de los tests). En caliente responde del cache; solo con el cache vacio
    consulta `user_prefs.load_prefs()` y, de respaldo, `os.environ`.
    """
    if override is not None:
        return _normalizar(override)
    if _CACHE["nivel"] is None:
        _CACHE["nivel"] = _leer_nivel_persistido()
    return _CACHE["nivel"]


def set_nivel_cmds(v: str) -> str:
    """Fija el nivel, lo persiste y devuelve el valor normalizado.

    Persiste por `user_prefs.save_pref` para que sobreviva al reinicio, y deja
    ademas `os.environ[K_CMD_NIVEL]` puesto por si la persistencia falla (la
    sesion viva no se queda sin efecto). Invalida el cache: el cambio tiene
    que verse en la siguiente pulsacion, no en el proximo arranque.
    """
    valor = _normalizar(v)
    try:
        from cognia.user_prefs import save_pref
        save_pref(K_CMD_NIVEL, valor)
    except Exception:
        pass
    os.environ[K_CMD_NIVEL] = valor
    invalidar_cache()
    _CACHE["nivel"] = valor   # ya lo sabemos: no hace falta releer el disco
    return valor


def es_avanzado(override: Optional[str] = None) -> bool:
    """True si hay que anunciar el catalogo COMPLETO.

    Dos entradas, y la implicacion va en UNA sola direccion: el nivel "todo"
    lo enciende, y `/modo avanzado` tambien (quien pide ver el detalle del
    proceso quiere ver las herramientas). `/modo sencillo` NO apaga un
    `/avanzado on` explicito: deshacer una eleccion del dueno por un efecto
    lateral es justo el bug que este eje separado evita.
    """
    if get_nivel_cmds(override) == _TODO:
        return True
    return not _ui_simple()


def invalidar_cache() -> None:
    """Olvida el nivel y el modo de UI cacheados.

    La llaman los handlers de `/avanzado` y `/modo`. Sin esto, el cambio en
    caliente no se ve hasta reiniciar (y el enrutador necesita ademas su
    `invalidar_catalogo()`: son dos caches distintos).
    """
    _CACHE["nivel"] = None
    _CACHE["ui_simple"] = None


# ---------------------------------------------------------------------------
# EL FILTRO
# ---------------------------------------------------------------------------

def nivel(cmd) -> str:
    """A que cubo pertenece `cmd`: "nucleo" | "avanzado" | "laboratorio".

    Un comando que no este en ningun cubo se trata como laboratorio (lo mas
    oculto), nunca como error: el catalogo puede crecer entre releases y una
    excepcion aqui reventaria el autocompletado.
    """
    s = ("" if cmd is None else str(cmd)).strip()
    if s in NUCLEO:
        return "nucleo"
    if s in AVANZADO:
        return "avanzado"
    if s in LABORATORIO:
        return "laboratorio"
    # "/plan ver algo" -> se decide por "/plan". Las claves CON subcomando ya
    # estan en los cubos ("/agente estado", "/modo rapido", "/distill run") y
    # las caza el match exacto de arriba, que gana a este.
    base = s.split(" ", 1)[0]
    if base != s:
        if base in NUCLEO:
            return "nucleo"
        if base in AVANZADO:
            return "avanzado"
    return "laboratorio"


def visibles(cmd_descriptions: dict, *, avanzado: bool) -> dict:
    """El sub-catalogo que se ANUNCIA, conservando el orden del original.

    Con `avanzado=True` devuelve `cmd_descriptions` TAL CUAL (el mismo objeto:
    los consumidores solo lo leen, y asi el caso comun no copia 280 entradas
    por pulsacion). Con `avanzado=False`, solo las claves de NUCLEO.

    Ojo: esto filtra lo que se MUESTRA. El despachador de cli.py sigue viendo
    el catalogo entero -- ocultar no es desactivar.
    """
    if avanzado:
        return cmd_descriptions
    try:
        pares = cmd_descriptions.items()
    except AttributeError:
        return {}
    return {k: v for k, v in pares if k in NUCLEO}


def contar_ocultos(cmd_descriptions: dict, avanzado: Optional[bool] = None) -> int:
    """Cuantos comandos quedan fuera del anuncio en el nivel actual.

    Lo usa el pie de `/comandos`: "N comandos ocultos - /avanzado los revela".
    `avanzado` explicito evita recalcular el nivel cuando el llamador ya lo
    tiene; con None se consulta `es_avanzado()`.
    """
    if avanzado is None:
        avanzado = es_avanzado()
    if avanzado:
        return 0
    try:
        total = len(cmd_descriptions)
    except TypeError:
        return 0
    return max(0, total - len(visibles(cmd_descriptions, avanzado=False)))
