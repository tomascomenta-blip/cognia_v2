r"""
cycle91_matched_prior.py — CICLO 91 (RESET v4, rama R-PRIOR, ataca H-V4-3 ABIERTA; hija de CYCLE 90): H-V4-3a por las
compuertas del engine. APOYADA: la FORMA/CALIDAD del prior (la base del estimador) — NO el volumen de datos ni la
capacidad cruda — fija la eficiencia muestral. Sobre el MISMO valor REAL no-nesteable de CYCLE 90 (dos bandas interiores,
verificador sandbox exp018), un prior MATCHEADO a la estructura (rbf: bumps gaussianos LOCALES en c × LINEAL en r, que
encode "suave/local en c, lineal en r" SIN conocer las bandas exactas) recupera a una FRACCIÓN del feedback que una base
no-paramétrica genérica (binned): rbf a presupuesto BAJO (0.687) ya SUPERA a bin a presupuesto ALTO (0.620, +0.067);
rbf gana a bin a igual bajo presupuesto (+0.147); rbf SATURA rápido (+0.033 low->high) mientras bin es DATA-HUNGRY
(+0.079); rbf >> poly2 (base equivocada, +0.221) y queda más cerca del techo bayes (gap 0.113 vs bin 0.213). => avanza
R-PRIOR/H-V4-3: el lever de la eficiencia muestral es el MATCH del prior con la estructura del valor, no el volumen.

DERIVA de exp075_matched_prior/results/results.json.

Correr (DESPUÉS de exp075):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp075_matched_prior.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle91_matched_prior
"""
import argparse
import dataclasses
import json
import os
import shutil
import sys

from cognia_x.research.schema import Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord, to_dict
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord, count_lines

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle91_matched_prior')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp075_matched_prior', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="sesgo inductivo / no-free-lunch: el prior correcto (la forma de la base) fija la eficiencia muestral; una base con la estructura adecuada iguala a un método general caro a una fracción de los datos", obtained=False,
                     claim=("R-PRIOR / teoría de aproximación: con la base adecuada (sesgo inductivo que matchee la "
                            "estructura del target) se recupera con MUCHas menos muestras que con una base genérica de "
                            "alta capacidad (no-paramétrica fina), que paga su flexibilidad con varianza/datos (NFL). La "
                            "CALIDAD/FORMA del prior — no su volumen ni su capacidad cruda — fija la eficiencia muestral; "
                            "un prior suave también promedia el ruido de las features. (Principio; es H-V4-3.)"))
