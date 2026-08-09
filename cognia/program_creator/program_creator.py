"""
program_creator.py — Orquestador del módulo de programación hobby de Cognia.

Este es el punto de entrada principal del módulo.
Implementa el loop completo:

  Idea → Generación → Ejecución en sandbox → Evaluación → Almacenamiento

La función principal es run_program_hobby(), que puede ser llamada desde:
  1. El ciclo de sueño de Cognia (sleep())
  2. Un loop idle externo
  3. Manualmente desde la CLI para pruebas

PRINCIPIO DE AISLAMIENTO:
  Este módulo puede LEER conceptos de Cognia (solo lectura) para inspiración,
  pero NUNCA modifica working_memory, episodic_memory, semantic_memory ni knowledge_graph.

  El único "write back" opcional es registrar metadata del programa como
  un evento log externo — nunca como un episodio de aprendizaje.
"""

import hashlib
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..disciplina    import DIR_ESTADO, Disyuntor, huella_de_texto
from .generator      import (generate_program, reparar_python, reparar_web,
                             GeneratedProgram)
from .sandbox_runner import run_in_sandbox, revisar_html, ExecutionResult
from .vista_navegador import revisar_en_navegador, InformeVisual
from .evaluator      import evaluate_program, EvaluationResult
from .storage        import (save_program, StoredProgramMeta, format_library_summary,
                             get_program_count, DEFAULT_STORAGE_DIR)

# ── Configuración ──────────────────────────────────────────────────────────────

# Pausa entre generaciones (segundos) para no saturar el LLM
INTER_GENERATION_PAUSE = 2.0

# Número máximo de intentos por sesión de hobby
MAX_ATTEMPTS_PER_SESSION = 3

# Cuantas veces se le devuelve el error al modelo antes de rendirse. Umbral de
# Aider (max_reflections=3), el mismo que cita cognia/disciplina/. El disyuntor
# puede cortar antes si detecta que los parches no mueven el sintoma.
MAX_REPARACIONES = 3

# Cuantas veces se vuelve a intentar la MISMA idea desde cero cuando ninguna
# generacion supera las compuertas. Tecnica que Cognia encontro investigando
# (snwfdhmp/awesome-ralph): insistir hasta cumplir la especificacion. El
# disyuntor puede cortar antes si insistir deja de aportar.
MAX_RONDAS_INSISTIENDO = 4

# Threshold mínimo para guardar (espejo del definido en evaluator.py)
STORE_THRESHOLD = 5.0

# Ruta del JSONL append-only del disyuntor, en .disciplina/ del cwd (mismo
# criterio que cognia/disciplina/__main__.py). Sin ruta_log el corte no dejaba
# NINGUN rastro y la calibracion del modo sombra (plan INVESTIGACION_Y_ANTIRUIDO)
# no podia contar los disparos de estos lazos.
def _ruta_disyuntor(tarea: str) -> Path:
    h = hashlib.sha1(tarea.encode("utf-8")).hexdigest()[:10]
    return DIR_ESTADO / f"pc_{h}.jsonl"


# Estadísticas de sesión para monitoreo
_session_stats = {
    "sessions_run":       0,
    "programs_attempted": 0,
    "programs_stored":    0,
    "last_run":           None,
}


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class HobbySessionResult:
    """Resultado de una sesión de programación hobby."""
    attempted:   int
    successful:  int           # Programas que pasaron el evaluador
    stored:      int           # Programas que se guardaron en disco
    programs:    list          # Lista de StoredProgramMeta de los guardados
    duration_sec: float
    timestamp:   str


# ── Lectura de conocimiento (solo lectura) ─────────────────────────────────────

