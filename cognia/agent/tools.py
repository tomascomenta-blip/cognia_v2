"""
cognia/agent/tools.py
=====================
Concrete tool registry for the Cognia agent loop.

Design (deliberately NOT abstract):
  - Each tool is a plain function ``fn(args: str, ctx: dict) -> str``.
  - ``args`` is the raw text after the tool name on the ACCION line.
  - ``ctx`` is a plain dict the loop fills in:
        ai             -> the Cognia instance (memory, kg, orchestrator)
        working_memory -> dict the agent reads/writes within a task
        agent_state    -> persisted dict (files_touched, tasks, ...)
        print_fn       -> live progress printer (markup-aware)
        show_diff      -> optional callback(old, new, path) for file writes
  - A tool returns the string that gets fed back to the model as RESULTADO.

Adding a tool = write one function + decorate it. No classes, no plugin
discovery, no inheritance. ``build_tools_doc()`` turns the registry into the
prompt text so the doc and the code can never drift apart.
"""

from __future__ import annotations

import ast
import atexit
import datetime
import glob as _glob
import json
import locale
import operator
import os
import re
import subprocess
import sys
import time as _time
from pathlib import Path

# Gate de escritura compartido con los workers Tier 1: confina TODA escritura
# del loop al workspace del agente (AGENT_WORKSPACE_ROOT, env-overridable via
# COGNIA_AGENT_WORKSPACE) y bloquea nombres sensibles (*.env, *secret*,
# binarios). Levanta ValueError con mensaje ASCII que nombra el workspace.
from cognia.agents.workers.dev_tools import resolve_write_path as _resolve_write_path

# name -> {"fn", "doc", "danger", "desc", "params"}
TOOLS: dict = {}


def tool(name: str, doc: str, danger: bool = False,
         desc: str = "", params: list = None):
    """Register a tool. ``doc`` is one line shown to the model verbatim.

    ``desc``/``params`` (opcionales, 2026-08-09): documentación RICA para el
    tool-calling nativo (schemas OpenAI que arma cognia/agent/tool_schemas.py).
    ``desc`` = cuándo/para qué usar la tool (frases completas); ``params`` =
    lista de dicts {"nombre","tipo","requerido","descripcion","clave"} en el
    ORDEN posicional del protocolo texto ('a | b'); "clave"=True marca los que
    van como token 'clave=valor' (ver armar_args). Una tool sin params sigue
    funcionando igual: el protocolo texto solo usa ``doc``."""
    def deco(fn):
        TOOLS[name] = {"fn": fn, "doc": doc, "danger": danger,
                       "desc": desc or "", "params": list(params or [])}
        return fn
    return deco


def build_tools_doc(allowed: set = None) -> str:
    """The tool list block injected into the agent prompt, built from the registry.

    ``allowed``: si se pasa, muestra SOLO esas tools (sub-agente acotado por
    rol -- delegar_subtarea). None = todas (comportamiento por defecto)."""
    return "\n".join(f"  {spec['doc']}" for name, spec in TOOLS.items()
                     if allowed is None or name in allowed)


# ── catalogo CORE (A5, 2026-08-09) ─────────────────────────────────────
# El set por DEFECTO que ve el modelo: ~12 tools ortogonales, decidido con el
# A/B del propio repo (2026-07-25, n=4+4: catalogo de 46 tools baja el camino
# feliz de 4.25/5 a 2.5/5 — mas tools NO es mas capacidad, es mas distraccion).
# calcular entra porque el gate del camino feliz tiene una tarea de calculo y
# es la via barata del modelo chico. El resto del registry SIGUE registrado e
# invocable (run_tool no filtra por esto): solo deja de anunciarse en el
# prompt. Modo avanzado y los flags opt-in (ver flag_de_optin) lo re-exponen.
# ejecutar_fondo es la 14a y la UNICA que se agrego al core (2026-08-18): las
# demas tools nuevas de esa tanda (ver_salida/matar_proceso/procesos, git_*,
# mover_archivo/crear_directorio/buscar_ficheros/leer_lote) quedan registradas
# e invocables pero NO anunciadas, porque el criterio para gastar una linea del
# prompt es "hoy es IMPOSIBLE", no "hoy es incomodo". Sin ejecutar_fondo un
# servidor, un build largo o un watcher no se pueden ni intentar (ejecutar es
# bloqueante y muere a los 600s); sus companeras se descubren por el TEXTO del
# resultado ("leelo con: ver_salida <id>"), que cuesta cero en el catalogo.
CORE_TOOLS = frozenset({
    "leer_archivo", "escribir_archivo", "editar_archivo", "apendar_archivo",
    "borrar_archivo", "listar", "buscar", "ejecutar", "ejecutar_fondo", "tests",
    "generar_codigo", "delegar_subtarea", "recordar", "calcular",
})


def catalogo_schemas(allowed: set = None) -> list:
    """El registry en forma consumible para tool-calling nativo (WP1 lo
    convierte a schemas OpenAI): [{nombre, descripcion, params, danger}].
    ``descripcion`` prefiere el ``desc`` rico y cae al ``doc`` de una linea.
    ``params`` viene en el ORDEN posicional del protocolo texto (ver
    armar_args); lista vacia = la tool solo declara su doc de una linea."""
    out = []
    for name, spec in TOOLS.items():
        if allowed is not None and name not in allowed:
            continue
        out.append({
            "nombre": name,
            "descripcion": spec.get("desc") or spec["doc"],
            "params": [dict(p) for p in spec.get("params", [])],
            "danger": spec.get("danger", False),
        })
    return out


def armar_args(name: str, argumentos: dict) -> str:
    """Arma el string ``args`` del protocolo texto desde un dict de argumentos
    nombrados (el puente inverso para un tool_call nativo: el modelo emite
    JSON, la tool sigue recibiendo su string de siempre).

    Convencion: los params posicionales (clave=False) se unen con ' | ' en el
    orden declarado; los de clave=True se agregan como tokens 'clave=valor' —
    con ' | ' delante en ejecutar (su parser lo exige para no confundirse con
    el comando) y con espacio en el resto (leer_archivo: auto_fix le recorta
    los pipes). Tool sin params declarados: se concatena lo que haya."""
    spec = TOOLS.get(name)
    params = (spec or {}).get("params") or []
    if not params:
        return " | ".join(str(v) for v in argumentos.values() if v is not None)
    posicionales, claves = [], []
    for p in params:
        val = argumentos.get(p["nombre"])
        if val is None:
            continue
        if p.get("clave"):
            claves.append(f"{p['nombre']}={val}")
        else:
            posicionales.append(str(val))
    args = " | ".join(posicionales)
    if claves:
        # 'ejecutar' exige el pipe delante de CADA clave: su parser lo pide
        # para no confundir 'timeout='/'cwd=' con un token del comando. Con dos
        # claves, unirlas entre si con un espacio dejaba la segunda sin pipe y
        # se la comia el comando (se ve con timeout + cwd juntos).
        if name == "ejecutar":
            args += " | " + " | ".join(claves)
        else:
            args += " " + " ".join(claves)
    return args


# Roles para sub-agentes acotados (delegar_subtarea): cada rol expone SOLO un
# subconjunto de tools -- un investigador no puede escribir/ejecutar, un
# implementador si. Acota el blast-radius de una subtarea delegada.
ROLE_TOOLS = {
    "investigador": {"leer_archivo", "leer_lote", "listar", "arbol",
                     "contar_lineas",
                     "buscar", "buscar_ficheros", "repo_map", "code_grafo",
                     "recordar", "kg_buscar",
                     "git_estado", "git_diff", "git_log",
                     "notas", "anotar", "resumir", "responder"},
    "implementador": {"leer_archivo", "leer_lote", "listar", "buscar",
                      "buscar_ficheros", "repo_map",
                      "code_grafo", "escribir_archivo", "editar_archivo",
                      "apendar_archivo", "borrar_archivo",
                      "copiar_archivo", "mover_archivo", "crear_directorio",
                      "generar_codigo", "contratos",
                      "py_validar",
                      "json_validar", "tests", "ejecutar", "ejecutar_fondo",
                      "ver_salida", "matar_proceso", "procesos",
                      "git_estado", "git_diff", "git_log",
                      "notas", "anotar",
                      "responder"},
}


# ── contador de uso liviano (TAREA 5) ──────────────────────────────────
# Dict en memoria {tool: {calls, ok, fail, last}} + flush ATOMICO (mismo
# patron _save_manifest de tool_synthesis: temp + os.replace, nunca deja el
# archivo a medio escribir) cada _USAGE_FLUSH_EVERY llamadas y en atexit.
# Best-effort: si el disco falla, el loop del agente no se entera.
_USAGE_PATH = Path(__file__).parent / "generated_tools" / "_tool_usage.json"
_USAGE: dict = {}
_usage_calls_since_flush = 0
_USAGE_FLUSH_EVERY = 20


def _usage_load() -> None:
    global _USAGE
    try:
        if _USAGE_PATH.exists():
            _USAGE = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _USAGE = {}


def _usage_flush() -> None:
    try:
        _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_USAGE, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _USAGE_PATH)
    except Exception:
        pass


def _record_usage(name: str, ok: bool) -> None:
    global _usage_calls_since_flush
    import datetime
    entry = _USAGE.setdefault(name, {"calls": 0, "ok": 0, "fail": 0, "last": None})
    entry["calls"] += 1
    entry["ok" if ok else "fail"] += 1
    entry["last"] = datetime.datetime.now().isoformat(timespec="seconds")
    _usage_calls_since_flush += 1
    if _usage_calls_since_flush >= _USAGE_FLUSH_EVERY:
        _usage_calls_since_flush = 0
        _usage_flush()
    # Cableado a UsageAnalytics (SQLite): el panel FEATURES leia una tabla que
    # NADIE escribia (3 lectores, 0 escritores -> "sin datos de uso aun" desde
    # siempre). Best-effort y NUNCA bajo pytest: los tests ejercitan run_tool
    # a mansalva y contaminarian la DB real con uso sintetico (mismo criterio
    # que _bon_log).
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            _usage_analytics().record(f"tool.{name}")
        except Exception:
            pass


_ANALYTICS = None


def _usage_analytics():
    """Singleton perezoso de UsageAnalytics (una sola conexion por proceso)."""
    global _ANALYTICS
    if _ANALYTICS is None:
        from cognia.analytics.usage_analytics import UsageAnalytics
        _ANALYTICS = UsageAnalytics()
    return _ANALYTICS


def get_tool_usage() -> dict:
    """Lectura de los contadores de uso (copia; no expone el dict interno)."""
    return {k: dict(v) for k, v in _USAGE.items()}


_usage_load()
atexit.register(_usage_flush)


# ── ACI: compactación de tool-outputs (mejora de HARNESS, 2026-07-13) ──
# El research del harness (HARNESS_RESEARCH.md) midió que los outputs de tools
# dominan 70-80% del budget de contexto y el 3B se pierde con dumps largos
# (ctx 16k). Cap uniforme head+tail: un output largo se recorta conservando
# la cabeza (la señal RESULTADO ...) y la cola (lo último suele ser lo
# relevante), con el completo guardado en disco por si el agente lo necesita.
# Cero riesgo: los outputs cortos (la mayoría) pasan intactos.
_ACI_CAP = int(os.environ.get("COGNIA_ACI_CAP", "1800"))
_ACI_HEAD = 1200
_ACI_TAIL = 450

# 2026-08-14: ese 1800 se midió con un 3B y ctx 16k, y se quedó fijo mientras
# el cerebro pasaba a servir 1.048.576 tokens. Recortar la salida de un
# comando a 1800 chars con esa ventana no protege nada: TIRA el stack trace,
# que casi siempre está en el medio — justo lo que head+tail no conserva. Y
# el agente entonces "repara" a ciegas, que es el bucle caro de la casa.
#
# El cap pasa a ser proporcional a la ventana REAL, con dos anclas:
#   - a ctx 16.384 da ~1.800: el valor histórico, para que nada cambie donde
#     se midió (contrafactual del test);
#   - techo absoluto de 24.000 chars, porque un output gigante deja de ser
#     información y pasa a ser ruido por mucha ventana que sobre.
# COGNIA_ACI_CAP explícito gana siempre: es el interruptor para medir.
_ACI_FRACCION_CTX = 0.03        # del contexto, en tokens
_ACI_CHARS_POR_TOKEN = 3.5
_ACI_TECHO = 24_000


def aci_cap_para(n_ctx: int = 0) -> int:
    """El cap de output para esa ventana. Sin n_ctx conocido, el histórico."""
    crudo = os.environ.get("COGNIA_ACI_CAP")
    if crudo:
        # 0 (o negativo) significa "sin recorte", no "recorta a cero": con el
        # calculo viejo head y tail daban 0 y el output era el marcador solo.
        try:
            pedido = int(crudo)
        except ValueError:
            pedido = 0
        if pedido > 0:
            return pedido
        return 10 ** 9
    if not n_ctx:
        return 1800
    escalado = int(n_ctx * _ACI_FRACCION_CTX * _ACI_CHARS_POR_TOKEN)
    return max(1800, min(_ACI_TECHO, escalado))


def _n_ctx_actual() -> int:
    """La ventana del backend servido AHORA, o 0. Nunca lanza ni sondea: usa
    el /props cacheado, porque esto corre en el camino caliente de cada tool."""
    try:
        from cognia.agent.model_profiles import n_ctx_del_backend
        return int(n_ctx_del_backend() or 0)
    except Exception:
        return 0


def aci_trim(text: str, name: str = "tool", cap: int = 0) -> str:
    """Recorta un output de tool largo a head+tail con un marcador; guarda el
    completo en el workspace. Idempotente sobre textos cortos."""
    cap = cap or aci_cap_para(_n_ctx_actual())
    if not text or len(text) <= cap:
        return text
    # head/tail se escalan sobre el CAP (no sobre head+tail): con el cap
    # histórico de 1800 esto da 1200/450 EXACTOS, que es el recorte de
    # siempre. Repartir sobre head+tail daba 1309/491 y rompía el
    # byte-idéntico justo en la ventana donde se midió — el contrafactual se
    # rompe en los decimales, no en los titulares.
    head = int(cap * (_ACI_HEAD / 1800))
    tail = int(cap * (_ACI_TAIL / 1800))
    ruta = ""
    try:
        base = Path(_resolve_write_path.__module__ and __import__(
            "cognia.agents.workers.dev_tools", fromlist=["AGENT_WORKSPACE_ROOT"]
        ).AGENT_WORKSPACE_ROOT)
        d = base / ".aci_overflow"
        d.mkdir(parents=True, exist_ok=True)
        import hashlib
        ruta = d / f"{name}_{hashlib.sha1(text.encode()).hexdigest()[:8]}.txt"
        ruta.write_text(text, encoding="utf-8")
        ruta = str(ruta)
    except Exception:
        ruta = "(no guardado)"
    omit = len(text) - head - tail
    return (text[:head]
            + f"\n[... {omit} chars omitidos (output completo en {ruta}) ...]\n"
            + text[-tail:])


# ── familias opt-in: tool -> flag que la enciende (A5, 2026-08-09) ─────
# UNA tabla para las dos caras del gate: (a) run_tool responde "DESHABILITADA
# — activala con X=1" uniforme cuando la tool no esta registrada porque su
# flag esta apagado, y (b) simple_mode/visible_tools rescata del recorte a las
# familias cuyo flag SI esta activo. Prefijos primero, nombres exactos para
# las que no siguen el prefijo de su familia (las 3 de LCD sin 'escena_').
_OPTIN_PREFIJOS = (
    ("pantalla_", "COGNIA_SCREEN"),
    ("escena_", "COGNIA_LCD"),
    ("imagen_", "COGNIA_IMG_TOOLS"),
    ("web_", "COGNIA_BROWSER"),
    # Flota multimodal (ola 2, 2026-08-09): voz/musica/3d/vlm opt-in duro.
    ("voz_", "COGNIA_VOZ_TOOLS"),
    ("musica_", "COGNIA_MUSICA_TOOLS"),
    ("tresd_", "COGNIA_3D_TOOLS"),
    ("vlm_", "COGNIA_VLM_TOOLS"),
)
_OPTIN_NOMBRES = {
    "repo_a_prompt": "COGNIA_REPO_REVERSE",
    # LCD sin prefijo escena_: viajan con el mismo paquete y el mismo flag
    "render_aprox": "COGNIA_LCD",
    "atribuir_fallo": "COGNIA_LCD",
    "reejecutar_etapa": "COGNIA_LCD",
    # Arnes (cognia/harness/tools_harness.py, 2026-08-12): cada capacidad se
    # anuncia SOLO con su subsistema encendido. No entran en CORE_TOOLS a
    # proposito: el A/B del repo midio que inflar el catalogo degrada al
    # modelo, asi que una tool nueva tiene que ganarse el sitio midiendo.
    "recuperar": "COGNIA_OFFLOAD",
    "consultar_oraculo": "COGNIA_ORACULO",
    "buscar_herramientas": "COGNIA_TOOLSEARCH",
    "deshacer_edicion": "COGNIA_UNDO_TOOL",
    "workflow": "COGNIA_WORKFLOW_TOOL",
    # TX/LIBRO (agente de horizonte largo, ESPEC 14.2 M3). Las 7 puertas
    # tipadas por las que el modelo escribe en la memoria append-only. Solo se
    # REGISTRAN con COGNIA_TX=1 (ver el final del modulo); estas entradas
    # existen para que con el flag apagado el mensaje sea "DESHABILITADA --
    # activala con COGNIA_TX=1" en vez de "no existe", que manda al
    # background researcher a sintetizar duplicados de tools ya escritas.
    "libro_grep": "COGNIA_TX",
    "libro_ver": "COGNIA_TX",
    "decidir": "COGNIA_TX",
    "afirmar": "COGNIA_TX",
    "pendiente": "COGNIA_TX",
    "resolver": "COGNIA_TX",
    "leccion": "COGNIA_TX",
}


def flag_de_optin(name: str) -> str:
    """Flag env que gobierna esta tool, o '' si no es de una familia opt-in."""
    if name in _OPTIN_NOMBRES:
        return _OPTIN_NOMBRES[name]
    for pref, flag in _OPTIN_PREFIJOS:
        if name.startswith(pref):
            return flag
    return ""


def _flag_activo(flag: str) -> bool:
    return os.environ.get(flag, "").strip().lower() in ("1", "on", "true", "yes")


# Tools cuyo output NO pasa por aci_trim porque ya se capan solas con un
# criterio mejor que head+tail genérico: leer_archivo (offset/limit + aviso de
# continuación: re-cortarlo rompe el contrato "el modelo edita lo que vio"),
# ejecutar/tests (cabeza+cola propia: el traceback vive al final), y
# editar_archivo (el mini-diff ya viene capado por mini_diff).
# Las tools RLM (2026-08-11) tambien: las de lectura se auto-capan a
# MAX_CHARS_VISTA y ctx_partir esta acotada por n<=64 (~3k chars de indice,
# sin contenido); sin la exencion aci_trim les comeria el MEDIO y el modelo
# veria texto del contexto que no existe (o perderia trozos del indice).
# git_diff/leer_lote/ver_salida (2026-08-18) por la MISMA razon que
# leer_archivo: traen texto que el modelo va a copiar literalmente (un hunk de
# patch, un fichero, la cola de un log) y el head+tail generico de aci_trim les
# comeria el MEDIO — el modelo escribiria bloques SEARCH con lineas que nunca
# existieron. Las tres llevan su propio tope con aviso explicito de truncado.
# `recuperar` (2026-08-23) por la MISMA razon: su salida ya esta capada por
# _FACTOR_MAX_BYTES (offloading.py) y trae el trozo EXACTO que el modelo
# pidio de un spill; el head+tail de aci_trim le comia el medio y la
# recuperacion prometida por el offload no llegaba nunca.
ACI_EXENTAS = frozenset({"responder", "leer_archivo", "leer_lote", "ejecutar",
                         "tests",
                         "editar_archivo", "git_diff", "ver_salida",
                         "ctx_info", "ctx_ver", "ctx_grep", "ctx_partir",
                         "rlm_llamar", "recuperar"})


# P0-1: TRES estados distintos, no dos. `_SIN_EXIT` = la tool ni siquiera paso
# por el shell (leer_archivo, responder...): no hay nada que medir y 'ok' lo
# sigue decidiendo la regex. `None` = paso por el shell pero NO se ejecuto
# (bloqueado / timeout / cwd malo): eso es FALLO, no exito. Un entero = exit
# real. Confundir los tres es justo el bug que P0-1 arregla.
_SIN_EXIT = object()


def _es_libro_caido(exc: BaseException) -> bool:
    """True si `exc` es la excepcion tipada del LIBRO (P0-2).

    Se importa AQUI y no arriba a proposito: solo corre en la rama de
    excepcion, asi que el camino caliente de run_tool no paga ni un import.
    """
    try:
        from cognia.tx.errores import LibroCaido
    except Exception:
        return False
    return isinstance(exc, LibroCaido)


