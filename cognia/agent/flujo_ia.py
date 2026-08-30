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

Y en editar(): se parte SIEMPRE del flujo actual. Lo que se le pide al modelo
son las OPERACIONES (anadir_nodo, conectar, ...), no el DAG entero; se aplican
en Python sobre el flujo real y el resultado se valida de una pieza con
`flows.validar`. Si el delta esta mal, no se aplica NADA y se reintenta por el
camino viejo (pedir el flujo completo), que sigue vivo como respaldo.

POR QUE EL DELTA, MEDIDO (2026-08-29, :8080 con Qwen3.8-27B-Ridge)
------------------------------------------------------------------
El editor visual no podia editar un flujo de 7 nodos: `ok:false` en 5 de 6
casos con "no cupo en el presupuesto de tokens". Instrumentando el camino
(prompt / razonamiento / JSON, con presupuesto de 8192 para que nada se
cortara) salieron DOS causas separadas, y solo una era la grande:

    nodos | prompt | razonamiento |  JSON | total | finish
        2 |  2.802 |        1.323 |    82 | 1.408 | stop
        5 |  2.995 |        4.498 |   237 | 4.738 | stop
        7 |  3.111 |        8.192 |     0 | 8.192 | LENGTH  <- ni empezo
       12 |  3.361 |        2.572 |   405 | 2.980 | stop

El JSON de salida cuesta 82-405 tokens y crece despacio; el RAZONAMIENTO
cuesta 1.300-8.192 y no crece con el flujo: se dispara. La plantilla de chat
de este modelo arranca en `reasoning_effort='xhigh'` cuando nadie dice lo
contrario, y el camino estructurado del editor no decia nada. El camino de
texto plano SI lo apagaba (`mejorar_prompt._kwargs_plantilla`), que es la
razon de que este fallo solo se viera en el editor visual.

Contrafactual, mismo caso de 7 nodos, lo unico que cambia es el pensamiento:

    xhigh (lo de hoy)     2.439 razon +  332 JSON = 2.774 tok  69,7 s  ok:false
    reasoning_effort low  1.420 razon +  357 JSON = 1.780 tok  46,1 s  ok:true
    enable_thinking=False     0 razon +  469 JSON =   470 tok  10,2 s  ok:true

Y el delta ademas hace el coste de salida CONSTANTE (medido con el mismo
pedido, thinking apagado): 256 / 309 / 244 / 267 / 292 tokens para flujos de
2 / 5 / 7 / 12 / 20 nodos, ~10-12 s en todos. Pedir el DAG entero es O(n) por
definicion (devuelve el flujo completo); pedir operaciones es O(cambio), que
es la unica de las dos que escala.

Lo que NO era: subir el presupuesto a secas no vale (con 3.000 el flujo de 7
nodos seguia dando `length`), y el prompt no es el problema (2.800-3.400
tokens de prefill a 1.878 tok/s son ~1,7 s de los 35).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

__all__ = ["Resultado", "editar", "de_sesion", "sanear_flujo", "aplicar_ops",
           "ESQUEMA_FLUJO", "ESQUEMA_DELTA"]

TEMPERATURA = 0.2          # estructura, no creatividad

# Presupuesto del RESPALDO (pedir el DAG entero). El 1400 de antes no daba ni
# para el razonamiento de un flujo de 5 nodos; 2000 cabe en el timeout de
# pared (a los 35 tok/s medidos son ~57 s de generacion) y cubre el peor DAG
# visto con el pensamiento acotado (1.780 tokens). Subirlo mas no sirve: el
# techo real no es este numero sino TIMEOUT_DEFECTO, porque sin streaming el
# timeout es un deadline de pared sobre la generacion entera.
N_PREDICT = 2000

# Presupuesto de la via por defecto (el delta). Las operaciones medidas
# cuestan 244-309 tokens para flujos de 2 a 20 nodos; el resto del margen es
# para el caso en que el backend IGNORE el "no pienses" y razone igual.
N_PREDICT_DELTA = 1600

TIMEOUT_DEFECTO = 120.0    # deadline de PARED: sin stream cubre la generacion
TOPE_TOOLS_PROMPT = 120    # el mismo tope de siempre, ahora con firma
TOPE_OPS = 40              # un delta de 40 operaciones ya no es un delta

# Interruptores. Ninguno hace falta para el uso normal: los dos existen para
# poder VOLVER al comportamiento viejo sin editar codigo si un modelo nuevo se
# porta distinto, y para que el diagnostico se pueda repetir.
#   COGNIA_FLUJO_DELTA=0   -> se pide el DAG entero, como antes del 2026-08-29.
#   COGNIA_FLUJO_PENSAR=1  -> no se apaga el razonamiento (el default lo apaga).


def _delta_encendido() -> bool:
    return os.environ.get("COGNIA_FLUJO_DELTA", "1") != "0"


def _pensar_encendido() -> bool:
    return os.environ.get("COGNIA_FLUJO_PENSAR", "0") == "1"

# El DAG como JSON Schema, para el modo `completar_fn` (json_schema strict).
# Es la MISMA forma que acepta sanear_flujo, no una segunda definicion con
# vida propia: aqui solo se declara lo que sanear_flujo ya exige (id, tool,
# args, wires) y lo que ya admite como opcional. Forzar la gramatica ahorra
# el 'el modelo devolvio prosa', pero NO sustituye a la validacion: un JSON
# perfecto puede seguir teniendo un ciclo o una tool inexistente, y eso lo
# caza flows.validar(), que sigue corriendo igual.
ESQUEMA_FLUJO = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string"},
        "resumen": {"type": "string"},
        "nodos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "tool": {"type": "string"},
                    "args": {"type": "string"},
                    "wires": {"type": "array", "items": {"type": "string"}},
                    "saltar_si": {"type": "string"},
                    "reintentos": {"type": "integer"},
                    "timeout_s": {"type": "number"},
                    "modelo": {"type": "string"},
                },
                "required": ["id", "tool", "args", "wires"],
            },
        },
    },
    "required": ["nombre", "resumen", "nodos"],
}


