r"""
cognia/agent/flows.py — flujos estilo n8n (DAG de tools) para Cognia
====================================================================
Mandato del dueño (2026-07-13): programar flujos estilo n8n, manual o
pidiéndole a Cognia que los organice. La investigación (AGENCIA_RESEARCH):
formato Node-RED `{id, type, wires}` (fácil de escribir/leer para el 3B) que
carga directo a un DAG; features de OpenFlow (retries, timeout, condicional)
que además curan cuelgues que el agente ya sufrió.

Un FLUJO = grafo dirigido acíclico de NODOS; cada nodo ejecuta una TOOL del
registro (cognia.agent.tools) con sus args, y sus salidas fluyen a los nodos
siguientes (wires). Convención n8n: la salida de un nodo se puede interpolar
en los args del siguiente con `{{id}}` (el RESULTADO del nodo `id`).

Modelo de datos (JSON serializable):
  {"nombre": str,
   "nodos": [{"id": str, "tool": str, "args": str, "wires": [ids...],
              "reintentos": int?, "timeout_s": float?, "saltar_si": str?}]}

Determinista y plano (sin clases de más): valida (DAG, tools existen), ordena
topológicamente y ejecuta. El "Cognia organiza el flujo" (desde lenguaje
natural) se apoya en el planner existente (from_plan) — cero LLM nuevo acá.
"""
from __future__ import annotations

import hashlib
import re
import time as _time
from typing import Callable


class FlowError(ValueError):
    pass


def validar(flujo: dict, tool_existe: Callable[[str], bool] | None = None) -> list:
    """Valida estructura + DAG. Devuelve el orden topológico de ids.
    Levanta FlowError con mensaje claro (ciclo, id duplicado, wire colgado,
    tool inexistente si se pasa tool_existe)."""
    nodos = flujo.get("nodos")
    if not isinstance(nodos, list) or not nodos:
        raise FlowError("el flujo no tiene 'nodos'")
    ids = [n.get("id") for n in nodos]
    if any(not i for i in ids):
        raise FlowError("hay nodos sin 'id'")
    if len(set(ids)) != len(ids):
        raise FlowError("ids de nodo duplicados")
    idset = set(ids)
    for n in nodos:
        if not n.get("tool"):
            raise FlowError(f"nodo '{n['id']}' sin 'tool'")
        if tool_existe is not None and not tool_existe(n["tool"]):
            raise FlowError(f"nodo '{n['id']}': tool '{n['tool']}' no existe")
        for w in (n.get("wires") or []):
            if w not in idset:
                raise FlowError(f"nodo '{n['id']}': wire a id inexistente '{w}'")
    # orden topológico (Kahn) — detecta ciclos
    hijos = {i: list(n.get("wires") or []) for i, n in zip(ids, nodos)}
    indeg = {i: 0 for i in ids}
    for i in ids:
        for w in hijos[i]:
            indeg[w] += 1
    cola = [i for i in ids if indeg[i] == 0]
    orden = []
    while cola:
        i = cola.pop(0)
        orden.append(i)
        for w in hijos[i]:
            indeg[w] -= 1
            if indeg[w] == 0:
                cola.append(w)
    if len(orden) != len(ids):
        raise FlowError("el flujo tiene un CICLO (no es un DAG)")
    return orden


_INTERP = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+)\s*\}\}")


def _interpolar(args: str, salidas: dict) -> str:
    """Reemplaza {{id}} por el RESULTADO (recortado) del nodo id ya ejecutado."""
    return _INTERP.sub(lambda m: str(salidas.get(m.group(1), ""))[:2000], args or "")


def _clave_cache(tool: str, args: str) -> str:
    """Clave de cache de un nodo: sha256 de tool + args YA interpolados.
    El separador NUL evita colisiones por concatenacion ambigua (tool 'ab'
    con args 'c' vs tool 'a' con args 'bc')."""
    return hashlib.sha256(f"{tool}\x00{args}".encode("utf-8")).hexdigest()


