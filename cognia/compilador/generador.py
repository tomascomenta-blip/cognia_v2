"""
cognia/compilador/generador.py
==============================
De una ESPEC al CODIGO: el handler `_slash_<nombre>` que va dentro de
cognia/cli.py, el modulo de apoyo donde vive la logica de verdad, y los TESTS
que prueban la herramienta ya injertada.

DONDE ENCAJA. `especificacion.py` decide QUE se va a construir; este modulo
escribe CON QUE codigo; `injertador.py` lo mete en los 5 sitios de la receta y
corre los guardianes. Este fichero no escribe en disco ni toca el CLI: devuelve
strings y las rutas donde deberian ir. La separacion es a proposito -- generar
es reversible y barato, injertar no.

LAS DOS DECISIONES QUE MANDAN EN ESTE FICHERO
---------------------------------------------
1. LA PLANTILLA ES EL CAMINO PRINCIPAL, NO EL PLAN B. El modelo local es un
   razonador (Qwen3.8-27B) y esta MEDIDO el 2026-08-30 que con presupuesto
   grande se va a razonar y NO EMITE NADA: 52.535 chars de razonamiento y CERO
   salida con 20.000 tokens. Ademas el techo real de generacion es n_ctx menos
   el prompt, no max_tokens. Asi que aqui el modelo solo puede MEJORAR un
   handler que ya existe y ya compila; si devuelve vacio, se corta o no pasa
   `validar_codigo`, se usa la plantilla y se dice en `avisos`. Un handler de
   plantilla que confiesa que una rama no esta implementada vale mas que uno
   inventado por un modelo que se corto a la mitad.

2. LA FUNCION DEL CLI NUNCA PUEDE LANZAR. La llama el bucle del REPL sin red
   debajo: una excepcion ahi se lleva por delante la sesion entera del duenio.
   Por eso `validar_codigo` no es un adorno de estilo -- rechaza el `raise` sin
   capturar, el `except` desnudo, el `except: pass` mudo y el import perezoso
   fuera de try/except. Son exactamente los cuatro caminos por los que una
   funcion de cli.py puede tumbar el REPL.

CONTRATO PUBLICO
    generar(espec, orch=None) -> dict con handler/modulo/ruta_modulo/tests/
                                 ruta_tests/via/avisos
    plantilla_handler(espec) -> str        (deterministico, sin modelo)
    validar_codigo(codigo, nombre) -> list (problemas; vacia = pasa)
"""

from __future__ import annotations

import ast
import logging
import re

from cognia.compilador import receta as rec

_log = logging.getLogger(__name__)

# ── Los helpers del CLI que el codigo generado PUEDE usar ────────────────────
#
# Lista CERRADA y comprobada con grep sobre cognia/cli.py el 2026-08-31:
#   _print_line (4334), _show_response (4365), _aviso_degradado (231),
#   _load_config (8453), _save_config (8462), _abrir_en_navegador (10953) y
#   _escape (267, `from rich.markup import escape as _escape`).
# Un handler que llame a un helper inventado importa bien y revienta EN
# CALIENTE la primera vez que el duenio teclea el comando -- que es el peor
# momento posible. Por eso el uso de un `_helper` que no este aqui es un
# problema de validacion, no un aviso.
HELPERS_CLI = (
    "_print_line",
    "_show_response",
    "_escape",
    "_aviso_degradado",
    "_load_config",
    "_save_config",
    "_abrir_en_navegador",
)

# Donde vive el modulo de apoyo de un comando generado. Es un subpaquete de
# namespace (sin __init__.py hace falta): quien escriba el fichero crea la
# carpeta y el import funciona igual en py3.
PAQUETE_APOYO = "cognia.compilador.generadas"
DIR_APOYO = "cognia/compilador/generadas"


# ── La frontera de seguridad, y POR QUE se mueve ─────────────────────────────
#
# cognia/agent/tool_synthesis._static_safety_scan existe y funciona, pero su
# allowlist esta hecha para tools PURAS: re, math, json, datetime... ni os, ni
# pathlib, ni subprocess. Aplicarla aqui tal cual rechazaria practicamente
# cualquier comando util, porque un comando del CLI existe justamente para
# TOCAR LA MAQUINA del duenio (leer un fichero, abrir el navegador, lanzar un
# proceso). Si el scan estatico prohibe eso, el compilador solo sabe fabricar
# comandos que no hacen nada.
#
# Asi que la frontera se mueve, y se mueve a un sitio concreto: lo que el scan
# sigue prohibiendo es la EJECUCION DINAMICA de codigo (eval/exec/compile/
# __import__) y los modulos que sirven para saltarse el propio scan
# (pickle/marshal/ctypes). El I/O y los procesos NO se juzgan aqui: los juzga
# el sandbox con timeout y, sobre todo, los GUARDIANES del injertador, que
# corren el codigo de verdad. Un scan estatico no puede distinguir un
# `subprocess.run(["git","status"])` legitimo de uno destructivo; ejecutarlo en
# un entorno controlado si. Prohibirlo en el scan solo consigue que el
# compilador sea inutil y que el duenio apague la comprobacion -- y un gate que
# no deja hacer nada acaba apagado.
_LO_QUE_UN_COMANDO_SI_NECESITA = frozenset({
    # de la blocklist de tool_synthesis, lo que un comando de verdad usa:
    "open",      # leer/escribir ficheros del duenio
    "input",     # preguntar s/n en el REPL (varios comandos ya lo hacen)
    "getattr", "setattr", "vars",   # introspeccion normal sobre config/objetos
})

# Modulos que no tienen uso legitimo en un comando del CLI y que ademas son el
# camino tipico para esquivar cualquier comprobacion estatica.
IMPORTS_PELIGROSOS = frozenset({
    "pickle", "marshal", "shelve", "ctypes", "cffi", "pty", "telnetlib",
    "ftplib", "smtplib", "winreg", "_winreg", "code", "codeop",
})

# Lo que un comando puede importar sin explicarse. Se parte de la allowlist de
# tool_synthesis (asi hereda las altas de aquel modulo) y se le suman los
# cuatro que el duenio pidio explicitamente -- os, pathlib, json, subprocess --
# mas la stdlib de andar por casa y el propio repo.
_EXTRA_ALLOWLIST = frozenset({
    "os", "pathlib", "json", "subprocess",
    "io", "sys", "time", "shutil", "tempfile", "csv", "glob", "platform",
    "webbrowser", "typing", "dataclasses", "argparse", "logging", "shlex",
    "sqlite3", "urllib", "http", "difflib", "uuid", "traceback", "contextlib",
    "enum", "copy", "warnings", "abc", "threading", "queue", "socket",
    "cognia", "rich", "pytest", "__future__",
})


def _imports_permitidos() -> frozenset:
    """La allowlist efectiva. Reusa la de tool_synthesis y la AMPLIA.

    Se importa dentro de la funcion (y no arriba) porque tool_synthesis
    arrastra el agente entero; y si no esta disponible se dice en el log en vez
    de callarselo, que es como se pierde una comprobacion sin enterarse.
    """
    base = set()
    try:
        from cognia.agent.tool_synthesis import _ALLOWED_IMPORTS as _base
        base = set(_base)
    except Exception as exc:
        _log.debug("tool_synthesis no importable (%s): sigo con la lista local "
                   "de este modulo, que ya cubre lo que necesita un comando",
                   exc)
        base = {"re", "math", "json", "datetime", "string", "random",
                "collections", "itertools", "functools", "textwrap",
                "unicodedata", "decimal", "statistics", "base64", "hashlib",
                "html"}
    return frozenset(base | set(_EXTRA_ALLOWLIST))