def run_tool(name: str, args: str, ctx: dict) -> str:
    """Dispatch one tool by name. Unknown name -> a helpful error string."""
    # Sub-agente acotado: si el ctx trae un set de tools permitidas (rol de
    # delegar_subtarea), una tool fuera del rol se rechaza con señal clara --
    # el modelo ve que no la tiene y elige otra (mismo estilo que 'no existe').
    _allowed = ctx.get("_allowed_tools") if isinstance(ctx, dict) else None
    if _allowed is not None and name not in _allowed and name != "responder":
        return (f"ERROR: '{name}' no esta permitida para este rol. "
                f"Validas: {', '.join(sorted(_allowed))}")
    spec = TOOLS.get(name)
    if spec is None:
        # Una tool opt-in ausente no es "no existe": existe y esta APAGADA por
        # su flag. Decir "no existe" hace concluir (al modelo y al usuario) que
        # Cognia no sabe hacerlo, cuando solo falta el flag. Mensaje UNIFORME
        # para TODA familia opt-in (antes solo pantalla_* lo tenia; escena_*/
        # imagen_*/web_* caian a "no existe" y encima disparaban
        # record_wanted_tool, mandando al background researcher a sintetizar
        # duplicados de tools ya escritas). Va ANTES de record_wanted_tool a
        # proposito, por eso mismo.
        _flag = flag_de_optin(name)
        if _flag and not _flag_activo(_flag):
            return (f"ERROR: '{name}' esta DESHABILITADA — activala con "
                    f"{_flag}=1.")
        # Signal: the agent wanted a tool that doesn't exist yet. Logged so the
        # background researcher can later turn frequent wishes into real tools.
        try:
            from cognia.agent.background_research import record_wanted_tool
            record_wanted_tool(name, hint=args[:120])
        except Exception:
            pass
        # El modelo suele acertar la TAREA y errar el NOMBRE: 'crear_archivo'
        # aparece 42 veces en wanted_tools con los argumentos correctos de
        # escribir_archivo. Devolverle las 54 tools era castigarlo con ruido
        # justo cuando esta perdido, y ademas contradice el A/B del propio repo
        # (catalogos grandes degradan). Se le da el nombre bueno, o 3 candidatas.
        try:
            from cognia.harness.traductor_tools import mensaje_error
            _visibles = _allowed if _allowed is not None else set(TOOLS)
            return mensaje_error(name, _visibles, catalogo_schemas(_visibles))
        except Exception:
            valid = ", ".join(TOOLS.keys())
            return f"ERROR: herramienta '{name}' no existe. Validas: {valid}"
    # ARNES (cognia/harness/interceptor.py, 2026-08-12): modo plan, hooks del
    # proyecto y checkpoint del estado previo. Devuelve un string cuando la
    # llamada queda VETADA -- ese texto es lo que lee el modelo en lugar del
    # resultado. Cualquier fallo de la capa deja pasar la llamada.
    try:
        from cognia.harness.interceptor import antes as _harness_antes
        _veto = _harness_antes(name, args, ctx)
    except Exception:
        _veto = None
    if _veto:
        return _veto
    try:
        out = spec["fn"](args, ctx)
        # P0-1: el exit code REAL, si la tool paso por el shell. Se saca ANTES
        # de calcular 'ok' porque MANDA sobre la regex (ver abajo). `pop` para
        # que no se filtre al ctx de la llamada siguiente: un exit rancio es
        # exactamente el bug de "evento sellado con el reloj rancio".
        _exit = ctx.pop("_exit", _SIN_EXIT) if isinstance(ctx, dict) else _SIN_EXIT
        # \bERROR\b sobre la cabeza de la PRIMERA linea: todos los retornos de
        # error del registry ponen ERROR en la linea 1, pero un exito cuyo
        # CONTENIDO arranca temprano (ctx_grep sobre un log con errores,
        # leer_archivo de un log) no debe marcarse fallido (fix 2026-08-11).
        ok = not re.search(r"\bERROR\b", out.split("\n", 1)[0][:120])
        # P0-1 (ESPEC agente largo 14.1) -- LA REGEX NO DECIDE EL EXITO CUANDO
        # HAY UN EXIT CODE. Dos fallos MEDIDOS que esto arregla:
        #   - `tests`/`ejecutar` con exit 1: la salida es "RESULTADO ejecutar
        #     (exit 1): ..." y NO contiene ERROR en los 120 primeros chars ->
        #     llegaba ok=True. Un pytest en rojo se contaba como victoria.
        #   - comando BLOQUEADO por el sentinel: "RESULTADO ejecutar: BLOQUEADO
        #     por Sentinel (...)" tampoco contiene ERROR -> ok=True SIN haberse
        #     ejecutado nunca.
        # La correccion es en UNA direccion sola: el exit puede TUMBAR un ok,
        # nunca resucitarlo. Un exit 0 con 'ERROR' en la cabeza (una tool que
        # devuelve su propio error tras un subprocess sano) sigue siendo fallo.
        if _exit is not _SIN_EXIT and _exit != 0:
            ok = False
    except Exception as exc:  # a broken tool must not kill the loop
        out = f"RESULTADO {name} ERROR: {exc}"
        ok = False
        # La tool reviento: no hubo exit real. None, que no es 0.
        _exit = None
        if isinstance(ctx, dict):
            ctx.pop("_exit", None)
    if isinstance(ctx, dict):
        # P0-1, LA MITAD QUE FALTABA: el `ok` corregido por el exit real NO
        # SALIA DE AQUI. Solo alimentaba `_record_usage`, un `emit` sin
        # suscriptores y el LIBRO (opt-in), mientras el bucle nativo se
        # calculaba el suyo con la MISMA regex que P0-1 vino a sustituir. Con
        # eso, `run_tool('tests', <suite en rojo>)` devolvia
        # "RESULTADO ejecutar (exit 1): F ..." y loop.py concluia tool_ok=True:
        # escribia `exit: 0` en el canal de estado (que documenta "su exit code
        # REAL"), contaba una suite roja como verificacion aprobada en el
        # presupuesto por progreso y se lo pasaba a la parada verificada de
        # Hermes. Se publican los dos, y se SOBREESCRIBEN en cada llamada (no
        # `pop` diferido) para que nadie lea el exit del turno anterior.
        ctx["_ultimo_exit"] = None if _exit is _SIN_EXIT else _exit
        ctx["_ultimo_ok"] = bool(ok)
    try:
        _record_usage(name, ok)
    except Exception:
        pass
    # Bus interno (cognia/events.py): cada tool ejecutada deja un evento
    # observable (oficina, analytics, /agente estado) sin acoplar nada acá.
    try:
        from cognia.events import emit
        emit("tool.ejecutada", nombre=name, ok=ok, args_head=args[:80])
    except Exception:
        pass
    # ACI: compactar outputs largos (mejora de harness) antes de devolver al
    # loop. Exentas las tools que YA capan su propio output con criterio propio
    # (ACI_EXENTAS): el doble truncado hacía que el modelo editara con
    # SEARCH/REPLACE texto que jamás vio (leer_archivo 4000 -> aci 1650,
    # evidencia baseline 2026-08-09) y que la cola de ejecutar (el traceback)
    # se recortara dos veces. 'responder' es la respuesta final, no observación.
    # ARNES: verificacion de lo escrito, hooks post_tool y offloading opt-in.
    # Va ANTES del aci_trim para que el veredicto de sintaxis no se pierda en
    # el recorte, y porque el offloading (cuando se enciende) sustituye al
    # truncado en vez de sumarse (el doble truncado esta MEDIDO como danino).
    try:
        from cognia.harness.interceptor import despues as _harness_despues
        # exit_code: None cuando no hubo exit REAL (tool que no es shell, o
        # comando bloqueado). El interceptor tiene prohibido tratarlo como 0.
        out = _harness_despues(name, args, ctx, out, ok,
                               exit_code=(None if _exit is _SIN_EXIT else _exit))
    except Exception as _exc_harness:
        # P0-2: LA UNICA excepcion del arnes que NO se traga. Si el LIBRO no
        # pudo dejar constancia, seguir significa decidir el ciclo siguiente
        # sobre un pasado incompleto SIN SABERLO. Para y lo dice.
        if _es_libro_caido(_exc_harness):
            raise
    # F3: si el offloading ya sustituyo el output por su preview+referencia
    # (empieza por su cabecera), aci_trim NO se aplica encima: el doble
    # truncado esta MEDIDO como danino y con el cap chico (1800, backend sin
    # /props) cortaria la referencia — la receta de recuperacion — al medio.
    if isinstance(out, str) and out.startswith("[SALIDA GRANDE"):
        return out
    return out if name in ACI_EXENTAS else aci_trim(out, name)


# ── small shared helpers ───────────────────────────────────────────────
# 'datos_bancos' guarda jsonl de cientos de MB (532MB medidos 2026-08-01):
# leerlos en un scan de texto colgaba `buscar` MINUTOS desde la raiz del repo.
_SKIP_DIRS = {".git", "venv", "venv312", "venv312gpu", "datos_bancos",
              "__pycache__", ".pytest_cache", "node_modules"}


def _dir_saltable(parts) -> bool:
    """True si la ruta cae en un dir que no se escanea. startswith('venv')
    cubre cualquier venv futuro (venv313, venv_gpu...) sin tener que listarlo:
    el bug fue exactamente que 'venv312gpu' no estaba en la lista."""
    return any(x in _SKIP_DIRS or x.startswith("venv") for x in parts)


# Topes del scan de `buscar` (2026-08-01): sin ellos, buscar desde la raiz del
# repo leia jsonl de cientos de MB y colgaba la tool minutos. Modulo-level
# para poder ajustarlos (y monkeypatchearlos en tests).
_MAX_SCAN_BYTES = 2_000_000   # archivos mas grandes no se leen (no son codigo)
_SCAN_DEADLINE_S = 12.0       # default; el env se lee EN LA LLAMADA, ver abajo


def _deadline_s() -> float:
    """Segundos de deadline del scan de `buscar`, leidos EN CADA LLAMADA.

    Antes se leia COGNIA_BUSCAR_DEADLINE en import-time. Con Cognia EMBEBIDO
    (importado por otro proceso, o el modulo ya cargado cuando se pone la
    variable) el knob no hacia NADA: quedaba congelado el valor del momento del
    import. Se lee aqui para que ajustarlo funcione siempre.
    El module-level sigue siendo el default y el punto de monkeypatch de tests
    (por eso el env vacio cae al atributo, no a un literal)."""
    crudo = os.environ.get("COGNIA_BUSCAR_DEADLINE", "").strip()
    if not crudo:
        return _SCAN_DEADLINE_S
    try:
        return float(crudo)
    except ValueError:
        return _SCAN_DEADLINE_S


def _aviso_test_vacio(wpath: Path, content: str) -> str:
    """AVISO (no bloqueo) si el archivo es un test de pytest (test_*.py) que
    colectaria 0 tests. Cazado 2026-08-01: la skill escribir-tests entrego un
    'test file' invalido y nadie lo noto hasta correr pytest. Se valida con
    AST, no con substring: un 'def test_' dentro de un string/docstring no es
    una funcion y no debe contar."""
    if wpath.suffix != ".py" or not wpath.name.startswith("test_"):
        return ""
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return (f" AVISO: sintaxis invalida (linea {e.lineno}: {e.msg}); "
                f"pytest no podria ni importar este test")
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")):
            return ""
    return (" AVISO: no define ninguna funcion test_*; pytest colectaria "
            "0 tests de este archivo")


def _strip_fences(text: str) -> str:
    """Remove ```lang ... ``` fences a model often wraps code in."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip("\n")


_ESCAPES_LITERALES = (("\\n", "\n"), ("\\t", "\t"))


def _texto_literal(text: str) -> str:
    """El texto que el usuario QUISO apendar, sin el envoltorio del modelo.

    Medido el 2026-07-24 reproduciendo la tarea 'apendar' del gate del camino
    feliz (3 corridas): el 7B emite el argumento entre comillas y a veces con
    el salto de linea escapado como texto —

        apendar_archivo bitacora.txt | 'tercera'
        apendar_archivo bitacora.txt | "tercera\\n"

    — y el archivo terminaba con la linea literal `"tercera\\n"`, comillas y
    barra incluidas. La postcondicion del gate (ultima linea == "tercera")
    fallaba por eso, no por el agente equivocando la tool.

    Se limpia SOLO el caso inequivoco: el texto entero envuelto en la MISMA
    comilla, sin esa comilla adentro. Un texto que legitimamente lleva comillas
    en el medio ('dijo "hola"') no se toca. Es de una linea, asi que no aplica
    a codigo (para eso esta escribir_archivo).
    """
    t = (text or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" and t[0] not in t[1:-1]:
        t = t[1:-1]
        for esc, real in _ESCAPES_LITERALES:
            t = t.replace(esc, real)
    return t


def _orch(ctx: dict):
    """Reuse the Cognia instance's orchestrator, building a local one if needed."""
    ai = ctx.get("ai")
    o = getattr(ai, "_orchestrator", None)
    if o is not None:
        return o
    from shattering.orchestrator import ShatteringOrchestrator
    return ShatteringOrchestrator(mode="local")


def _disp(path) -> str:
    """Ruta para MOSTRAR al modelo en el RESULTADO: relativa al workspace si esta
    adentro, si no absoluta.

    El 3B copiaba el path ABSOLUTO que devolvia escribir_archivo
    (C:\\Users\\...\\x.txt) y luego lo re-usaba/leia en loop (verificado en e2e del
    agente 2026-07-01). Mostrar la ruta relativa evita esa confusion y ademas
    coincide con los datos de fine-tune (sanitizados a relativo)."""
    try:
        import cognia.agents.workers.dev_tools as _dv
        root = Path(_dv.AGENT_WORKSPACE_ROOT).resolve()
        p = Path(path).resolve()
        if p == root:
            return "."
        if root in p.parents:
            return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        pass
    return str(path)


# ══════════════════════════════════════════════════════════════════════
# LA FRONTERA DE BYTES (codificacion y fin de linea)
# ══════════════════════════════════════════════════════════════════════
# Este venv corre con locale cp1252 y las tools mas usadas del agente cruzan la
# frontera bytes<->texto en cada llamada. El repo YA sabia hacerlo bien en el
# arnes (harness/hooks.py:_decodificar, harness/verificacion.py con PYTHONUTF8=1,
# harness/checkpoints.py con newline='') pero la leccion nunca llego al camino
# CALIENTE. Los cuatro fallos, todos REPRODUCIDOS el 2026-08-13 contra ficheros
# de verdad:
#   1. subprocess.run(text=True) sin encoding: el hilo lector revienta con
#      UnicodeDecodeError, deja r.stdout=None SIN lanzar, y '(r.stdout+r.stderr)'
#      devuelve "unsupported operand type(s) for +: 'NoneType' and 'str'" mas un
#      traceback en la consola del dueno. Un simple print(chr(0x0410)) bastaba.
#   2. leer con errors='replace' y REESCRIBIR el fichero entero: un latin-1
#      perdia TODOS sus acentos (0xf3 -> U+FFFD, irreversible) y editar_archivo
#      contestaba "OK (1 bloque)".
#   3. escribir_archivo abortaba la escritura ENTERA por una lectura previa que
#      solo alimenta el diff cosmetico.
#   4. write_text traduce \n a os.linesep: cambiar UNA linea CRLF-izaba el
#      fichero entero (diff de 500 lineas por un cambio de 1).
# La regla que sale de aca: leer bytes, DETECTAR la codificacion, y devolver esa
# misma codificacion y ese mismo fin de linea al escribir. Nunca "replace" en un
# camino que despues escribe.
#
# Dos limites CONOCIDOS de esta implementacion, dichos para que nadie se lleve
# la sorpresa mirando un diff:
#   a. Fin de linea MIXTO (mitad LF, mitad CRLF): se normaliza al DOMINANTE, o
#      sea que el diff toca lineas que nadie edito. Sigue siendo mejor que el
#      comportamiento previo (write_text CRLF-izaba el fichero entero en
#      Windows, mixto o no), pero no es "no tocar nada".
#   b. El fin de linea se decide por MAYORIA, no por linea. Un fichero 50/50
#      sale todo LF (el empate lo gana LF, ver _nl_dominante).


def _codecs_probables() -> list:
    """Cascada de codecs a probar al leer un fichero del que no sabemos nada.

    Copiada de harness/hooks.py:_codecs_de_respaldo (misma leccion, otro modulo;
    se replica en vez de importarse para no acoplar el registry de tools al
    arnes). OJO con ``locale.getpreferredencoding(False)``: bajo el modo UTF-8
    de Python devuelve 'utf-8', o sea el codec que ya fallo — el respaldo no
    respaldaba nada. ``locale.getencoding()`` da la codificacion REAL del locale
    (la pagina ANSI de Windows), que es la que tienen los ficheros del dueno
    escritos con el Bloc de notas viejo o por herramientas que no son Python.
    """
    codecs = ["utf-8"]
    try:
        codecs.append(locale.getencoding())       # 3.11+: ignora el modo UTF-8
    except AttributeError:                        # pragma: no cover - <=3.10
        codecs.append(locale.getpreferredencoding(False))
    codecs.append("cp1252")                       # la ANSI mas comun en Windows
    vistos, unicos = set(), []
    for c in codecs:
        cl = (c or "").lower()
        if cl and cl not in vistos:
            vistos.add(cl)
            unicos.append(c)
    return unicos


# BOMs: si el fichero trae marca de orden de bytes, la codificacion no se
# adivina, se LEE. Importa de verdad en esta maquina: PowerShell 5.1 escribe
# UTF-8 con BOM por defecto, y decodificar eso como 'utf-8' pelado deja un
# U+FEFF invisible al principio del texto que despues se reescribe (o peor, se
# mete en medio de un bloque SEARCH y no casa nunca).
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"),
         (b"\x00\x00\xfe\xff", "utf-32"), (b"\xff\xfe", "utf-16"),
         (b"\xfe\xff", "utf-16"))


def _decodificar_bytes(datos) -> str:
    """Bytes -> texto que NUNCA levanta. Para output de procesos y lecturas de
    solo-lectura: preferimos texto imperfecto a un traceback. latin-1 al final
    porque decodifica cualquier byte (1:1), asi que la cascada siempre termina."""
    if not datos:
        return ""
    if isinstance(datos, str):
        return datos
    for codec in _codecs_probables():
        try:
            return datos.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    return datos.decode("latin-1", errors="replace")


def _nl_dominante(datos) -> str:
    """El fin de linea que YA tiene el fichero. Acepta bytes o texto.

    Sobre BYTES para los codecs de 1 byte: el texto decodificado con
    universal-newlines ya perdio el dato. Sobre TEXTO para los codecs anchos
    (ver ``_codec_ancho``), donde contar b"\\r\\n" en crudo no casa nunca.
    Fin de linea MIXTO: gana el dominante y el fichero sale normalizado a el.
    Es una mejora sobre lo que hacia write_text (CRLF-izar todo en Windows),
    pero hay que saberlo: en un fichero mixto el diff toca lineas no editadas.
    """
    if isinstance(datos, bytes):
        crlf, lf_total = datos.count(b"\r\n"), datos.count(b"\n")
    else:
        crlf, lf_total = datos.count("\r\n"), datos.count("\n")
    return "\r\n" if crlf > (lf_total - crlf) else "\n"


def _codec_ancho(codec: str) -> bool:
    """True para utf-16/utf-32 (y sus variantes -le/-be/-sig).

    En estos codecs cada caracter ocupa 2 o 4 bytes, asi que un CRLF llega al
    disco como \\r\\x00\\n\\x00 (utf-16LE) y el conteo en bytes crudos da 0:
    _nl_dominante devolvia "\\n" y _escribir_texto pasaba a LF el fichero
    ENTERO — el mismo "cambiar UNA linea reescribe todo" del bug 4, por otra
    puerta. No es teorico en esta maquina: PowerShell 5.1 escribe utf-16 con
    ``Out-File`` por defecto, o sea que medio disco del dueno es utf-16.
    """
    c = (codec or "").lower().replace("_", "-")
    return c.startswith("utf-16") or c.startswith("utf-32")


def _decodificar_con(datos: bytes, codec: str) -> tuple:
    """(texto normalizado a '\\n', fin de linea original) para un codec dado.
    Deja subir UnicodeDecodeError/LookupError: es la senal de 'probar el
    siguiente codec de la cascada'."""
    texto = datos.decode(codec)
    # El nl se mide ANTES del .replace(): despues ya no queda ni un \r\n.
    nl = _nl_dominante(texto if _codec_ancho(codec) else datos)
    return texto.replace("\r\n", "\n"), nl


def _leer_texto(path: Path) -> tuple:
    """(texto, codec, nl) del fichero, con su codificacion REAL detectada.

    - ``texto`` viene con los saltos normalizados a '\\n' (como hacia
      read_text) para que los bloques SEARCH del modelo casen igual en un
      fichero CRLF; ``nl`` guarda el original para devolverlo al escribir.
    - ``codec`` es None cuando NINGUN codec de la cascada decodifica los bytes
      sin perdida: en ese caso ``texto`` es lo mejor que se pudo (latin-1) y
      quien vaya a ESCRIBIR debe abortar, no reescribir con U+FFFD.
    Deja subir OSError (fichero inexistente): el error de 'no existe' es del
    llamador, no de la codificacion.
    """
    datos = path.read_bytes()
    for bom, codec in _BOMS:
        if datos.startswith(bom):
            try:
                texto, nl = _decodificar_con(datos, codec)
                return texto, codec, nl
            except (UnicodeDecodeError, LookupError):
                break
    for codec in _codecs_probables():
        try:
            texto, nl = _decodificar_con(datos, codec)
            return texto, codec, nl
        except (UnicodeDecodeError, LookupError):
            continue
    # Ningun codec: latin-1 como red y el nl medido en bytes (el codec real es
    # desconocido, asi que 'ancho' no se puede afirmar; ademas quien escriba
    # con codec=None debe abortar, no reescribir).
    return (datos.decode("latin-1", errors="replace").replace("\r\n", "\n"),
            None, _nl_dominante(datos))


def _escribir_texto(path: Path, texto: str, codec: str = "utf-8",
                    nl: str = "\n") -> None:
    """Escribe con la codificacion y el fin de linea que se le dicen.

    ``newline=''`` es el punto: sin el, Python traduce cada '\\n' a os.linesep
    y en Windows cambiar UNA linea reescribe el fichero entero en CRLF (bug 4).
    Con newline='' el fichero sale EXACTAMENTE como el string, y por eso la
    conversion al fin de linea original se hace aca, explicita."""
    if nl != "\n":
        texto = texto.replace("\r\n", "\n").replace("\n", nl)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=codec, newline="") as fh:
        fh.write(texto)


def _env_utf8() -> dict:
    """Entorno para los hijos con el modo UTF-8 de Python FORZADO.

    Sin esto un hijo Python hereda cp1252 y `print('camion')` (o cualquier
    traceback con acentos) o revienta con UnicodeEncodeError o llega mutilado.
    Mismo remedio que harness/verificacion.py:254 para pytest, aplicado ahora al
    'ejecutar' del agente, que es por donde pasa TODO lo demas."""
    return dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


# ══════════════════════════════════════════════════════════════════════
# FILE TOOLS
# ══════════════════════════════════════════════════════════════════════

# Topes de leer_archivo (estilo Claude Code/OpenCode: read con limite de
# lineas + puntero "usa offset para seguir"). El cap de CHARS es la red de
# seguridad para archivos de lineas kilometricas (json minificado): 2000
# lineas x 80 chars ~ 160k chars reventarian el contexto igual.
_LEER_LIMIT_DEF = 2000     # lineas por llamada (default)
_LEER_LINEA_MAX = 500      # una linea mas larga se corta con marcador
_LEER_CAP_CHARS = int(os.environ.get("COGNIA_LEER_CAP", "24000"))

# offset/limit al FINAL de los args, como tokens sueltos 'offset=N limit=M'
# (sin '|': structure.auto_fix le recorta a leer_archivo todo lo que siga a un
# pipe porque el 3B reusaba el formato de escribir_archivo). Se acepta tambien
# la forma con '| offset=...' por si run_tool se llama directo (sin auto_fix).
_RE_LEER_KV = re.compile(r"(?:\s*\|)?\s+(offset|limit)\s*=\s*(\d+)\s*$", re.I)


@tool("leer_archivo",
      "leer_archivo <path> [offset=N] [limit=M]  -- leer un archivo (default "
      "2000 lineas desde la 1; offset=linea inicial para seguir)",
      desc="Lee un archivo de texto y devuelve su contenido TAL CUAL (para "
           "poder editarlo despues con editar_archivo). Por defecto muestra "
           "las primeras 2000 lineas; si el archivo sigue, el resultado "
           "termina con un aviso que dice con que offset continuar.",
      params=[
          {"nombre": "path", "tipo": "string", "requerido": True,
           "descripcion": "ruta del archivo a leer"},
          {"nombre": "offset", "tipo": "integer", "requerido": False,
           "clave": True,
           "descripcion": "linea inicial (1-indexada; default 1)"},
          {"nombre": "limit", "tipo": "integer", "requerido": False,
           "clave": True,
           "descripcion": "cuantas lineas mostrar (default 2000)"},
      ])
