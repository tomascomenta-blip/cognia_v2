# -*- coding: utf-8 -*-
"""Las capacidades del arnés expuestas al modelo como HERRAMIENTAS NATIVAS.

POR QUÉ EXISTE (2026-08-12, pedido explícito del dueño): una capacidad que el
modelo sólo conoce por una frase del prompt es una *instrucción ciega* — depende
de que obedezca. Estas se registran en el registry de `cognia/agent/tools.py`
con `desc` y `params` ricos, así que `catalogo_schemas()` las convierte en
schemas OpenAI y el bucle nativo se las manda a llama-server en el campo
`tools`. El modelo las ve como funciones con firma, no como prosa: el backend
que sirve a Qwythos-9B devuelve `finish_reason=tool_calls` con los argumentos ya
en JSON (verificado de primera mano contra :8080, build b10066).

EL TECHO DEL CATÁLOGO ES REAL. El A/B de este mismo repo (2026-07-25, n=4+4)
midió que 46 herramientas bajan el camino feliz de 4.25/5 a 2.5/5: más
herramientas no es más capacidad, es más distracción. Por eso NINGUNA de estas
entra en `CORE_TOOLS`. Cada una se anuncia sólo cuando su subsistema está
encendido, con el mismo mecanismo `flag_de_optin` que ya usan `pantalla_*`,
`imagen_*` y `escena_*`:

    recuperar ............ COGNIA_OFFLOAD=1    (sin offloading no hay handles)
    consultar_oraculo .... COGNIA_ORACULO=1    (necesita una flota con roles)
    buscar_herramientas .. COGNIA_TOOLSEARCH=1 (catálogo dinámico)
    deshacer_edicion ..... COGNIA_UNDO_TOOL=1  (el humano tiene /deshacer)
    workflow ............. COGNIA_WORKFLOW_TOOL=1 (el agente se reparte trabajo
                           a sí mismo: cuesta varias llamadas por invocación)

Sin flag, `run_tool` responde el mensaje uniforme "DESHABILITADA — activala con
<FLAG>=1" en vez de "no existe": la capacidad existe y está apagada, que es
distinto y el modelo lo entiende distinto.
"""

from __future__ import annotations

import re

from cognia.agent.tools import tool
from cognia.harness import workflows_adapter as _WF


@tool(
    "recuperar",
    "recuperar <handle> lineas 200-260 | buscar=<texto>  -- lee un trozo de una "
    "salida grande que se guardo entera en disco",
    desc=(
        "Lee una parte de una salida de herramienta que era demasiado grande para "
        "el historial y quedo guardada en disco. Cuando veas un resumen con un "
        "handle 'res:xxxxxx', esta es la forma de leer el resto: por rango de "
        "lineas o buscando texto dentro. No pierdas tiempo repitiendo la "
        "herramienta original: el contenido completo ya esta guardado."
    ),
    params=[
        {"nombre": "handle", "tipo": "string", "requerido": True,
         "descripcion": "el identificador 'res:3f2a1b' que aparece en el resumen"},
        {"nombre": "lineas", "tipo": "string", "requerido": False, "clave": True,
         "descripcion": "rango 1-indexado inclusivo, por ejemplo '200-260'"},
        {"nombre": "buscar", "tipo": "string", "requerido": False, "clave": True,
         "descripcion": "texto a buscar dentro; devuelve los aciertos con contexto"},
    ],
)
def _recuperar(args: str, ctx: dict) -> str:
    from cognia.harness import offloading
    return offloading.herramienta_recuperar(args, ctx)


@tool(
    "consultar_oraculo",
    "consultar_oraculo <pregunta> | <contexto>  -- pide ayuda a un modelo mas "
    "capaz cuando estas atascado o hay que decidir un enfoque",
    desc=(
        "Consulta a un modelo mas capaz de la flota. Usalo cuando estes atascado "
        "de verdad (el mismo error dos veces), cuando haya que elegir entre "
        "enfoques distintos, o para que revisen un diseno antes de escribirlo. "
        "Cuesta tiempo: no lo uses para cosas que puedes resolver leyendo el "
        "codigo. Devuelve un plan corto, no codigo entero."
    ),
    params=[
        {"nombre": "pregunta", "tipo": "string", "requerido": True,
         "descripcion": "que necesitas decidir o resolver, concreto"},
        {"nombre": "contexto", "tipo": "string", "requerido": False,
         "descripcion": "que probaste ya y el error exacto si lo hay"},
    ],
)
def _consultar_oraculo(args: str, ctx: dict) -> str:
    from cognia.harness import oraculo
    pregunta, _, contexto = (args or "").partition("|")
    res = oraculo.consultar(pregunta.strip(), contexto.strip(), _transporte_flota)
    if not res.get("ok"):
        return f"ERROR consultar_oraculo: {res.get('error') or 'sin respuesta'}"
    return f"RESULTADO consultar_oraculo ({res.get('rol', '?')}):\n{res.get('respuesta', '')}"


