"""
paso6_parches.py — PASO 6: Parches de integración del motor de consolidación
=============================================================================
Aplica exactamente TRES cambios a cognia.py.

ARCHIVO: cognia.py

  PARCHE A — Importar ConsolidationEngine al inicio
  PARCHE B — Inicializar en __init__()
  PARCHE C — Integrar en sleep() y observe()

Instrucciones:
  Busca el bloque ANTES en cognia.py y reemplázalo por DESPUÉS.
  Cada parche es independiente: aplícalos en orden A → B → C.
  NO modifica ningún otro archivo.
"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE A — Import
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia.py
# Ubicación: justo después del bloque de import de feedback_engine

PATCH_A_ANTES = """\
        # ── PASO 5: FeedbackEngine (aprendizaje por feedback) ──────────
        try:
            from feedback_engine import get_feedback_engine
            self._feedback_engine = get_feedback_engine(db_path)
            print("✅ FeedbackEngine PASO 5 activo")
        except ImportError:
            self._feedback_engine = None"""

PATCH_A_DESPUES = """\
        # ── PASO 5: FeedbackEngine (aprendizaje por feedback) ──────────
        try:
            from feedback_engine import get_feedback_engine
            self._feedback_engine = get_feedback_engine(db_path)
            print("✅ FeedbackEngine PASO 5 activo")
        except ImportError:
            self._feedback_engine = None

        # ── PASO 6: ConsolidationEngine (consolidación y limpieza) ─────
        try:
            from consolidation_engine import get_consolidation_engine
            self._consolidation_engine = get_consolidation_engine(
                db_path,
                consolidation_interval=self.consolidation_interval,
            )
            print("✅ ConsolidationEngine PASO 6 activo")
        except ImportError:
            self._consolidation_engine = None"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE B — Integración en sleep()
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia.py
# Ubicación: dentro de sleep(), después del bloque de feedback decay

PATCH_B_ANTES = """\
        # ── PASO 5: Decay de feedback_weight ──────────────────────────
        feedback_info = ""
        if self._feedback_engine is not None:
            try:
                decay_result = self._feedback_engine.decay_weights()
                if decay_result.get("updated", 0) > 0:
                    feedback_info = f"\\n   Feedback decay:    {decay_result['updated']} pesos normalizados"
            except Exception:
                pass"""

PATCH_B_DESPUES = """\
        # ── PASO 5: Decay de feedback_weight ──────────────────────────
        feedback_info = ""
        if self._feedback_engine is not None:
            try:
                decay_result = self._feedback_engine.decay_weights()
                if decay_result.get("updated", 0) > 0:
                    feedback_info = f"\\n   Feedback decay:    {decay_result['updated']} pesos normalizados"
            except Exception:
                pass

        # ── PASO 6: Ciclo completo de consolidación ────────────────────
        consolidation6_info = ""
        if self._consolidation_engine is not None:
            try:
                c6 = self._consolidation_engine.run_full_cycle()
                parts = []
                if c6.purged:       parts.append(f"{c6.purged} eliminados")
                if c6.weakened:     parts.append(f"{c6.weakened} debilitados")
                if c6.consolidated: parts.append(f"{c6.consolidated} fusionados")
                if c6.reinforced:   parts.append(f"{c6.reinforced} reforzados")
                if c6.decayed:      parts.append(f"{c6.decayed} decay")
                if c6.sem_deduped:  parts.append(f"{c6.sem_deduped} sem.dedup")
                if parts:
                    consolidation6_info = f"\\n   Consolidación v6:  {', '.join(parts)} ({c6.elapsed_ms:.0f}ms)"
            except Exception:
                pass"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE C — Añadir consolidation6_info al return de sleep()
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia.py
# Ubicación: la línea return final de sleep()

PATCH_C_ANTES = """\
                + extras + research_info + hobby_info + engine_info + feedback_info + architect_info)"""

PATCH_C_DESPUES = """\
                + extras + research_info + hobby_info + engine_info + feedback_info
                + consolidation6_info + architect_info)"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE D — Integrar tick() en observe() (ciclo ligero automático)
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia.py
# Ubicación: el bloque _maintenance.tick al final de observe()

PATCH_D_ANTES = """\
        if self._maintenance:
            self._maintenance.tick(self.interaction_count)
        return result"""

PATCH_D_DESPUES = """\
        if self._maintenance:
            self._maintenance.tick(self.interaction_count)

        # PASO 6: ciclo ligero de consolidación (decay + weaken suave)
        if self._consolidation_engine is not None:
            try:
                self._consolidation_engine.tick(self.interaction_count)
            except Exception:
                pass

        return result"""


# ══════════════════════════════════════════════════════════════════════
# SCRIPT DE APLICACIÓN AUTOMÁTICA
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    import shutil
    from datetime import datetime

    # cognia.py vive dentro de la subcarpeta cognia/
    _candidates = [
        os.path.join("cognia", "cognia.py"),   # cognia_v2/cognia/cognia.py  ← caso normal
        "cognia.py",                            # por si acaso está en raíz
    ]
    TARGET = next((p for p in _candidates if os.path.exists(p)), None)
    if TARGET is None:
        print("[ERROR] No se encontró cognia/cognia.py ni cognia.py")
        print("Ejecutar desde cognia_v2 (el directorio que contiene la carpeta 'cognia').")
        raise SystemExit(1)

    TS = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP = TARGET + f".bak_paso6_{TS}"

    patches = [
        ("A — Import ConsolidationEngine",      PATCH_A_ANTES, PATCH_A_DESPUES),
        ("B — Integrar en sleep()",              PATCH_B_ANTES, PATCH_B_DESPUES),
        ("C — Añadir info al return de sleep()", PATCH_C_ANTES, PATCH_C_DESPUES),
        ("D — tick() en observe()",              PATCH_D_ANTES, PATCH_D_DESPUES),
    ]

    print(f"\n[INFO] Archivo objetivo: {TARGET}")

    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"\n{'='*60}")
    print("  COGNIA — Aplicando parches PASO 6")
    print(f"{'='*60}\n")

    all_ok = True
    for name, antes, despues in patches:
        if antes in content:
            print(f"  ✅ Parche {name}")
        else:
            print(f"  ⚠️  Parche {name} — bloque ANTES no encontrado (¿ya aplicado?)")
            all_ok = False

    print()
    resp = input("¿Aplicar parches? (s/n): ").strip().lower()
    if resp != "s":
        print("Cancelado.")
        raise SystemExit(0)

    shutil.copy2(TARGET, BACKUP)
    print(f"\n[OK] Backup: {BACKUP}")

    applied = 0
    for name, antes, despues in patches:
        if antes in content:
            content = content.replace(antes, despues, 1)
            applied += 1
            print(f"  ✅ Aplicado: {name}")
        else:
            print(f"  ⏭️  Saltado:  {name} (ya aplicado o no encontrado)")

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[OK] {applied}/{len(patches)} parches aplicados en {TARGET}")

    # Copiar consolidation_engine.py al mismo directorio que cognia.py
    engine_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "consolidation_engine.py")
    engine_dst = os.path.join(os.path.dirname(os.path.abspath(TARGET)), "consolidation_engine.py")
    if not os.path.exists(engine_src):
        engine_src = "consolidation_engine.py"
    if os.path.exists(engine_src):
        shutil.copy2(engine_src, engine_dst)
        print(f"[OK] consolidation_engine.py copiado → {engine_dst}")
    else:
        print(f"[AVISO] No se encontró consolidation_engine.py — cópialo manualmente a:")
        print(f"        {engine_dst}")

    print("\nReinicia web_app.py para activar el PASO 6.")
