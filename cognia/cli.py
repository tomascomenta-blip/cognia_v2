"""
cognia/cli.py
==============
Interfaz de línea de comandos (REPL) para Cognia v3.
"""

from .cognia import Cognia
from .config import HAS_RESEARCH_ENGINE, HAS_PROGRAM_CREATOR

HELP_TEXT = """
╔════════════════════════════════════════════════════════════════╗
║              COGNIA v3 – Comandos disponibles                 ║
╠════════════════════════════════════════════════════════════════╣
║  HEREDADOS DE v2:                                             ║
║  observar <texto>               Observar sin etiqueta        ║
║  aprender <texto> | <label>     Enseñar con etiqueta         ║
║  corregir <obs> | <mal> | <bien> Corregir error              ║
║  hipotesis <A> | <B>            Generar hipótesis            ║
║  yo                             Introspección completa       ║
║  conceptos                      Listar conceptos             ║
║  dormir                         Consolidación tipo sueño     ║
║  repasar                        Ver episodios para repasar   ║
║  contradicciones                Ver contradicciones          ║
║  explicar <texto>               Autoexplicación              ║
║  olvido                         Ciclo de olvido              ║
╠════════════════════════════════════════════════════════════════╣
║  NUEVOS EN v3:                                                ║
║  grafo <concepto>               Ver knowledge graph          ║
║  hecho <subj> | <pred> | <obj>  Agregar hecho al grafo       ║
║  objetivos                      Ver objetivos cognitivos     ║
║  predecir <concepto>            Ver predicciones temporales  ║
║  inferir <concepto>             Inferencias sobre concepto   ║
╠════════════════════════════════════════════════════════════════╣
║  FASE 4 – Seguridad:                                          ║
║  desbloquear <pass>             Desbloquear sistema          ║
║  bloquear                       Bloquear sistema             ║
║  seguridad                      Estado de seguridad         ║
╠════════════════════════════════════════════════════════════════╣
║  FASE 5 – Escalado:                                           ║
║  escalar                        Ver nivel de escala actual   ║
╠════════════════════════════════════════════════════════════════╣
║  FASE 6 – Personalización:                                    ║
║  usuarios                       Listar perfiles de usuario   ║
║  usuario <id>                   Cambiar usuario activo       ║
║  estilo_info                    Ver estilo de aprendizaje    ║
║  indice_personal                Ver índice personal          ║
║  indice_add <concepto>          Añadir concepto al índice    ║
╠════════════════════════════════════════════════════════════════╣
║  ayuda  /  salir                                              ║
╚════════════════════════════════════════════════════════════════╝
"""