def _leer_archivo(args, ctx):
    raw = args.strip()
    offset, limit = 1, _LEER_LIMIT_DEF
    # extraer offset=/limit= del final (en cualquier orden, 0, 1 o 2 veces)
    while True:
        m = _RE_LEER_KV.search(raw)
        if not m:
            break
        if m.group(1).lower() == "offset":
            offset = max(1, int(m.group(2)))
        else:
            limit = max(1, int(m.group(2)))
        raw = raw[:m.start()].rstrip().rstrip("|").rstrip()
    path = Path(raw.strip().strip("\"'"))
    # Codificacion DETECTADA, no asumida: con encoding='utf-8', errors='replace'
    # un fichero latin-1 del dueno llegaba al modelo con U+FFFD donde habia
    # acentos — y el modelo despues copia eso en un bloque SEARCH que ya no casa.
    full, _codec, _nl = _leer_texto(path)
    if not full:
        return f"RESULTADO leer_archivo {_disp(path)}: (archivo vacio)"
    lineas = full.splitlines()
    total = len(lineas)
    if offset > total:
        return (f"RESULTADO leer_archivo {_disp(path)} ERROR: offset={offset} "
                f"pero el archivo tiene {total} lineas")
    sel, recorte_linea = [], False
    for ln in lineas[offset - 1:offset - 1 + limit]:
        if len(ln) > _LEER_LINEA_MAX:
            ln = (ln[:_LEER_LINEA_MAX]
                  + f"... [linea cortada: {len(ln)} chars]")
            recorte_linea = True
        sel.append(ln)
    # red de seguridad por chars: cortar en la ultima linea COMPLETA que cabe
    # (nunca a mitad de linea: el modelo copia lo que ve en bloques SEARCH)
    mostradas, usados = [], 0
    for ln in sel:
        if usados + len(ln) + 1 > _LEER_CAP_CHARS and mostradas:
            break
        mostradas.append(ln)
        usados += len(ln) + 1
    hasta = offset + len(mostradas) - 1
    content = "\n".join(mostradas)
    if hasta < total or recorte_linea:
        # Marcador explicito: sin esto el modelo cree que vio el archivo entero
        # y lo sobrescribe con una version mas corta (perdida de datos en
        # read-mod-write). El puntero de continuacion es el patron OpenCode.
        content += (f"\n... [TRUNCADO: mostrando lineas {offset}-{hasta} de "
                    f"{total} (archivo de {len(full)} chars); el archivo NO "
                    f"esta completo. Para seguir: leer_archivo {_disp(path)} "
                    f"offset={hasta + 1}. NO lo sobrescribas entero]")
    return f"RESULTADO leer_archivo {_disp(path)}: {content}"


# leer_lote (2026-08-18): leer N ficheros costaba N turnos del PRESUPUESTO DE
# PASOS (el loop corta por pasos, no por tokens), y el agente se quedaba sin
# vueltas antes de entender el codigo que iba a tocar. Topes propios (por
# fichero y total) + esta tool en ACI_EXENTAS: el head+tail generico mezclaria
# el final de un fichero con el principio de otro.
_LOTE_MAX_FICHEROS = 8
_LOTE_CAP_FICHERO = int(os.environ.get("COGNIA_LOTE_CAP_FICHERO", "6000"))
_LOTE_CAP_TOTAL = int(os.environ.get("COGNIA_LOTE_CAP_TOTAL", "24000"))


@tool("leer_lote",
      "leer_lote <path1> | <path2> | ...     -- lee VARIOS archivos en UNA "
      "llamada (hasta 8)",
      desc="Lee varios archivos de una sola vez y los devuelve separados por "
           "una cabecera con su ruta. Sirve para entender un modulo y sus "
           "vecinos sin gastar un turno por fichero. Cada archivo se corta si "
           "es largo (avisa); para leer uno entero usa leer_archivo con "
           "offset/limit.",
      params=[
          {"nombre": "paths", "tipo": "string", "requerido": True,
           "descripcion": "rutas separadas por ' | ' (hasta 8)"},
      ])
def _leer_lote(args, ctx):
    rutas = [r.strip().strip("\"\'") for r in re.split(r"\s*\|\s*", args or "")
             if r.strip()]
    if not rutas:
        return ("RESULTADO leer_lote ERROR: pasa al menos una ruta "
                "(varias separadas por ' | ')")
    sobran = rutas[_LOTE_MAX_FICHEROS:]
    rutas = rutas[:_LOTE_MAX_FICHEROS]
    bloques, usados = [], 0
    for ruta in rutas:
        path = Path(ruta)
        cab = f"===== {_disp(path)} ====="
        if not path.exists():
            bloques.append(f"{cab}\nERROR: no existe")
            continue
        if path.is_dir():
            bloques.append(f"{cab}\nERROR: es un directorio (usa listar)")
            continue
        try:
            texto, _codec, _nl = _leer_texto(path)
        except Exception as e:
            bloques.append(f"{cab}\nERROR: {e}")
            continue
        n_lineas = len(texto.splitlines())
        if not texto:
            bloques.append(f"{cab}\n(archivo vacio)")
            continue
        # Presupuesto restante REAL: cortar por fichero y ademas por total,
        # para que 8 ficheros medianos no revienten igual el contexto.
        resto = max(0, _LOTE_CAP_TOTAL - usados)
        cap = min(_LOTE_CAP_FICHERO, resto)
        if cap <= 0:
            bloques.append(f"{cab}\n[NO LEIDO: se agoto el tope total de "
                           f"{_LOTE_CAP_TOTAL} chars; pidelo con leer_archivo]")
            continue
        cuerpo = texto[:cap]
        if len(texto) > cap:
            cuerpo += (f"\n... [TRUNCADO: {len(cuerpo)} de {len(texto)} chars "
                       f"({n_lineas} lineas); sigue con leer_archivo "
                       f"{_disp(path)} offset=N]")
        usados += len(cuerpo)
        bloques.append(f"{cab} ({n_lineas} lineas)\n{cuerpo}")
    nota = ""
    if sobran:
        nota = (f" [se ignoraron {len(sobran)} rutas: el tope es "
                f"{_LOTE_MAX_FICHEROS} por llamada]")
    return (f"RESULTADO leer_lote ({len(rutas)} archivos){nota}:\n"
            + "\n".join(bloques))


@tool("escribir_archivo",
      "escribir_archivo <path> | <contenido>  -- crea/sobrescribe en el workspace (crea dirs)",
      desc="Crea un archivo nuevo (o SOBRESCRIBE uno existente ENTERO) con el "
           "contenido dado; crea los directorios intermedios. Para cambiar "
           "solo una parte de un archivo existente usa editar_archivo (no "
           "reescribas el archivo entero: perderias lo que no repitas). "
           "SI EL ARCHIVO ES LARGO (mas de ~120 lineas, por ejemplo una pagina "
           "web con estilos): escribelo POR PARTES -- esta llamada con la "
           "primera parte y luego apendar_archivo con el resto. Una sola "
           "llamada gigante se corta a medias y se pierde entera.",
      params=[
          {"nombre": "path", "tipo": "string", "requerido": True,
           "descripcion": "ruta del archivo (dentro del workspace)"},
          {"nombre": "contenido", "tipo": "string", "requerido": True,
           "descripcion": "contenido COMPLETO del archivo (varias lineas ok)"},
      ])
def _escribir_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escribir_archivo ERROR: formato (usa ruta | contenido)"
    try:
        wpath = _resolve_write_path(parts[0].strip())
    except ValueError as e:
        return f"RESULTADO escribir_archivo ERROR: {e}"
    content = _strip_fences(parts[1])
    # NOTA (2026-07-24): se probo aplicar tambien aca la limpieza de envoltorio
    # (_texto_literal) para texto plano de una linea. El A/B del gate dio 3/6
    # corridas perfectas contra 4/6 sin el cambio: sin evidencia de mejora sobre
    # la tool MAS usada del agente, no entra. Queda en apendar_archivo, que es
    # donde el defecto esta probado y el riesgo es menor.
    # La lectura del PREVIO solo alimenta el diff cosmetico (show_diff) y el fin
    # de linea a conservar: JAMAS puede bloquear la escritura. Con
    # read_text(encoding='utf-8') estricto, escribir sobre un fichero latin-1
    # existente devolvia "'utf-8' codec can't decode byte 0xf1" y NO escribia
    # nada — la tool mas usada del agente, muerta por un fichero con enies.
    old, nl = "", "\n"
    if wpath.exists():
        try:
            old, _codec_prev, nl = _leer_texto(wpath)
        except Exception:
            old, nl = "", "\n"
    # Se escribe SIEMPRE en utf-8 (es contenido nuevo entero, no una edicion
    # sobre lo viejo), pero respetando el fin de linea que el fichero ya tenia.
    _escribir_texto(wpath, content, "utf-8", nl)
    show_diff = ctx.get("show_diff")
    if callable(show_diff):
        try:
            show_diff(old, content, str(wpath))
        except Exception:
            pass
    ft = ctx.setdefault("agent_state", {}).setdefault("files_touched", [])
    if str(wpath) not in ft:
        ft.append(str(wpath))
        ctx["agent_state"]["files_touched"] = ft[-15:]
    return (f"RESULTADO escribir_archivo {_disp(wpath)}: OK ({len(content)} chars)"
            + _aviso_test_vacio(wpath, content))


@tool("editar_archivo",
      "editar_archivo <path> | <<<<<<< SEARCH\\n...\\n=======\\n...\\n>>>>>>> REPLACE  -- edicion quirurgica por bloque",
      desc="Edita un archivo existente reemplazando bloques SEARCH/REPLACE. El "
           "SEARCH debe copiar TEXTO EXACTO que viste con leer_archivo y ser "
           "UNICO en el archivo (si aparece varias veces, amplialo con mas "
           "lineas de contexto). Devuelve un mini-diff de lo aplicado. Es la "
           "forma correcta de modificar un archivo sin perder el resto.",
      params=[
          {"nombre": "path", "tipo": "string", "requerido": True,
           "descripcion": "ruta del archivo a editar (debe existir)"},
          {"nombre": "bloques", "tipo": "string", "requerido": True,
           "descripcion": "uno o mas bloques '<<<<<<< SEARCH\\n(texto exacto)"
                          "\\n=======\\n(reemplazo)\\n>>>>>>> REPLACE'"},
      ])
def _editar_archivo(args, ctx):
    """Edicion SEARCH/REPLACE (idea de Aider): cambia solo el bloque indicado en
    vez de reescribir el fichero entero. Barato y seguro para el modelo pequeno
    (no arrastra el resto del fichero). Acepta varios bloques seguidos. Si el
    SEARCH no casa, el error nombra el bloque y sugiere las lineas parecidas."""
    from cognia.agent.edit_block import (apply_edits, parse_bloques, EditError,
                                         mini_diff)
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return ("RESULTADO editar_archivo ERROR: formato (usa ruta | bloque "
                "<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE)")
    try:
        wpath = _resolve_write_path(parts[0].strip())
    except ValueError as e:
        return f"RESULTADO editar_archivo ERROR: {e}"
    if not wpath.exists():
        return (f"RESULTADO editar_archivo ERROR: {_disp(wpath)} no existe "
                f"(para crearlo usa escribir_archivo)")
    bloques = parse_bloques(_strip_fences(parts[1]))
    # errors='replace' aca era PERDIDA DE DATOS, no un detalle: esta tool
    # reescribe el fichero ENTERO, asi que cada byte que la lectura convirtio en
    # U+FFFD se persistia como U+FFFD. Un latin-1 con "camion con acentuacion"
    # perdia los dos acentos por cambiar 'def f' por 'def g', y la tool
    # respondia "OK (1 bloque)". Ahora: codificacion detectada, escritura con la
    # MISMA, y si no hay ninguna que decodifique sin perdida no se escribe nada.
    old, codec, nl = _leer_texto(wpath)
    if codec is None:
        return (f"RESULTADO editar_archivo ERROR: no se pudo decodificar "
                f"{_disp(wpath)} con ninguna codificacion de texto "
                f"(probadas: {', '.join(_codecs_probables())}). Editarlo "
                f"reescribiria el fichero entero perdiendo esos bytes, asi que "
                f"NO se toco. Si es binario, no es editable con SEARCH/REPLACE.")
    try:
        nuevo, estrategias = apply_edits(old, bloques)
    except EditError as e:
        return f"RESULTADO editar_archivo ERROR: {e}"
    if nuevo == old:
        return f"RESULTADO editar_archivo {_disp(wpath)}: sin cambios (el REPLACE es igual)"
    nota_codec = ""
    try:
        _escribir_texto(wpath, nuevo, codec, nl)
    except UnicodeEncodeError:
        # El REPLACE trae caracteres que la codificacion original no cubre
        # (una flecha '->' unicode en un latin-1). Subir el fichero a utf-8 y
        # DECIRLO es honesto; escribir '?' silenciosos no lo seria.
        _escribir_texto(wpath, nuevo, "utf-8", nl)
        nota_codec = (f" [el texto nuevo no cabe en {codec}: el fichero quedo "
                      f"en utf-8]")
    show_diff = ctx.get("show_diff")
    if callable(show_diff):
        try:
            show_diff(old, nuevo, str(wpath))
        except Exception:
            pass
    ft = ctx.setdefault("agent_state", {}).setdefault("files_touched", [])
    if str(wpath) not in ft:
        ft.append(str(wpath))
        ctx["agent_state"]["files_touched"] = ft[-15:]
    n = len(estrategias)
    # Mini-diff de vuelta al modelo: sin él, el modelo sigue razonando sobre la
    # versión vieja del fichero (el "OK" no dice QUÉ cambió). Capado en
    # mini_diff; editar_archivo está exento de aci_trim para que no se re-corte.
    _diff = mini_diff(old, nuevo)
    return (f"RESULTADO editar_archivo {_disp(wpath)}: OK ({n} bloque"
            f"{'s' if n != 1 else ''} [{', '.join(estrategias)}], {len(nuevo)} chars)"
            + nota_codec + (f"\n{_diff}" if _diff else ""))


@tool("apendar_archivo",
      "apendar_archivo <path> | <texto>      -- agrega texto al final (en el workspace)",
      desc="Agrega una linea de texto AL FINAL de un archivo sin tocar el "
           "resto (lo crea si no existe). Ideal para logs/bitacoras.",
      params=[
          {"nombre": "path", "tipo": "string", "requerido": True,
           "descripcion": "ruta del archivo (dentro del workspace)"},
          {"nombre": "texto", "tipo": "string", "requerido": True,
           "descripcion": "texto a agregar al final (sin comillas envolventes)"},
      ])
def _apendar_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO apendar_archivo ERROR: formato (usa ruta | texto)"
    try:
        wpath = _resolve_write_path(parts[0].strip())
    except ValueError as e:
        return f"RESULTADO apendar_archivo ERROR: {e}"
    text = _texto_literal(_strip_fences(parts[1]))
    wpath.parent.mkdir(parents=True, exist_ok=True)
    # Start on a fresh line if the file has content not ending in a newline,
    # so "append a line" never glues onto the previous one.
    # Apendar no reescribe lo viejo, pero SI mete bytes nuevos en el fichero: si
    # la bitacora esta en cp1252 y le pegamos utf-8, el fichero queda mixto y
    # nadie lo puede leer entero. Se apenda en la codificacion que YA tiene, y
    # con su mismo fin de linea (con encoding='utf-8' a secas, una linea nueva
    # en un fichero LF salia con CRLF).
    prefix, codec, nl = "", "utf-8", "\n"
    if wpath.exists():
        existing, det, nl = _leer_texto(wpath)
        codec = det or "utf-8"
        if existing and not existing.endswith("\n"):
            prefix = "\n"
    linea = prefix + (text if text.endswith("\n") else text + "\n")
    if nl != "\n":
        linea = linea.replace("\n", nl)
    try:
        with wpath.open("a", encoding=codec, newline="") as fh:
            fh.write(linea)
    except UnicodeEncodeError as e:
        return (f"RESULTADO apendar_archivo {_disp(wpath)} ERROR: el texto tiene "
                f"caracteres que no existen en {codec}, la codificacion del "
                f"fichero ({e.reason}). No se apendo nada (mezclar "
                f"codificaciones en un fichero lo rompe entero).")
    return f"RESULTADO apendar_archivo {_disp(wpath)}: OK (+{len(text)} chars)"


@tool("copiar_archivo", "copiar_archivo <src> | <dst>          -- copia un archivo (dst en el workspace)")
def _copiar_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO copiar_archivo ERROR: formato (usa src | dst)"
    import shutil
    # src puede leerse de cualquier lado (leer es legitimo); dst queda confinado.
    src = Path(parts[0].strip())
    try:
        dst = _resolve_write_path(parts[1].strip())
    except ValueError as e:
        return f"RESULTADO copiar_archivo ERROR: {e}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"RESULTADO copiar_archivo: {src} -> {_disp(dst)} OK"


# mover_archivo (2026-08-18): mover/renombrar costaba DOS tools y dos turnos
# (copiar_archivo + borrar_archivo) y dejaba el original si el borrado fallaba.
# Src y dst pasan los dos por el gate de escritura: mover BORRA el origen, asi
# que el origen tambien es una escritura (copiar_archivo puede leer de fuera
# del workspace justamente porque no lo toca).
@tool("mover_archivo",
      "mover_archivo <src> | <dst>           -- mueve/renombra un archivo (los "
      "dos dentro del workspace)",
      danger=True,
      desc="Mueve o renombra un archivo dentro del workspace del agente (crea "
           "el directorio destino si hace falta). Para duplicarlo sin quitar "
           "el original usa copiar_archivo.",
      params=[
          {"nombre": "src", "tipo": "string", "requerido": True,
           "descripcion": "ruta actual del archivo"},
          {"nombre": "dst", "tipo": "string", "requerido": True,
           "descripcion": "ruta nueva (si es un directorio existente, se mueve "
                          "dentro conservando el nombre)"},
      ])
def _mover_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO mover_archivo ERROR: formato (usa src | dst)"
    import shutil
    try:
        src = _resolve_write_path(parts[0].strip().strip("\"\'"))
        dst = _resolve_write_path(parts[1].strip().strip("\"\'"))
    except ValueError as e:
        return f"RESULTADO mover_archivo ERROR: {e}"
    if not src.exists():
        return f"RESULTADO mover_archivo ERROR: {_disp(src)} no existe"
    if src.is_dir():
        return (f"RESULTADO mover_archivo ERROR: {_disp(src)} es un directorio; "
                f"esta tool solo mueve archivos")
    # dst es un directorio que ya existe -> destino = ese dir / nombre del src
    # (es lo que hace 'mv a.txt carpeta/' y lo que el modelo espera).
    if dst.is_dir():
        dst = dst / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"RESULTADO mover_archivo: {_disp(src)} -> {_disp(dst)} OK"


@tool("crear_directorio",
      "crear_directorio <ruta>               -- crea un directorio (y los "
      "intermedios) en el workspace",
      desc="Crea un directorio dentro del workspace, con los intermedios que "
           "falten. No hace falta antes de escribir_archivo (esa ya los crea): "
           "sirve para preparar la estructura de un proyecto.",
      params=[
          {"nombre": "ruta", "tipo": "string", "requerido": True,
           "descripcion": "ruta del directorio a crear"},
      ])
def _crear_directorio(args, ctx):
    try:
        wpath = _resolve_write_path(args.strip().strip("\"\'"))
    except ValueError as e:
        return f"RESULTADO crear_directorio ERROR: {e}"
    if wpath.is_file():
        return (f"RESULTADO crear_directorio ERROR: {_disp(wpath)} ya existe y "
                f"es un ARCHIVO")
    ya = wpath.is_dir()
    wpath.mkdir(parents=True, exist_ok=True)
    return (f"RESULTADO crear_directorio {_disp(wpath)}: "
            + ("ya existia" if ya else "OK (creado)"))


# borrar_archivo (2026-08-09, catalogo core A5): el agente no tenia forma de
# BORRAR un archivo que el mismo creo (el fallback era 'ejecutar del/rm', que
# el sentinel frena con razon). Confinado al workspace via _resolve_write_path:
# borrar es una escritura. Solo archivos, nunca directorios (blast-radius).
@tool("borrar_archivo",
      "borrar_archivo <path>                 -- borra UN archivo (en el workspace)",
      danger=True,
      desc="Borra un archivo del workspace del agente. Solo archivos "
           "individuales (no directorios). Para vaciar un archivo sin "
           "borrarlo usa escribir_archivo con contenido vacio.",
      params=[
          {"nombre": "path", "tipo": "string", "requerido": True,
           "descripcion": "ruta del archivo a borrar (dentro del workspace)"},
      ])
def _borrar_archivo(args, ctx):
    try:
        wpath = _resolve_write_path(args.strip().strip("\"'"))
    except ValueError as e:
        return f"RESULTADO borrar_archivo ERROR: {e}"
    if not wpath.exists():
        return f"RESULTADO borrar_archivo ERROR: {_disp(wpath)} no existe"
    if wpath.is_dir():
        return (f"RESULTADO borrar_archivo ERROR: {_disp(wpath)} es un "
                f"directorio; esta tool solo borra archivos")
    wpath.unlink()
    return f"RESULTADO borrar_archivo {_disp(wpath)}: OK (borrado)"


@tool("listar", "listar <directorio>                   -- lista archivos/carpetas",
      desc="Lista los archivos y carpetas de un directorio (no recursivo). "
           "Para buscar por contenido usa 'buscar'.",
      params=[
          {"nombre": "directorio", "tipo": "string", "requerido": False,
           "descripcion": "directorio a listar (default: el actual)"},
      ])
def _listar(args, ctx):
    base = Path(args.strip() or ".")
    entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))[:40]
    listing = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in entries]
    return f"RESULTADO listar {base}: {listing}"


@tool("arbol", "arbol <directorio>                    -- arbol de archivos (2 niveles)")
def _arbol(args, ctx):
    base = Path(args.strip() or ".")
    out = []
    for p in sorted(base.rglob("*")):
        if _dir_saltable(p.parts):
            continue
        rel = p.relative_to(base)
        if len(rel.parts) > 2:
            continue
        out.append(("  " * (len(rel.parts) - 1)) + ("[D] " if p.is_dir() else "") + rel.parts[-1])
        if len(out) >= 60:
            break
    return "RESULTADO arbol:\n" + "\n".join(out)


@tool("contar_lineas", "contar_lineas <path>                  -- cuenta lineas de un archivo")
def _contar_lineas(args, ctx):
    p = Path(args.strip())
    n = sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
    size = p.stat().st_size
    return f"RESULTADO contar_lineas {p}: {n} lineas, {size} bytes"


# ══════════════════════════════════════════════════════════════════════
# SEARCH TOOLS
# ══════════════════════════════════════════════════════════════════════

# Marcas de que un "patron" es en realidad una pregunta sobre el mundo y no
# algo que pueda estar en los archivos del proyecto.
_RE_CODIGO = re.compile(
    r"[{}()\[\];=<>]|\bdef\b|\bclass\b|\bimport\b|\bfunction\b|\.py\b|\.js\b"
    r"|\.json\b|\.md\b|--|__|::")