def _get_seed_concepts(cognia_instance=None) -> list[str]:
    """
    Extrae conceptos del grafo de conocimiento de Cognia para inspirar
    los programas generados. SOLO LECTURA — nunca modifica nada.

    Args:
        cognia_instance: Instancia de Cognia (opcional).
                         Si no se pasa, se devuelve lista vacía.

    Returns:
        Lista de strings con nombres de conceptos.
    """
    if cognia_instance is None:
        return []
    try:
        # Leemos desde semantic memory — método list_all() es solo lectura
        concepts = cognia_instance.semantic.list_all()
        # Filtramos conceptos con suficiente confianza y soporte
        good = [
            c["concept"] for c in concepts
            if c.get("confidence", 0) >= 0.5
            and c.get("support", 0) >= 2
            and len(c["concept"]) > 3
        ]
        # Tomamos una muestra aleatoria pequeña para no sobrecargar el prompt
        return random.sample(good, min(5, len(good))) if good else []
    except Exception:
        return []


def _llm_de_cognia(cognia_instance):
    """Backend real del REPL como funcion inyectable para el generador.

    (prompt, system, max_tokens, temperature) -> texto | None.

    Desde 2026-07-26 delega en llm_local.generar (/v1/chat/completions) en vez
    de orch.infer (/completion con prompt crudo). Con un cerebro DE
    RAZONAMIENTO (gpt-oss-20b, combo pensar) el prompt crudo sin plantilla
    hace que el modelo piense EN TEXTO PLANO y agote max_tokens antes del
    HTML. Medido 2026-07-26 con el mismo prompt contra el mismo server:
    /completion devuelve "We need to produce..." + fence truncado
    (stop_type=limit); /v1/chat/completions devuelve Title/fence limpios
    porque el server separa el razonamiento en reasoning_content. Era la
    causa de que el lazo diseno-a-codigo rechazara la generacion inicial
    ("no es un documento HTML completo") y cayera al camino corto — capacidad
    atribuida a plomeria, la MISMA clase de bug que el confound de Ollama
    (num_ctx) cerrado esta noche.

    Se conserva el gate del orquestador: sin orquestador se devuelve None y
    cada pieza cae a su propio camino (que tambien es llm_local, auditado)."""
    orch = getattr(cognia_instance, "_orchestrator", None)
    if orch is None:
        return None

    from ..llm_local import detectar_backend, generar

    def llm(prompt, system="", max_tokens=2000, temperature=0.9):
        # timeout ESCALADO al presupuesto: sin el, este closure usaba el tope
        # plano de llm_local (120 s) y toda generacion larga moria en
        # "[llm] Error: timed out" — que aguas arriba se lee como "sin backend
        # LLM vivo" y degrada hasta el 404 de Ollama. MEDIDO 2026-08-02: una
        # landing completa son 15.472 tokens en 138 s (112 tok/s); el tope de
        # 120 s la mataba a falta de ~18 s.
        from ..llm_local import timeout_para
        return generar(prompt, system=system, temperature=temperature,
                       max_tokens=max_tokens, via="construir",
                       timeout=timeout_para(max_tokens)) or None

    # generator._call_llm registra QUE backend atendio leyendo llm.url_base;
    # sin el atributo, cada llamada quedaba en el audit como
    # "inyectado(url desconocida)" con :8080 supuesto (110 entradas al
    # 2026-08-01). Como el closure delega en llm_local.generar, su URL real
    # es la que detecta llm_local.
    backend = detectar_backend()
    if backend:
        llm.url_base = backend["url"]

    return llm


# ── Loop principal ─────────────────────────────────────────────────────────────


def _idea_pide_grafico(categoria: str) -> bool:
    """La sonda no conoce la idea; esto le dice si debia haber un grafico."""
    t = (categoria or "").lower()
    return any(p in t for p in ("grafico", "gráfico", "chart", "graph",
                                "grafica", "gráfica", "sparkline"))

