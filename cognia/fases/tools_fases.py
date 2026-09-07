# -*- coding: utf-8 -*-
"""
cognia/fases/tools_fases.py — las tools con las que el agente escribe en el
PROJECT STATE de la obra por fases (y lo consulta).

  fases_estado                         el estado (fase, DoD, issues, no tocar)
  fases_dod ver | marcar <id> ok|fallo [| evidencia=...] | definir <json>
  fases_issue agregar <P0..P4> | <titulo> [| pasos=..] [| esperado=..] [| actual=..] [| evidencia=..] [| causa=..]
  fases_issue cerrar <#id> [| causa=..] [| fix=..]   ·   fases_issue lista
  fases_hipotesis <texto> [| plan=..] [| esperado=..]
  fases_estable <que> [| motivo=..] [| quitar=1]

El workspace de la obra sale de COGNIA_FASES_WORKSPACE (lo siembra el
pipeline), de ctx['workspace'] o del cwd. Sin obra en curso cada tool lo dice.
Se registran SIEMPRE (baratas, sin deps) pero no entran en CORE_TOOLS: el
pipeline las anuncia via allowed_tools; fuera de una obra degradan con causa.
"""
from __future__ import annotations

import os
from pathlib import Path

from cognia.agent import pruebas_comun as PC
from cognia.fases import dod as _dod
from cognia.fases import estado as _est

NOMBRES = ("fases_estado", "fases_dod", "fases_issue", "fases_hipotesis", "fases_estable")


def _workspace(ctx) -> str:
    ws = os.environ.get("COGNIA_FASES_WORKSPACE") or ((ctx or {}).get("workspace") if isinstance(ctx, dict) else None) or os.getcwd()
    return str(Path(ws).resolve())


def _cargar(ctx):
    ws = _workspace(ctx)
    est = _est.cargar(ws)
    if est is None:
        raise ValueError("no hay una obra por fases en curso en %s (arrancala con /fases \"<encargo>\")" % ws)
    return est


def _err(tool, exc) -> str:
    return "RESULTADO %s ERROR: %s" % (tool, str(exc)[:400])