def _nombres_prohibidos() -> frozenset:
    """Nombres que no pueden aparecer NI referenciados (no solo llamados).

    Sale de la blocklist de tool_synthesis menos lo que un comando si necesita
    (ver _LO_QUE_UN_COMANDO_SI_NECESITA). Se mira la referencia y no solo la
    llamada porque `f = eval; f(x)` esquiva la comprobacion de llamadas: es la
    misma leccion que ya esta escrita en tool_synthesis, verificada alli el
    2026-07-03.
    """
    base = {"eval", "exec", "compile", "__import__", "globals", "locals",
            "breakpoint", "__builtins__"}
    try:
        from cognia.agent.tool_synthesis import _FORBIDDEN_NAMES as _base
        base |= set(_base)
    except Exception as exc:
        _log.debug("tool_synthesis no importable (%s): uso la blocklist local",
                   exc)
    return frozenset(base - _LO_QUE_UN_COMANDO_SI_NECESITA)


# ── Leer la Espec sin acoplarse a ella ───────────────────────────────────────
#
# La Espec vive en especificacion.py, que es un fichero HERMANO escrito en
# paralelo. Se lee por atributos y con alias en vez de importar el tipo por
# tres motivos: (1) el generador no necesita la clase, necesita los datos;
# (2) un import duro convierte un rename del vecino en un ImportError en el
# arranque del compilador; (3) asi los tests pueden pasar cualquier objeto con
# esos campos, que es como se inyectan dependencias en el resto del repo.
# Lo que NO se hace es adivinar en silencio: cada campo que falta y que hacia
# falta sale en `avisos`.

def _atr(espec, *nombres, defecto=None):
    for n in nombres:
        if hasattr(espec, n):
            v = getattr(espec, n)
            if v not in (None, ""):
                return v
        if isinstance(espec, dict) and n in espec and espec[n] not in (None, ""):
            return espec[n]
    return defecto


def _norm_sub(item) -> tuple:
    """(nombre, que_hace) de un subcomando venga como venga.

    Un subcomando puede llegar como str ('hoy'), como 'hoy: lo de hoy', como
    dict o como objeto con .nombre/.descripcion. Se normaliza aqui y no en cada
    plantilla para que el handler, el modulo y los tests hablen del MISMO
    nombre: un desajuste entre ellos da un comando que se despacha a una rama
    que no existe.
    """
    if isinstance(item, str):
        if ":" in item:
            cabeza, cola = item.split(":", 1)
            return _slug(cabeza), cola.strip()
        return _slug(item), ""
    if isinstance(item, dict):
        nom = item.get("nombre") or item.get("sub") or item.get("name") or ""
        que = item.get("que") or item.get("descripcion") or item.get("doc") or ""
        return _slug(nom), str(que).strip()
    nom = _atr(item, "nombre", "sub", "name", defecto="")
    que = _atr(item, "que", "descripcion", "doc", defecto="")
    return _slug(str(nom)), str(que).strip()


def _norm_criterio(item) -> tuple:
    """(entrada, espera) de un criterio de aceptacion.

    Un criterio dice 'si tecleo ESTO, la salida tiene que contener AQUELLO'.
    Se acepta un str con '->' o '=>' en medio, un dict, o un objeto con
    .entrada/.espera. Si no se puede sacar el 'espera', se devuelve vacio y el
    test generado se queda en la postcondicion honesta que si se puede
    comprobar (que la rama imprime algo), y se avisa.
    """
    if isinstance(item, str):
        for sep in ("->", "=>", "|"):
            if sep in item:
                a, b = item.split(sep, 1)
                return a.strip(), b.strip()
        return "", item.strip()
    if isinstance(item, dict):
        ent = (item.get("entrada") or item.get("arg") or item.get("dado")
               or item.get("cuando") or item.get("subcomando") or "")
        # 'invocacion' es la clave que USA especificacion._criterios, y no
        # estaba en la lista: el test generado llamaba al handler con cadena
        # VACIA para todos los criterios. Medido el 2026-08-31: el criterio del
        # subcomando inexistente ('/x zzz-inexistente' -> espera 'desconocido')
        # invocaba '/x' a secas, salia el estado por defecto y el test fallaba
        # con el handler perfectamente bien. El handler recibe el arg SIN el
        # nombre del comando, asi que hay que quitarselo.
        if not ent and item.get("invocacion"):
            inv = str(item.get("invocacion") or "").strip()
            partes = inv.split(None, 1)
            ent = partes[1] if (len(partes) > 1 and partes[0].startswith("/")) else ""
        esp = (item.get("espera") or item.get("esperado") or item.get("entonces")
               or item.get("contiene") or item.get("salida") or "")
        return str(ent).strip(), str(esp).strip()
    ent = _atr(item, "entrada", "arg", "dado", "cuando", "subcomando", defecto="")
    esp = _atr(item, "espera", "esperado", "entonces", "contiene", "salida",
               defecto="")
    return str(ent).strip(), str(esp).strip()


def _texto_seguro(txt, limite: int = 200) -> str:
    """Texto de la espec listo para METERSE DENTRO del codigo generado.

    Medido el 2026-08-31 sobre este mismo fichero: una descripcion con
    unas comillas TRIPLES, una comilla doble, un salto de linea o una barra
    invertida final producia un handler (y un modulo, y unos tests) que NO
    COMPILAN -- o sea el peor fallo posible de este generador, porque lo que no
    compila acaba dentro de cli.py y deja el producto sin arrancar. Y la espec
    la escribe un modelo o llega de un JSON: ese texto no es de fiar nunca.

    Se limpia lo minimo que hace falta para que el texto quepa igual en un
    literal de una linea que en un docstring:
      - la barra invertida se vuelve barra normal (rompe el literal y ademas
        inventa escapes: 'C:\\Users' -> \\U truncado);
      - saltos de linea y tabuladores se aplastan a un espacio;
      - las comillas dobles (y las triples) pasan a simples, que es lo unico
        que puede cerrar el literal o el docstring donde va metido.
    """
    t = str(txt or "").replace("\\", "/")
    t = " ".join(t.split())
    t = t.replace('"""', "'''").replace('"', "'")
    return t[:limite].strip()


def _slug(txt: str) -> str:
    """Un identificador Python valido a partir de texto libre."""
    txt = (txt or "").strip().lower().lstrip("/")
    txt = re.sub(r"[^a-z0-9_]+", "_", txt).strip("_")
    if txt and txt[0].isdigit():
        txt = "c_" + txt
    return txt