# Senal POSITIVA de que se pregunta por el mundo, no por el proyecto.
_RE_PREGUNTA_MUNDO = re.compile(
    r"\b(qu[eé]\s+(es|son|significa|fue)|qui[eé]n(es)?\s+(es|fue|son|lo|la)"
    r"|cu[aá]ndo\s|d[oó]nde\s|por\s+qu[eé]\s|para\s+qu[eé]\s"
    r"|cu[aá]l\s+es|cu[aá]nto[as]?\s|c[oó]mo\s+(funciona|se\s+llama)"
    r"|en\s+(internet|la\s+web|wikipedia|google)"
    r"|qui[eé]n\s+(invent|desarroll|cre|escrib|fund))", re.IGNORECASE)


def _parece_pregunta_del_mundo(patron: str) -> bool:
    """True si el patron es una PREGUNTA sobre algo externo al proyecto.

    Exige una senal POSITIVA de pregunta (que es / quien / donde / "en
    internet"...), no solo que no parezca codigo: con el criterio laxo,
    "archivo config settings" — un grep legitimo — se iba a Wikipedia
    (lo casco tests/test_buscar_fallback.py, y con razon).
    Ante la duda, NO: mejor "sin coincidencias" que una busqueda inventada."""
    p = (patron or "").strip()
    if len(p) < 6 or _RE_CODIGO.search(p):
        return False
    if not (2 <= len(p.split()) <= 14):
        return False
    if any(Path(t).exists() for t in p.split()):    # rutas del proyecto: no
        return False
    return bool(_RE_PREGUNTA_MUNDO.search(p))


@tool("buscar", "buscar <patron> | <directorio>        -- busca texto en archivos",
      desc="Busca un patron de texto (regex o literal) dentro de los archivos "
           "de un directorio o de un archivo concreto; devuelve hasta 15 "
           "lineas 'archivo:linea: texto'. Si el patron es una pregunta sobre "
           "el mundo (no sobre el proyecto), consulta la web.",
      params=[
          {"nombre": "patron", "tipo": "string", "requerido": True,
           "descripcion": "texto o regex a buscar (sin comillas envolventes)"},
          {"nombre": "directorio", "tipo": "string", "requerido": False,
           "descripcion": "directorio o archivo donde buscar (default: '.')"},
      ])
def _buscar(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    patron = parts[0].strip()
    directorio = parts[1].strip() if len(parts) > 1 else "."

    # El modelo entrecomilla el patron: escribe `buscar "class" | ruta`. Sin
    # quitarlas, se busca el literal `"class"` — con comillas — y no casa nunca.
    # Medido el 2026-07-20: el agente gasto 8 pasos reintentando la misma
    # busqueda con y sin comillas y acabo concluyendo, en falso, que el fichero
    # no tenia clases.
    for comilla in ('"', "'"):
        if len(patron) > 1 and patron.startswith(comilla) and patron.endswith(comilla):
            patron = patron[1:-1].strip()
            break
    directorio = directorio.strip("\"'")

    # El separador " | " es poco habitual y el modelo no lo usa: escribe
    # `buscar class cognia/mcp_libre.py`. Sin esto, el patron pasaba a ser la
    # frase entera, no encontraba nada y devolvia "sin resultados" — y el
    # agente concluia que el fichero NO TIENE clases, teniendo tres. Medido el
    # 2026-07-20 en una tarea real. Un vacio silencioso que produce una
    # conclusion falsa es peor que un error.
    if len(parts) == 1 and " " in patron:
        cabeza, _, cola = patron.rpartition(" ")
        if cola and Path(cola).exists():
            patron, directorio = cabeza.strip(), cola

    # ¿El ambito que pidio el usuario es uno de los que el scan salta entero?
    # Se calcula ANTES del scan, con el directorio ya resuelto. '.' (el default)
    # nunca es saltable, asi que esto solo se dispara con un ambito EXPLICITO.
    _ambito_saltado = _dir_saltable(Path(directorio).parts)

    # Deadline GLOBAL de la tool: desde la raiz del repo el scan colgaba
    # MINUTOS (jsonl de 532MB en datos_bancos + venv312gpu fuera de la
    # lista de skip). Al vencer, se corta el scan y se sigue con los
    # fallbacks (glob se salta, la web para preguntas del mundo sigue).
    _segundos = _deadline_s()
    _deadline = _time.time() + _segundos
    # Estado REAL del scan, no inferido del reloj: 'cortado' se pone donde de
    # verdad se rompe el bucle por deadline, y 'rg' donde de verdad contesto
    # ripgrep. Comparar _time.time() con el deadline al final mentia en los dos
    # sentidos (un scan completo pero lento se declaraba cortado, y un corte
    # con matches parciales se presentaba como scan completo).
    _estado = {"cortado": False, "rg": False}

    def _scan(pat):
        """rg -> fallback regex/substring sobre contenidos. Hasta 15 'archivo:n: txt'."""
        try:
            # -H (--with-filename) SIEMPRE: rg lo omite cuando el ambito es UN
            # fichero, y sin el ni el modelo ni los tests pueden saber de
            # donde salio el match (cazado 2026-08-09: 'buscar class |
            # cognia/mcp_libre.py' devolvia '67:class ErrorMCP' sin ruta).
            # SIN text=True a proposito: rg emite utf-8 y el hilo lector de
            # subprocess lo decodificaba con el locale (cp1252) — un solo
            # nombre/linea con acentos lo reventaba, dejaba r.stdout=None, el
            # '.strip()' de abajo tiraba AttributeError y el 'except Exception:
            # pass' se lo tragaba: rg quedaba DESACTIVADO en silencio y la
            # busqueda caia al escaneo lento. Bytes + cascada = nunca falla.
            r = subprocess.run(
                ["rg", "--no-heading", "-H", "-n", "--max-count", "3",
                 pat, directorio],
                capture_output=True, timeout=10,
            )
            salida = _decodificar_bytes(r.stdout).strip()
            if r.returncode == 0 and salida:
                _estado["rg"] = True
                return salida.splitlines()[:15]
        except Exception:
            pass
        out = []
        try:
            compiled = re.compile(pat, re.IGNORECASE)
        except re.error:
            compiled = None
        # Un FICHERO tambien es un ambito valido. `Path(fichero).rglob("*")`
        # devuelve 0 elementos, asi que acotar la busqueda a un fichero
        # concreto no funcionaba nunca por este camino — y este camino es el
        # unico que hay, porque `rg` no esta instalado en esta maquina, con lo
        # que el subprocess de arriba siempre falla. Medido el 2026-07-20.
        raiz = Path(directorio)
        candidatos = [raiz] if raiz.is_file() else raiz.rglob("*")

        for p in candidatos:
            if _time.time() > _deadline:
                _estado["cortado"] = True
                break
            if not p.is_file() or _dir_saltable(p.parts):
                continue
            try:
                # Archivos grandes (jsonl de datos, dumps) o binarios (byte
                # NUL en la cabeza) no son texto grepeable: leerlos entero
                # era lo que quemaba los minutos, no el numero de ficheros.
                if p.stat().st_size > _MAX_SCAN_BYTES:
                    continue
                with p.open("rb") as fh:
                    if b"\0" in fh.read(1024):
                        continue
                # read_text(errors='replace') SIN encoding usaba el locale:
                # un fichero utf-8 con 'funcion' acentuada se leia como
                # 'funciÃ³n' y el patron NO matcheaba. Un falso negativo
                # INVISIBLE (la tool contesta "sin coincidencias" tan campante),
                # que es el peor tipo de fallo de una tool de busqueda.
                for i, ln in enumerate(_leer_texto(p)[0].splitlines(), 1):
                    if (compiled and compiled.search(ln)) or (not compiled and pat.lower() in ln.lower()):
                        out.append(f"{p}:{i}: {ln.strip()[:100]}")
                        if len(out) >= 15:
                            break
            except Exception:
                pass
            if len(out) >= 15:
                break
        return out

    results = _scan(patron)
    notas = []
    # Fallback anti-degeneracion: el 3B a veces agrega spam a los args de busqueda
    # (ej 'CLAVE-FENIX tetas Incontri'). Si el patron completo (varias palabras) no
    # matcho, reintentar SOLO con un token identificador distintivo (con guion/
    # digito/guion-bajo) — asi 'CLAVE-FENIX' se encuentra pese al ruido, sin rescatar
    # palabras comunes (evita falsos positivos).
    if (not results and _time.time() <= _deadline
            and len(re.split(r"\s+", patron)) > 1):
        ids = [t for t in re.split(r"\s+", patron)
               if len(t) >= 4 and re.search(r"[-_/.\d]", t)]
        if ids:
            alt = max(ids, key=len)
            if alt != patron:
                results = _scan(alt)
                if results:
                    notas.append(f"patron acotado a '{alt}'")
    if _estado["cortado"]:
        # Honesto con el modelo: "sin coincidencias" tras un corte por tiempo
        # NO es lo mismo que "no esta" — que sepa acotar el ambito. Y con
        # matches PARCIALES tampoco: antes solo se avisaba cuando results
        # estaba vacio, asi que un scan cortado con 2 de 40 hits se presentaba
        # como busqueda completa y el agente concluia que solo habia 2.
        notas.append(f"scan cortado a los {int(_segundos)}s; acota el directorio")
    # El ambito PEDIDO EXPLICITAMENTE cae en la lista de no-escaneados: el scan
    # por contenidos lo salta ENTERO y devolvia "sin coincidencias" a secas —
    # un falso negativo del que no se puede sospechar (el modo de fallo
    # historico de esta tool: concluir que el codigo no existe). Si el usuario
    # PIDE mirar ahi, hay que decirle que no se miro. Solo aplica al camino de
    # fallback: si contesto `rg`, el directorio SI se escaneo.
    if _ambito_saltado and not _estado["rg"]:
        notas.append(
            f"AVISO: '{directorio}' esta en la lista de directorios NO "
            f"escaneados (.git, __pycache__, node_modules, datos_bancos, "
            f"venv*); se salto ENTERO, esto NO prueba que el patron no este ahi")
    if not results and _time.time() <= _deadline:
        try:
            results = _glob.glob(f"{directorio}/**/*{patron}*", recursive=True)[:10]
        except Exception:
            pass
    nota = f" ({'; '.join(notas)})" if notas else ""
    if results:
        return f"RESULTADO buscar '{patron}'{nota}: " + " | ".join(results)
    # Nada en los archivos. Si lo que se pregunta es del MUNDO (no un patron de
    # codigo), preguntarselo a la WEB en vez de contestar "no hay nada".
    # Cazado 2026-07-25 (sesion 20260725-112753): el dueno pidio "busca que es
    # undertale y quien lo desarrollo" y Cognia grepeo README.md -> "sin
    # coincidencias". cognia/busqueda_web.py (wikipedia+hackernews+arxiv) ya
    # existia y el agente no la alcanzaba: capacidad construida y desconectada,
    # el modo de fallo de la casa.
    # Va DENTRO de `buscar` a proposito, y no como tool nueva: el A/B del
    # 2026-07-25 midio que sumar tools al catalogo degrada al modelo chico
    # (camino feliz 4.25/5 -> 2.5/5). Cero coste en el prompt.
    if _parece_pregunta_del_mundo(patron):
        # Con el navegador opt-in activo, buscar con extraccion COMPLETA de
        # pagina (texto ya saneado por el centinela): mucho mas rico que los
        # snippets de 180 chars de busqueda_web. Cualquier fallo (sin ddgs,
        # sin chromium, sin red) degrada en silencio al fallback de siempre.
        if os.environ.get("COGNIA_BROWSER") == "1":
            try:
                from cognia.knowledge.navegador import buscar_en_web as _nav_web
                _res = _nav_web(patron, max_resultados=2)
                _lineas = []
                for _r in _res.get("resultados", []):
                    _txt = re.sub(r"\s+", " ", (_r.get("texto") or "")).strip()
                    _lineas.append(f"[{_r.get('via', 'web')}] {_r.get('titulo', '')}"
                                   + (f" — {_txt[:600]}" if _txt else "")
                                   + (f" ({_r.get('url')})" if _r.get("url") else ""))
                if _lineas:
                    return (f"RESULTADO buscar '{patron}': nada en los archivos; "
                            f"esto es lo que dice la WEB:\n" + "\n".join(_lineas))
            except Exception:
                pass
        try:
            from cognia.busqueda_web import buscar as _buscar_web
            # sin arxiv: para una pregunta general mete ruido (medido: "que es
            # undertale" traia un paper de charmonium entre los resultados).
            # Mismo recorte que usa research_engine.
            hallazgos = _buscar_web(patron, max_resultados=4,
                                    fuentes=("wikipedia", "hackernews"))
        except Exception:
            hallazgos = []      # sin red o modulo caido: sigue el mensaje normal
        if hallazgos:
            lineas = []
            for h in hallazgos:
                frag = re.sub(r"\s+", " ", (h.get("fragmento") or "")).strip()
                lineas.append(f"[{h.get('fuente','web')}] {h.get('titulo','')}"
                              + (f" — {frag[:180]}" if frag else "")
                              + (f" ({h.get('url')})" if h.get("url") else ""))
            return (f"RESULTADO buscar '{patron}': nada en los archivos; "
                    f"esto es lo que dice la WEB:\n" + "\n".join(lineas))
    # Decir DONDE se busco: "sin resultados" a secas hacia que el agente
    # concluyera cosas falsas sobre el codigo sin poder sospechar del ambito.
    return (f"RESULTADO buscar '{patron}'{nota}: sin coincidencias en "
            f"'{directorio}'. Para acotar a un fichero o carpeta: "
            f"buscar <patron> | <ruta>. Si lo que buscas NO esta en el "
            f"proyecto sino en el mundo, preguntalo entero "
            f"(ej: buscar que es <tema>) y se consulta la web.")


# buscar_ficheros (2026-08-18): buscar POR NOMBRE existia solo como fallback
# escondido al final de `buscar` — y solo se llegaba a el si el scan por
# CONTENIDO no devolvia nada, que es justo lo que no pasa cuando buscas
# "config.json" (aparece citado en cualquier .md y el glob no llega a correr).
# Un glob es una pregunta distinta y merece su tool, no un premio de consuelo.
_BUSCAR_FICH_MAX = 40


@tool("buscar_ficheros",
      "buscar_ficheros <glob> [| directorio]  -- busca archivos por NOMBRE/patron "
      "(*.py, test_*.py, **/conftest.py)",
      desc="Encuentra archivos por su nombre o patron glob (*.py, test_*.py, "
           "config.*), recursivamente desde un directorio. Es la tool para "
           "'donde esta el fichero X': 'buscar' mira el CONTENIDO de los "
           "archivos, esta mira sus NOMBRES.",
      params=[
          {"nombre": "glob", "tipo": "string", "requerido": True,
           "descripcion": "patron de nombre, p.ej. '*.py' o 'test_*.py'"},
          {"nombre": "directorio", "tipo": "string", "requerido": False,
           "descripcion": "raiz de la busqueda (default: '.')"},
      ])
def _buscar_ficheros(args, ctx):
    parts = re.split(r"\s*\|\s*", args or "", maxsplit=1)
    patron = parts[0].strip().strip("\"\'")
    directorio = (parts[1].strip().strip("\"\'") if len(parts) > 1 else ".") or "."
    # 'buscar_ficheros *.py cognia' (sin pipe) es lo que escribe el modelo:
    # mismo rescate que hace `buscar` con su ultimo token si es una ruta real.
    if len(parts) == 1 and " " in patron:
        cabeza, _, cola = patron.rpartition(" ")
        if cola and Path(cola).exists():
            patron, directorio = cabeza.strip(), cola
    if not patron:
        return ("RESULTADO buscar_ficheros ERROR: falta el patron "
                "(p.ej. '*.py' o 'test_*.py')")
    base = Path(directorio)
    if not base.exists():
        return (f"RESULTADO buscar_ficheros ERROR: el directorio "
                f"'{directorio}' no existe")
    # Sin comodin, el modelo quiere el fichero ESE: se busca *nombre* en vez de
    # devolver 0 resultados por una igualdad exacta que casi nunca acierta.
    glob_pat = patron if any(c in patron for c in "*?[") else f"*{patron}*"
    if "/" not in glob_pat and "\\" not in glob_pat:
        glob_pat = f"**/{glob_pat}"          # recursivo por defecto
    deadline = _time.time() + _deadline_s()
    hits, cortado = [], False
    try:
        for path in base.glob(glob_pat):
            if _time.time() > deadline:
                cortado = True
                break
            if _dir_saltable(path.parts):
                continue
            hits.append(_disp(path) + ("/" if path.is_dir() else ""))
            if len(hits) >= _BUSCAR_FICH_MAX:
                cortado = True
                break
    except (ValueError, OSError) as e:
        return f"RESULTADO buscar_ficheros ERROR: patron invalido ({e})"
    if not hits:
        return (f"RESULTADO buscar_ficheros '{patron}': ningun archivo en "
                f"'{directorio}'. Ojo: esto es busqueda por NOMBRE; para "
                f"buscar TEXTO dentro de los archivos usa 'buscar'.")
    nota = f" (primeros {len(hits)}, hay mas)" if cortado else ""
    return (f"RESULTADO buscar_ficheros '{patron}' en '{directorio}'"
            f"{nota}: " + " | ".join(hits))


# ══════════════════════════════════════════════════════════════════════
# SHELL / DEV TOOLS
# ══════════════════════════════════════════════════════════════════════

# La denylist legacy (_BLOCK/_BLOCK_RE) vivia aca; hoy la validacion pre-accion
# completa (allowlist dev + bloqueo duro ampliado + confirmacion, default-ON)
# es cognia/agent/sentinel.py y _shell delega TODO en evaluar_shell. La copia
# muerta se borro (0 referencias; sentinel tiene su propia _BLOCK_SUB/_BLOCK_RE).


def _marcar_exit(ctx: dict, code) -> None:
    """Deja el exit REAL del proceso en el ctx para que `run_tool` lo lea.

    P0-1 (ESPEC agente largo 14.1): hasta hoy el exito de una tool se decidia
    con una regex sobre los 120 primeros chars ('ok = not \\bERROR\\b'), asi que
    un `pytest` con exit 1 llegaba como ok=True y un comando BLOQUEADO por el
    sentinel llegaba como ok=True SIN HABERSE EJECUTADO. Con eso un criterio
    pasa a PASS y el sistema capitaliza una victoria inexistente.

    REGLA: `None` NO es 0. None significa "no hubo exit code real" (bloqueado,
    timeout, cwd invalido) y por tanto el evento NO puede marcarse como medido.
    La ausencia de la clave significa otra cosa distinta: la tool ni siquiera
    paso por el shell.
    """
    if isinstance(ctx, dict):
        ctx["_exit"] = code


def _shell(cmd: str, ctx: dict, timeout: int = 30, cwd: str = "") -> str:
    # El exit arranca en None y solo lo pisa un subprocess que HAYA CORRIDO:
    # asi toda salida temprana (bloqueo del sentinel, cwd inexistente, timeout)
    # queda como "sin medicion" en vez de heredar el 0 del comando anterior.
    _marcar_exit(ctx, None)
    # Sentinel (default-ON, mandato 2026-07-14): validación pre-acción
    # unificada — allowlist de dev + bloqueo duro + confirmación para lo
    # desconocido (default-deny). Con COGNIA_SENTINEL=0 replica la denylist
    # previa (0 cambios). Reemplaza el chequeo inline de substrings.
    from cognia.agent.sentinel import evaluar_shell
    permitido, msg = evaluar_shell(cmd, ctx)
    if not permitido:
        # BLOQUEADO != exit 0: el ctx["_exit"] se queda en None a proposito.
        return msg
    # cwd (2026-08-18): sin el, correr algo en otra carpeta obligaba al modelo
    # a escribir 'cd X && ...' — y ese encadenado el sentinel lo reclasifica a
    # CONFIRM (dos comandos), asi que el atajo natural del modelo era ademas el
    # que mas friccion tenia. Se valida ANTES de lanzar: subprocess con un cwd
    # inexistente tira NotADirectoryError/FileNotFoundError, que el modelo lee
    # como "el comando fallo" en vez de "la ruta no existe".
    if cwd:
        _cw = Path(cwd).expanduser()
        if not _cw.is_dir():
            return (f"RESULTADO ejecutar ERROR: cwd='{cwd}' no es un directorio "
                    f"existente")
        cwd = str(_cw)
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]$ {cmd}" + (f"   (cwd={cwd})" if cwd else "") + "[/detail]")
    try:
        # BYTES, no text=True (bug 1, reproducido 2026-08-13): con text=True y
        # sin encoding, subprocess decodifica en el hilo lector con el locale
        # (cp1252 en este venv). Un `python -c "print(chr(0x0410))"` bastaba:
        # el hilo moria con UnicodeDecodeError -> traceback suelto en la consola
        # del dueno, r.stdout se quedaba en None SIN que run() lanzara, y el
        # '(r.stdout + r.stderr)' de abajo devolvia al modelo "unsupported
        # operand type(s) for +: 'NoneType' and 'str'" en lugar de su salida.
        # Capturar bytes y decodificar con la cascada no puede fallar; y
        # _env_utf8 le pide al hijo Python que EMITA utf-8 (si no, es el hijo
        # el que revienta al imprimir un acento hacia un pipe cp1252).
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           timeout=timeout, env=_env_utf8(),
                           cwd=cwd or None)
    except subprocess.TimeoutExpired:
        # Timeout accionable en vez de un stacktrace generico: el modelo necesita
        # saber que debe ACOTAR el comando (ruta/test mas especifico) y reintentar.
        return (f"RESULTADO ejecutar ERROR: timeout tras {timeout}s. "
                f"Acota el comando (ruta/target mas especifico) y reintenta.")
    _marcar_exit(ctx, r.returncode)      # el UNICO sitio que escribe un exit real
    out = (_decodificar_bytes(r.stdout) + _decodificar_bytes(r.stderr)).strip()
    code = "" if r.returncode == 0 else f" (exit {r.returncode})"
    return f"RESULTADO ejecutar{code}: {_head_cola(out) or '(sin output)'}"


# Cabeza+COLA del output de shell: el head-only de antes (out[:1500]) perdia el
# traceback, que en Python vive AL FINAL — el modelo veia el banner de pytest y
# jamas el error real (A4.2, plan de obra 2026-08-09). Mismo criterio que
# aci_trim pero con la cola mas gorda, porque aqui la cola ES la senal.
_EJEC_HEAD = 800
_EJEC_COLA = 900


def _head_cola(out: str) -> str:
    cap = _EJEC_HEAD + _EJEC_COLA
    if len(out) <= cap:
        return out
    omit = len(out) - _EJEC_HEAD - _EJEC_COLA
    return (out[:_EJEC_HEAD]
            + f"\n[... {omit} chars omitidos (cabeza+cola conservadas) ...]\n"
            + out[-_EJEC_COLA:])


