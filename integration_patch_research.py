"""
integration_patch_research.py
==============================
Guía de los cambios mínimos a aplicar en cognia_v3.py para integrar
el módulo de investigación autónoma durante el sueño.

Solo 3 modificaciones — todas aditivas, ninguna toca código existente.
"""

# ==============================================================================
# MODIFICACIÓN 1 — Import del módulo (junto a los otros imports opcionales)
# ==============================================================================
# Ubicación: cerca de la línea 45-55, junto a los HAS_FATIGUE, HAS_PLANNER, etc.

PATCH_1 = '''
# ── Módulo de investigación autónoma ──────────────────────────────────────────
try:
    from cognia.research_engine import run_research_session, format_sleep_summary
    HAS_RESEARCH_ENGINE = True
except ImportError:
    HAS_RESEARCH_ENGINE = False
'''

# ==============================================================================
# MODIFICACIÓN 2 — Añadir en Cognia.__init__() después de los otros módulos
# ==============================================================================

PATCH_2 = '''
        # Módulo de investigación autónoma
        if HAS_RESEARCH_ENGINE:
            print("✅ ResearchEngine (investigación autónoma) activo")
'''

# ==============================================================================
# MODIFICACIÓN 3 — Añadir en el método sleep(), ANTES del return final
# ==============================================================================
# Ubicación: Justo después del bloque de hobby de programación (si existe),
# o justo antes de la línea "extras = ''"

PATCH_3 = '''
        # ── Investigación autónoma durante el sueño ────────────────────────
        research_info = ""
        if HAS_RESEARCH_ENGINE:
            try:
                research_session = run_research_session(
                    cognia_instance=self,
                    db_path=self.db,
                    max_questions=3,
                    verbose=False,   # Cambia a True para ver logs detallados
                )
                research_info = format_sleep_summary(research_session)
            except Exception:
                pass   # Nunca romper el ciclo de sueño
'''

# ==============================================================================
# MODIFICACIÓN 4 — Añadir research_info al return de sleep()
# ==============================================================================
# Cambiar el final del return de sleep():
#
# ANTES:
#   + extras)
#
# DESPUÉS:
#   + extras + research_info)   # si ya tienes hobby_info, añadir también:
#   + extras + hobby_info + research_info)

PATCH_4 = '''
# En el return final de sleep(), añadir + research_info al final.
# Si ya integraste el módulo de programación hobby:
#   + extras + hobby_info + research_info)
# Si no:
#   + extras + research_info)
'''

# ==============================================================================
# MODIFICACIÓN 5 (opcional) — Comando CLI para ver historial de investigaciones
# ==============================================================================

PATCH_5 = '''
    elif cmd == "research" or cmd == "investigaciones":
        if HAS_RESEARCH_ENGINE:
            from cognia.research_engine import show_research_history
            print(show_research_history(cognia.db))
        else:
            print("Módulo de investigación no disponible.")
'''

# ==============================================================================
# EJEMPLO DE SALIDA DE sleep() CON AMBOS MÓDULOS INTEGRADOS
# ==============================================================================

EXAMPLE_OUTPUT = """
😴 CICLO DE SUEÑO v3 completado (3420ms):
   Consolidación:  4 conceptos, 7 asociaciones
   Compresión:     12 labels, 3 episodios comprimidos
   Grafo:          +6 relaciones
   Olvido:         2 episodios
   Contradicciones resueltas: 1
   Nuevos objetivos: 2
   Hipótesis generadas: 1
   Investigación:  2/3 preguntas resueltas, +8 triples KG, +5 conceptos
   Programas hobby:  +1 guardados
"""

# ==============================================================================
# FLUJO COMPLETO DURANTE EL SUEÑO (con ambos módulos)
# ==============================================================================

FLOW = """
sleep() de Cognia con ambos módulos integrados:

  Consolidación semántica        (100%)
  Compresión conceptual          (100%)
  Actualización KG               (100%)
  Ciclo de olvido                (100%)
  Resolver contradicciones       (100%)
  Generar objetivos              (100%)
  ─────────────────────────────────────
  Hipótesis espontánea           (si hay ≥4 conceptos buenos)
  Investigación autónoma         (100% — investiga top-3 preguntas pendientes)
  ─────────────────────────────────────
  Hobby de programación          (40% probabilidad)
  Limpieza de ruido              (si hay ruido acumulado)

La investigación es DETERMINISTA (siempre ocurre si hay preguntas pendientes).
El hobby de programación es PROBABILÍSTICO (40%).
"""

if __name__ == "__main__":
    print(FLOW)
    print(EXAMPLE_OUTPUT)
