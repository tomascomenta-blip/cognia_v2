"""
cognia/agent/estado_tarea.py
============================
Estado DURABLE por tarea del agente (modo horizonte, COGNIA_HORIZONTE=1).

POR QUE EXISTE: el bucle nativo guarda todo su progreso en el KV del server y
en listas en memoria; si la tarea es larga (varios ciclos de contexto fresco)
o el proceso muere, no queda NADA verificable de que se hizo. Este modulo
persiste, por tarea, un estado chico en disco:

    ~/.cognia/data/tareas/<task_id>/estado.json   (override: COGNIA_TAREAS_DIR)

Regla dura (separacion PRO-LONG traza-objetiva/modelo): NADA entra como hito
'ok' sin veredicto de GoalContract — evidencia de filesystem/comando, jamas el
auto-reporte del modelo. El texto del modelo solo viaja como 'resumen'
informativo y nunca decide.

El override del directorio se lee a CALL-time (mismo patron que
COGNIA_TASKS_FILE en tasks_board.py) para que los tests aislen con tmp_path.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# Acciones del trace que tocan archivos: el primer campo del args legacy es la
# ruta (convencion 'path | resto' de tool_schemas.args_legacy).
_ACCIONES_ESCRITURA = ("escribir_archivo", "editar_archivo", "apendar_archivo")

_VEREDICTOS = ("completa", "incompleta", "abortada", "retomada")

# Un estado 'en_curso' cuyo estado.json no se toca hace mas de esto se
# considera HUERFANO (proceso muerto a mitad de tarea): es retomable — el
# escenario para el que existe el estado durable (hallazgo revision 2026-08-09).
_HUERFANA_S = 15 * 60


def dir_tareas() -> Path:
    """Raiz de los estados; COGNIA_TAREAS_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_TAREAS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "data" / "tareas"


def _ruta_estado(task_id: str) -> Path:
    return dir_tareas() / task_id / "estado.json"


def nuevo(task_id: str, tarea: str, criterios: list) -> dict:
    """Crea y persiste el estado inicial. ``criterios`` son los specs
    CONGELADOS de derive_criteria_from_task sobre la letra ORIGINAL: no se
    re-derivan nunca (el re-derivar sobre texto contaminado fue el bug A6)."""
    estado = {
        "version": 1,
        "task_id": task_id,
        # Texto COMPLETO de la tarea: es el ancla anti-deriva, nunca truncado.
        "tarea": tarea,
        "status": "en_curso",
        "criterios": [dict(c) for c in (criterios or [])],
        "hitos": [],
        "faltan": [c.get("description", "") for c in (criterios or [])],
        "archivos_tocados": [],
        "ultimo_error": "",
        "ciclos": [],
        "ts_inicio": datetime.now().isoformat(timespec="seconds"),
        "ts_fin": None,
    }
    guardar(estado)
    return estado


def guardar(estado: dict) -> None:
    """Escritura ATOMICA (tmp + os.replace): un crash a mitad de escritura
    deja el estado anterior legible, nunca un JSON truncado. No lanza: un
    disco roto degrada con Degradado al bus (la degradacion silenciosa es el
    modo de fallo historico del repo), y la tarea sigue."""
    try:
        ruta = _ruta_estado(estado["task_id"])
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, ruta)
    except Exception as exc:
        try:
            from cognia.ux import events as _ev
            _ev.emitir(_ev.Degradado(
                donde="estado_tarea.guardar", motivo=f"{type(exc).__name__}: {exc}",
                accion_sugerida="revisar permisos de ~/.cognia/data/tareas"))
        except Exception:
            pass


def cargar(task_id: str) -> dict | None:
    """Estado persistido de esa tarea, o None (ausente/corrupto degrada)."""
    try:
        raw = json.loads(_ruta_estado(task_id).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) and raw.get("task_id") else None
    except (OSError, ValueError):
        return None