def _correr_nodo(n: dict, args: str, ctx: dict, run_tool, log) -> tuple:
    """Corre UN nodo (reintentos + timeout best-effort). Devuelve (res, ok).
    Extraido de ejecutar() sin cambiar semantica para que el despacho
    paralelo reuse exactamente el mismo camino que el secuencial."""
    nid = n["id"]
    intentos = max(1, int(n.get("reintentos", 0)) + 1)
    timeout = n.get("timeout_s")
    res, ok = "", False
    for k in range(intentos):
        t0 = _time.time()
        try:
            res = run_tool(n["tool"], args, ctx)
        except Exception as exc:
            res = f"RESULTADO {n['tool']} ERROR: {exc}"
        dt = _time.time() - t0
        if timeout is not None and dt > float(timeout):
            res = (f"RESULTADO {n['tool']} ERROR: timeout "
                   f"({dt:.1f}s > {timeout}s)")
        ok = not re.search(r"\bERROR\b", res[:120])
        if log:
            log(f"[flujo] {nid} ({n['tool']}) intento {k+1}/{intentos}: "
                f"{'ok' if ok else 'error'}")
        if ok:
            break
    return res, ok


def ejecutar(flujo: dict, ctx: dict, run_tool: Callable[[str, str, dict], str],
             tool_existe: Callable[[str], bool] | None = None,
             log: Callable[[str], None] | None = None,
             paralelo: bool = False, cap: int = 2,
             cache: dict | None = None) -> dict:
    """Ejecuta el flujo en orden topológico. run_tool(name,args,ctx)->str es
    el dispatcher del registro (cognia.agent.tools.run_tool). Devuelve
    {"salidas": {id: resultado}, "orden": [...], "errores": {id: msg},
     "saltados": [ids], "cacheados": [ids]}.

    Por nodo: interpola {{deps}} en args, aplica `saltar_si` (si el texto
    aparece en alguna salida previa → se salta), reintenta `reintentos` veces
    y respeta `timeout_s` (best-effort por wall-clock; el tool corre igual,
    pero se marca timeout si excede). Un nodo que falla NO frena el flujo:
    se registra y sus dependientes reciben su error interpolado.

    paralelo=True (opt-in): despacho por NIVELES topológicos — un nivel son
    los nodos cuyas dependencias (padres) ya terminaron; los hermanos del
    mismo nivel corren juntos en un ThreadPoolExecutor(cap). cap default 2:
    la física medida de esta máquina es que un solo slot de GPU serializa y
    2-3 hilos solo solapan I/O, más no compra nada.
    DESVÍO SEMÁNTICO (por esto es opt-in y el default queda intacto): con
    paralelo, `saltar_si` y la interpolación {{id}} ven las salidas de los
    NIVELES previos COMPLETOS, nunca las de hermanos del mismo nivel. En
    secuencial un hermano posterior sí veía al anterior (el orden de Kahn los
    serializaba); en paralelo ese orden no existe, así que un `saltar_si` que
    dependía de un hermano deja de dispararse y un {{hermano}} interpola "".

    cache (opcional): dict {clave: salida} con clave = sha256(tool + args ya
    interpolados). Un nodo cuya clave está en el cache con salida ok se reusa
    sin ejecutar (queda anotado en "cacheados"); las salidas con ERROR no se
    guardan ni se reusan (un error viejo no debe enmascarar un reintento).
    El dict se MUTA con las salidas ok nuevas: el llamador decide si persiste."""
    orden = validar(flujo, tool_existe)
    by_id = {n["id"]: n for n in flujo["nodos"]}
    salidas: dict[str, str] = {}
    errores: dict[str, str] = {}
    saltados: list = []
    cacheados: list = []

    def _paso(nid: str, vista: dict) -> tuple:
        """Procesa un nodo mirando SOLO `vista` (las salidas que le tocan
        ver: todas las previas en secuencial, los niveles completos en
        paralelo). Devuelve (res, ok, estado) con estado en
        {'ok','error','saltado','cacheado'}."""
        n = by_id[nid]
        cond = (n.get("saltar_si") or "").strip()
        if cond and any(cond in v for v in vista.values()):
            if log:
                log(f"[flujo] {nid} saltado (saltar_si '{cond}')")
            return f"(saltado: '{cond}')", True, "saltado"
        args = _interpolar(n.get("args", ""), vista)
        if cache is not None:
            clave = _clave_cache(n["tool"], args)
            prev = cache.get(clave)
            # solo se reusa una salida SANA: un ERROR cacheado no vale
            if prev is not None and not re.search(r"\bERROR\b", str(prev)[:120]):
                if log:
                    log(f"[flujo] {nid} ({n['tool']}) cacheado")
                return str(prev), True, "cacheado"
        res, ok = _correr_nodo(n, args, ctx, run_tool, log)
        if cache is not None and ok:
            cache[clave] = res
        return res, ok, ("ok" if ok else "error")

    def _anotar(nid: str, res: str, ok: bool, estado: str) -> None:
        salidas[nid] = res
        if estado == "saltado":
            saltados.append(nid)
        elif estado == "cacheado":
            cacheados.append(nid)
        if not ok:
            errores[nid] = res[:200]

    if not paralelo:
        for nid in orden:
            res, ok, estado = _paso(nid, salidas)
            _anotar(nid, res, ok, estado)
    else:
        from concurrent.futures import ThreadPoolExecutor
        # padres (dependencias) de cada nodo, invirtiendo los wires
        padres: dict[str, set] = {i: set() for i in orden}
        for n in flujo["nodos"]:
            for w in (n.get("wires") or []):
                padres[w].add(n["id"])
        pendientes = list(orden)
        hechos: set = set()
        with ThreadPoolExecutor(max_workers=max(1, int(cap))) as pool:
            while pendientes:
                nivel = [i for i in pendientes if padres[i] <= hechos]
                # snapshot: los hermanos del nivel NO se ven entre si (el
                # desvio semantico documentado arriba)
                vista = dict(salidas)
                futs = {i: pool.submit(_paso, i, vista) for i in nivel}
                for i in nivel:
                    res, ok, estado = futs[i].result()
                    _anotar(i, res, ok, estado)
                    hechos.add(i)
                pendientes = [i for i in pendientes if i not in hechos]
    return {"salidas": salidas, "orden": orden, "errores": errores,
            "saltados": saltados, "cacheados": cacheados}


