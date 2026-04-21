"""
cognia_idle.py — Daemon de inactividad para Cognia v3
=====================================================
Corre Cognia en la terminal y la deja "vivir" sola:

  • Si llevas N segundos sin escribir nada → Cognia se duerme automáticamente
  • Durante el sueño puede crear programas (hobby) e investigar preguntas pendientes
  • Al despertar te muestra el resumen de lo que hizo
  • Tú sigues hablando con ella cuando quieras

USO:
    python cognia_idle.py                  # con defaults
    python cognia_idle.py --idle 120       # dormir tras 2 minutos de inactividad
    python cognia_idle.py --idle 60 --no-color

TECLAS ESPECIALES en el prompt:
    Enter vacío          → nada, Cognia sigue esperando
    Ctrl+C / "salir"     → salir limpio
    "estado"             → ver estado interno de Cognia
    "dormir"             → forzar ciclo de sueño ahora mismo
    "programas"          → ver biblioteca de programas generados
    "investigaciones"    → ver historial de investigaciones
"""

import argparse
import sys
import time
import threading
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Colores ANSI (se pueden desactivar con --no-color)
# ─────────────────────────────────────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    CYAN   = "\033[36m"
    YELLOW = "\033[33m"
    GREEN  = "\033[32m"
    BLUE   = "\033[34m"
    MAGENTA= "\033[35m"
    RED    = "\033[31m"

USE_COLOR = True

def col(code, text):
    return f"{code}{text}{C.RESET}" if USE_COLOR else text

def ts():
    """Timestamp corto para logs."""
    return datetime.now().strftime("%H:%M:%S")

# ─────────────────────────────────────────────────────────────────────────────
# Importar Cognia y módulos opcionales
# ─────────────────────────────────────────────────────────────────────────────

print("Cargando Cognia v3...", end=" ", flush=True)
try:
    from cognia_v3 import Cognia
    print("✅")
except ImportError as e:
    print(f"\n❌ No se pudo importar cognia_v3.py: {e}")
    print("   Asegúrate de ejecutar este script desde el mismo directorio.")
    sys.exit(1)

# Módulo de investigación autónoma (opcional)
try:
    from cognia.research_engine import run_research_session, format_sleep_summary
    HAS_RESEARCH = True
    print("✅ ResearchEngine cargado")
except ImportError:
    HAS_RESEARCH = False

# Módulo de programación hobby (opcional)
try:
    from cognia.program_creator import maybe_run_hobby, show_library, get_session_stats
    HAS_HOBBY = True
    print("✅ ProgramCreator cargado")
except ImportError:
    HAS_HOBBY = False

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_IDLE_SEC   = 90      # segundos de inactividad antes de dormir
SLEEP_CHECK_SEC    = 5       # con qué frecuencia chequeamos si hay que dormir
HOBBY_PROBABILITY  = 0.4     # probabilidad de crear un programa durante el sueño
MAX_SLEEP_RESEARCH = 3       # preguntas a investigar por ciclo de sueño

# ─────────────────────────────────────────────────────────────────────────────
# Estado compartido entre el hilo principal (input) y el watchdog (idle)
# ─────────────────────────────────────────────────────────────────────────────

class IdleState:
    def __init__(self):
        self.last_activity        = time.time()
        self.last_sleep_time      = 0.0   # timestamp del último ciclo de sueño
        self.last_hobby_time      = 0.0   # timestamp del último programa generado
        self.activity_since_sleep = True  # ¿hubo actividad desde el último sueño?
        self.is_sleeping          = False
        self.is_hobbying          = False  # generando programa ahora mismo
        self.sleep_count          = 0
        self.lock                 = threading.Lock()

    def touch(self):
        """Registrar actividad del usuario."""
        with self.lock:
            self.last_activity        = time.time()
            self.activity_since_sleep = True

    def idle_seconds(self) -> float:
        with self.lock:
            return time.time() - self.last_activity

    def should_sleep(self, idle_threshold: float) -> tuple:
        """
        Decide si debe dormir. Retorna (bool, motivo).
        - Si no hubo actividad nueva desde el último sueño, espera 30 min
          antes del siguiente (ciclo de mantenimiento).
        - Si hubo actividad nueva, duerme normalmente al cumplir idle_threshold.
        """
        with self.lock:
            idle = time.time() - self.last_activity
            if idle < idle_threshold:
                return False, ""
            if self.is_sleeping:
                return False, ""
            if not self.activity_since_sleep:
                mins_since = (time.time() - self.last_sleep_time) / 60
                if mins_since < 30:
                    return False, f"sin actividad nueva (mantenimiento en {30 - mins_since:.0f} min)"
                return True, "🔧 mantenimiento periódico"
            return True, "✨ consolidando actividad nueva"

    def mark_sleeping(self):
        with self.lock:
            self.is_sleeping          = True
            self.sleep_count         += 1
            self.last_sleep_time      = time.time()
            self.activity_since_sleep = False

    def mark_awake(self):
        with self.lock:
            self.is_sleeping   = False
            self.last_activity = time.time()

    def sleeping(self) -> bool:
        with self.lock:
            return self.is_sleeping

    def mark_hobbying(self):
        with self.lock:
            self.is_hobbying    = True
            self.last_hobby_time = time.time()

    def mark_hobby_done(self):
        with self.lock:
            self.is_hobbying = False

    def should_hobby(self, idle_threshold: float) -> bool:
        """Programa si lleva idle_threshold*2 sin hacer nada Y sin hobby reciente."""
        with self.lock:
            if self.is_sleeping or self.is_hobbying:
                return False
            idle = time.time() - self.last_activity
            if idle < idle_threshold * 2:
                return False
            # Esperar al menos 10 minutos entre programas
            mins_since_hobby = (time.time() - self.last_hobby_time) / 60
            return mins_since_hobby >= 10

