"""
storage.py — Almacenamiento de programas exitosos generados por Cognia.

CAMBIOS v2:
  - Cognia puede ELIMINAR programas mediocres automáticamente
  - replace_if_better(): cuando llega algo mejor de la misma categoría, borra el viejo
  - auto_cleanup(): si la biblioteca crece mucho, descarta los peores
  - Registro completo de eliminaciones en deleted_programs.json
  - El resumen distingue ideas propias (🧠) de categorías predefinidas (📋)
"""

import json
import os
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from .generator  import GeneratedProgram
from .evaluator  import EvaluationResult, format_evaluation_text

# ── Configuración ──────────────────────────────────────────────────────────────

DEFAULT_STORAGE_DIR    = Path(__file__).parent / "generated_programs"
INDEX_FILE             = "index.json"
DELETION_LOG_FILE      = "deleted_programs.json"
AUTO_CLEANUP_THRESHOLD = 25    # Si hay más programas que esto, limpia automático
# 5.0 y no 6.0 desde el 2026-07-20: el 6.0 se calibro cuando el autoevaluador
# inflaba las notas (daba 7.6-8.7 a paginas que un critico profesional puntuo
# 4.5-5.5). Con el critico capando, el 6.0 vaciaba la biblioteca — la corrida
# de capacidades maximas guardo 2 paginas y la limpieza las borro al instante.
# Decision del dueno: bajar el umbral a "aprobado" ahora que la nota es dura.
SURVIVAL_SCORE         = 5.0   # Puntuación mínima para sobrevivir una limpieza


# ── Dataclass de metadata ──────────────────────────────────────────────────────

@dataclass
class StoredProgramMeta:
    id:            str
    title:         str
    category:      str
    description:   str
    total_score:   float
    created_at:    str
    directory:     str
    self_proposed: bool = False
    # Sello del lazo generar->probar->puntuar (verificacion.reflejar_en_index).
    # total_score es lo que OPINO el juez LLM; puntaje_real es lo que se midio
    # corriendo el producto. Medido el 2026-07-23 sobre 6 productos reales: el
    # juez le dio 6.4 a un dashboard que mide 9.5 y 7.5 a otro que ni arranca.
    verificado:    bool  = None
    puntaje_real:  float = None
    verificado_en: str   = ""


# ── Utilidades internas ────────────────────────────────────────────────────────

def _sanitize_dirname(title: str) -> str:
    name = title.lower().strip()
    name = re.sub(r"[^a-z0-9\s_-]", "", name)
    name = re.sub(r"[\s-]+", "_", name)
    name = name[:50].strip("_")
    return name or "unnamed_program"

def _make_unique_dirname(base: str, storage_dir: Path) -> str:
    candidate, counter = base, 1
    while (storage_dir / candidate).exists():
        candidate = f"{base}_{counter:02d}"
        counter  += 1
    return candidate

def _load_index(storage_dir: Path) -> list:
    p = storage_dir / INDEX_FILE
    if not p.exists(): return []
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return []

