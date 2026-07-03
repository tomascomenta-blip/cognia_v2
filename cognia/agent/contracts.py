"""
cognia/agent/contracts.py
=========================
Verificacion por etapa del pipeline del agente (CP3, 06_AGENTE_PLAN §5-6).

Es la base del experimento AG-ARB, que falsea la afirmacion central del
paper del dueño (§4.2: "un arbitro atribuye la falla al modulo culpable en
un pipeline heterogeneo"). Aca vive la ESTRATEGIA (i) del plan —
verificacion por etapa con oraculos duros baratos— contra la que se compara
el arbitro-LLM global (estrategia ii/iii, en bench_arbitro.py).

Pipeline modelado (analogo agente del LCD del paper: etapas semanticamente
heterogeneas y NO sustituibles):
    plan  ->  design  ->  code  ->  test
Cada contrato compara la salida de una etapa contra la especificacion de la
anterior y devuelve la PRIMERA violacion (o None). La atribucion de la
cascada = el primer contrato violado. Los contratos son baratos y
deterministas (parseo/ast/ejecucion), cero LLM — esa es justamente la
hipotesis a testear: ¿le gana esto al juez-LLM cuando hay oraculo ejecutable?

Concreto: funciones planas que toman dicts de etapa; sin clases.
"""
from __future__ import annotations

import ast
import re

# Orden canonico de las etapas del pipeline (la cascada las recorre asi).
STAGES = ("plan", "design", "code", "test")


# ── plan -> design: cobertura de entidades ──────────────────────────────

