"""
program_creator.py — Orquestador del módulo de programación hobby de Cognia.

Este es el punto de entrada principal del módulo.
Implementa el loop completo:

  Idea → Generación → Ejecución en sandbox → Evaluación → Almacenamiento

La función principal es run_program_hobby(), que puede ser llamada desde:
  1. El ciclo de sueño de Cognia (sleep())
  2. Un loop idle externo
  3. Manualmente desde la CLI para pruebas

PRINCIPIO DE AISLAMIENTO:
  Este módulo puede LEER conceptos de Cognia (solo lectura) para inspiración,
  pero NUNCA modifica working_memory, episodic_memory, semantic_memory ni knowledge_graph.

  El único "write back" opcional es registrar metadata del programa como
  un evento log externo — nunca como un episodio de aprendizaje.
"""

import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .generator      import generate_program, GeneratedProgram
from .sandbox_runner import run_in_sandbox, ExecutionResult
from .evaluator      import evaluate_program, EvaluationResult
from .storage        import save_program, StoredProgramMeta, format_library_summary, get_program_count

# ── Configuración ──────────────────────────────────────────────────────────────

# Pausa entre generaciones (segundos) para no saturar el LLM
INTER_GENERATION_PAUSE = 2.0

# Número máximo de intentos por sesión de hobby
MAX_ATTEMPTS_PER_SESSION = 3

# Threshold mínimo para guardar (espejo del definido en evaluator.py)
STORE_THRESHOLD = 5.0

# Estadísticas de sesión para monitoreo
_session_stats = {
    "sessions_run":       0,
    "programs_attempted": 0,
    "programs_stored":    0,
    "last_run":           None,
}


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class HobbySessionResult:
    """Resultado de una sesión de programación hobby."""
    attempted:   int
    successful:  int           # Programas que pasaron el evaluador
    stored:      int           # Programas que se guardaron en disco
    programs:    list          # Lista de StoredProgramMeta de los guardados
    duration_sec: float
    timestamp:   str


# ── Lectura de conocimiento (solo lectura) ─────────────────────────────────────

def _get_seed_concepts(cognia_instance=None) -> list[str]:
    """
    Extrae conceptos del grafo de conocimiento de Cognia para inspirar
    los programas generados. SOLO LECTURA — nunca modifica nada.

    Args:
        cognia_instance: Instancia de Cognia (opcional).
                         Si no se pasa, se devuelve lista vacía.

    Returns:
        Lista de strings con nombres de conceptos.
    """
    if cognia_instance is None:
        return []
    try:
        # Leemos desde semantic memory — método list_all() es solo lectura
        concepts = cognia_instance.semantic.list_all()
        # Filtramos conceptos con suficiente confianza y soporte
        good = [
            c["concept"] for c in concepts
            if c.get("confidence", 0) >= 0.5
            and c.get("support", 0) >= 2
            and len(c["concept"]) > 3
        ]
        # Tomamos una muestra aleatoria pequeña para no sobrecargar el prompt
        return random.sample(good, min(5, len(good))) if good else []
    except Exception:
        return []


# ── Loop principal ─────────────────────────────────────────────────────────────

