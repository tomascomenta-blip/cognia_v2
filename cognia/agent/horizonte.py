"""
cognia/agent/horizonte.py
=========================
Outer loop de LONG TASK HORIZON (opt-in COGNIA_HORIZONTE=1).

POR QUE EXISTE: el bucle nativo corre UN ciclo con toda la memoria en el KV;
en tareas multi-entregable el modelo cierra dejando criterios sin cumplir (el
patron medido de la campana 2026-07-21) y el unico remedio era la SEGUNDA
PASADA — enterrada por A6 por sus dos bugs (recursion de _run_agent_task que
duplicaba la corrida entera, y criterios re-derivados de texto contaminado).

Este modulo aplica la sintesis de la investigacion long-horizon (2026-08-09,
BigBang-v1 / LongHorizon-Harness / PRO-LONG / HiAgent / plan-and-act):

- CICLOS con contexto FRESCO (fresh-context, LongHorizon-Harness): cada relevo
  re-arranca el bucle con [objetivo original, delta determinista], no arrastra
  el KV degradado del ciclo anterior — el contexto fresco es justamente la
  cura del estancamiento.
- Sello EJECUTABLE por ciclo (durable verified state): GoalContract.check()
  con evidencia real de filesystem/comando; el plan ES la lista 'faltan' del
  contrato (sin plan-texto en el prompt: A6).
- Criterios CONGELADOS: derivados UNA vez de la letra original saneada, jamas
  re-derivados (mata estructuralmente el bug A6).
- Estado durable + bitacora en disco (estado_tarea.py / bitacora.py): la
  tarea sobrevive al proceso y el agente puede consultar su propia historia
  (tarea_estado / bitacora_buscar) en vez de suponer.
- Progreso MONOTONO: si un relevo no sube satisfied_count, se corta (la
  memoria del repo: las rondas sin sello real RESTAN; aca el sello es real
  pero el churn se corta determinista).

CONTRATO RALPH (2026-08-24, packages/workflow/tool-ralph de deepseek-harness):
cada ronda es un worker FRESCO que, ademas de trabajar, REPORTA con un
documento de EXACTAMENTE 5 campos {status, summary, evidence, nextSteps,
blocker} y reglas duras por estado (ver validar_report). El report se valida
DOS veces (al parsear la salida del worker y al consumirlo para el traspaso),
el traspaso serializado tiene tope de chars (HANDOFF_MAX), un report invalido
se vuelve a pedir UNA vez citando el error y si vuelve a fallar la ronda se
declara fallida con el motivo (jamas se inventa un report). Anti-rendicion
(tool goal de dsh): 'blocked' solo se acepta si el MISMO bloqueo persistio
BLOCKED_RONDAS_MIN rondas seguidas; antes, se convierte en 'continue' con el
bloqueo anotado. Y el resultado NUNCA se presenta como verificado: el cierre
dice 'el worker reporta completado (N rondas)' + la evidencia listada; lo
verificado de verdad sigue siendo SOLO el sello de GoalContract.

NO toca bucle_nativo ni el while legacy: los envuelve. ``bucle`` y
``pedir_report`` son inyectables para testear el outer loop sin GPU.

LIMITACION CONOCIDA (misma que el epilogo de cli.py, pre-existente): el sello
GoalContract.check() resuelve rutas relativas contra el CWD del proceso. Si el
workspace del agente difiere del cwd, un file_exists relativo puede no verse;
el corte por progreso monotono acota el costo a UN relevo estéril. Alinear
check() con el workspace es trabajo de fase 2, junto con el epilogo.
"""

from __future__ import annotations

import json
import os
import re

# Prefijos del result_text de bucle_nativo que clasifican el corte (contrato
# de loop.py: infra y estancamiento se anuncian en el texto, el resto en
# ``finish``). Si loop.py cambia esos literales, los tests de aca lo cazan.
_INFRA_PREFIX = "(el agente no pudo hablar"
_STUCK_PREFIX = "(interrumpida"

