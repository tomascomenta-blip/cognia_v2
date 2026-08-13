# -*- coding: utf-8 -*-
"""El puente entre el agente y su propio motor de workflows.

POR QUE EXISTE (2026-08-13): `cognia/agent/workflows.py` está completo desde el
2026-08-11 —corrida con journal, presupuesto de tokens, salida estructurada por
schema, resume desde una corrida previa, `paralelo` y `pipeline`— y **nadie lo
llamaba**: ni un comando del REPL ni una herramienta del agente. Una capacidad
que el modelo no puede invocar es una capacidad que no existe, igual que un
schema publicado como prosa. Este módulo la pone a su alcance.

QUE HACE Y QUE NO
El motor ejecuta `agente()`: prompt -> texto (o dict validado contra un schema),
**sin herramientas**. Sirve para repartir TRABAJO DE PENSAR entre varias
llamadas independientes —analizar cinco ficheros, redactar cuatro secciones,
evaluar tres enfoques— y juntar los resultados. NO sirve para tareas que tocan
disco: para eso el agente ya tiene `delegar_subtarea`, que sí lleva herramientas.
Esa frontera está escrita en la descripción de la tool porque es la forma de que
el modelo no la use mal.

TOPES (un agente que se lanza workflows a sí mismo puede irse de las manos)
  - MAX_PASOS = 6 por workflow. Más pasos no es más capacidad: es más espera.
  - PROFUNDIDAD 1: dentro de un workflow la herramienta se rechaza con un motivo
    legible. Sin esto, un paso podría lanzar otro workflow y multiplicarse.
  - Presupuesto de tokens explícito, que el motor ya hace cumplir: agotado
    devuelve `{"_error": ...}` en vez de seguir gastando.
  - `paralelo` con cap=2, que es la física medida de esta máquina (un slot de
    GPU serializa; más hilos solo solapan I/O).
"""

from __future__ import annotations

import os
import re
import threading

MAX_PASOS = 6
PRESUPUESTO_DEFECTO = 60_000
MAX_TOKENS_PASO = 2048

# Marca de "ya estamos dentro de un workflow", por hilo: `paralelo` corre los
# pasos en un pool, así que una bandera global marcaría también al hilo padre
# que espera, y una de proceso no distinguiría corridas concurrentes.
_dentro = threading.local()

_SEPARADORES = re.compile(r"\s*(?:;|\n|(?<=\S)\s\|\s(?=\S))\s*")

# Restos de OTRAS plantillas de tool-calling que el modelo cuela DENTRO del
# valor de un argumento. Medido contra Qwythos-9B el 2026-08-13: pidiendole tres
# resumenes devolvio
#   pasos="...investigar TLS</parameter>\n<parameter=modo>\nparalelo"
# o sea, sintaxis estilo XML incrustada en el JSON del tool call. Sin limpiarla,
# `partir_pasos` veia 5 subtareas —dos de ellas basura— y cada una se pagaba con
# una llamada al modelo. El server no puede filtrarlo (para el es texto), asi
# que le toca al adaptador.
_RESTOS_PLANTILLA = re.compile(
    r"</?(?:parameter|tool_call|function|invoke|arg)\b[^>]*>", re.IGNORECASE)
_CLAVE_INCRUSTADA = re.compile(
    r"<\s*parameter\s*=\s*(\w+)\s*>\s*([^<\n]*)", re.IGNORECASE)


def sanear(texto: str) -> tuple:
    """Limpia restos de plantilla y devuelve (texto_limpio, claves_incrustadas).

    `claves_incrustadas` recupera lo que el modelo queria pasar como otro
    argumento (tipicamente `modo`) y quedo atrapado dentro de este: tirarlo
    seria perder su intencion, y dejarlo seria ejecutarlo como subtarea.
    """
    crudo = str(texto or "")
    claves = {k.lower(): v.strip() for k, v in _CLAVE_INCRUSTADA.findall(crudo)}
    limpio = _RESTOS_PLANTILLA.sub("\n", crudo)
    for clave, valor in claves.items():
        # El valor ya se recupero como argumento: fuera del cuerpo de las tareas.
        if valor:
            limpio = limpio.replace(valor, "\n")
    return limpio, claves


def en_workflow() -> bool:
    """True si el hilo actual ya está ejecutando un paso de workflow."""
    return bool(getattr(_dentro, "activo", False))


def partir_pasos(texto: str) -> list:
    """El string del modelo -> lista de subtareas.

    Acepta lo que un modelo escribe de verdad: separadas por ';', por saltos de
    línea, o numeradas ('1. ...'). Se limpian viñetas y numeración porque el
    prompt del paso no debe empezar con '3.' (el modelo cree que le falta el
    contexto de los pasos 1 y 2).
    """
    if not texto:
        return []
    limpio, _ = sanear(texto)
    crudos = _SEPARADORES.split(limpio)
    pasos = []
    for c in crudos:
        limpio = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", (c or "").strip())
        if limpio:
            pasos.append(limpio)
    return pasos


def _consolidar(pasos: list, resultados: list) -> str:
    """El texto que vuelve al modelo: un bloque por paso, con su fallo si lo hubo."""
    lineas = []
    fallos = 0
    for i, (paso, res) in enumerate(zip(pasos, resultados), 1):
        cabecera = f"--- paso {i}: {paso[:90]}"
        if res is None:
            fallos += 1
            lineas.append(f"{cabecera}\n(sin resultado: el paso no termino a tiempo)")
            continue
        if isinstance(res, dict) and res.get("_error"):
            fallos += 1
            lineas.append(f"{cabecera}\nERROR: {res['_error']}")
            continue
        lineas.append(f"{cabecera}\n{res if isinstance(res, str) else res}")
    cierre = (f"\n({len(pasos) - fallos} de {len(pasos)} pasos con resultado)"
              if fallos else f"\n({len(pasos)} pasos completados)")
    return "\n\n".join(lineas) + cierre