# ─────────────────────────────────────────────────────────────────────────────
# Ciclo de sueño enriquecido (llama al sleep() de Cognia + módulos opcionales)
# ─────────────────────────────────────────────────────────────────────────────

def run_sleep_cycle(cognia: Cognia, idle_state: IdleState) -> str:
    """
    Ejecuta el ciclo de sueño completo:
      1. sleep() nativo de Cognia
      2. Investigación autónoma (si HAS_RESEARCH)
      3. Hobby de programación (si HAS_HOBBY, probabilístico)

    Retorna el texto resumen para mostrar al usuario.
    """
    idle_state.mark_sleeping()
    n = idle_state.sleep_count
    print(f"\n{col(C.BLUE, f'[{ts()}]')} {col(C.MAGENTA, f'💤 Ciclo de sueño #{n} iniciado...')}")

    summary_parts = []

    # ── 1. Sleep nativo de Cognia ──────────────────────────────────────
    try:
        sleep_result = cognia.sleep()
        summary_parts.append(sleep_result)
    except Exception as e:
        summary_parts.append(f"⚠️  Error en sleep(): {e}")

    # ── 2. Investigación autónoma ──────────────────────────────────────
    if HAS_RESEARCH:
        try:
            print(f"   {col(C.CYAN, '🔬 Investigando preguntas pendientes...')}")
            session = run_research_session(
                cognia_instance=cognia,
                db_path=cognia.db,
                max_questions=MAX_SLEEP_RESEARCH,
                verbose=False,
            )
            research_line = format_sleep_summary(session)
            if research_line:
                summary_parts.append(research_line)
        except Exception as e:
            pass  # Nunca romper el ciclo de sueño

    # ── 3. Hobby de programación ───────────────────────────────────────
    if HAS_HOBBY:
        try:
            import random
            if random.random() < HOBBY_PROBABILITY:
                print(f"   {col(C.CYAN, '🎨 Generando programa hobby...')}")
                hobby_result = maybe_run_hobby(
                    cognia_instance=cognia,
                    idle_seconds=999,     # ya sabemos que está idle
                    min_idle=0,
                    probability=1.0,
                    storage_dir=None,
                )
                if hobby_result and hobby_result.stored > 0:
                    summary_parts.append(
                        f"\n   Programas hobby:  +{hobby_result.stored} guardados"
                    )
                elif hobby_result:
                    summary_parts.append(
                        f"\n   Programas hobby:  {hobby_result.attempted} intento(s), ninguno guardado"
                    )
        except Exception as e:
            pass  # Nunca romper el ciclo de sueño

    idle_state.mark_awake()

    full_summary = "\n".join(str(p) for p in summary_parts if p)
    return full_summary



# ─────────────────────────────────────────────────────────────────────────────
# Ciclo de hobby autónomo (independiente del sueño)
# ─────────────────────────────────────────────────────────────────────────────

