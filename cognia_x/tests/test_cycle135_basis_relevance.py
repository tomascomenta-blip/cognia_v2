r"""
CYCLE 135 / H-V4-10i — regresión (MIXTA post-verificación adversarial de 4 agentes). NÚCLEO (sobrevive, leakage-free): una BASE de
credit-assignment EXPRESIVA (rica/paridad-mixta) recupera el factor RELEVANCIA del R-VALOR bajo meta NO-LINEAL (cierra el caveat
EJE2 de 134); la base lineal falla bajo meta par por ORTOGONALIDAD-DE-PARIDAD; robusta a las 4 formas. CLAIMS SECUNDARIOS
RETRACTADOS: 'el prior paga' es ~80% artefacto de sub-regularización (se cierra subiendo el ridge); 'no hay base fija universal' es
FALSO (un feature relu fijo es casi-universal).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle135_basis_relevance.py -q
"""
from cognia_x.experiments.exp119_basis_relevance import run as X


def test_mixta_nucleo_recupera_secundarios_retractados():
    grid = X.run(n_seeds=80)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core_recovers"], (sm["matched_recovers"], sm["rich_recovers"], sm["rich_robust"])
    # el 'prior paga' NO es robusto (se cierra con regularización cross-validable)
    assert not sm["prior_pays_robust"], sm["data_cost"]
    # 'no hay base fija universal' es FALSO: un relu fijo es casi-universal
    assert sm["relu_near_universal"], sm["relu_worst"]


def test_nucleo_base_expresiva_recupera_bajo_no_linealidad():
    grid = X.run(n_seeds=80)
    bf = grid["by_form"]
    ev = bf["even"]
    # la base lineal (134) queda degradada bajo even; matched y rica resucitan la relevancia (decisión)
    assert ev["ambos_linear"] < 0.78, ev["ambos_linear"]
    assert ev["ambos_even"] > 0.90, ev["ambos_even"]
    assert ev["ambos_rich"] > 0.90, ev["ambos_rich"]
    assert ev["ambos_rich"] - ev["ambos_linear"] > 0.15, (ev["ambos_rich"], ev["ambos_linear"])
    # robusta a TODA forma sin saber cuál
    for form in X.META_FORMS:
        assert bf[form]["ambos_rich"] > 0.88, (form, bf[form]["ambos_rich"])


def test_prior_paga_es_artefacto_de_subregularizacion():
    # el gap matched-rica a σ_g alto se CIERRA subiendo el ridge (cross-validable) -> no es costo intrínseco de la generalidad
    grid = X.run(n_seeds=80)
    dc = X.build_summary(grid)["data_cost"]
    assert dc["gap_noise_loridge"] > 0.08, dc["gap_noise_loridge"]      # existe a ridge mild
    assert dc["gap_noise_hiridge"] < dc["gap_noise_loridge"] - 0.10, dc  # se DESPLOMA con más regularización


def test_no_hay_base_universal_es_falso_relu_casi_universal():
    grid = X.run(n_seeds=80)
    bf = grid["by_form"]
    relu_worst = min(bf[f]["ambos_relu"] for f in X.META_FORMS)
    assert relu_worst > 0.88, relu_worst                                # un feature FIJO relu recupera todas las formas
    # sólo fallan las bases de PARIDAD-PURA ortogonales (linear<->even)
    assert bf["even"]["ambos_linear"] < 0.78, bf["even"]["ambos_linear"]
    assert bf["linear"]["ambos_even"] < 0.80, bf["linear"]["ambos_even"]


def test_descubrimiento_genuino_no_colapsa_a_control():
    # bajo meta even, la base expresiva sube la decisión MUY por encima de solo-control (no es doble-conteo de control)
    grid = X.run(n_seeds=80)
    ev = grid["by_form"]["even"]
    assert ev["ambos_rich"] - ev["ctrl_solo"] > 0.4, (ev["ambos_rich"], ev["ctrl_solo"])