def _campos(espec) -> dict:
    """Todo lo que las plantillas necesitan, ya normalizado, + los avisos."""
    avisos = []
    cmd = str(_atr(espec, "cmd", "comando", defecto="") or "").strip()
    nombre = str(_atr(espec, "nombre", "funcion", defecto="") or "").strip()
    if not cmd and nombre:
        cmd = "/" + nombre.replace("_", "-")
    if not nombre and cmd:
        nombre = cmd.lstrip("/").replace("-", "_")
    nombre = _slug(nombre)
    if not cmd or not nombre:
        avisos.append("la espec no trae ni 'cmd' ni 'nombre': sin eso no hay "
                      "comando que generar")
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    # El cmd se mete en literales y en markup de rich en los tres ficheros
    # generados. Si trae una comilla o un corchete, lo generado no compila (o
    # pinta basura), asi que se limpia AQUI -- una sola vez, para que handler,
    # modulo y tests hablen del mismo nombre -- y se DICE si hubo que tocarlo.
    cmd_limpio = _sin_markup(_texto_seguro(cmd, 64))
    if cmd_limpio != cmd:
        avisos.append("el nombre del comando traia caracteres que no pueden ir "
                      "en el codigo generado: se usa %r en vez de %r"
                      % (cmd_limpio, cmd))
        cmd = cmd_limpio

    descripcion = _texto_seguro(_atr(espec, "descripcion", "desc", "resumen",
                                     "doc", defecto=""))
    if not descripcion:
        descripcion = "comando %s generado por el compilador de herramientas" % cmd
        avisos.append("la espec no trae descripcion: se pone una generica, y "
                      "ojo que la descripcion es la que decide la categoria de "
                      "/ayuda si no se declara a mano")

    subs, vistos = [], set()
    for item in (_atr(espec, "subcomandos", "subs", "acciones", defecto=[]) or []):
        nom, que = _norm_sub(item)
        if not nom or nom in vistos:
            continue
        vistos.add(nom)
        # `que` acaba en el docstring del handler y del modulo: mismo peligro
        # que la descripcion, misma limpieza.
        subs.append((nom, _texto_seguro(que, 120)))
    if not subs:
        avisos.append("la espec no declara subcomandos: el comando solo tendra "
                      "el estado por defecto")

    criterios = []
    for item in (_atr(espec, "criterios", "postcondiciones", "aceptacion",
                      defecto=[]) or []):
        ent, esp = _norm_criterio(item)
        if not ent and not esp:
            continue
        criterios.append((ent, esp))
    if not criterios:
        avisos.append("la espec no trae criterios: los tests generados solo "
                      "comprueban que cada rama imprime algo y que el handler "
                      "no lanza; eso es un examen flojo, pero es honesto")

    return {
        "cmd": cmd,
        "nombre": nombre,
        "descripcion": descripcion,
        "subs": subs,
        "criterios": criterios,
        "pasa_ai": bool(_atr(espec, "pasa_ai", "necesita_ai", defecto=False)),
        "cubo": str(_atr(espec, "cubo", defecto="AVANZADO")),
        "categoria": str(_atr(espec, "categoria", defecto="") or ""),
        "avisos": avisos,
    }


# ── La plantilla del handler ─────────────────────────────────────────────────

def plantilla_handler(espec) -> str:
    """El handler `_slash_<nombre>` DETERMINISTICO: sin modelo y sin sorpresas.

    Sigue el patron de la casa punto por punto (receta.RECETA_PROSA, sitio 2),
    que no es negociable porque el REPL depende de el: firma exacta, docstring
    con el punto de extension, import perezoso en try/except que degrada por
    _aviso_degradado y hace return, `arg = (arg or "").strip()`, una rama por
    subcomando, `Uso: ...` en el caso malo y el estado por defecto al final.

    Las ramas nacen SIN implementar y lo DICEN por pantalla. Esto es deliberado:
    la leccion del repo es que "no lo cablearon" y "se rompio" no pueden verse
    igual desde afuera. Un stub que se calla o que finge exito cuesta dias de
    diagnostico; uno que imprime "esta rama todavia no esta implementada" te
    dice la verdad la primera vez que lo tecleas.
    """
    d = _campos(espec)
    cmd, nombre = d["cmd"], d["nombre"]
    firma = ('def _slash_%s(arg: str = "", ai=None) -> None:' % nombre
             if d["pasa_ai"] else
             'def _slash_%s(arg: str = "") -> None:' % nombre)

    subs_txt = " | ".join(n for n, _ in d["subs"]) or "(ninguno)"
    # "subcomando desconocido" y NO solo "Uso: ..." (2026-08-31). Dos motivos,
    # y el segundo es el que manda: (a) es el patron de la casa -- el resto de
    # comandos del CLI nombran lo que no entendieron antes de dar el uso, y
    # decir solo el uso deja al duenio sin saber si es que tecleo mal o si el
    # comando no hace lo que creia; (b) es la POSTCONDICION que la espec pide
    # comprobar en toda herramienta compilada, porque una excepcion en esta
    # rama se lleva por delante el REPL entero. Medido: sin la palabra, toda
    # herramienta generada suspendia su tercer criterio con el codigo bien.
    uso = "subcomando desconocido. Uso: %s %s" % (
        cmd, " | ".join([n for n, _ in d["subs"]] + ["estado"]))

    L = [firma]
    L.append('    """`%s`: %s' % (cmd, d["descripcion"].rstrip(".") + "."))
    L.append("")
    if d["subs"]:
        L.append("    Subcomandos:")
        for nom, que in d["subs"]:
            L.append("      %s -- %s" % (nom, que or "(sin descripcion en la espec)"))
    else:
        L.append("    Sin subcomandos: solo el estado por defecto.")
    L.append("")
    L.append("    Sin argumentos (o 'estado'): que es el comando y como esta.")
    L.append("    PUNTO DE EXTENSION: %s/%s.py, dict ACCIONES. Cada subcomando"
             % (DIR_APOYO, nombre))
    L.append("    es una entrada de ese registry; aniadir uno es aniadir la")
    L.append("    funcion alli y su rama aqui. La logica NO vive en cli.py.")
    L.append('    """')
    L.append("    # Import PEREZOSO y blindado. Esta funcion la llama el bucle del")
    L.append("    # REPL sin red debajo: una excepcion aqui se lleva por delante la")
    L.append("    # sesion entera. Por eso todo fallo sale por _aviso_degradado y")
    L.append("    # return, y nunca por una excepcion que suba.")
    L.append("    try:")
    L.append("        from %s import %s as _mod" % (PAQUETE_APOYO, nombre))
    L.append("    except Exception as exc:")
    L.append('        _aviso_degradado("%s", f"modulo de apoyo no importable: {exc}")'
             % nombre)
    L.append("        return")
    L.append('    arg = (arg or "").strip()')
    L.append("    bajo = arg.lower()")
    L.append("")

    for nom, que in d["subs"]:
        L.append("    # %s" % (que or ("rama %s" % nom)))
        L.append('    if bajo == "%s" or bajo.startswith("%s "):' % (nom, nom))
        L.append('        resto = arg[len("%s"):].strip()' % nom)
        L.append("        try:")
        L.append('            res = _mod.ejecutar("%s", resto)' % nom)
        L.append("        except Exception as exc:")
        L.append('            _aviso_degradado("%s", f"%s fallo: {exc}")'
                 % (nombre, nom))
        L.append("            return")
        L.append('        mensaje = _escape(str(res.get("mensaje") or ""))')
        L.append('        if not res.get("implementado"):')
        L.append('            _print_line("[warn_cl]%s %s: " + mensaje + "[/warn_cl]")'
                 % (cmd, nom))
        L.append("            return")
        L.append("        _show_response(mensaje)")
        L.append("        return")
        L.append("")

    L.append("    # Argumento que no encaja en ninguna rama: se dice el uso y se")
    L.append("    # sale. Callarse aqui es lo que hace que un comando parezca roto.")
    L.append('    if bajo and bajo != "estado":')
    L.append('        _print_line("[warn_cl]%s[/warn_cl]")' % uso)
    L.append("        return")
    L.append("")
    L.append("    # Estado por defecto: sin argumentos el comando dice que es, que")
    L.append("    # subcomandos tiene y cuales estan implementados de verdad.")
    L.append("    try:")
    L.append("        est = _mod.estado()")
    L.append("    except Exception as exc:")
    L.append('        _aviso_degradado("%s", f"estado no disponible: {exc}")' % nombre)
    L.append("        return")
    L.append('    _print_line("[mod]%s[/mod] %s")' % (cmd, _sin_markup(d["descripcion"])))
    L.append("    for clave, valor in est.items():")
    L.append('        _print_line(f"  [mod]{clave:<20}[/mod] {_escape(str(valor))}")')
    L.append('    _print_line("[info_dim]subcomandos: %s[/info_dim]")' % subs_txt)
    return "\n".join(L) + "\n"


