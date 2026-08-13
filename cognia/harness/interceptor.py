# -*- coding: utf-8 -*-
"""El punto ÚNICO donde el arnés se mete entre el modelo y sus herramientas.

POR QUÉ EXISTE (2026-08-12): las capacidades destiladas de los harnesses
punteros —checkpoints antes de escribir, hooks del usuario, verificación tras
editar, offloading de salidas gigantes, modo plan— tienen todas el mismo punto
de aplicación: justo antes y justo después de ejecutar una herramienta. Meter
cada una por su lado en `run_tool` habría dejado cinco bloques try/except
sueltos dentro de una función que ya es el cuello de botella de todo el agente.
Aquí viven juntas, se testean juntas y `run_tool` sólo gana dos llamadas.

CONTRATO — las dos funciones NUNCA lanzan y NUNCA bloquean por su cuenta:
    antes(name, args, ctx)  -> None para seguir, o un str que SUSTITUYE al
                               resultado de la herramienta (la llamada no llega
                               a ejecutarse). El str es lo que lee el modelo.
    despues(name, args, ctx, out, ok) -> el texto final para el modelo.

Un fallo de cualquier capa degrada a "no hacer nada" y deja pasar la llamada:
el agente tiene que seguir funcionando aunque el arnés se rompa entero.

QUÉ VA ENCENDIDO POR DEFECTO Y POR QUÉ
  - checkpoints .......... SÍ. Es barato (una copia del contenido previo) y es
                           la única red bajo un agente que escribe ficheros.
  - modo plan ............ SÍ, pero el modo por defecto es "ejecutar", así que
                           no hace nada hasta que el usuario entra en /plan.
  - hooks del usuario .... SÍ, pero sin `.cognia/hooks.json` es un no-op.
  - verificar sintaxis ... SÍ. Es un `compile()`, cuesta microsegundos y caza el
                           fichero roto en el turno en que se rompió.
  - correr tests ......... NO. `COGNIA_AUTO_TESTS=1` lo enciende. En este repo
                           la suite son 6909 tests / 12 min: dispararla sola tras
                           cada edición convertiría cada paso en una eternidad.
                           Aider también la trae opt-in (--auto-test).
  - offloading ........... NO. `COGNIA_OFFLOAD=1` lo enciende. `run_tool` ya
                           recorta con `aci_trim`, y el repo tiene MEDIDO que el
                           doble truncado hace que el modelo edite con
                           SEARCH/REPLACE texto que nunca vio (baseline
                           2026-08-09). Adoptarlo exige medirlo CONTRA aci_trim,
                           no encenderlo por fe.
"""

from __future__ import annotations

import os
from pathlib import Path

# Herramientas cuyo primer argumento es la ruta que van a modificar. El registry
# es la fuente de verdad de qué existe; esto sólo dice DÓNDE está la ruta.
_ESCRIBEN = {
    "escribir_archivo": "primero",
    "editar_archivo": "primero",
    "apendar_archivo": "primero",
    "borrar_archivo": "todo",
}

# Extensiones que sabemos verificar (el resto pasa sin veredicto de sintaxis).
_VERIFICABLES = (".py", ".pyi", ".json")


def _activo(env: str) -> bool:
    return os.environ.get(env, "").strip().lower() in ("1", "on", "true", "yes", "si")


def raiz_proyecto(ctx: dict | None = None) -> Path:
    """La raíz contra la que se resuelven hooks, permisos y tests.

    El workspace del agente cuando lo hay (es donde de verdad escribe), y el
    directorio actual si no. Nunca lanza.
    """
    try:
        ws = (ctx or {}).get("workspace") or (ctx or {}).get("raiz")
        if ws:
            return Path(str(ws))
    except Exception:
        pass
    try:
        from cognia.agents.workers.dev_tools import AGENT_WORKSPACE_ROOT
        if AGENT_WORKSPACE_ROOT:
            return Path(str(AGENT_WORKSPACE_ROOT))
    except Exception:
        pass
    return Path.cwd()


def ruta_destino(name: str, args: str) -> str:
    """La ruta que la herramienta `name` va a tocar, o '' si no toca ninguna.

    El protocolo de texto del repo pone la ruta primero y separa con ' | ' el
    resto (contenido, bloques SEARCH/REPLACE). En el régimen nativo el puente
    `armar_args` reconstruye ese mismo string, así que esto vale para los dos.
    """
    modo = _ESCRIBEN.get(name)
    if not modo or not args:
        return ""
    crudo = args if modo == "todo" else args.split("|", 1)[0]
    return crudo.strip().strip('"').strip("'")