def _save_index(storage_dir: Path, index: list) -> None:
    with open(storage_dir / INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _score_num(e: dict) -> float:
    """total_score como numero SIEMPRE. El indice real tiene entradas legacy
    con total_score=null (19/78 al 2026-08-01: importes 'de construidos/' y
    migraciones) y `.get('total_score', 0)` NO protege de un null explicito:
    la clave existe. El sort de auto_cleanup comparaba None < float y tiraba
    TODO el /crear DESPUES de haber guardado el programa (cazado 2026-08-01,
    sesion remota 'EL ARCHIVO PROHIBIDO')."""
    v = e.get("total_score")
    return float(v) if isinstance(v, (int, float)) else 0.0

def _load_deletion_log(storage_dir: Path) -> list:
    p = storage_dir / DELETION_LOG_FILE
    if not p.exists(): return []
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return []

def _save_deletion_log(storage_dir: Path, log: list) -> None:
    with open(storage_dir / DELETION_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def _build_description_text(program: GeneratedProgram,
                              eval_result: EvaluationResult,
                              created_at: str) -> str:
    origin = "Yes — Cognia invented this idea" if getattr(program, "self_proposed", False) else "No — from predefined category"
    return "\n".join([
        f"Title         : {program.title}",
        f"Category      : {program.category}",
        f"Created at    : {created_at}",
        f"Score         : {etiqueta_auto(eval_result.total_score)}",
        f"Self-proposed : {origin}",
        "",
        "Description:",
        f"  {program.description}",
    ])


# ── Eliminación ────────────────────────────────────────────────────────────────

def delete_program(program_id: str, reason: str = "manual deletion",
                   storage_dir: Path = None) -> bool:
    """
    Elimina un programa físicamente y lo registra en el log de eliminaciones.
    Cognia usa este log para aprender qué tipos de programas no funcionan.
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    prog_dir = storage_dir / program_id
    if not prog_dir.exists(): return False

    index = _load_index(storage_dir)
    entry = next((e for e in index if e.get("id") == program_id), None)

    try:
        shutil.rmtree(prog_dir)
    except Exception as exc:
        print(f"[storage] ❌ Error eliminando {program_id}: {exc}")
        return False

    _save_index(storage_dir, [e for e in index if e.get("id") != program_id])

    if entry:
        log = _load_deletion_log(storage_dir)
        log.append({**entry, "deleted_at": datetime.now().isoformat(), "reason": reason})
        _save_deletion_log(storage_dir, log)
        print(f"[storage] 🗑️  Eliminado: '{entry.get('title', program_id)}' "
              f"(score={_score_num(entry):.1f}) — {reason}")
    return True


def auto_cleanup(storage_dir: Path = None, keep_minimum: int = 10,
                 survival_score: float = SURVIVAL_SCORE, verbose: bool = True) -> int:
    """
    Cognia revisa su biblioteca y descarta los programas más débiles.
    - Nunca toca los top-5 por puntuación (sus mejores trabajos)
    - Elimina los que están por debajo de survival_score
    - Nunca deja la biblioteca con menos de keep_minimum programas
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    index = _load_index(storage_dir)
    if len(index) <= keep_minimum: return 0

    if verbose:
        print(f"[storage] 🔍 Revisando biblioteca ({len(index)} programas)...")

    # Proteger los top-5
    sorted_index  = sorted(index, key=_score_num, reverse=True)
    protected_ids = {e["id"] for e in sorted_index[:5]}

    candidates = sorted(
        [e for e in index
         if _score_num(e) < survival_score and e.get("id") not in protected_ids],
        key=lambda e: (_score_num(e), e.get("created_at", ""))
    )

    deleted = 0
    for entry in candidates:
        if len(index) - deleted <= keep_minimum: break
        reason = (f"auto-cleanup: score {_score_num(entry):.1f} "
                  f"< survival threshold {survival_score}")
        if delete_program(entry["id"], reason=reason, storage_dir=storage_dir):
            deleted += 1

    if verbose:
        if deleted > 0:
            print(f"[storage] 🧹 Limpieza: {deleted} programas eliminados")
        else:
            print(f"[storage] ✨ Biblioteca limpia — todo por encima del umbral")
    return deleted


def replace_if_better(new_program: GeneratedProgram, new_eval: EvaluationResult,
                      storage_dir: Path = None) -> bool:
    """
    Si hay un programa de la misma categoría con puntuación >1 punto menor,
    lo elimina para hacer espacio al nuevo y mejor.
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    index = _load_index(storage_dir)
    same_cat = [
        e for e in index
        if (e.get("category") or "").lower() == new_program.category.lower()
        and _score_num(e) < new_eval.total_score - 1.0
    ]
    if not same_cat: return False

    worst  = min(same_cat, key=_score_num)
    reason = (f"replaced by '{new_program.title}' "
              f"(score {new_eval.total_score:.1f} > {_score_num(worst):.1f})")
    return delete_program(worst["id"], reason=reason, storage_dir=storage_dir)


# ── API pública ────────────────────────────────────────────────────────────────

def save_program(program: GeneratedProgram, eval_result: EvaluationResult,
                 storage_dir: Path = None) -> StoredProgramMeta:
    """Guarda un programa aprobado. Reemplaza inferiores de su categoría si los hay."""
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    storage_dir.mkdir(parents=True, exist_ok=True)

    replace_if_better(program, eval_result, storage_dir)

    base_name  = _sanitize_dirname(program.title)
    dir_name   = _make_unique_dirname(base_name, storage_dir)
    prog_dir   = storage_dir / dir_name
    prog_dir.mkdir(parents=True, exist_ok=True)

    created_at    = datetime.now().isoformat()
    self_proposed = getattr(program, "self_proposed", False)
    origin        = "self-proposed idea" if self_proposed else "predefined category"

    # Una pagina web se guarda como index.html y con comentarios HTML: meterle
    # cabecera con '#' la romperia, y el navegador no ejecuta un .py.
    if getattr(program, "lenguaje", "python") == "html":
        with open(prog_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(f"<!-- Generated by Cognia | {created_at}\n")
            f.write(f"     Category: {program.category}\n")
            f.write(f"     Score: {etiqueta_auto(eval_result.total_score)}\n")
            f.write(f"     Origin: {origin} -->\n")
            f.write(program.code)
    else:
        with open(prog_dir / "program.py", "w", encoding="utf-8") as f:
            f.write(f"# Generated by Cognia | {created_at}\n")
            f.write(f"# Category: {program.category}\n")
            f.write(f"# Score: {etiqueta_auto(eval_result.total_score)}\n")
            f.write(f"# Origin: {origin}\n\n")
            f.write(program.code)

    with open(prog_dir / "description.txt", "w", encoding="utf-8") as f:
        f.write(_build_description_text(program, eval_result, created_at))

    with open(prog_dir / "evaluation.txt", "w", encoding="utf-8") as f:
        f.write(format_evaluation_text(eval_result))

    meta = StoredProgramMeta(
        id=dir_name, title=program.title, category=program.category,
        description=program.description, total_score=eval_result.total_score,
        created_at=created_at, directory=dir_name, self_proposed=self_proposed,
    )

    index = _load_index(storage_dir)
    index.append(asdict(meta))
    _save_index(storage_dir, index)
    print(f"[storage] 💾 Guardado: {prog_dir}")

    if len(index) > AUTO_CLEANUP_THRESHOLD:
        auto_cleanup(storage_dir=storage_dir, verbose=True)

    return meta


def list_programs(storage_dir: Path = None) -> list[StoredProgramMeta]:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    programs = []
    # Las claves que el dataclass NO conoce se descartan en vez de tumbar la
    # entrada entera: el `except TypeError: continue` de antes hacia DESAPARECER
    # el programa de la biblioteca por un campo nuevo en el index. Medido el
    # 2026-07-23: al reflejar el sello de verificacion en 5 entradas,
    # get_program_count() decia 53 y list_programs() devolvia 48, en silencio.
    conocidas = set(StoredProgramMeta.__dataclass_fields__)
    for entry in _load_index(storage_dir):
        try:
            datos = {k: v for k, v in entry.items() if k in conocidas}
            datos.setdefault("self_proposed", False)
            programs.append(StoredProgramMeta(**datos))
        except TypeError:
            continue
    return sorted(programs, key=lambda p: p.created_at, reverse=True)


def get_program_count(storage_dir: Path = None) -> int:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    return len(_load_index(storage_dir))


def load_program_code(program_id: str, storage_dir: Path = None) -> str:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    prog_file = storage_dir / program_id / "program.py"
    if not prog_file.exists(): return ""
    try:
        with open(prog_file, "r", encoding="utf-8") as f: return f.read()
    except OSError: return ""


def get_deletion_log(storage_dir: Path = None) -> list:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    return _load_deletion_log(storage_dir)


def format_library_summary(storage_dir: Path = None) -> str:
    programs = list_programs(storage_dir)
    if not programs:
        return "📂 Biblioteca vacía — aún no se ha guardado ningún programa."

    self_proposed_count = sum(1 for p in programs if p.self_proposed)
    deletion_log        = get_deletion_log(storage_dir)

    # REGLA (2026-07-25): un score AUTO-ASIGNADO no se muestra como número.
    # total_score lo pone evaluator.py (regex + AST sobre el propio código); es
    # una opinión del sistema sobre sí mismo. Se le puso 7.8/10 a un random-walk
    # de 71 líneas sin input del jugador, y 5.4/10 a un "juego de Undertale" que
    # era un gráfico SVG de líneas. Solo puntaje_real —medido ejecutando— es un
    # número. Lo demás dice "sin verificar", que es la verdad.
    # "Promedio VERIFICADO" era otra media verdad: los 60 sellos existentes los
    # produjo cognia.autoprueba, que mide LIVENESS (compila/arranca/sin stubs),
    # no que el producto haga lo pedido. Decir "verificado" a secas invitaba a
    # leerlo como corrección. Se nombra el verificador.
    verificados = [p for p in programs if p.puntaje_real is not None]
    if verificados:
        promedio = sum(p.puntaje_real for p in verificados) / len(verificados)
        linea_prom = (f"Promedio estructural: {promedio:.1f}/10 "
                      f"({len(verificados)}/{len(programs)} con sello de "
                      f"autoprueba; 0 con veredicto del juez ejecutable)")
    else:
        linea_prom = f"Promedio: sin verificar (0/{len(programs)} verificados)"

    lines = [
        f"📂 Biblioteca Cognia ({len(programs)} programas)",
        f"   Ideas propias: {self_proposed_count} | {linea_prom} | "
        f"Eliminados históricamente: {len(deletion_log)}",
        "",
    ]
    for prog in programs[:10]:
        tag = "🧠" if prog.self_proposed else "📋"
        lines.append(f"  {tag} [{formatear_puntaje(prog)}] {prog.title}  "
                     f"({prog.category})")
    if len(programs) > 10:
        lines.append(f"  ... y {len(programs) - 10} más.")
    lines.append("")
    lines.append("  'sin verificar' = nadie ejecutó el producto; el número que "
                 "el sistema se puso a sí mismo no cuenta.")
    return "\n".join(lines)


def etiqueta_auto(score) -> str:
    """
    Cómo se nombra un score AUTO-ASIGNADO en cualquier salida del sistema.

    Nunca como número pelado. `total_score` lo produce evaluator.py con regex +
    AST sobre el propio código: es el sistema opinando de sí mismo, y así se le
    puso 7.8/10 a un random-walk sin input del jugador. El número se conserva
    (es información) pero va etiquetado como lo que es.
    """
    if not isinstance(score, (int, float)):
        return "sin verificar"
    return f"auto-asignado {score:.1f}/10 (SIN VERIFICAR)"


def formatear_puntaje(prog) -> str:
    """
    Cómo se muestra el puntaje de un producto. NUNCA devuelve un número que no
    haya salido de EJECUTAR el producto, y dice QUÉ se ejecutó.

    Hay dos verificadores y no miden lo mismo — confundirlos fue el hallazgo del
    2026-07-25:
      - `cognia.autoprueba` mide LIVENESS estructural (compila / arranca / sin
        stubs / hay doc / casan palabras de la descripción). Un random-walk que
        imprime saca 9.5. NO dice que el producto haga lo pedido.
      - `juez_ejecutable` abre el producto, INTERACTÚA y comprueba su contrato.
        Eso sí es corrección.

    Acepta un StoredProgramMeta o un dict del index.json.
    """
    def _campo(nombre, defecto=None):
        if isinstance(prog, dict):
            return prog.get(nombre, defecto)
        return getattr(prog, nombre, defecto)

    real = _campo("puntaje_real")
    if real is None:
        return "sin verificar"
    verificador = str(_campo("verificador", "") or "")
    if _campo("verificado") is False:
        return f"NO PASA ({real:.1f}/10 medido)"
    if "juez_ejecutable" in verificador:
        return f"{real:.1f}/10 por EJECUCIÓN"
    # Default histórico: los 60 sellos existentes son de cognia.autoprueba.
    return f"{real:.1f}/10 solo estructural"