def run_program_hobby(
    cognia_instance=None,
    max_attempts:   int  = MAX_ATTEMPTS_PER_SESSION,
    storage_dir:    Path = None,
    verbose:        bool = True,
    forced_idea:    str  = None,
) -> HobbySessionResult:
    """
    Ejecuta una sesión completa del hobby de programación de Cognia.

    Pipeline por intento:
      1. Leer conceptos semánticos de Cognia (solo lectura, opcional)
      2. Generar idea + código Python via LLM
      3. Ejecutar código en sandbox aislado
      4. Evaluar resultado (puntuación 0–10)
      5. Guardar si supera el threshold

    Args:
        cognia_instance : Instancia de Cognia para leer conceptos (opcional)
        max_attempts    : Máximo de programas a intentar en esta sesión
        storage_dir     : Directorio de almacenamiento (None = default)
        verbose         : Si True, imprime logs detallados

    Returns:
        HobbySessionResult con estadísticas de la sesión.
    """
    start_time = time.time()
    timestamp  = datetime.now().isoformat()

    if verbose:
        print(f"\n🎨 [ProgramCreator] Iniciando sesión de hobby — {timestamp}")
        print(f"   Intentos planificados: {max_attempts}")

    # Leer conceptos para inspiración (solo lectura)
    seed_concepts = _get_seed_concepts(cognia_instance)
    if verbose and seed_concepts:
        print(f"   Conceptos semilla: {seed_concepts}")

    attempted   = 0
    successful  = 0
    stored_list = []

    for attempt in range(1, max_attempts + 1):
        if verbose:
            print(f"\n── Intento {attempt}/{max_attempts} ──────────────────────────")

        # ── Paso 1: Generar programa ───────────────────────────────────
        program: Optional[GeneratedProgram] = generate_program(
            seed_concepts, forced_idea=forced_idea
        )
        attempted += 1
        _session_stats["programs_attempted"] += 1

        if program is None:
            if verbose:
                print("   ⚠️  Generación fallida — saltando intento.")
            if attempt < max_attempts:
                time.sleep(INTER_GENERATION_PAUSE)
            continue

        # ── Paso 2: Ejecutar en sandbox ────────────────────────────────
        exec_result: ExecutionResult = run_in_sandbox(program.code)

        # ── Paso 3: Evaluar ────────────────────────────────────────────
        eval_result: EvaluationResult = evaluate_program(program, exec_result)

        # ── Paso 4: Guardar si merece la pena ──────────────────────────
        if eval_result.should_store:
            successful += 1
            meta: StoredProgramMeta = save_program(program, eval_result, storage_dir)
            stored_list.append(meta)
            _session_stats["programs_stored"] += 1

            if verbose:
                print(f"   ✅ '{program.title}' guardado (score={eval_result.total_score:.1f})")
        else:
            if verbose:
                print(f"   🗑️  '{program.title}' descartado (score={eval_result.total_score:.1f} < {STORE_THRESHOLD})")

        # Pausa entre generaciones
        if attempt < max_attempts:
            time.sleep(INTER_GENERATION_PAUSE)

    # ── Estadísticas de sesión ─────────────────────────────────────────
    duration = round(time.time() - start_time, 1)
    _session_stats["sessions_run"] += 1
    _session_stats["last_run"]      = timestamp

    result = HobbySessionResult(
        attempted=    attempted,
        successful=   successful,
        stored=        len(stored_list),
        programs=      stored_list,
        duration_sec=  duration,
        timestamp=     timestamp,
    )

    if verbose:
        total_stored = get_program_count(storage_dir)
        print(f"\n🎨 Sesión completada en {duration}s")
        print(f"   Intentos: {attempted} | Guardados: {len(stored_list)}")
        print(f"   Total en biblioteca: {total_stored} programas\n")

    return result


# ── Integración con el ciclo idle de Cognia ────────────────────────────────────

def maybe_run_hobby(
    cognia_instance=None,
    idle_seconds:   float = 0.0,
    min_idle:       float = 30.0,
    probability:    float = 0.4,
    storage_dir:    Path  = None,
) -> Optional[HobbySessionResult]:
    """
    Versión probabilística de run_program_hobby() para integración con idle loop.

    Solo corre si:
      - Han pasado al menos `min_idle` segundos de inactividad
      - Con probabilidad `probability`

    Esta función está diseñada para ser llamada desde el ciclo de sueño de Cognia
    junto con la generación de hipótesis, como alternativa creativa.

    Ejemplo de uso en cognia_v3.py sleep():

        from cognia.program_creator.program_creator import maybe_run_hobby
        hobby_result = maybe_run_hobby(cognia_instance=self, idle_seconds=120)

    Args:
        cognia_instance : Instancia de Cognia (opcional, para seed concepts)
        idle_seconds    : Cuántos segundos lleva el sistema sin actividad
        min_idle        : Mínimo de segundos inactivo para activar el hobby
        probability     : Probabilidad de activación cuando se cumple min_idle
        storage_dir     : Directorio de almacenamiento

    Returns:
        HobbySessionResult si se ejecutó, None si no.
    """
    if idle_seconds < min_idle:
        return None

    if random.random() > probability:
        return None

    print("[ProgramCreator] 💤 Sistema idle — activando hobby de programación...")
    return run_program_hobby(
        cognia_instance=cognia_instance,
        max_attempts=1,        # Solo 1 programa por activación idle
        storage_dir=storage_dir,
        verbose=True,
    )


def get_session_stats() -> dict:
    """Devuelve estadísticas acumuladas de todas las sesiones."""
    return dict(_session_stats)


def show_library(storage_dir: Path = None) -> str:
    """Devuelve un resumen de la biblioteca de programas guardados."""
    return format_library_summary(storage_dir)