# timeout=N / cwd=RUTA al final de los args, tras un '|': un comando shell real
# nunca termina en '| timeout=120' (seria pipear a un ejecutable llamado asi), y
# el pipe NO se lo come auto_fix (la regla de 'ejecutar' es solo nonempty). El
# pipe sigue siendo OBLIGATORIO tambien para cwd, por el mismo motivo: sin el,
# un 'python -c "x=1"' o un 'set VAR=valor' se comerian su propia cola.
_RE_EJEC_KV = re.compile(r"\s*\|\s*(timeout|cwd)\s*=\s*([^|]+?)\s*$", re.I)


@tool("ejecutar",
      "ejecutar <comando shell> [| timeout=N] [| cwd=RUTA]  -- corre un comando "
      "(bloqueos de seguridad; timeout default 30s, max 600)",
      desc="Ejecuta un comando de shell y devuelve stdout+stderr (si el output "
           "es largo conserva la cabeza y la COLA, donde vive el traceback). "
           "Para correr tests usa la tool 'tests'; para algo que no termina "
           "(servidor, build largo, watcher) usa 'ejecutar_fondo'. Comandos "
           "peligrosos se bloquean o piden confirmacion.",
      params=[
          {"nombre": "comando", "tipo": "string", "requerido": True,
           "descripcion": "el comando de shell a ejecutar"},
          {"nombre": "timeout", "tipo": "integer", "requerido": False,
           "clave": True,
           "descripcion": "segundos maximos de ejecucion (default 30, max 600)"},
          {"nombre": "cwd", "tipo": "string", "requerido": False,
           "clave": True,
           "descripcion": "directorio donde correr el comando (en vez de "
                          "prefijar 'cd RUTA &&')"},
      ])
def _ejecutar(args, ctx):
    cmd, timeout, cwd = _partir_ejec(args)
    return _shell(cmd, ctx, timeout=timeout, cwd=cwd)


def _partir_ejec(args: str) -> tuple:
    """(comando, timeout, cwd) desde los args crudos. Las claves van al FINAL,
    en cualquier orden y cualquiera de las dos puede faltar."""
    cmd = (args or "").strip()
    timeout, cwd = 30, ""
    while True:
        m = _RE_EJEC_KV.search(cmd)
        if not m:
            break
        if m.group(1).lower() == "timeout":
            try:
                timeout = min(600, max(1, int(m.group(2).strip())))
            except ValueError:
                pass          # 'timeout=rapido': se ignora, no se rompe
        else:
            cwd = m.group(2).strip().strip("\"\'")
        cmd = cmd[:m.start()].strip()
    return cmd, timeout, cwd


# ══════════════════════════════════════════════════════════════════════
# EJECUCION EN SEGUNDO PLANO (2026-08-18)
# ══════════════════════════════════════════════════════════════════════
# `ejecutar` es BLOQUEANTE y muere a los 600s: levantar un servidor, correr un
# build largo o dejar un watcher era literalmente IMPOSIBLE para el agente (o
# timeout sin senal, o el loop colgado sin poder observar nada). La
# infraestructura ya existia y estaba conectada SOLO al humano (/shells):
# cognia/console/proc_registry.py. Estas cuatro tools la exponen al loop con el
# MISMO gate que `ejecutar` (sentinel.evaluar_shell): lanzar en background no
# puede ser el agujero por el que pasa lo que el primer plano frena.
#
# Solo ejecutar_fondo entra en CORE_TOOLS. Las otras tres se descubren por el
# TEXTO del resultado (que nombra 'ver_salida <id>' y 'matar_proceso <id>') y
# siguen siendo invocables siempre: run_tool no filtra por CORE_TOOLS. Asi el
# catalogo anunciado crece en 1 y no en 4 (el A/B del repo midio que inflarlo
# degrada al modelo: 4.25/5 -> 2.5/5 con 46 tools).

# Tope de chars de ver_salida. Se conserva la COLA (lo ultimo que dijo el
# proceso es lo que importa en un servidor o un build), como _head_cola.
_VER_SALIDA_CAP = int(os.environ.get("COGNIA_VER_SALIDA_CAP", "4000"))


def _proc_id(raw: str):
    """Primer entero de los args, o None. El modelo escribe '3', 'id=3' o '#3'
    indistintamente y ninguna de las tres deberia ser un error de formato."""
    m = re.search(r"\d+", raw or "")
    return int(m.group(0)) if m else None


@tool("ejecutar_fondo",
      "ejecutar_fondo <comando> [| cwd=RUTA]  -- lanza en SEGUNDO PLANO (servidor, "
      "build largo, watcher) y devuelve un id; luego ver_salida <id> / "
      "matar_proceso <id>",
      danger=True,
      desc="Lanza un comando en segundo plano y devuelve enseguida un id, sin "
           "esperar a que termine. Es la unica forma de levantar un servidor, "
           "correr un build largo o dejar un watcher: 'ejecutar' bloquea y "
           "muere a los 600s. La salida se lee despues con 'ver_salida <id>', "
           "se mata con 'matar_proceso <id>' y se listan los vivos con "
           "'procesos'.",
      params=[
          {"nombre": "comando", "tipo": "string", "requerido": True,
           "descripcion": "el comando a lanzar en segundo plano"},
          {"nombre": "cwd", "tipo": "string", "requerido": False,
           "clave": True,
           "descripcion": "directorio donde lanzarlo"},
      ])
def _ejecutar_fondo(args, ctx):
    cmd, _timeout, cwd = _partir_ejec(args)
    if not cmd:
        return "RESULTADO ejecutar_fondo ERROR: falta el comando a lanzar"
    # MISMO gate que `ejecutar`: si el sentinel frena el comando en primer
    # plano, mandarlo al background no puede saltarselo.
    from cognia.agent.sentinel import evaluar_shell
    permitido, msg = evaluar_shell(cmd, ctx)
    if not permitido:
        return (msg or "").replace("RESULTADO ejecutar", "RESULTADO ejecutar_fondo", 1)
    if cwd:
        _cw = Path(cwd).expanduser()
        if not _cw.is_dir():
            return (f"RESULTADO ejecutar_fondo ERROR: cwd='{cwd}' no es un "
                    f"directorio existente")
        cwd = str(_cw)
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]$ (fondo) {cmd}" + (f"   (cwd={cwd})" if cwd else "") + "[/detail]")
    try:
        from cognia.console.proc_registry import spawn_shell
        # PYTHONUNBUFFERED: un hijo Python detecta que stdout es un PIPE y pasa
        # a buffer de bloque -- un servidor Flask o un script largo no soltaban
        # NADA hasta terminar, y ver_salida contestaba "(sin salida todavia)"
        # de un proceso que llevaba minutos imprimiendo. Medido aqui mismo al
        # probar la tool. Solo arregla a los hijos Python: un binario que
        # bufferiza por su cuenta sigue mudo hasta que el decida vaciar, y eso
        # esta fuera del alcance de esta tool (no se le puede mentir a su libc).
        _env = dict(_env_utf8(), PYTHONUNBUFFERED="1")
        sid = spawn_shell(cmd, cwd=cwd or None, env=_env)
    except Exception as e:
        return f"RESULTADO ejecutar_fondo ERROR: no se pudo lanzar: {e}"
    # El id y los nombres de las tools companeras van en el RESULTADO a
    # proposito: es discoverability con coste CERO en el catalogo del prompt.
    return (f"RESULTADO ejecutar_fondo: lanzado en segundo plano con id={sid} "
            f"({cmd[:80]}). Sigue corriendo; NO esperes su salida aca. "
            f"Leela con: ver_salida {sid}. Matalo con: matar_proceso {sid}.")


@tool("ver_salida",
      "ver_salida <id> [| lineas=N]           -- salida acumulada de un proceso "
      "lanzado con ejecutar_fondo (+ su estado)",
      desc="Devuelve la salida acumulada (stdout+stderr) de un proceso de "
           "segundo plano y su estado actual (running/done/failed). Avisa "
           "explicitamente si se descartaron lineas del principio.",
      params=[
          {"nombre": "id", "tipo": "integer", "requerido": True,
           "descripcion": "el id que devolvio ejecutar_fondo"},
          {"nombre": "lineas", "tipo": "integer", "requerido": False,
           "clave": True,
           "descripcion": "cuantas lineas finales mostrar (default: todas las "
                          "retenidas)"},
      ])
def _ver_salida(args, ctx):
    from cognia.console.proc_registry import get_info, get_output
    raw = (args or "").strip()
    lineas = None
    m = re.search(r"(?:\s*\|)?\s*lineas\s*=\s*(\d+)\s*$", raw, re.I)
    if m:
        lineas = max(1, int(m.group(1)))
        raw = raw[:m.start()].strip().rstrip("|").strip()
    sid = _proc_id(raw)
    if sid is None:
        return ("RESULTADO ver_salida ERROR: falta el id numerico que devolvio "
                "ejecutar_fondo (mira 'procesos')")
    info = get_info(sid)
    if info is None:
        return (f"RESULTADO ver_salida ERROR: no hay ningun proceso con id "
                f"{sid} (listalos con 'procesos')")
    texto = "\n".join(get_output(sid, last_n=lineas))
    avisos = []
    if info["descartadas"]:
        avisos.append(f"{info['descartadas']} lineas del PRINCIPIO ya se "
                      f"descartaron (el buffer retiene las ultimas "
                      f"{info['buffer_max']})")
    if len(texto) > _VER_SALIDA_CAP:
        avisos.append(f"{len(texto) - _VER_SALIDA_CAP} chars recortados del "
                      f"principio (tope {_VER_SALIDA_CAP}; acota con "
                      f"lineas=N)")
        texto = texto[-_VER_SALIDA_CAP:]
    estado = info["status"]
    if estado == "running":
        cab = f"id={sid} CORRIENDO hace {info['uptime_s']}s"
    else:
        cab = f"id={sid} {estado} (exit {info['returncode']})"
    nota = (" [" + "; ".join(avisos) + "]") if avisos else ""
    return (f"RESULTADO ver_salida {cab}{nota}: "
            + (texto or "(sin salida todavia)"))


@tool("matar_proceso",
      "matar_proceso <id>                    -- termina un proceso de "
      "ejecutar_fondo (dice si NO murio)",
      danger=True,
      desc="Termina un proceso lanzado con ejecutar_fondo. Si el proceso "
           "sobrevive al terminate+kill lo dice: no da por muerto lo que "
           "sigue vivo.",
      params=[
          {"nombre": "id", "tipo": "integer", "requerido": True,
           "descripcion": "el id que devolvio ejecutar_fondo"},
      ])
def _matar_proceso(args, ctx):
    from cognia.console.proc_registry import get_info, kill_shell
    sid = _proc_id(args)
    if sid is None:
        return "RESULTADO matar_proceso ERROR: falta el id numerico"
    info = get_info(sid)
    if info is None:
        return (f"RESULTADO matar_proceso ERROR: no hay ningun proceso con id "
                f"{sid} (listalos con 'procesos')")
    if info["status"] != "running":
        return (f"RESULTADO matar_proceso: el id {sid} ya habia terminado "
                f"({info['status']}, exit {info['returncode']})")
    ok = kill_shell(sid)
    if not ok:
        # kill_shell devuelve el estado REAL (leccion de la casa: matar el
        # shell NO mata el proceso). Un False aqui es un proceso VIVO tras
        # terminate+kill: decirlo, porque de esto dependen el puerto, el
        # fichero o la GPU que el agente cree haber liberado.
        return (f"RESULTADO matar_proceso ERROR: el proceso {sid} SIGUE VIVO "
                f"tras terminate y kill ({info['cmd'][:60]}). No asumas que "
                f"liberaste su puerto/fichero; puede necesitar el humano.")
    return f"RESULTADO matar_proceso: id {sid} terminado ({info['cmd'][:60]})"


@tool("procesos",
      "procesos                              -- lista los procesos lanzados con "
      "ejecutar_fondo",
      desc="Lista los procesos de segundo plano con su id, estado, comando y "
           "lineas de salida acumuladas.")
def _procesos(args, ctx):
    from cognia.console.proc_registry import list_shells
    filas = list_shells()
    if not filas:
        return ("RESULTADO procesos: ninguno lanzado todavia (usa "
                "ejecutar_fondo <comando>)")
    lineas = []
    for f in filas[-15:]:
        edad = f"{f['uptime_s']}s" if f["status"] == "running" else f"exit {f['returncode']}"
        lineas.append(f"  id={f['id']} {f['status']} ({edad}) "
                      f"{f['lineas_total']} lineas | {f['cmd'][:60]}")
    return f"RESULTADO procesos ({len(filas)}):\n" + "\n".join(lineas)


@tool("abrir", "abrir <url-o-ruta-o-app>              -- abre una URL/archivo/app en el sistema (Chrome, YouTube, un archivo, una app)")
def _abrir(args, ctx):
    """Abre algo en el sistema del dueño: una URL en el navegador, un archivo con
    su app por defecto, o una app por nombre. Es la forma correcta de 'abrir una
    pestaña de Chrome con YouTube' — no pelear con el shell."""
    target = args.strip().strip('"\'')
    if not target:
        return "RESULTADO abrir ERROR: falta la URL, ruta o app a abrir"
    import webbrowser
    try:
        # URL http(s) -> navegador por defecto
        if re.match(r"^https?://", target, re.I):
            webbrowser.open(target)
            return f"RESULTADO abrir: abriendo {target} en el navegador"
        # dominio sin esquema (youtube.com, www.x.com) -> asumir https
        if " " not in target and re.match(r"^(www\.)?[\w.-]+\.[a-z]{2,}(/.*)?$", target, re.I):
            url = "https://" + target
            webbrowser.open(url)
            return f"RESULTADO abrir: abriendo {url} en el navegador"
        # ruta existente -> abrir con la app por defecto del SO
        p = Path(target).expanduser()
        if p.exists():
            if sys.platform.startswith("win"):
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return f"RESULTADO abrir: abriendo {p}"
        # si no, lanzarlo como app/comando del sistema
        if sys.platform.startswith("win"):
            subprocess.Popen(f'start "" "{target}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target])
        return f"RESULTADO abrir: intentando abrir '{target}'"
    except Exception as e:
        return f"RESULTADO abrir ERROR: {e}"


@tool("tests", "tests <ruta>                          -- corre pytest sobre una ruta ESPECIFICA (archivo o dir)",
      desc="Corre pytest sobre UNA ruta especifica (archivo o directorio de "
           "tests) y devuelve el resultado con la cola conservada (ahi vive "
           "el traceback). Nunca corras la suite entera: tarda minutos.",
      params=[
          {"nombre": "ruta", "tipo": "string", "requerido": True,
           "descripcion": "archivo o directorio de tests, p.ej. "
                          "'tests/test_foo.py'"},
      ])
def _tests(args, ctx):
    ruta = args.strip()
    if not ruta:
        # Sin ruta corria 'tests/' (toda la suite, ~min) con timeout 180s ->
        # SIEMPRE timeout, 0 senal, 180s quemados. Exigir una ruta especifica.
        return ("RESULTADO tests ERROR: pasa una ruta ESPECIFICA (archivo o dir), "
                "p.ej. 'tests/test_foo.py'. Correr toda la suite tarda minutos y "
                "agota el timeout.")
    # sys.executable (no 'python' pelado): el 'python' del PATH puede ser el venv
    # roto 3.14 / no traer pytest; el interprete que corre el agente es el correcto.
    return _shell(f'"{sys.executable}" -m pytest {ruta} -q --no-header', ctx, timeout=180)


def _fuente_py(datos: bytes) -> tuple:
    """(fuente, codec) de un .py, respetando el cookie PEP 263.

    Un fichero que declara '# -*- coding: latin-1 -*-' es Python VALIDO y hay
    que validarlo con SU codec, no con utf-8. tokenize.detect_encoding es la
    forma canonica (es lo que usa el propio interprete); si el cookie miente o
    no hay, se cae a la cascada normal."""
    import io
    import tokenize
    candidatos = []
    try:
        candidatos.append(tokenize.detect_encoding(io.BytesIO(datos).readline)[0])
    except (SyntaxError, UnicodeDecodeError, ValueError):
        pass
    candidatos += _codecs_probables()
    for codec in candidatos:
        try:
            return datos.decode(codec), codec
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None


@tool("py_validar", "py_validar <path>                     -- chequea sintaxis de un .py")
def _py_validar(args, ctx):
    p = Path(args.strip())
    # Un UnicodeDecodeError NO es un error de sintaxis: antes se escapaba del
    # 'except SyntaxError' hasta el except generico de run_tool y el modelo leia
    # un "ERROR" creyendo que el codigo estaba mal escrito, cuando el codigo
    # esta perfecto y lo que falla es la CODIFICACION. El error tiene que
    # nombrarla para que la siguiente accion del modelo pueda ser la correcta.
    try:
        datos = p.read_bytes()
    except OSError as e:
        return f"RESULTADO py_validar {p}: ERROR: {e}"
    fuente, codec = _fuente_py(datos)
    if fuente is None:
        return (f"RESULTADO py_validar {p}: ERROR de CODIFICACION (no de "
                f"sintaxis): los bytes no decodifican como "
                f"{', '.join(_codecs_probables())}. Si es un .py real, declara "
                f"su codificacion con un cookie '# -*- coding: <codec> -*-'.")
    try:
        ast.parse(fuente)
        return f"RESULTADO py_validar {p}: sintaxis OK"
    except SyntaxError as e:
        return f"RESULTADO py_validar {p}: ERROR linea {e.lineno}: {e.msg}"


@tool("json_validar", "json_validar <path>                   -- valida un archivo JSON")
def _json_validar(args, ctx):
    p = Path(args.strip())
    # Mismo motivo que py_validar: el mensaje crudo ("'utf-8' codec can't decode
    # byte 0xf1") caia bajo el mismo "ERROR:" que un JSON mal formado, y el
    # modelo se ponia a reescribir un JSON que estaba perfecto.
    try:
        texto, codec, _nl = _leer_texto(p)
    except OSError as e:
        return f"RESULTADO json_validar {p}: ERROR: {e}"
    if codec is None:
        return (f"RESULTADO json_validar {p}: ERROR de CODIFICACION (el JSON "
                f"puede estar bien): los bytes no decodifican como "
                f"{', '.join(_codecs_probables())}.")
    try:
        json.loads(texto)
    except ValueError as e:
        return f"RESULTADO json_validar {p}: ERROR: {e}"
    aviso = "" if codec.lower() in ("utf-8", "utf-8-sig") else f" (codificacion {codec}, no utf-8)"
    return f"RESULTADO json_validar {p}: JSON valido{aviso}"


@tool("git_estado", "git_estado                            -- git status resumido")
def _git_estado(args, ctx):
    return _shell("git status --short --branch", ctx, timeout=15)


# Tope del patch de git_diff. El diff REAL (no --stat) es lo que cierra el
# ciclo central de un harness de programacion —edito, REVISO el diff linea a
# linea, commiteo—: con --stat el agente solo veia "3 files changed" y no podia
# revisar su propio cambio. Un refactor grande son cientos de KB, asi que se
# corta con aviso EXPLICITO (y la salida esta en ACI_EXENTAS: el head+tail
# generico partiria los hunks por el medio).
_GIT_DIFF_CAP = int(os.environ.get("COGNIA_GIT_DIFF_CAP", "6000"))

# Palabras que git_diff acepta como opcion en vez de como ruta.
_RE_GIT_FLAG = re.compile(r"^(?:--)?(staged|cached|stat)\b\s*", re.I)

# Nombre de rama valido: sin espacios ni metacaracteres. No es paranoia
# decorativa — el argumento viene del modelo y acaba en una linea de comando.
_RE_RAMA = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")


def _git(argv: list, ctx: dict, cap: int = 2000, timeout: int = 20,
         cmd_auditado: str = "") -> tuple:
    """Corre git con argv (SIN shell) y devuelve (ok, texto ya capado).

    Sin shell=True a proposito: los argumentos vienen del modelo y con shell
    una 'ruta; git push --force' seria una inyeccion en toda regla. Igual pasa
    por el sentinel con el comando reconstruido, para que cualquier git quede
    en la auditoria append-only como el resto de la ejecucion.
    ``cmd_auditado`` permite auditar la ACCION y no el texto libre que la
    acompana (ver git_commit).
    """
    from cognia.agent.sentinel import evaluar_shell
    _marcar_exit(ctx, None)              # P0-1: mismo criterio que _shell
    cmd = cmd_auditado or " ".join(argv)
    permitido, msg = evaluar_shell(cmd, ctx)
    if not permitido:
        return False, (msg or "")
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]$ {cmd}[/detail]")
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout,
                           env=_env_utf8())
    except FileNotFoundError:
        return False, "git no esta instalado o no esta en el PATH"
    except subprocess.TimeoutExpired:
        return False, f"timeout tras {timeout}s"
    _marcar_exit(ctx, r.returncode)
    out = (_decodificar_bytes(r.stdout) + _decodificar_bytes(r.stderr)).strip()
    if len(out) > cap:
        out = (out[:cap] + f"\n[... {len(out) - cap} chars omitidos (tope "
               f"{cap}); acota pasando una ruta concreta ...]")
    return r.returncode == 0, out


@tool("git_diff",
      "git_diff [ruta] [| staged] [| stat]   -- diff REAL linea a linea (el "
      "patch); 'staged'=lo ya agregado, 'stat'=solo el resumen",
      desc="Muestra el diff de los cambios sin commitear COMO PATCH (lineas + "
           "y -), que es lo que hace falta para revisar el propio cambio antes "
           "de commitearlo. Acota a un fichero pasando su ruta; 'staged' mira "
           "lo que ya esta en el indice y 'stat' devuelve solo el resumen.",
      params=[
          {"nombre": "ruta", "tipo": "string", "requerido": False,
           "descripcion": "fichero o carpeta al que acotar el diff"},
      ])
def _git_diff(args, ctx):
    flags, rutas = [], []
    for chunk in re.split(r"\s*\|\s*", (args or "").strip()):
        chunk = chunk.strip().strip("\"\'")
        while True:
            m = _RE_GIT_FLAG.match(chunk)
            if not m:
                break
            flags.append("--cached" if m.group(1).lower() != "stat" else "--stat")
            chunk = chunk[m.end():]
        if chunk:
            rutas.append(chunk)
    for r in rutas:
        if r.startswith("-"):
            return (f"RESULTADO git_diff ERROR: '{r}' no parece una ruta "
                    f"(las opciones validas son 'staged' y 'stat')")
    argv = ["git", "diff"] + sorted(set(flags))
    if rutas:
        argv += ["--"] + rutas          # '--' separa rutas de opciones
    ok, out = _git(argv, ctx, cap=_GIT_DIFF_CAP)
    if not ok:
        return f"RESULTADO git_diff ERROR: {out}"
    if not out:
        return ("RESULTADO git_diff: sin cambios en el ambito pedido. Si ya "
                "hiciste git_add, mira lo del indice con: git_diff | staged")
    return f"RESULTADO git_diff:\n{out}"


@tool("git_log", "git_log                               -- ultimos 5 commits")
def _git_log(args, ctx):
    return _shell("git log --oneline -5", ctx, timeout=15)