def ejecutar(pasos, modo: str = "paralelo", nombre: str = "agente",
             presupuesto: int = PRESUPUESTO_DEFECTO,
             system: str = "", print_fn=None) -> dict:
    """Corre las subtareas en el motor de workflows. NUNCA lanza.

    Devuelve {"ok", "texto", "run_id", "pasos", "tokens", "error"}. El `texto`
    es lo que se le devuelve al modelo; `run_id` permite reanudar la corrida más
    tarde con `corrida(resume_de=run_id)`, que es la razón de devolverlo.
    """
    if isinstance(pasos, str):
        pasos = partir_pasos(pasos)
    pasos = [p for p in (pasos or []) if str(p).strip()][:MAX_PASOS]
    if not pasos:
        return {"ok": False, "texto": "", "run_id": "", "pasos": 0, "tokens": 0,
                "error": "no hay subtareas: describe al menos una"}
    if en_workflow():
        return {"ok": False, "texto": "", "run_id": "", "pasos": 0, "tokens": 0,
                "error": ("ya estas DENTRO de un workflow: un paso no puede "
                          "lanzar otro workflow. Resuelve este paso y devuelve "
                          "su resultado.")}

    try:
        from cognia.agent.workflows import agente, corrida, paralelo
    except Exception as exc:  # pragma: no cover - el motor va en el paquete
        return {"ok": False, "texto": "", "run_id": "", "pasos": 0, "tokens": 0,
                "error": f"motor de workflows no disponible: {exc}"}

    c = corrida(nombre, presupuesto_tokens=presupuesto,
                print_fn=print_fn or (lambda *_a, **_k: None))

    def _thunk(prompt: str):
        def _correr():
            _dentro.activo = True
            try:
                return agente(c, prompt, system=system, max_tokens=MAX_TOKENS_PASO)
            finally:
                _dentro.activo = False
        return _correr

    try:
        if (modo or "").strip().lower().startswith("sec"):
            resultados = []
            for p in pasos:
                resultados.append(_thunk(p)())
        else:
            resultados = paralelo([_thunk(p) for p in pasos])
    except Exception as exc:
        return {"ok": False, "texto": "", "run_id": c.run_id, "pasos": len(pasos),
                "tokens": _gastado(c), "error": f"el workflow fallo: {exc}"}
    finally:
        _cerrar(c)

    utiles = sum(1 for r in resultados
                 if r is not None and not (isinstance(r, dict) and r.get("_error")))
    return {"ok": utiles > 0, "texto": _consolidar(pasos, resultados),
            "run_id": c.run_id, "pasos": len(pasos), "tokens": _gastado(c),
            "error": "" if utiles else "ningun paso devolvio resultado"}


def _gastado(c) -> int:
    """Tokens consumidos por la corrida, o 0 si el motor no los expone.

    `PresupuestoTokens.gastado` es un METODO (thread-safe, con lock), no un
    atributo: `int(getattr(...))` devolvia el metodo, lanzaba TypeError y el
    except lo enmascaraba como 0 — el workflow informaba "0 tokens" mientras el
    journal registraba 844. Se acepta tambien la forma atributo por si el
    contrato del motor cambia.
    """
    try:
        valor = getattr(c.presupuesto, "gastado", 0)
        return int(valor() if callable(valor) else valor or 0)
    except Exception:
        return 0


def _cerrar(c) -> None:
    """Cierra el journal de la corrida sin que un fallo aquí tape el resultado."""
    for nombre in ("cerrar", "close"):
        fn = getattr(c, nombre, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                pass
    try:
        if getattr(c, "_fh", None):
            c._fh.close()
    except Exception:
        pass


# Documentación para el registro nativo de la herramienta (cognia/harness/
# tools_harness.py la usa tal cual: una sola fuente de verdad para el prompt,
# el schema OpenAI y el despacho).
DESC_WORKFLOW = (
    "Resuelve DE UNA VEZ varias partes independientes de la misma tarea y te "
    "devuelve todos los resultados juntos. Usalo en cuanto el pedido tenga "
    "VARIAS piezas que no dependen entre si: 'resumi A, B y C', 'evalua estos "
    "tres enfoques', 'redacta estas secciones'. Es la opcion correcta ahi: "
    "hacerlas una por una gasta un paso por pieza, y delegar_subtarea lanza UN "
    "sub-agente para UNA subtarea, no varias en paralelo. "
    "Cada paso es una consulta al modelo SIN herramientas, asi que sirve para "
    "analizar, redactar, comparar y decidir; si la pieza necesita tocar "
    "ficheros o ejecutar algo, esa va por delegar_subtarea. "
    "Maximo 6 pasos, y un paso no puede lanzar otro workflow."
)

PARAMS_WORKFLOW = [
    {"nombre": "pasos", "tipo": "string", "requerido": True,
     "descripcion": ("las subtareas separadas por ';' — cada una autocontenida, "
                     "porque el paso no ve el resto de la conversacion")},
    {"nombre": "modo", "tipo": "string", "requerido": False, "clave": True,
     "descripcion": "'paralelo' (por defecto) o 'secuencial'"},
]
