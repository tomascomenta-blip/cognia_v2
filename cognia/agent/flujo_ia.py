# -*- coding: utf-8 -*-
"""
cognia/agent/flujo_ia.py
========================
Las dos operaciones de flujos que necesitan al MODELO: editarlos hablando y
sacar uno de una sesion de trabajo. Modulo PURO.

POR QUE ESTAN JUNTAS
--------------------
Las dos hacen lo mismo por debajo: pedirle al modelo un DAG en el formato de
`agent/flows.py`, y despues NO fiarse de lo que devuelva. Comparten el
saneado, la validacion contra el registro de tools y la degradacion, que es
donde esta el 80% del codigo util. Separarlas duplicaria justo esa parte.

LA REGLA QUE GOBIERNA EL FICHERO
--------------------------------
El modelo propone; `flows.validar()` dispone. Un DAG con un ciclo, con un
wire colgado o con una tool que no existe NO se guarda: se devuelve el error
concreto y el flujo anterior queda intacto. Un editor conversacional que
puede dejar el flujo roto es peor que no tener editor, porque el dueno
descubre el destrozo al ejecutarlo, no al pedirlo.

Y en editar(): se parte SIEMPRE del flujo actual y se le pide al modelo el
flujo COMPLETO resultante, no un parche. Los parches ("anade un nodo aqui")
obligan a interpretar posiciones y el modelo se equivoca; el DAG entero se
valida de una pieza y, si esta mal, no se aplica nada.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

__all__ = ["Resultado", "editar", "de_sesion", "sanear_flujo"]

TEMPERATURA = 0.2          # estructura, no creatividad
N_PREDICT = 1400           # un DAG de 8 nodos en JSON ronda los 700 tokens
TIMEOUT_DEFECTO = 90.0     # generar un DAG entero es mas caro que reformular


@dataclass
class Resultado:
    ok: bool = False
    flujo: dict = field(default_factory=dict)
    motivo: str = ""
    resumen: str = ""
    ms: int = 0
    modelo: str = ""
    bruto: str = ""

    def a_dict(self) -> dict:
        return {"ok": self.ok, "flujo": dict(self.flujo), "motivo": self.motivo,
                "resumen": self.resumen, "ms": self.ms, "modelo": self.modelo}


_FORMATO = """FORMATO DE SALIDA (solo el JSON, nada antes ni despues):
{"nombre": "...",
 "resumen": "una linea diciendo que cambiaste y por que",
 "nodos": [
   {"id": "hallar", "tool": "buscar", "args": "tendencias IA 2026",
    "wires": ["guardar"]},
   {"id": "guardar", "tool": "escribir_archivo", "args": "informe.md\\n{{hallar}}",
    "wires": []}
 ]}

NOTA SOBRE EL EJEMPLO: las dos tools de arriba ("buscar", "escribir_archivo")
son tools REALES del registro de Cognia. No es un detalle de estilo: el modelo
COPIA los nombres del ejemplo, asi que un ejemplo con una tool inventada hace
que TODOS los flujos generados se rechacen por "tool no existe". El ejemplo
decia "buscar_web" (que no existe) y por eso ni sesion-a-flujo ni la edicion
conversacional funcionaban contra el modelo real, mientras los tests con
generar_fn inyectado pasaban todos. Lo cazo el e2e del 2026-08-28 y lo vigila
tests/test_flujo_ia.py::test_el_ejemplo_del_prompt_usa_tools_reales.

REGLAS DEL FORMATO (son duras: si no se cumplen, el flujo se rechaza entero)
- "id": corto, en minusculas, sin espacios, UNICO dentro del flujo.
- "tool": tiene que ser una de las tools de la lista que te doy. Nada mas.
- "wires": ids de los nodos que van DESPUES. [] si es el ultimo.
- El grafo tiene que ser ACICLICO: si A lleva a B, B no puede volver a A.
- Para usar la salida de un nodo dentro de los args de otro: {{id_del_nodo}}.
- Campos opcionales por nodo: "saltar_si" (expresion), "reintentos" (entero),
  "timeout_s" (numero), "modelo" (nombre del modelo para ese paso).