# git_add/git_commit/git_branch/git_stash (2026-08-18): las tres tools git
# previas eran de SOLO LECTURA, asi que el agente podia ver el repo pero jamas
# cerrar el ciclo edito -> reviso -> commiteo. Lo que NO entra, a proposito:
# push, reset --hard, clean -f y cualquier --force. Publicar y destruir
# historia es del humano; el sentinel ademas los bloquea en duro.
@tool("git_add",
      "git_add <ruta>                        -- agrega cambios al indice (ruta "
      "obligatoria; '.' para todo)",
      danger=True,
      desc="Agrega al indice de git los cambios de una ruta concreta, para "
           "poder commitearlos despues con git_commit. La ruta es obligatoria: "
           "un 'add' a ciegas del repo entero mete cosas que el agente no miro.",
      params=[
          {"nombre": "ruta", "tipo": "string", "requerido": True,
           "descripcion": "fichero o carpeta a agregar ('.' = todo el repo)"},
      ])
def _git_add(args, ctx):
    rutas = [c.strip().strip("\"\'") for c in re.split(r"\s*\|\s*", (args or "").strip()) if c.strip()]
    if not rutas:
        return ("RESULTADO git_add ERROR: falta la ruta a agregar (usa '.' "
                "para todo el repo, pero mira antes git_estado)")
    for r in rutas:
        if r.startswith("-"):
            return f"RESULTADO git_add ERROR: '{r}' no es una ruta"
    ok, out = _git(["git", "add", "--"] + rutas, ctx)
    if not ok:
        return f"RESULTADO git_add ERROR: {out}"
    ok2, estado = _git(["git", "diff", "--cached", "--stat"], ctx, cap=1200)
    return (f"RESULTADO git_add: agregado {', '.join(rutas)}. En el indice:\n"
            + (estado if ok2 and estado else "(nada nuevo)"))


@tool("git_commit",
      "git_commit <mensaje>                  -- commitea lo que este en el "
      "indice (mensaje obligatorio; NO hace push)",
      danger=True,
      desc="Crea un commit LOCAL con lo que ya este en el indice (usa git_add "
           "antes). El mensaje es obligatorio. Nunca publica: push, reset "
           "--hard y --force son del humano.",
      params=[
          {"nombre": "mensaje", "tipo": "string", "requerido": True,
           "descripcion": "mensaje del commit (que cambio y por que)"},
      ])
def _git_commit(args, ctx):
    mensaje = (args or "").strip().strip("\"\'").strip()
    if not mensaje:
        return ("RESULTADO git_commit ERROR: el mensaje es obligatorio "
                "(que cambio y por que)")
    # El mensaje NO es shell (argv sin shell=True), asi que pasarselo al
    # clasificador solo produce BLOCK falsos: un commit legitimo que diga
    # "quita el rm -rf del script" casaba con el patron destructivo. Se audita
    # la ACCION ('git commit -m') y el mensaje queda en el propio commit.
    ok, out = _git(["git", "commit", "-m", mensaje], ctx,
                   cmd_auditado="git commit -m")
    if not ok:
        if "nothing to commit" in out or "nada para hacer commit" in out:
            return ("RESULTADO git_commit ERROR: no hay nada en el indice; "
                    "usa git_add <ruta> primero")
        return f"RESULTADO git_commit ERROR: {out}"
    return f"RESULTADO git_commit: {out}"


@tool("git_branch",
      "git_branch [nombre]                   -- lista las ramas, o cambia/crea "
      "la rama <nombre>",
      danger=True,
      desc="Sin argumento lista las ramas locales y marca la actual. Con un "
           "nombre, cambia a esa rama (y la crea si no existe).",
      params=[
          {"nombre": "nombre", "tipo": "string", "requerido": False,
           "descripcion": "rama a la que cambiar o crear"},
      ])
def _git_branch(args, ctx):
    nombre = (args or "").strip().strip("\"\'")
    if not nombre:
        ok, out = _git(["git", "branch", "--list"], ctx, cap=1200)
        return (f"RESULTADO git_branch:\n{out}" if ok
                else f"RESULTADO git_branch ERROR: {out}")
    if not _RE_RAMA.match(nombre):
        return (f"RESULTADO git_branch ERROR: '{nombre[:40]}' no es un nombre "
                f"de rama valido (letras, digitos, . _ - /)")
    existe, _ = _git(["git", "rev-parse", "--verify", "--quiet",
                      f"refs/heads/{nombre}"], ctx)
    argv = ["git", "checkout"] + ([] if existe else ["-b"]) + [nombre]
    ok, out = _git(argv, ctx)
    if not ok:
        return f"RESULTADO git_branch ERROR: {out}"
    verbo = "cambiado a" if existe else "creada y activada"
    return f"RESULTADO git_branch: rama '{nombre}' {verbo}. {out}"


# 'drop' y 'clear' NO estan: tiran trabajo sin red (el stash es justamente la
# red). Guardar, recuperar y mirar si.
_GIT_STASH_SUB = {"": ["push", "-u"], "push": ["push", "-u"],
                  "save": ["push", "-u"], "pop": ["pop"], "list": ["list"],
                  "apply": ["apply"], "show": ["show"]}


@tool("git_stash",
      "git_stash [push|pop|list]             -- guarda los cambios sin "
      "commitear (default push), los recupera (pop) o los lista",
      danger=True,
      desc="Guarda temporalmente los cambios sin commitear para dejar el arbol "
           "limpio (push, el default), los devuelve (pop), o los lista (list). "
           "No borra stashes: 'drop' y 'clear' no estan disponibles.",
      params=[
          {"nombre": "subcomando", "tipo": "string", "requerido": False,
           "descripcion": "push (default) | pop | list | apply | show"},
      ])
def _git_stash(args, ctx):
    sub = (args or "").strip().strip("\"\'").lower()
    if sub not in _GIT_STASH_SUB:
        return (f"RESULTADO git_stash ERROR: '{sub[:30]}' no esta permitido. "
                f"Validos: push (default), pop, list, apply, show")
    ok, out = _git(["git", "stash"] + _GIT_STASH_SUB[sub], ctx, cap=1500)
    if not ok:
        return f"RESULTADO git_stash ERROR: {out}"
    return f"RESULTADO git_stash {sub or 'push'}: {out or '(sin salida)'}"


# ══════════════════════════════════════════════════════════════════════
# MATH / TIME / WEB
# ══════════════════════════════════════════════════════════════════════

_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("expresion no permitida (solo aritmetica)")


@tool("calcular", "calcular <expresion>                  -- aritmetica exacta (+ - * / // % **)")
def _calcular(args, ctx):
    expr = args.strip()
    # Models often wrap the expression in quotes/backticks or trail junk after a
    # pipe; keep only the arithmetic part.
    expr = expr.split("|", 1)[0].strip().strip("\"'`")
    val = _safe_eval(ast.parse(expr, mode="eval").body)
    return f"RESULTADO calcular: {expr} = {val}"


@tool("fecha", "fecha                                 -- fecha y hora actual")
def _fecha(args, ctx):
    import datetime
    return "RESULTADO fecha: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool("http_get", "http_get <url>                        -- descarga texto de una URL (http/https)")
def _http_get(args, ctx):
    import urllib.request
    url = args.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "RESULTADO http_get ERROR: solo http/https"
    req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.2"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        raw = resp.read(200_000).decode("utf-8", errors="replace")
    # Extracción limpia vía el conversor universal (cognia/converters.py):
    # quita script/style y conserva estructura de bloques, mejor que el
    # strip por regex (que dejaba el JS/CSS inline como "texto"). Fallback
    # al strip crudo si el parser HTML fallara.
    if "html" in ctype or "<" in raw[:200]:
        try:
            from cognia.converters import html_a_texto
            text = html_a_texto(raw)
        except Exception:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
    else:
        text = re.sub(r"\s+", " ", raw).strip()
    return f"RESULTADO http_get {url[:60]}: {text[:1500]}"


# ══════════════════════════════════════════════════════════════════════
# MCP TOOLS — servidores libres, sin registro ni clave
# ══════════════════════════════════════════════════════════════════════
#
# Van por cognia/mcp_libre.py, que habla el protocolo a mano con stdlib. Sin
# esto el cliente MCP seria una curiosidad de CLI: el valor esta en que Cognia
# pueda consultarlos MIENTRAS trabaja, que es lo que hace un agente de coding.
#
# Ambas leen; ninguna escribe ni gasta dinero, asi que danger=False.

def _partir(args: str, n: int):
    """Parte 'a b resto' en n trozos, el ultimo se queda con lo que sobre."""
    trozos = args.strip().split(None, n - 1)
    return trozos + [""] * (n - len(trozos))


@tool("docs_repo",
      "docs_repo <owner> <repo>              -- documentacion de un repo de GitHub (MCP libre)")
def _docs_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    owner, repo = _partir(args, 2)
    if not owner or not repo:
        return "RESULTADO docs_repo ERROR: uso: docs_repo <owner> <repo>"
    try:
        salida = cliente("gitmcp").llamar(
            "fetch_generic_documentation", {"owner": owner, "repo": repo})
    except ErrorMCP as exc:
        return f"RESULTADO docs_repo ERROR: {exc}"
    return f"RESULTADO docs_repo {owner}/{repo}: {salida[:2000]}"


@tool("preguntar_repo",
      "preguntar_repo <owner/repo> <pregunta>  -- pregunta en lenguaje natural sobre un repo")
def _preguntar_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    repo, pregunta = _partir(args, 2)
    if "/" not in repo or not pregunta:
        return ("RESULTADO preguntar_repo ERROR: uso: "
                "preguntar_repo <owner/repo> <pregunta>")
    try:
        salida = cliente("deepwiki").llamar(
            "ask_question", {"repoName": repo, "question": pregunta})
    except ErrorMCP as exc:
        return f"RESULTADO preguntar_repo ERROR: {exc}"
    return f"RESULTADO preguntar_repo {repo}: {salida[:2500]}"


@tool("docs_libreria",
      "docs_libreria <nombre> <tema>         -- documentacion al dia de una libreria")
def _docs_libreria(args, ctx):
    """Contra la API que el modelo recuerda de su entrenamiento, que envejece."""
    from cognia.mcp_libre import ErrorMCP, cliente
    nombre, tema = _partir(args, 2)
    if not nombre:
        return "RESULTADO docs_libreria ERROR: uso: docs_libreria <nombre> <tema>"
    try:
        c = cliente("context7")
        ident = c.llamar("resolve-library-id", {"libraryName": nombre})
        salida = c.llamar("query-docs",
                          {"libraryId": ident.strip().splitlines()[0][:120],
                           "query": tema or nombre})
    except (ErrorMCP, IndexError) as exc:
        return f"RESULTADO docs_libreria ERROR: {exc}"
    return f"RESULTADO docs_libreria {nombre}: {salida[:2500]}"


@tool("repo_map",
      "repo_map [terminos]                   -- mapa rankeado del codigo relevante (PageRank sobre el grafo)")
def _repo_map(args, ctx):
    """Selector de contexto tipo Aider: dado un tema (o nada), devuelve los
    modulos mas relevantes del codigo de Cognia rankeados por PageRank
    personalizado sobre el grafo de imports. Para el agente que necesita ubicar
    'donde vive esto' antes de leer/editar, sin volcar el repo entero."""
    from cognia.knowledge.repo_map import repo_map
    terms = args.strip()
    try:
        res = repo_map(mentioned=terms or None)
    except Exception as exc:
        return f"RESULTADO repo_map ERROR: {exc}"
    if not res["texto"]:
        return "RESULTADO repo_map: (sin codigo indexado)"
    cab = f"RESULTADO repo_map ({len(res['modulos'])}/{res['n_modulos']} modulos"
    if terms:
        cab += f", sesgado a '{terms[:60]}'"
    cab += "):"
    return cab + "\n" + res["texto"]


@tool("code_grafo",
      "code_grafo <modulo-o-simbolo>         -- vecindad en el grafo de codigo (def/refs/importa)")
def _code_grafo(args, ctx):
    """Navegacion tipo LSP sin language server: dado un modulo devuelve que
    importa / quien lo importa / que define; dado un simbolo (func o clase)
    devuelve donde se define y que modulos lo referencian. Construido del AST
    (no de la BD), asi nunca miente por estado de indice desactualizado."""
    from cognia.knowledge.code_nav import vecindad, formatear
    obj = args.strip()
    if not obj:
        return "RESULTADO code_grafo ERROR: uso: code_grafo <modulo-o-simbolo>"
    try:
        v = vecindad(obj)
    except Exception as exc:
        return f"RESULTADO code_grafo ERROR: {exc}"
    return f"RESULTADO code_grafo:\n{formatear(v)}"


@tool("buscar_en_repo",
      "buscar_en_repo <owner> <repo> <query> -- busca codigo en un repo de GitHub (MCP libre)")
def _buscar_en_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    owner, repo, query = _partir(args, 3)
    if not (owner and repo and query):
        return "RESULTADO buscar_en_repo ERROR: uso: buscar_en_repo <owner> <repo> <query>"
    try:
        salida = cliente("gitmcp").llamar(
            "search_generic_code",
            {"owner": owner, "repo": repo, "query": query})
    except ErrorMCP as exc:
        return f"RESULTADO buscar_en_repo ERROR: {exc}"
    return f"RESULTADO buscar_en_repo {owner}/{repo} '{query}': {salida[:2000]}"


# ══════════════════════════════════════════════════════════════════════
# MEMORY TOOLS (Cognia's own brain as tools -> RAG)
# ══════════════════════════════════════════════════════════════════════

@tool("recordar", "recordar <consulta>                   -- busca en la memoria episodica (RAG)",
      desc="Busca en la memoria episodica de Cognia (lo que el usuario y las "
           "tareas anteriores dejaron guardado) por similitud semantica.",
      params=[
          {"nombre": "consulta", "tipo": "string", "requerido": True,
           "descripcion": "que recuerdo buscar (lenguaje natural)"},
      ])
def _recordar(args, ctx):
    ai = ctx.get("ai")
    query = args.strip()
    try:
        from cognia.vectors import text_to_vector
    except ImportError:
        from vectors import text_to_vector
    vec = text_to_vector(query)
    hits = ai.episodic.retrieve_similar(vec, top_k=5)
    # retrieve_similar rankea por un score fusionado (sim+conf+imp+emocion) y SIEMPRE
    # devuelve top_k, asi que sin un piso de relevancia una consulta nueva surfacea
    # recuerdos no relacionados como si lo fueran. Piso conservador de coseno: descarta
    # solo lo ~0 (ruido), ordena por la similitud mostrada para que los numeros bajen.
    SIM_FLOOR = 0.1
    hits = sorted((h for h in hits if h.get("similarity", 0.0) >= SIM_FLOOR),
                  key=lambda h: h.get("similarity", 0.0), reverse=True)
    if not hits:
        return f"RESULTADO recordar '{query}': sin recuerdos relevantes"
    lines = [f"  ({h.get('similarity', 0):.2f}) {h.get('observation', '')[:120]}" for h in hits]
    return f"RESULTADO recordar '{query}':\n" + "\n".join(lines)


@tool("cuaderno",
      "cuaderno <nota|fuente|consultar|ver> | <texto/ruta/pregunta>  "
      "-- cuaderno inteligente: notas + fuentes ingeridas + consulta (RAG)")
def _cuaderno(args, ctx):
    # Open Notebook nativo (cognia/notebook.py): capacidad interna que orquesta
    # notas (SmartNotes) + fuentes (ingest->memoria) + consulta (recuperacion
    # vectorial, sin LLM). El agente lo usa dentro de una tarea para acumular
    # material y consultarlo.
    parts = re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    sub = parts[0].strip().lower()
    resto = parts[1].strip() if len(parts) > 1 else ""
    from cognia.notebook import Cuaderno
    cua = Cuaderno(ai=ctx.get("ai"))
    if sub == "nota":
        if not resto:
            return "RESULTADO cuaderno ERROR: falta el texto de la nota"
        nid = cua.anotar(resto)
        return f"RESULTADO cuaderno: nota #{nid} guardada"
    if sub == "fuente":
        res = cua.agregar_fuente(resto)
        if "error" in res:
            return f"RESULTADO cuaderno ERROR: {res['error']}"
        return (f"RESULTADO cuaderno: fuente '{res['archivo']}' ingerida "
                f"({res['chunks']} fragmentos)")
    if sub == "consultar":
        hits = cua.consultar(resto)
        if not hits:
            return f"RESULTADO cuaderno consultar '{resto[:40]}': sin material relevante"
        lines = [f"  ({h['score']}) {h['texto'][:120]}" for h in hits]
        return f"RESULTADO cuaderno consultar '{resto[:40]}':\n" + "\n".join(lines)
    if sub == "ver":
        r = cua.resumen()
        fuentes = ", ".join(n["content"][:40] for n in cua.fuentes(limite=8))
        return (f"RESULTADO cuaderno: {r['notas']} notas, {r['fuentes']} "
                f"fuentes. Fuentes: {fuentes or '(ninguna)'}")
    return ("RESULTADO cuaderno ERROR: subcomando invalido "
            "(nota|fuente|consultar|ver)")


@tool("memorizar", "memorizar <texto>                     -- guarda en memoria episodica")
def _memorizar(args, ctx):
    # observe() RECHAZA entradas muy cortas ({"status":"rejected","reason":...});
    # antes se ignoraba el retorno y siempre se reportaba 'guardado' (mentira al
    # modelo). Reportar el rechazo real; en cualquier otro caso, guardado.
    res = ctx["ai"].observe(args.strip(), provided_label="agente_tarea")
    if isinstance(res, dict) and res.get("status") == "rejected":
        reason = res.get("reason", "desconocido")
        return (f"RESULTADO memorizar: NO se guardo (razon: {reason}). "
                "El texto debe ser mas largo (min ~5 chars y 2 palabras).")
    return "RESULTADO memorizar: guardado en memoria episodica"


def _fmt_kg_fact(d) -> str:
    """Formatea un hecho del KG legible para el modelo. Maneja las dos formas de
    dict (get_facts: subject/predicate/object; get_neighbors: concept/relation).
    Antes se usaba str(d)[:80], que volcaba el repr crudo de Python truncado."""
    if not isinstance(d, dict):
        return str(d)[:100]
    subj = d.get("subject", "")
    pred = d.get("predicate") or d.get("relation", "")
    obj = d.get("object") or d.get("concept", "")
    core = " ".join(str(p) for p in (subj, pred, obj) if p)
    w = d.get("weight")
    if isinstance(w, (int, float)):
        core += f" (w={w:g})"
    return core or str(d)[:100]


@tool("kg_buscar", "kg_buscar <concepto>                  -- hechos del grafo sobre un concepto")
def _kg_buscar(args, ctx):
    ai = ctx.get("ai")
    concept = args.strip()
    facts = ai.kg.get_facts(concept) or ai.kg.get_neighbors(concept)
    if not facts:
        return f"RESULTADO kg_buscar '{concept}': sin hechos"
    return f"RESULTADO kg_buscar '{concept}': " + " | ".join(_fmt_kg_fact(f) for f in facts[:10])


@tool("kg_agregar", "kg_agregar <sujeto> | <relacion> | <objeto>  -- agrega un hecho al grafo")
def _kg_agregar(args, ctx):
    parts = [p.strip() for p in re.split(r"\s*\|\s*", args)]
    if len(parts) != 3:
        return "RESULTADO kg_agregar ERROR: formato (sujeto | relacion | objeto)"
    subj, rel, obj = parts
    rel = rel.lower()   # add_triple normaliza con .lower(); igualar el pre-check
    from cognia.knowledge.graph import KnowledgeGraph
    if rel not in KnowledgeGraph.VALID_RELATIONS:
        return ("RESULTADO kg_agregar ERROR: relacion invalida. Validas: "
                + ", ".join(KnowledgeGraph.VALID_RELATIONS))
    # add_triple devuelve is_new: True=hecho nuevo, False=ya existia (lo REFUERZA,
    # sube weight). Antes False se reportaba 'no agregado' (falso: si esta en el KG).
    ok = ctx["ai"].kg.add_triple(subj, rel, obj, source="agente")
    estado = "OK (nuevo)" if ok else "OK (ya existia, reforzado)"
    return f"RESULTADO kg_agregar: ({subj} {rel} {obj}) {estado}"