# El DELTA como JSON Schema. Mismo papel que ESQUEMA_FLUJO en su via: forzar
# la gramatica quita "el modelo contesto en prosa", y NO sustituye a nada --
# `aplicar_ops` comprueba que cada operacion se pueda aplicar de verdad y
# `flows.validar` sigue siendo el que manda sobre el resultado.
ESQUEMA_DELTA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string",
                           "enum": ["anadir_nodo", "borrar_nodo",
                                    "cambiar_args", "cambiar_tool",
                                    "cambiar_control", "conectar",
                                    "desconectar", "renombrar"]},
                    "id": {"type": "string"},
                    "tool": {"type": "string"},
                    "args": {"type": "string"},
                    "de": {"type": "string"},
                    "a": {"type": "string"},
                    "nombre": {"type": "string"},
                    "saltar_si": {"type": "string"},
                    "reintentos": {"type": "integer"},
                    "timeout_s": {"type": "number"},
                    "modelo": {"type": "string"},
                },
                "required": ["op"],
            },
        },
    },
    "required": ["resumen", "ops"],
}


@dataclass
class Resultado:
    ok: bool = False
    flujo: dict = field(default_factory=dict)
    motivo: str = ""
    resumen: str = ""
    ms: int = 0
    modelo: str = ""
    bruto: str = ""
    # Por que via salio: "delta" (operaciones), "flujo entero" (el respaldo) o
    # "" (no se llego a hablar con el modelo). Es un dato de diagnostico, no
    # de control: quien llama sigue mirando solo `ok`.
    via: str = ""

    def a_dict(self) -> dict:
        return {"ok": self.ok, "flujo": dict(self.flujo), "motivo": self.motivo,
                "resumen": self.resumen, "ms": self.ms, "modelo": self.modelo,
                "via": self.via}


# EL SEPARADOR DE LOS ARGS ES " | ", Y AQUI ES DONDE SE ENSENA (2026-08-29).
# Los dos ejemplos de este modulo (el de _FORMATO y el de `cambiar_args` en
# _SYSTEM_DELTA) decian args:"informe.md\n{{hallar}}", y `escribir_archivo`
# exige "ruta | contenido". El modelo COPIA la forma del ejemplo igual que
# copia los nombres de las tools, asi que TODOS los flujos que escribian un
# fichero salian con un unico argumento y el nodo moria en ejecucion con
# "ERROR: formato". Contrafactual medido el 2026-08-29: el MISMO flujo, con
# lo unico cambiado el "\n" por " | ", da 0 errores y un informe.md de 1001
# bytes. Es la causa raiz de "los workflows no entregan nada": no fallaba el
# motor, fallaba lo que el prompt ensenaba a escribir. La convencion va
# ademas declarada como REGLA en los dos prompts, porque un ejemplo correcto
# sin regla se pierde en cuanto la tarea no se parece al ejemplo.
#
# Y EL NODO DE ENTRADA SE ENSENA AQUI TAMBIEN (2026-08-30). `asegurar_prompt`
# le pone a todo flujo guardado un nodo `prompt` con args:"" -- pero el
# CABLEADO ({{prompt}} dentro de los args del nodo que depende del objetivo)
# no lo hace nadie mas que el modelo, y estos dos prompts no nombraban ni una
# vez `prompt`, `prompt_fijo` ni `{{prompt}}`. Medido contra el :8080 el
# 2026-08-30, ANTES de este cambio:
#   - de_sesion devolvia el flujo SIN nodo de entrada (0 de 1); al guardarlo,
#     `asegurar_prompt` le colgaba uno que no referenciaba NADIE: el flujo
#     ignoraba en silencio el texto de `/flujoteca ejecutar <flujo> <texto>`;
#   - pidiendole al editor "que el fichero guarde lo que yo escriba al
#     ejecutar el flujo" sobre un flujo sin entrada, contesto ok=True con
#     args "notas.txt | {{texto_usuario}}" -- un marcador INVENTADO, que
#     `_interpolar` sustituye por cadena vacia: fichero vacio y cero errores.
# Por eso la regla es explicita en los DOS caminos (el DAG entero y el delta)
# y el ejemplo de _FORMATO ya trae el nodo de entrada INTERPOLADO: el modelo
# copia la forma del ejemplo.
_FORMATO = """FORMATO DE SALIDA (solo el JSON, nada antes ni despues):
{"nombre": "...",
 "resumen": "una linea diciendo que cambiaste y por que",
 "nodos": [
   {"id": "prompt", "tool": "prompt", "args": "tendencias IA 2026",
    "wires": ["hallar"]},
   {"id": "hallar", "tool": "buscar", "args": "{{prompt}}",
    "wires": ["guardar"]},
   {"id": "guardar", "tool": "escribir_archivo", "args": "informe.md | {{hallar}}",
    "wires": []}
 ]}

NOTA SOBRE EL EJEMPLO: las tres tools de arriba ("prompt", "buscar",
"escribir_archivo") son tools REALES del registro de Cognia. No es un detalle
de estilo: el modelo COPIA los nombres del ejemplo, asi que un ejemplo con una
tool inventada hace que TODOS los flujos generados se rechacen por "tool no
existe". El ejemplo
decia "buscar_web" (que no existe) y por eso ni sesion-a-flujo ni la edicion
conversacional funcionaban contra el modelo real, mientras los tests con
generar_fn inyectado pasaban todos. Lo cazo el e2e del 2026-08-28 y lo vigila
tests/test_flujo_ia.py::test_el_ejemplo_del_prompt_usa_tools_reales.

EL NODO DE ENTRADA (el PRIMERO de todo flujo, como "prompt" en el ejemplo)
- Su tool es "prompt" (VARIABLE: el texto que el dueno teclea al lanzar el
  flujo con `/flujoteca ejecutar <flujo> <texto>` PISA su args) o
  "prompt_fijo" (CONSTANTE: ignora ese texto). Su args es el valor por
  defecto; sus wires, los nodos que arrancan el trabajo.
- Su salida se interpola con {{prompt}} (o {{<su id>}} si se llama de otro
  modo). TODO nodo cuyo trabajo dependa del objetivo del usuario TIENE que
  llevar ese marcador dentro de sus args, como "hallar" en el ejemplo. Un
  flujo cuyo nodo de entrada no usa NADIE ignora en silencio lo que el dueno
  pidio: corre, sale verde y hace siempre exactamente lo mismo.
- No inventes otros marcadores ({{texto_usuario}}, {{objetivo}}...): un {{x}}
  que no sea el id de un nodo REAL del flujo se sustituye por CADENA VACIA, y
  el flujo entrega un fichero vacio sin dar ni un error.

REGLAS DEL FORMATO (son duras: si no se cumplen, el flujo se rechaza entero)
- "id": corto, en minusculas, sin espacios, UNICO dentro del flujo.
- "tool": tiene que ser una de las tools de la lista que te doy. Nada mas.
- "args": los argumentos POSICIONALES de la tool van en UNA sola cadena,
  separados por " | " (espacio, barra vertical, espacio) y en el MISMO orden
  en que los declara la firma de la tool en la lista de arriba. EL SALTO DE
  LINEA NO SEPARA ARGUMENTOS: los saltos de linea que pongas dentro de un
  argumento (el contenido de un fichero, por ejemplo) son parte de ESE
  argumento. Con escribir_archivo(path, contenido):
      BIEN: "informe.md | {{hallar}}"
      MAL:  "informe.md\\n{{hallar}}"   <- es UN solo argumento y la tool falla
  Una tool de un solo argumento no lleva ningun " | ".
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

_SYSTEM_DELTA = """Eres el editor de flujos de trabajo de Cognia.

