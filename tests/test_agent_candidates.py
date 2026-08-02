"""
Regresion de cognia/agent/candidates.py (BoN + juez por tests visibles, CP1).

El juez ejecuta codigo REAL en subprocess (via run_task_tests) — aca se fija
la semantica del rank sin modelo: el generador es una funcion enlatada
determinista, la EJECUCION de los asserts es real (no mock del oraculo).
"""
from cognia.agent.candidates import (
    best_of_n, build_test_gen_prompt, dedupe_codes, extract_asserts,
    generate_candidates, rank_candidates,
)

GOOD_CODE = "def double(n):\n    return n * 2\n"
BAD_CODE = "def double(n):\n    return n + 2\n"       # pasa double(2)==4, falla el resto
BROKEN_CODE = "def double(n)\n    return n * 2\n"      # SyntaxError

ASSERTS = ["assert double(2) == 4", "assert double(5) == 10",
           "assert double(0) == 0"]


def test_extract_asserts_filtra_y_dedupe():
    raw = (
        "Here are the tests:\n"
        "```python\n"
        "assert double(2) == 4\n"          # valido
        "assert double(2) == 4\n"          # duplicado
        "assert triple(2) == 6\n"          # otra funcion -> fuera
        "assert double(3 == 6\n"           # sintaxis rota -> fuera
        "print('hola')\n"                  # no es assert -> fuera
        "assert double(0) == 0\n"          # valido
        "```\n"
    )
    got = extract_asserts(raw, "double")
    assert got == ["assert double(2) == 4", "assert double(0) == 0"]


def test_extract_asserts_respeta_cap():
    raw = "\n".join(f"assert double({i}) == {i*2}" for i in range(10))
    assert len(extract_asserts(raw, "double", max_asserts=3)) == 3


def test_dedupe_codes():
    codes = [GOOD_CODE, "def double(n):\n\n    return n * 2", BAD_CODE, ""]
    # el 2do es el mismo codigo modulo whitespace; el vacio se descarta
    assert dedupe_codes(codes) == [0, 2]


def test_generate_candidates_temperaturas_y_seeds():
    calls = []

    def fake_gen(prompt, temperature, seed):
        calls.append((temperature, seed))
        return f"c{len(calls)}"

    outs = generate_candidates(fake_gen, "p", n=4, seed=100)
    assert outs == ["c1", "c2", "c3", "c4"]
    assert calls[0] == (0.0, 100)                     # candidato 0 greedy
    assert all(t == 0.7 for t, _ in calls[1:])        # resto con sampling
    assert [s for _, s in calls] == [100, 101, 102, 103]  # seeds distintas


def test_rank_el_correcto_gana_aunque_llegue_ultimo():
    codes = [BAD_CODE, BROKEN_CODE, GOOD_CODE]
    best_idx, ranking, mode = rank_candidates(codes, ASSERTS, "double")
    assert mode == "tests"
    assert best_idx == 2
    assert ranking[0]["score"] == 3
    # el roto puntua 0 y queda ultimo o anteultimo, nunca primero
    assert ranking[0]["idx"] != 1


def test_rank_empate_gana_el_greedy():
    # dos codigos identicos en comportamiento -> mismo score -> idx menor
    codes = [GOOD_CODE, GOOD_CODE.replace("n * 2", "2 * n")]
    best_idx, ranking, mode = rank_candidates(codes, ASSERTS, "double")
    assert best_idx == 0


def test_rank_sin_asserts_degrada_declarado():
    best_idx, ranking, mode = rank_candidates([BAD_CODE, GOOD_CODE], [],
                                              "double")
    assert mode == "greedy_fallback"
    assert best_idx == 0                              # greedy, y lo declara


def test_best_of_n_e2e_con_generador_enlatado():
    """Pipeline completo: el 'modelo' enlatado propone tests y candidatos;
    la ejecucion que decide es real. El candidato correcto (idx 1) gana."""
    responses = iter([
        # 1) generacion de tests visibles (greedy)
        "assert double(2) == 4\nassert double(5) == 10",
        # 2) candidato 0 (greedy): buggy
        "```python\n" + BAD_CODE + "```",
        # 3) candidato 1: correcto
        "```python\n" + GOOD_CODE + "```",
    ])

    def fake_gen(prompt, temperature, seed):
        return next(responses)

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=2, seed=7)
    assert out["rank_mode"] == "tests"
    assert out["best_idx"] == 1
    assert "n * 2" in out["code"]
    assert out["visible_tests"] == ["assert double(2) == 4",
                                    "assert double(5) == 10"]
    assert out["n_unique"] == 2