def run_hobby_cycle(cognia, idle_state: IdleState):
    """
    Corre cuando Cognia lleva mucho tiempo idle sin dormir.
    Genera un programa hobby de forma completamente autónoma.
    """
    if not HAS_HOBBY:
        return

    idle_state.mark_hobbying()
    print(f"\n{col(C.BLUE, f'[{ts()}]')} {col(C.MAGENTA, '🎨 Cognia se aburre — generando programa hobby...')}")

    try:
        from cognia.program_creator import show_library
        result = maybe_run_hobby(
            cognia_instance=cognia,
            idle_seconds=999,
            min_idle=0,
            probability=1.0,
            storage_dir=None,
        )
        if result and result.stored > 0:
            print(f"{col(C.GREEN, f'   ✅ Programa guardado: {result.programs[0].title} (score={result.programs[0].total_score:.1f})')}")
        elif result:
            print(f"{col(C.DIM, f'   🗑️  Programa descartado (score insuficiente)')}")
    except Exception as e:
        print(f"{col(C.DIM, f'   ⚠️  Hobby error: {e}')}")
    finally:
        idle_state.mark_hobby_done()
        print(f"\n{col(C.CYAN, 'Cognia v3')}> ", end="", flush=True)

# ─────────────────────────────────────────────────────────────────────────────
# Watchdog: hilo que monitorea inactividad y dispara el sueño
# ─────────────────────────────────────────────────────────────────────────────

def idle_watchdog(cognia: Cognia, idle_state: IdleState,
                  idle_threshold: float, stop_event: threading.Event):
    """
    Hilo daemon que revisa cada SLEEP_CHECK_SEC segundos si
    el usuario lleva idle_threshold segundos inactivo.
    Si es así, dispara el ciclo de sueño.
    """
    while not stop_event.is_set():
        time.sleep(SLEEP_CHECK_SEC)

        if stop_event.is_set():
            break

        if idle_state.sleeping() or idle_state.is_hobbying:
            continue  # ocupada, esperar

        do_sleep, motivo = idle_state.should_sleep(idle_threshold)
        idle = idle_state.idle_seconds()
        remaining = idle_threshold - idle

        if do_sleep:
            print(f"\n{col(C.DIM, f'[{ts()}] {idle:.0f}s idle — {motivo}')}") 
            summary = run_sleep_cycle(cognia, idle_state)
            print(f"\n{col(C.GREEN, summary)}")
            print(f"\n{col(C.CYAN, 'Cognia v3')}> ", end="", flush=True)

        elif HAS_HOBBY and idle_state.should_hobby(idle_threshold):
            # Cognia lleva mucho tiempo sin hacer nada — que programe
            t = threading.Thread(
                target=run_hobby_cycle,
                args=(cognia, idle_state),
                daemon=True,
                name="hobby-thread",
            )
            t.start()

        elif motivo:
            print(f"\r{col(C.DIM, f'[{motivo}]')}  ", end="", flush=True)

        elif remaining <= 15 and idle > 10:
            print(f"\r{col(C.DIM, f'[idle {idle:.0f}s / {idle_threshold:.0f}s — dormirá en {remaining:.0f}s]')}  ", end="", flush=True)



# ─────────────────────────────────────────────────────────────────────────────
# Comandos especiales de la CLI del daemon
# ─────────────────────────────────────────────────────────────────────────────

def handle_special_command(cmd: str, cognia: Cognia, idle_state: IdleState) -> bool:
    """
    Maneja comandos especiales del daemon (no de Cognia).
    Retorna True si fue un comando especial, False si debe pasarse a Cognia.
    """
    cmd = cmd.strip().lower()

    if cmd == "estado":
        print(cognia.introspect())
        return True

    elif cmd == "dormir":
        print(col(C.YELLOW, "Forzando ciclo de sueño..."))
        summary = run_sleep_cycle(cognia, idle_state)
        print(col(C.GREEN, summary))
        return True

    elif cmd == "programas" or cmd == "library":
        if HAS_HOBBY:
            print(show_library())
        else:
            print("⚠️  Módulo de programación hobby no disponible.")
        return True

    elif cmd == "investigaciones":
        if HAS_RESEARCH:
            from cognia.research_engine import show_research_history
            print(show_research_history(cognia.db))
        else:
            print("⚠️  Módulo de investigación no disponible.")
        return True

    elif cmd == "ayuda" or cmd == "help":
        print(HELP_TEXT)
        return True

    elif cmd in ("salir", "exit", "quit"):
        raise SystemExit(0)

    return False


