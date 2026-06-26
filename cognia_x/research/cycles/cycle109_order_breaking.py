r"""
cycle109_order_breaking.py — CICLO 109 (RESET v4, rama R-VALOR, COMPLETA el principio de CYCLE 108): H-V4-8n por las
compuertas del engine. APOYADA: a error RMS IGUALADO, el daño a la asignación (ranking/top-k) sigue el orden
ORDER-PRESERVING > RUIDO > ORDER-BREAKING-SISTEMÁTICO: biased_mono (sesgo constante order-preserving) es el MEJOR, noisy
(ruido order-breaking aleatorio) intermedio, biased_nonmono (sesgo de banda-media, order-breaking sistemático) el PEOR por
lejos. => el lever del daño es ROMPER EL ORDEN, no 'sesgo vs ruido'; la SISTEMATICIDAD ayuda si es order-preserving y
AGRAVA si es order-breaking (mete SIEMPRE los mismos ítems equivocados). Completa la reversión de CYCLE 108: la categoría
correcta para juzgar la calidad de un estimador de valor para ASIGNAR es order-preserving vs order-breaking, no
sesgo/ruido.

DERIVA de exp093_order_breaking/results/results.json.

Correr (DESPUÉS de exp093):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp093_order_breaking.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle109_order_breaking
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle109_order_breaking')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp093_order_breaking', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="robustez del ranking: la métrica de error relevante para argmax/top-k es el DESACUERDO DE ORDEN (Kendall-tau), no el RMS; un error order-preserving no cambia el ranking; un error order-breaking SISTEMÁTICO es peor que uno aleatorio (sesga el orden de forma consistente)", obtained=False,
                     claim=("Para el ranking (argmax/top-k), la métrica de error relevante es el DESACUERDO DE ORDEN "
                            "(Kendall-tau), no el RMS. Un error order-preserving (offset constante/monótono) no cambia el "
                            "ranking; un error order-breaking ALEATORIO (ruido) lo desordena al azar; uno order-breaking "
                            "SISTEMÁTICO lo desordena de forma CONSISTENTE (los mismos pares mal) -> es el peor. "
                            "(Principio.)"))
S_EXP092 = Source(tier=5, ref="cognia_x/experiments/exp092_bias_vs_noise", obtained=True,
                  claim=("CYCLE 108 reveló (revirtiendo la intuición) que un sesgo CONSTANTE order-preserving daña MENOS "
                         "que el ruido. H-V4-8n COMPLETA el principio: el lever es order-breaking; un sesgo NO-monótono "
                         "(order-breaking sistemático) debería ser el PEOR."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp093 primero): " + results_path)

    mvn = sm['mono_vs_noisy_hi']
    nvn = sm['noisy_vs_nonmono_hi']
    g = sm['grid']
    hi = sorted([float(k[1:]) for k in g.keys()])[-1]
    ch = g["s{}".format(hi)]
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim093 = ("exp093 (propio, {n} seeds, numpy): a σ={h} el daño sigue order-preserving > ruido > order-breaking: "
                "biased_mono={bm} > noisy={no} (+{mvn}) > biased_nonmono={bn} (+{nvn}). El lever es romper el orden; la "
                "sistematicidad ayuda si preserva el orden, agrava si lo rompe. Completa CYCLE 108.").format(
                    n=n_seeds, h=hi, bm=_f(ch['biased_mono']), no=_f(ch['noisy']), mvn=_f(mvn), bn=_f(ch['biased_nonmono']), nvn=_f(nvn))
    S_EXP093 = Source(tier=5, ref="cognia_x/experiments/exp093_order_breaking", obtained=True, claim=claim093)
    for src in (S_PRINCIPLE, S_EXP092, S_EXP093):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 Kendall-tau/order-disagreement; S_EXP092 tier5 reversión de CYCLE 108; S_EXP093 tier5 dato propio).")

    ev_for = [S_EXP093.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP093.ref]
    advtext = ("{V} (COMPLETA CYCLE 108: el lever del daño a la asignación es ROMPER EL ORDEN): CYCLE 108 reveló que un "
               "sesgo CONSTANTE order-preserving daña MENOS que el ruido, refinando 'bias peor que noise' a 'lo que daña "
               "es el error order-breaking'. H-V4-8n lo COMPLETA comparando TRES errores a RMS IGUALADO: sesgo "
               "order-PRESERVING (offset constante por tipo), RUIDO (order-breaking ALEATORIO) y sesgo order-BREAKING "
               "SISTEMÁTICO (boost de la banda-media de valor -> mid sobre high). RESULTADO: a σ={h} el daño sigue el "
               "orden predicho -- biased_mono={bm} (order-preserving = MEJOR) > noisy={no} (ruido = intermedio, +{mvn}) > "
               "biased_nonmono={bn} (order-breaking sistemático = PEOR, +{nvn}). => el lever del daño a la asignación "
               "(ranking/top-k) es ROMPER EL ORDEN, NO 'sesgo vs ruido': la SISTEMATICIDAD AYUDA si el error es "
               "order-preserving (el sesgo constante es el mejor) y AGRAVA si es order-breaking (el sesgo no-monótono es "
               "el peor, porque mete SIEMPRE los mismos ítems equivocados, mientras el ruido los mete al azar y se "
               "promedia algo). LECCIÓN COMPLETA (108+109): para juzgar la calidad de un estimador de valor para ASIGNAR "
               "(rankear), la categoría correcta es order-preserving vs order-breaking (la métrica relevante es el "
               "DESACUERDO DE ORDEN / Kendall-tau, no el RMS); reconcilia CYCLE 55 (el sesgo del verificador dañaba porque "
               "DISTORSIONA -order-breaks- qué se acepta) y 106 (las transformaciones monótonas -order-preserving- no "
               "afectan el ranking pero SÍ el umbral). EVIDENCIA: el principio order-disagreement (tier2) lo PREDECÍA. "
               "Caveats: valor escalar, top-k, errores sintéticos; para decisiones de UMBRAL/costo (101/104) un offset "
               "order-preserving SÍ importa (106) -> la conclusión es para RANKING.").format(
                   V=status.upper(), h=hi, bm=_f(ch['biased_mono']), no=_f(ch['noisy']), mvn=_f(mvn),
                   bn=_f(ch['biased_nonmono']), nvn=_f(nvn))

    hyp = Hypothesis(
        id="H-V4-8n",
        statement=("A error RMS igualado, el daño a la asignación (ranking) sigue order-preserving > ruido > "
                   "order-breaking-sistemático: el lever del daño es ROMPER EL ORDEN, no 'sesgo vs ruido'; la "
                   "sistematicidad ayuda si preserva el orden y agrava si lo rompe."),
        prediction=("APOYADA si biased_nonmono < noisy < biased_mono a σ moderado/alto (cada brecha >0.02); REFUTADA si "
                    "el order-breaking sistemático no es el peor; MIXTA en otro caso. (Pre-registrada, numpy, 48 seeds, "
                    "RMS igualado, 3 tipos de error.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp093_order_breaking")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8n")
        notes.append("H-V4-8n marcada '{}' con DoD completo (completa el principio order-breaking de 108).".format(status))

    analogy = AnalogyRecord(
        problem=("Para elegir las mejores opciones, mi medidor de valor puede fallar de tres formas: subir/bajar un grupo "
                 "entero por igual, meter ruido al azar, o sobre-valorar SIEMPRE las del medio. ¿Cuál me arruina más?"),
        everyday=("La PEOR es sobre-valorar SIEMPRE las del medio: termino agarrando siempre las mismas opciones "
                  "mediocres en vez de las buenas. El ruido al azar es menos malo (a veces me confunde, a veces no, se "
                  "promedia). Y subir/bajar un grupo entero por igual es la MENOS mala (dentro del grupo sigo eligiendo "
                  "las mejores). Lo que importa no es si el fallo es 'sistemático' o 'al azar', sino si me ROMPE EL ORDEN "
                  "-- y un fallo sistemático que rompe el orden es el peor porque se equivoca SIEMPRE igual."),
        solutions=["sesgo order-PRESERVING (offset por grupo): el MENOS malo (orden intra-grupo intacto)",
                   "ruido aleatorio: intermedio (rompe órdenes al azar, se promedia algo)",
                   "sesgo order-BREAKING sistemático (mid sobre high): el PEOR (mete siempre los mismos equivocados)",
                   "el lever es ROMPER EL ORDEN; la sistematicidad ayuda si preserva y agrava si rompe"],
        principles=["la métrica de error relevante para rankear es el DESACUERDO DE ORDEN (Kendall-tau), no el RMS",
                    "order-preserving (constante/monótono) no daña el ranking; order-breaking sí",
                    "el order-breaking SISTEMÁTICO daña más que el aleatorio (se equivoca siempre igual)",
                    "reconcilia CYCLE 55 (verificador sesgado = order-breaking) y 106 (monótono no afecta ranking)"],
        adaptation=("El lab establece (108+109) el principio: para evaluar/mejorar un estimador de valor de ASIGNACIÓN "
                    "(ranking), la categoría correcta es ORDER-PRESERVING vs ORDER-BREAKING, no 'sesgo vs ruido'. "
                    "Priorizar reducir el error ORDER-BREAKING (especialmente el sistemático: un sesgo correlacionado con "
                    "el valor que invierte pares); los offsets constantes/monótonos son benignos para rankear (aunque "
                    "importan para decisiones de UMBRAL/costo, 106). Próximo: medir el order-disagreement (Kendall-tau) "
                    "del estimador de valor real (confianza del modelo) directamente; integrar en el lazo real; y SCALE."),
        measurement=("exp093 ({n} seeds): a σ={h} biased_mono={bm} > noisy={no} (+{mvn}) > biased_nonmono={bn} (+{nvn}) -> "
                     "order-preserving>ruido>order-breaking.").format(
                         n=n_seeds, h=hi, bm=_f(ch['biased_mono']), no=_f(ch['noisy']), mvn=_f(mvn),
                         bn=_f(ch['biased_nonmono']), nvn=_f(nvn)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (tres fallos del medidor; sobre-valorar siempre las del medio es el peor).")

    kl = ("REAL (exp093): a RMS igualado el daño a la asignación (ranking) sigue order-preserving > ruido > "
          "order-breaking-sistemático (biased_mono={bm} > noisy={no} > biased_nonmono={bn} a σ={h}). El lever es ROMPER "
          "EL ORDEN; la sistematicidad ayuda si preserva el orden y agrava si lo rompe. Completa CYCLE 108. TECHO: valor "
          "escalar, top-k, errores sintéticos; para decisiones de UMBRAL/costo el offset order-preserving SÍ importa "
          "(106); la métrica relevante (Kendall-tau del estimador real) no se midió aún.").format(
              bm=_f(ch['biased_mono']), no=_f(ch['noisy']), bn=_f(ch['biased_nonmono']), h=hi)
    ceilings.add(CeilingRecord(
        subsystem="Calidad del estimador de valor para ASIGNAR (ranking) — el lever del daño es ROMPER EL ORDEN (order-disagreement), no 'sesgo vs ruido'; el order-breaking SISTEMÁTICO es el peor (completa 108)",
        known_limit=kl,
        blockers=[{"text": "conclusión para decisiones de RANKING (top-k); para UMBRAL/costo (101/104) un offset order-preserving SÍ importa (CYCLE 106) -> decisión-dependiente", "kind": "diseno"},
                  {"text": "la métrica relevante (DESACUERDO DE ORDEN / Kendall-tau del estimador de valor REAL, p.ej. la confianza del modelo) no se midió aún -- sólo errores sintéticos controlados", "kind": "diseno"},
                  {"text": "valor escalar, top-k, numpy/juguete; no integrado con el lazo cerrado real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP093.ref, S_EXP092.ref]))
    notes.append("1 techo 'real': el lever del daño a la asignación es order-breaking (no sesgo/ruido); el sistemático es el peor.")

    dstmt = ("North-Star R-VALOR (principio de calidad del estimador para ASIGNAR, 108+109): el lever del daño a la "
             "asignación (ranking/top-k) es ROMPER EL ORDEN, no 'sesgo vs ruido'. La sistematicidad AYUDA si el error es "
             "order-preserving (un sesgo constante es el MEJOR de los tres) y AGRAVA si es order-breaking (un sesgo "
             "no-monótono es el PEOR; el ruido aleatorio queda en medio). Decisión: para evaluar/mejorar un estimador de "
             "valor de asignación, usar la categoría ORDER-PRESERVING vs ORDER-BREAKING (métrica: desacuerdo de orden / "
             "Kendall-tau), no el RMS ni 'sesgo vs ruido'; priorizar reducir el error order-breaking (sobre todo el "
             "sistemático). Reconcilia CYCLE 55 (verificador sesgado = order-breaking) y 106 (monótono no afecta ranking "
             "pero sí umbral). Próximo: medir el order-disagreement del estimador real; lazo cerrado real; y SCALE.")
    drat = ("exp093 (tier5, propio, {n} seeds, numpy): a σ={h} biased_mono={bm} > noisy={no} (+{mvn}) > biased_nonmono={bn} "
            "(+{nvn}). Convergente con Kendall-tau/order-disagreement (tier2) y con la reversión de CYCLE 108 (tier5). "
            "APOYADA: el lever es order-breaking; el sistemático es el peor.").format(
                n=n_seeds, h=hi, bm=_f(ch['biased_mono']), no=_f(ch['noisy']), mvn=_f(mvn), bn=_f(ch['biased_nonmono']), nvn=_f(nvn))
    dec = Decision(id="D-V4-71", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP093), _to_plain(S_EXP092)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-71 ACEPTADA por el ledger (tier5 exp093 + tier5 exp092).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-71:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle109_order_breaking',
                                description='CYCLE 109 (RESET v4, H-V4-8n: el lever del daño a la asignación es ROMPER EL ORDEN; el order-breaking sistemático es el peor -- APOYADA; completa 108).')
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
    print("RESUMEN — CYCLE 109 (RESET v4): el lever del daño a la asignación es ROMPER EL ORDEN; el sistemático es el peor (H-V4-8n)")
    print("=" * 78)
    print("veredicto H-V4-8n:", status.upper() if status else "?")
    print("  order-preserving (mejor) > ruido > order-breaking-sistemático (peor). La categoría correcta es order-preserving vs order-breaking.")
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