"""

_SYSTEM_EDITAR = """Eres el editor de flujos de trabajo de Cognia.

Recibes un flujo existente y una instruccion del usuario en lenguaje natural.
Devuelves el flujo COMPLETO ya modificado.

""" + _FORMATO + """
REGLAS DE EDICION
1. Devuelve el flujo ENTERO, no solo lo que cambia.
2. Cambia SOLO lo que la instruccion pide. Los nodos que no se mencionan
   tienen que salir identicos, con el mismo id.
3. Si la instruccion no se puede cumplir (pide una tool que no existe, o
   crearia un ciclo), devuelve el flujo SIN TOCAR y explica por que en
   "resumen".
4. Conserva el "nombre" del flujo salvo que te pidan renombrarlo.
"""

_SYSTEM_SESION = """Eres el analista que convierte una sesion de trabajo en un
flujo reutilizable.

Recibes lo que paso en una sesion: lo que el usuario pidio, las herramientas
que se usaron y en que orden, y lo que se produjo. Devuelves un flujo que
REPRODUCE ese trabajo, generalizado para poder volver a correrlo.

""" + _FORMATO + """
REGLAS DE ANALISIS (esto no es transcribir, es inferir la ESTRUCTURA)
1. No copies los mensajes. Extrae los PASOS: que se hizo, con que tool, en
   que orden y que dependia de que.
2. Junta en un solo nodo los reintentos y las correcciones del mismo paso.
   Si algo se hizo tres veces porque fallo dos, es UN nodo, no tres.
3. Descarta lo que no forma parte del trabajo: saludos, preguntas de
   aclaracion, comandos del CLI, exploracion que no llevo a nada.
4. Los datos concretos de ESA sesion (una ruta, un nombre de fichero, un
   tema de busqueda) van en los args tal cual: el flujo tiene que correr.
5. Dos pasos que no dependen uno del otro NO se encadenan: los dos cuelgan
   del mismo padre, para que puedan correr en paralelo.
6. Si la sesion no contiene ningun trabajo reproducible, devuelve
   {"nombre": "", "resumen": "por que no hay flujo", "nodos": []}.
