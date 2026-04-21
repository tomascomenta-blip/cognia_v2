"""
scoring_engine.py — Sistema de puntuación para propuestas de Cognia
====================================================================
Registra y acumula scores para propuestas (código, módulos, cambios arquitectónicos).

TABLA DE PUNTOS:
  +15 → propuesta nueva e interesante que el usuario no había considerado
  +10 → código que funciona a la primera sin errores
  +8  → solución más eficiente que la existente
  +5  → buena documentación o explicación clara
  -20 → error de sintaxis en código propuesto
  -15 → código que rompe módulos existentes
  -10 → propuesta repetida que ya existe en Cognia
  -8  → código que no sigue el estilo del proyecto

INTEGRACIÓN CON EpisodicMemory:
  El score acumulado ajusta el feedback_weight del episodio relacionado.
  El SelfArchitect consulta get_score_summary() para aprender qué tipo
  de propuestas son bien recibidas.

USO:
  from scoring_engine import get_scoring_engine
  se = get_scoring_engine(db_path="cognia_memory.db")
  se.record("prop_001", "nueva_funcion", +10, "código funcionó sin errores")
  se.record("prop_001", "documentacion", +5, "docstrings claros")
  summary = se.get_score_summary()
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# ── Tabla de puntos (constantes públicas para que el SelfArchitect las use) ───

SCORE_NEW_INTERESTING     = +15   # propuesta original
SCORE_WORKS_FIRST_TRY     = +10   # código funciona sin errores
SCORE_MORE_EFFICIENT      = +8    # solución más eficiente
SCORE_GOOD_DOCS           = +5    # buena documentación
SCORE_SYNTAX_ERROR        = -20   # error de sintaxis
SCORE_BREAKS_MODULES      = -15   # rompe módulos existentes
SCORE_ALREADY_EXISTS      = -10   # propuesta duplicada
SCORE_WRONG_STYLE         = -8    # no sigue el estilo del proyecto

# Mapeo de etiquetas a valores (para registro automático desde otros módulos)
SCORE_TABLE: dict[str, int] = {
    "nueva_propuesta":     SCORE_NEW_INTERESTING,
    "codigo_funciona":     SCORE_WORKS_FIRST_TRY,
    "mas_eficiente":       SCORE_MORE_EFFICIENT,
    "buena_documentacion": SCORE_GOOD_DOCS,
    "error_sintaxis":      SCORE_SYNTAX_ERROR,
    "rompe_modulos":       SCORE_BREAKS_MODULES,
    "propuesta_repetida":  SCORE_ALREADY_EXISTS,
    "mal_estilo":          SCORE_WRONG_STYLE,
}

# ── Esquema de tablas ──────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS scoring_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL,
    event_label     TEXT NOT NULL,
    points          INTEGER NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    proposal_type   TEXT NOT NULL DEFAULT 'codigo',
    created_at      TEXT NOT NULL,
    ep_id           INTEGER DEFAULT NULL    -- episodio relacionado en episodic_memory
);

CREATE TABLE IF NOT EXISTS scoring_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL UNIQUE,
    proposal_type   TEXT NOT NULL DEFAULT 'codigo',
    total_score     INTEGER NOT NULL DEFAULT 0,
    event_count     INTEGER NOT NULL DEFAULT 0,
    outcome         TEXT NOT NULL DEFAULT 'pendiente',
    created_at      TEXT NOT NULL,
    closed_at       TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_scoring_proposal ON scoring_events(proposal_id);
CREATE INDEX IF NOT EXISTS idx_scoring_label    ON scoring_events(event_label);
CREATE INDEX IF NOT EXISTS idx_scoring_date     ON scoring_events(created_at);
"""


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ScoreEvent:
    """Evento individual de scoring."""
    proposal_id:   str
    event_label:   str
    points:        int
    reason:        str
    proposal_type: str
    created_at:    str
    ep_id:         Optional[int] = None


