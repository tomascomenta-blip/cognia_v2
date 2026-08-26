"""
goal_contract.py
================
Chimera "verifiable goal contract" + anti-goal-drift component
(whitepaper section 8.3, points 2 and 6).

A goal is expressed as CHECKABLE success criteria and progress is evaluated
with REAL checks (filesystem, command exit code, text presence) -- NOT
self-reports. This is the anti progress-hallucination guarantee: a goal is
only "complete" when every criterion is independently verifiable.

Drift detection is delegated to the existing AnchorTracker (Conversation
Anchor Tracker, Phase 61); we do not reimplement it.

Runnable as:  python -m cognia.agents.goal_contract
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# WHY: tolerate the module being importable even if the anchor tracker (or its
# transitive deps) is unavailable; drift becomes a no-op instead of a crash.
try:
    from cognia.context.anchor_tracker import AnchorTracker
except Exception:  # pragma: no cover - defensive import guard
    AnchorTracker = None  # type: ignore


_COMMAND_TIMEOUT_SECONDS = 30

# P0-3 (ESPEC agente largo 14.1 y 9.5) -- TIMEOUT CONFIGURABLE.
# El 30 s fijo hacia inejecutable como criterio cualquier cosa mas lenta que un
# import, y a la vez dejaba correr criterios de minutos por ciclo. Ahora: el
# default se mueve por env var, y CADA criterio puede traer el suyo en su spec
# ('timeout': N). Sigue habiendo tope duro, por la misma razon que en _shell.
_TIMEOUT_ENV = "COGNIA_CONTRATO_TIMEOUT"
_TIMEOUT_MAX = 600

# Un criterio POR CICLO tiene que costar menos que esto o el overhead del ciclo
# se come el diseno (con un pytest de 40 s la compuerta G5 sube el overhead al
# 31 % [D]). La suite de este repo son 6.909 tests / 12 min: no es un criterio,
# es un cierre. `coste_ms` se MIDE en la primera ejecucion, no se declara.
CRITERIO_BARATO_MS = 5000


def _timeout_default() -> int:
    """Segundos por defecto para command_succeeds. NUNCA lanza."""
    crudo = (os.environ.get(_TIMEOUT_ENV) or "").strip()
    if not crudo:
        return _COMMAND_TIMEOUT_SECONDS
    try:
        return max(1, min(_TIMEOUT_MAX, int(crudo)))
    except ValueError:
        # Un valor basura no puede APAGAR el timeout en silencio: se cae al
        # default declarado. (El aviso lo da /tx estado, que lee esta misma
        # funcion y compara con lo que hay en el entorno.)
        return _COMMAND_TIMEOUT_SECONDS


def timeout_de(spec: dict) -> int:
    """El timeout de ESTE criterio: su 'timeout' si lo trae, si no el default."""
    crudo = (spec or {}).get("timeout")
    if crudo is None:
        return _timeout_default()
    try:
        return max(1, min(_TIMEOUT_MAX, int(crudo)))
    except (TypeError, ValueError):
        return _timeout_default()


def workspace_por_defecto() -> Optional[str]:
    """El workspace del agente, o None si no hay ninguno (y entonces se
    conserva el comportamiento viejo: CWD del proceso).

    Call-time y no constante de import: la campana cambia
    COGNIA_AGENT_WORKSPACE por tarea DENTRO del mismo proceso, y una constante
    fijada al importar deja el contrato midiendo la carpeta de la tarea
    anterior (el mismo bug que ya cazo `dev_tools._root_actual`).
    """
    crudo = (os.environ.get("COGNIA_AGENT_WORKSPACE") or "").strip()
    if crudo and os.path.isdir(crudo):
        return crudo
    try:
        from cognia.agents.workers import dev_tools
        raiz = dev_tools._root_actual()
    except Exception:
        return None
    if raiz and os.path.isdir(str(raiz)):
        return str(raiz)
    return None


def _resolver(path: str, workspace: Optional[str]) -> str:
    """La ruta del criterio resuelta contra el WORKSPACE, no contra el CWD.

    P0-3, bug identificado en el inventario: `GoalContract` resolvia
    'cognia/estado/canal.py' contra el directorio del proceso. El agente
    escribe en su workspace (`COGNIA_AGENT_WORKSPACE`), asi que un criterio
    file_exists daba `missing:` sobre un fichero que SI existia, o --peor-- daba
    `exists:` porque en el CWD del proceso habia otro fichero con ese nombre:
    un PASS sobre un artefacto que la tarea nunca produjo.
    """
    if not path:
        return path
    if not workspace:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(str(workspace), path)


@dataclass
class Criterion:
    kind: str          # one of: file_exists, text_in_file, command_succeeds, text_present
    spec: dict         # parameters for the check (path / substring / command / evidence_key)
    description: str    # human-readable WHY this criterion proves progress


@dataclass
class CriterionResult:
    criterion: Criterion
    satisfied: bool
    detail: str        # evidence string or error text (never raised, always captured)
    # P0-3: lo que costo MEDIDO, no declarado. None = no se llego a ejecutar.
    coste_ms: Optional[int] = None
    # Un criterio que se pasa de timeout NO es un FAIL: es un flaky del
    # instrumento (ESPEC 9.5, C2) y no puede disparar un rollback. Se separa
    # del `satisfied=False` normal porque piden decisiones opuestas.
    timeout: bool = False
    # HEREDADO: no se ejecuto en ESTA pasada; vale el veredicto de la anterior
    # (ESPEC 9.5: "si nada cambio, el resultado anterior vale por construccion:
    # mismos bytes -> mismo exit"). Se marca para que la evidencia no mienta
    # sobre CUANDO se midio.
    heredado: bool = False


@dataclass
class ContractStatus:
    goal: str
    satisfied_count: int
    total: int
    complete: bool
    results: list
    drift: Optional[float] = None
    # Cuantos criterios de `results` vienen heredados de una pasada anterior.
    # `complete` EXIGE que sea 0: afirmar "objetivo cumplido" habiendo
    # ejecutado la mitad de los criterios es capitalizar una victoria que nadie
    # midio en este momento.
    heredados: int = 0


# --- individual real checks -------------------------------------------------
# WHY: each check returns (satisfied, detail) and NEVER raises. A broken check
# must downgrade the criterion to unsatisfied with an explanatory detail so the
# contract can never hallucinate completion from an exception.

def _check_file_exists(spec: dict, workspace: Optional[str] = None) -> tuple:
    path = _resolver(spec.get("path", ""), workspace)
    try:
        ok = os.path.exists(path)
        return ok, ("exists: " + path) if ok else ("missing: " + path)
    except Exception as exc:  # pragma: no cover - defensive
        return False, "error: " + repr(exc)


def _check_text_in_file(spec: dict, workspace: Optional[str] = None) -> tuple:
    path = _resolver(spec.get("path", ""), workspace)
    substring = spec.get("substring", "")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            contents = handle.read()
    except Exception as exc:
        return False, "error reading " + path + ": " + repr(exc)
    if substring in contents:
        return True, "found '" + substring + "' in " + path
    return False, "absent '" + substring + "' in " + path


def _check_command_succeeds(spec: dict, workspace: Optional[str] = None) -> tuple:
    # WHY: evidence must be RUNNABLE, not claimed. A zero exit code from a real
    # subprocess is the strongest non-self-report signal of progress.
    #
    # P0-3: cwd = WORKSPACE. Un 'python -m pytest tests/foo.py' lanzado desde el
    # CWD del proceso corre los tests de OTRO arbol; el criterio pasaba (o
    # fallaba) por un repo que la tarea nunca toco. Y el timeout ya no es la
    # constante de 30 s: sale de `timeout_de(spec)`.
    command = spec.get("command", "")
    limite = timeout_de(spec)
    cwd = str(workspace) if workspace and os.path.isdir(str(workspace)) else None
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=limite,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        # El prefijo 'timeout' lo lee `_es_timeout` para NO contarlo como FAIL:
        # un instrumento que no llega a tiempo no es evidencia de nada.
        return False, "timeout after " + str(limite) + "s: " + str(command)
    except Exception as exc:
        return False, "error: " + repr(exc)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    snippet = tail[-1] if tail else ""
    if proc.returncode == 0:
        return True, "rc=0 " + snippet
    return False, "rc=" + str(proc.returncode) + " " + snippet


def _check_text_present(spec: dict, evidence: Optional[dict]) -> tuple:
    # WHY: when evidence is supplied directly (e.g. captured agent output), we
    # still verify a substring is literally present rather than trusting a flag.
    substring = spec.get("substring", "")
    key = spec.get("evidence_key", "")
    blob = ""
    if evidence is not None:
        blob = str(evidence.get(key, "")) if key else ""
        if not key:
            blob = str(evidence.get("text", ""))
    if substring and substring in blob:
        return True, "found '" + substring + "' in evidence['" + (key or "text") + "']"
    return False, "absent '" + substring + "' in evidence['" + (key or "text") + "']"


# Punto de extension: para anadir un tipo de criterio se registra aqui una
# funcion (spec, evidence, workspace) -> (ok, detalle). Nada mas.
_CHECKS = {
    "file_exists": lambda spec, evidence, ws=None: _check_file_exists(spec, ws),
    "text_in_file": lambda spec, evidence, ws=None: _check_text_in_file(spec, ws),
    "command_succeeds": lambda spec, evidence, ws=None: _check_command_succeeds(spec, ws),
    "text_present": lambda spec, evidence, ws=None: _check_text_present(spec, evidence),
}


def _es_timeout(detail: str) -> bool:
    return str(detail or "").startswith("timeout after ")


class GoalContract:
    """A goal bound to verifiable criteria, with anchor-based drift detection."""

    def __init__(self, goal: str, criteria: list, session_id: str = "default",
                 workspace: Optional[str] = None) -> None:
        self.goal = goal
        self.criteria = list(criteria)
        self.session_id = session_id
        # P0-3: contra QUE se resuelven las rutas y desde donde se lanzan los
        # comandos. None = comportamiento viejo (CWD del proceso), para no
        # romper a los llamadores actuales. `workspace_por_defecto()` es lo que
        # usa el loop del agente.
        self.workspace = str(workspace) if workspace else None
        # coste_ms MEDIDO por criterio, indexado por su posicion. Se mide en la
        # PRIMERA ejecucion y no se vuelve a medir: el ruido de las siguientes
        # (cache de disco caliente) haria parecer barato lo que no lo es.
        self.coste_ms = {}
        # El ULTIMO CriterionResult por posicion. Es lo que se hereda cuando un
        # criterio caro se salta: sin esto, el criterio desaparecia del recuento
        # y `satisfied_count` BAJABA solo por haberlo saltado. Medido: un
        # contrato con un criterio de 118 ms que falla y otro de 6063 ms que
        # pasa daba 1/2 en el ciclo 1 y 0/1 en el ciclo 2, G5 leia "progreso
        # 1 -> 0" y reportaba un RETROCESO que nunca ocurrio -- y como
        # `salud['progreso']` solo se actualiza en las salidas HECHO/ANCHO, se
        # quedaba clavado y el agente dejaba de resetear PARA SIEMPRE.
        self.ultimo = {}
        # WHY: tolerate missing AnchorTracker dep -> drift simply unavailable.
        self._tracker = None
        if AnchorTracker is not None:
            try:
                self._tracker = AnchorTracker()
                self._tracker.set_anchor(session_id, goal)
            except Exception:
                self._tracker = None

    @classmethod
    def from_spec(cls, goal: str, specs: list, session_id: str = "default",
                  workspace: Optional[str] = None) -> "GoalContract":
        criteria = []
        for raw in specs:
            kind = raw.get("kind", "")
            description = raw.get("description", kind)
            # Build the spec dict from the flat convenience keys.
            spec = {
                k: v for k, v in raw.items()
                if k not in ("kind", "description")
            }
            criteria.append(Criterion(kind=kind, spec=spec, description=description))
        return cls(goal, criteria, session_id=session_id, workspace=workspace)

    def check(self, evidence: Optional[dict] = None, current_query: Optional[str] = None,
              solo_baratos: bool = False) -> ContractStatus:
        """Corre los criterios y devuelve el estado.

        `solo_baratos=True` (P0-3, regla del criterio barato de la ESPEC 9.5):
        salta los criterios cuyo coste MEDIDO supera `CRITERIO_BARATO_MS`. Es
        lo que se corre POR CICLO; el cierre corre `check()` entero. Un criterio
        que nunca se midio NO se salta: se ejecuta una vez, precisamente para
        conocer su coste. Un check saltado NO desaparece del recuento: hereda
        el veredicto de la ultima vez que SI se ejecuto (ESPEC 9.5, "mismos
        bytes -> mismo exit"), marcado como heredado en su `detail`. Y
        `complete` exige que no haya ni uno heredado: cero criterios saltados
        es la condicion para poder decir "objetivo cumplido".
        """
        results = []
        satisfied_count = 0
        total = 0
        heredados = 0
        for idx, criterion in enumerate(self.criteria):
            checker = _CHECKS.get(criterion.kind)
            if checker is None:
                results.append(CriterionResult(criterion, False, "unknown kind: " + str(criterion.kind)))
                total += 1
                continue
            previo = self.coste_ms.get(idx)
            if solo_baratos and previo is not None and previo > CRITERIO_BARATO_MS:
                # No se ejecuta, pero SI cuenta: se arrastra el ultimo veredicto
                # medido. Tirarlo hacia que `satisfied_count` bajase solo por
                # haber saltado el criterio, y G5 leia ese descenso como
                # RETROCESO (= deriva) y cerraba el reset para siempre.
                ult = self.ultimo.get(idx)
                heredado_ok = bool(ult.satisfied) if ult is not None else False
                cuando = "" if ult is None else " el veredicto anterior fue %s" % (
                    "PASS" if heredado_ok else "FAIL")
                results.append(CriterionResult(
                    criterion, heredado_ok,
                    "HEREDADO, no reejecutado en esta pasada (caro: %d ms > "
                    "%d ms; corre en el cierre).%s"
                    % (previo, CRITERIO_BARATO_MS, cuando),
                    coste_ms=previo,
                    timeout=bool(getattr(ult, "timeout", False)),
                    heredado=True))
                total += 1
                heredados += 1
                if heredado_ok:
                    satisfied_count += 1
                continue
            t0 = time.perf_counter()
            try:
                ok, detail = checker(criterion.spec, evidence, self.workspace)
            except Exception as exc:  # WHY: never let one bad criterion abort the whole contract.
                ok, detail = False, "error: " + repr(exc)
            gastado = int((time.perf_counter() - t0) * 1000)
            if previo is None:
                self.coste_ms[idx] = gastado      # se mide UNA vez, la primera
            total += 1
            if ok:
                satisfied_count += 1
            res = CriterionResult(criterion, bool(ok), detail,
                                  coste_ms=self.coste_ms.get(idx, gastado),
                                  timeout=_es_timeout(detail))
            results.append(res)
            self.ultimo[idx] = res

        # `heredados == 0` es parte de la condicion: `complete` significa "los
        # criterios pasan", no "los que me dio tiempo a correr pasan".
        complete = satisfied_count == total and total > 0 and heredados == 0

        drift = None
        if current_query is not None and self._tracker is not None:
            try:
                drift = float(self._tracker.check_drift(self.session_id, current_query))
            except Exception:
                drift = None

        return ContractStatus(
            goal=self.goal,
            satisfied_count=satisfied_count,
            total=total,
            complete=complete,
            results=results,
            drift=drift,
            heredados=heredados,
        )

    def record_turn(self) -> None:
        # WHY: AnchorTracker only arms drift checks after REMIND_AFTER_TURNS turns;
        # expose the counter so callers can advance the session honestly.
        if self._tracker is not None:
            try:
                self._tracker.record_turn(self.session_id)
            except Exception:
                pass

    def reanchor_hint(self, current_query: str) -> str:
        # WHY: re-anchoring against drift -- delegate to the existing tracker.
        if self._tracker is None:
            return ""
        try:
            return self._tracker.get_anchor_hint(self.session_id, current_query)
        except Exception:
            return ""


# --- derivación mecánica de criterios desde la tarea -------------------------
# WHY: para que el loop /hacer pueda armar un contrato SIN pedirle criterios al
# usuario ni gastar una llamada LLM. Conservador a propósito: solo criterios
# NECESARIOS obvios (archivo mencionado -> file_exists; pedido de tests con una
# ruta de test -> command_succeeds pytest). Puede devolver [] — mejor ningún
# contrato que uno inventado que bloquee 'responder' con falsos negativos.

import re as _re

# WHY el prefijo de unidad opcional y el ~: las tareas reales traen rutas
# absolutas de Windows (C:\..., TOMANQ~1) ademas de relativas.
_TASK_FILE_RX = _re.compile(
    r"((?:[A-Za-z]:[/\\])?[\w.~/\\-]+\.(?:py|md|txt|json|html|css|js|yaml|yml|csv))\b")
_TASK_TEST_RX = _re.compile(r"\b(test|tests|pytest|prueba|pruebas)\b",
                            _re.IGNORECASE)
_MAX_DERIVED = 3


def derive_criteria_from_task(task: str, py_exe: Optional[str] = None,
                              raiz: Optional[str] = None) -> list:
    """Specs (para GoalContract.from_spec) derivadas de la letra de la tarea.

    - ruta con pinta de test (test_*.py o bajo tests/) + mención de tests
      -> command_succeeds: pytest sobre esa ruta (oráculo ejecutable real);
    - cualquier otra ruta mencionada -> file_exists (necesario, no suficiente),
      y SOLO si esa ruta no existe ya: un criterio que se cumple antes de
      empezar no verifica nada (ver el comentario de abajo);
    - tope _MAX_DERIVED criterios, dedupe por ruta.

    `raiz` es el workspace contra el que se comprueba la existencia; por
    defecto, el directorio de trabajo. Se deriva al ARRANCAR la tarea, así que
    lo que hay en disco en ese momento es el estado "antes".
    """
    # Saneo harmony (A6, causa raiz medida 2026-08-09): cuando la letra llega
    # contaminada con tokens de canal de un razonador (<|channel|>analysis...,
    # <|end|>, bloques <think>), el derivador veia "keywords" que no son de la
    # tarea y armaba criterios basura (evidencia baseline de la obra A6, la
    # misma que enterro la SEGUNDA PASADA). Se limpia SIEMPRE, sin flag: sobre
    # una tarea limpia es un no-op y el test de no-regresion lo cristaliza.
    # Los bloques <think> se borran CON su contenido: el razonamiento filtrado
    # no es la letra de la tarea y sus keywords ('tests', rutas hipoteticas)
    # derivaban criterios que nadie pidio (hallazgo de la revision 2026-08-09:
    # borrar solo las etiquetas dejaba el veneno adentro). Un </think> huerfano
    # (bloque truncado) se limpia como etiqueta suelta.
    task = _re.sub(r"<think>.*?</think>", " ", task or "", flags=_re.DOTALL)
    task = _re.sub(r"<\|[^|>]{1,40}\|>", " ", task)
    task = _re.sub(r"</?think>", " ", task)
    specs = []
    seen = set()
    # WHY quitar las rutas antes de buscar intencion de tests: la palabra
    # 'tests' DENTRO de una ruta (tests/test_foo.py) no es un pedido de
    # correrlos ("lee tests/test_foo.py y explicalo" no debe armar pytest).
    stripped = _TASK_FILE_RX.sub(" ", task or "")
    wants_tests = bool(_TASK_TEST_RX.search(stripped))
    py = py_exe or sys.executable
    for m in _TASK_FILE_RX.finditer(task or ""):
        path = m.group(1)
        if path in seen or len(specs) >= _MAX_DERIVED:
            continue
        seen.add(path)
        name = os.path.basename(path)
        is_testfile = name.startswith("test_") or "tests" in path.replace("\\", "/").split("/")
        if wants_tests and is_testfile and path.endswith(".py"):
            specs.append({
                "kind": "command_succeeds",
                "command": '"' + py + '" -m pytest ' + path + " -q --no-header",
                "description": "los tests mencionados pasan: " + path,
            })
        else:
            # UN CRITERIO QUE YA SE CUMPLE ANTES DE EMPEZAR NO ES UN CRITERIO
            # (2026-08-26). `file_exists` sobre una ruta que YA esta en disco
            # no discrimina nada: pase lo que pase en la tarea, sale [OK].
            #
            # MEDIDO: se le pidio al agente completar `game/ai.py` (que existia
            # con 80 bytes de basura) mencionando ademas `config.py` y
            # `game/core.py` como contexto. El turno gasto 27,8 minutos, no
            # escribio NI UN BYTE... y el contrato cerro con
            # "SATISFIED: 3/3 / COMPLETE: yes / ✓ Objetivo verificado".
            # Los tres ficheros existian antes de arrancar. El sistema afirmo
            # haber verificado un trabajo que no se hizo, que es peor que no
            # verificar nada.
            #
            # Se descarta en vez de convertirlo en "debe haber cambiado":
            # derivar eso de la letra es frigil ("lee X y explicalo" no pide
            # cambiar X), y callar es honesto donde inventar no lo es. Si con
            # esto no queda ningun criterio, el contrato sale vacio y el turno
            # no puede decir "objetivo verificado" -- que es exactamente lo
            # que debe pasar cuando no hay nada que se pueda comprobar.
            if os.path.exists(os.path.join(raiz, path) if raiz else path):
                logging.getLogger(__name__).debug(
                    "criterio file_exists descartado: %s ya existia antes de "
                    "la tarea, no discrimina", path)
                continue
            specs.append({
                "kind": "file_exists", "path": path,
                "description": "la tarea menciona " + path + " -> debe existir",
            })
    return specs


def format_status(status: ContractStatus) -> str:
    lines = []
    lines.append("GOAL: " + status.goal)
    for res in status.results:
        # [TO] y no [--]: un timeout del instrumento NO es un criterio fallado
        # (ESPEC 9.5). Verlos iguales dispararia rollbacks por lentitud.
        # [==] es el heredado: no se midio AHORA, y verlo como un [OK] recien
        # medido es exactamente la mentira que este subsistema no puede contar.
        if getattr(res, "heredado", False):
            mark = "[==]"
        else:
            mark = "[OK]" if res.satisfied else ("[TO]" if res.timeout else "[--]")
        coste = "" if res.coste_ms is None else ("  (%d ms)" % res.coste_ms)
        lines.append("  " + mark + " " + res.criterion.description + " -- " + res.detail + coste)
    lines.append("SATISFIED: " + str(status.satisfied_count) + "/" + str(status.total))
    if getattr(status, "heredados", 0):
        lines.append("HEREDADOS: " + str(status.heredados)
                     + " criterio(s) NO reejecutados en esta pasada")
    lines.append("COMPLETE: " + ("yes" if status.complete else "no"))
    if status.drift is not None:
        lines.append("DRIFT: " + ("%.3f" % status.drift))
    return "\n".join(lines)


def _demo() -> None:
    # --- Real verifiable contract against THIS repo's Chimera work ---------
    py = sys.executable  # WHY: run the import check under the SAME interpreter.
    contract = GoalContract.from_spec(
        "Build the Chimera HYDRA capstone with band routing",
        [
            {"kind": "file_exists", "path": "cognia/chimera.py",
             "description": "Chimera capstone module exists"},
            {"kind": "file_exists", "path": "cognia/context/band_router.py",
             "description": "Band router module exists"},
            {"kind": "text_in_file", "path": "README.md", "substring": "HYDRA",
             "description": "README documents HYDRA"},
            {"kind": "command_succeeds",
             "command": py + " -c \"import cognia.chimera\"",
             "description": "cognia.chimera imports cleanly"},
        ],
        session_id="chimera-demo",
    )
    status = contract.check()
    print("=== Verifiable goal contract (real repo) ===")
    print(format_status(status))

    # --- Drift demonstration ----------------------------------------------
    print()
    print("=== Anti-goal-drift demo ===")
    drift_contract = GoalContract("refactor shards", [], session_id="drift-demo")
    # WHY: AnchorTracker arms drift only after REMIND_AFTER_TURNS turns.
    for _ in range(6):
        drift_contract.record_turn()
    on_topic = drift_contract.check(current_query="refactor the model shards loader")
    off_topic = drift_contract.check(current_query="write a poem about the ocean")
    print("on-topic  query 'refactor the model shards loader' -> drift="
          + ("%.3f" % on_topic.drift if on_topic.drift is not None else "n/a"))
    print("off-topic query 'write a poem about the ocean'     -> drift="
          + ("%.3f" % off_topic.drift if off_topic.drift is not None else "n/a"))
    hint = drift_contract.reanchor_hint("write a poem about the ocean")
    print("reanchor_hint: " + (hint if hint else "(no hint)"))


if __name__ == "__main__":
    _demo()