def registrar_ciclo(estado: dict, ciclo: int, nat: dict, status,
                    trace_delta: list, motivo_relevo: str = "",
                    report: dict | None = None,
                    report_error: str = "") -> None:
    """Vuelca el resultado de UN ciclo del bucle al estado y persiste.

    - ``status`` es un ContractStatus real: hitos/faltan salen SOLO de sus
      CriterionResult (.satisfied, .criterion.description, .detail).
    - ``trace_delta`` son las entradas del trace de ESTE ciclo (slice por
      indice): de ahi salen archivos tocados y el ultimo error.
    - ``nat`` es el dict que devuelve bucle_nativo (pasos/tokens/finish/texto).
    - ``report`` es el REPORT de ronda del worker (contrato ralph, ya
      validado dos veces por horizonte.py) o None si no lo hubo, con
      ``report_error`` diciendo por que. Informativo como el resumen: el
      worker REPORTA, el contrato decide.
    """
    ya_ok = {h["criterio"] for h in estado["hitos"]}
    for res in getattr(status, "results", []) or []:
        desc = res.criterion.description
        if res.satisfied and desc not in ya_ok:
            estado["hitos"].append({
                "criterio": desc, "ok": True, "ciclo": ciclo,
                "evidencia": (res.detail or "")[:160],
            })
    estado["faltan"] = [res.criterion.description
                       for res in (getattr(status, "results", []) or [])
                       if not res.satisfied]
    for a in trace_delta or []:
        if a.get("action") in _ACCIONES_ESCRITURA and a.get("ok"):
            path = (a.get("args") or "").split("|", 1)[0].strip()
            if path and path not in estado["archivos_tocados"]:
                estado["archivos_tocados"].append(path)
    for a in reversed(trace_delta or []):
        if not a.get("ok"):
            estado["ultimo_error"] = (a.get("result_head") or "")[:160]
            break
    estado["ciclos"].append({
        "n": ciclo,
        "pasos": int(nat.get("pasos") or 0),
        "tokens": int(nat.get("tokens") or 0),
        "finish": nat.get("finish", ""),
        "motivo_relevo": motivo_relevo,
        # Texto del modelo: informativo, JAMAS decide (eso es del contrato).
        "resumen": (nat.get("texto") or "")[:300],
        "report": dict(report) if report else None,
        "report_error": (report_error or "")[:300],
    })
    guardar(estado)


def cerrar(estado: dict, veredicto: str) -> None:
    """Cierra el estado con veredicto final y persiste."""
    estado["status"] = veredicto if veredicto in _VEREDICTOS else "abortada"
    estado["ts_fin"] = datetime.now().isoformat(timespec="seconds")
    guardar(estado)


def resumen_para_prompt(estado: dict, faltan: list, max_chars: int = 1200) -> str:
    """El bloque de CONTINUACION para el ciclo fresco. DETERMINISTA: plantilla
    fija sobre el estado, sin LLM. La tarea original NO se repite aca (viaja
    como history[0], que el bucle fija siempre); esto es solo el delta."""
    n = len(estado.get("ciclos", [])) + 1
    cabeza = (f"CONTINUACION de una tarea en curso (ciclo {n}). "
              "No empieces de cero: la TAREA es la de arriba y parte ya esta "
              "hecha y VERIFICADA.")
    # La COLA (faltantes + instruccion) es lo que gobierna el ciclo: se arma
    # primero y sobrevive SIEMPRE; el detalle de hitos/archivos consume solo
    # el presupuesto restante (un truncado plano decapitaba el SOLO FALTA).
    # Caps elegidos para que cabeza+cola quepan SIEMPRE en max_chars=1200 por
    # construccion (~150 + ~860): la instruccion gobernante y el SOLO FALTA
    # jamas se cortan; solo el detalle del medio cede espacio.
    def _linea(texto: str, tope: int = 100) -> str:
        # Cabeza + COLA: el dato clave de un criterio (el nombre de archivo)
        # vive al FINAL de la ruta; cortar solo por la cola lo perdia.
        if len(texto) <= tope:
            return texto
        mitad = (tope - 3) // 2
        return texto[:mitad] + "..." + texto[-mitad:]

    cola = ["\nSOLO FALTA:"]
    cola.extend(f"- {_linea(f)}" for f in (faltan or [])[:6])
    cola.append(
        "\nCompleta exactamente eso. Si dudas de que ya hiciste algo, usa la "
        "tool tarea_estado o bitacora_buscar en vez de suponer. Si un criterio "
        "faltante es imposible, dilo explicitamente en tu respuesta final.")
    cola_txt = "\n".join(cola)
    resto = max_chars - len(cabeza) - len(cola_txt) - 2
    medio: list = []
    hitos = [h["criterio"] for h in estado.get("hitos", [])]
    if hitos:
        medio.append("\nYA VERIFICADO con evidencia real (NO lo repitas):")
        medio.extend(f"- {_linea(h)}" for h in hitos[:8])
    tocados = estado.get("archivos_tocados", [])
    if tocados:
        medio.append("\nARCHIVOS YA TOCADOS: " + ", ".join(tocados[:10])[:300])
    if estado.get("ultimo_error"):
        medio.append("\nULTIMO ERROR: " + estado["ultimo_error"][:160])
    medio_txt = "\n".join(medio)[:max(0, resto)]
    return "\n".join(p for p in (cabeza, medio_txt, cola_txt) if p)


