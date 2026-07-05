"""
cognia/agent/prompt_evolution.py
================================
Auto-prompting / self-scaffolding: Cognia MEJORA SU PROPIO andamiaje de prompts
midiendo, no adivinando. Un "andamiaje" (Scaffold) es el system-prompt + el
banco few-shot + la instruccion de reparacion que envuelven al 3B congelado en
una tarea de tool-calling. Este modulo evoluciona ese andamiaje contra un
puntaje REAL del modelo, con separacion dev/test y gate de no-regresion.

Por que asi (y no OPRO puro):
  OPRO/APE asumen un OPTIMIZADOR fuerte que reescribe el prompt leyendo la
  trayectoria de scores. Nuestro optimizador candidato ES el mismo 3B debil ->
  malo proponiendo. La literatura factible aca es STOP (Zelikman 2023): mejorar
  el ANDAMIAJE con el LLM congelado, y APE/PromptBreeder: GENERAR variantes +
  SELECCIONAR por puntaje empirico. Entonces:
    - Las MUTACIONES son operadores CONCRETOS keyed a los buckets de error que
      el eval mide (value_error:string, wrong_func_name, wrong_count, ...). El
      generador puede ser una plantilla (robusta, sin depender del 3B) o el 3B
      mismo (opcional); el ARBITRO SIEMPRE es el puntaje medido (honesto).
    - La SELECCION es un gate de no-regresion sobre DEV; el numero final se
      reporta sobre TEST held-out (cognia_v3/eval/bfcl_split.py) para no
      overfittear la slice.
    - Un operador de COMPRESION prueba la hipotesis "prompt menos detallado mas
      valido": recorta el system-prompt y se queda con el recorte SOLO si DEV no
      baja y el costo (tokens) cae -> Pareto calidad/costo (clave por el prefill
      caro en CPU).

Concreto: dataclass Scaffold + funciones planas. El scoring recibe un callable
`generate` inyectable, asi los tests corren con un backend FALSO (sin cargar el
3B); la "verificacion REAL" es una corrida aparte con el modelo de verdad.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from cognia_v3.eval.bfcl_ast_checker import check_response, parse_model_response

# Callable que abstrae el backend: (prompt, max_tokens, temperature, seed) -> str
GenerateFn = Callable[..., str]

# Donde se persiste el mejor andamiaje descubierto (lo carga el loop /hacer).
STATE_DIR = Path(__file__).parent / "prompt_state"
BEST_SCAFFOLD_PATH = STATE_DIR / "bfcl_best_scaffold.json"


# ---------------------------------------------------------------------------
# Representacion del andamiaje
# ---------------------------------------------------------------------------

# Exemplar few-shot = (functions_json, question, answer). Igual forma que el
# banco del harness (bench_bfcl_slice.FEWSHOT_EXEMPLARS_BFCL) para poder sembrar
# el andamiaje v1 tal cual.
Exemplar = tuple


@dataclass
class Scaffold:
    """Un andamiaje candidato: lo unico que cambia entre corridas del MISMO 3B
    congelado sobre la MISMA slice. `origin` traza como se genero (para el log
    de la evolucion); no afecta el prompt."""
    name: str
    system_prompt: str
    fewshot: list = field(default_factory=list)   # lista de (funcs_json, q, ans)
    repair_hint: str = ""
    origin: str = "seed"

    def token_cost(self) -> int:
        """Proxy de costo de prefill: caracteres del system-prompt + few-shot +
        repair (lo que se paga en CADA paso). No son tokens exactos pero ordena
        candidatos por costo de forma monotona y barata."""
        n = len(self.system_prompt) + len(self.repair_hint)
        for funcs, q, ans in self.fewshot:
            n += len(funcs) + len(q) + len(ans)
        return n

    def to_dict(self) -> dict:
        return {
            "name": self.name, "system_prompt": self.system_prompt,
            "fewshot": [list(e) for e in self.fewshot],
            "repair_hint": self.repair_hint, "origin": self.origin,
        }

    @staticmethod
    def from_dict(d: dict) -> "Scaffold":
        return Scaffold(
            name=d["name"], system_prompt=d["system_prompt"],
            fewshot=[tuple(e) for e in d.get("fewshot", [])],
            repair_hint=d.get("repair_hint", ""), origin=d.get("origin", "loaded"),
        )


# ---------------------------------------------------------------------------
# Construccion de prompts a partir de un Scaffold (parametriza el harness)
# ---------------------------------------------------------------------------

def _fewshot_prefix(scaffold: Scaffold) -> str:
    if not scaffold.fewshot:
        return ""
    parts = ["Examples of the exact format expected:\n\n"]
    for funcs, q, ans in scaffold.fewshot:
        # funcs vacio == exemplar SOLO-FORMATO (bootstrapeado): muestra la sintaxis
        # question->call sin re-listar el schema (barato en prefill; el schema
        # real ya va en el prompt de la tarea).
        if funcs:
            parts.append(f"Available functions:\n{funcs}\nQuestion: {q}\nAnswer: {ans}\n\n")
        else:
            parts.append(f"Question: {q}\nAnswer: {ans}\n\n")
    parts.append("Now answer the real request the same way.\n\n")
    return "".join(parts)


def build_user_msg(scaffold: Scaffold, functions: list, question_text: str) -> str:
    return (_fewshot_prefix(scaffold)
            + "Available functions:\n" + json.dumps(functions, indent=2)
            + "\n\nQuestion: " + question_text)


def build_prompt(scaffold: Scaffold, functions: list, question_text: str) -> str:
    """ChatML (Qwen) con el system-prompt del scaffold. Import perezoso de la
    plantilla (node.inference_pipeline) para no cargar el backend en los tests
    que solo arman texto."""
    from node.inference_pipeline import _apply_qwen_template
    return _apply_qwen_template(build_user_msg(scaffold, functions, question_text),
                                system=scaffold.system_prompt)


def build_repair_prompt(scaffold: Scaffold, functions: list, question_text: str,
                        prev: str, error: str) -> str:
    from node.inference_pipeline import _apply_qwen_template
    hint = ("\nReply again with ONLY the call(s) in the exact format "
            "func(param=value), copying the function name EXACTLY from the list. "
            "Separate multiple calls with ';'.")
    if scaffold.repair_hint:
        hint += "\n" + scaffold.repair_hint
    user_msg = (build_user_msg(scaffold, functions, question_text)
                + "\n\nYour previous answer was:\n" + (prev or "(empty)")
                + "\n\nThat is INVALID: " + error + hint)
    return _apply_qwen_template(user_msg, system=scaffold.system_prompt)


def _available_names(functions: list) -> set:
    names = set()
    for fd in functions:
        n = fd.get("name", "")
        names.add(n)
        names.add(n.replace(".", "_"))
    return names


def validate_calls(calls: list, error_type, functions: list) -> str | None:
    """Error de FORMA accionable (no de correctitud) para el retry: se parseo >=1
    llamada y el/los nombre(s) existen. NO mira la ground-truth (cero leakage)."""
    if error_type is not None or not calls:
        return "no se parseo ninguna llamada valida en formato func(param=value)"
    names = _available_names(functions)
    for call in calls:
        for fname in call:
            if fname not in names:
                return (f"la funcion '{fname}' no esta en la lista; "
                        f"nombres validos: {sorted(names)[:8]}")
    return None


# ---------------------------------------------------------------------------
# Scoring de un andamiaje (la parte CARA: corre el modelo)
# ---------------------------------------------------------------------------

@dataclass
class ScoreResult:
    accuracy: float
    n: int
    n_passed: int
    n_repaired: int
    by_category: dict            # cat -> (passed, total)
    error_buckets: dict          # error_type -> count (solo fallos)
    per_item: list               # [{id,category,passed,error_type,repaired}]
    token_cost: int

    def summary(self) -> str:
        cats = " ".join(f"{c}={p}/{t}" for c, (p, t) in sorted(self.by_category.items()))
        return (f"acc={self.accuracy:.3f} ({self.n_passed}/{self.n}) "
                f"rep={self.n_repaired} cost={self.token_cost} | {cats}")


def score_scaffold(scaffold: Scaffold, items: list, generate: GenerateFn, *,
                   repair: bool = True, max_tokens: int = 512, seed: int = 42,
                   on_item: Callable[[dict], None] | None = None) -> ScoreResult:
    """
    Corre `scaffold` sobre `items` usando `generate` y devuelve un ScoreResult.

    `items`: lista de dicts YA RESUELTOS con claves:
        id, category, functions (lista), question (str), ground_truth (lista).
      (Se resuelven con resolve_items() a partir de [{"id","category"}]; separado
       para que los tests pasen items sinteticos sin tocar los datos de BFCL.)
    `generate`: callable(prompt, max_tokens=..., temperature=..., seed=...) -> str.
      Inyectable: el backend real o un fake determinista en tests.
    El oraculo (check_response) es SIEMPRE el mismo del harness congelado.
    """
    per_item, buckets = [], {}
    n_pass = n_rep = 0
    from collections import Counter
    cat_pass, cat_tot = Counter(), Counter()

    for it in items:
        cat, functions, q, gt = (it["category"], it["functions"],
                                 it["question"], it["ground_truth"])
        prompt = build_prompt(scaffold, functions, q)
        response = generate(prompt, max_tokens=max_tokens, temperature=0.0, seed=seed) or ""

        did_repair = False
        if repair:
            calls0, err0 = parse_model_response(response)
            struct_err = validate_calls(calls0, err0, functions)
            if struct_err is not None:
                retry = generate(
                    build_repair_prompt(scaffold, functions, q, response, struct_err),
                    max_tokens=max_tokens, temperature=0.0, seed=seed) or ""
                calls1, err1 = parse_model_response(retry)
                if validate_calls(calls1, err1, functions) is None:
                    response, did_repair = retry, True
                    n_rep += 1

        passed, error_type, _detail = check_response(cat, functions, gt, response)
        cat_tot[cat] += 1
        if passed:
            n_pass += 1
            cat_pass[cat] += 1
        else:
            buckets[error_type] = buckets.get(error_type, 0) + 1
        rec = {"id": it["id"], "category": cat, "passed": passed,
               "error_type": error_type, "repaired": did_repair}
        per_item.append(rec)
        if on_item:
            on_item(rec)

    n = len(items)
    by_cat = {c: (cat_pass[c], cat_tot[c]) for c in cat_tot}
    return ScoreResult(
        accuracy=(n_pass / n if n else 0.0), n=n, n_passed=n_pass, n_repaired=n_rep,
        by_category=by_cat, error_buckets=buckets, per_item=per_item,
        token_cost=scaffold.token_cost(),
    )


def resolve_items(entries: list) -> list:
    """[{"id","category"}] -> items resueltos (functions/question/ground_truth)
    leyendo los datos congelados de BFCL. Import perezoso del harness (toca
    disco); los tests unitarios no lo usan."""
    from cognia_v3.eval.bench_bfcl_slice import (
        load_category_items, load_category_answers, question_text_of, CATEGORIES,
    )
    items_cache = {c: load_category_items(c) for c in CATEGORIES}
    answers_cache = {c: load_category_answers(c) for c in CATEGORIES}
    out = []
    for e in entries:
        cat, iid = e["category"], e["id"]
        item = items_cache[cat][iid]
        out.append({
            "id": iid, "category": cat, "functions": item["function"],
            "question": question_text_of(item),
            "ground_truth": answers_cache[cat][iid],
        })
    return out


# ---------------------------------------------------------------------------
# Andamiaje semilla (== v1 del harness, medido en 86% sobre las 200)
# ---------------------------------------------------------------------------

def seed_scaffold() -> Scaffold:
    """El andamiaje v1 tal cual (system-prompt + 2 few-shot + repair del harness):
    punto de partida MEDIDO (86% en la slice completa) del que evolucionar."""
    from cognia_v3.eval.bench_bfcl_slice import SYSTEM_PROMPT, FEWSHOT_EXEMPLARS_BFCL
    return Scaffold(
        name="v1_seed",
        system_prompt=SYSTEM_PROMPT,
        fewshot=[tuple(e) for e in FEWSHOT_EXEMPLARS_BFCL[:2]],
        repair_hint="",
        origin="seed",
    )


# ---------------------------------------------------------------------------
# Operadores de mutacion (keyed a los buckets de error que el eval mide)
# ---------------------------------------------------------------------------
# Cada operador toma un Scaffold y devuelve uno NUEVO (o None si no aplica). El
# arbitro es SIEMPRE el puntaje empirico: un operador propone, el gate decide.
# Los textos son cortos a proposito (cada char es prefill de cada paso).

_RULE_EXACT_STRINGS = (
    "When a parameter value is a string quoted or named in the request, copy it "
    "EXACTLY (same words, casing, units and symbols); never paraphrase, translate "
    "or reformat it."
)
_RULE_COUNT_CALLS = (
    "Emit exactly ONE call per distinct action requested: read the request, count "
    "the separate actions, and produce that many calls separated by ';'."
)
_RULE_EXACT_NAMES = (
    "Use function names spelled EXACTLY as in the list; do not shorten, translate "
    "or invent names."
)

# Exemplars few-shot adicionales, cada uno enseña un modo de fallo concreto.
_EX_PARALLEL_MULTIPLE = (
    '[{"name": "book_flight", "description": "Book a flight.", "parameters": '
    '{"type": "object", "properties": {"city": {"type": "string"}}, "required": '
    '["city"]}}, {"name": "reserve_hotel", "description": "Reserve a hotel.", '
    '"parameters": {"type": "object", "properties": {"city": {"type": "string"}, '
    '"nights": {"type": "integer"}}, "required": ["city", "nights"]}}]',
    "Book a flight to Tokyo and to Osaka, and reserve a hotel in Tokyo for 3 nights.",
    'book_flight(city="Tokyo"); book_flight(city="Osaka"); '
    'reserve_hotel(city="Tokyo", nights=3)',
)
_EX_STRING_EXACT = (
    '[{"name": "set_status", "description": "Set a user status.", "parameters": '
    '{"type": "object", "properties": {"message": {"type": "string"}, "mood": '
    '{"type": "string", "enum": ["happy", "busy", "away"]}}, "required": '
    '["message", "mood"]}}]',
    'Set my status message to "Out for lunch" and my mood to busy.',
    'set_status(message="Out for lunch", mood="busy")',
)

# Mapa bucket-de-error -> (etiqueta, funcion de mutacion). El bucket dominante en
# DEV dispara su operador. Varias claves de checker mapean al mismo remedio.
_BUCKET_TO_MUTATION = {
    "value_error:string": ("add_rule_exact_strings", "rule_exact_strings"),
    "value_error:others": ("add_rule_exact_strings", "rule_exact_strings"),
    "value_error:list/tuple": ("add_rule_exact_strings", "rule_exact_strings"),
    "value_error:dict_value": ("add_rule_exact_strings", "rule_exact_strings"),
    "value_error:dict_key": ("add_rule_exact_strings", "rule_exact_strings"),
    "simple_function_checker:wrong_func_name": ("add_rule_exact_names", "rule_exact_names"),
    "parallel_function_checker_no_order:wrong_count": ("add_rule_count_calls", "rule_count_calls"),
    "simple_function_checker:unexpected_param": ("add_rule_exact_strings", "rule_exact_strings"),
}


def _append_rule(scaffold: Scaffold, rule: str, tag: str) -> Scaffold | None:
    """Agrega una regla al final del system-prompt (idempotente: si ya esta, no
    duplica -> devuelve None para que el gate no gaste una eval en un no-cambio)."""
    if rule in scaffold.system_prompt:
        return None
    return replace(scaffold, name=f"{scaffold.name}+{tag}",
                   system_prompt=scaffold.system_prompt.rstrip() + " " + rule,
                   origin=f"mut:{tag}")


def mut_rule_exact_strings(s: Scaffold) -> Scaffold | None:
    return _append_rule(s, _RULE_EXACT_STRINGS, "exactstr")


def mut_rule_count_calls(s: Scaffold) -> Scaffold | None:
    return _append_rule(s, _RULE_COUNT_CALLS, "count")


def mut_rule_exact_names(s: Scaffold) -> Scaffold | None:
    return _append_rule(s, _RULE_EXACT_NAMES, "exactname")


def _add_exemplar(scaffold: Scaffold, ex: Exemplar, tag: str) -> Scaffold | None:
    if any(e[1] == ex[1] for e in scaffold.fewshot):   # misma pregunta ya presente
        return None
    return replace(scaffold, name=f"{scaffold.name}+{tag}",
                   fewshot=list(scaffold.fewshot) + [ex], origin=f"mut:{tag}")


def mut_fewshot_parallel_multiple(s: Scaffold) -> Scaffold | None:
    return _add_exemplar(s, _EX_PARALLEL_MULTIPLE, "ex_pm")


def mut_fewshot_string_exact(s: Scaffold) -> Scaffold | None:
    return _add_exemplar(s, _EX_STRING_EXACT, "ex_str")


def mut_compress_system(s: Scaffold) -> Scaffold | None:
    """Hipotesis 'menos detallado, mas valido': recorta la frase mas redundante
    del system-prompt. Se acepta SOLO si DEV no baja y el costo cae (lo decide el
    gate Pareto, no este operador). Aca solo produce el candidato mas corto."""
    sp = s.system_prompt
    # La ultima oracion del prompt base repite 'only the call(s)' -> candidata a
    # recorte sin perder informacion.
    redundant = (" Do not output any prose, explanation, or markdown -- only the "
                 "call(s).")
    if redundant in sp:
        return replace(s, name=f"{s.name}+short", origin="mut:compress",
                       system_prompt=sp.replace(redundant, ""))
    return None


# System-prompt MINIMO: la evidencia dice que sobre-instruir DEGRADA a modelos
# chicos (un 4B: fallos criticos 2.4-7.5% -> 4.8-45.5% al sobre-instruir). Esta
# variante prueba el extremo del eje 'menos detallado': solo lo imprescindible.
_MINIMAL_SYSTEM = (
    "Reply with ONLY the function call(s) in Python syntax func(param=value), "
    "multiple calls separated by ';'. No prose."
)


def mut_minimal_system(s: Scaffold) -> Scaffold | None:
    """Reemplaza el system-prompt por el minimo. Candidato agresivo del eje
    'menos, mas valido': puede SUBIR accuracy en un 3B (sobre-instruir dana),
    no solo bajar costo. El gate decide con la evidencia."""
    if s.system_prompt == _MINIMAL_SYSTEM:
        return None
    return replace(s, name=f"{s.name}+min", origin="mut:minimal",
                   system_prompt=_MINIMAL_SYSTEM)


# ---------------------------------------------------------------------------
# BootstrapFewShot (DSPy): cosechar few-shots de las trazas que el 3B YA resuelve
# bien, verificadas por el ORACULO. Es el mecanismo #1 de la investigacion y la
# forma mas literal de "la IA mejora sus propios prompts": no inventa ejemplos,
# usa sus propios exitos verificados. Exemplars SOLO-FORMATO (sin el schema
# pesado) -> baratos en prefill.
# ---------------------------------------------------------------------------

# Categorias debiles medidas (v1 86%): parallel_multiple 70%, live_simple 77.5%.
# Se priorizan al cosechar (mas senal donde mas falla).
_HARD_CATEGORIES = ("parallel_multiple", "parallel", "live_simple")


def bootstrap_exemplars(base: Scaffold, harvest_items: list, generate: GenerateFn, *,
                        k: int = 2, max_tokens: int = 256, seed: int = 42,
                        on_item: Callable[[dict], None] | None = None) -> list:
    """
    Corre `base` sobre `harvest_items`, se queda con las respuestas que el oraculo
    marca CORRECTAS, y devuelve hasta k exemplars SOLO-FORMATO (funcs="", question,
    answer_verificada). Prioriza categorias dificiles y respuestas cortas
    (Promptbreeder: el prompt/ejemplo corto suele ganar).

    NB anti-leakage: `harvest_items` debe ser DISJUNTO del set sobre el que luego
    se puntua el scaffold (si no, se estaria evaluando sobre los mismos items que
    se metieron como ejemplo). El runner separa harvest / tune / test.
    """
    verified = []
    for it in harvest_items:
        prompt = build_prompt(base, it["functions"], it["question"])
        resp = (generate(prompt, max_tokens=max_tokens, temperature=0.0, seed=seed) or "").strip()
        passed, _et, _d = check_response(it["category"], it["functions"],
                                        it["ground_truth"], resp)
        if on_item:
            on_item({"id": it["id"], "category": it["category"], "passed": passed})
        if not passed:
            continue
        # respuesta a una sola linea (la primera con la(s) llamada(s))
        answer = resp.splitlines()[0].strip() if resp else ""
        if not answer:
            continue
        # pregunta compacta: ultima linea 'user:' (evita el schema y el rol)
        q = it["question"].split("user:")[-1].strip()[:200] or it["question"][:200]
        hard_rank = 0 if it["category"] in _HARD_CATEGORIES else 1
        verified.append((hard_rank, len(answer), ("", q, answer)))
    # dificiles primero, luego respuestas cortas
    verified.sort(key=lambda t: (t[0], t[1]))
    return [ex for _hr, _ln, ex in verified[:k]]


def make_bootstrapped(base: Scaffold, exemplars: list) -> Scaffold | None:
    """Anexa los exemplars cosechados al banco few-shot del `base`. None si no se
    cosecho nada (no gastar una eval en un no-cambio)."""
    if not exemplars:
        return None
    existing_qs = {e[1] for e in base.fewshot}
    new_ex = [e for e in exemplars if e[1] not in existing_qs]
    if not new_ex:
        return None
    return replace(base, name=f"{base.name}+boot{len(new_ex)}",
                   fewshot=list(base.fewshot) + new_ex, origin="mut:bootstrap")


# Operadores dirigidos por bucket (se disparan segun el fallo dominante en DEV).
_MUTATION_FNS = {
    "rule_exact_strings": mut_rule_exact_strings,
    "rule_count_calls": mut_rule_count_calls,
    "rule_exact_names": mut_rule_exact_names,
}

# Operadores "siempre-candidatos" (se prueban ademas del dirigido cada ronda).
# El eje 'menos, mas valido' entra como candidato de pleno derecho (minimal +
# compress): si el 3B rinde igual o mejor con menos texto, el gate lo adopta.
_ALWAYS_MUTATIONS = [
    ("fewshot_parallel_multiple", mut_fewshot_parallel_multiple),
    ("fewshot_string_exact", mut_fewshot_string_exact),
    ("compress_system", mut_compress_system),
    ("minimal_system", mut_minimal_system),
]


def propose_mutations(scaffold: Scaffold, score: ScoreResult) -> list:
    """Lista de (tag, Scaffold) candidatos para esta ronda, ordenada: primero el
    operador dirigido al bucket de error DOMINANTE en DEV (STOP-style: leer el
    fallo -> proponer el remedio), luego los siempre-candidatos. Filtra los
    no-cambio (None). Cero LLM: robusto y barato; el 3B no tiene que optimizar."""
    proposals = []
    # 1) dirigido al bucket dominante
    if score.error_buckets:
        top_bucket = max(score.error_buckets.items(), key=lambda kv: kv[1])[0]
        mapping = _BUCKET_TO_MUTATION.get(top_bucket)
        if mapping:
            _label, fn_key = mapping
            cand = _MUTATION_FNS[fn_key](scaffold)
            if cand is not None:
                proposals.append((fn_key, cand))
    # 2) siempre-candidatos
    for tag, fn in _ALWAYS_MUTATIONS:
        cand = fn(scaffold)
        if cand is not None:
            proposals.append((tag, cand))
    return proposals


# ---------------------------------------------------------------------------
# Busqueda evolutiva con gate de no-regresion (sobre DEV)
# ---------------------------------------------------------------------------

@dataclass
class EvolutionLog:
    seed_score: ScoreResult
    best_scaffold: Scaffold
    best_score: ScoreResult
    trajectory: list          # [{round, tag, name, accuracy, cost, accepted}]
    accepted_path: list       # nombres de los andamiajes aceptados en orden


def _accepts(cand: ScoreResult, incumbent: ScoreResult, min_gain: float) -> str | None:
    """Criterio del gate. Devuelve el motivo de aceptacion ('acc' | 'pareto') o
    None si se rechaza. 'acc': mejora accuracy por > min_gain. 'pareto': misma (o
    mejor) accuracy con MENOS costo -> avala la hipotesis 'menos, mas valido'."""
    if cand.accuracy > incumbent.accuracy + min_gain:
        return "acc"
    if cand.accuracy >= incumbent.accuracy and cand.token_cost < incumbent.token_cost:
        return "pareto"
    return None


def evolve(seed: Scaffold, dev_items: list, generate: GenerateFn, *,
           rounds: int = 3, min_gain: float = 0.0, repair: bool = True,
           log: Callable[[str], None] = print) -> EvolutionLog:
    """
    APE/PromptBreeder-style sobre DEV: desde `seed`, cada ronda propone mutaciones
    (dirigidas al bucket de error dominante + siempre-candidatos), las puntua con
    el modelo, y ADOPTA la mejor que pase el gate de no-regresion. Corta cuando
    una ronda no produce ninguna aceptada (convergencia) o se acaban las rondas.

    NB: toda decision es sobre DEV. El numero honesto se mide DESPUES sobre TEST
    held-out (run_prompt_evolution.py), nunca aca -> no overfittea el reporte.
    """
    incumbent = seed
    inc_score = score_scaffold(seed, dev_items, generate, repair=repair)
    log(f"[evolve] seed {seed.name}: {inc_score.summary()}")
    seed_score = inc_score
    trajectory = [{"round": 0, "tag": "seed", "name": seed.name,
                   "accuracy": inc_score.accuracy, "cost": inc_score.token_cost,
                   "accepted": True, "reason": "seed"}]
    accepted_path = [seed.name]

    for r in range(1, rounds + 1):
        proposals = propose_mutations(incumbent, inc_score)
        if not proposals:
            log(f"[evolve] ronda {r}: sin mutaciones nuevas -> convergio")
            break
        best_cand = best_score = best_tag = best_reason = None
        for tag, cand in proposals:
            sc = score_scaffold(cand, dev_items, generate, repair=repair)
            reason = _accepts(sc, inc_score, min_gain)
            log(f"[evolve] ronda {r} cand {cand.name} ({tag}): {sc.summary()} "
                f"-> {'ACEPTA:'+reason if reason else 'rechaza'}")
            trajectory.append({"round": r, "tag": tag, "name": cand.name,
                               "accuracy": sc.accuracy, "cost": sc.token_cost,
                               "accepted": bool(reason), "reason": reason})
            if reason is None:
                continue
            # entre las aceptadas, la mejor por (accuracy, -costo)
            if (best_cand is None or sc.accuracy > best_score.accuracy or
                    (sc.accuracy == best_score.accuracy and
                     sc.token_cost < best_score.token_cost)):
                best_cand, best_score, best_tag, best_reason = cand, sc, tag, reason
        if best_cand is None:
            log(f"[evolve] ronda {r}: ninguna candidata paso el gate -> corta")
            break
        incumbent, inc_score = best_cand, best_score
        accepted_path.append(best_cand.name)
        log(f"[evolve] ronda {r}: adopta {best_cand.name} "
            f"({best_reason}, {inc_score.summary()})")

    return EvolutionLog(seed_score=seed_score, best_scaffold=incumbent,
                        best_score=inc_score, trajectory=trajectory,
                        accepted_path=accepted_path)


# ---------------------------------------------------------------------------
# Persistencia: el loop /hacer carga el mejor andamiaje descubierto
# ---------------------------------------------------------------------------

def persist_best(scaffold: Scaffold, meta: dict | None = None) -> Path:
    """Guarda el andamiaje ganador (+ metadata de la corrida) para que el agente
    en vivo lo use. Solo se llama tras validar en TEST (no overfittear en vivo)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"scaffold": scaffold.to_dict(), "meta": meta or {}}
    BEST_SCAFFOLD_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return BEST_SCAFFOLD_PATH


def load_best() -> Scaffold | None:
    """El mejor andamiaje persistido, o None si aun no se corrio la evolucion.
    Best-effort: un JSON corrupto no debe romper el loop."""
    try:
        if not BEST_SCAFFOLD_PATH.exists():
            return None
        payload = json.loads(BEST_SCAFFOLD_PATH.read_text(encoding="utf-8"))
        return Scaffold.from_dict(payload["scaffold"])
    except Exception:
        return None
