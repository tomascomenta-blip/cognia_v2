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
    despues(name, args, ctx, out, ok, exit_code=None) -> el texto final.

Un fallo de cualquier capa degrada a "no hacer nada" y deja pasar la llamada:
el agente tiene que seguir funcionando aunque el arnés se rompa entero.

LA UNICA EXCEPCION A ESA REGLA (P0-2, ESPEC agente largo seccion 14.1): `LibroCaido`.
El resto de las capas son mejoras (un checkpoint que no se guarda cuesta un
/deshacer); la MEMORIA no lo es. Si el LIBRO no pudo escribir, el ciclo
siguiente decidiria sobre un pasado incompleto sin enterarse -- disco lleno =
memoria apagada en silencio, y el fallo tipico de este sistema es el vacio
silencioso, no la excepcion. Por eso `_libro()` tiene envelope propio y su
excepcion tipada SUBE hasta `run_tool`, que la deja pasar a proposito.

`exit_code` (P0-1): el returncode REAL del proceso, o **None** cuando no hubo
ninguno (la herramienta no paso por el shell, o el sentinel la bloqueo).
**None no es 0.** Sin exit real un evento NO puede marcarse `origen=medido`.

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
  - offloading ........... EN EL CLI si (F3, 2026-08-23): el REPL propaga la
                           config 'offload' (default on) a COGNIA_OFFLOAD al
                           arrancar; embebido sigue opt-in por env/config
                           (offloading.activo()). NO se suma a `aci_trim`:
                           run_tool salta el trim cuando el output ya es el
                           preview del offloading — el doble truncado esta
                           MEDIDO como danino (el modelo edita con
                           SEARCH/REPLACE texto que nunca vio, baseline
                           2026-08-09). `COGNIA_OFFLOAD=0` lo apaga siempre.
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