FLAG = "COGNIA_HORIZONTE"
ENV_CICLOS = "COGNIA_HORIZONTE_CICLOS"
ENV_HANDOFF_MAX = "COGNIA_HORIZONTE_HANDOFF_MAX"
# Techo duro de rondas: el config/env pueden pedir menos, nunca mas. Subio de
# 3 a 8 con el contrato ralph (las rondas ahora tienen report y traspaso
# acotado); el default sigue saliendo de /esfuerzo (1-3).
_TECHO_CICLOS = 8

# ── Contrato ralph: el report de ronda ───────────────────────────────────────
ESTADOS_REPORT = ("continue", "complete", "blocked")
# Firma EXACTA de claves (sort + join, como la doble validacion de dsh).
FIRMA_REPORT = "blocker,evidence,nextSteps,status,summary"
HANDOFF_MAX = 16384
BLOCKED_RONDAS_MIN = 3

# JSON Schema estricto para response_format (forma verificada en vivo contra
# llama-server en workflows.py: json_schema + strict). additionalProperties
# False y required de los 5: el server ya fuerza la forma por gramatica; la
# validacion de aca es la segunda linea (y la unica en un fake).
SCHEMA_REPORT = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(ESTADOS_REPORT)},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "nextSteps": {"type": "array", "items": {"type": "string"}},
        "blocker": {"type": "string"},
    },
    "required": ["status", "summary", "evidence", "nextSteps", "blocker"],
    "additionalProperties": False,
}


class ReportInvalido(ValueError):
    """El report del worker viola el contrato (mensaje = motivo citable)."""


class HandoffDemasiadoGrande(ValueError):
    """El traspaso serializado supera el tope de chars."""


def habilitado() -> bool:
    """Flag leido a CALL-time (patron del repo: los tests lo setean/limpian)."""
    return os.environ.get(FLAG, "").strip() == "1"


def max_ciclos_env() -> int:
    """Override por env COGNIA_HORIZONTE_CICLOS (techo duro), o 0 si no hay."""
    try:
        n = int(os.environ.get(ENV_CICLOS, "") or 0)
    except ValueError:
        n = 0
    return min(n, _TECHO_CICLOS) if n > 0 else 0


def handoff_max_env() -> int:
    """Tope del traspaso serializado: env COGNIA_HORIZONTE_HANDOFF_MAX (el CLI
    la siembra desde la config 'horizonte_handoff_max') o HANDOFF_MAX."""
    try:
        n = int(os.environ.get(ENV_HANDOFF_MAX, "") or 0)
    except ValueError:
        n = 0
    return n if n > 0 else HANDOFF_MAX


def _str_normalizado(valor, campo: str, vacio_ok: bool = False) -> str:
    if not isinstance(valor, str):
        raise ReportInvalido(f"'{campo}' debe ser string, no "
                             f"{type(valor).__name__}")
    if valor != valor.strip():
        raise ReportInvalido(f"'{campo}' no esta normalizado (espacios al "
                             f"borde)")
    if not valor and not vacio_ok:
        raise ReportInvalido(f"'{campo}' esta vacio")
    return valor