def _leer_previo(ruta: Path) -> str | None:
    """El contenido actual del fichero, o None si no existe/no es texto."""
    try:
        if not ruta.is_file():
            return None
        return ruta.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def antes(name: str, args: str, ctx: dict) -> str | None:
    """Todo lo que pasa ANTES de ejecutar la herramienta.

    Devuelve None (seguir) o el texto que el modelo verá en lugar del resultado.
    El orden importa: el modo plan corta antes que los hooks para no pagar el
    coste de lanzar procesos por una llamada que igual no va a ocurrir.
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    ctx.pop("_harness_checkpoint", None)

    # 1) MODO PLAN — investigar sin tocar nada. El motivo es para el modelo.
    try:
        from cognia.harness import modo_plan
        if modo_plan.en_modo_plan():
            spec = _spec(name)
            permitido, motivo = modo_plan.puede_usar(
                name, danger=bool(spec.get("danger")), args=args)
            if not permitido:
                return motivo
    except Exception:
        pass

    # 2) HOOKS pre_tool del proyecto — pueden VETAR la llamada.
    try:
        from cognia.harness import hooks
        raiz = raiz_proyecto(ctx)
        # hooks_activos() es el kill-switch (COGNIA_HOOKS=0); el fichero es la
        # condición de que haya algo que correr. Hacen falta LAS DOS.
        if hooks.hooks_activos() and hooks.ruta_config(raiz).is_file():
            pre = hooks.correr_pre(name, args, raiz)
            if not pre.get("permitido", True):
                return pre.get("motivo") or f"BLOQUEADO por un hook pre_tool antes de '{name}'."
    except Exception:
        pass

    # 3) CHECKPOINT — el estado previo del fichero, antes de que se pierda.
    destino = ruta_destino(name, args)
    if destino:
        try:
            from cognia.harness import checkpoints
            ruta = Path(destino)
            if not ruta.is_absolute():
                ruta = raiz_proyecto(ctx) / ruta
            entrada = checkpoints.registrar(ruta, _leer_previo(ruta), motivo=name)
            ctx["_harness_checkpoint"] = entrada
        except Exception:
            pass
    return None


def despues(name: str, args: str, ctx: dict, out: str, ok: bool) -> str:
    """Todo lo que pasa DESPUÉS. Devuelve el texto final para el modelo."""
    ctx = ctx if isinstance(ctx, dict) else {}
    texto = out if isinstance(out, str) else str(out)

    # 1) VERIFICACIÓN de lo que se acaba de escribir (sintaxis siempre; tests
    #    sólo con COGNIA_AUTO_TESTS=1). Sólo si la herramienta dijo que fue bien:
    #    verificar un fichero que no se llegó a escribir sería ruido.
    destino = ruta_destino(name, args)
    if ok and destino and name != "borrar_archivo":
        veredicto = _verificar(destino, ctx)
        if veredicto:
            texto = f"{texto}\n{veredicto}"

    # 2) HOOKS post_tool — pueden anexar texto al resultado.
    try:
        from cognia.harness import hooks
        raiz = raiz_proyecto(ctx)
        if hooks.hooks_activos() and hooks.ruta_config(raiz).is_file():
            post = hooks.correr_post(name, args, texto, raiz)
            anexo = (post or {}).get("anexo") or ""
            if anexo.strip():
                texto = f"{texto}\n{anexo.strip()}"
    except Exception:
        pass

    # 3) OFFLOADING de salidas gigantes (opt-in: ver la cabecera del módulo).
    if _activo("COGNIA_OFFLOAD"):
        try:
            from cognia.harness import offloading
            if len(texto.encode("utf-8", "ignore")) > offloading.umbral_bytes():
                handle = offloading.guardar(texto, tool=name, args=args)
                texto = offloading.resumir_para_modelo(texto, tool=name, handle=handle)
        except Exception:
            pass
    return texto


def _spec(name: str) -> dict:
    """El spec del registry para `name`, o {} si no se puede consultar."""
    try:
        from cognia.agent.tools import TOOLS
        return TOOLS.get(name) or {}
    except Exception:
        return {}


def _verificar(destino: str, ctx: dict) -> str:
    """El bloque RESULTADO de la verificación, o '' si no aplica.

    Sólo mira ficheros que sabemos verificar y que existen tras la escritura;
    cualquier fallo de la capa devuelve '' (el agente no se entera).
    """
    try:
        if not destino.lower().endswith(_VERIFICABLES):
            return ""
        raiz = raiz_proyecto(ctx)
        ruta = Path(destino)
        if not ruta.is_absolute():
            ruta = raiz / ruta
        if not ruta.is_file():
            return ""
        contenido = ruta.read_text(encoding="utf-8", errors="replace")
        from cognia.harness import verificacion
        veredicto = verificacion.verificar_edicion(
            ruta, contenido, raiz=raiz, correr=_activo("COGNIA_AUTO_TESTS"))
        # Silencio cuando todo está bien y no se corrió nada: el agente no
        # necesita un "ok" por cada línea que escribe, sólo enterarse del roto.
        if veredicto.get("sintaxis_ok") and veredicto.get("tests_ok") is None:
            return ""
        return verificacion.texto_resultado(veredicto)
    except Exception:
        return ""