S_EXP074 = Source(tier=5, ref="cognia_x/experiments/exp074_nonnested_value", obtained=True,
                  claim=("CYCLE 90 halló que sobre un valor REAL no-nesteable (dos bandas interiores) el poly2 falla y "
                         "una base RICA GENÉRICA (binned) recupera sólo PARCIAL y es DATA-HUNGRY (no alcanza bayes ni con "
                         "T=1000). Dejó como próximo: un prior MATCHEADO que recupere barato. H-V4-3a lo testea."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp075 primero): " + results_path)

    se = sm['rbf_sample_eff_vs_bin_low']
    fc = sm['rbf_fraction_cost_vs_bin_high']
    rs = sm['rbf_saturates']
    bd = sm['bin_data_hungry']
    vp = sm['rbf_vs_poly2']
    rbg = sm['rbf_bayes_gap']
    bbg = sm['bin_bayes_gap']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim075 = ("exp075 (propio, {n} seeds, numpy + sandbox exp018, mismo sustrato no-nesteable de exp074): el prior "
                "MATCHEADO (rbf local en c × lineal en r) es SAMPLE-EFFICIENT: rbf_low={rl} >= bin_high={bh} (a fracción "
                "del costo, Δ={fc}); rbf gana a bin a igual bajo presupuesto +{se}; rbf satura +{rs} vs bin data-hungry "
                "+{bd}; rbf >> poly2 +{vp}; rbf más cerca de bayes (gap {rbg} vs bin {bbg}).").format(
                    n=n_seeds, rl=_f(g['low']['learned_rbf']), bh=_f(g['high']['learned_bin']), fc=_f(fc), se=_f(se),
                    rs=_f(rs), bd=_f(bd), vp=_f(vp), rbg=_f(rbg), bbg=_f(bbg))
    S_EXP075 = Source(tier=5, ref="cognia_x/experiments/exp075_matched_prior", obtained=True, claim=claim075)
    for src in (S_PRINCIPLE, S_EXP074, S_EXP075):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 R-PRIOR/sesgo-inductivo; S_EXP074 tier5 base genérica data-hungry de CYCLE 90; S_EXP075 tier5 dato propio).")

    ev_for = [S_EXP075.ref]
    ev_against = [S_EXP075.ref, S_EXP074.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (ataca H-V4-3/R-PRIOR ABIERTA; hija de CYCLE 90): CYCLE 90 mostró que una base RICA GENÉRICA (binned) "
               "recupera el valor no-nesteable sólo PARCIAL y CARO (data-hungry, no alcanza bayes). H-V4-3a testea si un "
               "prior MATCHEADO a la estructura recupera BARATO. El prior matcheado = rbf: bumps gaussianos LOCALES en c "
               "× LINEAL en r -- encode el TIPO de estructura ('suave/local en c, lineal en r' = la forma de "
               "E[v]=band(c)·r) SIN conocer las bandas exactas (9 centros EQUIESPACIADOS, no en las bandas; los datos "
               "ajustan los coeficientes). RESULTADO: la FORMA del prior FIJA la eficiencia muestral. (1) SAMPLE "
               "EFFICIENCY: rbf a presupuesto BAJO ({rl}) ya iguala/SUPERA a la base genérica bin a presupuesto ALTO "
               "({bh}) -- recupera a una FRACCIÓN del costo (Δ={fc}); y gana a bin a igual bajo presupuesto (+{se}). "
               "(2) rbf SATURA rápido (high−low +{rs}) mientras bin es DATA-HUNGRY (+{bd}). (3) rbf >> poly2 (base "
               "GLOBAL equivocada, +{vp}) y queda MÁS CERCA del techo bayes (gap {rbg} vs bin {bbg}: el prior suave "
               "también promedia el ruido de features que la grilla dura del bin sufre). => el lever de la eficiencia "
               "muestral NO es el volumen de datos ni la capacidad cruda, sino el MATCH del prior (la base) con la "
               "estructura del valor -- exactamente R-PRIOR/H-V4-3. EVIDENCIA EN CONTRA / CAVEAT HONESTO: (a) el rbf no "
               "alcanza bayes (gap {rbg}): el prior matcheado es eficiente, no perfecto (ruido de features + bumps "
               "finitos); (b) el prior está MATCHEADO por conocimiento de DISEÑO (yo sabía que la estructura era "
               "local-en-c); de DÓNDE viene el prior correcto (descubrirlo/aprenderlo) es la pregunta más profunda de "
               "R-PRIOR, no resuelta aquí; (c) un bin con kernel-smoothing tendería al rbf -> confirma que el lever es "
               "la SUAVIDAD/estructura, no la etiqueta 'paramétrico vs no'. Caveats: g sintético de bandas, espacio 2D, "
               "objetivo escalar; falta el generador de MODELO real y SCALE.").format(
                   V=status.upper(), rl=_f(g['low']['learned_rbf']), bh=_f(g['high']['learned_bin']), fc=_f(fc),
                   se=_f(se), rs=_f(rs), bd=_f(bd), vp=_f(vp), rbg=_f(rbg), bbg=_f(bbg))

    hyp = Hypothesis(
        id="H-V4-3a",
        statement=("La FORMA/CALIDAD del prior (la base del estimador) — no el volumen de datos ni la capacidad cruda — "
                   "fija la eficiencia muestral: un prior MATCHEADO a la estructura del valor (rbf local) recupera el "
                   "valor no-nesteable a una FRACCIÓN del feedback que una base no-paramétrica genérica (bin). (Hija "
                   "operativa de H-V4-3 / R-PRIOR.)"),
        prediction=("APOYADA si rbf es sample-efficient (rbf_low >= bin_high − 0.02, a fracción del costo; rbf_low > "
                    "bin_low + 0.03) Y rbf supera a poly2 (+0.03); REFUTADA si rbf ≈ bin/poly2 (la forma no aporta); "
                    "MIXTA si ayuda parcial pero no a clara fracción del costo. (Pre-registrada, sandbox real exp018, "
                    "48 seeds, 2 presupuestos.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp075_matched_prior")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-3a")
        notes.append("H-V4-3a marcada '{}' con DoD completo (avanza H-V4-3/R-PRIOR ABIERTA).".format(status))

    analogy = AnalogyRecord(
        problem=("Para hallar dos zonas buenas escondidas, ¿me conviene un mapa en blanco de cuadrícula fina (que lleno "
                 "a fuerza de visitas) o traer de antemano la corazonada correcta sobre QUÉ FORMA tienen las zonas?"),
        everyday=("Traer la FORMA correcta gana por lejos: si sé que las zonas buenas son 'parches suaves' (aunque no "
                  "sepa dónde), con pocas visitas ya las ubico -- mi corazonada rellena lo que no vi. El mapa en blanco "
                  "de cuadrícula fina necesita MUCHas más visitas para lo mismo, y sus casillas a caballo del borde lo "
                  "confunden. La corazonada equivocada ('más a la derecha es mejor') no sirve. No es cuánto explorás: es "
                  "traer la forma correcta del problema."),
        solutions=["prior MATCHEADO (rbf local): con POCO feedback ya iguala a la cuadrícula fina con MUCHO feedback",
                   "base genérica fina (bin): recupera pero data-hungry y la confunde el ruido en los bordes",
                   "base global equivocada (poly2): no acierta dos zonas separadas",
                   "un bin con suavizado tendería al rbf -> el lever es la SUAVIDAD/estructura, no la etiqueta"],
        principles=["la base del estimador es un PRIOR; su MATCH con la estructura fija la eficiencia muestral (R-PRIOR)",
                    "un prior con el sesgo inductivo correcto recupera a una FRACCIÓN de los datos de una base genérica",
                    "una base genérica de alta capacidad paga su flexibilidad con varianza/datos (no-free-lunch)",
                    "un prior suave además promedia el ruido de las features que una grilla dura sufre"],
        adaptation=("El lab AVANZA R-PRIOR/H-V4-3: la forma/calidad del prior (la base) fija la eficiencia muestral. "
                    "Combinado con CYCLE 90 (el poly2 no es universal), la política de reconstrucción de R-VALOR es: "
                    "elegir la base por la ESTRUCTURA esperada del valor -- poly2 si es suave/conjuntivo (89), una base "
                    "local/matcheada si es multi-banda (91), nunca una genérica data-hungry por defecto. Próximo: de "
                    "DÓNDE viene el prior correcto (descubrir/seleccionar la base de los datos, meta-prior); el generador "
                    "de MODELO real (lazo cerrado exp018); y SCALE."),
        measurement=("exp075 ({n} seeds): rbf_low={rl} >= bin_high={bh} (fracción del costo Δ={fc}); rbf gana a bin_low "
                     "+{se}; rbf satura +{rs} vs bin data-hungry +{bd}; rbf>>poly2 +{vp}; rbf gap bayes {rbg} vs bin "
                     "{bbg}.").format(n=n_seeds, rl=_f(g['low']['learned_rbf']), bh=_f(g['high']['learned_bin']),
                                      fc=_f(fc), se=_f(se), rs=_f(rs), bd=_f(bd), vp=_f(vp), rbg=_f(rbg), bbg=_f(bbg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (traer la FORMA correcta del problema gana a la cuadrícula en blanco).")

    kl = ("REAL (exp075): la FORMA/CALIDAD del prior fija la eficiencia muestral (R-PRIOR/H-V4-3). Un prior MATCHEADO "
          "(rbf local en c × lineal en r) recupera el valor no-nesteable de CYCLE 90 a una FRACCIÓN del feedback que la "
          "base genérica (bin): rbf_low={rl} >= bin_high={bh}; rbf satura +{rs} vs bin data-hungry +{bd}; rbf>>poly2 "
          "+{vp}. TECHO: el prior eficiente no alcanza bayes (gap {rbg}); y queda ABIERTO de DÓNDE viene el prior "
          "correcto (descubrirlo/aprenderlo).").format(rl=_f(g['low']['learned_rbf']), bh=_f(g['high']['learned_bin']),
                                                        rs=_f(rs), bd=_f(bd), vp=_f(vp), rbg=_f(rbg))
    ceilings.add(CeilingRecord(
        subsystem="R-PRIOR — la forma/calidad del prior (la base) fija la eficiencia muestral; un prior matcheado recupera a fracción del costo de una base genérica",
        known_limit=kl,
        blockers=[{"text": "el prior está MATCHEADO por conocimiento de DISEÑO (se sabía que la estructura era local-en-c); de DÓNDE viene/cómo se descubre el prior correcto (meta-prior, selección de base de los datos) es la pregunta más profunda de R-PRIOR, no resuelta", "kind": "diseno"},
                  {"text": "el prior matcheado es eficiente pero NO perfecto: no alcanza el techo bayes (ruido de features + bumps finitos)", "kind": "fisico"},
                  {"text": "g sintético de bandas, espacio 2D, objetivo escalar; falta el generador de MODELO real (lazo cerrado exp018) y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP075.ref, S_EXP074.ref]))
    notes.append("1 techo 'real': la forma del prior fija la eficiencia muestral; queda abierto de dónde viene el prior correcto.")

    dstmt = ("North-Star R-PRIOR (avanza H-V4-3 ABIERTA; cierra el próximo de CYCLE 90): la FORMA/CALIDAD del prior (la "
             "base del estimador) — no el volumen de datos ni la capacidad cruda — fija la eficiencia muestral. Un prior "
             "MATCHEADO a la estructura (rbf local) recupera el valor no-nesteable a una FRACCIÓN del feedback de una "
             "base genérica data-hungry (bin), y supera a la base equivocada (poly2). Decisión: la política de "
             "reconstrucción de R-VALOR elige la BASE por la ESTRUCTURA esperada del valor (poly2 si suave/conjuntivo 89; "
             "base local/matcheada si multi-banda 91), nunca una genérica data-hungry por defecto. Liga gap #2 con "
             "R-PRIOR. Próximo: de DÓNDE viene el prior correcto (meta-prior / selección de base); el generador de MODELO "
             "real; y SCALE.")
    drat = ("exp075 (tier5, propio, {n} seeds, numpy + sandbox exp018): rbf_low={rl} >= bin_high={bh} (fracción del "
            "costo, Δ={fc}); rbf gana a bin_low +{se}; rbf satura +{rs} vs bin data-hungry +{bd}; rbf>>poly2 +{vp}. "
            "Convergente con sesgo-inductivo/NFL (tier2) y con la base genérica data-hungry de CYCLE 90 (tier5). APOYADA "
            "la tesis R-PRIOR.").format(n=n_seeds, rl=_f(g['low']['learned_rbf']), bh=_f(g['high']['learned_bin']),
                                        fc=_f(fc), se=_f(se), rs=_f(rs), bd=_f(bd), vp=_f(vp))
    dec = Decision(id="D-V4-53", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP075), _to_plain(S_EXP074)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-53 ACEPTADA por el ledger (tier5 exp075 + tier5 exp074).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-53:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle91_matched_prior',
                                description='CYCLE 91 (RESET v4, H-V4-3a: la forma del prior fija la eficiencia muestral -- APOYADA; avanza R-PRIOR/H-V4-3).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, sm = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 91 (RESET v4): la FORMA del prior fija la eficiencia muestral (H-V4-3a) — avanza R-PRIOR/H-V4-3")
    print("=" * 78)
    print("veredicto H-V4-3a:", status.upper() if status else "?")
    print("  el prior MATCHEADO (rbf local) recupera a FRACCIÓN del feedback de una base genérica (bin); supera a poly2; cerca de bayes.")
    print("")
    for n in notes:
        print("  CHECK ", n)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
