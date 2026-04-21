"""
integration_patch_language_engine.py
=====================================
Guía de los cambios MÍNIMOS para integrar el Language Engine
en los archivos existentes SIN romper nada.

Solo 2 archivos se modifican:
  • respuestas_articuladas.py  (1 función nueva + patch en responder_articulado)
  • cognia_v3.py               (1 línea en sleep() para evolución de prompts)

Todo lo demás queda intacto.
"""

# ==============================================================================
# ARCHIVO 1: respuestas_articuladas.py
# ==============================================================================
#
# MODIFICACIÓN 1 — Añadir import al inicio del archivo
# Ubicación: junto a los otros imports, después de "import os, sys, json..."
# ──────────────────────────────────────────────────────────────────────────────

PATCH_RA_IMPORT = '''
# ── Language Engine híbrido (opcional pero recomendado) ───────────────────────
try:
    from language_engine import get_language_engine
    HAS_LANGUAGE_ENGINE = True
except ImportError:
    HAS_LANGUAGE_ENGINE = False
'''

# ==============================================================================
# MODIFICACIÓN 2 — Reemplazar el bloque de llamada a Ollama en responder_articulado()
#
# ANTES (líneas ~437-483):
#   try:
#       respuesta = llamar_ollama(
#           prompt,
#           tipo=tipo_pregunta,
#           ...
#       )
#       ...
#       return resultado
#   except Exception as e:
#       ...
#       return {"error": ...}
#
# DESPUÉS: añadir el bloque del engine ANTES del try de llamar_ollama
# ==============================================================================

PATCH_RA_RESPOND = '''
    # ── Language Engine: intentar responder sin LLM primero ───────────────────
    if HAS_LANGUAGE_ENGINE:
        try:
            engine = get_language_engine(ai)
            engine_result = engine.respond(
                cognia_instance    = ai,
                question           = pregunta,
                pre_built_context  = contexto,   # reutiliza el contexto ya construido
            )
            # Si no usó LLM o usó LLM con éxito → retornar directamente
            if engine_result.response and not engine_result.stage_used == "fallback":
                resultado = engine_result.to_dict()
                # Compatibilidad con el formato esperado por web_app.py
                resultado["response"]         = engine_result.response
                resultado["modelo"]           = engine_result.modelo or MODELO
                resultado["tipo_pregunta"]    = engine_result.tipo_pregunta or tipo_pregunta
                resultado["tiene_contexto"]   = engine_result.tiene_contexto
                resultado["episodios_usados"] = engine_result.episodios_usados
                resultado["info_suficiente"]  = engine_result.info_suficiente
                resultado["response_id"]      = engine_result.response_id
                resultado["suficiencia"]      = _suficiencia
                # Guardar en chat_history (igual que antes)
                try:
                    if hasattr(ai, "chat_history"):
                        ai.chat_history.log(
                            role="assistant",
                            content=engine_result.response[:500],
                            response_id=engine_result.response_id,
                            confidence=engine_result.confidence,
                        )
                except Exception:
                    pass
                # Guardar respuesta en working_mem (igual que antes)
                try:
                    from cognia_v3 import text_to_vector, analyze_emotion
                    _vec_r = text_to_vector(engine_result.response[:200])
                    if _vec_r:
                        ai.working_mem.add(
                            f"[Cognia]: {engine_result.response[:280]}",
                            None, _vec_r,
                            analyze_emotion(engine_result.response[:100]), 0.5
                        )
                except Exception:
                    pass
                return resultado
        except Exception as e:
            print(f"[Cognia LOG] LanguageEngine error: {e} — fallback a Ollama directo")
            # Si falla el engine, sigue el flujo normal de Ollama

    # ── Flujo original de Ollama (fallback si engine no disponible) ───────────
    # ... (código existente de llamar_ollama sin cambios)
'''

# ==============================================================================
# ARCHIVO 2: cognia_v3.py
# ==============================================================================
#
# MODIFICACIÓN 3 — Añadir evolución de prompts en sleep()
# Ubicación: al final del método sleep(), ANTES del return
# ──────────────────────────────────────────────────────────────────────────────

PATCH_V3_SLEEP = '''
        # ── Language Engine: evolución de prompts durante el sueño ───────────
        engine_info = ""
        try:
            if HAS_LANGUAGE_ENGINE:
                engine = get_language_engine(self)
                evolved = engine.run_prompt_evolution()
                if evolved:
                    engine_info = f"\\n   Prompts evolucionados: {len(evolved)}"
                # Limpiar caché de respuestas expiradas
                engine.cache.clear_expired()
        except Exception:
            pass
'''

# MODIFICACIÓN 4 — Añadir engine_info al return de sleep()
PATCH_V3_SLEEP_RETURN = '''
# En el return final de sleep(), añadir + engine_info:
#   + extras + engine_info)
# O si ya tienes research_info y hobby_info:
#   + extras + hobby_info + research_info + engine_info)
'''

# ==============================================================================
# MODIFICACIÓN 5 — Invalidar caché cuando Cognia aprende algo nuevo
# Ubicación: en observe(), dentro del bloque "MODO APRENDIZAJE"
# Después de: self.semantic.update_concept(...)
# ──────────────────────────────────────────────────────────────────────────────

PATCH_V3_LEARN = '''
            # Invalidar caché de respuestas del concepto aprendido
            try:
                if HAS_LANGUAGE_ENGINE:
                    get_language_engine(self).invalidate_concept(provided_label)
            except Exception:
                pass
'''

# ==============================================================================
# RESUMEN DE ARCHIVOS NUEVOS
# ==============================================================================

SUMMARY = """
ARCHIVOS NUEVOS (crear en el mismo directorio que cognia_v3.py):
  • language_engine.py         ← orquestador principal
  • symbolic_responder.py      ← respuestas sin LLM
  • response_cache.py          ← caché semántico
  • prompt_optimizer.py        ← compresión + evolución de prompts

ARCHIVOS MODIFICADOS (cambios mínimos):
  • respuestas_articuladas.py  ← 1 import + 1 bloque en responder_articulado()
  • cognia_v3.py               ← 2 líneas en sleep() + 1 línea en observe()

NUEVA TABLA EN SQLite (se crea automáticamente):
  • response_cache             ← caché de respuestas persistente
  • prompt_metrics             ← métricas para evolución de prompts

COMPORTAMIENTO EN PRODUCCIÓN:
  Si HAS_LANGUAGE_ENGINE = False → todo funciona igual que antes (Ollama directo)
  Si HAS_LANGUAGE_ENGINE = True  → pipeline de 5 etapas, Ollama solo cuando necesario

REDUCCIÓN ESPERADA DE LLAMADAS A OLLAMA:
  • Sesión con temas conocidos:    60-80% menos llamadas LLM
  • Sesión con temas nuevos:       20-35% menos llamadas LLM
  • Bajo carga crítica (CPU>85%):  100% sin LLM (respuesta simbólica forzada)
"""

if __name__ == "__main__":
    print(SUMMARY)