def validar_report(obj) -> dict:
    """Valida el report de 5 campos con las reglas duras de dsh y lo devuelve
    tal cual (sin normalizar: un string sin trim ES invalido). Lanza
    ReportInvalido con el motivo exacto para poder citarlo al worker.

    - claves EXACTAS: sorted(keys).join(',') == FIRMA_REPORT
    - status en {continue, complete, blocked}
    - summary string no vacio y == trim; evidence/nextSteps listas de strings
      no vacios y == trim; blocker string (vacio permitido) == trim
    - continue: nextSteps > 0 y blocker vacio
    - complete: evidence > 0 Y nextSteps == 0 Y blocker vacio
    - blocked: blocker no vacio
    """
    if not isinstance(obj, dict):
        raise ReportInvalido(f"el report debe ser un objeto JSON, no "
                             f"{type(obj).__name__}")
    firma = ",".join(sorted(str(k) for k in obj.keys()))
    if firma != FIRMA_REPORT:
        raise ReportInvalido(f"claves {firma!r} != {FIRMA_REPORT!r}")
    status = obj["status"]
    if status not in ESTADOS_REPORT:
        raise ReportInvalido(f"status {status!r} no esta en "
                             f"{'|'.join(ESTADOS_REPORT)}")
    _str_normalizado(obj["summary"], "summary")
    for campo in ("evidence", "nextSteps"):
        lista = obj[campo]
        if not isinstance(lista, list):
            raise ReportInvalido(f"'{campo}' debe ser una lista de strings")
        for i, item in enumerate(lista):
            _str_normalizado(item, f"{campo}[{i}]")
    blocker = _str_normalizado(obj["blocker"], "blocker", vacio_ok=True)
    if status == "continue":
        if not obj["nextSteps"]:
            raise ReportInvalido("status continue exige nextSteps no vacio")
        if blocker:
            raise ReportInvalido("status continue exige blocker vacio")
    elif status == "complete":
        if not obj["evidence"]:
            raise ReportInvalido("status complete exige evidence no vacio "
                                 "(sin evidencia no hay completado)")
        if obj["nextSteps"]:
            raise ReportInvalido("status complete exige nextSteps vacio")
        if blocker:
            raise ReportInvalido("status complete exige blocker vacio")
    else:
        if not blocker:
            raise ReportInvalido("status blocked exige blocker no vacio")
    return obj


_RE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parsear_report(texto: str) -> dict:
    """PRIMERA validacion: de la salida cruda del worker al dict validado.
    Tolera un fence ```json``` alrededor (el server con gramatica no lo pone,
    un modelo sin response_format a veces si); nada mas se tolera."""
    crudo = (texto or "").strip()
    m = _RE_FENCE.match(crudo)
    if m:
        crudo = m.group(1)
    if not crudo:
        raise ReportInvalido("salida vacia: no hay report")
    try:
        obj = json.loads(crudo)
    except ValueError as exc:
        raise ReportInvalido(f"no es JSON valido ({exc})") from None
    return validar_report(obj)


def serializar_handoff(report: dict, max_chars: int = None) -> str:
    """Traspaso serializado (JSON con claves ordenadas) con tope de chars."""
    tope = max_chars or handoff_max_env()
    txt = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1)
    if len(txt) > tope:
        raise HandoffDemasiadoGrande(
            f"el traspaso serializado tiene {len(txt)} chars y el tope es "
            f"{tope} (config 'horizonte_handoff_max' / {ENV_HANDOFF_MAX}): "
            f"resume summary/evidence/nextSteps")
    return txt


def consumir_report(report: dict, max_chars: int = None) -> str:
    """SEGUNDA validacion, al consumir: mismas reglas + cota del traspaso.
    Devuelve el handoff serializado listo para el prompt de la ronda
    siguiente. Lanza ReportInvalido / HandoffDemasiadoGrande."""
    validar_report(report)
    return serializar_handoff(report, max_chars)


def fusionar_blocked(report: dict, racha: int, blocker_previo: str) -> tuple:
    """Anti-rendicion: 'blocked' se ACEPTA solo si el mismo blocker persistio
    BLOCKED_RONDAS_MIN rondas consecutivas. Antes de eso el report se
    convierte en 'continue' con el bloqueo ANOTADO en summary (y nextSteps
    minimo si no traia). Devuelve (report_resultante, racha_nueva,
    blocker_anotado): racha_nueva es la cuenta de rondas seguidas con ese
    blocker (0 si el report no es blocked); blocker_anotado es '' si no hubo
    conversion."""
    if report.get("status") != "blocked":
        return report, 0, ""
    blocker = report["blocker"]
    racha_nueva = racha + 1 if blocker == blocker_previo else 1
    if racha_nueva >= BLOCKED_RONDAS_MIN:
        return report, racha_nueva, ""
    fusionado = dict(report)
    fusionado["status"] = "continue"
    fusionado["blocker"] = ""
    fusionado["summary"] = (f"[BLOQUEO REPORTADO, no aceptado aun (ronda "
                            f"{racha_nueva}/{BLOCKED_RONDAS_MIN} con el mismo "
                            f"bloqueo): {blocker}] " + report["summary"])
    if not fusionado["nextSteps"]:
        fusionado["nextSteps"] = [
            "Volver a intentar desde el workspace lo que se reporto "
            "bloqueado; si el bloqueo es real, reportarlo con el MISMO "
            "texto de blocker"]
    return fusionado, racha_nueva, blocker