@tool("anotar", "anotar <clave> | <valor>              -- guarda nota en memoria de trabajo")
def _anotar(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO anotar ERROR: formato (clave | valor)"
    ctx.setdefault("working_memory", {})[parts[0].strip()] = parts[1].strip()
    return f"RESULTADO anotar: '{parts[0].strip()}' guardado"


@tool("notas", "notas                                 -- lee la memoria de trabajo")
def _notas(args, ctx):
    wm = ctx.get("working_memory", {})
    if not wm:
        return "RESULTADO notas: (vacia)"
    return "RESULTADO notas:\n" + "\n".join(f"  {k}: {v}" for k, v in wm.items())


# ══════════════════════════════════════════════════════════════════════
# LLM-BACKED TOOLS
# ══════════════════════════════════════════════════════════════════════

@tool("resumir", "resumir <texto>                       -- resume un texto con el modelo")
def _resumir(args, ctx):
    text = args.strip()
    prompt = f"Resume en 2-3 frases claras, en espanol:\n\n{text[:3000]}"
    out = _orch(ctx).infer(prompt).text.strip()
    return f"RESULTADO resumir: {out[:800]}"


# Best-of-N + juez EXPUESTO como tool (wire de BoN al loop /hacer, CORRIDA-2).
# Integracion aditiva: en vez de reescribir el loop ReAct (accion-por-accion),
# el agente INVOCA esta tool para escribir una funcion nueva; adentro corre el
# pipeline medido (test-first -> N candidatos temp>0 -> juez por EJECUCION de
# los tests visibles -> escribe el MEJOR). Mismo mecanismo que dio +10pp en el
# bench (cognia/agent/candidates.py), ahora usable en vivo.
_BON_N = 6  # candidatos por llamada (N-1 a temp 0.7 + 1 greedy); ~2-3 min CPU


# Umbral de dificultad para despertar el 7B (MoM fase 4): el mismo 0.30 con el
# que model_router.estimate_difficulty separa hard de easy. Pre-filtro barato:
# NO decide el escalado (eso lo decide el fallo REACTIVO de tests), solo evita
# el cold-start del 7B en tareas triviales-que-fallan.
_HEAVY_THRESHOLD = 0.30


def _bon_n(desc: str, bon_max: int = None) -> tuple:
    """(N, dificultad): N adaptativo por dificultad ex-ante (cascada
    barato-primero). model_router.estimate_difficulty (cero LLM, calibrado
    contra las etiquetas del bench) decide cuanto computo invertir: pool
    chico donde el 3B casi siempre acierta, grande donde falla mas. El
    early-stop de best_of_n ya corta el caso trivial (greedy perfecto) a 1
    candidato; esto acota el costo del resto (~25s/candidato en el i3).
    bon_max: techo por /esfuerzo (perfil hibrido); None = sin techo extra."""
    from cognia.agent.model_router import estimate_difficulty
    d = estimate_difficulty(desc)
    if d < 0.15:
        n = 3
    elif d >= 0.50:
        n = 10
    else:
        n = _BON_N
    if bon_max:
        n = min(n, int(bon_max))
    return n, d


# Telemetria append-only del BoN en vivo: la tupla (dificultad ex-ante,
# resultado real de los tests visibles, costo) por invocacion es EL dataset
# para recalibrar el umbral del router (hoy hand-tuned contra el bench) con
# trafico real. Best-effort: si el disco falla, la tool no se entera.
_BON_TELEMETRY = Path(__file__).parent / "generated_tools" / "_bon_telemetry.jsonl"


def _bon_log(rec: dict) -> None:
    # Higiene del instrumento (2026-07-12): los unit tests ejercitan
    # _generar_codigo con fakes y estaban escribiendo telemetria FALSA al
    # ledger de produccion (la telemetria es el dataset de calibracion de
    # θ/router: contaminarla rompe la calibracion futura). Bajo pytest no
    # se registra nada.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        _BON_TELEMETRY.parent.mkdir(parents=True, exist_ok=True)
        with _BON_TELEMETRY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# Nombres que parecen una firma pero no son el objetivo: builtins y verbos de
# la propia consigna. Sin esta lista, "imprima el resultado(x)" daria 'imprima'.
_NO_SON_ENTRY = frozenset({
    "print", "input", "len", "range", "open", "str", "int", "float", "list",
    "dict", "set", "tuple", "sum", "min", "max", "abs", "round", "sorted",
    "type", "bool", "map", "filter", "zip", "enumerate", "format",
    "imprima", "imprime", "imprimir", "muestra", "mostrar", "devuelve",
    "devolver", "retorna", "retornar", "calcula", "calcular", "def",
    "python", "return", "if", "for", "while", "class",
})
_FIRMA_RX = re.compile(r"\b([A-Za-z_]\w*)\s*\(\s*[^)]{0,120}\)")


def _firma_suelta(texto: str):
    """El nombre de una firma `nombre(args)` suelta en la descripcion.

    POR QUE (2026-08-13): `extract_entry_point` solo reconoce la firma cuando
    va precedida de la palabra 'funcion'/'function' — pero la propia ayuda de
    generar_codigo le pide al modelo justo lo contrario: "inclui `suma(a, b)`".
    Medido: extract_entry_point('suma(a, b)') -> None, o sea que el modelo
    obedecia la instruccion al pie de la letra y la herramienta lo rechazaba
    igual. Esto cubre ese hueco SIN tocar extract_entry_point, que la comparten
    BoN y las etapas de stepwise (y ensancharla ahi cambiaria caminos medidos).
    """
    for m in _FIRMA_RX.finditer(texto or ""):
        nombre = m.group(1)
        if nombre.lower() not in _NO_SON_ENTRY:
            return nombre
    return None


@tool("generar_codigo",
      "generar_codigo <ruta.py> | <descripcion con el nombre exacto `func(args)`>  "
      "-- genera N candidatos con test-first y ESCRIBE el mejor por tests",
      desc="Escribe una FUNCION Python nueva a partir de una descripcion: "
           "genera varios candidatos, los juzga ejecutando tests y escribe el "
           "mejor en la ruta dada. Preferila a escribir_archivo cuando la "
           "tarea es 'implementa la funcion X'. La descripcion DEBE incluir "
           "el nombre exacto de la funcion, p.ej. `suma(a, b)`.",
      params=[
          {"nombre": "ruta", "tipo": "string", "requerido": True,
           "descripcion": "archivo .py destino (dentro del workspace)"},
          {"nombre": "descripcion", "tipo": "string", "requerido": True,
           "descripcion": "que debe hacer la funcion, con su nombre exacto "
                          "`nombre(args)` incluido"},
      ])
def _generar_codigo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO generar_codigo ERROR: formato (ruta.py | descripcion)"
    path_s, desc = parts[0].strip(), parts[1].strip()
    from cognia.agent.stepwise import extract_entry_point
    entry = (extract_entry_point(desc) or extract_entry_point(path_s)
             or _firma_suelta(desc))
    if not entry:
        # El mensaje tiene que decir QUE HACER, no solo que fallo. Medido el
        # 2026-08-13 con scripts/diag_tarea_python.py: ante "escribi y ejecuta
        # un script que imprima la suma de 100 mas 250" (un SCRIPT, no una
        # funcion) el modelo elegia generar_codigo, recibia "no identifique el
        # nombre de la funcion" y reintentaba IDENTICO 3 veces hasta que el
        # detector de estancamiento mataba la tarea: 1 de cada 3 corridas del
        # gate del camino feliz se perdia asi. Con la salida nombrada, el
        # modelo cambia de herramienta en el paso siguiente.
        return ("RESULTADO generar_codigo ERROR: esta herramienta escribe UNA "
                "FUNCION y no encuentro su nombre en la descripcion. "
                "Si querias una funcion, repeti la llamada incluyendo el nombre "
                "exacto, p.ej. `suma(a, b)`. Si lo que necesitas es un SCRIPT "
                "(codigo que se ejecuta de arriba a abajo), esta no es la "
                "herramienta: usa escribir_archivo con el codigo completo y "
                "despues ejecutar.")
    try:
        wpath = _resolve_write_path(path_s)
    except ValueError as e:
        return f"RESULTADO generar_codigo ERROR: {e}"

    orch = _orch(ctx)

    # Perfil HIBRIDO de la corrida (hybrid_router): viene del loop /hacer via
    # ctx, o se calcula aca si la tool corre suelta. Da los PERMISOS por
    # /esfuerzo (colonia 7B/q35, superorganismo, techo BoN) y el umbral de
    # dificultad desplazado que usan las etapas reactivas de abajo. A esfuerzo
    # medio (default) el umbral ES _HEAVY_THRESHOLD: comportamiento identico
    # al de antes. Los kill-switches env siguen mandando en cada etapa.
    _hyb = ctx.get("hybrid")
    if not isinstance(_hyb, dict):
        try:
            from cognia.agent.hybrid_router import route_profile
            _hyb = route_profile(desc)
        except Exception:
            _hyb = {}
    _hyb_umbral = _hyb.get("umbral_pesado", _HEAVY_THRESHOLD)

    def _code_gen(prompt, temperature=0.0, seed=None):
        return orch.infer(prompt, max_tokens=768, temperature=temperature).text or ""

    def _test_gen(prompt, temperature=0.0, seed=None):
        return orch.infer(prompt, max_tokens=256, temperature=temperature).text or ""

    from cognia.agent.candidates import best_of_n
    from cognia_v3.eval.benchmark_code import extract_code
    code_prompt = ("Escribe UNA funcion Python COMPLETA que cumpla esto. Responde "
                   "SOLO con un bloque ```python ...``` con la funcion, sin "
                   "explicaciones.\n\n" + desc)
    # llamada con 1 arg (los tests monkeypatchean _bon_n con esa firma);
    # el techo por /esfuerzo del perfil se aplica afuera
    n_plan, dif = _bon_n(desc)
    if _hyb.get("bon_max"):
        n_plan = min(n_plan, int(_hyb["bon_max"]))
    _t0 = _time.time()
    try:
        out = best_of_n(_code_gen, code_prompt, desc, entry, extract_code,
                        n=n_plan, seed=42, test_gen_fn=_test_gen)
    except Exception as exc:
        return f"RESULTADO generar_codigo ERROR: {exc}"
    _best_t = out.get("ranking", [{}])[0] if out.get("ranking") else {}
    code = out.get("code", "")
    _score_3b, _total = _best_t.get("score"), _best_t.get("total")
    # Asserts visibles del test-first: los usa la mesa redonda (el escalado
    # 7B reemplaza `out` entero y los perderia).
    _visible = out.get("visible_tests") or []

    # ── Escalado REACTIVO al especialista de capacidad 7B (MoM fase 4) ──────
    # Si el mejor candidato del 3B FALLA sus tests visibles (o no produjo la
    # funcion) y la tarea es DURA, reintentar con el 7B (cascada 40->60% medida
    # en codigo duro). REACTIVO, no predictivo (el router predictivo medio
    # 45<60): el 7B solo dispara donde el 3B ya fallo -> jamas desperdicia
    # computo en lo que el 3B resolvia. Se queda con el mejor de (3B, 7B) por
    # score de tests visibles -> B nunca peor que A. Kill-switch COGNIA_HEAVY_
    # CODE OFF (default) => heavy_code_backend() es None => 0 cambios.
    # Lazy-load-usar-cerrar (RAM steady-state 0 en el i3 de 12GB).
    _escalado_7b, _score_7b = False, None
    # El 3B tiene CONFIRMACION de exito solo si genero tests visibles reales y los
    # paso TODOS. Sin tests (total=0) NO hay confirmacion: el e2e (burst_balloons,
    # 2026-07-10) cazo que el disparador viejo 'score<total' NUNCA saltaba con 0
    # tests visibles, aunque el codigo fallara los tests ocultos -> el +20pp del
    # gate no se materializaba en produccion. Ahora: en tarea dura, si el 3B no
    # CONFIRMA exito, escalar. El 'mejor de (3B,7B)' garantiza que escalar de mas
    # nunca empeora; el pre-filtro de dificultad acota el costo a tareas duras.
    _confirmado_3b = (_total and _score_3b is not None and _score_3b >= _total)
    _fallo_3b = (not _confirmado_3b) or (f"def {entry}" not in code)
    if _fallo_3b and dif >= _hyb_umbral and _hyb.get("colonia_7b", True):
        try:
            from node.heavy_code import heavy_code_backend, close_heavy_code
            _heavy = heavy_code_backend()
            if _heavy is not None:
                _pf = ctx.get("print_fn")
                if callable(_pf):
                    _pf("[detail]Codigo dificil: el 3B fallo sus tests -> "
                        "escalando al especialista 7B (mas lento)...[/detail]")
                try:
                    from cognia_v3.eval.benchmark_code import (
                        build_prompt, SYSTEM_PROMPT)
                    # GREEDY del 7B (1 candidato, prompt del gate), NO best_of_n.
                    # El probe (2026-07-10) MIDIO que el 7B greedy recupera 4/4
                    # tareas duras (single_number/rotate_array/min_jumps/put) que
                    # el best_of_n+juez-de-tests-visibles descartaba: el JUEZ debil
                    # (tests visibles autogenerados, 2/4) era el cuello, no el
                    # modelo ni el prompt. Greedy reproduce EXACTO el protocolo del
                    # gate bajo el que el 7B recupero 8/8 (+20pp). El 3B ya fallo/no
                    # confirmo, asi que el 7B (medido mejor en dura) es la mejor
                    # apuesta: quedarse con el si produjo la funcion.
                    _gate_prompt = build_prompt(desc, system=SYSTEM_PROMPT)
                    _raw7 = _heavy.generate(_gate_prompt, max_tokens=768,
                                            temperature=0.0, cache_prompt=False)
                    _code7 = extract_code(_raw7 or "")
                    if _code7.strip() and f"def {entry}" in _code7:
                        code = _code7
                        _best_t = {"score": None, "total": None}
                        out = {"n_generated": 1, "n_unique": 1,
                               "rank_mode": "7b_greedy", "code": _code7,
                               "ranking": [_best_t]}
                        _escalado_7b = True
                finally:
                    close_heavy_code()
        except Exception:
            pass   # cualquier falla del 7B -> quedarse con el 3B (fallback seguro)

    # ── Etapa 3 de la cascada: Qwen3.5-4B no-think (COLONIA E2, 2026-07-12) ──
    # MEDIDO (PREREG_E1_QWEN35 + union-oraculo): qwen35 RAW 17/40 > 3B 15/40
    # en el set duro, y 4 tareas las resuelve SOLO qwen35 (ni 3B ni 7B) ->
    # union de la colonia 27/40 vs 23/40 de la cascada 2-etapas. Dispara solo
    # en tarea dura cuando (a) no hay funcion valida aun, o (b) hay asserts
    # visibles y el candidato actual NO los pasa todos. El candidato q35
    # REEMPLAZA solo si (a) no habia funcion, o (b) mejora ESTRICTAMENTE el
    # score visible (keep-best; leccion del juez debil del deploy 7B).
    # Lazy-usar-cerrar (2.7GB); sin GGUF o COGNIA_FLEET30=0 -> no-op.
    _escalado_q35 = False
    if dif >= _hyb_umbral and _hyb.get("colonia_q35", True):
        _sin_funcion = f"def {entry}" not in code
        _score_v = None
        if not _sin_funcion and _visible:
            try:
                from cognia.agent.deliberation import (execution_feedback,
                                                       feedback_score)
                _score_v, _ = feedback_score(
                    execution_feedback(code, _visible, entry))
            except Exception:
                _score_v = None
        # Trigger por rama (cada una con su dato):
        #  (a) sin funcion valida -> q35 (adicion pura);
        #  (b) visibles fallando -> q35 compite por mejora ESTRICTA;
        #  (c) SIN visibles (0 asserts = sin confirmacion, la rama del fix
        #      burst_balloons) y el 7B NO tomo la tarea -> q35 reemplaza al
        #      greedy no-confirmado del 3B (E1: q35 17/40 > 3B 15/40 RAW).
        #      Si el 7B YA reemplazo, se respeta (su gate midio 8/8 con
        #      ocultos; no hay dato head-to-head q35-vs-7B sin oraculo).
        #      Gap cazado por el live check e2e DBG1 (2026-07-12): el
        #      trigger original exigia visibles y esta rama quedaba muda.
        _sin_confirmacion = (not _visible and not _confirmado_3b
                             and not _escalado_7b)
        if (_sin_funcion
                or (_score_v is not None and _score_v < len(_visible))
                or _sin_confirmacion):
            try:
                from node.fleet_registry import (close_fleet_member,
                                                 fleet_backend)
                _q35 = fleet_backend("qwen35_4b")
                if _q35 is not None:
                    _pf = ctx.get("print_fn")
                    if callable(_pf):
                        _pf("[detail]Etapa 3 de la colonia: probando con "
                            "Qwen3.5-4B...[/detail]")
                    try:
                        from cognia_v3.eval.benchmark_code import (
                            SYSTEM_PROMPT as _SP35, build_prompt as _bp35)
                        _raw35 = _q35.generate(
                            _bp35(desc, system=_SP35) + "<think>\n\n</think>\n\n",
                            max_tokens=640, temperature=0.0,
                            cache_prompt=False)
                        _code35 = extract_code(_raw35 or "")
                        if _code35.strip() and f"def {entry}" in _code35:
                            _usar = _sin_funcion or _sin_confirmacion
                            if not _usar and _visible:
                                from cognia.agent.deliberation import (
                                    execution_feedback as _ef35,
                                    feedback_score as _fs35)
                                _s35, _ = _fs35(_ef35(_code35, _visible, entry))
                                _usar = _s35 > (_score_v or 0)
                            if _usar:
                                code = _code35
                                _best_t = {"score": None, "total": None}
                                out = {"n_generated": out.get("n_generated"),
                                       "n_unique": out.get("n_unique"),
                                       "rank_mode": "q35_greedy",
                                       "code": _code35,
                                       "ranking": [_best_t]}
                                _escalado_q35 = True
                    finally:
                        close_fleet_member("qwen35_4b")
            except Exception:
                pass   # cualquier falla del q35 -> quedarse con lo previo

    # ── Mesa redonda FLEET-30 (deliberacion ENTRE modelos; default OFF) ─────
    # COGNIA_DELIBERACION=1 la activa (gate con tests OCULTOS pre-registrado:
    # PREREG_DELIBERACION.md; hasta que PASE, queda opt-in). Etapa ADITIVA:
    # solo corre si tras 3B (+7B si escalo) el candidato NO pasa todos sus
    # tests visibles y la tarea es dura. La critica es EJECUCION real
    # (deliberation.py, keep-best estricto): el 7B/3B se pasan el candidato
    # con el traceback del sandbox y lo reparan por turnos. Riesgo declarado:
    # con tests visibles DEBILES la mesa puede sobre-ajustar a un assert
    # equivocado (leccion del juez del escalado 7B) — por eso el gate que
    # decide el default mide con tests ocultos, y el trigger exige asserts.
    _mesa_mejoro = False
    if (os.environ.get("COGNIA_DELIBERACION", "").strip().lower()
            in ("1", "on", "true", "yes")) and _visible and dif >= _hyb_umbral:
        try:
            from cognia.agent.deliberation import (deliberate,
                                                   execution_feedback,
                                                   feedback_score)
            _fb0 = execution_feedback(code, _visible, entry)
            _s0, _t0v = feedback_score(_fb0)
            if _t0v and _s0 < _t0v:
                _pf = ctx.get("print_fn")
                if callable(_pf):
                    _pf("[detail]Mesa redonda: los modelos deliberan sobre el "
                        "candidato (feedback de ejecucion real)...[/detail]")
                _parts = []
                _hv = None
                try:
                    from node.heavy_code import (close_heavy_code,
                                                 heavy_code_backend)
                    _hv = heavy_code_backend()
                except Exception:
                    _hv = None
                if _hv is not None:
                    from cognia_v3.eval.benchmark_code import (
                        SYSTEM_PROMPT as _MR_SP, build_prompt as _mr_bp)

                    def _gen_7b(p, temperature=0.0, seed=None, _h=_hv):
                        return _h.generate(_mr_bp(p, system=_MR_SP),
                                           max_tokens=768, temperature=0.0,
                                           cache_prompt=False) or ""
                    _parts.append(("7b", _gen_7b))
                _parts.append(("3b", _code_gen))
                try:
                    _mesa = deliberate(desc, entry, _parts, extract_code,
                                       _visible, initial_code=code, rounds=2)
                finally:
                    if _hv is not None:
                        close_heavy_code()
                if _mesa.get("mejorado") and _mesa.get("code", "").strip():
                    code = _mesa["code"]
                    _best_t = {"score": _mesa["score"], "total": _mesa["total"]}
                    out = {"n_generated": out.get("n_generated"),
                           "n_unique": out.get("n_unique"),
                           "rank_mode": "mesa_redonda", "code": code,
                           "ranking": [_best_t]}
                    _mesa_mejoro = True
        except Exception:
            pass   # la mesa nunca rompe la tool: fallback al candidato previo

    # ── Etapa 4: SUPERORGANISMO (colonia por pedazos; default OFF) ─────────
    # COGNIA_SUPERORGANISMO=1 la activa. Gate PREREG_SUPERORGANISMO CRUZADO
    # (2026-07-14: NEWX3 y ALG3 pasan tests OCULTOS donde pass@16=0): la
    # descomposición con oráculo por pieza + spec-asserts del enunciado +
    # feromona compra capacidad más allá del techo de la cascada 1-3. Es el
    # miembro MÁS caro (2 modelos 4B lazy + hasta 16 gens): último recurso,
    # solo tarea dura donde NADA confirmó. Keep-best conservador: reemplaza
    # solo si (a) no hay función válida, o (b) el superorganismo pasó TODOS
    # sus spec-asserts (señal fuerte de su propio oráculo; el veredicto
    # final sigue siendo del caller). Queda opt-in hasta la batería e2e.
    _superorg = False
    from cognia.agent.superorganismo import (superorganismo_enabled,
                                             superorganismo_solve)
    _sin_funcion_4 = f"def {entry}" not in code
    _confirmado_actual = (_escalado_7b or _mesa_mejoro
                          or (_best_t.get("total")
                              and _best_t.get("score") is not None
                              and _best_t.get("score") >= _best_t.get("total")))
    if (superorganismo_enabled(_hyb) and dif >= _hyb_umbral
            and (_sin_funcion_4 or not _confirmado_actual)):
        _pf = ctx.get("print_fn")
        if callable(_pf):
            _pf("[detail]Etapa 4: superorganismo (colonia por pedazos, "
                "lento)...[/detail]")
        _so = superorganismo_solve(desc, entry, print_fn=ctx.get("print_fn"))
        if _so and (_sin_funcion_4
                    or _so["spec_pass"] == _so["spec_total"]):
            code = _so["code"]
            _best_t = {"score": _so["spec_pass"], "total": _so["spec_total"]}
            out = {"n_generated": _so["gens"], "n_unique": _so["gens"],
                   "rank_mode": "superorganismo", "code": code,
                   "ranking": [_best_t]}
            _superorg = True

    _bon_log({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "task_head": desc[:120], "difficulty": dif, "n_planned": n_plan,
        "n_generated": out.get("n_generated"), "rank_mode": out.get("rank_mode"),
        "score": _best_t.get("score"), "total": _best_t.get("total"),
        "secs": round(_time.time() - _t0, 1),
        "escalado_7b": _escalado_7b, "score_3b": _score_3b, "score_7b": _score_7b,
        "mesa_redonda": _mesa_mejoro, "escalado_q35": _escalado_q35,
        "superorganismo": _superorg,
        "modalidad": _hyb.get("modalidad"), "esfuerzo": _hyb.get("esfuerzo"),
    })
    if not code.strip() or f"def {entry}" not in code:
        return (f"RESULTADO generar_codigo ERROR: no se genero una funcion "
                f"'{entry}' valida en {out.get('n_generated', 0)} candidatos.")
    wpath.parent.mkdir(parents=True, exist_ok=True)
    # El fichero debe ser un SCRIPT ejecutable, no solo una definicion: el
    # camino feliz (gate 2026-07-20) midio al agente re-ejecutando suma.py en
    # bucle porque `def suma(): ...` sin main no imprime NADA, y el loop se
    # estancaba esperando un output que no podia llegar. Si la entry no lleva
    # argumentos y el codigo no tiene ya un __main__, se anade el guard que la
    # llama e imprime — ejecutar el fichero produce el resultado pedido.
    if "__main__" not in code and f"def {entry}(" in code:
        firma = code.split(f"def {entry}(", 1)[1].split(")", 1)[0].strip()
        sin_args = (firma == "" or all(
            a.strip().startswith(("*", "**")) or "=" in a
            for a in firma.split(",") if a.strip()))
        if sin_args:
            code += (f"\n\nif __name__ == \"__main__\":\n"
                     f"    print({entry}())")
    wpath.write_text(code + "\n", encoding="utf-8")
    ft = ctx.setdefault("agent_state", {}).setdefault("files_touched", [])
    if str(wpath) not in ft:
        ft.append(str(wpath))
        ctx["agent_state"]["files_touched"] = ft[-15:]
    best = out.get("ranking", [{}])[0] if out.get("ranking") else {}
    _tag7 = " [escalado a 7B]" if _escalado_7b else ""
    if _escalado_q35:
        _tag7 += " [etapa 3: Qwen3.5]"
    if _mesa_mejoro:
        _tag7 += " [mesa redonda]"
    if _superorg:
        _tag7 += " [superorganismo]"
    return (f"RESULTADO generar_codigo {_disp(wpath)}: OK (mejor de "
            f"{out.get('n_unique', '?')} candidatos unicos, rank={out.get('rank_mode')}, "
            f"tests visibles {best.get('score', '?')}/{best.get('total', '?')}, "
            f"{len(code)} chars){_tag7}")


# Contratos por etapa del pipeline plan->design->code->test (contracts.py,
# AG-ARB): la cascada attribute_failure estaba escrita y medida
# (bench_arbitro) pero NINGUNA tool la exponia al loop -- y skill_capture ya
# tenia registrado el reconocedor _recognize_contratos_pasan esperando una
# tool cuyo nombre contenga 'contrat' (rama muerta dependiente). Determinista,
# cero LLM: entidades por parseo, firmas por ast, tests en el sandbox real.
@tool("contratos",
      "contratos <plan> | <firmas del design> | <ruta.py o codigo> | <asserts>  "
      "-- verifica el pipeline plan->design->code->test y atribuye la etapa que falla")
def _contratos(args, ctx):
    parts = re.split(r"\s*\|\s*", args or "", maxsplit=3)
    if len(parts) != 4 or not parts[2].strip():
        return ("RESULTADO contratos ERROR: formato (plan | firmas del design | "
                "ruta.py o codigo | asserts), 4 partes separadas por '|'")
    plan_txt, design_txt, code_arg, tests_txt = (p.strip() for p in parts)
    # code: una ruta .py (relativa al workspace del agente, donde escribe
    # generar_codigo) o el codigo en linea.
    code_src = code_arg
    if code_arg.endswith(".py") and "\n" not in code_arg:
        cpath = Path(code_arg)
        if not cpath.is_file():
            try:
                from cognia.agents.workers.dev_tools import _root_actual
                cpath = Path(_root_actual()) / code_arg
            except Exception:
                pass
        try:
            code_src = cpath.read_text(encoding="utf-8")
        except OSError:
            return f"RESULTADO contratos ERROR: no pude leer '{code_arg}'"
    from cognia.agent.contracts import attribute_failure
    from cognia.agent.stepwise import extract_entry_point
    entry = (extract_entry_point(design_txt) or extract_entry_point(tests_txt)
             or extract_entry_point(plan_txt) or "")
    firmas = [s.strip() for s in re.split(r"[;\n]+", design_txt) if s.strip()]
    pipeline = {
        "plan": {"text": plan_txt},
        "design": {"text": design_txt, "signatures": firmas},
        "code": {"code": code_src, "entry_point": entry},
        "test": {"tests": tests_txt, "entry_point": entry},
    }
    try:
        r = attribute_failure(pipeline)
    except Exception as exc:
        return f"RESULTADO contratos ERROR: {exc}"
    if r["stage"] is None:
        # literal que reconoce skill_capture._recognize_contratos_pasan
        return "RESULTADO contratos: todos los contratos pasan"
    return (f"RESULTADO contratos: FALLA en etapa '{r['stage']}' "
            f"(contrato {r['contract']}): {r['reason']}")


# HERMES self-tooling EN VIVO: el agente puede pedir una tool nueva sin salir
# del loop /hacer. Reusa el mismo pipeline generar->scan->sandbox->registrar
# de cognia.agent.tool_synthesis (regla 8 CLAUDE.md: nada auto-generado se
# vuelve ejecutable sin pasar _static_safety_scan + sandbox); esta tool NO
# agrega un camino nuevo de ejecucion, solo lo dispara desde el loop. danger=True
# porque el resultado queda invocable (staged) sin revision humana previa.
@tool("crear_herramienta",
      "crear_herramienta <nombre> | <proposito> | <test_input> | <resultado_esperado>  "
      "-- sintetiza y REGISTRA una tool nueva (sandbox-verificada, queda staged)",
      danger=True)
def _crear_herramienta(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=3)
    if len(parts) != 4 or any(not p.strip() for p in parts):
        return ("RESULTADO crear_herramienta ERROR: formato (usa nombre | proposito | "
                "test_input | resultado_esperado), 4 partes separadas por '|'")
    nombre, proposito, test_input, esperado = (p.strip() for p in parts)

    from cognia.agent.tool_synthesis import ToolSpec, synthesize_and_register, load_generated_tools
    spec = ToolSpec(name=nombre, doc=proposito[:60], purpose=proposito,
                    test_input=test_input, expect_contains=esperado)
    res = synthesize_and_register(spec, orch=_orch(ctx), max_attempts=2)
    if not res.get("ok"):
        # motivo REAL (scan estatico, sandbox, o repair agotado) -- nunca un
        # "no se pudo" generico; el modelo/usuario necesita saber que fallo.
        return f"RESULTADO crear_herramienta ERROR: {res.get('reason', 'desconocido')}"

    load_generated_tools()  # la deja invocable YA en este proceso (TOOLS global)
    return (f"RESULTADO crear_herramienta: '{nombre}' creada y verificada "
            f"(version {res.get('version', '?')}, tier {res.get('tier', 'staged')}). "
            "Ya es invocable con su nombre.")


# Ciclo de vida COMPLETO del self-tooling: _write_verified preserva cada
# version anterior en _history/ justamente "para permitir rollback_tool si la
# nueva version sale peor", pero rollback_tool no tenia llamador -- una
# actualizacion mala era irreversible desde el loop. danger=True: reemplaza
# codigo ejecutable registrado (misma categoria que crear_herramienta).
@tool("revertir_herramienta",
      "revertir_herramienta <nombre> | <version>  -- restaura una tool creada "
      "con crear_herramienta a una version previa guardada en _history",
      danger=True)
def _revertir_herramienta(args, ctx):
    parts = re.split(r"\s*\|\s*", args or "", maxsplit=1)
    if len(parts) != 2 or any(not p.strip() for p in parts):
        return ("RESULTADO revertir_herramienta ERROR: formato "
                "(nombre | version), p.ej.: mi_tool | 0.1.0")
    nombre, version = (p.strip() for p in parts)
    from cognia.agent.tool_synthesis import load_generated_tools, rollback_tool
    res = rollback_tool(nombre, version)
    if not res.get("ok"):
        return f"RESULTADO revertir_herramienta ERROR: {res.get('reason', '?')}"
    load_generated_tools()  # recarga la version restaurada en TOOLS
    return (f"RESULTADO revertir_herramienta: '{nombre}' restaurada a la "
            f"version {version} (tier staged, contadores de uso en 0)")


# Sub-agente acotado: delega una SUBTAREA a una corrida anidada de _run_agent_task
# con (a) un ROL que restringe las tools disponibles (investigador=solo lectura,
# implementador=+escritura/ejecucion), (b) un sub-presupuesto de pasos, y (c) el
# router de modelo por dificultad (el runner elige 3B/7B). El runner recursivo se
# inyecta en ctx['_run_agent'] desde cli.py (evita el import circular tools<->cli).
# Profundidad acotada (ctx['_delegation_depth']) para que un sub-agente no delegue
# infinitamente.
_MAX_DELEGATION_DEPTH = 2


@tool("delegar_subtarea",
      "delegar_subtarea <investigador|implementador> | <subtarea>  "
      "-- corre la subtarea en un sub-agente con tools acotadas por rol y su propio presupuesto",
      desc="Delega una SUBTAREA autocontenida a un sub-agente con contexto "
           "fresco y tools acotadas por rol: 'investigador' solo lee/busca, "
           "'implementador' ademas escribe y ejecuta. Util para explorar sin "
           "gastar el contexto de la tarea principal.",
      params=[
          {"nombre": "rol", "tipo": "string", "requerido": True,
           "descripcion": "'investigador' (solo lectura) o 'implementador' "
                          "(lectura+escritura+ejecucion)"},
          {"nombre": "subtarea", "tipo": "string", "requerido": True,
           "descripcion": "la subtarea, autocontenida (el sub-agente no ve tu "
                          "historial)"},
      ])
def _delegar_subtarea(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        return ("RESULTADO delegar_subtarea ERROR: formato (rol | subtarea); "
                "rol = investigador | implementador")
    rol, subtarea = parts[0].strip().lower(), parts[1].strip()
    if rol not in ROLE_TOOLS:
        return (f"RESULTADO delegar_subtarea ERROR: rol '{rol}' desconocido "
                f"(usa: {', '.join(ROLE_TOOLS)})")

    runner = ctx.get("_run_agent")
    if not callable(runner):
        return ("RESULTADO delegar_subtarea ERROR: delegacion no disponible en "
                "este contexto")

    depth = ctx.get("_delegation_depth", 0)
    # Techo por perfil hibrido (/esfuerzo): bajo=0 (sin delegacion), medio/
    # alto=2, maximo=3. Sin perfil, el constante de siempre.
    _max_depth = ctx.get("_delegation_max", _MAX_DELEGATION_DEPTH)
    if depth >= _max_depth:
        return (f"RESULTADO delegar_subtarea ERROR: profundidad maxima de "
                f"delegacion ({_max_depth}) alcanzada; resolve la "
                "subtarea directamente.")

    # Sub-presupuesto: la mitad de lo que quede (o un piso), para que la
    # subtarea no se coma el presupuesto entero del padre.
    remaining = ctx.get("_steps_remaining", 8)
    sub_budget = max(3, int(remaining) // 2)
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]delegando a sub-agente '{rol}' (presupuesto {sub_budget})[/detail]")
    try:
        sub_result = runner(subtarea, allowed_tools=ROLE_TOOLS[rol],
                            max_steps=sub_budget, delegation_depth=depth + 1)
    except Exception as exc:
        return f"RESULTADO delegar_subtarea ERROR: {exc}"
    return f"RESULTADO delegar_subtarea ({rol}): {str(sub_result)[:600]}"


# ── Computer-use: tools de pantalla (mandato 2026-07-13, gate de seguridad) ──
# Registro al final para que `tool` y ROLE_TOOLS ya existan. Opt-in duro
# (COGNIA_SCREEN=1) TAMBIEN en el registro, no solo en runtime: registradas
# siempre inflaban el catalogo default a 46 tools y el A/B 2026-07-25 midio
# que el catalogo grande degrada al 3B (camino feliz 4.25/5 -> 2.5/5). El gate
# runtime (_enabled) se conserva por si el flag cambia en caliente. El control
# remoto no pierde nada: cognia/remoto/sesiones.py exporta COGNIA_SCREEN=1
# antes de lanzar cada REPL. Mismos valores que screen_tools._enabled().
if os.environ.get("COGNIA_SCREEN", "").strip().lower() in ("1", "on", "true", "yes"):
    try:
        from cognia.agent import screen_tools as _screen_tools
        _screen_tools.register(tool)
        # Las 7 que registra screen_tools.register(), no 5: pantalla_ventanas y
        # pantalla_activar_ventana quedaban FUERA del rol, asi que un
        # sub-agente 'implementador' las veia en el catalogo global pero
        # delegar_subtarea se las recortaba — capacidad registrada y
        # desconectada, el modo de fallo de la casa.
        for _t in ("pantalla_captura", "pantalla_localizar", "pantalla_click",
                   "pantalla_escribir", "pantalla_tecla",
                   "pantalla_ventanas", "pantalla_activar_ventana"):
            ROLE_TOOLS["implementador"].add(_t)
    except Exception as _exc:
        # Con el flag puesto, tragarse el import dejaria una capacidad pedida
        # y desconectada en silencio (el modo de fallo de la casa): avisar.
        print(f"[cognia] COGNIA_SCREEN=1 pero screen_tools no cargo: {_exc}",
              file=sys.stderr)


# ── Plan como artefacto mutable (patron OpenManus, mandato 2026-07-13) ──
# El unico patron de OpenManus que faltaba: is_stuck y terminate ya existen
# en el loop (register_action + responder), mejores. Ver plan_artifact.py.
try:
    from cognia.agent import plan_artifact as _plan_artifact
    _plan_artifact.register(tool)
    ROLE_TOOLS["investigador"].add("plan")
    ROLE_TOOLS["implementador"].add("plan")
except Exception:
    pass


# ── Flujos n8n: "Cognia organiza el flujo" desde NL (mandato 2026-07-13) ──
try:
    from cognia.agent import flows as _flows
    _flows.register(tool)
    # ejecutar_flujo cierra el ciclo: crear_flujo persistia .flujo.json y
    # NADIE lo consumia (motor flows.ejecutar sin llamador de produccion).
    for _t in ("crear_flujo", "ejecutar_flujo"):
        ROLE_TOOLS["implementador"].add(_t)
except Exception:
    pass


# ── Tools de IMAGEN (cableado del barrido nocturno 2026-07-24) ──────────
# cognia.assets estaba verificado en GPU y el agente no podia alcanzarlo.
# OPT-IN DURO (COGNIA_IMG_TOOLS=1), como las de pantalla: registradas
# default-ON bajaban el camino feliz de 4.25/5 a 2.5/5 (A/B n=4+4 medido
# 2026-07-25) — el techo de nº de tools del modelo chico es real.
# Imports perezosos dentro de cada tool; sin GPU devuelven ERROR legible.
if os.environ.get("COGNIA_IMG_TOOLS") == "1":
    try:
        from cognia.agent import image_tools as _image_tools
        _image_tools.register(tool)
        for _t in ("imagen_generar", "imagen_editar", "imagen_quitar_fondo"):
            ROLE_TOOLS["implementador"].add(_t)
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_IMG_TOOLS=1 pero image_tools no cargo: {_exc}",
              file=sys.stderr)


# ── Navegador del agente (opt-in COGNIA_BROWSER=1) ─────────────────────
# Chromium headless + centinela anti-inyeccion (sentinel.evaluar_contenido_web).
# Opt-in duro como imagen\pantalla: tools default-ON degradan al 3B
# (A\B 2026-07-25: camino feliz 4.25/5 -> 2.5/5).
if os.environ.get("COGNIA_BROWSER") == "1":
    try:
        from cognia.agent import browser_tool as _browser_tool
        _browser_tool.register(tool)
        for _t in ("web_buscar", "web_abrir"):
            ROLE_TOOLS["investigador"].add(_t)
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_BROWSER=1 pero browser_tool no cargo: {_exc}",
              file=sys.stderr)