def run_program_hobby(
    cognia_instance=None,
    max_attempts:   int  = MAX_ATTEMPTS_PER_SESSION,
    storage_dir:    Path = None,
    verbose:        bool = True,
    forced_idea:    str  = None,
) -> HobbySessionResult:
    """
    Ejecuta una sesión completa del hobby de programación de Cognia.

    Pipeline por intento:
      1. Leer conceptos semánticos de Cognia (solo lectura, opcional)
      2. Generar idea + código Python via LLM
      3. Ejecutar código en sandbox aislado
      4. Evaluar resultado (puntuación 0–10)
      5. Guardar si supera el threshold

    Args:
        cognia_instance : Instancia de Cognia para leer conceptos (opcional)
        max_attempts    : Máximo de programas a intentar en esta sesión
        storage_dir     : Directorio de almacenamiento (None = default)
        verbose         : Si True, imprime logs detallados

    Returns:
        HobbySessionResult con estadísticas de la sesión.
    """
    start_time = time.time()
    timestamp  = datetime.now().isoformat()

    if verbose:
        print(f"\n🎨 [ProgramCreator] Iniciando sesión de hobby — {timestamp}")
        print(f"   Intentos planificados: {max_attempts}")

    # Leer conceptos para inspiración (solo lectura)
    seed_concepts = _get_seed_concepts(cognia_instance)
    if verbose and seed_concepts:
        print(f"   Conceptos semilla: {seed_concepts}")

    # Backend real del REPL (si hay): antes el generador SOLO hablaba con
    # Ollama hardcodeado y /crear no podia funcionar en la instalacion
    # recomendada (cognia install-model, sin Ollama).
    llm = _llm_de_cognia(cognia_instance)

    attempted   = 0
    successful  = 0
    stored_list = []

    for attempt in range(1, max_attempts + 1):
        if verbose:
            print(f"\n── Intento {attempt}/{max_attempts} ──────────────────────────")

        # ── Paso 1: Generar programa ───────────────────────────────────
        program: Optional[GeneratedProgram] = generate_program(
            seed_concepts, forced_idea=forced_idea, llm=llm
        )
        attempted += 1
        _session_stats["programs_attempted"] += 1

        if program is None:
            if verbose:
                print("   ⚠️  Generación fallida — saltando intento.")
            if attempt < max_attempts:
                time.sleep(INTER_GENERATION_PAUSE)
            continue

        # ── Paso 2: Ejecutar en sandbox (o revisar, si es una web) ─────
        # Una pagina HTML no se ejecuta con Python; se inspecciona.
        if getattr(program, "lenguaje", "python") == "html":
            exec_result: ExecutionResult = revisar_html(program.code)

            # ── Paso 2b: mirarla de verdad en el navegador ─────────────
            # La revision estatica no distingue "HTML valido" de "pagina que
            # funciona": una pagina puede salir entera en negro con el CSS
            # perfectamente escrito. Aqui se renderiza, se observa, y si algo
            # falla se le devuelven los defectos al modelo para que corrija.
            _con_grafico = _idea_pide_grafico(program.category)
            visual = revisar_en_navegador(program.code,
                                          requiere_grafico=_con_grafico)
            if verbose and visual.nota:
                print(f"   [vista] {visual.nota}")

            # Completitud contra la IDEA (campana 2026-07-21): lo pedido y no
            # implementado entra como defecto al MISMO canal de reparacion.
            # (Patron nº1 de fallo en 20 tareas duras: componentes omitidos.)
            try:
                from cognia.program_creator.generator import (
                    componentes_faltantes)
                _faltas = componentes_faltantes(program.category, program.code)
            except Exception:
                _faltas = []
            if _faltas and verbose:
                print(f"   📋 Componentes pedidos ausentes: "
                      f"{'; '.join(_faltas)}")

            if visual.defectos or _faltas:
                if verbose and visual.defectos:
                    print(f"   👁️  Defectos vistos en el navegador: "
                          f"{'; '.join(visual.defectos)}")
                if verbose:
                    print("   🔧 Pidiendo correccion al modelo...")

                # El navegador sabe QUE falla; el analisis estatico sabe DONDE.
                # Medido el 2026-07-19: con solo el sintoma ("todo sale del
                # mismo color") el modelo refactorizo el ternario y dejo la
                # clase en el sitio equivocado. Hay que darle el selector.
                pistas = list(visual.defectos) + _faltas
                if exec_result.execution_errors:
                    pistas += [l for l in exec_result.execution_errors.splitlines()
                               if l.strip()]

                # Hasta 3 intentos, como G1 en el camino Python (umbral de
                # Aider). Antes habia UN solo intento: con los chequeos de
                # calidad del 2026-07-20 detectando mas defectos, una unica
                # oportunidad dejaba paginas reparables sin reparar
                # ("Correccion descartada" y a guardar con el defecto).
                def _faltas_de(codigo):
                    try:
                        from cognia.program_creator.generator import (
                            componentes_faltantes)
                        return componentes_faltantes(program.category, codigo)
                    except Exception:
                        return []

                _total = len(visual.defectos) + len(_faltas)
                for _ronda in range(1, 4):
                    arreglado = reparar_web(program, pistas, llm=llm)
                    if arreglado is None:
                        if verbose:
                            print("   ↩️  El modelo no devolvio una correccion valida.")
                        break
                    visual_2 = revisar_en_navegador(
                        arreglado.code, requiere_grafico=_con_grafico)
                    _faltas_2 = _faltas_de(arreglado.code)
                    _total_2 = len(visual_2.defectos) + len(_faltas_2)
                    if _total_2 < _total:
                        program = arreglado
                        visual  = visual_2
                        _faltas, _total = _faltas_2, _total_2
                        exec_result = revisar_html(program.code)
                        if verbose:
                            print(f"   ✅ Correccion {_ronda} aceptada "
                                  f"({_total} pendientes)")
                        if not _total:
                            break
                        pistas = list(visual.defectos) + _faltas
                    else:
                        # Sin mejora: no se insiste a ciegas (regla 11).
                        if verbose:
                            print(f"   ↩️  Correccion {_ronda} descartada: no mejoraba.")
                        break

            # Lo que se VE manda sobre lo que se lee: si la pagina no funciona
            # en el navegador, no puede contar como ejecucion exitosa.
            if visual.defectos:
                exec_result.success = False
                exec_result.execution_errors = (
                    (exec_result.execution_errors + "\n" if exec_result.execution_errors else "")
                    + "En navegador: " + "; ".join(visual.defectos))
            informe_visual = visual
        else:
            exec_result: ExecutionResult = run_in_sandbox(program.code)
            informe_visual = None

            # ── G1: el error vuelve al modelo en vez de tirar el programa ──
            # Antes un fallo se regeneraba desde cero. Caso medido en
            # planes/AUTOPROGRAMACION_COGNIA.md: 114 LOC con SQLite, undo y 4
            # tests, muertos en el sandbox y descartados sin un solo intento.
            #
            # Cableado al disyuntor desde el principio, como exige el plan:
            # este lazo es literalmente el bucle de parches que ese modulo
            # existe para cortar.
            if not exec_result.success:
                tarea_rep = f"reparar {program.title}"[:60]
                disyuntor = Disyuntor(tarea_rep,
                                      ruta_log=_ruta_disyuntor(tarea_rep))
                # El fallo original NO es un parche: es el punto de partida, y
                # el modelo todavia no ha tocado nada. Registrarlo con
                # hubo_cambio=True gastaba una de las dos huellas que dispara
                # D6, asi que el disyuntor cortaba tras UNA sola reparacion en
                # vez de las 3 del umbral de Aider. El propio modulo ya prevee
                # esta distincion con --sin-cambio: observar no es parchear.
                disyuntor.registrar(
                    huella_de_texto(exec_result.execution_errors),
                    ok=False, hubo_cambio=False)

                for n_arreglo in range(1, MAX_REPARACIONES + 1):
                    motivo = disyuntor.motivo_corte()
                    if motivo:
                        # El disparo queda en el JSONL: es el dato que la
                        # calibracion del modo sombra necesita (mismo patron
                        # que tool_synthesis.py).
                        disyuntor.persistir_evento(
                            "disparo", motivo=motivo,
                            intento=len(disyuntor.intentos))
                        if verbose:
                            print(f"   ⛔ Disyuntor ({motivo}): "
                                  f"dejo de parchear a ciegas.")
                        break

                    if verbose:
                        print(f"   🔧 Reparacion {n_arreglo}/{MAX_REPARACIONES}: "
                              f"{exec_result.execution_errors.strip().splitlines()[-1][:70]}")

                    arreglado = reparar_python(program, exec_result.execution_errors, llm=llm)
                    if arreglado is None:
                        if verbose:
                            print("   ↩️  El modelo no devolvio codigo valido.")
                        break

                    nuevo = run_in_sandbox(arreglado.code)
                    disyuntor.registrar(
                        huella_de_texto(nuevo.execution_errors), ok=nuevo.success)

                    if nuevo.success:
                        program, exec_result = arreglado, nuevo
                        if verbose:
                            print(f"   ✅ Reparado al intento {n_arreglo}.")
                        break

                    # No arreglo, pero puede haber avanzado: se sigue desde el
                    # codigo nuevo solo si cambio el sintoma.
                    if nuevo.execution_errors != exec_result.execution_errors:
                        program, exec_result = arreglado, nuevo

        # ── Paso 3: Evaluar ────────────────────────────────────────────
        eval_result: EvaluationResult = evaluate_program(program, exec_result)

        # ── Paso 3b: la opinion del profesional (solo webs) ────────────
        # "Si alguien que no es artista opina sobre su propio trabajo dira
        # 'esta buenisimo'; tiene que criticar un profesional" (el dueno,
        # 2026-07-20). El critico es un rol SEPARADO del creador, con los
        # hechos medidos del navegador y el DOM RENDERIZADO como ojos. Su
        # nota CAPA la del autoevaluador: nadie se puntua por encima de su
        # critico. Medido el dia del cambio: el autoevaluador daba 7.6 a una
        # pagina cuyo grafico era una caja vacia; el critico le dio 4.5.
        if (getattr(program, "lenguaje", "python") == "html"
                and informe_visual is not None):
            try:
                from .critico import criticar_web
                critica = criticar_web(
                    program.category,
                    informe_visual.dom_renderizado or program.code,
                    informe_visual.hechos)
            except Exception:
                critica = None      # sin critico no se bloquea la sesion
            if critica:
                if verbose:
                    print(f"   🎭 Critico ({critica['critico']}): "
                          f"{critica['nota']:.1f}/10 — {critica['veredicto']}")
                eval_result.notes.append(
                    f"Critico ({critica['critico']}): {critica['nota']:.1f}/10 "
                    f"— {critica['veredicto']}")
                eval_result.notes.extend(
                    f"[critico] {d}" for d in critica["defectos"][:3])
                if critica["nota"] < eval_result.total_score:
                    eval_result.total_score = critica["nota"]
                    eval_result.should_store = (
                        eval_result.total_score >= STORE_THRESHOLD)

        # ── Paso 4: Guardar si merece la pena ──────────────────────────
        if eval_result.should_store:
            successful += 1
            meta: StoredProgramMeta = save_program(program, eval_result, storage_dir)
            stored_list.append(meta)
            _session_stats["programs_stored"] += 1

            if verbose:
                # El score que se imprime va etiquetado: es AUTO-ASIGNADO por
                # evaluator.py (regex+AST), no medido ejecutando. Ver
                # storage.etiqueta_auto.
                from .storage import etiqueta_auto
                print(f"   ✅ '{program.title}' guardado "
                      f"({etiqueta_auto(eval_result.total_score)})")

            # Las capturas se dejan JUNTO a la pagina guardada: input_images
            # (lo que miro para validarse) y output_images (el resultado).
            # meta.directory es solo el NOMBRE del directorio, no la ruta: hay
            # que componerla o las capturas acaban en el cwd.
            if informe_visual is not None and getattr(meta, "directory", None):
                dir_final = (storage_dir or DEFAULT_STORAGE_DIR) / meta.directory
                # Solo si la pagina SIGUE existiendo: el auto-cleanup corre
                # dentro de save_program y puede haberla borrado ya (paso el
                # 2026-07-20 con el critico experto capando notas). Sin este
                # check, las capturas RESUCITABAN el directorio borrado como
                # un cascaron huerfano con solo input_images.
                if (dir_final / "index.html").exists():
                    final = revisar_en_navegador(program.code, dir_final)
                    if verbose and (final.input_images or final.output_images):
                        print(f"      input_images: {len(final.input_images)} | "
                              f"output_images: {len(final.output_images)}")
        else:
            if verbose:
                from .storage import etiqueta_auto
                print(f"   🗑️  '{program.title}' descartado "
                      f"({etiqueta_auto(eval_result.total_score)} < "
                      f"{STORE_THRESHOLD})")

        # Pausa entre generaciones
        if attempt < max_attempts:
            time.sleep(INTER_GENERATION_PAUSE)

    # ── Estadísticas de sesión ─────────────────────────────────────────
    duration = round(time.time() - start_time, 1)
    _session_stats["sessions_run"] += 1
    _session_stats["last_run"]      = timestamp

    result = HobbySessionResult(
        attempted=    attempted,
        successful=   successful,
        stored=        len(stored_list),
        programs=      stored_list,
        duration_sec=  duration,
        timestamp=     timestamp,
    )

    # SELLO DE VERIFICACION REAL (2026-07-24): el score que guarda save_program
    # viene del juez LLM; no dice si el programa CORRE. Aca, tras guardarlo, se
    # corre de verdad (compila/importa/arranca/sin-stubs) y se deja su
    # .verificacion.json al lado. Best-effort y fuera del camino critico: si la
    # verificacion falla, el producto ya esta guardado igual. El dueno pidio
    # "que cognia pruebe end to end sus propios productos y evalue cosas".
    base_dir = storage_dir or DEFAULT_STORAGE_DIR
    for _meta in stored_list:
        _carpeta = getattr(_meta, "directory", None)
        if not _carpeta:
            continue
        try:
            from cognia.program_creator.verificacion import (
                verificar_al_crear, sello_de_calidad, escribir_sello)
            _dir = Path(base_dir) / _carpeta
            _res = verificar_al_crear(_dir)
            escribir_sello(_dir, sello_de_calidad(_res))   # acepta el veredicto directo
            if verbose:
                _ok = "corre" if _res.get("ok") else "NO corre"
                print(f"   🔬 '{getattr(_meta, 'title', _carpeta)}' verificado: "
                      f"{_ok} ({_res.get('puntaje', '?')}/10)")
        except Exception:
            pass

    if verbose:
        total_stored = get_program_count(storage_dir)
        print(f"\n🎨 Sesión completada en {duration}s")
        print(f"   Intentos: {attempted} | Guardados: {len(stored_list)}")
        print(f"   Total en biblioteca: {total_stored} programas\n")

    return result