def texto_cierre(report, rondas: int, motivo_fallo: str = "") -> str:
    """Lo que se le dice al dueno al cerrar. NUNCA 'completado' a secas: el
    worker REPORTA y el harness lo repite tal cual, con la evidencia listada
    (dsh: 'the worker reports completion')."""
    r = "ronda" if rondas == 1 else "rondas"
    if not report:
        return (f"el worker no entrego un report valido ({rondas} {r})"
                + (f": {motivo_fallo}" if motivo_fallo else ""))
    st = report.get("status")
    if st == "complete":
        lineas = [f"el worker reporta completado ({rondas} {r}). Evidencia "
                  f"reportada (NO verificada por el harness):"]
        lineas.extend(f"  - {e}" for e in report.get("evidence", []))
        return "\n".join(lineas)
    if st == "blocked":
        return (f"el worker reporta bloqueo ({rondas} {r}): "
                f"{report.get('blocker', '')}")
    lineas = [f"el worker reporta que sigue pendiente ({rondas} {r}). "
              f"Proximos pasos reportados:"]
    lineas.extend(f"  - {p}" for p in report.get("nextSteps", []))
    return "\n".join(lineas)


def prompt_de_ronda(ronda: int, max_rondas: int, delta: str, handoff: str,
                    blocker_anotado: str = "", contrato_faltan: int = 0,
                    report_previo_status: str = "") -> str:
    """El prompt del worker FRESCO de la ronda >= 2 (traduccion de las frases
    clave del prompt de ronda de dsh). ``delta`` es el bloque DETERMINISTA
    del estado (estado_tarea.resumen_para_prompt: hitos verificados, SOLO
    FALTA) y ``handoff`` el report previo serializado (ya con cota)."""
    partes = [
        f"Eres un WORKER FRESCO: no recibes la conversacion previa. Ronda "
        f"{ronda} de {max_rondas}.",
        "El OBJETIVO es INMUTABLE: es la tarea de arriba, tal cual, y no se "
        "renegocia.",
        "El WORKSPACE y su arbol actual son la memoria de largo plazo y la "
        "FUENTE DE VERDAD: inspecciona (listar / leer / ejecutar) antes de "
        "actuar.",
        "El traspaso previo es SOLO un traspaso ACOTADO del worker anterior: "
        "confirmalo contra el workspace antes de darlo por cierto.",
    ]
    if report_previo_status == "complete" and contrato_faltan:
        partes.append(
            f"OJO: el worker anterior reporto 'complete' pero el contrato "
            f"ejecutable del harness sigue con {contrato_faltan} criterio(s) "
            f"sin cumplir: su evidencia NO alcanzo. Manda el contrato.")
    if blocker_anotado:
        partes.append(
            f"BLOQUEO REPORTADO por el worker anterior (no aceptado aun): "
            f"{blocker_anotado}. Intentalo de nuevo desde el workspace; si "
            f"el bloqueo es real, reportalo con el MISMO texto de blocker.")
    if delta:
        partes.append("\n" + delta)
    if handoff:
        partes.append("\nTRASPASO del worker anterior (acotado, sin verificar):\n"
                      + handoff)
    return "\n".join(partes)


