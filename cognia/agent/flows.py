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


def ejecutar(flujo: dict, ctx: dict, run_tool: Callable[[str, str, dict], str],
             tool_existe: Callable[[str], bool] | None = None,
             log: Callable[[str], None] | None = None) -> dict:
    """Ejecuta el flujo en orden topológico. run_tool(name,args,ctx)->str es
    el dispatcher del registro (cognia.agent.tools.run_tool). Devuelve
    {"salidas": {id: resultado}, "orden": [...], "errores": {id: msg},
     "saltados": [ids]}.

    Por nodo: interpola {{deps}} en args, aplica `saltar_si` (si el texto
    aparece en alguna salida previa → se salta), reintenta `reintentos` veces
    y respeta `timeout_s` (best-effort por wall-clock; el tool corre igual,
    pero se marca timeout si excede). Un nodo que falla NO frena el flujo:
    se registra y sus dependientes reciben su error interpolado."""
    orden = validar(flujo, tool_existe)
    by_id = {n["id"]: n for n in flujo["nodos"]}
    salidas: dict[str, str] = {}
    errores: dict[str, str] = {}
    saltados: list = []
    for nid in orden:
        n = by_id[nid]
        cond = (n.get("saltar_si") or "").strip()
        if cond and any(cond in v for v in salidas.values()):
            saltados.append(nid)
            salidas[nid] = f"(saltado: '{cond}')"
            if log:
                log(f"[flujo] {nid} saltado (saltar_si '{cond}')")
            continue
        args = _interpolar(n.get("args", ""), salidas)
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
        salidas[nid] = res
        if not ok:
            errores[nid] = res[:200]
    return {"salidas": salidas, "orden": orden, "errores": errores,
            "saltados": saltados}


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
        nodos.append({"id": pid, "tool": tool, "args": desc, "wires": []})
        if prev is not None:
            nodos[prev]["wires"].append(pid)
        prev = i
    return {"nombre": nombre, "nodos": nodos}


def to_json(flujo: dict) -> str:
    import json
    return json.dumps(flujo, ensure_ascii=False, indent=1)


def from_json(texto: str) -> dict:
    import json
    f = json.loads(texto)
    if "nodos" not in f:
        raise FlowError("JSON sin 'nodos'")
    return f