def _tx_encendido() -> bool:
    """El flag TX leido de la MISMA fuente que el CLI y el driver.

    NO vale `_activo("COGNIA_TX")` a secas: el CLI enciende el subsistema
    guardando `tx_activo` en la config, y con el env sin poner esta funcion
    devolvia False mientras `/tx estado` decia ACTIVO. Resultado medido: la
    tarea abierta, el panel verde y CERO eventos en el LIBRO (7 -> 7 tras una
    llamada real a run_tool), sin un solo aviso -- el `return` iba antes de
    `_avisar_libro_ausente`. Ver `cognia/tx/flag.py`.

    El camino apagado sigue siendo un `os.environ.get`: solo cuando el env NO
    dice nada se consulta la config (una vez por proceso, cacheada), y ahi el
    import de `cognia.tx.flag` es barato -- el paquete solo trae `errores.py`.
    """
    crudo = os.environ.get("COGNIA_TX", "").strip().lower()
    if crudo:
        return crudo in ("1", "on", "true", "yes", "si")
    try:
        from cognia.tx.flag import activo as _flag_tx
        return _flag_tx()
    except Exception:
        return False


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
        # _root_actual() y NO la constante AGENT_WORKSPACE_ROOT: esa se fija al
        # IMPORTAR el modulo. Las tools escriben por _root_actual() (call-time),
        # asi que en un proceso largo que cambia COGNIA_AGENT_WORKSPACE o hace
        # os.chdir entre tareas —la campana los cambia LOS DOS por tarea en el
        # mismo proceso: scripts/campana_tareas.py:303-304— el checkpoint se
        # registraba en el workspace VIEJO mientras la escritura ocurria en el
        # nuevo: la escritura quedaba SIN RED y /deshacer restauraba un fichero
        # que nadie habia tocado. Es exactamente el bug que dev_tools ya cazo en
        # 2026-07-21 y documenta en _root_actual() ("6 tareas de agente
        # escribieron todas en la carpeta de la primera").
        from cognia.agents.workers import dev_tools
        raiz = dev_tools._root_actual()
        if raiz:
            return Path(str(raiz))
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
    """El contenido actual del fichero, o None si no existe/no es texto utf-8.

    Este valor es LO UNICO que ve `checkpoints.registrar` sobre el estado previo,
    y su unico criterio para decidir si el respaldo sirve. Por eso lee con el
    MISMO lector que usa el almacen (`checkpoints._leer_exacto`: utf-8 estricto,
    newline='') en vez de con `errors='replace'`.

    POR QUE (2026-08-13): con `errors='replace'` un fichero latin-1 devolvia
    texto NO vacio lleno de U+FFFD. `registrar` cree al llamador cuando manda
    contenido no vacio, asi que su defensa (releer el disco y marcar
    'no_versionado' cuando no es utf-8) no reponia nada: el blob se guardaba ya
    CORRUPTO y con estado='guardado'. /deshacer escribia esos U+FFFD ENCIMA del
    fichero original —destruyendo los acentos de verdad— y contestaba
    "restaurado". Devolviendo None, `registrar` marca 'no_versionado' y
    /deshacer AVISA de que no restauro nada, que es la unica respuesta honesta:
    mejor no restaurar que restaurar basura (LIMITES DECLARADOS de
    checkpoints.py).
    """
    try:
        if not ruta.is_file():
            return None
        from cognia.harness.checkpoints import _leer_exacto
        return _leer_exacto(ruta)
    except Exception:
        # Ni siquiera se pudo importar el almacen: mismo criterio, a mano.
        try:
            return ruta.read_bytes().decode("utf-8")
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

    # 0) RAMA ESPECULATIVA (multiverso, 2026-08-19) — dentro de una rama que
    # puede perder, lo IRREVERSIBLE no se ejecuta: se veta y se encola para
    # correr UNA vez, en el mundo real, si la rama gana. Va primero porque es la
    # unica comprobacion cuyo fallo es irreparable: si un push se escapa, no hay
    # checkpoint ni hook que lo arregle.
    try:
        from cognia.multiverso import ramas as _ramas
        _veto_rama = _ramas.veto_activo(name, args)
        if _veto_rama:
            return _veto_rama
    except Exception:
        pass

    # 0.5) SISTEMA INMUNE — anticuerpos ejecutables derivados de fallos ya
    # atribuidos por la autopsia causal. Un anticuerpo NO es una leccion en
    # prosa: es un chequeo determinista que veta la accion que reprodujo el
    # fallo, y solo se activa tras aprobar un examen con casos sanos. Con cero
    # anticuerpos registrados esto cuesta una lectura de lista vacia.
    # COGNIA_INMUNE=0 lo apaga.
    if os.environ.get("COGNIA_INMUNE", "1").strip().lower() not in ("0", "off", "false", "no"):
        try:
            from cognia.inmune import anticuerpos as _inm
            _v = _inm.evaluar(name, args, ctx)
            if _v and _v.get("veto"):
                return _v.get("mensaje") or (
                    "BLOQUEADO por un anticuerpo del sistema inmune: esta "
                    "accion reprodujo un fallo ya diagnosticado.")
        except Exception:
            pass

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
            ruta = Path(destino)
            if not ruta.is_absolute():
                ruta = raiz_proyecto(ctx) / ruta
            previo = _leer_previo(ruta)
            # El previo se guarda TAMBIEN en ctx (2026-09-04): la reversion
            # por sintaxis (harness/reversion_sintaxis, lint diferencial de
            # SWE-agent) lo compara con lo que quede en disco tras el edit,
            # y no puede depender de que el almacen de checkpoints haya
            # funcionado (disco lleno = sin checkpoint, pero el previo esta).
            ctx["_harness_previo"] = {"ruta": str(ruta), "contenido": previo,
                                      "tool": name}
            from cognia.harness import checkpoints
            entrada = checkpoints.registrar(ruta, previo, motivo=name)
            ctx["_harness_checkpoint"] = entrada
        except Exception:
            pass
    return None