_PROMPT_REPORT = (
    "Termino tu ronda de trabajo. Emite AHORA el REPORT de ronda como un "
    "unico objeto JSON con EXACTAMENTE estas 5 claves: status, summary, "
    "evidence, nextSteps, blocker.\n"
    "- status: 'continue' (queda trabajo: nextSteps NO vacio, blocker vacio), "
    "'complete' (objetivo cumplido: evidence NO vacio, nextSteps vacio, "
    "blocker vacio) o 'blocked' (no se puede seguir: blocker NO vacio).\n"
    "- summary: que hiciste en ESTA ronda, 1-4 frases.\n"
    "- evidence: lista de hechos COMPROBABLES en el workspace (rutas creadas, "
    "comandos corridos con su salida, tests que pasaron). Sin evidencia no "
    "hay 'complete'.\n"
    "- nextSteps: lista de pasos concretos para el proximo worker (vacia si "
    "complete).\n"
    "- blocker: que impide seguir (vacio salvo blocked).\n"
    "Strings sin espacios al borde, ninguno vacio salvo blocker. Solo el "
    "JSON, sin texto alrededor.")


def pedir_report_por_chat(completar, system: str, hist_ciclo: list,
                          texto_final: str, perfil: dict,
                          error_previo: str = "") -> str:
    """Pide el report al MISMO worker (su contexto de la ronda: objetivo +
    RESULTADO de sus tools + su respuesta final) por chat completions con
    response_format estricto. Devuelve la salida cruda (parsear_report la
    valida) o lanza ReportInvalido si la peticion fallo."""
    contexto = "\n\n".join(hist_ciclo)
    if texto_final:
        contexto += "\n\nRESPUESTA FINAL DEL WORKER:\n" + texto_final
    mensajes = [{"role": "system", "content": system}] if system else []
    mensajes.append({"role": "user", "content": contexto})
    pedido = _PROMPT_REPORT
    if error_previo:
        pedido = (f"Tu report anterior fue INVALIDO: {error_previo}. "
                  f"Corrigelo.\n\n" + pedido)
    mensajes.append({"role": "user", "content": pedido})
    # SIN pensamiento: el report resume lo que YA paso, no decide nada, y el
    # razonamiento se comia el presupuesto (medido 2026-08-24 contra el 27B
    # en :8080: con enable_thinking el report costaba 1.605 tokens / 33 s y
    # en la corrida real llego VACIO por finish=length; sin pensar, 101
    # tokens / 3,7 s y valido). Familias que no leen enable_thinking ignoran
    # la clave. max_tokens con piso 4096 por si la familia piensa igual.
    kw_plantilla = dict((perfil or {}).get("kwargs_plantilla") or {})
    kw_plantilla["enable_thinking"] = False
    kwargs = {
        "url": (perfil or {}).get("url", ""),
        "max_tokens": max(int((perfil or {}).get("max_tokens", 4096) or 4096),
                          4096),
        "razonador": False,
        "via": "horizonte_report",
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "report_ronda",
                                            "schema": SCHEMA_REPORT,
                                            "strict": True}},
        "kwargs_plantilla": kw_plantilla,
    }
    resp = completar(mensajes, tools=None, **kwargs)
    if getattr(resp, "error", ""):
        raise ReportInvalido(f"el backend no devolvio el report: {resp.error}")
    texto = getattr(resp, "texto", "") or ""
    if not texto.strip():
        # Distinguir "no dijo nada" de "se le acabo el presupuesto pensando":
        # son diagnosticos opuestos y el error se cita al worker.
        fin = getattr(resp, "finish_reason", "") or "?"
        raise ReportInvalido(
            f"salida vacia (finish={fin}, max_tokens={kwargs['max_tokens']}): "
            f"no hay report")
    return texto