def _sin_markup(txt: str) -> str:
    """Texto seguro para meter DENTRO de un literal de markup de rich.

    Los corchetes abren tags en rich y las comillas dobles cierran el literal
    de Python: si la descripcion de la espec trae cualquiera de las dos, el
    handler generado no compila o pinta basura. Se limpia en el generador y no
    en el handler porque en el handler seria una llamada mas que puede fallar.
    """
    return (txt or "").replace('"', "'").replace("[", "(").replace("]", ")")


# ── La plantilla del modulo de apoyo ─────────────────────────────────────────

def plantilla_modulo(espec) -> str:
    """El modulo donde vive la logica: el punto de extension de verdad.

    Va aparte de cli.py por dos razones medidas en este repo: cli.py son 23.000
    lineas y todo lo que crece ahi es codigo que nadie prueba solo; y el
    injertador solo sabe INSERTAR bloques en cli.py, asi que cuanto menos
    codigo del comando viva alli, menos superficie tiene el injerto.
    """
    d = _campos(espec)
    nombre, cmd = d["nombre"], d["cmd"]

    L = ['"""']
    L.append("Modulo de apoyo de %s -- generado por cognia/compilador/generador.py." % cmd)
    L.append("")
    L.append("%s" % d["descripcion"])
    L.append("")
    L.append("POR QUE EXISTE. El handler del CLI (_slash_%s en cognia/cli.py)" % nombre)
    L.append("tiene que ser delgado y NO PUEDE LANZAR nunca, porque lo llama el bucle")
    L.append("del REPL. La logica de verdad vive aqui, donde si se puede probar sola.")
    L.append("")
    L.append("PUNTO DE EXTENSION: el dict ACCIONES. Cada subcomando es una funcion")
    L.append("`_<sub>(resto: str) -> dict` que devuelve")
    L.append('{"ok": bool, "implementado": bool, "mensaje": str}. Aniadir un')
    L.append("subcomando es aniadir la funcion, su entrada en ACCIONES y su rama en el")
    L.append("handler; nada mas.")
    L.append("")
    L.append("ESTADO: las ramas nacen SIN implementar y lo DICEN (implementado=False).")
    L.append("Un stub que finge exito cuesta dias de diagnostico; uno que confiesa te")
    L.append("lo dice la primera vez que tecleas el comando.")
    L.append('"""')
    L.append("")
    L.append("from __future__ import annotations")
    L.append("")
    L.append('NOMBRE = "%s"' % cmd)
    L.append("")
    L.append("# Subcomandos que YA estan implementados de verdad. Se actualiza a mano")
    L.append("# al implementar cada rama: es la unica fuente de esa verdad, y el")
    L.append("# estado del comando la saca por pantalla.")
    L.append("IMPLEMENTADOS = set()")
    L.append("")
    L.append("")

    for nom, que in d["subs"]:
        L.append("def _%s(resto: str = \"\") -> dict:" % nom)
        L.append('    """%s' % (que or ("subcomando %s de %s." % (nom, cmd))))
        L.append("")
        L.append("    TODO: sin implementar. Cuando lo implementes, devuelve")
        L.append('    implementado=True y aniade "%s" a IMPLEMENTADOS.' % nom)
        L.append('    """')
        # El mensaje se parte en dos literales adyacentes y no en una expresion
        # con parentesis: generar codigo con continuaciones es donde se cuela un
        # literal sin cerrar, y aqui ya paso una vez (SyntaxError en el modulo
        # generado el 2026-08-31, cazado por el smoke test antes de escribirlo).
        L.append('    return {"ok": False, "implementado": False,')
        L.append('            "mensaje": "la rama %s de %s todavia no esta '
                 'implementada"' % (nom, cmd))
        L.append('                       " (punto de extension: _%s en %s/%s.py)"}'
                 % (nom, DIR_APOYO, nombre))
        L.append("")
        L.append("")

    if d["subs"]:
        L.append("ACCIONES = {")
        for nom, _ in d["subs"]:
            L.append('    "%s": _%s,' % (nom, nom))
        L.append("}")
    else:
        L.append("# Sin subcomandos declarados en la espec: el registry nace vacio y")
        L.append("# ese es el sitio donde se aniade el primero.")
        L.append("ACCIONES = {}")
    L.append("")
    L.append("")
    L.append('def ejecutar(sub: str, resto: str = "") -> dict:')
    L.append('    """Despacha un subcomando. SIEMPRE devuelve dict, nunca lanza:')
    L.append("    el handler del CLI depende de eso para no tumbar el REPL.")
    L.append('    """')
    L.append("    fn = ACCIONES.get((sub or \"\").strip().lower())")
    L.append("    if fn is None:")
    L.append('        return {"ok": False, "implementado": False,')
    L.append('                "mensaje": "subcomando desconocido: %r" % sub}')
    L.append("    try:")
    L.append("        return fn(resto)")
    L.append("    except Exception as exc:")
    L.append("        # No se relanza: quien llama es el CLI. El error se DEVUELVE")
    L.append("        # con su tipo para que se vea, que no es lo mismo que callarlo.")
    L.append('        return {"ok": False, "implementado": True,')
    L.append('                "mensaje": "%s fallo: %s: %s" % (sub, type(exc).__name__, exc)}')
    L.append("")
    L.append("")
    L.append("def estado() -> dict:")
    L.append('    """Foto del comando para `%s estado`."""' % cmd)
    L.append("    pendientes = sorted(set(ACCIONES) - set(IMPLEMENTADOS))")
    L.append("    return {")
    L.append('        "comando": NOMBRE,')
    L.append('        "subcomandos": ", ".join(sorted(ACCIONES)) or "(ninguno)",')
    L.append('        "implementados": ", ".join(sorted(IMPLEMENTADOS)) or "(ninguno)",')
    L.append('        "sin implementar": ", ".join(pendientes) or "(ninguno)",')
    L.append('        "modulo": __name__,')
    L.append("    }")
    return "\n".join(L) + "\n"