def _transporte_flota(prompt: str, rol: str, timeout: int) -> str:
    """Habla con la flota local. El oráculo no sabe de HTTP: eso vive aquí.

    Usa el mismo cliente que el bucle nativo (`agent/chat_client.py`), así que
    hereda su manejo de razonadores y su clamp de presupuesto.

    LÍMITE DECLARADO: hoy el ruteo por rol es un puerto de la flota
    (`cognia/flota.py:PUERTOS`), no un mapa rol→URL. Si el puerto del rol
    responde se usa; si no, se habla con el backend por defecto. Media
    respuesta vale más que un error, y el `rol` que devuelve `consultar` dice
    con quién se habló de verdad, así que el agente nunca cree que consultó a
    un modelo más capaz cuando no lo hizo.
    """
    from cognia.agent.chat_client import completar
    url = _url_del_rol(rol)
    resp = completar([{"role": "user", "content": prompt}],
                     max_tokens=1200, temperature=0.7, top_p=0.8,
                     **({"url": url} if url else {}))
    if not getattr(resp, "ok", False):
        raise RuntimeError(getattr(resp, "error", "el modelo no respondio"))
    return resp.texto


def _url_del_rol(rol: str) -> str:
    """URL del puerto de la flota que atiende ese rol, o '' para el de siempre.

    Sólo devuelve una URL si el puerto RESPONDE: apuntar al 8081 cuando no hay
    nadie escuchando convertiría la consulta en un timeout silencioso.
    """
    try:
        from cognia import flota
        for puerto, etiqueta in flota.PUERTOS:
            if rol and rol.lower() in etiqueta.lower() and flota._responde(puerto):
                return f"http://127.0.0.1:{puerto}"
    except Exception:
        pass
    return ""


@tool(
    "buscar_herramientas",
    "buscar_herramientas <que necesitas hacer>  -- busca herramientas que no "
    "estan en tu lista y las deja disponibles",
    desc=(
        "Busca entre TODAS las herramientas registradas (hay muchas mas de las "
        "que ves en tu lista) por lo que quieres hacer, descrito en lenguaje "
        "normal. Las que encuentre quedan disponibles para llamarlas en el paso "
        "siguiente. Usalo cuando la tarea pida algo que tu lista no cubre, en "
        "vez de inventarte un nombre de herramienta."
    ),
    params=[
        {"nombre": "consulta", "tipo": "string", "requerido": True,
         "descripcion": "que necesitas hacer, en lenguaje normal"},
    ],
)
def _buscar_herramientas(args: str, ctx: dict) -> str:
    from cognia.agent.tools import catalogo_schemas
    from cognia.harness import registro_dinamico as rd
    consulta = (args or "").strip()
    if not consulta:
        return "ERROR buscar_herramientas: dime que necesitas hacer."
    indice = rd.indexar(catalogo_schemas())
    resultados = rd.buscar(indice, consulta, limite=5)
    if not resultados:
        return f"RESULTADO buscar_herramientas: nada que case con {consulta!r}."
    sesion = (ctx or {}).get("_sesion_tools") or "agente"
    rd.activar(sesion, [nombre for nombre, _, _ in resultados])
    return rd.texto_resultado_busqueda(resultados)


@tool(
    "workflow",
    "workflow <subtarea1; subtarea2; ...> [modo=paralelo|secuencial]  -- reparte "
    "trabajo de pensar entre varias llamadas y junta los resultados",
    desc=_WF.DESC_WORKFLOW,
    params=_WF.PARAMS_WORKFLOW,
)
def _workflow(args: str, ctx: dict) -> str:
    crudo = (args or "").strip()
    modo = "paralelo"
    # El modo puede llegar de tres formas: como token 'modo=x' del protocolo
    # texto, o incrustado por el modelo dentro del propio valor de 'pasos'
    # (Qwythos cuela '<parameter=modo>paralelo'; ver `sanear`). Las dos se
    # recogen, y si no hay ninguna manda el defecto.
    _, incrustadas = _WF.sanear(crudo)
    if incrustadas.get("modo"):
        modo = incrustadas["modo"]
    m = re.search(r"\bmodo\s*=\s*(\w+)", crudo)
    if m:
        modo = m.group(1)
        crudo = crudo[:m.start()] + crudo[m.end():]
    res = _WF.ejecutar(crudo, modo=modo, nombre="agente",
                       print_fn=(ctx or {}).get("print_fn"))
    if not res["ok"]:
        return f"RESULTADO workflow ERROR: {res['error']}"
    return (f"RESULTADO workflow ({res['pasos']} pasos, {res['tokens']} tokens, "
            f"corrida {res['run_id']}):\n{res['texto']}")


@tool(
    "deshacer_edicion",
    "deshacer_edicion [n]  -- revierte la ultima escritura de ficheros que hiciste",
    desc=(
        "Deshace la ultima escritura de fichero de esta sesion y devuelve el "
        "fichero a como estaba. Usalo cuando te des cuenta de que una edicion "
        "empeoro las cosas, en vez de intentar reescribirla de memoria."
    ),
    params=[
        {"nombre": "n", "tipo": "string", "requerido": False,
         "descripcion": "numero de la entrada a deshacer; vacio = la ultima"},
    ],
    danger=True,
)
def _deshacer_edicion(args: str, ctx: dict) -> str:
    from cognia.harness import checkpoints
    crudo = (args or "").strip()
    try:
        n = int(crudo) if crudo else None
    except ValueError:
        return "ERROR deshacer_edicion: 'n' tiene que ser un numero (o vacio)."
    return f"RESULTADO deshacer_edicion: {checkpoints.deshacer(n)}"