def register(tool) -> None:
    @tool("fases_estado",
          "fases_estado  -- el estado de la obra por fases: fase actual, Definicion de Hecho, issues abiertos, NO TOCAR",
          desc="Muestra el PROJECT STATE de la obra en curso: fase actual, requisitos de la Definicion de Hecho con su "
               "estado (OK / FALLA / sin verificar), issues abiertos por prioridad, sistemas estables que no se tocan y la "
               "ultima version aceptada. Leelo antes de decidir que hacer en la iteracion.",
          params=[], timeout_s=30)
    def _fases_estado(args, ctx):
        try:
            est = _cargar(ctx)
        except ValueError as exc:
            return _err("fases_estado", exc)
        return "RESULTADO fases_estado:\n" + _est.render_md(est, para_modelo=True)

    @tool("fases_dod",
          "fases_dod ver | marcar <id> ok|fallo [| evidencia=...] | definir <json>  -- la Definicion de Hecho: verla, marcar un requisito manual con evidencia, o definirla (fase de planificacion)",
          desc="La Definicion de Hecho (Definition of Done) de la obra. `ver` la lista; `marcar F3 ok | evidencia=captura x.png "
               "muestra...` marca un requisito MANUAL (visual/UX) con la evidencia que lo prueba; `definir <json>` la escribe "
               "entera (solo en la fase de planificacion, con el formato JSON pedido). Los requisitos con verificacion ejecutable "
               "los marca el verificador, no vos.",
          params=[{"nombre": "accion", "tipo": "string", "requerido": True, "descripcion": "ver | marcar <id> ok|fallo | definir <json>"},
                  {"nombre": "evidencia", "tipo": "string", "requerido": False, "clave": True, "descripcion": "que lo prueba (captura, salida, test)"}],
          timeout_s=30)
    def _fases_dod(args, ctx):
        s, o = PC.partir_args(args, ("evidencia",))
        try:
            est = _cargar(ctx)
        except ValueError as exc:
            return _err("fases_dod", exc)
        partes = s.split(None, 1)
        op = (partes[0] if partes else "ver").lower()
        resto = partes[1] if len(partes) > 1 else ""
        if op == "ver" or not op:
            res = _dod.resumen(est["dod"])
            lineas = ["RESULTADO fases_dod: %d/%d OK, %d fallan, %d sin verificar" % (res["ok"], res["total"], res["fallan"], res["sin"])]
            for it in _dod.items(est["dod"]):
                lineas.append("  " + _est._linea_req(it))
            return "\n".join(lineas)
        if op == "marcar":
            toks = resto.split()
            if len(toks) < 2 or toks[1].lower() not in ("ok", "fallo", "falla", "no"):
                return _err("fases_dod", "uso: fases_dod marcar <id> ok|fallo | evidencia=...")
            it = _dod.buscar(est["dod"], toks[0])
            if it is None:
                return _err("fases_dod", "no existe el requisito %s" % toks[0])
            if (it.get("verif") or {}).get("tipo") != "manual":
                return _err("fases_dod", "%s tiene verificacion ejecutable (%s): la marca el verificador, no vos. Arregla el producto y se re-verifica"
                            % (it["id"], it["verif"]["tipo"]))
            if not o.get("evidencia"):
                return _err("fases_dod", "sin evidencia no se marca: pasa evidencia=<que captura/salida lo prueba>")
            _dod.marcar(est["dod"], it["id"], toks[1].lower() == "ok", o.get("evidencia", ""))
            _est.guardar(est)
            return "RESULTADO fases_dod: %s marcado %s (evidencia: %s)" % (it["id"], toks[1].upper(), o.get("evidencia", "")[:120])
        if op == "definir":
            d = _dod.parsear_json(resto)
            if d is None:
                return _err("fases_dod", "no encontre un JSON valido con funcionales/visuales/calidad. Formato:\n" + _dod.plantilla_para_modelo())
            meta = d.pop("_meta", {})
            est["dod"] = d
            if meta.get("tipo_producto"):
                est["tipo_producto"] = str(meta["tipo_producto"]).strip().lower()
            if meta.get("entrypoint"):
                est["entrypoint"] = str(meta["entrypoint"]).strip()
            if meta.get("arquitectura"):
                est["notas"].append("arquitectura: " + str(meta["arquitectura"])[:800])
            _est.guardar(est)
            res = _dod.resumen(d)
            return ("RESULTADO fases_dod: Definicion de Hecho guardada: %d requisitos (%d con verificacion ejecutable, %d manuales) · tipo %s · entrypoint %s"
                    % (res["total"], res["total"] - res["manuales"], res["manuales"], est.get("tipo_producto") or "?", est.get("entrypoint") or "?"))
        return _err("fases_dod", "accion desconocida %r (ver | marcar | definir)" % op)

    @tool("fases_issue",
          "fases_issue agregar <P0..P4> | <titulo> [| pasos=..] [| esperado=..] [| actual=..] [| evidencia=..] [| causa=..] · cerrar <#id> [| causa=..] [| fix=..] · lista"
          "  -- el registro de bugs (Known Issues) con prioridad",
          desc="Registra un bug reproducible con su prioridad (P0 bloqueante, P1 critico, P2 alto, P3 medio, P4 bajo), pasos para "
               "reproducirlo, esperado, actual, evidencia y causa probable; cierra uno cuando esta arreglado (con causa y fix); "
               "lista los abiertos por prioridad. El juez rechaza una version que abre P0 nuevos y premia las que cierran issues.",
          params=[{"nombre": "accion", "tipo": "string", "requerido": True, "descripcion": "agregar <P> | <titulo> · cerrar <#id> · lista"},
                  {"nombre": "pasos", "tipo": "string", "requerido": False, "clave": True, "descripcion": "pasos para reproducir"},
                  {"nombre": "esperado", "tipo": "string", "requerido": False, "clave": True, "descripcion": "que deberia pasar"},
                  {"nombre": "actual", "tipo": "string", "requerido": False, "clave": True, "descripcion": "que pasa"},
                  {"nombre": "evidencia", "tipo": "string", "requerido": False, "clave": True, "descripcion": "captura, salida o test que lo muestra"},
                  {"nombre": "causa", "tipo": "string", "requerido": False, "clave": True, "descripcion": "causa probable o confirmada"},
                  {"nombre": "fix", "tipo": "string", "requerido": False, "clave": True, "descripcion": "que se cambio para arreglarlo"}],
          timeout_s=30)
    def _fases_issue(args, ctx):
        s, o = PC.partir_args(args, ("pasos", "esperado", "actual", "evidencia", "causa", "fix"))
        try:
            est = _cargar(ctx)
        except ValueError as exc:
            return _err("fases_issue", exc)
        partes = s.split(None, 1)
        op = (partes[0] if partes else "lista").lower()
        resto = partes[1] if len(partes) > 1 else ""
        if op == "agregar":
            m = resto.split("|", 1)
            if len(m) < 2:
                return _err("fases_issue", "uso: fases_issue agregar P2 | titulo | pasos=... | esperado=... | actual=...")
            it = _est.issue_agregar(est, m[0].strip(), m[1].strip(), o.get("pasos", ""), o.get("esperado", ""),
                                    o.get("actual", ""), o.get("evidencia", ""), o.get("causa", ""))
            _est.guardar(est)
            return "RESULTADO fases_issue: %s %s registrado: %s" % (it["id"], it["prioridad"], it["titulo"])
        if op == "cerrar":
            it = _est.issue_cerrar(est, resto.strip(), o.get("causa", ""), o.get("fix", ""))
            if it is None:
                return _err("fases_issue", "no existe el issue %r" % resto.strip())
            _est.guardar(est)
            return "RESULTADO fases_issue: %s cerrado (%s)" % (it["id"], it["titulo"])
        ab = _est.issues_abiertos(est)
        if not ab:
            return "RESULTADO fases_issue: sin issues abiertos"
        return "RESULTADO fases_issue (%d abiertos):\n" % len(ab) + "\n".join(
            "  %s %s %s%s" % (i["id"], i["prioridad"], i["titulo"], (" -- pasos: " + i["pasos"][:120]) if i.get("pasos") else "") for i in ab)

    @tool("fases_hipotesis",
          "fases_hipotesis <hipotesis> [| plan=1. ...; 2. ...] [| esperado=...]  -- declara la hipotesis de la iteracion ANTES de tocar codigo",
          desc="Cada iteracion es un experimento: declara que crees que pasa y por que, el plan (pocos pasos, una sola cosa) y el "
               "resultado esperado. El juez la guarda junto a la version para saber que se intento y si funciono.",
          params=[{"nombre": "hipotesis", "tipo": "string", "requerido": True, "descripcion": "que crees que pasa y por que"},
                  {"nombre": "plan", "tipo": "string", "requerido": False, "clave": True, "descripcion": "pasos concretos"},
                  {"nombre": "esperado", "tipo": "string", "requerido": False, "clave": True, "descripcion": "resultado esperado y como se valida"}],
          timeout_s=30)
    def _fases_hipotesis(args, ctx):
        s, o = PC.partir_args(args, ("plan", "esperado"))
        try:
            est = _cargar(ctx)
        except ValueError as exc:
            return _err("fases_hipotesis", exc)
        if not s.strip():
            return _err("fases_hipotesis", "falta la hipotesis")
        est["hipotesis"] = {"texto": s.strip()[:400], "plan": o.get("plan", "")[:600], "esperado": o.get("esperado", "")[:300],
                            "fase": est.get("fase_actual", "")}
        _est.guardar(est)
        return "RESULTADO fases_hipotesis: registrada. Ahora: cambios pequenos, verifica con tools reales, y reporta HIPOTESIS/CAMBIOS/RESULTADO."

    @tool("fases_estable",
          "fases_estable <fichero o sistema> [| motivo=...] [| quitar=1]  -- marca algo como ESTABLE (NO TOCAR) o lo desmarca",
          desc="Un sistema que ya pasa todos sus requisitos y no tiene bugs se marca estable: las fases siguientes no lo tocan "
               "salvo razon concreta, y el juez rechaza una version que lo modifique fuera de la regresion final.",
          params=[{"nombre": "que", "tipo": "string", "requerido": True, "descripcion": "ruta de fichero (o carpeta) o nombre del sistema"},
                  {"nombre": "motivo", "tipo": "string", "requerido": False, "clave": True, "descripcion": "por que es estable"},
                  {"nombre": "quitar", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "1 = desmarcar"}],
          timeout_s=30)
    def _fases_estable(args, ctx):
        s, o = PC.partir_args(args, ("motivo", "quitar"))
        try:
            est = _cargar(ctx)
        except ValueError as exc:
            return _err("fases_estable", exc)
        if not s.strip():
            return _err("fases_estable", "falta que marcar")
        if o.get("quitar") == "1":
            ok = _est.estable_quitar(est, s)
            _est.guardar(est)
            return "RESULTADO fases_estable: %s" % ("desmarcado " + s if ok else "no estaba marcado " + s)
        _est.estable_agregar(est, s, o.get("motivo", ""))
        _est.guardar(est)
        return "RESULTADO fases_estable: %s marcado NO TOCAR (%d estables)" % (s.strip(), len(est["estables"]))