def from_plan(nombre: str, pasos: list) -> dict:
    """Construye un flujo LINEAL desde una lista de pasos (planner.SubTask o
    dicts con 'description'/'tool_required'). Cada paso → un nodo encadenado
    al siguiente. Es el puente "Cognia organiza el flujo": el planner
    determinista arma los pasos, esto los vuelve un DAG ejecutable."""
    nodos = []
    prev = None
    for i, p in enumerate(pasos):
        pid = f"n{i}"
        tool = (getattr(p, "tool_required", None)
                or (p.get("tool_required") if isinstance(p, dict) else None)
                or (p.get("tool") if isinstance(p, dict) else None)
                or "responder")
        desc = (getattr(p, "description", None)
                or (p.get("description") if isinstance(p, dict) else "")
                or (p.get("args") if isinstance(p, dict) else "") or "")
        # modelo recomendado por Cognia para ese paso (color del nodo)
        try:
            from cognia.oficina.identidad import recomendar_modelo
            modelo = recomendar_modelo(tool)
        except Exception:
            modelo = None
        nodos.append({"id": pid, "tool": tool, "args": desc, "wires": [],
                      "modelo": modelo})
        if prev is not None:
            nodos[prev]["wires"].append(pid)
        prev = i
    return {"nombre": nombre, "nodos": nodos}


def organizar_flujo(texto: str) -> dict:
    """"Cognia organiza el flujo": desde una descripción en lenguaje natural,
    usa el planner simbólico (0-LLM) para descomponer en pasos y los vuelve un
    flujo (DAG) ejecutable. Devuelve el flujo. Cero modelo (plan_task es
    determinista por templates)."""
    from cognia.agents.planner import plan_task
    subtasks = plan_task(texto, task_id="flujo")
    flujo = from_plan(texto[:60], subtasks)
    validar(flujo)                      # asegura DAG antes de devolver
    return flujo


def to_json(flujo: dict) -> str:
    import json
    return json.dumps(flujo, ensure_ascii=False, indent=1)


def from_json(texto: str) -> dict:
    import json
    f = json.loads(texto)
    if "nodos" not in f:
        raise FlowError("JSON sin 'nodos'")
    return f