def _obtener_report(pedir_report, hist_ciclo: list, nat: dict, ronda: int,
                    racha: int, blocker_previo: str, handoff_max: int,
                    print_fn) -> dict:
    """Pide, parsea (1a validacion), fusiona blocked y consume (2a validacion
    + cota). Un fallo se cita al worker y se vuelve a pedir UNA vez; al
    segundo fallo la ronda queda sin report, con el motivo (jamas se inventa).
    Devuelve {report, handoff, racha, blocker_anotado, error, intentos}."""
    error = ""
    for intento in (1, 2):
        try:
            crudo = pedir_report(hist_ciclo, nat.get("texto") or "", error)
            report = parsear_report(crudo)                   # 1a validacion
            report, racha_n, anotado = fusionar_blocked(report, racha,
                                                        blocker_previo)
            handoff = consumir_report(report, handoff_max)   # 2a validacion
            return {"report": report, "handoff": handoff, "racha": racha_n,
                    "blocker_anotado": anotado, "error": "",
                    "intentos": intento}
        except (ReportInvalido, HandoffDemasiadoGrande) as exc:
            error = str(exc)
            if intento == 1:
                print_fn(f"[warn_cl]horizonte: report de la ronda {ronda} "
                         f"invalido ({error[:200]}); lo vuelvo a pedir "
                         f"citando el error[/warn_cl]")
        except Exception as exc:                # fallo del pedidor (red, bug)
            error = f"{type(exc).__name__}: {exc}"
            break
    print_fn(f"[warn_cl]horizonte: ronda {ronda} SIN report valido tras "
             f"{'2 intentos' if error else '1 intento'}: {error[:300]}"
             f"[/warn_cl]")
    return {"report": None, "handoff": "", "racha": 0, "blocker_anotado": "",
            "error": error, "intentos": 2}


# ── Estado vivo para la puerta /horizonte estado ─────────────────────────────
# Foto de la ULTIMA corrida (o la activa): la lee _slash_horizonte. Vive en
# memoria del proceso; el estado durable completo esta en estado_tarea.
_ULTIMA: dict = {}


def estado_actual() -> dict:
    """Copia de la foto viva (vacia si no corrio ningun horizonte)."""
    return dict(_ULTIMA)


def _foto(**campos) -> None:
    _ULTIMA.update(campos)


def _motivo_relevo(nat: dict) -> str:
    """Clasifica POR QUE el ciclo no cerro completo, con las senales que
    bucle_nativo ya emite (finish + prefijo del texto): sin tocar loop.py."""
    texto = nat.get("texto") or ""
    if texto.startswith(_STUCK_PREFIX):
        return "estancamiento"
    finish = nat.get("finish", "")
    if finish == "length":
        return "truncado"
    if finish == "stop":
        return "stop_con_faltantes"
    return "presupuesto_agotado"