def _entities(text: str) -> set:
    """Sustantivos-clave del texto: tokens alfanumericos de 3+ chars,
    normalizados. Aproximacion barata de 'los objetos que la etapa nombra'
    (analogo a los objetos del layout en el LCD del paper)."""
    return {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")}


def contract_plan_design(plan: dict, design: dict) -> str | None:
    """El design debe referenciar TODAS las entidades requeridas por el plan.
    plan['required_entities'] = lista de nombres que el diseño debe cubrir;
    fallback: se derivan del texto del plan. Devuelve la 1ra faltante o None."""
    required = plan.get("required_entities")
    if required is None:
        required = sorted(_entities(plan.get("text", "")))
    design_text = design.get("text", "") + " " + " ".join(design.get("signatures", []))
    present = _entities(design_text)
    missing = [e for e in required if e.lower() not in present]
    if missing:
        return f"design no cubre entidad(es) del plan: {missing[:5]}"
    return None


# ── design -> code: compatibilidad de firmas ────────────────────────────

def _defined_signatures(code: str) -> dict:
    """{nombre: [args]} de funciones y metodos top-level del codigo. '' si
    no parsea (eso lo captura el contrato, no un crash)."""
    sigs = {}
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return sigs
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Contar TODOS los parametros nombrados: pos-only + pos-o-kw +
            # kw-only (antes solo .args -> `def f(a, *, b)` contaba aridad 1
            # y disparaba un falso 'aridad incompatible' contra un diseño de 2).
            a = node.args
            sigs[node.name] = ([p.arg for p in getattr(a, "posonlyargs", [])]
                               + [p.arg for p in a.args]
                               + [p.arg for p in a.kwonlyargs])
    return sigs


def contract_design_code(design: dict, code: dict) -> str | None:
    """El codigo debe DEFINIR cada firma que el diseño declaro, con aridad
    compatible. design['signatures'] = ['def foo(a, b)', 'bar(x)', ...].
    Devuelve la 1ra firma incumplida (nombre faltante o aridad distinta)."""
    src = code.get("code", "")
    if not src.strip():
        return "code vacio"
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return f"code no parsea: linea {exc.lineno}: {exc.msg}"
    defined = _defined_signatures(src)
    for sig in design.get("signatures", []):
        m = re.search(r"(\w+)\s*\(([^)]*)\)", sig)
        if not m:
            continue
        name = m.group(1)
        want_args = [a.strip().split(":")[0].split("=")[0].strip()
                     for a in m.group(2).split(",") if a.strip()]
        if name not in defined:
            return f"code no define '{name}' (declarada en el diseño)"
        got = [a for a in defined[name] if a != "self"]
        if len(got) != len(want_args):
            return (f"'{name}' tiene {len(got)} args, el diseño pedia "
                    f"{len(want_args)} ({want_args})")
    return None


# ── code -> test: ejecucion real ────────────────────────────────────────

def contract_code_test(code: dict, test: dict) -> str | None:
    """El codigo debe PASAR los tests de la etapa. test['tests'] = string de
    asserts; se ejecuta code+tests en el sandbox real (mismo motor que el
    benchmark de codigo). Devuelve el tipo de fallo o None si pasa."""
    from cognia_v3.eval.benchmark_code import run_task_tests
    entry = test.get("entry_point") or code.get("entry_point", "")
    passed, err_type, err_detail = run_task_tests(
        code.get("code", ""), test.get("tests", ""), entry)
    if passed:
        return None
    return f"tests fallan ({err_type}): {err_detail[:120]}"


# ── cascada contratos-primero: atribucion por primer contrato violado ───

_CONTRACTS = [
    ("plan", "design", contract_plan_design),
    ("design", "code", contract_design_code),
    ("code", "test", contract_code_test),
]


def attribute_failure(pipeline: dict) -> dict:
    """Estrategia (i)+(iii) del plan: verificacion por etapa con un CONTROL
    para desambiguar el borde design/code. Devuelve {stage, reason, contract}
    — stage None si todos los oraculos pasan.

    Un contrato I/O entre A y B, al violarse, NO dice por si solo cual de las
    dos etapas fallo (el problema exacto del §4.2 del paper: una sombra mal
    puede venir de iluminacion O de una geometria mal que iluminacion
    proceso bien). Para localizar se usa un 'renderizado de control' (la idea
    (iii) del propio paper): un oraculo INDEPENDIENTE de la etapa en disputa.

    Cascada:
      1. ¿el design cubre las entidades del plan? No -> 'design' (dropeo de
         requisito en el design; oraculo: contract_plan_design).
      2. ¿el code respeta las firmas del design? No -> CONTROL: ¿el code pasa
         los tests de la etapa? Si pasa, el code es correcto-para-la-tarea y
         el outlier es el DESIGN (firma mala) -> 'design'. Si NO pasa, el
         code esta mal -> 'code'.
      3. ¿el code pasa los tests? No -> 'code' (bug de codigo; NO se puede
         distinguir de un test corrupto sin una 2da referencia — limite
         declarado: un test-fault se atribuye a code).
      4. todo pasa -> None.
    """
    plan = pipeline.get("plan", {})
    design = pipeline.get("design", {})
    code = pipeline.get("code", {})
    test = pipeline.get("test", {})

    # 1. design vs plan (cobertura de entidades)
    r1 = contract_plan_design(plan, design)
    if r1 is not None:
        return {"stage": "design", "reason": r1, "contract": "plan->design"}

    # 2. code vs design (firmas) con control por tests
    r2 = contract_design_code(design, code)
    if r2 is not None:
        control = contract_code_test(code, test)  # None = el code pasa los tests
        if control is None:
            # code correcto-para-la-tarea pero incompatible con el design:
            # el outlier es el design (firma mala).
            return {"stage": "design", "reason": f"firma del design vs code: {r2}",
                    "contract": "design->code(control:code_ok)"}
        return {"stage": "code", "reason": r2, "contract": "design->code"}

    # 3. code vs test (ejecucion)
    r3 = contract_code_test(code, test)
    if r3 is not None:
        return {"stage": "code", "reason": r3, "contract": "code->test"}

    return {"stage": None, "reason": "todos los contratos pasan", "contract": None}