def crear_hasta_lograr(
    idea:          str,
    max_rondas:    int = MAX_RONDAS_INSISTIENDO,
    cognia_instance=None,
    storage_dir:   Path = None,
    verbose:       bool = True,
) -> HobbySessionResult:
    """
    Insiste con la misma idea hasta que salga algo que pase sus propias pruebas.

    Es la tecnica que Cognia encontro investigando (`snwfdhmp/awesome-ralph`,
    913 estrellas): correr al agente en bucle hasta cumplir la especificacion,
    en vez de aceptar el primer intento. Aqui la "especificacion cumplida" no
    es una opinion del modelo: es que el programa supere las compuertas que se
    montaron esta noche — corre en el sandbox, sus tests no estan en rojo, y la
    nota llega al umbral.

    Lo que la separa de un simple bucle de reintentos es saber parar. Cada
    ronda registra su huella en el disyuntor: si dos rondas seguidas fallan
    dejando el sintoma IDENTICO, no se esta avanzando y se corta. Reintentar
    sin esa condicion es exactamente el bucle de parches esteriles que
    `cognia/disciplina/` existe para cortar.

    Devuelve el HobbySessionResult de la ronda que lo logro, o el de la ultima
    si ninguna lo consiguio.
    """
    tarea_ins = f"insistir: {idea[:50]}"
    disyuntor = Disyuntor(tarea_ins, ruta_log=_ruta_disyuntor(tarea_ins))
    ultimo: Optional[HobbySessionResult] = None

    for ronda in range(1, max_rondas + 1):
        if verbose:
            print(f"\n🔁 Ronda {ronda}/{max_rondas} — {idea[:60]}")

        resultado = run_program_hobby(
            cognia_instance = cognia_instance,
            max_attempts    = 1,
            storage_dir     = storage_dir,
            verbose         = verbose,
            forced_idea     = idea,
        )
        ultimo = resultado

        if resultado.stored > 0:
            if verbose:
                print(f"✅ Logrado en la ronda {ronda}: "
                      f"{', '.join(p.title for p in resultado.programs)}")
            return resultado

        # Huella de la ronda: que se intento y con que resultado. Dos rondas
        # con la misma huella significan que insistir no esta aportando nada.
        disyuntor.registrar(
            huella_de_texto(f"ronda sin guardar: {resultado.attempted} intentos"),
            ok=False)

        motivo = disyuntor.motivo_corte()
        if motivo:
            disyuntor.persistir_evento("disparo", motivo=motivo,
                                       intento=len(disyuntor.intentos))
            if verbose:
                print(f"⛔ Disyuntor ({motivo}): insistir no esta avanzando, paro.")
            break

    if verbose:
        print(f"🔁 Sin exito tras {ronda} ronda(s).")
    return ultimo or HobbySessionResult(
        attempted=0, successful=0, stored=0, programs=[],
        duration_sec=0.0, timestamp=datetime.now().isoformat())