def test_prompt_de_tests_no_pide_la_funcion():
    p = build_test_gen_prompt("Write double(n).", "double", k=3)
    assert "Do NOT write the function" in p
    assert "double(" in p

def test_best_of_n_early_stop_greedy_perfecto():
    """Si el greedy pasa TODOS los tests visibles, no se genera el resto del
    pool (lossless: los empates los gana el idx menor). Se declara en
    rank_mode y n_generated deja la evidencia."""
    calls = []

    def fake_gen(prompt, temperature, seed):
        calls.append(temperature)
        if len(calls) == 1:                     # paso test-first
            return "assert double(2) == 4\nassert double(5) == 10"
        return "```python\n" + GOOD_CODE + "```"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=8, seed=7)
    assert out["rank_mode"] == "tests_greedy_early"
    assert out["best_idx"] == 0
    assert out["n_generated"] == 1
    assert len(calls) == 2                      # tests + SOLO el greedy


def test_best_of_n_greedy_imperfecto_genera_el_pool_completo():
    """Regresion: si el greedy NO pasa todo, el pipeline genera los N
    candidatos y rankea como siempre (el correcto gana aunque llegue 2do)."""
    calls = []

    def fake_gen(prompt, temperature, seed):
        calls.append(temperature)
        if len(calls) == 1:
            return "assert double(2) == 4\nassert double(5) == 10"
        if len(calls) == 2:                     # greedy: buggy (pasa 1/2)
            return "```python\n" + BAD_CODE + "```"
        return "```python\n" + GOOD_CODE + "```"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=3, seed=7)
    assert out["rank_mode"] == "tests"
    assert out["best_idx"] == 1
    assert out["n_generated"] == 3
    assert len(calls) == 4                      # tests + 3 candidatos


def test_best_of_n_early_stop_no_aplica_con_bpb():
    """Con bpb_fn el desempate puede preferir otro candidato -> el corte
    temprano NO es lossless y no debe aplicarse."""
    calls = []

    def fake_gen(prompt, temperature, seed):
        calls.append(temperature)
        if len(calls) == 1:
            return "assert double(2) == 4"
        return "```python\n" + GOOD_CODE + "```"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=3, seed=7, bpb_fn=lambda c: 1.0)
    assert out["n_generated"] == 3              # pool completo, sin corte


def test_best_of_n_empate_lo_rompe_el_consenso_de_ejecucion():
    """Regresión A14 (descablado): en un empate del top score de visibles,
    best_of_n elegía por idx menor — a ciegas. Ahora exec_consensus genera
    inputs, EJECUTA los empatados y gana la moda de comportamiento: entre
    un buggy (idx 1) y dos correctos (idx 2 y 3) que empatan 1/1, el
    consenso elige un correcto. Sin el wiring, best_idx sería 1."""
    TRIPLE = "def double(n):\n    return n * 3\n"      # pasa double(0)==0
    GOOD2 = "def double(n):\n    return n + n\n"       # correcto, otra forma
    responses = iter([
        # 1) test-first: un solo assert DEBIL (0 lo delata a greedy, no a n*3)
        "assert double(0) == 0",
        # 2) greedy: buggy que FALLA el visible (evita el early-stop)
        "```python\n" + BAD_CODE + "```",
        # 3) candidato 1: buggy que PASA el visible (n*3)
        "```python\n" + TRIPLE + "```",
        # 4) candidato 2: correcto
        "```python\n" + GOOD_CODE + "```",
        # 5) candidato 3: correcto, otra forma (misma firma que el 2)
        "```python\n" + GOOD2 + "```",
        # 6) generacion de inputs distinguidores (consensus_tiebreak)
        "double(2)\ndouble(5)\ndouble(-1)",
    ])

    def fake_gen(prompt, temperature, seed):
        return next(responses)

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=4, seed=7)
    assert out["rank_mode"] == "tests+consensus"
    assert out["best_idx"] in (2, 3)            # un correcto, no el n*3
    assert out["consensus"]["winner_size"] == 2  # cluster de los 2 correctos


def _pool_empatado():
    """Generador enlatado que produce un EMPATE en visibles (1/1) entre un
    buggy (idx 1) y dos correctos (idx 2 y 3) -> obliga al consenso."""
    TRIPLE = "def double(n):\n    return n * 3\n"
    GOOD2 = "def double(n):\n    return n + n\n"
    return iter([
        "assert double(0) == 0",                 # visible debil
        "```python\n" + BAD_CODE + "```",        # greedy: falla el visible
        "```python\n" + TRIPLE + "```",
        "```python\n" + GOOD_CODE + "```",
        "```python\n" + GOOD2 + "```",
    ])


