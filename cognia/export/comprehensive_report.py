"""
cognia/export/comprehensive_report.py
=======================================
Comprehensive Markdown Report Generator.
Aggregates data from 7 subsystems into a single Markdown report.
No LLM calls — pure data aggregation.
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Optional


class ComprehensiveReportGenerator:
    """
    Generates a full Markdown report aggregating all Cognia subsystems.
    No LLM calls. Uses _safe_call() so any subsystem failure yields empty data.
    """

    def _safe_call(self, fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:
            return {}

    # ── Section helpers ─────────────────────────────────────────────────

    def _get_profile_data(self, user_id: str) -> dict:
        try:
            from cognia.intelligence.cognitive_profile import CognitiveProfile
            cp = CognitiveProfile()
            return cp.build(user_id)
        except Exception:
            return {}

    def _get_notes_stats(self) -> dict:
        try:
            from cognia.notes.smart_notes import SmartNotesEngine
            sne = SmartNotesEngine()
            # count total and by_type from DB directly via the engine's pool
            from storage.db_pool import get_pool
            from cognia.notes.smart_notes import _get_db
            db = _get_db()
            with get_pool(db).get() as conn:
                total = conn.execute("SELECT COUNT(*) FROM smart_notes").fetchone()[0]
                rows = conn.execute(
                    "SELECT note_type, COUNT(*) FROM smart_notes GROUP BY note_type"
                ).fetchall()
            by_type = {r[0]: r[1] for r in rows}
            return {"total": total, "by_type": by_type}
        except Exception:
            return {"total": 0, "by_type": {}}

    def _get_top_features(self, user_id: str, period_days: int) -> list:
        try:
            from cognia.analytics.usage_analytics import UsageAnalytics
            ua = UsageAnalytics()
            return ua.get_top_features(user_id=user_id, days=period_days, limit=5)
        except Exception:
            return []

    def _get_quality_score(self, period_days: int) -> dict:
        try:
            from cognia.reasoning.self_critic import SelfCritic
            sc = SelfCritic()
            avg = sc.get_avg_score(days=period_days)
            # determine trend: compare first vs second half of period
            import time
            cutoff_full = time.time() - period_days * 86400
            cutoff_half = time.time() - (period_days // 2) * 86400
            from storage.db_pool import get_pool
            with get_pool(sc._db_path).get() as conn:
                row_early = conn.execute(
                    "SELECT AVG(overall_score) FROM response_critiques "
                    "WHERE ts >= ? AND ts < ?",
                    (cutoff_full, cutoff_half),
                ).fetchone()
                row_late = conn.execute(
                    "SELECT AVG(overall_score) FROM response_critiques "
                    "WHERE ts >= ?",
                    (cutoff_half,),
                ).fetchone()
            early = float(row_early[0]) if row_early and row_early[0] is not None else avg
            late = float(row_late[0]) if row_late and row_late[0] is not None else avg
            diff = late - early
            if diff > 0.05:
                trend = "mejorando"
            elif diff < -0.05:
                trend = "declinando"
            else:
                trend = "estable"
            return {"avg": round(avg, 4), "trend": trend}
        except Exception:
            return {"avg": 0.0, "trend": "sin datos"}

    def _get_achievement_names(self, user_id: str) -> list:
        try:
            from cognia.gamification.achievement_system import AchievementSystem
            from cognia.intelligence.cognitive_profile import _get_db
            ach = AchievementSystem(db_path=_get_db())
            unlocked = ach.get_user_achievements(user_id)
            return [a["name"] for a in unlocked]
        except Exception:
            return []

    # ── Main report builder ─────────────────────────────────────────────

    def generate(self, period_days: int = 7, user_id: str = "default") -> str:
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        datetime_str = now.strftime("%Y-%m-%d %H:%M")

        # Gather all data (each wrapped; failures return fallback)
        profile = self._safe_call(self._get_profile_data, user_id)
        notes = self._safe_call(self._get_notes_stats)
        top_features = self._safe_call(self._get_top_features, user_id, period_days)
        quality = self._safe_call(self._get_quality_score, period_days)
        achievement_names = self._safe_call(self._get_achievement_names, user_id)

        # Extract sub-dicts from profile
        overall_score = int(profile.get("overall_score", 0))
        analytics = profile.get("analytics", {})
        active_days = analytics.get("active_days", 0)
        streak = analytics.get("streak", 0)

        goals = profile.get("goals", {})
        goals_pending = goals.get("pending", 0)
        goals_completed = goals.get("completed", 0)
        goals_total = goals.get("total", 0)
        goals_in_progress = max(0, goals_total - goals_pending - goals_completed)

        learning = profile.get("learning", {})
        learn_total = learning.get("total", 0)
        learn_mastered = learning.get("mastered", 0)
        learn_due = learning.get("due_today", 0)

        notes_total = notes.get("total", 0) if isinstance(notes, dict) else 0
        notes_by_type = notes.get("by_type", {}) if isinstance(notes, dict) else {}

        achievements = profile.get("achievements", {})
        ach_unlocked = achievements.get("unlocked", 0)
        ach_total = achievements.get("total", 0)
        ach_points = achievements.get("points", 0)

        avg_score = quality.get("avg", 0.0) if isinstance(quality, dict) else 0.0
        trend = quality.get("trend", "sin datos") if isinstance(quality, dict) else "sin datos"

        features_list = top_features if isinstance(top_features, list) else []

        # ── Build Markdown ──────────────────────────────────────────────

        lines: list[str] = []

        lines.append(f"# Reporte Cognia -- {date_str}")
        lines.append(f"**Periodo:** Ultimos {period_days} dias | **Usuario:** {user_id}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Perfil Cognitivo
        lines.append("## Perfil Cognitivo")
        lines.append(f"- Puntuacion general: {overall_score}/1000")
        lines.append(f"- Dias activos: {active_days}")
        lines.append(f"- Racha actual: {streak} dia(s)")
        lines.append("")

        # Objetivos
        lines.append("## Objetivos")
        lines.append("| Estado | Cantidad |")
        lines.append("|---|---|")
        lines.append(f"| Pendientes | {goals_pending} |")
        lines.append(f"| En progreso | {goals_in_progress} |")
        lines.append(f"| Completados | {goals_completed} |")
        lines.append("")

        # Aprendizaje
        lines.append("## Aprendizaje (SM-2)")
        lines.append(f"- Total tarjetas: {learn_total}")
        lines.append(f"- Dominadas (>=5 repeticiones): {learn_mastered}")
        lines.append(f"- Para revisar hoy: {learn_due}")
        lines.append("")

        # Notas
        note_types = ["fact", "decision", "action", "insight", "question"]
        by_type_str = ", ".join(
            f"{t}: {notes_by_type.get(t, 0)}" for t in note_types
        )
        lines.append("## Notas Guardadas")
        lines.append(f"- Total: {notes_total}")
        lines.append(f"- Por tipo: {{{by_type_str}}}")
        lines.append("")

        # Logros
        lines.append("## Logros")
        lines.append(f"- Desbloqueados: {ach_unlocked}/{ach_total} ({ach_points} puntos)")
        if achievement_names and isinstance(achievement_names, list):
            for name in achievement_names:
                lines.append(f"  - {name}")
        lines.append("")

        # Calidad de respuestas
        lines.append("## Calidad de Respuestas")
        lines.append(f"- Puntuacion promedio ({period_days}d): {avg_score}/1.0")
        lines.append(f"- Tendencia: {trend}")
        lines.append("")

        # Funciones mas usadas
        lines.append("## Funciones Mas Usadas")
        if features_list:
            for item in features_list:
                feat = item.get("feature", "?")
                total = item.get("total", 0)
                lines.append(f"- {feat}: {total} usos")
        else:
            lines.append("- Sin datos de uso registrados")
        lines.append("")

        lines.append("---")
        lines.append(f"*Generado por Cognia v3 -- {datetime_str}*")

        return "\n".join(lines)

    def save(self, path: str, period_days: int = 7, user_id: str = "default") -> str:
        """Save the generated report to path. Returns absolute path."""
        content = self.generate(period_days=period_days, user_id=user_id)
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path) if os.path.dirname(abs_path) else ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return abs_path