def render_estado(estado: dict) -> str:
    """Render legible del estado para la tool tarea_estado (y para humanos)."""
    lineas = [f"TAREA ({estado.get('status', '?')}): "
              + (estado.get("tarea") or "")[:200]]
    for h in estado.get("hitos", []):
        lineas.append(f"  [OK] {h['criterio']} -- {h.get('evidencia', '')}"
                      f" (ciclo {h.get('ciclo', '?')})")
    for f in estado.get("faltan", []):
        lineas.append(f"  [--] {f}")
    if estado.get("archivos_tocados"):
        lineas.append("  archivos: " + ", ".join(estado["archivos_tocados"][:10]))
    if estado.get("ultimo_error"):
        lineas.append("  ultimo error: " + estado["ultimo_error"])
    lineas.append(f"  ciclos corridos: {len(estado.get('ciclos', []))}")
    ultimo = (estado.get("ciclos") or [{}])[-1]
    if ultimo.get("report"):
        r = ultimo["report"]
        lineas.append(f"  ultimo report del worker: {r.get('status')} -- "
                      f"{(r.get('summary') or '')[:160]}")
    return "\n".join(lineas)


def ultima_incompleta() -> dict | None:
    """El estado retomable mas reciente (para /hacer retomar), o None.

    Retomable = 'incompleta' (cerro sin cumplir el contrato) o 'en_curso'
    HUERFANA (estado.json sin tocar hace >_HUERFANA_S: el proceso murio a
    mitad de tarea — el crash es justamente el caso para el que existe el
    estado durable). El task_id arranca con YYYYmmdd-HHMMSS asi que el orden
    lexicografico descendente ES el orden temporal."""
    import time as _time
    try:
        dirs = sorted((d for d in dir_tareas().iterdir() if d.is_dir()),
                      key=lambda d: d.name, reverse=True)
    except OSError:
        return None
    for d in dirs:
        est = cargar(d.name)
        if not est:
            continue
        if est.get("status") == "incompleta":
            return est
        if est.get("status") == "en_curso":
            try:
                edad = _time.time() - (d / "estado.json").stat().st_mtime
            except OSError:
                continue
            if edad > _HUERFANA_S:
                return est
    return None


def podar_viejas(max_tareas: int = 20, excluir: str = "") -> None:
    """Retiene las ``max_tareas`` mas recientes; borra el resto. ``excluir``
    protege la tarea ACTIVA aunque quedara fuera del corte (otro proceso con
    el reloj adelantado no debe borrarla bajo sus pies). Nunca lanza."""
    try:
        dirs = sorted((d for d in dir_tareas().iterdir() if d.is_dir()),
                      key=lambda d: d.name, reverse=True)
        for d in dirs[max_tareas:]:
            if excluir and d.name == excluir:
                continue
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def nuevo_task_id(tarea: str) -> str:
    """'YYYYmmdd-HHMMSS-<slug8>' — ordenable por nombre y legible."""
    slug = re.sub(r"[^a-z0-9]+", "-", (tarea or "").lower())[:8].strip("-")
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + (slug or "tarea")
