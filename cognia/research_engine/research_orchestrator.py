"""
research_orchestrator.py — Orquestador de investigación autónoma de Cognia.

Coordina el ciclo completo de investigación durante el sueño:

  1. Leer preguntas pendientes del CuriosityEngine
  2. Seleccionar las más importantes (por score)
  3. Investigar cada una con el LLM
  4. Integrar el conocimiento en Cognia
  5. Marcar las preguntas como exploradas
  6. Retornar resumen de la sesión

DISEÑO:
    Este módulo es el único que escribe en curiosity_proposals (via mark_explored).
    Toda escritura de conocimiento va a través de knowledge_integrator.
    Falla de forma silenciosa — nunca rompe el ciclo de sueño principal.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .researcher          import research_question, ResearchResult
from .knowledge_integrator import integrate_research, get_research_log, IntegrationResult

# ── Configuración ──────────────────────────────────────────────────────────────

# Máximo de preguntas investigadas por ciclo de sueño
MAX_QUESTIONS_PER_SLEEP = 3

# Score mínimo para que una pregunta valga la pena investigar
MIN_SCORE_TO_RESEARCH = 0.40

# Pausa entre investigaciones (no saturar Ollama)
INTER_RESEARCH_PAUSE_SEC = 1.5


# ── Dataclass de sesión ────────────────────────────────────────────────────────

@dataclass
class ResearchSessionResult:
    """Resultado completo de una sesión de investigación durante el sueño."""
    questions_available:  int
    questions_attempted:  int
    questions_successful: int
    triples_added_total:  int
    concepts_touched_total: int
    duration_sec:         float
    timestamp:            str
    summaries:            list = field(default_factory=list)  # Resúmenes de cada pregunta


# ── Selección de preguntas ─────────────────────────────────────────────────────

def _select_questions(pending: list, max_q: int) -> list:
    """
    Selecciona las mejores preguntas para investigar.
    Prioriza:
      1. Contradicciones (más urgentes)
      2. Mayor score de curiosidad
      3. Evita investigar la misma pregunta dos veces seguidas
    """
    if not pending:
        return []

    # Dar bonus a contradicciones
    def priority_key(p):
        type_bonus = 0.15 if p.get("type") == "contradiction" else 0.0
        return p.get("score", 0.0) + type_bonus

    sorted_pending = sorted(pending, key=priority_key, reverse=True)
    eligible = [p for p in sorted_pending if p.get("score", 0) >= MIN_SCORE_TO_RESEARCH]

    return eligible[:max_q]


# ── Loop principal ─────────────────────────────────────────────────────────────

def run_research_session(
    cognia_instance,
    db_path:    str,
    max_questions: int = MAX_QUESTIONS_PER_SLEEP,
    verbose:    bool   = True,
) -> ResearchSessionResult:
    """
    Ejecuta una sesión completa de investigación autónoma.

    Requiere que cognia_instance tenga:
      - cognia_instance.curiosity_engine  (para obtener preguntas pendientes)
      - cognia_instance.kg                (para escribir triples)
      - cognia_instance.semantic          (para reforzar conceptos)

    Args:
        cognia_instance : Instancia de Cognia
        db_path         : Path a la base de datos
        max_questions   : Máximo de preguntas a investigar esta sesión
        verbose         : Logs detallados

    Returns:
        ResearchSessionResult con estadísticas de la sesión.
    """
    start_time = time.time()
    timestamp  = datetime.now().isoformat()

    session = ResearchSessionResult(
        questions_available=  0,
        questions_attempted=  0,
        questions_successful= 0,
        triples_added_total=  0,
        concepts_touched_total= 0,
        duration_sec=         0.0,
        timestamp=            timestamp,
    )

    # ── Verificar que el CuriosityEngine esté disponible ──────────────
    if not hasattr(cognia_instance, "curiosity_engine") or \
       cognia_instance.curiosity_engine is None:
        if verbose:
            print("[research] ⚠️  CuriosityEngine no disponible — saltando investigación")
        return session

    # ── Obtener preguntas pendientes ───────────────────────────────────
    try:
        pending = cognia_instance.curiosity_engine.get_pending_proposals()
    except Exception as exc:
        if verbose:
            print(f"[research] ⚠️  Error obteniendo propuestas: {exc}")
        return session

    session.questions_available = len(pending)

    if not pending:
        if verbose:
            print("[research] 💤 No hay preguntas pendientes para investigar")
        return session

    # ── Seleccionar las mejores preguntas ──────────────────────────────
    selected = _select_questions(pending, max_questions)

    if verbose:
        print(f"\n🔬 [ResearchEngine] Iniciando sesión — {len(selected)} preguntas seleccionadas "
              f"de {len(pending)} pendientes")

    # ── Ciclo de investigación ─────────────────────────────────────────
    for i, proposal in enumerate(selected, 1):
        if verbose:
            qtype = proposal.get("type", "?")
            score = proposal.get("score", 0)
            print(f"\n── Pregunta {i}/{len(selected)} [{qtype}] score={score:.2f} ──")
            print(f"   '{proposal.get('question', '')[:80]}'")

        session.questions_attempted += 1

        # Paso 1: Investigar con LLM
        result: Optional[ResearchResult] = research_question(proposal)

        if result is None:
            if verbose:
                print("   ❌ Investigación fallida")
            # Marcamos como explorada igual para no reintentar indefinidamente
            try:
                cognia_instance.curiosity_engine.mark_explored(
                    proposal["id"],
                    outcome="research_failed"
                )
            except Exception:
                pass
            if i < len(selected):
                time.sleep(INTER_RESEARCH_PAUSE_SEC)
            continue

        # Paso 2: Integrar conocimiento en Cognia
        integration: IntegrationResult = integrate_research(
            result=result,
            cognia_instance=cognia_instance,
            db_path=db_path,
        )

        # Paso 3: Marcar pregunta como explorada en CuriosityEngine
        outcome_summary = (
            f"Investigated: {result.answer[:100]}... "
            f"[+{integration.triples_added} KG triples, "
            f"+{integration.concepts_touched} concepts]"
        )
        try:
            cognia_instance.curiosity_engine.mark_explored(
                proposal["id"],
                outcome=outcome_summary
            )
        except Exception as exc:
            print(f"[research] ⚠️  mark_explored error: {exc}")

        # Actualizar estadísticas de sesión
        session.questions_successful    += 1
        session.triples_added_total     += integration.triples_added
        session.concepts_touched_total  += integration.concepts_touched
        session.summaries.append({
            "question": proposal.get("question", "")[:80],
            "type":     proposal.get("type", ""),
            "triples":  integration.triples_added,
            "concepts": integration.concepts_touched,
        })

        if verbose:
            print(f"   ✅ Integrado: +{integration.triples_added} triples, "
                  f"+{integration.concepts_touched} conceptos")

        # Pausa entre investigaciones
        if i < len(selected):
            time.sleep(INTER_RESEARCH_PAUSE_SEC)

    # ── Finalizar sesión ───────────────────────────────────────────────
    session.duration_sec = round(time.time() - start_time, 1)

    if verbose:
        print(f"\n🔬 Sesión completada en {session.duration_sec}s")
        print(f"   Investigadas: {session.questions_successful}/{session.questions_attempted}")
        print(f"   Conocimiento: +{session.triples_added_total} triples KG, "
              f"+{session.concepts_touched_total} conceptos\n")

    return session


def format_sleep_summary(session: ResearchSessionResult) -> str:
    """
    Genera la línea de resumen para añadir al output del método sleep() de Cognia.
    """
    if session.questions_attempted == 0:
        return ""

    return (
        f"\n   Investigación:  {session.questions_successful}/{session.questions_attempted} "
        f"preguntas resueltas, "
        f"+{session.triples_added_total} triples KG, "
        f"+{session.concepts_touched_total} conceptos"
    )


def show_research_history(db_path: str, limit: int = 10) -> str:
    """
    Resumen legible del historial de investigaciones.
    Para usar desde la CLI de Cognia.
    """
    log = get_research_log(db_path, limit)
    if not log:
        return "📚 No hay historial de investigaciones aún."

    lines = [f"📚 Historial de investigación ({len(log)} entradas recientes)\n"]
    for entry in log:
        ts    = entry["timestamp"][:16]
        topic = entry.get("topic") or entry.get("question", "")[:40]
        lines.append(
            f"  [{ts}] {topic} "
            f"(+{entry['triples_added']} triples, conf={entry['confidence']:.2f})"
        )
    return "\n".join(lines)