@dataclass
class ScoreSummary:
    """Resumen del historial de scoring."""
    total_events:        int
    total_points_all:    int
    avg_score_per_proposal: float
    top_positive_labels: list[dict]   # labels con más puntos positivos
    top_negative_labels: list[dict]   # labels con más penalizaciones
    recent_proposals:    list[dict]   # últimas 5 propuestas con su score
    success_rate:        float        # % de propuestas con score > 0


# ── Clase principal ────────────────────────────────────────────────────────────

class ScoringEngine:
    """
    Registra y consulta el historial de puntuaciones de propuestas.

    Flujo típico:
      1. SelfArchitect genera una propuesta → se crea sesión con proposal_id
      2. Cada verificación automática llama record() con el label apropiado
      3. El usuario da feedback → record() con "codigo_funciona" o "error_sintaxis"
      4. close_session() cierra la sesión con outcome final
      5. adjust_episodic_weight() propaga el score a EpisodicMemory
    """

    def __init__(self, db_path: str, cognia_instance=None):
        """
        Args:
            db_path:          ruta al SQLite de Cognia
            cognia_instance:  instancia de Cognia (para ajustar feedback_weight)
        """
        self.db  = db_path
        self._ai = cognia_instance
        self._init_tables()
        logger.info(
            "ScoringEngine inicializado",
            extra={"op": "scoring_engine.init", "context": f"db={db_path}"},
        )

    # ── Inicialización ─────────────────────────────────────────────────

    def _init_tables(self):
        try:
            conn = sqlite3.connect(self.db)
            conn.executescript(_DDL)
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "scoring_engine._init_tables", exc)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db)
        conn.text_factory = str
        return conn

    # ── API pública: registrar eventos ────────────────────────────────

    def record(
        self,
        proposal_id:   str,
        event_label:   str,
        points:        int = None,
        reason:        str = "",
        proposal_type: str = "codigo",
        ep_id:         int = None,
    ) -> int:
        """
        Registra un evento de scoring para una propuesta.

        Args:
            proposal_id:   identificador de la propuesta (ej: "prop_20250416_001")
            event_label:   etiqueta del evento (usar constantes de SCORE_TABLE)
            points:        puntos a otorgar. Si None, se busca en SCORE_TABLE
            reason:        descripción textual del por qué
            proposal_type: tipo de propuesta ("codigo", "modulo", "arquitectura")
            ep_id:         id del episodio en EpisodicMemory (opcional)

        Returns:
            id del evento registrado, o -1 si falló
        """
        # Resolver puntos desde la tabla si no se especificaron
        if points is None:
            points = SCORE_TABLE.get(event_label, 0)
            if points == 0:
                logger.warning(
                    f"event_label '{event_label}' no está en SCORE_TABLE y "
                    "no se especificaron puntos. Se registra como 0.",
                    extra={"op": "scoring_engine.record",
                           "context": f"proposal_id={proposal_id}"},
                )

        now = datetime.now().isoformat()
        try:
            conn = self._connect()
            c = conn.cursor()

            # Registrar evento
            c.execute("""
                INSERT INTO scoring_events
                (proposal_id, event_label, points, reason, proposal_type,
                 created_at, ep_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (proposal_id, event_label, points, reason,
                  proposal_type, now, ep_id))
            event_id = c.lastrowid

            # Actualizar/crear sesión
            c.execute("""
                SELECT id, total_score, event_count
                FROM scoring_sessions WHERE session_id = ?
            """, (proposal_id,))
            session_row = c.fetchone()

            if session_row:
                new_score = session_row[1] + points
                new_count = session_row[2] + 1
                c.execute("""
                    UPDATE scoring_sessions
                    SET total_score = ?, event_count = ?
                    WHERE session_id = ?
                """, (new_score, new_count, proposal_id))
            else:
                c.execute("""
                    INSERT INTO scoring_sessions
                    (session_id, proposal_type, total_score, event_count,
                     outcome, created_at)
                    VALUES (?, ?, ?, 1, 'pendiente', ?)
                """, (proposal_id, proposal_type, points, now))

            conn.commit()
            conn.close()

            # Log con emoji para distinguir positivo/negativo visualmente
            sign = "✅" if points >= 0 else "❌"
            logger.info(
                f"Score registrado {sign}",
                extra={
                    "op":      "scoring_engine.record",
                    "context": (
                        f"proposal={proposal_id} label={event_label} "
                        f"points={points:+d} reason={reason[:60]}"
                    ),
                },
            )

            # Propagar automáticamente a EpisodicMemory si hay ep_id
            if ep_id and self._ai:
                self._adjust_episodic_weight(ep_id, points)

            return event_id
        except Exception as exc:
            log_db_error(logger, "scoring_engine.record", exc,
                         extra_ctx=f"proposal_id={proposal_id} label={event_label}")
            return -1

    def record_from_execution(
        self,
        proposal_id:   str,
        exec_success:  bool,
        has_syntax_err: bool = False,
        breaks_imports: bool = False,
        proposal_type: str = "codigo",
        ep_id:         int = None,
    ) -> int:
        """
        Registra el score automáticamente basado en el resultado de CodeExecutor.

        Integración directa con run_python() / validate_python().

        Args:
            proposal_id:    identificador de la propuesta
            exec_success:   si el código ejecutó sin errores
            has_syntax_err: si hubo SyntaxError en validación
            breaks_imports: si hubo imports peligrosos
            proposal_type:  tipo de propuesta
            ep_id:          id del episodio relacionado

        Returns:
            id del último evento registrado
        """
        last_id = -1
        if has_syntax_err:
            last_id = self.record(
                proposal_id, "error_sintaxis", SCORE_SYNTAX_ERROR,
                "SyntaxError detectado en validación", proposal_type, ep_id
            )
        elif breaks_imports:
            last_id = self.record(
                proposal_id, "rompe_modulos", SCORE_BREAKS_MODULES,
                "Imports peligrosos o incompatibles detectados", proposal_type, ep_id
            )
        elif exec_success:
            last_id = self.record(
                proposal_id, "codigo_funciona", SCORE_WORKS_FIRST_TRY,
                "Código ejecutó correctamente a la primera", proposal_type, ep_id
            )
        else:
            # Código no funcionó pero tampoco hay SyntaxError — error de runtime
            last_id = self.record(
                proposal_id, "error_runtime", -5,
                "Código falló en ejecución (error de runtime)", proposal_type, ep_id
            )
        return last_id

    def close_session(
        self,
        proposal_id: str,
        outcome:     str = "completada",
    ) -> dict:
        """
        Cierra una sesión de scoring y devuelve el resultado final.

        Args:
            proposal_id: identificador de la sesión
            outcome:     "completada" | "rechazada" | "descartada"

        Returns:
            dict con total_score, event_count, outcome
        """
        now = datetime.now().isoformat()
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                UPDATE scoring_sessions
                SET outcome = ?, closed_at = ?
                WHERE session_id = ?
            """, (outcome, now, proposal_id))
            c.execute("""
                SELECT total_score, event_count FROM scoring_sessions
                WHERE session_id = ?
            """, (proposal_id,))
            row = c.fetchone()
            conn.commit()
            conn.close()

            if row:
                result = {
                    "proposal_id": proposal_id,
                    "total_score": row[0],
                    "event_count": row[1],
                    "outcome": outcome,
                }
                logger.info(
                    f"Sesión cerrada",
                    extra={"op":      "scoring_engine.close_session",
                           "context": (f"proposal={proposal_id} "
                                       f"score={row[0]} events={row[1]} "
                                       f"outcome={outcome}")},
                )
                return result
        except Exception as exc:
            log_db_error(logger, "scoring_engine.close_session", exc,
                         extra_ctx=f"proposal_id={proposal_id}")
        return {"proposal_id": proposal_id, "total_score": 0,
                "event_count": 0, "outcome": "error"}

    def get_proposal_score(self, proposal_id: str) -> int:
        """Devuelve el score acumulado de una propuesta."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                SELECT COALESCE(SUM(points), 0)
                FROM scoring_events WHERE proposal_id = ?
            """, (proposal_id,))
            score = c.fetchone()[0]
            conn.close()
            return int(score)
        except Exception as exc:
            log_db_error(logger, "scoring_engine.get_proposal_score", exc,
                         extra_ctx=f"proposal_id={proposal_id}")
            return 0

    # ── API pública: consultas y resumen ──────────────────────────────

    def get_score_summary(self, last_n_proposals: int = 20) -> ScoreSummary:
        """
        Devuelve un resumen del historial de scoring.
        El SelfArchitect usa esto para aprender qué propuestas son bien recibidas.

        Args:
            last_n_proposals: cuántas propuestas recientes incluir en el resumen

        Returns:
            ScoreSummary con estadísticas agregadas
        """
        try:
            conn = self._connect()
            c = conn.cursor()

            # Total de eventos y puntos
            c.execute("SELECT COUNT(*), COALESCE(SUM(points), 0) FROM scoring_events")
            total_events, total_points = c.fetchone()

            # Labels con más puntos positivos
            c.execute("""
                SELECT event_label, SUM(points) as total, COUNT(*) as n
                FROM scoring_events WHERE points > 0
                GROUP BY event_label ORDER BY total DESC LIMIT 5
            """)
            top_positive = [
                {"label": r[0], "total_points": r[1], "count": r[2]}
                for r in c.fetchall()
            ]

            # Labels con más penalizaciones
            c.execute("""
                SELECT event_label, SUM(points) as total, COUNT(*) as n
                FROM scoring_events WHERE points < 0
                GROUP BY event_label ORDER BY total ASC LIMIT 5
            """)
            top_negative = [
                {"label": r[0], "total_points": r[1], "count": r[2]}
                for r in c.fetchall()
            ]

            # Propuestas recientes
            c.execute("""
                SELECT session_id, proposal_type, total_score,
                       event_count, outcome, created_at
                FROM scoring_sessions
                ORDER BY created_at DESC LIMIT ?
            """, (last_n_proposals,))
            recent = [
                {
                    "proposal_id":   r[0],
                    "type":          r[1],
                    "total_score":   r[2],
                    "event_count":   r[3],
                    "outcome":       r[4],
                    "created_at":    r[5],
                }
                for r in c.fetchall()
            ]

            # Tasa de éxito (propuestas con score > 0)
            positive_count = sum(1 for p in recent if p["total_score"] > 0)
            success_rate   = (positive_count / len(recent)) if recent else 0.0

            # Score promedio por propuesta
            avg_score = (
                sum(p["total_score"] for p in recent) / len(recent)
                if recent else 0.0
            )

            conn.close()
            return ScoreSummary(
                total_events=total_events,
                total_points_all=total_points,
                avg_score_per_proposal=round(avg_score, 1),
                top_positive_labels=top_positive,
                top_negative_labels=top_negative,
                recent_proposals=recent,
                success_rate=round(success_rate, 2),
            )
        except Exception as exc:
            log_db_error(logger, "scoring_engine.get_score_summary", exc)
            return ScoreSummary(
                total_events=0, total_points_all=0,
                avg_score_per_proposal=0.0,
                top_positive_labels=[], top_negative_labels=[],
                recent_proposals=[], success_rate=0.0,
            )

    def format_summary(self) -> str:
        """Devuelve el resumen en formato legible para el SelfArchitect."""
        s = self.get_score_summary()
        lines = [
            "📊 ScoringEngine — Resumen de historial",
            f"   Eventos totales:    {s.total_events}",
            f"   Puntos acumulados:  {s.total_points_all:+d}",
            f"   Score promedio:     {s.avg_score_per_proposal:+.1f} / propuesta",
            f"   Tasa de éxito:      {s.success_rate:.0%}",
        ]
        if s.top_positive_labels:
            lines.append("\n   ✅ Labels más valiosos:")
            for lbl in s.top_positive_labels[:3]:
                lines.append(f"      {lbl['label']}: {lbl['total_points']:+d}pts ({lbl['count']}x)")
        if s.top_negative_labels:
            lines.append("\n   ❌ Labels más penalizados:")
            for lbl in s.top_negative_labels[:3]:
                lines.append(f"      {lbl['label']}: {lbl['total_points']:+d}pts ({lbl['count']}x)")
        if s.recent_proposals:
            lines.append("\n   📋 Últimas propuestas:")
            for p in s.recent_proposals[:5]:
                score_str = f"{p['total_score']:+d}"
                icon = "✅" if p["total_score"] > 0 else ("⚠️" if p["total_score"] == 0 else "❌")
                lines.append(
                    f"      {icon} [{p['type']}] {p['proposal_id'][:20]}... "
                    f"score={score_str} ({p['outcome']})"
                )
        return "\n".join(lines)

    # ── Integración con EpisodicMemory ─────────────────────────────────

    def _adjust_episodic_weight(self, ep_id: int, points: int):
        """
        Ajusta el feedback_weight del episodio en EpisodicMemory
        basado en los puntos del scoring.

        Conversión:
          score >= +10 → delta = +0.30 (episodio muy bueno, sube en ranking)
          score >= +5  → delta = +0.15
          score >= 0   → sin cambio
          score < 0    → delta = -0.15 (baja en ranking)
          score <= -15 → delta = -0.30 (muy malo, penalización máxima)
        """
        if points >= 10:
            delta = 0.30
        elif points >= 5:
            delta = 0.15
        elif points > 0:
            delta = 0.05
        elif points < -15:
            delta = -0.30
        elif points < 0:
            delta = -0.15
        else:
            return  # sin cambio para 0 puntos

        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute(
                "SELECT COALESCE(feedback_weight, 1.0) FROM episodic_memory WHERE id = ?",
                (ep_id,)
            )
            row = c.fetchone()
            if not row:
                conn.close()
                return
            old_weight = float(row[0])
            new_weight = max(0.2, min(2.0, old_weight + delta))
            c.execute(
                "UPDATE episodic_memory SET feedback_weight = ? WHERE id = ?",
                (new_weight, ep_id)
            )
            conn.commit()
            conn.close()
            logger.debug(
                "feedback_weight de episodio ajustado por scoring",
                extra={"op":      "scoring_engine._adjust_episodic_weight",
                       "context": (f"ep_id={ep_id} delta={delta:+.2f} "
                                   f"old={old_weight:.2f} new={new_weight:.2f}")},
            )
        except Exception as exc:
            log_db_error(logger, "scoring_engine._adjust_episodic_weight", exc,
                         extra_ctx=f"ep_id={ep_id} points={points}")

    def adjust_weights_from_session(self, proposal_id: str, ep_id: int):
        """
        Aplica el score total de una sesión cerrada al feedback_weight
        del episodio relacionado. Llamar después de close_session().
        """
        total = self.get_proposal_score(proposal_id)
        self._adjust_episodic_weight(ep_id, total)


