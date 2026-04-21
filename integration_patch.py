"""
integration_patch.py
====================
Este archivo NO es un módulo ejecutable.
Es una guía de los cambios mínimos a aplicar en cognia_v3.py para
integrar el módulo de programación hobby.

Solo se necesitan 3 modificaciones — todas en cognia_v3.py:

  1. Import del módulo (al principio del archivo)
  2. Inicialización en Cognia.__init__()
  3. Llamada desde Cognia.sleep()

Cada sección incluye:
  - El contexto exacto donde insertar el código
  - El código a añadir
  - Explicación del cambio
"""

# ==============================================================================
# MODIFICACIÓN 1 — Import del módulo
# ==============================================================================
# Ubicación: Cerca de los otros imports opcionales, alrededor de la línea 45-55
# (junto a los HAS_FATIGUE, HAS_PLANNER, etc.)
#
# Añadir DESPUÉS de los imports existentes de módulos opcionales:

PATCH_1_IMPORTS = '''
# ── Módulo de programación hobby (opcional) ────────────────────────────────────
try:
    from cognia.program_creator import maybe_run_hobby, show_library, get_session_stats
    HAS_PROGRAM_CREATOR = True
except ImportError:
    HAS_PROGRAM_CREATOR = False
'''

# ==============================================================================
# MODIFICACIÓN 2 — Inicialización en Cognia.__init__()
# ==============================================================================
# Ubicación: Al final de Cognia.__init__(), después de la línea que dice:
#   self.curiosity_engine = ActiveCuriosityEngine(db_path) if HAS_CURIOSITY_ENGINE else None
#   if self.curiosity_engine: print("✅ CuriosityEngine activo")
#
# Añadir DESPUÉS de esas líneas:

PATCH_2_INIT = '''
        # Módulo de programación hobby (Hobby Programming)
        self._hobby_idle_seconds = 0.0   # Contador de inactividad para el hobby
        self._last_interaction_time = time.time()
        if HAS_PROGRAM_CREATOR:
            print("✅ ProgramCreator (hobby) activo")
'''

# ==============================================================================
# MODIFICACIÓN 3 — Llamada desde Cognia.sleep()
# ==============================================================================
# Ubicación: Al final del método sleep(), DESPUÉS de la generación de hipótesis
# (después del bloque que dice "Hipótesis espontánea durante el sueño")
# y ANTES del return final.
#
# Añadir ANTES del bloque de "Limpieza de ruido episódico":

PATCH_3_SLEEP = '''
        # ── Hobby de programación durante el sueño ─────────────────────────
        hobby_info = ""
        if HAS_PROGRAM_CREATOR:
            try:
                import random as _rand
                # 40% de probabilidad de programar durante el sueño
                # (el otro 60% lo dedicamos a hipótesis y otras actividades)
                creative_choice = _rand.choices(
                    ["program", "other"],
                    weights=[0.4, 0.6],
                )[0]

                if creative_choice == "program":
                    hobby_result = maybe_run_hobby(
                        cognia_instance=self,
                        idle_seconds=60.0,    # Siempre cumple el mínimo durante sleep()
                        min_idle=60.0,
                        probability=1.0,      # Ya decidimos arriba, ejecutar siempre
                        storage_dir=None,
                    )
                    if hobby_result and hobby_result.stored > 0:
                        hobby_info = f"\\n   Programas hobby:  +{hobby_result.stored} guardados"
                    elif hobby_result:
                        hobby_info = f"\\n   Programas hobby:  {hobby_result.attempted} intentos, ninguno guardado"
            except Exception:
                pass
'''

# ==============================================================================
# MODIFICACIÓN 4 — Añadir al return del método sleep()
# ==============================================================================
# En el return final de sleep(), añadir `+ hobby_info` al final del string:
#
# ANTES:
#   return (f"😴 CICLO DE SUEÑO v3 completado ({duration_ms}ms):\\n"
#           ...
#           f"   Hipótesis generadas: {hipotesis_n}"
#           + extras)
#
# DESPUÉS:
#   return (f"😴 CICLO DE SUEÑO v3 completado ({duration_ms}ms):\\n"
#           ...
#           f"   Hipótesis generadas: {hipotesis_n}"
#           + extras + hobby_info)   # <── añadir hobby_info aquí

PATCH_4_RETURN = '''
# En la línea del return de sleep(), cambiar:
#   + extras)
# por:
#   + extras + hobby_info)
'''

# ==============================================================================
# MODIFICACIÓN 5 (opcional) — Comando CLI para ver la biblioteca
# ==============================================================================
# Si Cognia tiene una CLI REPL, se puede añadir un comando:
# Ubicación: En la función repl() o en el método que maneja comandos de usuario.

PATCH_5_CLI = '''
    elif cmd == "programs" or cmd == "library":
        if HAS_PROGRAM_CREATOR:
            print(show_library())
        else:
            print("Módulo de programación hobby no disponible.")

    elif cmd == "program_stats":
        if HAS_PROGRAM_CREATOR:
            stats = get_session_stats()
            print(f"Sesiones: {stats['sessions_run']}")
            print(f"Intentos: {stats['programs_attempted']}")
            print(f"Guardados: {stats['programs_stored']}")
            print(f"Última sesión: {stats['last_run']}")
        else:
            print("Módulo de programación hobby no disponible.")
'''

# ==============================================================================
# RESUMEN
# ==============================================================================

SUMMARY = """
RESUMEN DE INTEGRACIÓN
======================

Archivos modificados:
  • cognia_v3.py  (5 cambios mínimos, todos aditivos, ninguno modifica código existente)

Archivos nuevos:
  • cognia/program_creator/__init__.py
  • cognia/program_creator/generator.py
  • cognia/program_creator/sandbox_runner.py
  • cognia/program_creator/evaluator.py
  • cognia/program_creator/storage.py
  • cognia/program_creator/program_creator.py
  • cognia/generated_programs/  (directorio, se crea automáticamente)

Comportamiento en producción:
  • Durante sleep(), Cognia tiene 40% de probabilidad de generar un programa
  • Los programas se ejecutan en subproceso aislado (timeout 5s)
  • Solo se guardan programas con score >= 5.0/10
  • Los programas se guardan en cognia/generated_programs/<nombre>/
  • El módulo nunca modifica working_memory, episodic_memory, semantic_memory ni KG

Para probar sin Cognia:
  python -m cognia.program_creator.program_creator
"""

if __name__ == "__main__":
    print(SUMMARY)
