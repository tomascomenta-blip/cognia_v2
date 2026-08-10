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

NO toca bucle_nativo ni el while legacy: los envuelve. ``bucle`` es inyectable
para testear el outer loop sin GPU.

LIMITACION CONOCIDA (misma que el epilogo de cli.py, pre-existente): el sello
GoalContract.check() resuelve rutas relativas contra el CWD del proceso. Si el
workspace del agente difiere del cwd, un file_exists relativo puede no verse;
el corte por progreso monotono acota el costo a UN relevo estéril. Alinear
check() con el workspace es trabajo de fase 2, junto con el epilogo.
"""

from __future__ import annotations

import os

# Prefijos del result_text de bucle_nativo que clasifican el corte (contrato
# de loop.py: infra y estancamiento se anuncian en el texto, el resto en
# ``finish``). Si loop.py cambia esos literales, los tests de aca lo cazan.
_INFRA_PREFIX = "(el agente no pudo hablar"
_STUCK_PREFIX = "(interrumpida"

FLAG = "COGNIA_HORIZONTE"
_TECHO_CICLOS = 3


def habilitado() -> bool:
    """Flag leido a CALL-time (patron del repo: los tests lo setean/limpian)."""
    return os.environ.get(FLAG, "").strip() == "1"


def max_ciclos_env() -> int:
    """Override por env COGNIA_HORIZONTE_CICLOS (techo duro 3), o 0 si no hay."""
    try:
        n = int(os.environ.get("COGNIA_HORIZONTE_CICLOS", "") or 0)
    except ValueError:
        n = 0
    return min(n, _TECHO_CICLOS) if n > 0 else 0


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
                        max_ciclos: int = 2, bucle=None) -> dict:
    """Corre hasta ``max_ciclos`` ciclos de ``bucle`` (default: bucle_nativo),
    sellando cada uno con GoalContract sobre los ``criterios`` CONGELADOS.

    Contrato de salida: el dict de bucle_nativo + {"ciclos": n,
    "contrato_ok": bool|None, "task_id": task_id}. contrato_ok=None significa
    "sin criterios verificables" (1 solo ciclo, identico a hoy).

    ``history`` y ``trace`` son las MISMAS listas que maneja cli.py: el ciclo 1
    corre sobre ellas tal cual (identico a hoy); los ciclos >=2 corren sobre un
    history fresco [objetivo, delta] y sus RESULTADO nuevos se extienden al
    history real para que el post-procesado (E8, skills, adjuntos) los vea.
    """
    from cognia.agent import bitacora, estado_tarea

    if bucle is None:
        from cognia.agent.loop import bucle_nativo as bucle

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

    while n < max(1, max_ciclos):
        n += 1
        if n == 1:
            hist_ciclo, trace_ciclo = history, trace
            idx0 = len(trace)
        else:
            hist_ciclo = [history[0],
                          estado_tarea.resumen_para_prompt(
                              estado, estado.get("faltan", []))]
            # Trace FRESCO por ciclo: bucle_nativo corta por no-progreso
            # mirando trace[-3:] — con el trace compartido, los fallos del
            # ciclo ANTERIOR mataban al ciclo fresco tras un solo paso,
            # anulando justamente el reintento (revision 2026-08-09).
            trace_ciclo = []
            idx0 = 0
            print_fn(f"[detail]horizonte: ciclo {n}/{max_ciclos} con contexto "
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

        # Sin criterios verificables no hay sello posible: 1 ciclo, como hoy.
        # (Mejor ningun contrato que uno inventado — docstring del derivador.)
        if not criterios or GoalContract is None:
            contrato_ok = None
            estado_tarea.registrar_ciclo(estado, n, nat, None,
                                         trace_ciclo[idx0:], "")
            break

        st = GoalContract.from_spec(task[:120], criterios).check()
        estado_tarea.registrar_ciclo(estado, n, nat, st, trace_ciclo[idx0:],
                                     motivo)
        bitacora.anotar({
            "tipo": "ciclo_fin", "ciclo": n,
            "contrato": f"{st.satisfied_count}/{st.total}",
            "faltan": [r.criterion.description for r in st.results
                       if not r.satisfied][:6],
            "finish": nat.get("finish", ""),
            "motivo_relevo": motivo,
        })

        if st.complete:
            contrato_ok = True
            break
        contrato_ok = False
        if (nat.get("texto") or "").startswith(_INFRA_PREFIX):
            break                     # infra caida: relanzar fallaria igual
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

    salida = dict(nat)
    salida["pasos"] = pasos_total
    salida["tokens"] = tokens_total
    salida.update({"ciclos": n, "contrato_ok": contrato_ok,
                   "task_id": task_id})
    return salida