def despues(name: str, args: str, ctx: dict, out: str, ok: bool,
            exit_code=None) -> str:
    """Todo lo que pasa DESPUES. Devuelve el texto final para el modelo.

    `exit_code` es opcional y por defecto None para no romper a los llamadores
    viejos (la firma de 5 argumentos sigue siendo valida).
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    texto = out if isinstance(out, str) else str(out)

    # 0) LIBRO (P0-2) -- va PRIMERO y con envelope propio: la constancia se deja
    #    antes de que ninguna capa opcional pueda reventar y saltarse el resto.
    #    Es la unica linea de `despues` que puede lanzar.
    _libro(name, args, ctx, texto, ok, exit_code)

    # 1) VERIFICACIÓN de lo que se acaba de escribir (sintaxis siempre; tests
    #    sólo con COGNIA_AUTO_TESTS=1). Sólo si la herramienta dijo que fue bien:
    #    verificar un fichero que no se llegó a escribir sería ruido.
    destino = ruta_destino(name, args)
    # 0.5) REVERSION POR SINTAXIS NUEVA (2026-09-04, lint diferencial de
    #      SWE-agent): un editar_archivo que deja sin parsear un .py/.json que
    #      parseaba se deshace AQUI, antes de verificar, y el texto lo dice.
    #      Va antes del paso 1 para que la verificacion vea el disco ya
    #      restaurado (y calle) en vez de repetir el error que se acaba de
    #      explicar. Degrada avisando por log, nunca convierte ok en error.
    if ok and destino and name == "editar_archivo":
        try:
            from cognia.harness import reversion_sintaxis
            texto = reversion_sintaxis.aplicar(name, destino, ctx, texto)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "interceptor.reversion_sintaxis degradado: %s: %s",
                exc.__class__.__name__, exc)
    if ok and destino and name != "borrar_archivo":
        veredicto = _verificar(destino, ctx)
        if veredicto:
            texto = f"{texto}\n{veredicto}"

    # 1.5) CONTENIDO EXTERNO (2026-09-04, hermes make_tool_result_message):
    #      lo que devuelven buscar/http_get/mcp_*/navegador_* es texto ajeno
    #      y viaja envuelto en <contenido_externo> con la guia "datos, no
    #      instrucciones". Antes del offloading para que la cabecera y la
    #      guia queden en la cabeza que el preview conserva.
    try:
        from cognia.harness import contenido_externo
        texto = contenido_externo.envolver(name, texto)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "interceptor.contenido_externo degradado: %s: %s",
            exc.__class__.__name__, exc)

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

    # 3) OFFLOADING de salidas gigantes (F3): preview cabeza+cola + referencia
    #    con handle, ruta y bytes exactos. El flag lo lee offloading.activo()
    #    (env COGNIA_OFFLOAD > config 'offload' de /offload) y NO `_activo` a
    #    secas: leer solo el env aqui repetiria el bug del flag TX (config
    #    verde, subsistema muerto). La resiliencia vive DENTRO de
    #    formatear_observacion: si el disco falla conserva el inline truncado
    #    y avisa degradado — nunca convierte una tool exitosa en error.
    #    EXENTAS_OFFLOAD (hoy: `recuperar`): la salida de la propia via de
    #    recuperacion ya viene capada por _FACTOR_MAX_BYTES; re-offloadearla
    #    anidaba spills (handle sobre handle) y el modelo nunca podia ver el
    #    trozo que pidio — el contrato RESTAURABLE quedaba irrestaurable.
    try:
        from cognia.harness import offloading
        if name not in offloading.EXENTAS_OFFLOAD and offloading.activo():
            texto = offloading.formatear_observacion(texto, tool=name, args=args)
    except Exception as exc:
        # No hay _aviso_degradado importable aqui sin arrastrar el CLI; el
        # modulo de offloading ya avisa sus propios fallos. Esto solo cubre
        # el import roto, y lo dice en vez de callar.
        import logging
        logging.getLogger(__name__).warning(
            "interceptor.offloading degradado: %s: %s",
            exc.__class__.__name__, exc)

    # 4) RECORDATORIO DE REPETICION (harness/repeticion, advisory): va el
    #    ULTIMO a proposito — despues del offloading, para que el recordatorio
    #    no se vaya a disco con la salida grande, y al FINAL del texto, que es
    #    lo que aci_trim conserva (cabeza+cola) y lo ultimo que lee el modelo
    #    antes de decidir. Cuenta tambien las fallidas (`ok` va en la
    #    telemetria). Nunca lanza, nunca veta.
    texto = _recordatorio_repeticion(name, args, ctx, texto, ok)
    return texto


def vetado(name: str, args: str, ctx: dict, texto: str) -> str:
    """Lo que ve el modelo cuando `antes` VETO la llamada. Una llamada
    denegada tambien cuenta como repeticion (repetir un veto identico es el
    bucle mas tonto y mas frecuente), asi que pasa por el mismo recordatorio.
    Nunca lanza."""
    return _recordatorio_repeticion(name, args, ctx, texto, False)


def _recordatorio_repeticion(name, args, ctx, texto, ok) -> str:
    try:
        from cognia.harness import repeticion
        return repeticion.anexar(name, args, ctx, texto, ok=ok)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "interceptor.repeticion degradado: %s: %s",
            exc.__class__.__name__, exc)
        return texto


# ======================================================================
# LIBRO -- el enganche de la memoria append-only (P0-2, ESPEC seccion 14.1)
# ======================================================================
# QUE HAY AQUI HOY: el CONTRATO y el HUECO. El almacen (`cognia/tx/libro.py`)
# lo escribe el bloque M1. Mientras no exista, esto cuesta un `_activo()` con
# COGNIA_TX apagado y ni siquiera importa el paquete.
#
# Lo que NO hace: no juzga, no pide nada a un LLM, y el modelo no rellena un
# solo campo de la provenance. Todos los campos salen de la maquina.

# `conf = f(origen)` (ESPEC seccion 3.3). Funcion PURA de una tabla cerrada: si la
# confianza la emitiera el mismo modelo cuyo juicio esta en el azar (0,517
# medido), el resultado serian hechos falsos con etiqueta creible.
_CONF_POR_ORIGEN = {
    "usuario": 1.00,
    "medido": 1.00,
    "citado": 0.90,
    "derivado": 1.00,
    "modelo": 0.30,      # techo DURO. No asciende por repeticion. Jamas.
}


def _sha14(dato) -> str:
    """sha256[:14] de un texto o de bytes. El formato del LIBRO (ESPEC seccion 3.2)."""
    import hashlib
    if isinstance(dato, str):
        dato = dato.encode("utf-8", "replace")
    return hashlib.sha256(dato or b"").hexdigest()[:14]


def _clave_canonica(name: str, args: str, exit_code, destino: str) -> tuple:
    """(clave, valor) de la ESPEC 3.4, delegando en `cognia.tx.claves`.

    ANTES ESTABA CABLEADO A MANO como `clave='cmd:'+name` y eso vaciaba DOS
    gates (medido 2026-08-19):
      - la clave era el nombre de la TOOL ('cmd:ejecutar'), no el comando, asi
        que todas las llamadas a `ejecutar` caian en la misma clave con exits
        distintos; y `claves.canonica` -- la unica funcion que produce
        'archivo:<ruta>' y 'test:<args>' -- NO LA LLAMABA NADIE.
      - sin 'archivo:', la banda A quedaba vacia y G3 devolvia verde
        'artefactos 0/0' en los 500 commits de una tarea que escribio 40
        ficheros. El unico sitio del repo que escribia banda 'A' era el propio
        drill `/tx mutar`, que se sembraba su testigo para salir 3/3.
    Si el import de TX falla, se degrada a la forma vieja Y SE DICE.
    """
    try:
        from cognia.tx import claves as _claves
        return _claves.canonica(name, args, None, exit_code=exit_code,
                                ruta_destino=destino)
    except Exception as exc:
        _avisar_claves_degradadas(exc)
        medido = isinstance(exit_code, int) and not isinstance(exit_code, bool)
        return ("cmd:" + str(name), exit_code if medido else None)


_CLAVES_AVISADO = []


def _avisar_claves_degradadas(exc: BaseException) -> None:
    if _CLAVES_AVISADO:
        return
    _CLAVES_AVISADO.append(1)
    import sys
    print("[degradado] tx.claves: no pude canonizar la clave (%s: %s); las "
          "filas van con la forma vieja 'cmd:<tool>' y G3 no vera artefactos"
          % (type(exc).__name__, exc), file=sys.stderr)


def envelope(name: str, args: str, ctx: dict, out: str, ok: bool,
             exit_code=None) -> dict:
    """La provenance de UNA llamada a tool. Funcion pura salvo por `_sha14`.

    Se separa de `_libro` para poder testearla sin tocar disco ni encender el
    subsistema, que es como se caza que `origen` se degrade cuando debe.

    LA REGLA QUE JUSTIFICA TODO P0-1: `origen='medido'` SOLO con un exit code
    entero de verdad. Con `exit_code=None` (bloqueado, timeout, o una tool que
    no es shell) el origen baja a 'derivado' y `prov.tipo` deja de ser
    'ejecutada'. Sin eso, `origen=medido` y `conf=1,00` son etiquetas creibles
    sobre datos inventados: exactamente el fallo que este diseno previene.

    LA EXCEPCION, Y POR QUE NO ROMPE LA REGLA: una tool que ESCRIBIO un fichero
    produce una fila `archivo:<ruta>` cuyo valor es el sha256 que la maquina
    acaba de leer DEL DISCO. Ahi no hay exit code que exigir -- el dato medido
    es el sha, y es tan de la maquina como un returncode. Si el fichero no se
    puede leer (la escritura fallo, o era un borrado) no se inventa nada: se
    cae a la fila `cmd:` de siempre con `valor=None`.
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    texto = out if isinstance(out, str) else str(out)
    crudo = texto.encode("utf-8", "replace")
    medido = isinstance(exit_code, int) and not isinstance(exit_code, bool)
    # ABSOLUTA contra la raiz del proyecto, y no la ruta cruda del argumento:
    # el sha lo lee este proceso (con SU cwd) y lo re-lee G3 contra el
    # WORKSPACE de la tarea. Con la ruta relativa, los dos podian estar
    # hasheando ficheros homonimos de carpetas distintas -- el mismo bug que
    # P0-3 arreglo en GoalContract, ahora en la banda A.
    destino = ruta_destino(name, args)
    fallo_ruta = ""
    if destino:
        try:
            _p = Path(destino)
            if not _p.is_absolute():
                _p = raiz_proyecto(ctx) / _p
            destino = str(_p)
        except Exception as exc:
            # No se traga: la ruta se queda RELATIVA y eso cambia contra que
            # hashea G3. Queda dicho dentro de la propia provenance.
            fallo_ruta = "%s: %s" % (type(exc).__name__, exc)
    prov = {
        "tipo": "ejecutada" if medido else "derivada",
        "cmd": name,
        "args_sha": _sha14(args or ""),
        "cwd": str(raiz_proyecto(ctx)),
        "salida_sha": _sha14(crudo),
        "salida_bytes": len(crudo),
        "cola": texto[-160:],
    }
    if fallo_ruta:
        prov["ruta_sin_resolver"] = fallo_ruta
    if medido:
        prov["exit_code"] = exit_code
    else:
        # Se dice POR QUE no hay exit, en vez de omitirlo: "no se cableo" y "se
        # bloqueo" piden decisiones opuestas y desde fuera se ven igual.
        prov["fn"] = "interceptor.envelope"
        prov["base"] = ["exit_code:None"]
        prov["sin_exit"] = True
    origen = "medido" if medido else "derivado"
    # Para una tool de escritura, la clave la define la RUTA, no el contenido:
    # `canonica` corta los args a 120 chars y con el cuerpo del fichero dentro
    # la clave de dos escrituras al mismo sitio sale distinta (y encima mete
    # trozos de codigo en la memoria). `destino if ok else ""` porque una
    # escritura que fallo no produjo artefacto: se queda como fila `cmd:`.
    clave, valor = _clave_canonica(name, destino or args, exit_code,
                                   destino if ok else "")
    ev = {
        "t": "comando",
        "op": "add",
        "quien": "harness",
        "origen": origen,
        "conf": _CONF_POR_ORIGEN[origen],
        "ok": bool(ok),
        "exit_code": exit_code,          # None NO es 0. Se propaga tal cual.
        "clave": clave,
        "valor": valor,
        "ruta_destino": destino,
        "texto": texto[:400],
        "prov": prov,
    }
    if str(clave).startswith("archivo:") and valor is not None:
        # ARTEFACTO: banda A, y el ID SALE DE LA RUTA, no del contador de
        # eventos. Con un id nuevo por escritura, el fold dejaria vivas TODAS
        # las versiones y G3 re-hashearia el disco contra el sha VIEJO: rojo
        # para siempre a la segunda edicion del mismo fichero. Con `amend` y un
        # id estable hay UNA fila viva por fichero, en su sitio original (el
        # fold conserva la posicion del primer add), y G3 solo suspende cuando
        # alguien toca el fichero POR FUERA del agente -- que es la C1 de la
        # ESPEC 7.6 y para lo que existe el gate.
        ev["t"] = "fichero"
        ev["op"] = "amend"
        ev["banda"] = "A"
        ev["id"] = "A-" + _sha14(str(clave))[:8]
        ev["origen"] = "medido"
        ev["conf"] = _CONF_POR_ORIGEN["medido"]
        ev["estado"] = "verificado"
        prov["tipo"] = "ejecutada"
        prov["fn"] = "claves.sha_de_fichero"
        prov["sha_disco"] = valor
        prov.pop("sin_exit", None)
        prov.pop("base", None)
    return ev


