"""
Regresion de cognia/agent/structure.py (generate-then-structure, CP1).

Fija la semantica de los 3 niveles: auto_fix mecanico, validate_action
contra la firma, y el retry unico con error real (reinfer enlatado — la
validacion es real, el 'modelo' del retry es una funcion deterministica).
"""
from cognia.agent.structure import (
    auto_fix, build_repair_hint, structure_action, validate_action,
)


# ── nivel 1: auto_fix mecanico ──────────────────────────────────────────

def test_autofix_inserta_pipe_faltante():
    args = "notas/plan.md\nContenido del plan\ncon varias lineas"
    fixed = auto_fix("escribir_archivo", args)
    assert fixed == "notas/plan.md | Contenido del plan\ncon varias lineas"
    assert validate_action("escribir_archivo", fixed) is None


def test_autofix_no_toca_args_validos():
    args = "notas/plan.md | contenido"
    assert auto_fix("escribir_archivo", args) == args


def test_autofix_no_inventa_pipe_sin_ruta_clara():
    # 1ra linea NO parece ruta -> no se inserta '|' (mejor error que corrupcion)
    args = "esto es prosa\ny mas prosa"
    assert "|" not in auto_fix("escribir_archivo", args)


def test_autofix_quita_comillas_envolventes():
    assert auto_fix("leer_archivo", '"notas/plan.md"') == "notas/plan.md"
    assert auto_fix("leer_archivo", "`x.py`") == "x.py"


def test_autofix_ruta_contaminada_con_contenido():
    """El modelo reusa el formato 'ruta | contenido' de escribir_archivo en
    tools de SOLO ruta. Cazado en el E2E 2026-07-21: leer_archivo recibio
    'hola_e2e.txt | hola e2e' -> Path invalido [Errno 22]. Quedarse con la ruta."""
    assert auto_fix("leer_archivo", "hola_e2e.txt | hola e2e") == "hola_e2e.txt"
    assert auto_fix("contar_lineas", "x.py | print(1)") == "x.py"
    # una ruta limpia no se toca
    assert auto_fix("leer_archivo", "carpeta/x.py") == "carpeta/x.py"


# ── nivel 2: validate_action ────────────────────────────────────────────

def test_validate_partes_faltantes():
    err = validate_action("escribir_archivo", "solo_una_ruta.md")
    assert err is not None and "'|'" in err and "<ruta> | <contenido>" in err


def test_validate_kg_agregar_3_partes():
    assert validate_action("kg_agregar", "a | es_un | b") is None
    err = validate_action("kg_agregar", "a | b")
    assert err is not None and "3 partes" in err


def test_validate_ruta_con_accion_colada():
    err = validate_action("leer_archivo", "x.py ACCION: leer_archivo y.py")
    assert err is not None and "ACCION" in err


def test_validate_vacio_y_url():
    assert validate_action("ejecutar", "   ") is not None
    assert validate_action("http_get", "ftp://x") is not None
    assert validate_action("http_get", "https://x.com") is None


def test_validate_tool_sin_regla_pasa():
    assert validate_action("fecha", "") is None
    assert validate_action("tool_inexistente", "lo que sea") is None


# ── nivel 3: retry unico con error real ─────────────────────────────────

def test_structure_repara_con_reinfer():
    def reinfer(hint):
        assert "FORMATO INVALIDO" in hint
        return "ACCION: escribir_archivo notas/plan.md | contenido corregido"

    action, args, meta = structure_action(
        "escribir_archivo", "sin separador ni ruta clara", reinfer)
    assert meta["repaired"] is True and meta["error"] is None
    assert action == "escribir_archivo"
    assert args == "notas/plan.md | contenido corregido"


def test_structure_retry_fallido_devuelve_original_con_error():
    action, args, meta = structure_action(
        "escribir_archivo", "sin separador ni ruta clara",
        reinfer=lambda hint: "sigo divagando sin formato")
    assert meta["repaired"] is False and meta["error"] is not None
    assert args == "sin separador ni ruta clara"


def test_structure_valido_no_reinfiere():
    def reinfer(hint):
        raise AssertionError("no debe llamarse: los args ya validan")

    action, args, meta = structure_action(
        "leer_archivo", "notas/plan.md", reinfer)
    assert meta == {"auto_fixed": False, "repaired": False, "error": None}


def test_structure_autofix_evita_el_retry():
    # el nivel 1 resuelve solo: nivel 3 no debe ejecutarse
    def reinfer(hint):
        raise AssertionError("no debe llamarse: auto_fix ya lo arreglo")

    action, args, meta = structure_action(
        "escribir_archivo", "notas/x.md\ncontenido", reinfer)
    assert meta["auto_fixed"] is True and meta["error"] is None
    assert args == "notas/x.md | contenido"


def test_hint_menciona_error_y_formato():
    h = build_repair_hint("escribir_archivo", "x", "detalle del error")
    assert "detalle del error" in h and "ACCION" in h
