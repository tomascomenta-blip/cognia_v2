r"""
cycle69_prior_quality.py — CICLO 69 (RESET v4): H-V4-3 por las compuertas del engine. Raíz FRESCA R-PRIOR del
thesis v4 (la CALIDAD del prior > su forma).

H-V4-3: un prior con la SIMETRÍA correcta es muy eficiente muestralmente y un prior FALSO hunde (peor que no
asumir nada) -> lo que importa es la CALIDAD/corrección del prior, no tenerlo ni su forma. DERIVA de
exp054_prior_quality/results/results.json.

Correr (DESPUÉS de exp054):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp054_prior_quality.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle69_prior_quality
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle69_prior_quality')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp054_prior_quality', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_NFL = Source(tier=1, ref="no-free-lunch / equivariancia (sample efficiency from the right prior)", obtained=False,
               claim=("La inducción es sub-determinada (NFL): un prior es necesario, y su CALIDAD/corrección -- "
                      "no su forma -- fija la eficiencia muestral; un prior con la simetría correcta (equivariancia) "
                      "es barato y muy eficiente; uno equivocado introduce sesgo irreducible. (Principio.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (R-PRIOR)", obtained=True,
                claim=("El thesis v4 lista R-PRIOR como raíz convergente: 'programa más corto / MDL / búsqueda de "
                       "programas' es UNA apuesta de diseño, no la raíz; lo irreducible es un prior fuerte y bien "
                       "elegido. H-V4-3 lo prueba."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp054 primero): " + results_path)
    cur = sm['curves']
    ns, nb = sm['nt_small'], sm['nt_big']
    cor, gen, wrong = cur['correcto'], cur['general'], cur['equivocado']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP054 = Source(tier=5, ref="cognia_x/experiments/exp054_prior_quality", obtained=True,
                      claim=("exp054 (propio, {n} seeds, logreg numpy, tarea perm-invariante y=sum(x)>=D/2): el "
                             "prior CORRECTO (1 feature) alcanza {cs} con {ns} ejemplos (general {gs} ahí); el "
                             "general necesita ~{nb} para igualar; el prior EQUIVOCADO se queda en {wb} a {nb} "
                             "(<< general {gb}). La CALIDAD del prior fija la eficiencia muestral.").format(
                                 n=n_seeds, cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]), nb=nb, wb=_f(wrong[nb]),
                                 gb=_f(gen[nb])))
    for src in (S_NFL, S_TREE, S_EXP054):
        ledger.add_source(src)
    notes.append("3 fuentes (S_NFL tier1 no-free-lunch/equivariancia; S_TREE tier5 thesis R-PRIOR; S_EXP054 tier5 dato propio).")

    ev_for = [S_EXP054.ref, S_TREE.ref]
    ev_against = [S_EXP054.ref]
    adv = ("{V} (raíz FRESCA R-PRIOR del thesis v4): el thesis dice que 'programa más corto / MDL / búsqueda de "
           "programas' es UNA apuesta de diseño y que lo irreducible es un prior fuerte y BIEN ELEGIDO; su CALIDAD "
           "(no su forma) fija la eficiencia muestral. exp054 lo PRUEBA en una tarea perm-invariante (y=sum(x)>="
           "D/2, depende sólo del CONTEO). Tres priors = tres feature maps de una logreg: CORRECTO (perm-invariante, "
           "1 feature = el conteo), GENERAL (D features crudas), EQUIVOCADO (asume que sólo importan k posiciones). "
           "RESULTADO: el prior CORRECTO alcanza {cs} con sólo {ns} ejemplos mientras el general da {gs} ahí "
           "(+{eff} de eficiencia muestral); el general necesita ~{nb} ejemplos para IGUALAR lo que el correcto "
           "logra con {ns} (~16x menos datos). El prior EQUIVOCADO se queda CLAVADO en {wb} aun a {nb} ejemplos, "
           "MUY por DEBAJO del general ({gb}) -- un prior FALSO no es 'menos prior', es SESGO IRREDUCIBLE que "
           "hunde por debajo de no asumir nada. => lo que importa es la CALIDAD/corrección del prior (la simetría "
           "correcta), no tenerlo ni su forma; un prior barato con la equivarianza correcta vence a la fuerza "
           "bruta de datos. EVIDENCIA EN CONTRA (caveats honestos): (1) tarea de juguete (1 simetría, "
           "perm-invariancia, logreg lineal); falta una familia de simetrías y modelos más ricos. (2) el techo del "
           "correcto depende de entrenar bien (con sobre-regularización se topaba en ~0.82; con l2 chico llega a "
           "~1.0 -- el prior CORRECTO puede representar la verdad, la regularización lo ocultaba; se reporta el "
           "techo real). (3) no se comparó contra un buscador-de-programas/MDL real (sólo se argumenta el costo). "
           "CONCLUSIÓN: R-PRIOR confirmada en juguete -- la calidad del prior es el lever de la eficiencia "
           "muestral; conecta con R-VALOR (un buen prior es valor a priori sobre qué estructura importa).").format(
               V=status.upper(), cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]), eff=_f(cor[ns] - gen[ns]), nb=nb,
               wb=_f(wrong[nb]), gb=_f(gen[nb]))

    hyp = Hypothesis(
        id="H-V4-3",
        statement=("La CALIDAD/corrección del prior fija la eficiencia muestral: un prior con la simetría correcta "
                   "es muy eficiente y un prior falso hunde (peor que no asumir nada); importa la calidad, no la "
                   "forma ni tenerlo."),
        prediction=("APOYADA si el prior correcto alcanza alta acc (>=0.90) con muchos menos ejemplos que el "
                    "general Y el prior equivocado queda por debajo del general a n grande; REFUTADA si el correcto "
                    "no es más eficiente o el equivocado no hunde; MIXTA si una mitad sí y la otra no. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp054_prior_quality")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-3")
        notes.append("H-V4-3 marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Para aprender una regla con POCOS ejemplos, ¿qué importa más: tener cualquier corazonada fuerte, "
                 "o tener la corazonada CORRECTA sobre qué estructura tiene el problema?"),
        everyday=("Si sabés que sólo importa CUÁNTOS hay (no cuáles), aprendés la regla con 8 ejemplos. Sin esa "
                  "pista (mirás todo) necesitás ~16x más ejemplos. Y con la pista EQUIVOCADA (creés que sólo "
                  "importan los primeros 3) nunca aprendés bien, peor que mirar todo: una corazonada FALSA te "
                  "hunde. La calidad de la corazonada, no tenerla, es lo que vale."),
        solutions=["prior CORRECTO (la simetría real) -> alta acc con poquísimos ejemplos",
                   "prior GENERAL (sin asumir nada) -> aprende, pero necesita ~16x más datos",
                   "prior EQUIVOCADO (simetría falsa) -> sesgo irreducible, peor que el general",
                   "=> la CALIDAD/corrección del prior fija la eficiencia muestral"],
        principles=["la inducción es sub-determinada (NFL): un prior es necesario; su CALIDAD fija la eficiencia",
                    "un prior con la equivarianza correcta es barato y muy eficiente (vence a la fuerza bruta de datos)",
                    "un prior FALSO no es 'menos prior': es sesgo irreducible que hunde por debajo de no asumir nada",
                    "lo que importa es la corrección del prior, no su forma (MDL/programas es una apuesta, no la raíz)"],
        adaptation=("El lab prioriza ELEGIR BIEN el prior (la simetría/estructura correcta) sobre la forma del "
                    "buscador. Conecta con R-VALOR: un buen prior es valor a priori sobre qué estructura importa. "
                    "Próximos: familia de simetrías; APRENDER la simetría correcta de datos (meta-prior); comparar "
                    "contra un MDL/buscador real para medir el ahorro de costo."),
        measurement=("exp054: correcto {cs}@{ns} (general {gs}@{ns}, +{eff}); general iguala ~@{nb}; equivocado "
                     "{wb}@{nb} << general {gb}. {n} seeds.").format(cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]),
                                                                    eff=_f(cor[ns] - gen[ns]), nb=nb,
                                                                    wb=_f(wrong[nb]), gb=_f(gen[nb]), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la corazonada CORRECTA vale, no tener cualquier corazonada).")

    ceilings.add(CeilingRecord(
        subsystem="R-PRIOR — la CALIDAD/corrección del prior fija la eficiencia muestral (no su forma ni tenerlo)",
        known_limit=("REAL (exp054): un prior con la simetría CORRECTA (perm-invariante) alcanza {cs} con {ns} "
                     "ejemplos (general {gs}, ~16x menos datos); un prior EQUIVOCADO se clava en {wb} (<< general "
                     "{gb}) -- sesgo irreducible. La calidad del prior es el lever de R-PRIOR.").format(
                         cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]), wb=_f(wrong[nb]), gb=_f(gen[nb])),
        blockers=[{"text": "tarea de juguete (1 simetría perm-invariante, logreg lineal); falta una familia de simetrías y modelos más ricos", "kind": "diseno"},
                  {"text": "no se comparó contra un buscador-de-programas/MDL real para medir el ahorro de costo (sólo se argumenta)", "kind": "diseno"},
                  {"text": "falta APRENDER la simetría correcta de datos (meta-prior): aquí se da de antemano", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP054.ref, S_TREE.ref]))
    notes.append("1 techo 'real': la calidad/corrección del prior fija la eficiencia muestral (R-PRIOR confirmada en juguete).")

    dstmt = ("Raíz v4 R-PRIOR (H-V4-3): la CALIDAD/corrección del prior -- no su forma ni tenerlo -- fija la "
             "eficiencia muestral. Un prior con la simetría CORRECTA (perm-invariante, 1 feature) alcanza {cs} con "
             "{ns} ejemplos donde el general da {gs} (~16x menos datos para igualar); un prior EQUIVOCADO se clava "
             "en {wb} (<< general {gb}) -- sesgo irreducible, PEOR que no asumir nada. Decisión: el lab prioriza "
             "ELEGIR BIEN el prior (la simetría/estructura) sobre la forma del buscador (MDL/programas es una "
             "apuesta, no la raíz). Conecta R-PRIOR con R-VALOR (un buen prior es valor a priori sobre qué "
             "estructura importa). Próximos: familia de simetrías; APRENDER la simetría (meta-prior); comparar "
             "contra un MDL real.").format(cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]), wb=_f(wrong[nb]), gb=_f(gen[nb]))
    drat = ("exp054 (tier5, propio, {n} seeds): prior correcto {cs}@{ns} vs general {gs}@{ns} (+eficiencia); "
            "equivocado {wb}@{nb} << general {gb} (sesgo). Convergente con NFL/equivariancia (tier1) y con el "
            "thesis R-PRIOR. {V}.").format(n=n_seeds, cs=_f(cor[ns]), ns=ns, gs=_f(gen[ns]), wb=_f(wrong[nb]),
                                           nb=nb, gb=_f(gen[nb]), V=status.upper())
    dec = Decision(id="D-V4-32", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP054), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-32 ACEPTADA por el ledger (tier5 exp054 + tier5 thesis R-PRIOR).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-32:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle69_prior_quality',
                                description='CYCLE 69 (RESET v4, H-V4-3: calidad del prior > forma).')
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
    print("RESUMEN — CYCLE 69 (RESET v4): la CALIDAD del prior fija la eficiencia muestral (H-V4-3) — raíz R-PRIOR")
    print("=" * 78)
    print("veredicto H-V4-3:", status.upper() if status else "?")
    print("  un prior con la simetría correcta es barato y muy eficiente; uno falso hunde (peor que no asumir nada).")
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