# ── Singleton ──────────────────────────────────────────────────────────────────

_SCORING_INSTANCE: Optional[ScoringEngine] = None


def get_scoring_engine(db_path: str = None,
                       cognia_instance=None) -> ScoringEngine:
    """
    Devuelve la instancia singleton del ScoringEngine.

    Args:
        db_path:          ruta al SQLite de Cognia
        cognia_instance:  instancia de Cognia (para ajustar feedback_weight)
    """
    global _SCORING_INSTANCE
    if _SCORING_INSTANCE is None:
        if db_path is None and cognia_instance is not None:
            db_path = getattr(cognia_instance, "db", "cognia_memory.db")
        db_path = db_path or "cognia_memory.db"
        _SCORING_INSTANCE = ScoringEngine(db_path, cognia_instance)
    elif cognia_instance is not None and _SCORING_INSTANCE._ai is None:
        _SCORING_INSTANCE._ai = cognia_instance
    return _SCORING_INSTANCE


# ── Tests básicos ──────────────────────────────────────────────────────────────

def _test_record_and_score(tmp_db: str):
    """Test 1: registrar eventos y verificar score."""
    se = ScoringEngine(tmp_db)

    # Propuesta exitosa
    se.record("prop_001", "nueva_propuesta",   SCORE_NEW_INTERESTING, "idea original")
    se.record("prop_001", "codigo_funciona",   SCORE_WORKS_FIRST_TRY, "ejecutó OK")
    se.record("prop_001", "buena_documentacion", SCORE_GOOD_DOCS, "docstrings claros")

    score = se.get_proposal_score("prop_001")
    expected = SCORE_NEW_INTERESTING + SCORE_WORKS_FIRST_TRY + SCORE_GOOD_DOCS
    assert score == expected, f"FALLO: score={score} esperado={expected}"
    print(f"  ✅ Score propuesta exitosa: {score:+d} pts")

    # Propuesta con errores
    se.record("prop_002", "error_sintaxis", SCORE_SYNTAX_ERROR, "SyntaxError en línea 5")
    se.record("prop_002", "mal_estilo",     SCORE_WRONG_STYLE, "camelCase en vez de snake_case")
    score_bad = se.get_proposal_score("prop_002")
    assert score_bad == SCORE_SYNTAX_ERROR + SCORE_WRONG_STYLE
    print(f"  ✅ Score propuesta con errores: {score_bad:+d} pts")