Recibes un flujo existente y una instruccion del usuario en lenguaje natural.
Devuelves SOLO la lista de OPERACIONES que hay que aplicarle. NO devuelvas el
flujo entero: los nodos que no cambian no se nombran.

FORMATO DE SALIDA (solo el JSON, nada antes ni despues):
{"resumen": "una linea diciendo que cambiaste y por que",
 "ops": [
   {"op": "anadir_nodo", "id": "hallar", "tool": "buscar",
    "args": "tendencias IA 2026"},
   {"op": "conectar", "de": "hallar", "a": "guardar"}
 ]}

LAS OPERACIONES, TODAS LAS QUE HAY
- {"op":"anadir_nodo","id":"hallar","tool":"buscar","args":"tendencias IA"}
- {"op":"borrar_nodo","id":"hallar"}
- {"op":"cambiar_args","id":"guardar","args":"informe.md | {{hallar}}"}
- {"op":"cambiar_tool","id":"guardar","tool":"apendar_archivo"}
- {"op":"cambiar_control","id":"hallar","reintentos":3,"timeout_s":30}
- {"op":"conectar","de":"hallar","a":"guardar"}
- {"op":"desconectar","de":"hallar","a":"guardar"}
- {"op":"renombrar","nombre":"informe diario"}

NOTA SOBRE EL EJEMPLO: "buscar", "escribir_archivo" y "apendar_archivo" son
tools REALES del registro de Cognia. El modelo COPIA los nombres del ejemplo,
asi que un ejemplo con una tool inventada hace que TODOS los deltas se
rechacen por "tool no existe" (paso de verdad el 2026-08-28).

REGLAS (son duras: si no se cumplen, no se aplica NADA)
1. "tool" tiene que ser una de las tools de la lista que te doy. Nada mas.
1b. "args" son los argumentos POSICIONALES de la tool en UNA sola cadena,
   separados por " | " y en el MISMO orden en que los declara la firma de la
   tool en la lista de arriba. EL SALTO DE LINEA NO SEPARA ARGUMENTOS: lo que
   pongas tras un "\\n" sigue siendo parte del argumento anterior. Con
   escribir_archivo(path, contenido): "informe.md | {{hallar}}" esta BIEN y
   "informe.md\\n{{hallar}}" esta MAL (la tool recibe un solo argumento y
   falla). Una tool de un solo argumento no lleva ningun " | ".
2. "id": corto, en minusculas, sin espacios, y que no exista ya en el flujo.
3. Para INTERCALAR un nodo nuevo X entre A y B hacen falta CUATRO operaciones:
   anadir_nodo X, desconectar A->B, conectar A->X, conectar X->B.
4. Para usar la salida de un nodo dentro de los args de otro: {{id_del_nodo}}.
5. El grafo tiene que quedar ACICLICO: si A lleva a B, B no puede volver a A.
6. Campos opcionales de anadir_nodo: "saltar_si", "reintentos", "timeout_s",
   "modelo". En un nodo QUE YA EXISTE esos cuatro se cambian con
   "cambiar_control" (nunca con "cambiar_args"), y se QUITAN mandandolos a 0
   o a "".
7. Si la instruccion YA esta cumplida en el flujo, o no se puede cumplir
   (pide una tool que no existe, o crearia un ciclo), devuelve "ops": [] y
   explica por que en "resumen". No inventes un cambio para no dejarlo vacio.
8. EL NODO DE ENTRADA. Todo flujo empieza por un nodo cuya tool es "prompt"
   (VARIABLE: el texto que el dueno teclea en `/flujoteca ejecutar <flujo>
   <texto>` pisa su args) o "prompt_fijo" (CONSTANTE). Su salida se interpola
   con {{prompt}}, o con {{<su id>}} si se llama de otro modo. CUANDO LO QUE
   TE PIDEN DEPENDA DEL OBJETIVO DEL USUARIO, el nodo que lo use tiene que
   llevar ese marcador en sus args:
     {"op":"cambiar_args","id":"hallar","args":"{{prompt}}"}
   Y si el flujo que recibes NO trae nodo de entrada, anadelo y conectalo a
   la primera raiz:
     {"op":"anadir_nodo","id":"prompt","tool":"prompt","args":"<por defecto>"}
     {"op":"conectar","de":"prompt","a":"<la raiz del flujo>"}
   No inventes otros marcadores ({{texto_usuario}}, {{objetivo}}...): un {{x}}
   que no sea el id de un nodo REAL se sustituye por CADENA VACIA y el flujo
   entrega un fichero vacio sin dar ni un error.
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