# ── Ingenieria inversa de repos (opt-in COGNIA_REPO_REVERSE=1) ──────────
# Opt-in duro como imagen/pantalla: tools default-ON degradan al 3B
# (A/B 2026-07-25: camino feliz 4.25/5 -> 2.5/5).
if os.environ.get("COGNIA_REPO_REVERSE") == "1":
    try:
        from cognia.agent import repo_reverse_tool as _repo_reverse_tool
        _repo_reverse_tool.register(tool)
        ROLE_TOOLS["investigador"].add("repo_a_prompt")
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_REPO_REVERSE=1 pero repo_reverse_tool no cargo: "
              f"{_exc}", file=sys.stderr)


# ── Tools de HORIZONTE (COGNIA_HORIZONTE=1, obra long-horizon 2026-08-09) ──
# Siempre registradas (sin deps, baratas) pero NO en CORE_TOOLS: solo se
# ANUNCIAN al modelo cuando cli.py arma el modo horizonte (P1 agrega ambas al
# _tool_filter). Sin ctx["_horizonte_task_id"] degradan con causa visible.
# Mecanismo PRO-LONG: el agente CONSULTA su estado/bitacora con el arnes en
# vez de cargar la historia al contexto o (peor) suponer que ya hizo algo.

@tool("tarea_estado",
      "tarea_estado                          -- hitos verificados y faltantes de la tarea larga en curso",
      desc=("Muestra el estado durable de la tarea de horizonte en curso: que "
            "criterios ya estan VERIFICADOS con evidencia real (no los "
            "repitas), cuales faltan, archivos tocados y ultimo error. Usala "
            "antes de rehacer algo que quiza ya hiciste."),
      params=[])
def _tarea_estado(args, ctx):
    tid = (ctx or {}).get("_horizonte_task_id", "")
    if not tid:
        return ("RESULTADO tarea_estado: ERROR solo disponible dentro de una "
                "tarea /hacer en modo horizonte (COGNIA_HORIZONTE=1, regimen "
                "nativo)")
    from cognia.agent.estado_tarea import cargar, render_estado
    est = cargar(tid)
    if est is None:
        return f"RESULTADO tarea_estado: ERROR no hay estado para {tid}"
    return "RESULTADO tarea_estado:\n" + render_estado(est)


@tool("bitacora_buscar",
      "bitacora_buscar [<n> |] <patron>      -- busca en la bitacora de la tarea larga (regex, ultimas n)",
      desc=("Busca en la bitacora append-only de la tarea de horizonte en "
            "curso (cada tool ejecutada, sus argumentos y resultados). Util "
            "para recordar que archivos tocaste, que fallo y por que, sin "
            "adivinar. patron es regex case-insensitive; n (opcional) limita "
            "a las ultimas n coincidencias."),
      params=[{"nombre": "patron", "tipo": "string", "requerido": True,
               "descripcion": "regex a buscar en la bitacora"},
              {"nombre": "n", "tipo": "integer", "requerido": False,
               "descripcion": "ultimas n coincidencias (default 20)"}])
def _bitacora_buscar(args, ctx):
    tid = (ctx or {}).get("_horizonte_task_id", "")
    if not tid:
        return ("RESULTADO bitacora_buscar: ERROR solo disponible dentro de "
                "una tarea /hacer en modo horizonte (COGNIA_HORIZONTE=1, "
                "regimen nativo)")
    # El patron es un REGEX y puede contener '|' (alternacion): va ULTIMO.
    # Formato: '<n> | <patron>' o solo '<patron>' — el primer token solo se
    # trata como n si es un entero puro; si no, TODO el args es el patron.
    patron, n = (args or "").strip(), 20
    partes = re.split(r"\s*\|\s*", patron, maxsplit=1)
    if len(partes) == 2 and partes[0].strip().isdigit():
        n = int(partes[0])
        patron = partes[1].strip()
    if not patron:
        return "RESULTADO bitacora_buscar: ERROR falta el patron a buscar"
    from cognia.agent.bitacora import buscar
    return ("RESULTADO bitacora_buscar:\n"
            + buscar(patron, ultimas_n=n, task_id=tid))


# ── Tools de VOZ (opt-in COGNIA_VOZ_TOOLS=1, flota multimodal 2026-08-09) ──
# Opt-in duro como imagen/pantalla: tools default-ON degradan al 3B
# (A/B 2026-07-25: camino feliz 4.25/5 -> 2.5/5).
if os.environ.get("COGNIA_VOZ_TOOLS") == "1":
    try:
        from cognia.agent import voz_tools as _voz_tools
        _voz_tools.register(tool)
        for _t in ("voz_decir", "voz_escuchar", "voz_clonar"):
            ROLE_TOOLS["implementador"].add(_t)
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_VOZ_TOOLS=1 pero voz_tools no cargo: {_exc}",
              file=sys.stderr)


# ── Tool de MUSICA (opt-in COGNIA_MUSICA_TOOLS=1, flota multimodal) ────────
# Opt-in duro como imagen/pantalla: tools default-ON degradan al 3B
# (A/B 2026-07-25: camino feliz 4.25/5 -> 2.5/5).
if os.environ.get("COGNIA_MUSICA_TOOLS") == "1":
    try:
        from cognia.agent import musica_tools as _musica_tools
        _musica_tools.register(tool)
        ROLE_TOOLS["implementador"].add("musica_orquestar")
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_MUSICA_TOOLS=1 pero musica_tools no cargo: "
              f"{_exc}", file=sys.stderr)


# ── Tool 3D (opt-in COGNIA_3D_TOOLS=1, flota multimodal) ───────────────────
# Opt-in duro como imagen/pantalla: tools default-ON degradan al 3B
# (A/B 2026-07-25: camino feliz 4.25/5 -> 2.5/5).
if os.environ.get("COGNIA_3D_TOOLS") == "1":
    try:
        from cognia.agent import tresd_tools as _tresd_tools
        _tresd_tools.register(tool)
        ROLE_TOOLS["implementador"].add("tresd_generar")
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_3D_TOOLS=1 pero tresd_tools no cargo: {_exc}",
              file=sys.stderr)


# ── Tool VLM (opt-in COGNIA_VLM_TOOLS=1, flota multimodal) ─────────────────
# Opt-in duro como imagen/pantalla: tools default-ON degradan al 3B
# (A/B 2026-07-25: camino feliz 4.25/5 -> 2.5/5). vlm_mirar es de
# solo-lectura: tambien va al rol investigador.
if os.environ.get("COGNIA_VLM_TOOLS") == "1":
    try:
        from cognia.agent import vlm_tools as _vlm_tools
        _vlm_tools.register(tool)
        ROLE_TOOLS["implementador"].add("vlm_mirar")
        ROLE_TOOLS["investigador"].add("vlm_mirar")
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_VLM_TOOLS=1 pero vlm_tools no cargo: {_exc}",
              file=sys.stderr)


# ── Tools RLM (contexto largo por tools, 2026-08-11) ───────────────────────
# Siempre registradas (patron horizonte: sin deps, baratas) pero NO en
# CORE_TOOLS: solo se anuncian cuando /rlm arma el modo via _allowed_tools;
# sin ctx["_rlm"] cada tool degrada con causa visible en runtime.
try:
    from cognia.agent import rlm as _rlm_mod
    _rlm_mod.register(tool)
except Exception as _exc:
    # Sin flag que lo justifique: el silencio seria capacidad perdida.
    print(f"[cognia] tools RLM no cargaron: {_exc}", file=sys.stderr)


# ── Tools del ARNES (destiladas de los harnesses punteros, 2026-08-12) ─────
# Se registran SIEMPRE (para que existan y el mensaje de run_tool sea
# "DESHABILITADA — activala con <FLAG>=1" en vez de "no existe"), pero cada una
# lleva su flag en _OPTIN_NOMBRES, asi que el catalogo por defecto NO crece.
# El import va al final a proposito: tools_harness importa este modulo para
# usar el decorador @tool, y hacerlo antes cerraria el ciclo.
try:
    from cognia.harness import tools_harness as _tools_harness  # noqa: F401
except Exception as _exc:
    print(f"[cognia] tools del arnes no cargaron: {_exc}", file=sys.stderr)


# ── Tools TX/LIBRO (agente de horizonte largo, 2026-08-19) ────────────────
# OPT-IN DURO, como las tools VLM: con COGNIA_TX apagado el registry NO cambia
# ni un byte. Esa es la condicion que puso el dueno para todo el subsistema TX
# (el bucle del agente lo usa a diario) y se testea en tests/test_cli_tx.py.
# Con el flag encendido tampoco entran en CORE_TOOLS: las anuncia el modo TX.
# `tx.flag.activo()` y no `_flag_activo("COGNIA_TX")`: `/tx on` guarda el flag
# en la CONFIG, y con el env sin poner este bloque no corria nunca. En una
# sesion nueva eso dejaba al modelo sin las 7 puertas por las que escribe
# memoria mientras el REPL decia ACTIVO, y `run_tool('decidir', ...)`
# contestaba "no existe" -- justo el mensaje que el comentario de
# `_OPTIN_NOMBRES` dice haber eliminado.
def _tx_encendido() -> bool:
    try:
        from cognia.tx.flag import activo as _flag_tx
        return _flag_tx()
    except Exception:
        return _flag_activo("COGNIA_TX")


if _tx_encendido():
    try:
        from cognia.tx import tools as _tx_tools
        _tx_tools.register(tool)
    except Exception as _exc:
        # Flag puesto por el dueno: el silencio seria capacidad desconectada.
        print(f"[cognia] COGNIA_TX=1 pero cognia/tx/tools.py no cargo: {_exc}",
              file=sys.stderr)