# ── La plantilla de los tests de la herramienta ──────────────────────────────

def plantilla_tests(espec) -> str:
    """Los tests que prueban la herramienta YA INJERTADA, de verdad.

    Importan cognia.cli, llaman al handler con cada subcomando y miran la
    salida real con capsys. No hay `assert True` ni skip por entorno: un test
    que se salta solo no examina nada (leccion del repo: un skipif por env var
    dejo un test sin ejecutar NUNCA). Si el comando no esta injertado, estos
    tests FALLAN, que es exactamente lo que tienen que hacer.
    """
    d = _campos(espec)
    cmd, nombre = d["cmd"], d["nombre"]
    slug = _slug(nombre)

    L = ['"""']
    L.append("Tests de %s -- generados por cognia/compilador/generador.py." % cmd)
    L.append("")
    L.append("Prueban la herramienta DE VERDAD: importan el CLI ya injertado, llaman")
    L.append("al handler con cada subcomando y comprueban la salida real con capsys.")
    L.append("Si el comando no esta dado de alta en los 5 sitios de la receta, estos")
    L.append("tests fallan -- que es lo que tienen que hacer: un comando a medias es")
    L.append("el peor estado posible.")
    L.append('"""')
    L.append("")
    L.append("from cognia import cli")
    L.append("from cognia.compilador import receta as rec")
    L.append("")
    L.append("")
    L.append("def _handler():")
    L.append('    """El handler injertado. Sin skip: si no esta, es un fallo."""')
    L.append('    fn = getattr(cli, "_slash_%s", None)' % nombre)
    # Una sola linea: partir un literal generado entre dos L.append es donde se
    # cuela una comilla sin cerrar (ya paso el 2026-08-31 en este mismo fichero).
    L.append('    assert fn is not None, "cli.py no tiene _slash_%s: %s no esta '
             'injertado"' % (nombre, cmd))
    L.append("    return fn")
    L.append("")
    L.append("")
    L.append("def _salida(capsys) -> str:")
    L.append('    """La salida en UNA linea: rich parte las lineas segun el ancho de')
    L.append("    la consola, asi que buscar una subcadena en el texto crudo falla en")
    L.append("    una terminal estrecha y pasa en una ancha. Aplastar los espacios")
    L.append("    quita esa fuente de intermitencia.")
    L.append('    """')
    L.append('    return " ".join(capsys.readouterr().out.split())')
    L.append("")
    L.append("")
    L.append("def test_%s_esta_en_los_sitios_de_la_receta():" % slug)
    L.append('    """Puerta visible: sin esto el comando es un fantasma."""')
    L.append('    assert "%s" in rec.catalogo(), "no esta en _CMD_DESCRIPTIONS"' % cmd)
    L.append("    cubos = rec.cubos()")
    L.append('    donde = [k for k, v in cubos.items() if "%s" in v]' % cmd)
    L.append('    assert len(donde) == 1, ("tiene que estar en EXACTAMENTE un cubo '
             'y esta en %s" % donde)')
    L.append("")
    L.append("")
    L.append("def test_%s_estado_por_defecto_dice_algo(capsys):" % slug)
    L.append('    """Sin argumentos el comando tiene que contar que es y como esta."""')
    L.append('    _handler()("")')
    L.append("    out = _salida(capsys)")
    L.append('    assert out, "el estado por defecto no imprimio nada"')
    L.append('    assert "%s" in out, "el estado no nombra el comando"' % cmd)
    L.append("")
    L.append("")

    for nom, que in d["subs"]:
        L.append("def test_%s_sub_%s(capsys):" % (slug, nom))
        L.append('    """%s"""' % (que or ("la rama %s responde algo por pantalla."
                                           % nom)))
        L.append('    _handler()(%r)' % nom)
        L.append("    out = _salida(capsys)")
        L.append('    assert out, "la rama %s no imprimio nada: un stub mudo y uno '
                 'roto se ven igual"' % nom)
        L.append('    assert "%s" in out.lower(), "la salida no menciona el '
                 'subcomando"' % nom)
        L.append("")
        L.append("")

    L.append("def test_%s_argumento_desconocido_dice_el_uso(capsys):" % slug)
    L.append('    """El caso malo tiene que decir el uso, no callarse."""')
    L.append('    _handler()("zzz-argumento-que-no-existe")')
    L.append("    out = _salida(capsys).lower()")
    L.append('    assert "uso" in out, "un argumento invalido no saco el uso"')
    L.append("")
    L.append("")
    L.append("def test_%s_nunca_lanza():" % slug)
    L.append('    """La regla dura del CLI: una excepcion aqui tumba el REPL entero.')
    L.append("    Si alguna de estas llamadas lanza, el test falla -- que es")
    L.append("    justamente la sesion del duenio cayendose, pero en pytest.")
    L.append('    """')
    entradas = ['""', '"estado"', '"   "', '"basura con espacios"', '"--help"']
    entradas += ['%r' % n for n, _ in d["subs"]]
    L.append("    for entrada in (%s):" % ", ".join(entradas))
    L.append("        _handler()(entrada)")
    L.append("")

    for i, (ent, esp) in enumerate(d["criterios"], 1):
        L.append("")
        L.append("def test_%s_criterio_%d(capsys):" % (slug, i))
        # El criterio va DOS veces al fichero: al docstring (donde una comilla
        # doble, un salto de linea o una barra invertida lo parten -- medido el
        # 2026-08-31) y al assert, donde va con %r y NO se toca: ahi el texto
        # tiene que ser el que pidio el duenio, letra por letra.
        L.append('    """Criterio de la espec: %s"""'
                 % _texto_seguro("%s -> %s" % (ent or "(sin argumento)",
                                               esp or "(imprime algo)")))
        L.append("    _handler()(%r)" % ent)
        L.append("    out = _salida(capsys)")
        L.append('    assert out, "el criterio no produjo salida"')
        if esp:
            L.append("    assert %r.lower() in out.lower(), (" % esp)
            L.append('        "la salida no cumple el criterio: %s" % out[:200])')
        else:
            L.append("    # La espec no dice QUE tiene que salir, solo que salga: no")
            L.append("    # se inventa una postcondicion que no pidio nadie.")
        L.append("")
    return "\n".join(L) + "\n"


# ── La validacion ────────────────────────────────────────────────────────────

