"""
cognia/flujos/reproductor.py
============================
QUE RESUELVE: ejecuta un FLUJO parametrizado (el que produce
cognia/flujos/generalizador.py) contra el registry de tools REAL, liga sus
parametros, verifica sus postcondiciones EN DISCO y devuelve un informe con el
coste, para poder compararlo contra hacer la misma tarea con el agente.

POR QUE EXISTE: un flujo aprendido solo vale si alguien lo vuelve a correr y
COMPRUEBA que hizo lo que decia. La leccion medida de este repo es que las
skills auto-capturadas ENVENENARON tareas ajenas (una traza de atasco ascendida
a "procedimiento verificado" bajo el camino feliz de 5/5 a 2-4/5). La defensa no
es una nota en prosa: es este modulo, que corre el flujo y lo somete a un examen
EJECUTABLE (fichero_existe / fichero_contiene / comando_exit0). Nada aprendido
deberia quedar activo sin pasar por aqui.

FORMA DEL FLUJO (contrato con el generalizador):

    {
      "nombre": "publicar_modulo",
      "params": ["ruta"] | [{"nombre": "ruta", "obligatorio": True,
                             "default": None, "descripcion": "..."}],
      "pasos": [
         {"tool": "escribir_archivo", "args_plantilla": "{ruta} | hola"},
         {"tipo": "modelo", "instruccion": "resume {ruta} en 3 lineas"},
      ],
      "postcondiciones": [
         {"tipo": "fichero_existe",  "ruta": "{ruta}"},
         {"tipo": "fichero_contiene","ruta": "{ruta}", "texto": "hola"},
         {"tipo": "comando_exit0",   "comando": "python -m pytest -q"},
      ],
    }

TODO SE INYECTA (run_tool_fn, agente_fn, ejecutar_fn, print_fn) para poder
probar el modulo entero en seco: sin modelo, sin red y sin tocar el registry.

REGLAS DURAS QUE CUMPLE:
- ``ligar`` falla RUIDOSO (envelope con ok=False y el motivo): un flujo a medio
  ligar que se ejecuta es peor que uno que no corre.
- ``reproducir`` NUNCA lanza: devuelve el informe con el fallo dentro. Un fallo
  que devuelve None es invisible; aqui el fallo viaja en el envelope.
- Las postcondiciones se comprueban leyendo el DISCO y, cuando hace falta,
  EJECUTANDO lo que quedo escrito. JAMAS contra el texto que devolvio un modelo.

Solo stdlib. Funciones planas y dicts.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

# Un marcador es {identificador}. NO se usa str.format a proposito: los args de
# las tools llevan JSON, f-strings y llaves de codigo ('{"a": 1}', '{x}') y
# format() reventaria o comeria esas llaves. Con un regex de identificador solo
# tocamos lo que parece un parametro, y {{ }} escapa una llave literal.
_MARCADOR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ESC_ABRE = "\x00"
_ESC_CIERRA = "\x01"

# Recorte del resultado que entra en el informe. El informe se imprime, se
# guarda en journal y se compara entre corridas: guardar la salida entera de un
# leer_archivo lo haria inservible.
_HEAD_CHARS = 300
_HEAD_LINEAS = 3

# Timeout por defecto de comando_exit0. Una postcondicion colgada es un banco
# colgado: el incidente historico de este repo es el proceso que sigue vivo dos
# horas ocupando el unico slot.
_TIMEOUT_COMANDO_S = 120.0


# ---------------------------------------------------------------------------
# Sustitucion de parametros
# ---------------------------------------------------------------------------

def _sustituir(texto: str, valores: dict) -> tuple[str, list]:
    """Sustituye {param} por su valor. Devuelve (texto, marcadores_sin_ligar).

    No lanza: un marcador sin valor se DEJA tal cual y se reporta, para que el
    que llama decida (ligar() aborta; asi el motivo llega entero al usuario en
    vez de morir en un KeyError sin contexto).
    """
    if not isinstance(texto, str):
        return texto, []
    protegido = texto.replace("{{", _ESC_ABRE).replace("}}", _ESC_CIERRA)
    faltan: list = []

    def _rep(m):
        nombre = m.group(1)
        if nombre in valores and valores[nombre] is not None:
            return str(valores[nombre])
        faltan.append(nombre)
        return m.group(0)

    salida = _MARCADOR.sub(_rep, protegido)
    salida = salida.replace(_ESC_ABRE, "{").replace(_ESC_CIERRA, "}")
    return salida, faltan


def params_declarados(flujo: dict) -> list:
    """Normaliza flujo['params'] a [{nombre, obligatorio, default, descripcion}].

    El generalizador puede escribir params de tres formas (lista de nombres,
    lista de dicts, o dict nombre->default) segun de donde saco el flujo; el
    reproductor las acepta todas en vez de romperse por la forma.
    """
    crudos = (flujo or {}).get("params") or []
    fuera: list = []
    if isinstance(crudos, dict):
        for nombre, default in crudos.items():
            fuera.append({"nombre": str(nombre), "obligatorio": default is None,
                          "default": default, "descripcion": ""})
        return fuera
    for p in crudos:
        if isinstance(p, str):
            fuera.append({"nombre": p, "obligatorio": True, "default": None,
                          "descripcion": ""})
            continue
        if not isinstance(p, dict):
            continue
        nombre = str(p.get("nombre") or p.get("name") or "").strip()
        if not nombre:
            continue
        default = p.get("default")
        # Un param con default NO es obligatorio salvo que lo diga explicito:
        # obligar a repetir un valor que el flujo ya trae es la via mas corta a
        # que nadie reproduzca nada.
        obligatorio = p.get("obligatorio", p.get("required", default is None))
        fuera.append({"nombre": nombre, "obligatorio": bool(obligatorio),
                      "default": default,
                      "descripcion": str(p.get("descripcion") or "")})
    return fuera


def ligar(flujo: dict, valores: dict) -> dict:
    """Liga los parametros del flujo. Envelope, nunca None ni excepcion.

    Devuelve:
        {"ok": True,  "pasos": [...], "postcondiciones": [...],
         "valores": {...}, "error": "", "faltan": [], "sin_ligar": [],
         "extra": [...]}
        {"ok": False, "pasos": [], "error": "<motivo legible>", ...}

    Falla RUIDOSO en dos casos, ambos por la misma razon (un flujo a medio ligar
    que se ejecuta hace dano real en disco con rutas a medias):
      - falta un parametro OBLIGATORIO -> "faltan"
      - queda un {marcador} sin valor   -> "sin_ligar"
    """
    flujo = flujo or {}
    valores = dict(valores or {})
    decl = params_declarados(flujo)

    efectivos: dict = {}
    faltan: list = []
    for p in decl:
        nombre = p["nombre"]
        if nombre in valores and valores[nombre] is not None:
            efectivos[nombre] = valores[nombre]
        elif p["default"] is not None:
            efectivos[nombre] = p["default"]
        elif p["obligatorio"]:
            faltan.append(nombre)
    # Valores no declarados: se USAN igual (el flujo puede traer marcadores que
    # el bloque params no declaro; el generalizador falla por defecto en esa
    # direccion) pero se reportan para que el error se vea.
    extra = [k for k in valores if k not in efectivos]
    for k in extra:
        if valores[k] is not None:
            efectivos[k] = valores[k]

    if faltan:
        return {"ok": False, "pasos": [], "postcondiciones": [],
                "valores": efectivos, "faltan": sorted(set(faltan)),
                "sin_ligar": [], "extra": extra,
                "error": ("faltan parametros obligatorios: "
                          + ", ".join(sorted(set(faltan))))}

    sin_ligar: list = []
    pasos: list = []
    for i, paso in enumerate(flujo.get("pasos") or [], 1):
        if not isinstance(paso, dict):
            continue
        nuevo = dict(paso)
        nuevo["i"] = i
        tipo = str(paso.get("tipo") or ("modelo" if paso.get("instruccion")
                                        and not paso.get("tool") else "tool"))
        nuevo["tipo"] = tipo
        for campo in ("args_plantilla", "args", "instruccion", "cwd"):
            if campo in nuevo and isinstance(nuevo[campo], str):
                lig, f = _sustituir(nuevo[campo], efectivos)
                nuevo[campo] = lig
                sin_ligar.extend(f)
        # 'args' es el campo ya ligado que consume reproducir(); args_plantilla
        # se conserva para poder mostrar de donde salio.
        if "args" not in nuevo:
            nuevo["args"] = nuevo.get("args_plantilla", "")
        pasos.append(nuevo)

    post: list = []
    for p in flujo.get("postcondiciones") or []:
        if not isinstance(p, dict):
            continue
        nuevo = dict(p)
        for campo in ("ruta", "texto", "contiene", "patron", "comando", "cwd"):
            if campo in nuevo and isinstance(nuevo[campo], str):
                lig, f = _sustituir(nuevo[campo], efectivos)
                nuevo[campo] = lig
                sin_ligar.extend(f)
        post.append(nuevo)

    if sin_ligar:
        return {"ok": False, "pasos": [], "postcondiciones": [],
                "valores": efectivos, "faltan": [],
                "sin_ligar": sorted(set(sin_ligar)), "extra": extra,
                "error": ("quedaron marcadores sin ligar: "
                          + ", ".join("{%s}" % m for m in sorted(set(sin_ligar))))}

    return {"ok": True, "pasos": pasos, "postcondiciones": post,
            "valores": efectivos, "error": "", "faltan": [], "sin_ligar": [],
            "extra": extra}


# ---------------------------------------------------------------------------
# Postcondiciones: se comprueban en DISCO / EJECUTANDO, jamas contra el texto
# que devolvio un modelo o una tool. Esta es la regla dura del repo: el modelo
# que acaba de escribir el fichero es el peor testigo de que el fichero existe.
# ---------------------------------------------------------------------------

def ejecutar_comando(comando: str, cwd=None,
                     timeout_s: float = _TIMEOUT_COMANDO_S) -> tuple:
    """Ejecutor por defecto de comando_exit0 -> (codigo, salida). No lanza.

    Codigos sinteticos para que el informe distinga el modo de fallo:
      124 = timeout (mismo codigo que coreutils timeout, por costumbre)
      -1  = no se pudo ni lanzar
    """
    try:
        proc = subprocess.run(comando, shell=True,
                              cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True,
                              errors="replace", timeout=timeout_s)
        salida = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, salida
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT tras {timeout_s:g}s"
    except Exception as exc:                       # no lanzar en camino caliente
        return -1, f"no se pudo ejecutar: {exc}"


def _codigo_y_salida(res) -> tuple:
    """Normaliza lo que devuelva un ejecutar_fn inyectado.

    Acepta int, (codigo, salida) o {"codigo"/"returncode"/"exit", "salida"}:
    quien inyecta el ejecutor no deberia tener que aprender una forma nueva.
    """
    if isinstance(res, int):
        return res, ""
    if isinstance(res, tuple) and res:
        codigo = res[0]
        salida = res[1] if len(res) > 1 else ""
        try:
            return int(codigo), str(salida or "")
        except Exception:
            return -1, str(res)
    if isinstance(res, dict):
        for k in ("codigo", "returncode", "exit", "exit_code", "rc"):
            if k in res:
                try:
                    return int(res[k]), str(res.get("salida") or res.get("output") or "")
                except Exception:
                    break
    return -1, f"ejecutar_fn devolvio algo no interpretable: {res!r}"


def _resolver(ruta: str, workspace) -> Path:
    p = Path(str(ruta))
    if p.is_absolute() or workspace is None:
        return p
    return Path(str(workspace)) / p


def verificar_postcondiciones(post, workspace=None, ejecutar_fn=None) -> list:
    """Verifica las postcondiciones de un flujo. Devuelve
    [{"check", "ok", "detalle"}]. NUNCA lanza.

    Tipos soportados (los tres que puede emitir el generalizador):
      fichero_existe   {"ruta"}                  -> Path.exists() en DISCO
      fichero_contiene {"ruta", "texto"|"patron"} -> lee el fichero del DISCO
                        ("regex": True usa 'patron' como expresion)
      comando_exit0    {"comando", "cwd"?}        -> EJECUTA y exige codigo 0

    Un tipo desconocido NO se aprueba por defecto: ok=False con el motivo. Un
    examen que aprueba lo que no entiende es el bug del que salio este modulo.
    """
    ejecutar_fn = ejecutar_fn or ejecutar_comando
    fuera: list = []
    for p in post or []:
        if not isinstance(p, dict):
            fuera.append({"check": str(p)[:80], "ok": False,
                          "detalle": "postcondicion mal formada (no es dict)"})
            continue
        tipo = str(p.get("tipo") or p.get("check") or "").strip()
        try:
            if tipo == "fichero_existe":
                ruta = str(p.get("ruta") or "")
                destino = _resolver(ruta, workspace)
                existe = destino.exists()
                fuera.append({
                    "check": f"fichero_existe:{ruta}", "ok": bool(existe),
                    "detalle": (f"existe ({destino.stat().st_size} bytes)"
                                if existe and destino.is_file()
                                else "existe (directorio)" if existe
                                else f"NO existe: {destino}")})
            elif tipo == "fichero_contiene":
                ruta = str(p.get("ruta") or "")
                aguja = str(p.get("texto") or p.get("contiene")
                            or p.get("patron") or "")
                destino = _resolver(ruta, workspace)
                if not destino.is_file():
                    fuera.append({"check": f"fichero_contiene:{ruta}", "ok": False,
                                  "detalle": f"NO existe el fichero: {destino}"})
                else:
                    # errors=replace: un fichero binario o mal codificado tiene
                    # que dar VEREDICTO, no una excepcion que mate el informe.
                    cuerpo = destino.read_text(encoding="utf-8", errors="replace")
                    if p.get("regex"):
                        hallado = re.search(aguja, cuerpo) is not None
                    else:
                        hallado = aguja in cuerpo
                    fuera.append({
                        "check": f"fichero_contiene:{ruta}", "ok": bool(hallado),
                        "detalle": (f"contiene {aguja[:60]!r}" if hallado
                                    else f"NO contiene {aguja[:60]!r} "
                                         f"({len(cuerpo)} chars leidos)")})
            elif tipo == "comando_exit0":
                comando = str(p.get("comando") or p.get("cmd") or "")
                cwd = p.get("cwd") or workspace
                codigo, salida = _codigo_y_salida(ejecutar_fn(comando, cwd))
                fuera.append({
                    "check": f"comando_exit0:{comando[:80]}",
                    "ok": codigo == 0,
                    "detalle": (f"exit {codigo}"
                                + ("" if codigo == 0 else
                                   " | " + _head(salida)))})
            else:
                fuera.append({"check": f"{tipo or '(sin tipo)'}", "ok": False,
                              "detalle": ("tipo de postcondicion desconocido: "
                                          "no se aprueba lo que no se entiende")})
        except Exception as exc:                   # el examen nunca mata el turno
            fuera.append({"check": f"{tipo}:{str(p.get('ruta') or p.get('comando') or '')[:60]}",
                          "ok": False, "detalle": f"EXCEPCION al verificar: {exc}"})
    return fuera


# ---------------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------------

def _head(texto: str, chars: int = _HEAD_CHARS, lineas: int = _HEAD_LINEAS) -> str:
    t = (texto or "").strip()
    trozos = t.splitlines()[:lineas]
    corto = " / ".join(x.strip() for x in trozos)
    return corto[:chars]


def _paso_ok(resultado: str, paso: dict) -> bool:
    """Decide si un paso salio bien mirando la PRIMERA linea del resultado.

    POR QUE solo la primera: las tools de este repo ponen el estado en la
    cabecera ('RESULTADO leer_archivo x.py ERROR: ...'), pero el CUERPO puede
    contener la palabra ERROR legitimamente (un grep, un log leido). Mirar el
    texto entero convertia en fallo cualquier paso que leyera un log.
    Un paso puede anular la heuristica con 'exito_si' (substring en el
    resultado) o 'fallo_si'.
    """
    texto = resultado or ""
    exito_si = paso.get("exito_si")
    if exito_si:
        return str(exito_si) in texto
    fallo_si = paso.get("fallo_si")
    if fallo_si:
        return str(fallo_si) not in texto
    primera = texto.strip().splitlines()[0] if texto.strip() else ""
    return re.search(r"\bERROR\b", primera) is None


def _emitir(evento) -> None:
    """Publica en el bus de eventos si esta disponible. Guardado entero: el
    adorno jamas rompe una reproduccion (mismo contrato que ux/events.py)."""
    try:
        from cognia.ux.events import emitir
        emitir(evento)
    except Exception:
        pass


def _avisar(print_fn, linea: str) -> None:
    if print_fn is None:
        return
    try:
        print_fn(linea)
    except Exception:
        pass                                        # el adorno no rompe nada


# Variable de entorno que ancla las ESCRITURAS del registry real
# (cognia/agents/workers/dev_tools.py:_root_actual la lee en CALL-time y, si no
# esta, cae a os.getcwd()).
_ENV_WORKSPACE = "COGNIA_AGENT_WORKSPACE"


def _anclar_workspace(workspace):
    """Ancla el workspace de las tools REALES mientras dura la reproduccion.

    MEDIDO al cablear este modulo (2026-08-18): pasar el workspace SOLO en el
    ctx no basta. Las tools de escritura no miran el ctx: resuelven contra
    COGNIA_AGENT_WORKSPACE o, si falta, contra os.getcwd(). Un flujo reproducido
    con workspace=tmp escribia en el directorio del REPL y las postcondiciones
    lo reprobaban por el motivo EQUIVOCADO (buscaban en tmp un fichero que si se
    habia escrito, en otro sitio). Devuelve el valor previo para restaurarlo.
    """
    previo = os.environ.get(_ENV_WORKSPACE)
    try:
        os.environ[_ENV_WORKSPACE] = str(workspace)
    except Exception:
        pass
    return previo


def _restaurar_workspace(previo) -> None:
    try:
        if previo is None:
            os.environ.pop(_ENV_WORKSPACE, None)
        else:
            os.environ[_ENV_WORKSPACE] = previo
    except Exception:
        pass


def _ejecutar_pasos(ligado, run_tool_fn, agente_fn, ctx, parar_en_fallo,
                    print_fn, ok_fn, nombre):
    """Corre los pasos ligados y devuelve (pasos_informe, razon_parada).

    Extraido de reproducir_hibrido para que el anclaje del workspace pueda
    envolverlo en try/finally sin reindentar el bucle: si el anclaje se filtrara
    fuera de la reproduccion, la SIGUIENTE tarea del agente escribiria en el
    workspace del flujo. Esa fuga es exactamente el fallo silencioso que este
    modulo existe para no cometer.
    """
    pasos_informe: list = []
    razon = ""
    for paso in ligado["pasos"]:
        tipo = paso.get("tipo", "tool")
        args = paso.get("args", "")
        i = paso.get("i", len(pasos_informe) + 1)
        if tipo == "modelo":
            instruccion = paso.get("instruccion", "")
            etiqueta = "modelo"
            t_paso = time.perf_counter()
            if agente_fn is None:
                ok, resultado = False, ("ERROR: paso de tipo 'modelo' sin "
                                        "agente_fn: el flujo no se puede "
                                        "reproducir entero")
            else:
                try:
                    salida = agente_fn(instruccion, ctx)
                    if isinstance(salida, dict):
                        ok = bool(salida.get("ok", True))
                        resultado = str(salida.get("texto")
                                        or salida.get("resultado") or "")
                    else:
                        resultado = "" if salida is None else str(salida)
                        ok = True
                except Exception as exc:
                    ok, resultado = False, f"ERROR: EXCEPCION en agente_fn: {exc}"
            dur = round(time.perf_counter() - t_paso, 4)
            pasos_informe.append({"i": i, "tipo": "modelo", "tool": etiqueta,
                                  "args": instruccion, "ok": ok,
                                  "resultado_head": _head(resultado),
                                  "duracion_s": dur})
        else:
            tool = str(paso.get("tool") or "")
            t_paso = time.perf_counter()
            _emitir(_ev_inicio(tool, args, i))
            if not tool:
                ok, resultado = False, "ERROR: paso sin 'tool'"
            else:
                try:
                    salida = run_tool_fn(tool, args, ctx)
                    resultado = "" if salida is None else str(salida)
                    ok = bool(ok_fn(resultado, paso)) if ok_fn else _paso_ok(resultado, paso)
                except Exception as exc:
                    ok, resultado = False, f"ERROR: EXCEPCION en {tool}: {exc}"
            dur = round(time.perf_counter() - t_paso, 4)
            _emitir(_ev_fin(tool, args, ok, _head(resultado), dur, i))
            pasos_informe.append({"i": i, "tipo": "tool", "tool": tool,
                                  "args": args, "ok": ok,
                                  "resultado_head": _head(resultado),
                                  "duracion_s": dur})

        ultimo = pasos_informe[-1]
        _avisar(print_fn, "[flujo {}] paso {} {} {} ({:.2f}s)".format(
            nombre, i, "OK " if ultimo["ok"] else "FALLO",
            ultimo["tool"], ultimo["duracion_s"]))
        if not ultimo["ok"] and parar_en_fallo:
            razon = f"paso {i} fallo ({ultimo['tool']})"
            break
    return pasos_informe, razon


def reproducir_hibrido(flujo: dict, valores: dict, run_tool_fn, agente_fn=None,
                       *, workspace=None, parar_en_fallo=True, print_fn=None,
                       ctx=None, ejecutar_fn=None, ok_fn=None,
                       anclar_workspace=True) -> dict:
    """Reproduce un flujo donde algunos pasos NO son mecanicos.

    CONTRATO DEL PASO DE MODELO
    ---------------------------
    Un paso {"tipo": "modelo", "instruccion": "..."} se delega en
    ``agente_fn(instruccion, ctx) -> str`` (o -> dict {"ok", "texto"}).
    POR QUE existe: un flujo aprendido tiene 6 pasos mecanicos y uno que exige
    criterio ("elige el nombre del modulo segun lo que haya en el repo").
    Congelar ese paso como una llamada a tool fija es lo que hace que el flujo
    solo sirva para el caso exacto del que se aprendio; delegarlo mantiene el
    resto reproducible. El texto que devuelva agente_fn se guarda en el informe
    pero NO decide nada: el veredicto sigue siendo el de las postcondiciones,
    que se miden en disco.
    Si aparece un paso de modelo y agente_fn es None, ese paso FALLA ruidoso
    (no se salta): saltarlo produciria un informe verde de un flujo incompleto.

    ``run_tool_fn(nombre, args, ctx) -> str`` es la misma firma que
    cognia/agent/tools.py:run_tool, para poder pasar el registry real tal cual.

    ``anclar_workspace=True`` (default) exporta COGNIA_AGENT_WORKSPACE mientras
    corren los pasos y lo restaura al salir: es el UNICO canal por el que el
    registry real confina las escrituras (medido, ver _anclar_workspace).
    Ponerlo en False solo tiene sentido con un run_tool_fn falso.

    NUNCA lanza: cualquier excepcion de run_tool_fn/agente_fn se convierte en un
    paso ok=False con la excepcion en resultado_head.
    """
    t0 = time.perf_counter()
    ligado = ligar(flujo, valores)
    nombre = str((flujo or {}).get("nombre") or "(sin nombre)")

    if not ligado["ok"]:
        _avisar(print_fn, f"[flujo {nombre}] NO se ejecuta: {ligado['error']}")
        return {"ok": False, "flujo": nombre, "pasos": [], "postcondiciones": [],
                "razon_parada": f"ligado fallido: {ligado['error']}",
                "duracion_total_s": round(time.perf_counter() - t0, 4),
                "ligado": ligado}

    if ctx is None:
        ctx = {}
    ctx = dict(ctx)
    if workspace is not None:
        # El ctx lleva el workspace para las tools que SI lo miran; las de
        # escritura NO lo miran (ver _anclar_workspace: van por env var). Se
        # ponen los dos canales a proposito, y el que manda es el env var.
        ctx.setdefault("cwd", str(workspace))
        ctx.setdefault("workspace", str(workspace))
    ctx.setdefault("_flujo", nombre)

    previo_ws = None
    anclado = workspace is not None and anclar_workspace
    if anclado:
        previo_ws = _anclar_workspace(workspace)
    try:
        pasos_informe, razon = _ejecutar_pasos(
            ligado, run_tool_fn, agente_fn, ctx, parar_en_fallo, print_fn,
            ok_fn, nombre)
    finally:
        if anclado:
            _restaurar_workspace(previo_ws)

    # Las postcondiciones se verifican SIEMPRE, incluso si un paso fallo: el
    # veredicto real es el disco. Un paso puede "fallar" por una cabecera fea y
    # haber dejado el fichero bien, y al reves — un flujo con todos los pasos en
    # verde puede no haber escrito nada.
    post = verificar_postcondiciones(ligado["postcondiciones"], workspace,
                                     ejecutar_fn)
    for p in post:
        _avisar(print_fn, "[flujo {}] post {} {} — {}".format(
            nombre, "OK " if p["ok"] else "FALLO", p["check"], p["detalle"]))

    pasos_ok = all(p["ok"] for p in pasos_informe)
    ejecuto_todo = len(pasos_informe) == len(ligado["pasos"])
    post_ok = all(p["ok"] for p in post)
    if not razon and not pasos_ok:
        fallidos = [str(p["i"]) for p in pasos_informe if not p["ok"]]
        razon = f"pasos fallidos (sin parar): {', '.join(fallidos)}"
    if not razon and not post_ok:
        malas = [p["check"] for p in post if not p["ok"]]
        razon = f"postcondicion fallida: {'; '.join(malas)[:200]}"

    return {"ok": bool(pasos_ok and post_ok and ejecuto_todo),
            "flujo": nombre,
            "pasos": pasos_informe,
            "postcondiciones": post,
            "razon_parada": razon,
            "duracion_total_s": round(time.perf_counter() - t0, 4),
            "ligado": ligado}


def reproducir(flujo: dict, valores: dict, run_tool_fn, *, workspace=None,
               parar_en_fallo=True, print_fn=None, ctx=None, ejecutar_fn=None,
               ok_fn=None) -> dict:
    """Reproduce un flujo MECANICO (sin pasos de modelo). NUNCA lanza.

    Informe = {ok, pasos:[{tool, args, ok, resultado_head, duracion_s}],
               postcondiciones:[{check, ok, detalle}], razon_parada,
               duracion_total_s}.
    Es reproducir_hibrido con agente_fn=None: si el flujo trae un paso de
    modelo, ese paso falla ruidoso en vez de saltarse.
    """
    return reproducir_hibrido(flujo, valores, run_tool_fn, None,
                              workspace=workspace, parar_en_fallo=parar_en_fallo,
                              print_fn=print_fn, ctx=ctx,
                              ejecutar_fn=ejecutar_fn, ok_fn=ok_fn)


def _ev_inicio(tool: str, args: str, paso: int):
    from cognia.ux.events import ToolInicio
    return ToolInicio(tool=tool, args=str(args)[:120], paso=paso)


def _ev_fin(tool: str, args: str, ok: bool, resumen: str, dur: float, paso: int):
    from cognia.ux.events import ToolFin
    return ToolFin(tool=tool, args=str(args)[:120], ok=ok,
                   resumen=resumen[:200], duracion_s=dur, paso=paso)


# ---------------------------------------------------------------------------
# Coste: el numero que hace falta para el CONTRAFACTUAL
# ---------------------------------------------------------------------------

def coste(informe: dict) -> dict:
    """Pared y pasos de una reproduccion, para compararla contra hacer la misma
    tarea con el agente.

    POR QUE: un flujo aprendido solo se adopta si GANA a la alternativa. Sin
    este numero, "el flujo funciono" se confunde con "el flujo convino", que es
    exactamente el error que dejo skills envenenadas activas. La comparacion
    honesta es este dict contra el mismo dict de la corrida del agente.
    """
    informe = informe or {}
    pasos = informe.get("pasos") or []
    post = informe.get("postcondiciones") or []
    pared_pasos = sum(float(p.get("duracion_s") or 0.0) for p in pasos)
    return {
        "ok": bool(informe.get("ok")),
        "pasos": len(pasos),
        "pasos_ok": sum(1 for p in pasos if p.get("ok")),
        "pasos_fallidos": sum(1 for p in pasos if not p.get("ok")),
        "pasos_modelo": sum(1 for p in pasos if p.get("tipo") == "modelo"),
        "pared_s": round(float(informe.get("duracion_total_s") or 0.0), 4),
        "pared_pasos_s": round(pared_pasos, 4),
        # La resta es el coste del EXAMEN (postcondiciones + ligado). Se separa
        # porque verificar es lo unico que este modulo agrega frente a correr
        # las tools a pelo, y hay que poder defenderlo con un numero.
        "pared_examen_s": round(max(0.0, float(informe.get("duracion_total_s") or 0.0)
                                    - pared_pasos), 4),
        "postcondiciones": len(post),
        "postcondiciones_ok": sum(1 for p in post if p.get("ok")),
    }


def resumen_linea(informe: dict) -> str:
    """Una linea para el REPL: veredicto, pasos, postcondiciones y pared."""
    c = coste(informe)
    return ("flujo {}: {} — {}/{} pasos, {}/{} postcondiciones, {:.2f}s{}"
            .format(informe.get("flujo", "?"),
                    "OK" if c["ok"] else "FALLO",
                    c["pasos_ok"], c["pasos"],
                    c["postcondiciones_ok"], c["postcondiciones"],
                    c["pared_s"],
                    "" if c["ok"] else f" — {informe.get('razon_parada', '')}"))