def _test_record_from_execution(tmp_db: str):
    """Test 2: integración con CodeExecutor."""
    se = ScoringEngine(tmp_db)

    # Simular resultado exitoso de CodeExecutor
    last_id = se.record_from_execution(
        "prop_exec_001", exec_success=True,
        has_syntax_err=False, breaks_imports=False
    )
    assert last_id > 0, "FALLO: record_from_execution devolvió -1"
    score = se.get_proposal_score("prop_exec_001")
    assert score == SCORE_WORKS_FIRST_TRY
    print(f"  ✅ record_from_execution (éxito): {score:+d} pts")

    # Simular SyntaxError
    se.record_from_execution(
        "prop_exec_002", exec_success=False,
        has_syntax_err=True, breaks_imports=False
    )
    score_bad = se.get_proposal_score("prop_exec_002")
    assert score_bad == SCORE_SYNTAX_ERROR
    print(f"  ✅ record_from_execution (error sintaxis): {score_bad:+d} pts")


def _test_summary(tmp_db: str):
    """Test 3: get_score_summary y format_summary."""
    se = ScoringEngine(tmp_db)
    se.record("prop_s1", "nueva_propuesta", SCORE_NEW_INTERESTING)
    se.close_session("prop_s1", "completada")

    summary = se.get_score_summary()
    assert summary.total_events > 0, "FALLO: sin eventos en summary"
    assert summary.success_rate >= 0
    text = se.format_summary()
    assert "ScoringEngine" in text
    print(f"  ✅ get_score_summary OK: {summary.total_events} eventos, "
          f"success_rate={summary.success_rate:.0%}")
    print(f"  ✅ format_summary OK ({len(text)} chars)")


def run_tests():
    """Ejecuta todos los tests del ScoringEngine."""
    import tempfile, os
    print("\n🧪 Tests ScoringEngine:")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp = f.name
    try:
        _test_record_and_score(tmp)
        _test_record_from_execution(tmp)
        _test_summary(tmp)
    finally:
        os.unlink(tmp)
    print("✅ Todos los tests pasaron.\n")


if __name__ == "__main__":
    run_tests()