def validar_codigo(codigo, nombre) -> list:
    """Problemas del handler generado. Lista vacia = pasa.

    Comprueba, en este orden y por este motivo:
      1. compila (si no, el injertador dejaria cli.py con sintaxis rota);
      2. se llama `_slash_<nombre>` y empieza por esa def -- el injertador lo
         exige literalmente y ademas el despacho llama a ese nombre;
      3. tiene docstring (sitio 2 de la receta);
      4. ningun `except` desnudo ni `except ...: pass` mudo: 'no lo cablearon'
         y 'se rompio' no pueden verse igual desde afuera;
      5. ninguna excepcion que pueda ESCAPAR al REPL: ni un `raise` suelto en
         el handler, ni uno escondido en una funcion auxiliar a la que el
         handler llama sin protegerse, ni uno a nivel de modulo (ese sube al
         importar cli.py y se lleva el producto entero);
      6. ningun import perezoso fuera de try/except, por lo mismo;
      7. solo helpers del CLI que EXISTEN (HELPERS_CLI);
      8. sin ejecucion dinamica ni imports peligrosos (ver la nota sobre donde
         se pone la frontera, arriba en este fichero);
      9. que el handler IMPRIMA algo por algun camino: un comando mudo y uno
         roto se ven igual desde afuera, que es la unica cosa que este repo
         tiene prohibida.

    Los puntos 4, 5, 7 y 8 se miran sobre TODO el codigo, no solo sobre la
    funcion del handler: lo que devuelve el modelo (y lo que el injertador
    pega) puede traer funciones auxiliares y sentencias de modulo, y esas
    corren igual dentro de cli.py.
    """
    problemas = []
    codigo = codigo or ""
    nombre = _slug(str(nombre or ""))
    esperada = "_slash_%s" % nombre

    try:
        arbol = ast.parse(codigo)
    except SyntaxError as exc:
        return ["sintaxis rota en la linea %s: %s" % (exc.lineno, exc.msg)]

    if not codigo.strip().startswith("def %s(" % esperada):
        problemas.append("el handler tiene que empezar por 'def %s(' (el "
                         "injertador lo comprueba literalmente) y empieza por %r"
                         % (esperada, codigo.strip()[:48]))

    # AsyncFunctionDef entra en la lista a proposito: si el modelo devuelve
    # `async def _slash_x`, el handler NO sirve (el REPL lo llama sincrono),
    # pero el mensaje tiene que decir que la funcion esta ahi y es async, no
    # "no hay ninguna" -- un diagnostico que miente cuesta mas que el fallo.
    funcs = [n for n in arbol.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    fn = next((f for f in funcs
               if f.name == esperada and isinstance(f, ast.FunctionDef)), None)
    if fn is None:
        hay = ", ".join(("async def " if isinstance(f, ast.AsyncFunctionDef)
                         else "") + f.name for f in funcs)
        problemas.append("no hay ninguna funcion %s en el codigo (hay: %s)"
                         % (esperada, hay or "ninguna"))
        return problemas

    if not (fn.args.args and fn.args.args[0].arg == "arg"):
        problemas.append("el primer parametro tiene que llamarse 'arg': el "
                         "despacho del REPL lo pasa por posicion")
    if not ast.get_docstring(fn):
        problemas.append("sin docstring: la receta exige que diga que hace y "
                         "cual es el punto de extension")

    problemas += _problemas_excepciones(arbol)
    problemas += _problemas_raise(arbol, fn)
    problemas += _problemas_imports(arbol, codigo)
    problemas += _problemas_helpers(arbol)
    problemas += _problemas_peligrosos(arbol)
    problemas += _problemas_mudez(fn)
    return problemas


def _problemas_mudez(fn) -> list:
    """Un handler que no imprime por NINGUN camino no esta entregado.

    Es el fallo tipico de este repo -- el vacio silencioso -- y la validacion
    lo dejaba pasar: un handler del modelo con el cuerpo a medias (`if x: pass`)
    compilaba, cumplia la firma y entraba como via='modelo'. Desde fuera, un
    comando mudo y uno roto se ven igual.
    """
    for nodo in ast.walk(fn):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id in (HELPERS_CLI + ("print",))):
            return []
    return ["el handler no imprime por ningun camino (ni %s ni print): un "
            "comando mudo y uno roto se ven igual desde afuera"
            % ", ".join(HELPERS_CLI[:3])]


def _problemas_excepciones(arbol) -> list:
    """`except` desnudos y `except: pass` mudos en TODO el codigo generado.

    Se mira el arbol entero y no solo el handler: una funcion auxiliar con un
    `except: pass` se pega igual dentro de cli.py y se traga igual el fallo.
    """
    fuera = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ExceptHandler):
            continue
        linea = getattr(nodo, "lineno", "?")
        if nodo.type is None:
            fuera.append("except desnudo en la linea %s: se traga hasta "
                         "KeyboardInterrupt y no deja ver que fallo" % linea)
        cuerpo = [s for s in nodo.body
                  if not (isinstance(s, ast.Expr)
                          and isinstance(s.value, ast.Constant)
                          and isinstance(s.value.value, str))]
        mudo = all(isinstance(s, ast.Pass)
                   or (isinstance(s, ast.Expr)
                       and isinstance(s.value, ast.Constant)
                       and s.value.value is Ellipsis)
                   for s in cuerpo) if cuerpo else True
        if mudo:
            fuera.append("'except: pass' mudo en la linea %s: prohibido por "
                         "CLAUDE.md -- todo fallo pasa por _aviso_degradado"
                         % linea)
    return fuera


def _padres(raiz) -> dict:
    mapa = {}
    for nodo in ast.walk(raiz):
        for hijo in ast.iter_child_nodes(nodo):
            mapa[hijo] = nodo
    return mapa


_FUNCIONES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _captura_todo(try_nodo) -> bool:
    """True si ese try tiene un `except` que se queda con CUALQUIER excepcion."""
    for h in try_nodo.handlers:
        if h.type is None:
            return True
        if isinstance(h.type, ast.Name) and h.type.id in ("Exception",
                                                          "BaseException"):
            return True
        if isinstance(h.type, ast.Tuple) and any(
                isinstance(e, ast.Name) and e.id in ("Exception",
                                                     "BaseException")
                for e in h.type.elts):
            return True
    return False


def _protegido(nodo, mapa) -> bool:
    """True si `nodo` esta en el CUERPO de un try que captura todo.

    Se sube hasta el borde de su funcion y NO mas alla: un try de la funcion de
    fuera no captura lo que pasa dentro de un `def` anidado -- captura, como
    mucho, la LLAMADA a ese def, que se juzga aparte. Tampoco cuenta estar en
    el `except` ni en el `finally`: ahi la excepcion ya va subiendo.
    """
    actual = nodo
    while actual in mapa:
        padre = mapa[actual]
        if isinstance(padre, ast.Try) and actual in padre.body:
            if _captura_todo(padre):
                return True
        if isinstance(padre, _FUNCIONES):
            return False
        actual = padre
    return False


def _funcion_contenedora(nodo, mapa):
    """La funcion (o None, si es codigo de modulo) donde vive `nodo`."""
    actual = nodo
    while actual in mapa:
        padre = mapa[actual]
        if isinstance(padre, _FUNCIONES):
            return padre
        actual = padre
    return None


def _cuerpo_propio(f):
    """Los nodos de `f` SIN entrar en las funciones anidadas dentro de ella."""
    pila = list(f.body) if isinstance(f.body, list) else [f.body]
    while pila:
        n = pila.pop()
        yield n
        if isinstance(n, _FUNCIONES):
            continue
        pila.extend(ast.iter_child_nodes(n))


