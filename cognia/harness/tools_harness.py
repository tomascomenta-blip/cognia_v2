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

import os
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
        # El texto de los pasos que SI salieron viaja aunque la corrida falle
        # (el critico que revienta tras 2 pasos OK). Sin esto el modelo recibe
        # solo "ERROR" y vuelve a pedir el mismo trabajo ya pagado.
        if res.get("texto"):
            return _entregar(
                f"RESULTADO workflow ERROR: {res['error']}\n"
                f"Lo ya resuelto y pagado ({res.get('pasos', 0)} pasos, "
                f"{res.get('tokens', 0)} tokens):",
                res["texto"], args)
        return f"RESULTADO workflow ERROR: {res['error']}"
    return _entregar(
        f"RESULTADO workflow ({res['pasos']} pasos, {res['tokens']} tokens, "
        f"corrida {res['run_id']}):",
        res["texto"], args)


# Umbral EN BYTES por encima del cual el texto del workflow se entrega como
# ruta+resumen en vez de entero. NO es el umbral de offloading (2000 B, el
# TOOL_RESULT_CHAR_LIMIT de Cline): son dos numeros con dos trabajos distintos
# y por eso no se comparten.
#   - ESTE decide SI el texto entra entero. 8000 B ~ 2.000 tokens ~ 12% del
#     n_ctx=16384 medido en :8080. Por debajo, un workflow de tres frases o de
#     tres parrafos sigue llegando byte a byte como hasta hoy: el camino corto
#     no puede empeorar, y offloadear a 2000 B lo habria roto.
#   - EL DE OFFLOADING decide cuanto ocupa el RESUMEN cuando ya se decidio
#     guardar. Ahi si conviene que sea chico: el resumen es lo que se queda en
#     el historial para siempre.
# POR QUE 8000 y no mas: loop.py:_recortar_mensajes recorta el content de los
# turnos `tool` a 200 CHARS en cuanto el prompt pasa el 80% del n_ctx. Un
# workflow de 6 pasos x 2048 tokens son ~45.000 chars: entraba entero, empujaba
# el prompt por encima del 80% y en la pasada siguiente el documento ENTERO se
# volvia 200 chars. Se perdia todo, y sin copia. Guardado en disco, el recorte
# se lleva el resumen y el documento sigue estando.
UMBRAL_TEXTO_WORKFLOW = 8000
_ENV_UMBRAL_WORKFLOW = "COGNIA_WF_TOOL_MAX"


def _umbral_texto_workflow() -> int:
    """El umbral efectivo, a call-time. Basura o <=0 -> el defecto (misma regla
    que `offloading.umbral_bytes`: con umbral 0 hasta un 'OK' iria a disco)."""
    bruto = os.environ.get(_ENV_UMBRAL_WORKFLOW, "").strip()
    if not bruto:
        return UMBRAL_TEXTO_WORKFLOW
    try:
        valor = int(float(bruto))
    except (TypeError, ValueError):
        return UMBRAL_TEXTO_WORKFLOW
    return valor if valor > 0 else UMBRAL_TEXTO_WORKFLOW


def _entregar(cabecera: str, texto: str, args: str) -> str:
    """El texto del workflow al modelo: entero si cabe, RUTA+resumen si no.

    Las tres cosas que tiene que llevar un documento que no viene entero, y
    ninguna es opcional:
      1. la RUTA absoluta en disco — es lo unico que funciona SIEMPRE, porque
         el handle depende de que `recuperar` este registrada y esa tool es
         opt-in (COGNIA_OFFLOAD=1). Con la ruta basta `leer_archivo`, que es
         una CORE_TOOL.
      2. un RESUMEN con principio y final de verdad, no un tocon.
      3. COMO consultarlo, con un rango que existe.
    Los tres los da `offloading` ya probado; aqui se anade la ruta y se elige
    el umbral.

    DEGRADACION: si guardar en disco falla, se devuelve el texto ENTERO como
    hasta hoy. Es peor para la ventana, pero esta es la UNICA copia del
    trabajo: `formatear_observacion` degrada a resumen-sin-handle porque alli
    el original siempre existe en otra parte (el fichero, el log); aqui no
    existe, y un resumen sin copia es perder tokens ya pagados.
    """
    cuerpo = f"{cabecera}\n{texto}"
    umbral = _umbral_texto_workflow()
    if len(cuerpo.encode("utf-8", "ignore")) <= umbral:
        return cuerpo                      # camino corto: identico a siempre
    try:
        from cognia.harness import offloading
        handle = offloading.guardar(texto, tool="workflow", args=args)
        ruta = offloading.ruta_de(handle)
        resumen = offloading.resumir_para_modelo(
            texto, tool="workflow", handle=handle)
        # Quien ESCRIBE en el almacen se ocupa de que no crezca sin fin.
        # `podar` existia y no lo llamaba NADIE (el offloading del interceptor
        # es opt-in y nunca se cableo la limpieza); esta rama escribe con
        # COGNIA_OFFLOAD apagado, asi que sin esto el almacen solo crece. Nunca
        # toca la sesion en curso —o sea, jamas el fichero que se acaba de
        # guardar— y no lanza: la politica es la del propio modulo (20 sesiones
        # / 200 MB).
        offloading.podar()
    except Exception:
        return cuerpo
    if not ruta:
        return cuerpo                      # sin ruta no hay a donde mandarlo
    return (f"{cabecera}\n{resumen}\n"
            f"[EL TEXTO COMPLETO ESTA EN DISCO, no se perdio nada:\n"
            f"  {ruta}\n"
            f"  leer_archivo {ruta}   (funciona siempre)\n"
            f"  recuperar {handle} lineas 1-60   (si la tool `recuperar` esta "
            f"activa)\n"
            f"NO vuelvas a lanzar el workflow: ya esta pagado y guardado.]")


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