def test_best_of_n_usa_el_input_gen_fn_para_el_consenso():
    """Regresion 2026-08-01: el bench pasaba SOLO test_gen_fn (system
    'responde SOLO con asserts') y best_of_n lo reusaba para pedir los
    inputs del consenso -> el modelo devolvia asserts, 0 inputs, consenso
    None SIEMPRE. Ahora el consenso tiene su propio generador y se declara
    cual se uso."""
    responses = _pool_empatado()
    usados = []

    def code_gen(prompt, temperature, seed):
        usados.append("code")
        return next(responses)

    def test_gen(prompt, temperature, seed):
        usados.append("test")
        return next(responses)                   # el primer enlatado

    def input_gen(prompt, temperature, seed):
        usados.append("input")
        assert "Do NOT write the expected result" in prompt
        return "double(2)\ndouble(5)\ndouble(-1)"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(code_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=4, seed=7, test_gen_fn=test_gen,
                    input_gen_fn=input_gen)
    assert usados.count("input") == 1            # se llamo al generador propio
    assert out["rank_mode"] == "tests+consensus"
    assert out["consensus"]["input_gen"] == "input_gen_fn"
    assert out["consensus"]["reason"] == "consenso"
    assert out["best_idx"] in (2, 3)


def test_best_of_n_declara_cuando_el_consenso_no_puede():
    """Si el consenso se INTENTA y no desempata, el pick sale por indice —
    y eso ya no se disfraza de 'tests': rank_mode lo dice y consensus.reason
    explica por que. Sin el fix, rank_mode quedaba 'tests' (indistinguible
    de un consenso exitoso) y el modo de fallo era invisible."""
    responses = _pool_empatado()

    def code_gen(prompt, temperature, seed):
        return next(responses)

    def test_gen(prompt, temperature, seed):
        return next(responses)

    def input_gen(prompt, temperature, seed):
        return "Sure, here are some ideas for tests."   # cero llamadas

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(code_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=4, seed=7, test_gen_fn=test_gen,
                    input_gen_fn=input_gen)
    assert out["rank_mode"] == "tests+consenso_nulo"
    assert out["consensus"]["reason"] == "sin_inputs"
    assert out["best_idx"] == 1                  # desempate por indice, visible


def test_best_of_n_sin_input_gen_fn_lo_declara_como_fallback():
    """Sin input_gen_fn el consenso reusa test_gen_fn (system de asserts) y
    lo DECLARA: el caller queda advertido en el JSON."""
    responses = _pool_empatado()

    def code_gen(prompt, temperature, seed):
        return next(responses)

    def test_gen(prompt, temperature, seed):
        try:
            return next(responses)
        except StopIteration:                    # la llamada del consenso
            return "assert double(2) == 4\nassert double(5) == 10"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(code_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=4, seed=7, test_gen_fn=test_gen)
    assert out["consensus"]["input_gen"] == "test_gen_fn(fallback)"
    # y aun asi decide: de los asserts se rescata la llamada
    assert out["rank_mode"] == "tests+consensus"
    assert out["best_idx"] in (2, 3)


def test_best_of_n_sin_empate_no_llama_al_consenso():
    """Con un ganador claro en visibles no hay empate: el consenso NI se
    invoca (cero llamadas extra al modelo) y rank_mode queda 'tests'."""
    responses = iter([
        "assert double(2) == 4\nassert double(5) == 10",
        "```python\n" + BAD_CODE + "```",       # greedy: 1/2
        "```python\n" + GOOD_CODE + "```",      # candidato 1: 2/2 (gana solo)
    ])

    def fake_gen(prompt, temperature, seed):
        return next(responses)                  # StopIteration si llamara mas

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=2, seed=7)
    assert out["rank_mode"] == "tests"
    assert out["best_idx"] == 1
    assert out["consensus"] is None


def test_best_of_n_sin_tests_visibles_corta_en_greedy():
    """Sin oraculo el ranking siempre elige el primer unico no-vacio (=el
    greedy): generar N-1 extra es CPU tirada. Corta y lo declara."""
    calls = []

    def fake_gen(prompt, temperature, seed):
        calls.append(temperature)
        if len(calls) == 1:
            return "no tests here, sorry"       # test-gen no produce asserts
        return "```python\n" + GOOD_CODE + "```"

    from cognia_v3.eval.benchmark_code import extract_code
    out = best_of_n(fake_gen, "PROMPT", "task: double a number", "double",
                    extract_code, n=8, seed=7)
    assert out["rank_mode"] == "greedy_fallback_early"
    assert out["n_generated"] == 1
    assert len(calls) == 2