def _funciones_que_lanzan(arbol, mapa) -> set:
    """Nombres de las funciones del codigo desde las que PUEDE salir una
    excepcion: o porque tienen un raise suelto, o porque llaman a otra que si.

    Se itera a punto fijo porque la cadena encadena: _a llama a _b, que llama a
    _c, que lanza. Sin esto, meter el raise una funcion mas adentro bastaba
    para pasar la validacion -- que es exactamente el agujero medido el
    2026-08-31: un `def _comprobar(): raise ValueError(...)` llamado desde el
    handler pasaba la validacion y tumbaba el REPL al teclear el comando.
    """
    funcs = {}
    for n in ast.walk(arbol):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(n.name, n)
    lanzan = set()
    for _ in range(len(funcs) + 1):
        nuevas = set()
        for nom, f in funcs.items():
            if nom in lanzan:
                continue
            for n in _cuerpo_propio(f):
                if isinstance(n, ast.Raise) and not _protegido(n, mapa):
                    nuevas.add(nom)
                    break
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in lanzan and not _protegido(n, mapa)):
                    nuevas.add(nom)
                    break
        if not nuevas:
            break
        lanzan |= nuevas
    return lanzan


def _problemas_raise(arbol, fn) -> list:
    """Toda excepcion que pueda llegar al REPL. Se miran TRES sitios:

      1. el `raise` suelto dentro del handler (el caso obvio);
      2. la LLAMADA sin proteger, desde el handler, a una funcion del propio
         codigo que puede lanzar -- esconder el raise una funcion mas adentro
         no lo hace inofensivo: sigue subiendo por la pila hasta el REPL;
      3. el `raise` (o esa misma llamada) a nivel de MODULO: ese ni siquiera
         espera a que tecleen el comando, sube al importar cli.py y deja el
         producto entero sin arrancar.
    """
    mapa = _padres(arbol)
    lanzan = _funciones_que_lanzan(arbol, mapa)
    fuera = []
    for nodo in ast.walk(arbol):
        es_raise = isinstance(nodo, ast.Raise)
        es_llamada = (isinstance(nodo, ast.Call)
                      and isinstance(nodo.func, ast.Name)
                      and nodo.func.id in lanzan)
        if not (es_raise or es_llamada):
            continue
        cont = _funcion_contenedora(nodo, mapa)
        if cont is not None and cont is not fn:
            continue      # dentro de otra funcion: se juzga en su llamada
        if _protegido(nodo, mapa):
            continue
        linea = getattr(nodo, "lineno", "?")
        donde = ("" if cont is fn else
                 " (a nivel de modulo: sube al IMPORTAR cli.py)")
        if es_raise:
            fuera.append("raise sin capturar en la linea %s%s: una excepcion "
                         "que sube desde el handler se lleva por delante el "
                         "REPL" % (linea, donde))
        else:
            fuera.append("llamada sin proteger a %s() en la linea %s%s: esa "
                         "funcion lleva un raise sin capturar dentro, asi que "
                         "la excepcion sube igual y se lleva el REPL"
                         % (nodo.func.id, linea, donde))
    return fuera


def _problemas_imports(arbol, codigo) -> list:
    """Imports: fuera de try/except (mata el REPL) y fuera de la allowlist."""
    permitidos = _imports_permitidos()
    lineas = (codigo or "").splitlines()
    mapa = _padres(arbol)
    fuera = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Import, ast.ImportFrom)):
            continue
        modulos = ([a.name for a in nodo.names] if isinstance(nodo, ast.Import)
                   else [nodo.module or ""])
        linea = getattr(nodo, "lineno", 0)
        texto = lineas[linea - 1] if 0 < linea <= len(lineas) else ""
        justificado = "justificado" in texto.lower()

        # dentro de una funcion y no dentro de un try -> puede tumbar el REPL
        actual, en_try, en_funcion = nodo, False, False
        while actual in mapa:
            padre = mapa[actual]
            if isinstance(padre, ast.Try) and actual in padre.body:
                en_try = True
            if isinstance(padre, ast.FunctionDef):
                en_funcion = True
            actual = padre
        if en_funcion and not en_try:
            fuera.append("import perezoso fuera de try/except en la linea %s: "
                         "si el modulo no esta, la excepcion sube y tumba el "
                         "REPL" % linea)

        for mod in modulos:
            raiz = (mod or "").split(".")[0]
            if raiz in IMPORTS_PELIGROSOS:
                fuera.append("import peligroso en la linea %s: %s (sirve para "
                             "saltarse esta misma comprobacion)" % (linea, mod))
            elif raiz and raiz not in permitidos and not justificado:
                fuera.append("import fuera de la allowlist en la linea %s: %s "
                             "(si hace falta de verdad, la linea lleva un "
                             "comentario '# justificado: <motivo>')"
                             % (linea, mod))
    return fuera


def _nombres_ligados(arbol) -> set:
    """Todo nombre que el propio codigo define: no puede ser un helper del CLI."""
    ligados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ligados.add(nodo.name)
            for a in list(getattr(nodo, "args", None).args
                          if getattr(nodo, "args", None) else []):
                ligados.add(a.arg)
            args = getattr(nodo, "args", None)
            if args is not None:
                for a in (list(args.posonlyargs) + list(args.kwonlyargs)
                          + ([args.vararg] if args.vararg else [])
                          + ([args.kwarg] if args.kwarg else [])):
                    ligados.add(a.arg)
        elif isinstance(nodo, ast.Name) and isinstance(nodo.ctx, (ast.Store,
                                                                 ast.Del)):
            ligados.add(nodo.id)
        elif isinstance(nodo, ast.alias):
            ligados.add((nodo.asname or nodo.name).split(".")[0])
        elif isinstance(nodo, ast.ExceptHandler) and nodo.name:
            ligados.add(nodo.name)
        elif isinstance(nodo, (ast.Global, ast.Nonlocal)):
            ligados.update(nodo.names)
    return ligados


def _problemas_helpers(arbol) -> list:
    """Helpers del CLI inventados.

    Regla concreta: cualquier nombre que empiece por '_' , que el codigo NO
    defina ni importe, y que no este en HELPERS_CLI, solo puede venir del
    espacio de nombres de cli.py -- o sea, o existe alli o el comando revienta
    la primera vez que se teclea. Como la lista de los que existen esta
    comprobada con grep, lo que no esta en ella es inventado.
    """
    ligados = _nombres_ligados(arbol)
    fuera, vistos = [], set()
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Name) and isinstance(nodo.ctx, ast.Load)):
            continue
        n = nodo.id
        if not n.startswith("_") or n.startswith("__") or n in ligados:
            continue
        if n in HELPERS_CLI or n in vistos:
            continue
        vistos.add(n)
        fuera.append("helper del CLI inexistente en la linea %s: %s() no esta "
                     "en cli.py (los que hay: %s)"
                     % (getattr(nodo, "lineno", "?"), n, ", ".join(HELPERS_CLI)))
    return fuera


# Atributos que se LLAMAN igual que un prohibido pero no son el prohibido.
# `re.compile` es el caso que muerde: `re` esta en la allowlist justamente
# para que un comando pueda buscar en un texto, y sin esta excepcion el
# validador rechazaba `re.compile(...)` como "ejecucion dinamica de codigo".
# Un gate que prohibe el uso normal del modulo que el mismo permite importar
# es un gate que acaba apagado; y el peligro real (`builtins.compile`) sigue
# cazado, porque ahi el receptor no es `re`.
_ATRIBUTOS_QUE_NO_SON_LO_QUE_PARECEN = frozenset({
    ("re", "compile"), ("regex", "compile"), ("_re", "compile"),
})


