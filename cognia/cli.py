"""
cognia/cli.py
==============
Interfaz de lÃ­nea de comandos (REPL) para Cognia v3.
"""

from .cognia import Cognia
from .config import HAS_RESEARCH_ENGINE, HAS_PROGRAM_CREATOR

HELP_TEXT = """
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘              COGNIA v3 â€” Comandos disponibles                 â•‘
â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£
â•‘  HEREDADOS DE v2:                                             â•‘
â•‘  observar <texto>               Observar sin etiqueta        â•‘
â•‘  aprender <texto> | <label>     EnseÃ±ar con etiqueta         â•‘
â•‘  corregir <obs> | <mal> | <bien> Corregir error              â•‘
â•‘  hipotesis <A> | <B>            Generar hipÃ³tesis            â•‘
â•‘  yo                             IntrospecciÃ³n completa       â•‘
â•‘  conceptos                      Listar conceptos             â•‘
â•‘  dormir                         ConsolidaciÃ³n tipo sueÃ±o     â•‘
â•‘  repasar                        Ver episodios para repasar   â•‘
â•‘  contradicciones                Ver contradicciones          â•‘
â•‘  explicar <texto>               AutoexplicaciÃ³n              â•‘
â•‘  olvido                         Ciclo de olvido              â•‘
â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£
â•‘  NUEVOS EN v3:                                                â•‘
â•‘  grafo <concepto>               Ver knowledge graph          â•‘
â•‘  hecho <subj> | <pred> | <obj>  Agregar hecho al grafo       â•‘
â•‘  objetivos                      Ver objetivos cognitivos     â•‘
â•‘  predecir <concepto>            Ver predicciones temporales  â•‘
â•‘  inferir <concepto>             Inferencias sobre concepto   â•‘
â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£
â•‘  ayuda  /  salir                                              â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
                print("âš ï¸  MÃ³dulo de investigaciÃ³n no disponible.")
        elif raw in ("programs", "library", "biblioteca"):
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import show_library
                print(show_library())
            else:
                print("âš ï¸  MÃ³dulo de programaciÃ³n hobby no disponible.")
        elif raw == "program_stats":
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import get_session_stats
                stats = get_session_stats()
                print(f"Sesiones:    {stats['sessions_run']}")
                print(f"Intentos:    {stats['programs_attempted']}")
                print(f"Guardados:   {stats['programs_stored']}")
                print(f"Ãšltima vez:  {stats['last_run']}")
            else:
                print("âš ï¸  MÃ³dulo de programaciÃ³n hobby no disponible.")
        elif raw.startswith("repasar "):
            parts = raw[8:].split()
            try:
                ep_id = int(parts[0])
                correcto = len(parts) < 2 or parts[1].lower() in ("correcto", "si", "sÃ­", "yes")
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