def _libro(name: str, args: str, ctx: dict, out: str, ok: bool,
           exit_code=None) -> None:
    """Deja constancia de la llamada en el LIBRO. OPT-IN: COGNIA_TX=1.

    ENVELOPE PROPIO, distinto del resto del modulo: aqui un fallo NO degrada a
    "no hacer nada". Sube como `LibroCaido` y para el ciclo.

    Los tres estados posibles, y ninguno se confunde con otro:
      - COGNIA_TX apagado ......... no-op absoluto (ni se importa el paquete).
      - encendido y sin `tx/libro` . no-op ANUNCIADO una vez por proceso: el
        almacen todavia no esta construido, que no es lo mismo que roto.
      - encendido y con `tx/libro` . escribe; si no puede, LibroCaido.
    """
    if not _tx_encendido():
        return
    # find_spec y no un try/ImportError: un ImportError DENTRO de libro.py (una
    # dependencia rota) se veria identico a "el fichero no esta", y son los dos
    # estados que este bloque existe para separar.
    try:
        import importlib.util
        hay = importlib.util.find_spec("cognia.tx.libro") is not None
    except Exception:
        hay = False
    if not hay:
        _avisar_libro_ausente()
        return
    try:
        from cognia.tx import libro as _almacen
    except Exception as exc:
        # El fichero existe pero no importa (sintaxis rota, dependencia): eso
        # SI es una averia, no un hueco pendiente.
        raise _caido("no pude importar cognia.tx.libro", exc)
    try:
        evento = envelope(name, args, ctx, out, ok, exit_code)
    except Exception as exc:
        raise _caido("no pude armar la provenance de '%s'" % name, exc)
    try:
        _almacen.registrar_tool(evento, ctx=ctx)
    except Exception as exc:
        if _es_libro_caido(exc):
            raise                        # ya viene tipada del almacen
        raise _caido("no pude escribir el evento de '%s'" % name, exc)


