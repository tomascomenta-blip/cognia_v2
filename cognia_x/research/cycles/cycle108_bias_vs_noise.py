r"""
cycle108_bias_vs_noise.py — CICLO 108 (RESET v4, rama R-VALOR, calidad del estimador: SESGO vs RUIDO): H-V4-8m por las
compuertas del engine. REFUTADA con REVERSIÓN informativa: la hipótesis era que un SESGO sistemático del estimador de
valor degrada la asignación (ranking) MÁS que el RUIDO equivalente. RESULTADO al revés: a error RMS igualado, un sesgo
por-tipo (OFFSET CONSTANTE) es BENIGNO -- preserva el ORDEN DENTRO de cada tipo (sólo desplaza tipos entre sí), así que el
top-k aún toma los mejores; el RUIDO aleatorio corrompe TODOS los órdenes y es PEOR a σ alto. => lo que daña la asignación
es el error que ROMPE EL ORDEN (ruido, o sesgo NO-monótono), no un offset sistemático order-preserving. Refina la
intuición 'bias peor que noise' y conecta con 106 (transformaciones monótonas preservan el ranking).

DERIVA de exp092_bias_vs_noise/results/results.json.

Correr (DESPUÉS de exp092):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp092_bias_vs_noise.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle108_bias_vs_noise
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle108_bias_vs_noise')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp092_bias_vs_noise', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="robustez del RANKING: argmax/top-k es invariante a transformaciones que preservan el ORDEN; un offset constante por grupo preserva el orden intra-grupo; sólo el error que ROMPE el orden (ruido, no-monotonía) degrada el ranking", obtained=False,
                     claim=("El argmax/top-k depende sólo del ORDEN. Una transformación que preserva el orden (offset "
                            "constante, monótona) no cambia el ranking dentro del grupo afectado; sólo el error que ROMPE "
                            "el orden (ruido aleatorio, sesgo no-monótono/correlacionado con el valor) degrada la "
                            "selección. Un sesgo CONSTANTE puede mis-rankear ENTRE grupos pero preserva el orden DENTRO. "
                            "(Principio; cf. CYCLE 106.)"))
S_EXP090 = Source(tier=5, ref="cognia_x/experiments/exp090_calibration_decisions", obtained=True,
                  claim=("CYCLE 106 mostró que una transformación MONÓTONA del valor preserva el ranking (calibración "
                         "irrelevante para top-k). H-V4-8m testea si un SESGO sistemático (no-monótono entre tipos) daña "
                         "la asignación más que el ruido."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp092 primero): " + results_path)

    gaps = sm['gaps_noisy_minus_biased']
    gap_hi = sm['gap_hi']
    g = sm['grid']
    n_seeds = data['args']['seeds']
    gaps_txt = ", ".join("σ{}={}".format(s, _f(v)) for s, v in gaps.items())

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim092 = ("exp092 (propio, {n} seeds, numpy): a error RMS IGUALADO, el sesgo por-tipo (offset constante) NO degrada "
                "más que el ruido; a σ alto es MEJOR (brechas noisy−biased: {gt}). El offset constante preserva el orden "
                "INTRA-tipo; el ruido corrompe todos los órdenes. La hipótesis 'bias peor que noise' queda REFUTADA "
                "(revertida).").format(n=n_seeds, gt=gaps_txt)
    S_EXP092 = Source(tier=5, ref="cognia_x/experiments/exp092_bias_vs_noise", obtained=True, claim=claim092)
    for src in (S_PRINCIPLE, S_EXP090, S_EXP092):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 robustez del ranking al orden; S_EXP090 tier5 monótona-preserva-ranking de 106; S_EXP092 tier5 dato propio).")

    ev_for = [S_EXP092.ref, S_PRINCIPLE.ref]      # la evidencia APOYA el principio order-preserving (que REFUTA la hipótesis)
    ev_against = [S_EXP092.ref]
    advtext = ("{V} con REVERSIÓN informativa: la hipótesis (basada en la intuición y en el sesgo del verificador de CYCLE "
               "55) era que un SESGO SISTEMÁTICO del estimador de valor degrada la asignación (ranking) MÁS que el RUIDO "
               "equivalente (el sesgo no se promedia). RESULTADO al REVÉS: a error RMS IGUALADO, el sesgo por-TIPO (un "
               "OFFSET CONSTANTE, +σ a t=0, −σ a t=1) NO degrada más; a σ alto el SESGADO es MEJOR que el ruidoso (brechas "
               "noisy−biased por σ: {gt} -> negativas a σ alto). MECANISMO: un offset CONSTANTE por tipo PRESERVA el ORDEN "
               "DENTRO de cada tipo (sólo desplaza los tipos entre sí), así que el top-k todavía toma los MEJORES ítems "
               "de cada tipo (su ranking intra-tipo está intacto); el RUIDO ALEATORIO, en cambio, corrompe TODAS las "
               "comparaciones -> mete ítems genuinamente de bajo valor. => lo que daña la asignación (ranking/top-k) es "
               "el error que ROMPE EL ORDEN (ruido aleatorio, o un sesgo NO-monótono/correlacionado con el valor), NO un "
               "sesgo sistemático ORDER-PRESERVING. REFINA la intuición 'bias peor que noise': un sesgo CONSTANTE es "
               "BENIGNO para rankear (consistente con CYCLE 106: transformaciones monótonas preservan el ranking); sólo "
               "el sesgo que DISTORSIONA el orden (no-monótono) sería dañino -- y ESE es el caso del verificador de CYCLE "
               "55 (off-by-one cambia qué se acepta, distorsiona). LECCIÓN: al juzgar la calidad de un estimador de valor "
               "para ASIGNAR, no basta la magnitud del error ni 'sesgo vs ruido'; importa si el error PRESERVA o ROMPE el "
               "ORDEN. EVIDENCIA: el principio order-preserving (tier2) PREDECÍA esto y la hipótesis ingenua no lo "
               "consideró. Caveats: sesgo modelado como offset constante por tipo (el caso order-preserving); un sesgo "
               "no-monótono daría el resultado opuesto -- no testeado aquí; valor escalar, top-k, numpy/juguete.").format(
                   V=status.upper(), gt=gaps_txt)

    hyp = Hypothesis(
        id="H-V4-8m",
        statement=("(Hipótesis original) un SESGO sistemático del estimador de valor degrada la asignación (ranking) MÁS "
                   "que el RUIDO equivalente a RMS igualado. (REFUTADA: un sesgo CONSTANTE order-preserving degrada MENOS "
                   "que el ruido; lo que daña el ranking es el error que ROMPE el orden, no el sesgo per se.)"),
        prediction=("APOYADA si biased << noisy (>+0.05) a σ moderado/alto y la brecha crece; REFUTADA si biased ≈ o > "
                    "noisy (el sesgo constante no es peor / es mejor). (Pre-registrada, numpy, 48 seeds, RMS igualado.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp092_bias_vs_noise")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8m")
        notes.append("H-V4-8m marcada '{}' con DoD completo (reversión: el sesgo order-preserving es benigno).".format(status))

    analogy = AnalogyRecord(
        problem=("Mi medidor de 'qué tan buena' es cada opción tiene un defecto: o bien le mete RUIDO aleatorio a cada "
                 "medición, o bien SUBE todas las del grupo A y BAJA todas las del grupo B por igual. ¿Cuál me arruina "
                 "más para ELEGIR las mejores?"),
        everyday=("Me arruina más el RUIDO aleatorio. Subir/bajar un grupo entero por igual (offset constante) DENTRO del "
                  "grupo deja el orden intacto -- sigo eligiendo las mejores de cada grupo; sólo me confundo de cuántas "
                  "tomar de cada grupo. El ruido aleatorio, en cambio, me revuelve TODO el orden y me hace agarrar "
                  "opciones genuinamente malas. Lo que importa para elegir no es si el defecto es 'sistemático' o "
                  "'aleatorio', sino si me ROMPE EL ORDEN."),
        solutions=["sesgo constante por grupo (order-preserving): benigno para elegir (orden intra-grupo intacto)",
                   "ruido aleatorio: rompe todos los órdenes -> agarro malas (peor a error alto)",
                   "sesgo NO-monótono (correlacionado con el valor): SÍ rompe el orden -> dañino (no testeado)",
                   "lo que daña la asignación es el error que ROMPE EL ORDEN, no 'sesgo vs ruido'"],
        principles=["el top-k depende sólo del ORDEN; un offset constante por grupo preserva el orden intra-grupo",
                    "el ruido aleatorio rompe TODAS las comparaciones -> degrada el ranking más que un offset constante",
                    "lo que daña la asignación es el error que ROMPE el orden (ruido / sesgo no-monótono), no el sesgo per se",
                    "refina 'bias peor que noise' (intuición ingenua) y CYCLE 55 (el sesgo del verificador dañaba porque distorsiona qué se acepta)"],
        adaptation=("El lab CORRIGE una intuición: al juzgar la calidad de un estimador de valor para ASIGNAR, importa si "
                    "el error PRESERVA o ROMPE el ORDEN, no si es 'sesgo' o 'ruido'. Un sesgo constante order-preserving "
                    "es benigno para rankear (cf. 106); el ruido y el sesgo no-monótono dañan. Política: priorizar "
                    "reducir el error ORDER-DISRUPTING del estimador de valor (ruido fino, sesgo correlacionado), no los "
                    "offsets sistemáticos constantes. Próximo: sesgo NO-monótono (correlacionado con el valor) -> "
                    "¿confirma que SÓLO el order-breaking daña?; el caso de decisiones de UMBRAL (donde el offset SÍ "
                    "importa, 106); y SCALE."),
        measurement=("exp092 ({n} seeds): brechas noisy−biased por σ: {gt} (a σ alto el sesgado es MEJOR -> hipótesis "
                     "REFUTADA/revertida).").format(n=n_seeds, gt=gaps_txt),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (medidor con ruido vs offset por grupo: el ruido arruina más para elegir).")

    kl = ("REAL (exp092): a error RMS IGUALADO, un sesgo por-tipo (OFFSET CONSTANTE order-preserving) NO degrada la "
          "asignación (ranking) más que el ruido; a σ alto es MEJOR (brechas noisy−biased: {gt}). Lo que daña el ranking "
          "es el error que ROMPE el ORDEN (ruido / sesgo no-monótono), no un offset sistemático. REFUTA la hipótesis "
          "ingenua 'bias peor que noise'. TECHO: sesgo modelado como offset constante (order-preserving); un sesgo "
          "no-monótono daría lo opuesto; para decisiones de UMBRAL el offset SÍ importa (106); valor escalar, top-k.").format(gt=gaps_txt)
    ceilings.add(CeilingRecord(
        subsystem="Calidad del estimador de valor para ASIGNAR — lo que daña el ranking es el error que ROMPE el ORDEN (ruido / sesgo no-monótono), no un sesgo constante order-preserving (refuta 'bias peor que noise')",
        known_limit=kl,
        blockers=[{"text": "el sesgo se modeló como OFFSET CONSTANTE por tipo (order-preserving intra-tipo); un sesgo NO-monótono/correlacionado con el valor SÍ rompería el orden y daría el resultado opuesto -- no testeado", "kind": "diseno"},
                  {"text": "el resultado es para decisiones de RANKING (top-k); para decisiones de UMBRAL/costo el offset constante SÍ importa (CYCLE 106) -- la conclusión es decisión-dependiente", "kind": "diseno"},
                  {"text": "valor escalar, top-k, numpy/juguete; no integrado con el lazo cerrado real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP092.ref, S_EXP090.ref]))
    notes.append("1 techo 'real': lo que daña la asignación es el error order-breaking, no el sesgo constante (refuta la hipótesis ingenua).")

    dstmt = ("North-Star R-VALOR (calidad del estimador para ASIGNAR -- corrige una intuición): lo que daña la asignación "
             "(ranking/top-k) es el error que ROMPE el ORDEN (ruido aleatorio, o sesgo NO-monótono/correlacionado con el "
             "valor), NO un sesgo SISTEMÁTICO constante order-preserving (que de hecho degrada MENOS que el ruido "
             "equivalente). Decisión: al evaluar/mejorar un estimador de valor para asignar, priorizar reducir el error "
             "ORDER-DISRUPTING (ruido fino, sesgo correlacionado), no los offsets constantes; recordar que para decisiones "
             "de UMBRAL/costo (101/104) el offset SÍ importa (106). REFUTA la hipótesis ingenua 'bias peor que noise' y "
             "afina la lección de CYCLE 55 (el sesgo del verificador dañaba porque DISTORSIONA qué se acepta, no por ser "
             "sesgo). Próximo: sesgo no-monótono; y SCALE.")
    drat = ("exp092 (tier5, propio, {n} seeds, numpy): a RMS igualado biased NO < noisy; a σ alto biased > noisy (brechas "
            "noisy−biased {gt}). Convergente con robustez-del-ranking-al-orden (tier2) y con la monótona-preserva-ranking "
            "de CYCLE 106 (tier5). REFUTADA la hipótesis 'bias peor que noise'; lo que daña es el error order-breaking.").format(
                n=n_seeds, gt=gaps_txt)
    dec = Decision(id="D-V4-70", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP092), _to_plain(S_EXP090)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-70 ACEPTADA por el ledger (tier5 exp092 + tier5 exp090).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-70:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle108_bias_vs_noise',
                                description='CYCLE 108 (RESET v4, H-V4-8m: REFUTADA con reversión -- el sesgo constante order-preserving daña MENOS que el ruido; lo que daña es el error que rompe el orden).')
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
    print("RESUMEN — CYCLE 108 (RESET v4): REFUTADA con reversión -- el sesgo constante daña MENOS que el ruido; lo que daña es el error que ROMPE el orden (H-V4-8m)")
    print("=" * 78)
    print("veredicto H-V4-8m:", status.upper() if status else "?")
    print("  un offset constante por tipo preserva el orden intra-tipo (benigno); el ruido corrompe todo el ranking. Refina 'bias peor que noise'.")
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