# ── resolucion de la ruta de un flujo guardado (para ejecutar_flujo) ────────
def _resolver_ruta_flujo(args: str):
    """Ruta del .flujo.json a ejecutar. Sin args -> el .flujo.json del
    workspace (donde persiste crear_flujo). Con args: ruta literal si existe,
    si no se busca en el workspace (con y sin el sufijo .flujo.json).
    Devuelve un Path existente o None."""
    from pathlib import Path
    nombre = (args or "").strip()
    candidatos = []
    try:
        from cognia.agents.workers.dev_tools import _root_actual
        root = Path(_root_actual())
    except Exception:
        root = None
    if not nombre:
        if root is not None:
            candidatos.append(root / ".flujo.json")
    else:
        candidatos.append(Path(nombre))
        if root is not None:
            candidatos.append(root / nombre)
            if not nombre.endswith(".flujo.json"):
                candidatos.append(root / f"{nombre}.flujo.json")
    for c in candidatos:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


# ── tools `crear_flujo` + `ejecutar_flujo` ──────────────────────────────────
def register(tool_decorator) -> None:
    @tool_decorator(
        "crear_flujo",
        "crear_flujo <descripcion> -- organiza la tarea en un flujo (DAG de "
        "pasos estilo n8n) desde lenguaje natural, y lo guarda",
        danger=False)
    def _t_crear_flujo(args, ctx):
        texto = (args or "").strip()
        if not texto:
            return "RESULTADO crear_flujo ERROR: falta la descripcion"
        try:
            flujo = organizar_flujo(texto)
        except Exception as exc:
            return f"RESULTADO crear_flujo ERROR: {exc}"
        # persistir en el workspace del agente
        try:
            from cognia.agents.workers.dev_tools import _root_actual
            from pathlib import Path
            dest = Path(_root_actual()) / ".flujo.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(to_json(flujo), encoding="utf-8")
            # lienzo visual estilo n8n al lado del JSON (flow_view.export
            # estaba escrito y sin llamador de produccion): best-effort, el
            # flujo queda usable aunque el HTML falle.
            try:
                from cognia.agent.flow_view import export as _export_html
                _export_html(flujo, str(dest.with_suffix("")) + ".html",
                             title=f"Cognia · Flujo: {texto[:50]}")
            except Exception:
                pass
        except Exception:
            pass
        pasos = "\n".join(f"  {i+1}. [{n['tool']}] {n['args'][:60]}"
                          for i, n in enumerate(flujo["nodos"]))
        return (f"RESULTADO crear_flujo: {len(flujo['nodos'])} pasos\n{pasos}\n"
                "(guardado en .flujo.json; lienzo en .flujo.html)")

    @tool_decorator(
        "ejecutar_flujo",
        "ejecutar_flujo <nombre|ruta.flujo.json> -- ejecuta un flujo guardado "
        "(DAG de tools) en orden topologico; sin args usa el .flujo.json del "
        "workspace",
        danger=False)
    def _t_ejecutar_flujo(args, ctx):
        import json as _json
        import os
        ctx = ctx if isinstance(ctx, dict) else {}
        # guardia anti-recursion: antes era la bandera _flujo_en_curso (cero
        # anidamiento); ahora es un contador de profundidad con techo 2 — un
        # flujo puede ejecutar UN nivel de sub-flujo, al tercer nivel ERROR.
        depth = ctx.get("_flujo_depth")
        if depth is None:
            # compat: llamadores viejos marcaban la bandera sin contador;
            # respetarla como "sin presupuesto de anidamiento"
            depth = 2 if ctx.get("_flujo_en_curso") else 0
        if depth >= 2:
            return ("RESULTADO ejecutar_flujo ERROR: ya hay un flujo en "
                    "ejecucion (profundidad maxima de sub-flujos: 2)")
        ruta = _resolver_ruta_flujo(args)
        if ruta is None:
            return ("RESULTADO ejecutar_flujo ERROR: no encontre el flujo "
                    f"'{(args or '').strip() or '.flujo.json'}' (crealo antes "
                    "con crear_flujo)")
        try:
            flujo = from_json(ruta.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"RESULTADO ejecutar_flujo ERROR: {ruta.name} invalido: {exc}"
        # dispatcher REAL del registro: import local (tools.py importa este
        # modulo al registrar -> import a nivel de modulo seria un ciclo).
        from cognia.agent.tools import TOOLS, run_tool
        log = ctx.get("print_fn") if callable(ctx.get("print_fn")) else None
        # opt-in estrictos por env (== "1", el parse de la casa): el paralelo
        # cambia la semantica de saltar_si entre hermanos y el cache persiste
        # estado en disco — ninguno debe activarse solo.
        paralelo = os.environ.get("COGNIA_FLOWS_PARALELO", "") == "1"
        cache, cache_ruta = None, None
        if os.environ.get("COGNIA_FLOWS_CACHE", "") == "1":
            cache = {}
            try:
                from pathlib import Path
                from cognia.agents.workers.dev_tools import _root_actual
                cache_ruta = Path(_root_actual()) / ".flujo_cache.json"
                if cache_ruta.is_file():
                    prev = _json.loads(cache_ruta.read_text(encoding="utf-8"))
                    if isinstance(prev, dict):
                        cache = prev
            except Exception:
                cache_ruta = None       # sin workspace/JSON roto: cache en RAM
        # la profundidad viaja POR RAMA en una copia superficial del ctx, no
        # como contador mutado en el ctx compartido: con paralelo, dos nodos
        # ejecutar_flujo hermanos comparten ctx y el patron leer/incrementar/
        # decrementar sufria carrera (ambos leian 1, ambos escribian 2 y sus
        # dos finally lo bajaban a 0 -> el sub-flujo del nivel siguiente
        # arrancaba como top-level y su cadena anidada burlaba la guardia).
        # Los objetos anidados (agent_state, working_memory, print_fn) se
        # comparten igual por ser copia superficial; el padre nunca ve su
        # nivel alterado porque su dict ya no se toca.
        ctx_hijo = dict(ctx)
        ctx_hijo["_flujo_depth"] = depth + 1
        try:
            res = ejecutar(flujo, ctx_hijo, run_tool,
                           tool_existe=lambda n: n in TOOLS, log=log,
                           paralelo=paralelo, cache=cache)
        except FlowError as exc:
            return f"RESULTADO ejecutar_flujo ERROR: {exc}"
        if cache_ruta is not None:
            # persistencia atomica tmp+replace (patron estado_tarea.py).
            # Fusion con lo que haya en disco ANTES de escribir (fix
            # 2026-08-11): un sub-flujo hijo persiste SU cache mientras este
            # flujo corre, y escribir solo `cache` (el snapshot leido al
            # arrancar + los nodos propios) PISABA las claves del hijo. En
            # colision de clave gana lo propio: es lo mas fresco de ESTA
            # corrida.
            try:
                fusion = {}
                try:
                    if cache_ruta.is_file():
                        prev = _json.loads(
                            cache_ruta.read_text(encoding="utf-8"))
                        if isinstance(prev, dict):
                            fusion = prev
                except Exception:
                    pass        # JSON roto en disco: se escribe lo propio
                fusion.update(cache)
                tmp = cache_ruta.with_suffix(".json.tmp")
                tmp.write_text(_json.dumps(fusion, ensure_ascii=False),
                               encoding="utf-8")
                os.replace(tmp, cache_ruta)
            except Exception:
                pass                    # el cache es aceleracion, no estado
        lineas = []
        for nid in res["orden"]:
            estado = ("saltado" if nid in res["saltados"]
                      else "cacheado" if nid in res.get("cacheados", [])
                      else "error" if nid in res["errores"] else "ok")
            lineas.append(f"  {nid}: {estado} - "
                          f"{str(res['salidas'].get(nid, ''))[:80]}")
        n_err = len(res["errores"])
        cabeza = (f"RESULTADO ejecutar_flujo {ruta.name}: "
                  f"{len(res['orden'])} nodos, {n_err} con error, "
                  f"{len(res['saltados'])} saltados")
        if cache is not None:
            cabeza += f", {len(res.get('cacheados', []))} cacheados"
        return cabeza + "\n" + "\n".join(lineas)