# ── EJECUCION GUIONADA (2026-09-04): probar programas de consola que piden teclado ──
@tool(
    "ejecutar_guion",
    "ejecutar_guion <comando> | entradas=1|4|q [| timeout=N] [| cwd=RUTA] [| pausa=MS]"
    "  -- corre un programa de consola tecleandole las entradas UNA A UNA y devuelve lo que "
    "imprimio tras cada una",
    desc=(
        "Prueba de punta a punta un programa de CONSOLA que pide teclado por input, sin "
        "humano: lanza el comando, espera a que se quede esperando, le teclea la primera "
        "entrada, captura lo que imprime, teclea la siguiente... y devuelve la salida "
        "SEGMENTADA por entrada (>>> arranque, >>> entrada: '1', ...), el exit code y si "
        "quedo colgado esperando mas. Usala para comprobar 'despues de teclear X mostro Y' "
        "en menus, juegos de texto y asistentes; para paginas web usa renderizar con guion."
    ),
    params=[
        {"nombre": "comando", "tipo": "string", "requerido": True,
         "descripcion": "el comando a correr (ej: python juego.py)"},
        {"nombre": "entradas", "tipo": "string", "requerido": True, "clave": True,
         "descripcion": "las entradas en orden separadas por | (ej: 1|4|5|q); vacio = solo Enter"},
        {"nombre": "timeout", "tipo": "integer", "requerido": False, "clave": True,
         "descripcion": "segundos totales (default 60)"},
        {"nombre": "cwd", "tipo": "string", "requerido": False, "clave": True,
         "descripcion": "directorio de trabajo"},
        {"nombre": "pausa", "tipo": "integer", "requerido": False, "clave": True,
         "descripcion": "ms de silencio que indican que el programa espera teclado (default 400)"},
    ],
    timeout_s=180,
)
def _ejecutar_guion(args: str, ctx: dict) -> str:
    from cognia.agent import ejecucion_guionada as _EG
    s = (args or "").strip()
    opts = {}
    while True:
        ms = list(re.finditer(r"(?:\|\s*|\s+)(entradas|timeout|cwd|pausa)\s*=\s*", s, re.I))
        if not ms:
            break
        m = ms[-1]
        opts[m.group(1).lower()] = s[m.end():].strip().strip("|").strip()
        s = s[:m.start()].strip().rstrip("|").strip()
    comando = s
    if not comando:
        return "RESULTADO ejecutar_guion ERROR: falta el comando. Uso: ejecutar_guion <comando> | entradas=1|2|q"
    # Mismo gate que `ejecutar`: es un comando de shell con los permisos del usuario.
    try:
        from cognia.agent.sentinel import evaluar_shell
        permitido, msg = evaluar_shell(comando, ctx, cwd=opts.get("cwd", ""))
        if not permitido:
            return msg
    except Exception as exc:
        return f"RESULTADO ejecutar_guion ERROR: el gate de permisos no respondio ({type(exc).__name__}: {exc})"
    try:
        timeout = int(opts.get("timeout") or 60)
        pausa = int(opts.get("pausa") or 400)
    except ValueError:
        return "RESULTADO ejecutar_guion ERROR: timeout y pausa tienen que ser numeros"
    entradas = _EG.partir_entradas(opts.get("entradas", ""))
    cwd = opts.get("cwd") or ((ctx or {}).get("workspace") if isinstance(ctx, dict) else None)
    if cwd and not os.path.isdir(cwd):
        return f"RESULTADO ejecutar_guion ERROR: cwd='{cwd}' no es un directorio"
    r = _EG.correr_guionado(comando, entradas, cwd=cwd, timeout_s=max(5, min(timeout, 170)), pausa_ms=max(100, pausa))
    return "RESULTADO ejecutar_guion:\n" + _EG.texto_guionado(r, comando)


# ── MEMORIA LARGA (2026-09-04): la puerta del modelo a la memoria externa ─────
# Solo se anuncia con COGNIA_MEMORIA_LARGA=1 (ver _OPTIN_NOMBRES en agent/tools):
# el A/B del repo midio que inflar el catalogo degrada, asi que no entra en CORE.
@tool(
    "memoria_buscar",
    "memoria_buscar <consulta> [tipo=decision|error|codigo|restriccion] [historial=1]"
    "  -- busca en la memoria de largo plazo de esta tarea (lo que salio de la ventana)",
    desc=(
        "Recupera de la memoria externa de la tarea lo que ya no esta en la "
        "conversacion: decisiones, restricciones del dueno, errores y sus "
        "soluciones, codigo leido, ficheros tocados. Usala cuando dudes de algo "
        "que se dijo o se hizo antes de la ultima reconstruccion del contexto. "
        "Con historial=1 trae tambien las versiones anteriores de una decision."
    ),
    params=[
        {"nombre": "consulta", "tipo": "string", "requerido": True,
         "descripcion": "que buscas, con tus propias palabras"},
        {"nombre": "tipo", "tipo": "string", "requerido": False, "clave": True,
         "descripcion": "limitar a un tipo: decision, restriccion, error, solucion, codigo, fichero"},
        {"nombre": "historial", "tipo": "string", "requerido": False, "clave": True,
         "descripcion": "1 para incluir versiones superadas (historial de una decision)"},
    ],
)
def _memoria_buscar(args: str, ctx: dict) -> str:
    from cognia.memoria_larga import herramienta_buscar
    return herramienta_buscar(args, ctx)