def _id_limpio(valor) -> str:
    """El id tal y como lo normaliza sanear_flujo. La MISMA regla en los dos
    sitios: si aqui se aceptara 'mi nodo' y alli se convirtiera en 'mi_nodo',
    un `conectar` al id crudo apuntaria a un nodo que no existe."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", str(valor or "")).strip("_")


def aplicar_ops(flujo: dict, ops, *, tool_existe=None) -> tuple:
    """(flujo nuevo, motivo_si_invalido). El flujo de entrada NO se toca.

    TODO O NADA. Una operacion que no se puede aplicar (un id que no existe,
    un nodo repetido, una op que no esta en la lista) rechaza el delta ENTERO
    y devuelve ({}, motivo). Aplicar las que se pueden y callar el resto es
    justo el fallo que la cabecera de este fichero declara inaceptable: el
    dueno se creeria que su instruccion se cumplio y lo descubriria al
    ejecutar.

    DOS PASADAS, y la razon es medida: el modelo emite `conectar` en el mismo
    delta que el `anadir_nodo` del destino, a veces antes. Con una sola pasada
    secuencial ese delta correcto se rechazaria por "el nodo no existe". Los
    nodos se crean/borran/cambian en la pasada 1 y los cables se aplican en la
    2, contra el conjunto FINAL de nodos.
    """
    if not isinstance(flujo, dict):
        return {}, "no hay flujo sobre el que aplicar el delta"
    if not isinstance(ops, list):
        return {}, "el modelo no devolvio una lista 'ops'"
    if len(ops) > TOPE_OPS:
        return {}, (f"el modelo pidio {len(ops)} operaciones de golpe "
                    f"(el tope es {TOPE_OPS}): eso ya no es un cambio, es un "
                    f"flujo nuevo")

    nodos = []
    for n in (flujo.get("nodos") or []):
        if not isinstance(n, dict):
            return {}, "el flujo de partida tiene nodos que no son objetos"
        copia = dict(n)
        copia["wires"] = list(n.get("wires") or [])
        nodos.append(copia)
    nombre = str(flujo.get("nombre") or "")
    por_id = {str(n.get("id") or ""): n for n in nodos}
    cables = []

    for i, op in enumerate(ops, start=1):
        if not isinstance(op, dict):
            return {}, f"la operacion {i} no es un objeto JSON"
        que = str(op.get("op") or "").strip()

        if que == "anadir_nodo":
            nid = _id_limpio(op.get("id"))
            tool = str(op.get("tool") or "").strip()
            if not nid:
                return {}, f"la operacion {i} (anadir_nodo) no trae 'id'"
            if not tool:
                return {}, (f"la operacion {i} quiere anadir el nodo '{nid}' "
                            f"sin decir con que tool")
            if nid in por_id:
                return {}, (f"la operacion {i} quiere anadir el nodo '{nid}' "
                            f"pero ya hay uno con ese id")
            nuevo = {"id": nid, "tool": tool,
                     "args": str(op.get("args") or ""), "wires": []}
            for campo in ("saltar_si", "reintentos", "timeout_s", "modelo"):
                if op.get(campo) not in (None, ""):
                    nuevo[campo] = op[campo]
            nodos.append(nuevo)
            por_id[nid] = nuevo

        elif que == "borrar_nodo":
            nid = _id_limpio(op.get("id"))
            if nid not in por_id:
                return {}, (f"la operacion {i} quiere borrar el nodo '{nid}', "
                            f"que no existe en el flujo")
            nodos = [n for n in nodos if n is not por_id[nid]]
            del por_id[nid]
            for n in nodos:
                n["wires"] = [w for w in n["wires"] if w != nid]
            cables = [c for c in cables if nid not in (c[1], c[2])]

        elif que in ("cambiar_args", "cambiar_tool", "cambiar_control"):
            nid = _id_limpio(op.get("id"))
            if nid not in por_id:
                return {}, (f"la operacion {i} quiere cambiar el nodo '{nid}', "
                            f"que no existe en el flujo")
            if que == "cambiar_args":
                por_id[nid]["args"] = str(op.get("args") or "")
            elif que == "cambiar_tool":
                tool = str(op.get("tool") or "").strip()
                if not tool:
                    return {}, (f"la operacion {i} quiere cambiarle la tool a "
                                f"'{nid}' sin decir a cual")
                por_id[nid]["tool"] = tool
            else:
                # "hazlo reintentable" es UNA de las tres sugerencias que el
                # editor pinta en su primera pantalla, y sin esta operacion el
                # delta no sabia expresarla: el turno caia siempre al respaldo
                # caro (medido: 15,6 s por el DAG entero contra los 3-9 s del
                # delta). Un delta que no puede decir lo que si puede decir el
                # camino de respaldo no es un delta, es media via.
                tocado = False
                for campo, tipo in (("reintentos", int), ("timeout_s", float),
                                    ("saltar_si", str), ("modelo", str)):
                    if campo not in op or op[campo] is None:
                        continue
                    tocado = True
                    try:
                        valor = tipo(op[campo])
                    except Exception:
                        return {}, (f"la operacion {i} le pone a '{campo}' un "
                                    f"valor que no es {tipo.__name__}: "
                                    f"{op[campo]!r}")
                    # 0 y "" QUITAN el campo: es como se apaga un reintento o
                    # un saltar_si sin inventar una operacion mas.
                    if valor in (0, 0.0, ""):
                        por_id[nid].pop(campo, None)
                    else:
                        por_id[nid][campo] = valor
                if not tocado:
                    return {}, (f"la operacion {i} (cambiar_control) no dice "
                                f"que cambiarle a '{nid}'")

        elif que in ("conectar", "desconectar"):
            de = _id_limpio(op.get("de"))
            a = _id_limpio(op.get("a"))
            if not de or not a:
                return {}, (f"la operacion {i} ({que}) necesita 'de' y 'a'")
            cables.append((que, de, a))

        elif que == "renombrar":
            nom = str(op.get("nombre") or "").strip()
            if not nom:
                return {}, f"la operacion {i} (renombrar) no trae 'nombre'"
            nombre = nom

        else:
            return {}, (f"la operacion {i} pide '{que or '(vacio)'}', que no "
                        f"es una operacion conocida")

    for j, (que, de, a) in enumerate(cables, start=1):
        for extremo in (de, a):
            if extremo not in por_id:
                return {}, (f"el {que} numero {j} nombra el nodo '{extremo}', "
                            f"que no existe en el flujo")
        wires = por_id[de]["wires"]
        if que == "conectar":
            if a not in wires:
                wires.append(a)
        else:
            por_id[de]["wires"] = [w for w in wires if w != a]

    return sanear_flujo({"nombre": nombre, "nodos": nodos},
                        tool_existe=tool_existe, nombre_previo=nombre)


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


# El `doc` de una linea del registro lleva delante la PLANTILLA DE USO:
#     "copiar_archivo <src> | <dst>        -- copia un archivo (dst al work.)"
# `catalogo_nodos._una_linea` se queda con lo de DESPUES del " -- " (es lo que
# necesita la tarjeta de la paleta) y tira justo la parte de delante, que es el
# unico sitio donde vive la forma de los args de las tools sin params
# declarados. Aqui se recupera esa mitad.
_RX_USO = re.compile(r"^(\S+.*?)\s+--\s+\S.*$")
_ANCHO_USO = 90


def _sintaxis_de_doc(nombre: str, doc: str) -> str:
    """La plantilla de uso del doc ('copiar_archivo <src> | <dst>'), o "".

    Se exige que el doc empiece por el nombre de la tool y que traiga el
    separador " -- ": sin las dos cosas no es un doc con plantilla de uso sino
    una descripcion suelta, y devolverla como firma seria inventar una forma
    de args, que es exactamente el fallo que este modulo evita.
    """
    d = " ".join(str(doc or "").split())
    nombre = str(nombre or "").strip()
    if not d or not nombre or not d.startswith(nombre):
        return ""
    m = _RX_USO.match(d)
    if not m:
        return ""
    uso = m.group(1).strip()
    if not uso.startswith(nombre):
        return ""
    return uso[:_ANCHO_USO]


def _firma_de(entrada: dict, doc: str = "") -> str:
    """La forma de llamar a la tool, para el prompt.

    TRES CASOS, y la diferencia entre el segundo y el tercero es la que costo
    el hallazgo del 2026-08-29:

    1. params DECLARADOS  -> "tool(param, param_opcional?)".
    2. params NO declarados (lista vacia) -> la plantilla de uso del doc,
       "copiar_archivo <src> | <dst>". El contrato de `tools.catalogo_schemas`
       dice literalmente que la lista vacia significa "la tool solo declara su
       doc de una linea" (y `armar_args` lo confirma: "tool sin params
       declarados: se concatena lo que haya"), NO "la tool no lleva args".
       Son 33 de las 70 tools del registro por defecto.
    3. ni params ni plantilla -> el nombre A SECAS, sin parentesis.

    Emitir "tool()" en los casos 2 y 3 INVERTIA el objetivo del cambio: antes
    el modelo veia el nombre pelado (neutro) y despues veia una firma que le
    AFIRMA que la tool no lleva argumentos. Con "copiar_archivo(): copia un
    archivo" delante, el modelo emite args:"" , `flows.validar` no mira los
    args, el flujo se guarda con 200 y el dueno se entera al EJECUTARLO -- el
    modo de fallo que la cabecera de este fichero declara inaceptable.
    """
    nombre = str(entrada.get("nombre", "") or "")
    crudos = entrada.get("params")
    if not isinstance(crudos, (list, tuple)):
        crudos = ()
    partes = []
    for p in crudos:
        if not isinstance(p, dict):
            continue
        pn = str(p.get("nombre") or "").strip()
        if not pn:
            continue
        partes.append(pn if p.get("requerido") else pn + "?")
    if partes:
        return f"{nombre}({', '.join(partes)})"
    # `sintaxis` se lee del catalogo si algun dia lo expone; hoy no lo hace y
    # la plantilla se saca del doc del registro, que es de donde viene.
    sintaxis = str(entrada.get("sintaxis") or "").strip()
    if not sintaxis:
        sintaxis = _sintaxis_de_doc(nombre, doc or entrada.get("doc") or "")
    return sintaxis or nombre


def _docs_de_tools() -> dict:
    """{tool: doc de una linea} del registro, o {} si no se puede leer."""
    try:
        from cognia.agent import tools as _tools
        registro = getattr(_tools, "TOOLS", None) or {}
        return {str(n): str((spec or {}).get("doc") or "")
                for n, spec in registro.items()}
    except Exception:
        return {}


def _lineas_de_tools(tools: list) -> list:
    """Una linea por tool: firma + una linea de descripcion, si se puede.

    POR QUE (medido, 2026-08-29): el prompt daba SOLO los nombres
    (", ".join(sorted(tools)[:120])). El modelo acertaba la tool y se
    inventaba la FORMA de los args, que en Cognia es un protocolo de texto
    posicional ("path | contenido"), no un JSON. Con la firma delante, deja
    de adivinarla.

    MEDIDO contra el :8080 (Qwen3.8-27B-Ridge, n=1 por brazo, mismo prompt y
    misma temperatura, lo unico que cambia es la firma) con "apunta en el
    grafo que informe.md lo genero el flujo":
        kg_agregar()                                -> args sin un solo pipe
        kg_agregar <sujeto> | <relacion> | <objeto> -> "informe.md |
                                                       generado_por | ..."
    Con el mismo montaje, "copia informe.md a informe.bak" salio bien por los
    dos lados: la firma vacia no rompe SIEMPRE, rompe cuando la forma de los
    args no se puede adivinar.

    `catalogo_nodos` se importa TOLERANTE a proposito: si no esta o falla, se
    cae a la lista de nombres de siempre. Un prompt con menos contexto es
    peor; un prompt que no sale porque un modulo de UI no esta implementado
    es una edicion conversacional rota.
    """
    nombres = sorted(tools)[:TOPE_TOOLS_PROMPT]
    if not nombres:
        return []
    try:
        ricas = _lineas_ricas(nombres)
    except Exception:
        # La proteccion cubre TODO el armado, no solo el import: `_firma_de`
        # tambien corre sobre datos del catalogo y esta llamada esta FUERA del
        # try que envuelve al modelo en editar(), asi que lo que reviente aqui
        # rompe el "NUNCA lanza" del contrato publico.
        ricas = []
    return ricas or [", ".join(nombres)]


def _lineas_ricas(nombres: list) -> list:
    """Las lineas con firma y descripcion, o [] si no hay catalogo."""
    import importlib
    _cn = importlib.import_module("cognia.agent.catalogo_nodos")
    ricas = {}
    for e in (_cn.catalogo() or []):
        if isinstance(e, dict) and e.get("nombre"):
            ricas[str(e["nombre"])] = e
    if not ricas:
        return []
    docs = _docs_de_tools()
    lineas = []
    for n in nombres:
        e = ricas.get(n)
        if not e:
            # La tool existe para quien llama pero no esta en el catalogo
            # (una familia recien registrada, un fake de un test). Se nombra
            # igual: quitarla de la lista se la esconderia al modelo.
            lineas.append(f"- {n}")
            continue
        desc = " ".join(str(e.get("descripcion") or "").split())[:110]
        lineas.append(f"- {_firma_de(e, docs.get(n, ''))}"
                      + (f": {desc}" if desc else ""))
    return lineas


def _kwargs_sin_pensar() -> dict:
    """`{"kwargs_plantilla": {...}}` para APAGAR el razonamiento, o {}.

    Se pregunta al PERFIL del modelo y no se manda la clave a ciegas, igual
    que hace `mejorar_prompt._kwargs_plantilla` (que es de donde viene esta
    idea y la razon de que el camino de texto plano nunca sufriera este bug):
    la clave que apaga el pensamiento es distinta por familia, y mandar
    `enable_thinking` a un modelo cuya plantilla no la conoce no apaga nada.

    MEDIDO el 2026-08-29 contra el :8080 con el flujo real de 7 nodos y el
    pedido literal del dueno: con el pensamiento en su default (`xhigh`) el
    turno cuesta 2.774 tokens y 69,7 s y sale `ok:false`; apagado cuesta 470
    tokens y 10,2 s y sale `ok:true`. No es una optimizacion: es la diferencia
    entre que el chat del editor funcione y que no.
    """
    if _pensar_encendido():
        return {}
    try:
        from cognia.agent.model_profiles import perfil_del_agente
        kw = dict(perfil_del_agente().get("kwargs_plantilla") or {})
    except Exception:
        # Sin perfil no se adivina la clave: se deja pensar y se paga con
        # presupuesto (que para eso N_PREDICT_DELTA lleva margen de sobra).
        return {}
    if "enable_thinking" in kw:
        kw["enable_thinking"] = False
    return {"kwargs_plantilla": kw} if kw else {}


def _generar_estructurado(prompt: str, system: str, *, timeout_s: float,
                          completar_fn, registro: dict,
                          esquema: dict = None, nombre_esquema: str = "flujo",
                          max_tokens: int = None, extra: dict = None) -> str:
    """El texto del modelo pidiendolo con json_schema strict.

    `completar_fn` tiene la firma de `chat_client.completar` (mensajes,
    response_format, ...). Se pide por parametro y no se importa aqui para
    que el modulo siga siendo PURO: quien lo pasa es el servidor del editor,
    que ya sabe a que backend habla.

    Un fallo del cliente se convierte en excepcion a proposito: editar() y
    de_sesion() ya envuelven la llamada y devuelven el flujo intacto con el
    motivo. Devolver "" aqui daria el motivo generico "no devolvio JSON" y
    perderia el error real.
    """
    resp = completar_fn(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompt}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": nombre_esquema,
                                         "schema": esquema or ESQUEMA_FLUJO,
                                         "strict": True}},
        temperature=TEMPERATURA,
        max_tokens=int(max_tokens or N_PREDICT), timeout=timeout_s,
        via="flujo_ia", **(extra or {}))
    if isinstance(resp, str):
        return resp
    error = str(getattr(resp, "error", "") or "")
    if error:
        raise RuntimeError(error)
    # El mismo registro que rellena el camino de texto plano: sin esto, la
    # respuesta cortada por presupuesto pasaria como "el modelo no devolvio
    # JSON" y el dueno no sabria que le falto sitio.
    registro["finish_reason"] = str(getattr(resp, "finish_reason", "") or "")
    registro["modelo"] = _modelo_de(resp)
    # Lo que hace falta para que el motivo de "no cupo" diga la VERDAD MEDIDA
    # en vez de culpar al tamano del flujo: cuantos tokens se gastaron y en
    # que mitad se fueron. Sin esto el mensaje solo podia repetir el tope.
    texto = str(getattr(resp, "texto", "") or "")
    razon = str(getattr(resp, "reasoning_content", "") or "")
    uso = getattr(resp, "usage", None)
    if isinstance(uso, dict) and uso.get("completion_tokens"):
        registro["completion_tokens"] = int(uso["completion_tokens"])
    registro["razon_chars"] = len(razon)
    registro["texto_chars"] = len(texto)
    return texto


MODELO_DESCONOCIDO = "desconocido"


def _modelo_de(resp) -> str:
    """El nombre del modelo que contesto, o "desconocido". NUNCA "".

    `RespuestaChat` (cognia/agent/chat_client.py) NO tiene campo `modelo` --
    sus campos son texto, tool_calls, finish_reason, usage, reasoning_content,
    error, duracion_s, cortado, tool_calls_parciales, usage_estimado,
    usage_via y frames_malformados. El `getattr(resp, "modelo", "")` de antes
    lo tapaba con su default: por la via estructurada (la de por defecto en el
    editor visual) el chat devolvia SIEMPRE modelo:"" y quedaba igual que "el
    backend no contesto". Se pregunta, por este orden:

    1. la respuesta, por si el cliente que la trae si lo dice (lo hacen los
       dobles de los tests y cualquier cliente con campo `modelo`/`model`);
    2. el backend, que es de donde lo saca la via de texto plano
       (`mejorar_prompt._construir_generar` lee el `model` que devuelve
       llama-server). `_modelo_servido` usa el /props CACHEADO y no lanza;
    3. si ninguna de las dos sabe, se dice "desconocido" -- que es un dato,
       mientras que "" se lee como un hueco.
    """
    for campo in ("modelo", "model"):
        valor = str(getattr(resp, campo, "") or "").strip()
        if valor:
            return valor
    try:
        from cognia.agent import chat_client as _cc
        servido = str(_cc._modelo_servido() or "").strip()
        if servido:
            return servido
    except Exception:
        pass
    return MODELO_DESCONOCIDO


def _generar(prompt: str, system: str, *, url=None, timeout_s: float,
             generar_fn, registro: dict, completar_fn=None,
             esquema: dict = None, nombre_esquema: str = "flujo",
             max_tokens: int = None, extra: dict = None) -> str:
    max_tokens = int(max_tokens or N_PREDICT)
    if generar_fn is not None:
        # `generar_fn` manda sobre `completar_fn`: es el que inyectan los
        # tests y el que hace deterministas las 25 pruebas del modulo.
        return generar_fn(prompt, system)
    if completar_fn is not None:
        return _generar_estructurado(prompt, system, timeout_s=timeout_s,
                                     completar_fn=completar_fn,
                                     registro=registro, esquema=esquema,
                                     nombre_esquema=nombre_esquema,
                                     max_tokens=max_tokens, extra=extra)
    from cognia.harness import mejorar_prompt as _mp
    destino = _mp._detectar_url(url)
    if not destino:
        raise RuntimeError(_mp._motivo_backend(url) or "sin backend local")
    fn = _mp._construir_generar(destino, timeout_s, registro)
    # El presupuesto del reformulador (600 tokens) no da para un DAG entero.
    # (Este camino ya apaga el razonamiento por su cuenta, en
    # `mejorar_prompt._kwargs_plantilla`: es la razon de que el bug del
    # presupuesto solo se viera por la via estructurada del editor visual.)
    _viejo = _mp.N_PREDICT
    try:
        _mp.N_PREDICT = max_tokens
        return fn(prompt, system)
    finally:
        _mp.N_PREDICT = _viejo


def _limpiar_medidas(registro: dict) -> None:
    """Deja el registro sin las medidas del intento anterior."""
    for clave in ("finish_reason", "completion_tokens", "razon_chars",
                  "texto_chars"):
        registro.pop(clave, None)


def _motivo_presupuesto(registro: dict, tope: int, sujeto: str) -> str:
    """El motivo de "no cupo", con los NUMEROS que se midieron de verdad.

    El mensaje viejo decia "proba una instruccion mas acotada o un flujo mas
    chico" y las dos mitades eran falsas: el verificador del 2026-08-29 midio
    que el flujo de 3 nodos y el de 2 fallaban IGUAL, porque lo que se comia
    el presupuesto no era el flujo sino el razonamiento. Un motivo que culpa
    a lo que no fue manda al dueno a arreglar lo que no esta roto.
    """
    gastados = registro.get("completion_tokens")
    razon = int(registro.get("razon_chars") or 0)
    texto = int(registro.get("texto_chars") or 0)
    cabeza = (f"{sujeto} no cupo en el presupuesto de tokens "
              f"(max_tokens={tope})")
    if gastados:
        cabeza += f": el modelo gasto los {gastados}"
    else:
        cabeza += ": el modelo lo agoto"
    if razon and not texto:
        return (cabeza + f" pensando ({razon} caracteres de razonamiento) y no "
                f"llego a escribir ni el primer caracter del JSON. No es el "
                f"tamano del flujo: con el razonamiento asi de largo falla "
                f"igual un flujo de 2 nodos")
    if razon:
        return (cabeza + f" repartidos en {razon} caracteres de razonamiento y "
                f"{texto} de JSON, que quedo a medias")
    if texto:
        return cabeza + f" escribiendo {texto} caracteres de JSON sin cerrarlo"
    return (cabeza + " sin devolver nada utilizable; el backend no dice en que "
            "se los gasto")


def editar(flujo: dict, instruccion: str, *, generar_fn=None, url=None,
           timeout_s: float = TIMEOUT_DEFECTO, tool_existe=None,
           listar_tools=None, completar_fn=None) -> Resultado:
    """Aplica `instruccion` a `flujo` y devuelve el flujo nuevo. NUNCA lanza.

    Con ok=False, `flujo` vuelve EXACTAMENTE como entro: quien llama puede
    guardar el resultado sin comprobar nada y no rompe nada.

    `completar_fn` es OPCIONAL y no cambia nada de lo de antes: sin el, el
    camino es exactamente el mismo POST de texto plano de siempre. Con el
    (lo pasa el editor visual) se pide el JSON por gramatica, que quita la
    clase entera de fallos "el modelo contesto en prosa". `generar_fn` sigue
    ganando a los dos.

    DOS INTENTOS, en este orden (ver la cabecera del fichero para los numeros
    que lo decidieron):

    1. DELTA: se le piden las operaciones y se aplican en Python con
       `aplicar_ops`. Coste de salida CONSTANTE con el tamano del flujo.
    2. RESPALDO: si el delta no se puede aplicar, se pide el DAG entero,
       exactamente como se hacia antes. No se pierde nada por intentar el
       barato primero: cuando el delta sale (lo normal) el turno cuesta ~10 s.

    `generar_fn` NO pasa por el delta: su contrato es "un prompt, un texto",
    y meterle una segunda llamada por dentro cambiaria lo que miden los ~25
    tests que lo inyectan. Los dos caminos que hablan con un modelo de verdad
    (el estructurado del editor y el de texto plano del CLI) si lo usan.
    """
    inicio = time.monotonic()
    registro = {"modelo": ""}
    original = dict(flujo or {})

    def _fallo(motivo: str, bruto: str = "", via: str = "") -> Resultado:
        return Resultado(ok=False, flujo=original, motivo=motivo, bruto=bruto,
                         ms=int((time.monotonic() - inicio) * 1000),
                         modelo=registro.get("modelo", ""), via=via)

    def _igual(resumen: str, via: str) -> Resultado:
        # No es un error: el modelo puede haber decidido que la instruccion no
        # se podia cumplir. Se dice, y no se guarda una version identica.
        return Resultado(ok=False, flujo=original, motivo="el flujo quedo igual",
                         resumen=resumen[:300], via=via,
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
    lineas_tools = _lineas_de_tools(tools)
    if lineas_tools:
        partes += ["", "Tools disponibles (usa SOLO estas):"] + lineas_tools
    partes += ["", "Instruccion del usuario:", instruccion.strip()]
    prompt = "\n".join(partes)
    if tool_existe is None and tools:
        tool_existe = (lambda t: t in set(tools))

    # ---- intento 1: el delta -------------------------------------------
    fallo_delta = None
    if _delta_encendido() and generar_fn is None:
        _limpiar_medidas(registro)
        try:
            bruto = _generar(prompt, _SYSTEM_DELTA, url=url,
                             timeout_s=timeout_s, generar_fn=None,
                             registro=registro, completar_fn=completar_fn,
                             esquema=ESQUEMA_DELTA, nombre_esquema="delta",
                             max_tokens=N_PREDICT_DELTA,
                             extra=_kwargs_sin_pensar())
        except (TimeoutError, OSError) as exc:
            # Red caida o deadline agotado: el respaldo hablaria con el mismo
            # backend y tardaria otro tanto en fallar igual. Se dice y ya.
            return _fallo(f"timeout o red: {type(exc).__name__}: {exc}",
                          via="delta")
        except Exception as exc:
            return _fallo(f"{type(exc).__name__}: {exc}", via="delta")

        if str(registro.get("finish_reason") or "") == "length":
            fallo_delta = _motivo_presupuesto(registro, N_PREDICT_DELTA,
                                              "el delta")
        else:
            crudo = _extraer_json(bruto)
            ops = crudo.get("ops") if isinstance(crudo, dict) else None
            resumen = str((crudo or {}).get("resumen") or "")
            if not isinstance(ops, list):
                fallo_delta = "el modelo no devolvio una lista 'ops'"
            elif not ops:
                # Respuesta LEGITIMA y contemplada por el prompt ("si ya esta
                # cumplida, devuelve ops vacio"). No se reintenta con el DAG
                # entero: seria pagar 40 s mas por preguntarle lo mismo.
                return _igual(resumen, "delta")
            else:
                nuevo, motivo = aplicar_ops(original, ops,
                                            tool_existe=tool_existe)
                if motivo:
                    fallo_delta = motivo
                elif nuevo.get("nodos") == original.get("nodos") and \
                        nuevo.get("nombre") == (str(original.get("nombre") or "")
                                                or nuevo.get("nombre")):
                    # El `or nuevo...` no es cosmetico: un flujo SIN nombre sale
                    # de sanear_flujo llamandose "flujo", y sin esto un delta
                    # que no cambio nada se anunciaria como un cambio.
                    return _igual(resumen, "delta")
                else:
                    return Resultado(ok=True, flujo=nuevo, motivo="ok",
                                     resumen=resumen[:300], via="delta",
                                     ms=int((time.monotonic() - inicio) * 1000),
                                     modelo=registro.get("modelo", ""))

    # ---- intento 2 (o unico): el flujo entero, como siempre --------------
    # Se BORRAN las medidas del intento anterior: si no, un respaldo que se
    # corta por presupuesto contaria los caracteres de razonamiento del delta
    # y el motivo -- que existe justamente para no mentir -- mentiria.
    _limpiar_medidas(registro)
    try:
        bruto = _generar(prompt, _SYSTEM_EDITAR, url=url,
                         timeout_s=timeout_s, generar_fn=generar_fn,
                         registro=registro, completar_fn=completar_fn,
                         esquema=ESQUEMA_FLUJO, nombre_esquema="flujo",
                         max_tokens=N_PREDICT, extra=_kwargs_sin_pensar())
    except (TimeoutError, OSError) as exc:
        return _fallo(f"timeout o red: {type(exc).__name__}: {exc}",
                      via="flujo entero")
    except Exception as exc:
        return _fallo(f"{type(exc).__name__}: {exc}", via="flujo entero")

    def _con_delta(motivo: str) -> str:
        """El motivo del respaldo, sin esconder que antes fallo el delta."""
        if not fallo_delta:
            return motivo
        return f"{motivo} (y antes, por operaciones: {fallo_delta})"

    if str(registro.get("finish_reason") or "") == "length":
        return _fallo(_con_delta(_motivo_presupuesto(registro, N_PREDICT,
                                                     "el flujo")),
                      via="flujo entero")

    crudo = _extraer_json(bruto)
    nuevo, motivo = sanear_flujo(crudo, tool_existe=tool_existe,
                                 nombre_previo=original.get("nombre", ""))
    if motivo:
        return _fallo(_con_delta(motivo), bruto=bruto[:400], via="flujo entero")
    if nuevo.get("nodos") == original.get("nodos"):
        return _igual(str(crudo.get("resumen") or ""), "flujo entero")
    return Resultado(ok=True, flujo=nuevo, motivo="ok",
                     resumen=str(crudo.get("resumen") or "")[:300],
                     via="flujo entero",
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
              tool_existe=None, listar_tools=None,
              completar_fn=None) -> Resultado:
    """Convierte una sesion en un flujo. NUNCA lanza.

    `pasos_reales` son las tools que de VERDAD se ejecutaron (del grabador de
    cognia/flujos o del historial del agente). Pesan mas que la conversacion:
    lo que se ejecuto es un hecho, lo que se dijo es una intencion.

    `completar_fn` es opcional y hace lo mismo que en editar(): pedir el JSON
    por gramatica. Sin el, nada cambia.
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
                         registro=registro, completar_fn=completar_fn,
                         max_tokens=N_PREDICT, extra=_kwargs_sin_pensar())
    except (TimeoutError, OSError) as exc:
        return _fallo(f"timeout o red: {type(exc).__name__}: {exc}")
    except Exception as exc:
        return _fallo(f"{type(exc).__name__}: {exc}")

    if str(registro.get("finish_reason") or "") == "length":
        # Aqui NO hay delta que valer: de una sesion sale un flujo nuevo, no
        # un cambio sobre uno que ya existe. Pero el motivo dice los mismos
        # numeros medidos, que es lo que permite saber si falto sitio para el
        # JSON o si se lo comio el razonamiento.
        return _fallo(_motivo_presupuesto(registro, N_PREDICT, "la sesion"))

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
