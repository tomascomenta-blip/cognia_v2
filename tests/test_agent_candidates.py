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