_LIBRO_AVISADO = []


def _avisar_libro_ausente() -> None:
    """UNA vez por proceso, y por el canal visible. Un subsistema encendido que
    no hace nada tiene que decirlo: 'no lo cablearon' y 'se rompio' no pueden
    verse iguales desde fuera."""
    if _LIBRO_AVISADO:
        return
    _LIBRO_AVISADO.append(1)
    motivo = ("COGNIA_TX=1 pero cognia/tx/libro.py todavia no existe (bloque "
              "M1 de la ESPEC): NO se esta escribiendo memoria")
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado("tx.libro", motivo)
    except Exception:
        import sys
        print("[degradado] tx.libro: " + motivo, file=sys.stderr)


def _caido(motivo: str, causa: BaseException):
    """La excepcion tipada, o un RuntimeError si ni el paquete TX se importa
    (sin el no hay nada que parar, pero tampoco se calla)."""
    try:
        from cognia.tx.errores import LibroCaido
    except Exception:
        return RuntimeError("LIBRO CAIDO: %s (%s: %s)"
                            % (motivo, type(causa).__name__, causa))
    return LibroCaido(motivo, causa)


def _es_libro_caido(exc: BaseException) -> bool:
    try:
        from cognia.tx.errores import LibroCaido
    except Exception:
        return False
    return isinstance(exc, LibroCaido)


def _spec(name: str) -> dict:
    """El spec del registry para `name`, o {} si no se puede consultar."""
    try:
        from cognia.agent.tools import TOOLS
        return TOOLS.get(name) or {}
    except Exception:
        return {}


def _verificar(destino: str, ctx: dict) -> str:
    """El bloque RESULTADO de la verificación, o '' si no aplica.

    Sólo mira ficheros que sabemos verificar y que existen tras la escritura.

    EL SILENCIO ES AMBIGUO Y ESO COSTABA CARO (2026-08-18). Antes, cualquier
    excepción de la capa de verificación devolvía '' — y '' YA significaba
    "verificado y todo bien". Un ImportError, un fichero bloqueado o un pytest
    que no arranca se le presentaban al agente EXACTAMENTE igual que un visto
    bueno, y el agente seguía construyendo encima. Un fallo del instrumento no
    puede leerse como aprobación del sujeto: ahora se dice.
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
    except Exception as exc:
        return (f"RESULTADO: no pude verificar {destino} "
                f"({type(exc).__name__}: {exc}). El fichero se escribió, pero "
                f"NADIE comprobó que sea válido.")