def ciclos_con_contrato(task, system, completar, schemas, args_legacy,
                        mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                        history, trace, print_fn, max_turns,
                        criterios: list, task_id: str, estado: dict,
                        max_ciclos: int = 2, bucle=None, pedir_report=None,
                        handoff_max: int = None) -> dict:
    """Corre hasta ``max_ciclos`` rondas de ``bucle`` (default: bucle_nativo),
    sellando cada una con GoalContract sobre los ``criterios`` CONGELADOS y
    pidiendole a cada worker su REPORT de ronda (contrato ralph).

    Contrato de salida: el dict de bucle_nativo + {"ciclos": n,
    "contrato_ok": bool|None, "task_id": task_id, "report": dict|None,
    "cierre_worker": str}. contrato_ok=None significa "sin criterios
    verificables": ahi gobierna el report del worker (continue -> otra ronda,
    hasta max_ciclos); sin report posible, 1 solo ciclo, identico a antes.

    ``history`` y ``trace`` son las MISMAS listas que maneja cli.py: el ciclo 1
    corre sobre ellas tal cual (identico a hoy); los ciclos >=2 corren sobre un
    history fresco [objetivo, prompt_de_ronda] y sus RESULTADO nuevos se
    extienden al history real para que el post-procesado (E8, skills,
    adjuntos) los vea.

    ``pedir_report(hist_ciclo, texto_final, error_previo) -> str`` es
    inyectable; por defecto se arma sobre ``completar`` (None = sin report).
    """
    from cognia.agent import bitacora, estado_tarea

    if bucle is None:
        from cognia.agent.loop import bucle_nativo as bucle
    if pedir_report is None and completar is not None:
        def pedir_report(hist_ciclo, texto_final, error_previo,
                         _c=completar, _s=system, _p=perfil):
            return pedir_report_por_chat(_c, _s, hist_ciclo, texto_final,
                                         _p, error_previo)
    if handoff_max is None:
        handoff_max = handoff_max_env()

    try:
        from cognia.agents.goal_contract import GoalContract
    except Exception:
        GoalContract = None

    n = 0
    prev_satisfied = None
    motivo = ""
    contrato_ok = None
    nat: dict = {"texto": "", "pasos": 0, "ok": False, "tokens": 0, "finish": ""}
    pasos_total = 0
    tokens_total = 0
    report = None                 # ultimo report valido (o None)
    handoff = ""                  # su serializacion con cota
    racha_blocked = 0
    blocker_previo = ""
    blocker_anotado = ""
    report_error = ""
    max_ciclos = max(1, max_ciclos)
    _ULTIMA.clear()
    _foto(task_id=task_id, tarea=(task or "")[:200], activa=True, rondas=0,
          max_rondas=max_ciclos, handoff_max=handoff_max,
          criterios=len(criterios or []), report=None, report_error="",
          cierre="", contrato_ok=None)

    while n < max_ciclos:
        n += 1
        if n == 1:
            hist_ciclo, trace_ciclo = history, trace
            idx0 = len(trace)
        else:
            faltan = estado.get("faltan", [])
            hist_ciclo = [history[0], prompt_de_ronda(
                n, max_ciclos,
                estado_tarea.resumen_para_prompt(estado, faltan) if criterios
                else "",
                handoff, blocker_anotado=blocker_anotado,
                contrato_faltan=len(faltan) if criterios else 0,
                report_previo_status=(report or {}).get("status", ""))]
            # Trace FRESCO por ciclo: bucle_nativo corta por no-progreso
            # mirando trace[-3:] — con el trace compartido, los fallos del
            # ciclo ANTERIOR mataban al ciclo fresco tras un solo paso,
            # anulando justamente el reintento (revision 2026-08-09).
            trace_ciclo = []
            idx0 = 0
            print_fn(f"[detail]horizonte: ronda {n}/{max_ciclos} con worker "
                     f"fresco (motivo: {motivo}; faltan "
                     f"{len(estado.get('faltan', []))})[/detail]")
        nat = bucle(task, system, completar, schemas, args_legacy,
                    mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                    hist_ciclo, trace_ciclo, print_fn, max_turns)
        pasos_total += int(nat.get("pasos") or 0)
        tokens_total += int(nat.get("tokens") or 0)
        if n >= 2:
            # Lo que el bucle apendeo a las listas frescas, de vuelta a las
            # reales (history posiciones 2+: 0=objetivo, 1=delta) para el
            # post-procesado de cli.py (E8, skills, skill_capture).
            history.extend(hist_ciclo[2:])
            trace.extend(trace_ciclo)

        infra_caida = (nat.get("texto") or "").startswith(_INFRA_PREFIX)
        # REPORT de ronda (ralph): se pide al worker sobre su propio contexto.
        # Con la infra caida no se pide (fallaria igual).
        if pedir_report is not None and not infra_caida:
            r = _obtener_report(pedir_report, hist_ciclo, nat, n,
                                racha_blocked, blocker_previo, handoff_max,
                                print_fn)
            report, handoff, report_error = r["report"], r["handoff"], r["error"]
            racha_blocked, blocker_anotado = r["racha"], r["blocker_anotado"]
            blocker_previo = (blocker_anotado
                              or (report or {}).get("blocker", ""))
            if report is not None:
                print_fn(f"[detail]horizonte: report ronda {n}: "
                         f"{report['status']} — {report['summary'][:160]}"
                         f"[/detail]")
        else:
            report, handoff, report_error = None, "", (
                "infra caida" if infra_caida else "sin pedidor de report")
        _foto(rondas=n, report=report, report_error=report_error)

        # Sin criterios verificables no hay sello posible: gobierna el report
        # (continue -> otra ronda); sin report, 1 ciclo como siempre.
        # (Mejor ningun contrato que uno inventado — docstring del derivador.)
        if not criterios or GoalContract is None:
            contrato_ok = None
            estado_tarea.registrar_ciclo(estado, n, nat, None,
                                         trace_ciclo[idx0:], motivo,
                                         report=report,
                                         report_error=report_error)
            bitacora.anotar({"tipo": "ciclo_fin", "ciclo": n, "contrato": "",
                             "finish": nat.get("finish", ""),
                             "motivo_relevo": motivo,
                             "report_status": (report or {}).get("status", ""),
                             "report_error": report_error})
            if (report or {}).get("status") != "continue" or n >= max_ciclos:
                break
            motivo = "worker_continue"
            continue

        st = GoalContract.from_spec(task[:120], criterios).check()
        estado_tarea.registrar_ciclo(estado, n, nat, st, trace_ciclo[idx0:],
                                     motivo, report=report,
                                     report_error=report_error)
        bitacora.anotar({
            "tipo": "ciclo_fin", "ciclo": n,
            "contrato": f"{st.satisfied_count}/{st.total}",
            "faltan": [r.criterion.description for r in st.results
                       if not r.satisfied][:6],
            "finish": nat.get("finish", ""),
            "motivo_relevo": motivo,
            "report_status": (report or {}).get("status", ""),
            "report_error": report_error,
        })

        if st.complete:
            contrato_ok = True
            break
        contrato_ok = False
        if infra_caida:
            break                     # infra caida: relanzar fallaria igual
        if (report or {}).get("status") == "blocked":
            # Bloqueo ACEPTADO (persistio BLOCKED_RONDAS_MIN rondas): seguir
            # seria pedirle al worker que se estrelle contra lo mismo.
            print_fn(f"[warn_cl]horizonte: bloqueo aceptado tras "
                     f"{racha_blocked} rondas con el mismo blocker; corto."
                     f"[/warn_cl]")
            break
        if n >= max_ciclos:
            break                     # techo de ciclos
        if prev_satisfied is not None and st.satisfied_count <= prev_satisfied:
            # Progreso monotono: el relevo anterior no subio el contrato ->
            # seguir seria churn (las rondas sin avance RESTAN, memoria repo).
            print_fn("[warn_cl]horizonte: sin progreso del contrato entre "
                     f"ciclos ({st.satisfied_count}/{st.total}); corto "
                     "honesto.[/warn_cl]")
            break
        prev_satisfied = st.satisfied_count
        motivo = _motivo_relevo(nat)

    cierre = texto_cierre(report, n, report_error)
    if contrato_ok is True:
        cierre += (f"\n(el contrato ejecutable del harness SI verifico los "
                   f"{len(criterios)} criterios)")
    elif contrato_ok is False:
        cierre += ("\n(el contrato ejecutable del harness NO se cumplio: "
                   f"faltan {len(estado.get('faltan', []))})")
    print_fn(f"[info_dim]horizonte: {cierre}[/info_dim]")
    try:
        estado["cierre_worker"] = cierre
        estado_tarea.guardar(estado)
    except Exception as exc:
        print_fn(f"[warn_cl]horizonte: no pude persistir el cierre "
                 f"({type(exc).__name__}: {exc})[/warn_cl]")
    _foto(activa=False, cierre=cierre, contrato_ok=contrato_ok, rondas=n,
          report=report, report_error=report_error)

    salida = dict(nat)
    salida["pasos"] = pasos_total
    salida["tokens"] = tokens_total
    salida.update({"ciclos": n, "contrato_ok": contrato_ok,
                   "task_id": task_id, "report": report,
                   "cierre_worker": cierre})
    # Sello de traza (COGNIA_TRAZAS=1): las 3 salidas del while (contrato
    # completo / incompleto / sin criterios) convergen aca con el contrato_ok
    # final ya fijado. Se sella por el id que publico el hook del loop
    # (ctx['_traza_task_id']) o, si no esta, por el task_id del horizonte
    # (comparten id via bitacora.task_id_activo). Best-effort: un fallo del
    # sellador jamas toca la salida.
    try:
        from cognia.agent import traza_chatml as _trz
        if _trz.habilitada():
            _trz.sellar((ctx or {}).get("_traza_task_id") or task_id,
                        {"contrato_ok": contrato_ok, "horizonte": True})
    except Exception:
        pass
    return salida