"""


def _extraer_json(bruto: str) -> dict:
    """El primer objeto JSON equilibrado del texto del modelo, o {}."""
    t = (bruto or "").strip()
    t = re.sub(r"<think>.*?</think>", " ", t, flags=re.S | re.I)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.M)
    inicio = t.find("{")
    if inicio < 0:
        return {}
    hondo = 0
    for i in range(inicio, len(t)):
        if t[i] == "{":
            hondo += 1
        elif t[i] == "}":
            hondo -= 1
            if hondo == 0:
                try:
                    return json.loads(t[inicio:i + 1])
                except Exception:
                    return {}
    return {}


def sanear_flujo(crudo, *, tool_existe=None, nombre_previo: str = "") -> tuple:
    """(flujo limpio, motivo_si_invalido).

    Limpia lo que se puede limpiar sin cambiar la intencion (tipos, campos
    sobrantes, wires duplicados) y RECHAZA lo que no (ciclos, wires colgados,
    tools inexistentes, nodos sin id o sin tool). La frontera importa:
    arreglar un ciclo por nuestra cuenta seria inventarle al usuario un flujo
    que no pidio, y tirar el nodo que no se entiende le devolveria un flujo
    mutilado con cara de bueno.
    """
    if not isinstance(crudo, dict):
        return {}, "el modelo no devolvio un objeto JSON"
    nodos_crudos = crudo.get("nodos")
    if not isinstance(nodos_crudos, list):
        return {}, "el JSON no trae una lista 'nodos'"
    if not nodos_crudos:
        return ({"nombre": crudo.get("nombre") or nombre_previo, "nodos": []},
                "el modelo devolvio un flujo vacio")

    limpios, vistos = [], set()
    for n in nodos_crudos:
        # Un nodo que no se puede sanear RECHAZA el flujo entero, no se
        # descarta. Descartarlo devolvia ok=True con un flujo al que le
        # faltaba en silencio justo el nodo que el usuario pidio anadir, y el
        # dueno lo descubria al ejecutarlo. El id duplicado ademas lo rechaza
        # flows.validar(): deduplicarlo aqui le escondia el error al unico
        # validador que manda.
        if not isinstance(n, dict):
            return {}, "hay elementos de 'nodos' que no son objetos JSON"
        nid = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(n.get("id") or "")).strip("_")
        if not nid:
            return {}, "hay nodos sin 'id'"
        if nid in vistos:
            return {}, f"ids de nodo duplicados: '{nid}'"
        tool = str(n.get("tool") or "").strip()
        if not tool:
            return {}, f"nodo '{nid}' sin 'tool'"
        vistos.add(nid)
        nodo = {"id": nid, "tool": tool,
                "args": str(n.get("args") or ""),
                "wires": []}
        wires = n.get("wires") or []
        if isinstance(wires, str):
            # El modelo escribe a veces "wires": "b" en vez de ["b"]. Es una
            # errata de forma, no de intencion: se arregla.
            wires = [wires]
        for w in wires:
            w = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(w)).strip("_")
            if w and w not in nodo["wires"]:
                nodo["wires"].append(w)
        for campo, tipo in (("reintentos", int), ("timeout_s", float),
                            ("saltar_si", str), ("modelo", str)):
            if n.get(campo) not in (None, ""):
                try:
                    nodo[campo] = tipo(n[campo])
                except Exception:
                    pass
        limpios.append(nodo)

    flujo = {"nombre": str(crudo.get("nombre") or nombre_previo or "flujo"),
             "nodos": limpios}

    # La validacion DURA la hace flows.validar(): es la misma que usa el
    # ejecutor, asi que lo que pase por aqui corre seguro. Duplicar sus
    # reglas aqui garantizaria que un dia digan cosas distintas.
    from cognia.agent import flows as _flows
    try:
        _flows.validar(flujo, tool_existe=tool_existe)
    except Exception as exc:
        return {}, str(exc)
    return flujo, ""


def _tools_disponibles(tool_existe=None, listar_tools=None) -> list:
    """Los nombres de tool que el modelo puede usar. Sin esta lista el modelo
    inventa tools plausibles ('descargar_pdf') y el flujo se rechaza entero."""
    if listar_tools is not None:
        try:
            return list(listar_tools() or [])
        except Exception:
            return []
    try:
        from cognia.agent import tools as _tools
        for nombre in ("nombres", "listar", "disponibles"):
            fn = getattr(_tools, nombre, None)
            if callable(fn):
                return list(fn() or [])
        registro = getattr(_tools, "TOOLS", None) or getattr(_tools, "_TOOLS", None)
        if isinstance(registro, dict):
            return sorted(registro)
    except Exception:
        pass
    return []


def _generar(prompt: str, system: str, *, url=None, timeout_s: float,
             generar_fn, registro: dict) -> str:
    if generar_fn is not None:
        return generar_fn(prompt, system)
    from cognia.harness import mejorar_prompt as _mp
    destino = _mp._detectar_url(url)
    if not destino:
        raise RuntimeError(_mp._motivo_backend(url) or "sin backend local")
    fn = _mp._construir_generar(destino, timeout_s, registro)
    # El presupuesto del reformulador (600 tokens) no da para un DAG entero.
    _viejo = _mp.N_PREDICT
    try:
        _mp.N_PREDICT = N_PREDICT
        return fn(prompt, system)
    finally:
        _mp.N_PREDICT = _viejo


def editar(flujo: dict, instruccion: str, *, generar_fn=None, url=None,
           timeout_s: float = TIMEOUT_DEFECTO, tool_existe=None,
           listar_tools=None) -> Resultado:
    """Aplica `instruccion` a `flujo` y devuelve el flujo nuevo. NUNCA lanza.

    Con ok=False, `flujo` vuelve EXACTAMENTE como entro: quien llama puede
    guardar el resultado sin comprobar nada y no rompe nada.
    """
    inicio = time.monotonic()
    registro = {"modelo": ""}
    original = dict(flujo or {})

    def _fallo(motivo: str, bruto: str = "") -> Resultado:
        return Resultado(ok=False, flujo=original, motivo=motivo, bruto=bruto,
                         ms=int((time.monotonic() - inicio) * 1000),
                         modelo=registro.get("modelo", ""))

    if not (instruccion or "").strip():
        return _fallo("no dijiste que cambiar")
    if not original.get("nodos"):
        return _fallo("el flujo esta vacio: no hay nada que editar")

    from cognia.agent import flujoteca as _ft
    tools = _tools_disponibles(tool_existe, listar_tools)
    partes = ["Flujo actual:", _ft.describir(original), "",
              "JSON actual:", json.dumps(original, ensure_ascii=False)]
    if tools:
        partes += ["", "Tools disponibles (usa SOLO estas):",
                   ", ".join(sorted(tools)[:120])]
    partes += ["", "Instruccion del usuario:", instruccion.strip()]

    try:
        bruto = _generar("\n".join(partes), _SYSTEM_EDITAR, url=url,
                         timeout_s=timeout_s, generar_fn=generar_fn,
                         registro=registro)
    except (TimeoutError, OSError) as exc:
        return _fallo(f"timeout o red: {type(exc).__name__}: {exc}")
    except Exception as exc:
        return _fallo(f"{type(exc).__name__}: {exc}")

    if str(registro.get("finish_reason") or "") == "length":
        return _fallo(f"el flujo no cupo en el presupuesto de tokens "
                      f"(max_tokens={N_PREDICT}): proba una instruccion mas "
                      f"acotada o un flujo mas chico")

    crudo = _extraer_json(bruto)
    if tool_existe is None and tools:
        tool_existe = (lambda t: t in set(tools))
    nuevo, motivo = sanear_flujo(crudo, tool_existe=tool_existe,
                                 nombre_previo=original.get("nombre", ""))
    if motivo:
        return _fallo(motivo, bruto=bruto[:400])
    if nuevo.get("nodos") == original.get("nodos"):
        # No es un error: el modelo puede haber decidido que la instruccion no
        # se podia cumplir. Se dice, y no se guarda una version identica.
        return Resultado(ok=False, flujo=original,
                         motivo="el flujo quedo igual",
                         resumen=str(crudo.get("resumen") or "")[:300],
                         ms=int((time.monotonic() - inicio) * 1000),
                         modelo=registro.get("modelo", ""))
    return Resultado(ok=True, flujo=nuevo, motivo="ok",
                     resumen=str(crudo.get("resumen") or "")[:300],
                     ms=int((time.monotonic() - inicio) * 1000),
                     modelo=registro.get("modelo", ""))


# ---------------------------------------------------------------------------
# De sesion a flujo
# ---------------------------------------------------------------------------

def resumir_sesion(historial, *, tope_turnos: int = 40,
                   tope_chars: int = 6000) -> str:
    """La sesion en texto, recortada, lista para el modelo.

    Recorta por el MEDIO y no por el final: el principio de una sesion trae
    el objetivo y el final trae el resultado; lo que sobra es la exploracion
    de en medio, que es justo lo que el prompt pide descartar."""
    turnos = [t for t in (historial or [])
              if isinstance(t, dict) and str(t.get("content") or "").strip()]
    if not turnos:
        return ""
    if len(turnos) > tope_turnos:
        mitad = tope_turnos // 2
        turnos = (turnos[:mitad]
                  + [{"role": "system",
                      "content": f"[... {len(turnos) - tope_turnos} turnos "
                                 f"intermedios omitidos ...]"}]
                  + turnos[-(tope_turnos - mitad):])
    lineas = []
    for t in turnos:
        rol = {"user": "USUARIO", "assistant": "COGNIA"}.get(
            str(t.get("role")), str(t.get("role") or "?").upper())
        cont = re.sub(r"\s+", " ", str(t.get("content") or "")).strip()
        lineas.append(f"{rol}: {cont[:400]}")
    texto = "\n".join(lineas)
    return texto[:tope_chars]


def de_sesion(historial, *, nombre: str = "", pasos_reales=None,
              generar_fn=None, url=None, timeout_s: float = TIMEOUT_DEFECTO,
              tool_existe=None, listar_tools=None) -> Resultado:
    """Convierte una sesion en un flujo. NUNCA lanza.

    `pasos_reales` son las tools que de VERDAD se ejecutaron (del grabador de
    cognia/flujos o del historial del agente). Pesan mas que la conversacion:
    lo que se ejecuto es un hecho, lo que se dijo es una intencion.
    """
    inicio = time.monotonic()
    registro = {"modelo": ""}

    def _fallo(motivo: str, bruto: str = "") -> Resultado:
        return Resultado(ok=False, flujo={}, motivo=motivo, bruto=bruto,
                         ms=int((time.monotonic() - inicio) * 1000),
                         modelo=registro.get("modelo", ""))

    resumen = resumir_sesion(historial)
    if not resumen and not pasos_reales:
        return _fallo("la sesion esta vacia: no hay nada que convertir")

    tools = _tools_disponibles(tool_existe, listar_tools)
    partes = []
    if pasos_reales:
        partes += ["Herramientas que se EJECUTARON de verdad, en orden "
                   "(esto es lo que mas peso tiene):"]
        for i, p in enumerate(pasos_reales[:60], start=1):
            if isinstance(p, dict):
                partes.append(f"  {i}. {p.get('tool', '?')}  "
                              f"{str(p.get('args', ''))[:120]}"
                              + ("  [fallo]" if p.get("ok") is False else ""))
            else:
                partes.append(f"  {i}. {str(p)[:140]}")
        partes.append("")
    if resumen:
        partes += ["Conversacion de la sesion:", resumen, ""]
    if tools:
        partes += ["Tools disponibles (usa SOLO estas):",
                   ", ".join(sorted(tools)[:120]), ""]
    if nombre:
        partes.append(f'El flujo se tiene que llamar: "{nombre}"')

    try:
        bruto = _generar("\n".join(partes), _SYSTEM_SESION, url=url,
                         timeout_s=timeout_s, generar_fn=generar_fn,
                         registro=registro)
    except (TimeoutError, OSError) as exc:
        return _fallo(f"timeout o red: {type(exc).__name__}: {exc}")
    except Exception as exc:
        return _fallo(f"{type(exc).__name__}: {exc}")

    if str(registro.get("finish_reason") or "") == "length":
        return _fallo(f"la sesion no cupo en el presupuesto de tokens "
                      f"(max_tokens={N_PREDICT})")

    crudo = _extraer_json(bruto)
    if tool_existe is None and tools:
        tool_existe = (lambda t: t in set(tools))
    flujo, motivo = sanear_flujo(crudo, tool_existe=tool_existe,
                                 nombre_previo=nombre)
    if motivo == "el modelo devolvio un flujo vacio":
        # Respuesta legitima: el prompt la contempla ("si la sesion no
        # contiene trabajo reproducible"). El motivo lo dice el modelo.
        return _fallo(str(crudo.get("resumen")
                          or "esta sesion no tiene trabajo reproducible"))
    if motivo:
        return _fallo(motivo, bruto=bruto[:400])
    return Resultado(ok=True, flujo=flujo, motivo="ok",
                     resumen=str(crudo.get("resumen") or "")[:300],
                     ms=int((time.monotonic() - inicio) * 1000),
                     modelo=registro.get("modelo", ""))