def repl():
    ai = Cognia()
    print(HELP_TEXT)

    while True:
        try:
            raw = input("Cognia v3> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nHasta luego.")
            break

        if not raw:
            continue

        if raw == "salir":
            print("Hasta luego.")
            break
        elif raw == "ayuda":
            print(HELP_TEXT)
        elif raw == "yo":
            print(ai.introspect())
        elif raw == "conceptos":
            print(ai.list_concepts())
        elif raw == "olvido":
            print(ai.forget_cycle())
        elif raw == "dormir":
            print(ai.sleep())
        elif raw == "repasar":
            print(ai.review_due())
        elif raw == "contradicciones":
            print(ai.show_contradictions())
        elif raw == "objetivos":
            print(ai.show_goals())
        elif raw in ("research", "investigaciones"):
            if HAS_RESEARCH_ENGINE:
                from cognia.research_engine import show_research_history
                print(show_research_history(ai.db))
            else:
                print("⚠️  Módulo de investigación no disponible.")
        elif raw in ("programs", "library", "biblioteca"):
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import show_library
                print(show_library())
            else:
                print("⚠️  Módulo de programación hobby no disponible.")
        elif raw == "program_stats":
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import get_session_stats
                stats = get_session_stats()
                print(f"Sesiones:    {stats['sessions_run']}")
                print(f"Intentos:    {stats['programs_attempted']}")
                print(f"Guardados:   {stats['programs_stored']}")
                print(f"Última vez:  {stats['last_run']}")
            else:
                print("⚠️  Módulo de programación hobby no disponible.")
        elif raw.startswith("repasar "):
            parts = raw[8:].split()
            try:
                ep_id = int(parts[0])
                correcto = len(parts) < 2 or parts[1].lower() in ("correcto", "si", "sí", "yes")
                print(ai.mark_review(ep_id, correcto))
            except Exception:
                print("Uso: repasar <id> correcto|incorrecto")
        elif raw.startswith("aprender ") and "|" in raw:
            partes = raw[9:].split("|", 1)
            print(ai.learn(partes[0].strip(), partes[1].strip()))
        elif raw.startswith("observar "):
            print(ai.process(raw[9:].strip()))
        elif raw.startswith("corregir ") and raw.count("|") >= 2:
            partes = raw[9:].split("|")
            print(ai.correct(partes[0].strip(), partes[1].strip(), partes[2].strip()))
        elif raw.startswith("hipotesis ") and "|" in raw:
            partes = raw[10:].split("|", 1)
            print(ai.generate_hypothesis(partes[0].strip(), partes[1].strip()))
        elif raw.startswith("explicar "):
            print(ai.explain(raw[9:].strip()))
        elif raw.startswith("grafo "):
            print(ai.show_graph(raw[6:].strip()))
        elif raw.startswith("hecho ") and raw.count("|") >= 2:
            partes = raw[6:].split("|")
            print(ai.add_fact(partes[0].strip(), partes[1].strip(), partes[2].strip()))
        elif raw.startswith("predecir "):
            print(ai.predict_next(raw[9:].strip()))
        elif raw.startswith("inferir "):
            print(ai.infer_about(raw[8:].strip()))
        elif raw.startswith("narrativa "):
            print(ai.get_narrative(raw[9:].strip()))
        elif raw.startswith("mesh_iniciar"):
            parts = raw.split()
            port = int(parts[1]) if len(parts) > 1 else 7474
            print(ai.start_mesh(port))
        elif raw.startswith("mesh_peer "):
            print(ai.connect_mesh_peer(raw[10:].strip()))
        elif raw.startswith("mesh_publicar ") and raw.count("|") >= 2:
            partes = raw[14:].split("|")
            triple = [{"subject":   partes[0].strip(),
                       "predicate": partes[1].strip(),
                       "object":    partes[2].strip()}]
            print(ai.publish_knowledge(triple))
        elif raw == "mesh_estado":
            print(ai.mesh_status())
        # Fase 4: Seguridad
        elif raw == "seguridad":
            print(ai.security_status())
        elif raw == "bloquear":
            print(ai.lock_security())
        elif raw.startswith("desbloquear "):
            passphrase = raw[len("desbloquear "):].strip()
            if passphrase:
                print(ai.unlock_security(passphrase))
            else:
                print("Uso: desbloquear <passphrase>")
        # Fase 5: Escalado dinamico
        elif raw == "escalar":
            try:
                from cognia.scale_manager import get_scale_manager
                sm = get_scale_manager()
                st = sm.status()
                print(f"\n Nivel {st['level']}: {st['name']}")
                print(f"   Modelo recomendado : {st['model']}")
                print(f"   Timeout            : {st['timeout_s']}s")
                print(f"   RAM disponible     : {st['ram_gb']} GB")
                print(f"   Memorias activas   : {st['memories']}")
                print(f"   Peers activos      : {st['peers']}")
                print(f"   Historial niveles  : {st['hit_counts']}\n")
            except Exception as e:
                print(f"  ScaleManager no disponible: {e}")
        # Fase 6: Personalizacion profunda
        elif raw == "usuarios":
            try:
                from cognia.user_profile import list_users
                users = list_users(ai.db)
                if users:
                    for u in users:
                        print(f"  [{u['id']}] {u['name']}  (interacciones: {u.get('interactions', 0)})")
                else:
                    print("  No hay usuarios registrados.")
            except Exception as e:
                print(f"  No disponible: {e}")
        elif raw.startswith("usuario "):
            uid = raw[8:].strip()
            try:
                from cognia.user_profile import switch_user
                print(switch_user(ai, uid))
            except Exception as e:
                print(f"  No disponible: {e}")
        elif raw == "estilo_info":
            try:
                from cognia.learning.style_engine import StyleEngine
                se = StyleEngine(ai.db)
                info = se.get_style_info()
                print("\n  Estilo de aprendizaje actual:")
                for k, v in info.items():
                    print(f"    {k}: {v}")
                print()
            except Exception as e:
                print(f"  No disponible: {e}")
        elif raw == "indice_personal":
            try:
                from cognia.memory.personal_index import PersonalIndex
                pi = PersonalIndex(ai.db)
                conceptos = pi.list_concepts()
                if conceptos:
                    print("\n  Indice personal:")
                    for c in conceptos:
                        print(f"    - {c}")
                    print()
                else:
                    print("  Indice personal vacio. Usa: indice_add <concepto>")
            except Exception as e:
                print(f"  No disponible: {e}")
        elif raw.startswith("indice_add "):
            concepto = raw[11:].strip()
            if concepto:
                try:
                    from cognia.memory.personal_index import PersonalIndex
                    pi = PersonalIndex(ai.db)
                    print(pi.add_concept(concepto))
                except Exception as e:
                    print(f"  No disponible: {e}")
            else:
                print("Uso: indice_add <concepto>")
        else:
            try:
                from respuestas_articuladas import responder_articulado
                resultado = responder_articulado(ai, raw)
                if "error" in resultado:
                    print(f"Error: {resultado['error']}")
                else:
                    print(f"\n{resultado['response']}\n")
                    stage = resultado.get('stage', '')
                    if stage:
                        print(f"[stage: {stage}]")
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    repl()