def _problemas_peligrosos(arbol) -> list:
    prohibidos = _nombres_prohibidos()
    fuera = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Name) and nodo.id in prohibidos:
            fuera.append("nombre prohibido en la linea %s: %s (ejecucion "
                         "dinamica de codigo)"
                         % (getattr(nodo, "lineno", "?"), nodo.id))
        elif isinstance(nodo, ast.Attribute) and nodo.attr in prohibidos:
            receptor = nodo.value.id if isinstance(nodo.value, ast.Name) else ""
            if (receptor, nodo.attr) in _ATRIBUTOS_QUE_NO_SON_LO_QUE_PARECEN:
                continue
            fuera.append("atributo prohibido en la linea %s: .%s"
                         % (getattr(nodo, "lineno", "?"), nodo.attr))
    return fuera


# ── La via del modelo (acotada a proposito) ──────────────────────────────────

_PROMPT = """Mejora este comando del CLI de Cognia. Devuelve SOLO codigo Python.

Comando: %(cmd)s -- %(desc)s
Subcomandos: %(subs)s

Reglas (obligatorias):
- firma exacta: %(firma)s
- docstring corto que diga que hace
- imports dentro de try/except Exception as exc -> _aviso_degradado + return
- NUNCA raise, NUNCA except desnudo
- solo estos helpers: _print_line, _show_response, _escape, _aviso_degradado
- maximo %(lineas)d lineas

Responde el codigo entre ```python y ```, sin explicar nada.
"""

# Presupuesto CORTO a proposito. Medido el 2026-08-30 contra este mismo modelo:
# con 20.000 tokens de presupuesto genero 52.535 chars de razonamiento y CERO
# salida. Un techo bajo empuja al modelo a emitir; y si aun asi vuelve vacio,
# el camino de degradacion (la plantilla) ya esta escrito.
MAX_TOKENS = 700
TEMPERATURA = 0.2
MAX_LINEAS = 60


def _codigo_del_texto(texto: str) -> str:
    """Saca el bloque de codigo de la respuesta del modelo.

    Acepta con y sin valla: un razonador que se corta a menudo emite la valla
    de apertura y no la de cierre, y tirar esa respuesta entera por una valla
    que falta seria perder codigo que compila.
    """
    texto = texto or ""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.DOTALL)
    if m:
        return m.group(1).strip("\n")
    m = re.search(r"```(?:python)?\s*\n(.*)", texto, re.DOTALL)
    if m:
        return m.group(1).strip("\n")
    i = texto.find("def _slash_")
    return texto[i:].strip("\n") if i >= 0 else ""


def _handler_del_modelo(espec, orch, avisos) -> str:
    """Pide el handler al modelo. Devuelve "" en cuanto algo no cuadra.

    Todo camino de fallo escribe en `avisos`: la diferencia entre "no habia
    modelo", "el modelo devolvio vacio" y "el modelo devolvio codigo malo"
    tiene que verse desde fuera, porque las tres se arreglan distinto.
    """
    d = _campos(espec)
    firma = ('def _slash_%s(arg: str = "", ai=None) -> None:' % d["nombre"]
             if d["pasa_ai"] else
             'def _slash_%s(arg: str = "") -> None:' % d["nombre"])
    prompt = _PROMPT % {
        "cmd": d["cmd"],
        "desc": d["descripcion"][:200],
        "subs": ", ".join(n for n, _ in d["subs"]) or "(ninguno)",
        "firma": firma,
        "lineas": MAX_LINEAS,
    }
    try:
        resp = orch.infer(prompt, max_tokens=MAX_TOKENS, temperature=TEMPERATURA)
    except Exception as exc:
        avisos.append("el modelo fallo (%s: %s): handler de plantilla"
                      % (type(exc).__name__, exc))
        return ""
    texto = getattr(resp, "text", None)
    if texto is None:
        avisos.append("la respuesta del modelo no tiene .text (%s): handler de "
                      "plantilla" % type(resp).__name__)
        return ""
    if not str(texto).strip():
        avisos.append("el modelo devolvio VACIO (es el fallo medido del "
                      "razonador: se va a razonar y no emite): handler de "
                      "plantilla")
        return ""
    codigo = _codigo_del_texto(str(texto))
    if not codigo.strip():
        avisos.append("el modelo respondio pero sin bloque de codigo (%d chars "
                      "de prosa): handler de plantilla" % len(str(texto)))
        return ""
    problemas = validar_codigo(codigo, d["nombre"])
    if problemas:
        avisos.append("el handler del modelo no pasa la validacion (%s): "
                      "handler de plantilla" % "; ".join(problemas[:3]))
        return ""
    return codigo


# ── El contrato publico ──────────────────────────────────────────────────────

def generar(espec, orch=None) -> dict:
    """De la Espec al codigo. No escribe nada en disco: devuelve strings.

    `via` dice de donde salio el HANDLER: "modelo" solo si el modelo devolvio
    codigo que ademas paso `validar_codigo`; en cualquier otro caso
    "plantilla", y el motivo en `avisos`. El modulo de apoyo y los tests son
    SIEMPRE de plantilla: son estructura, no creatividad, y un modelo que se
    corta a la mitad de un fichero de tests deja un examen que no examina.
    """
    d = _campos(espec)
    avisos = list(d["avisos"])
    nombre = d["nombre"]

    handler, via = "", "plantilla"
    if orch is not None:
        handler = _handler_del_modelo(espec, orch, avisos)
        if handler:
            via = "modelo"
    else:
        avisos.append("sin orquestador: handler de plantilla (deterministico)")

    if not handler:
        handler = plantilla_handler(espec)
        via = "plantilla"
        problemas = validar_codigo(handler, nombre)
        if problemas:
            # No deberia pasar nunca: la plantilla esta cubierta por sus tests.
            # Si pasa, se dice -- callarlo aqui es entregar un comando roto.
            avisos.append("LA PLANTILLA NO SE VALIDA A SI MISMA (%s): revisar "
                          "generador.plantilla_handler" % "; ".join(problemas[:3]))

    # El nombre del comando se valida contra el catalogo REAL: colisiona por
    # nombre o por prefijo mucho antes de llegar al injertador, y ahi el
    # diagnostico ya es caro.
    try:
        ok_nombre, motivo = rec.validar_nombre(d["cmd"])
        if not ok_nombre:
            avisos.append("nombre rechazado por la receta: %s" % motivo)
        elif motivo:
            avisos.append(motivo)
    except Exception as exc:
        avisos.append("no pude validar el nombre contra el catalogo (%s: %s)"
                      % (type(exc).__name__, exc))

    return {
        "handler": handler,
        "modulo": plantilla_modulo(espec),
        "ruta_modulo": "%s/%s.py" % (DIR_APOYO, nombre),
        "tests": plantilla_tests(espec),
        "ruta_tests": "tests/test_cmd_%s.py" % nombre,
        "via": via,
        "avisos": avisos,
    }