HELP_TEXT = f"""
{col(C.BOLD, '╔══════════════════════════════════════════════════════════╗')}
{col(C.BOLD, '║             COGNIA v3  —  Modo Autónomo                  ║')}
{col(C.BOLD, '╠══════════════════════════════════════════════════════════╣')}
{col(C.BOLD, '║  Comandos del daemon:')}
{col(C.BOLD, '║')}  estado          → Introspección interna de Cognia
{col(C.BOLD, '║')}  dormir          → Forzar ciclo de sueño ahora
{col(C.BOLD, '║')}  programas       → Ver biblioteca de programas hobby
{col(C.BOLD, '║')}  investigaciones → Ver historial de investigación
{col(C.BOLD, '║')}  ayuda           → Esta ayuda
{col(C.BOLD, '║')}  salir           → Salir limpiamente
{col(C.BOLD, '╠══════════════════════════════════════════════════════════╣')}
{col(C.BOLD, '║  Comandos de Cognia (como siempre):')}
{col(C.BOLD, '║')}  <cualquier texto>  → Cognia lo procesa
{col(C.BOLD, '║')}  aprender X | Y     → Enseñarle algo
{col(C.BOLD, '║')}  observar X         → Procesar observación
{col(C.BOLD, '║')}  conceptos          → Listar conceptos aprendidos
{col(C.BOLD, '║')}  contradicciones    → Ver contradicciones detectadas
{col(C.BOLD, '║')}  objetivos          → Ver objetivos cognitivos
{col(C.BOLD, '╚══════════════════════════════════════════════════════════╝')}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Loop principal
# ─────────────────────────────────────────────────────────────────────────────

def main(idle_threshold: float = DEFAULT_IDLE_SEC):
    global USE_COLOR

    cognia     = Cognia()
    idle_state = IdleState()
    stop_event = threading.Event()

    print(HELP_TEXT)
    print(col(C.DIM, f"Cognia se dormirá automáticamente tras "
                     f"{idle_threshold:.0f}s de inactividad."))
    print()

    # Lanzar watchdog en hilo daemon
    watchdog_thread = threading.Thread(
        target=idle_watchdog,
        args=(cognia, idle_state, idle_threshold, stop_event),
        daemon=True,
        name="idle-watchdog",
    )
    watchdog_thread.start()

    # ── Loop de input del usuario ──────────────────────────────────────
    try:
        while True:
            try:
                raw = input(f"{col(C.CYAN, 'Cognia v3')}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{col(C.YELLOW, 'Hasta luego.')}")
                break

            if not raw:
                continue

            # Registrar actividad para resetear el contador idle
            idle_state.touch()

            # Comandos especiales del daemon
            if handle_special_command(raw, cognia, idle_state):
                continue

            # Pasar a Cognia (misma lógica que en repl())
            try:
                if raw.startswith("aprender ") and "|" in raw:
                    partes = raw[9:].split("|", 1)
                    print(cognia.learn(partes[0].strip(), partes[1].strip()))

                elif raw.startswith("observar "):
                    print(cognia.process(raw[9:].strip()))

                elif raw.startswith("corregir ") and raw.count("|") >= 2:
                    partes = raw[9:].split("|")
                    print(cognia.correct(partes[0].strip(), partes[1].strip(), partes[2].strip()))

                elif raw.startswith("hipotesis ") and "|" in raw:
                    partes = raw[10:].split("|", 1)
                    print(cognia.generate_hypothesis(partes[0].strip(), partes[1].strip()))

                elif raw.startswith("explicar "):
                    print(cognia.explain(raw[9:].strip()))

                elif raw.startswith("grafo "):
                    print(cognia.show_graph(raw[6:].strip()))

                elif raw.startswith("hecho ") and raw.count("|") >= 2:
                    partes = raw[6:].split("|")
                    print(cognia.add_fact(partes[0].strip(), partes[1].strip(), partes[2].strip()))

                elif raw.startswith("predecir "):
                    print(cognia.predict_next(raw[9:].strip()))

                elif raw.startswith("inferir "):
                    print(cognia.infer_about(raw[8:].strip()))

                elif raw == "conceptos":
                    print(cognia.list_concepts())

                elif raw == "contradicciones":
                    print(cognia.show_contradictions())

                elif raw == "objetivos":
                    print(cognia.show_goals())

                elif raw == "olvido":
                    print(cognia.forget_cycle())

                elif raw == "repasar":
                    print(cognia.review_due())

                elif raw == "yo":
                    print(cognia.introspect())

                else:
                    # Procesamiento general (chat)
                    print(cognia.process(raw))

            except Exception as e:
                print(f"{col(C.RED, f'Error procesando entrada: {e}')}")

    finally:
        stop_event.set()
        print(col(C.DIM, "Watchdog detenido. ¡Hasta luego!"))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cognia v3 con ciclos de sueño autónomos."
    )
    parser.add_argument(
        "--idle", "-i",
        type=float,
        default=DEFAULT_IDLE_SEC,
        metavar="SEGUNDOS",
        help=f"Segundos de inactividad antes de dormir (default: {DEFAULT_IDLE_SEC})",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Desactivar colores ANSI",
    )
    args = parser.parse_args()

    if args.no_color:
        USE_COLOR = False

    main(idle_threshold=args.idle)