# ── Integración con el ciclo idle de Cognia ────────────────────────────────────

def maybe_run_hobby(
    cognia_instance=None,
    idle_seconds:   float = 0.0,
    min_idle:       float = 30.0,
    probability:    float = 0.4,
    storage_dir:    Path  = None,
) -> Optional[HobbySessionResult]:
    """
    Versión probabilística de run_program_hobby() para integración con idle loop.

    Solo corre si:
      - Han pasado al menos `min_idle` segundos de inactividad
      - Con probabilidad `probability`

    Esta función está diseñada para ser llamada desde el ciclo de sueño de Cognia
    junto con la generación de hipótesis, como alternativa creativa.

    Ejemplo de uso en cognia_v3.py sleep():

        from cognia.program_creator.program_creator import maybe_run_hobby
        hobby_result = maybe_run_hobby(cognia_instance=self, idle_seconds=120)

    Args:
        cognia_instance : Instancia de Cognia (opcional, para seed concepts)
        idle_seconds    : Cuántos segundos lleva el sistema sin actividad
        min_idle        : Mínimo de segundos inactivo para activar el hobby
        probability     : Probabilidad de activación cuando se cumple min_idle
        storage_dir     : Directorio de almacenamiento

    Returns:
        HobbySessionResult si se ejecutó, None si no.
    """
    if idle_seconds < min_idle:
        return None

    if random.random() > probability:
        return None

    print("[ProgramCreator] 💤 Sistema idle — activando hobby de programación...")
    return run_program_hobby(
        cognia_instance=cognia_instance,
        max_attempts=1,        # Solo 1 programa por activación idle
        storage_dir=storage_dir,
        verbose=True,
    )


def get_session_stats() -> dict:
    """Devuelve estadísticas acumuladas de todas las sesiones."""
    return dict(_session_stats)


def show_library(storage_dir: Path = None) -> str:
    """Devuelve un resumen de la biblioteca de programas guardados."""
    return format_library_summary(storage_dir)
