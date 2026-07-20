r"""
cycle74_adaptive_value_memory.py — CICLO 74 (RESET v4, arco "R-VALOR bajo realismo", CIERRE del sub-arco 72-73-74):
H-V4-5d por las compuertas del engine. El estimador de valor ELIGE su propia tasa de olvido: un meta-SELECTOR
full<->decay gateado por el hit-rate reciente de cada experto (endógeno, sin oráculo ni aviso de régimen) logra
NO-REGRET -- iguala al mejor experto en CADA régimen, lo que ningún decay FIJO logra en ambos.

H-V4-5d cierra la muleta #1 de CYCLE 73 (decay FIJO). Replica el selector de estrategia (CYCLE 66) sobre el
estimador de valor. DERIVA de exp058_adaptive_value_memory/results/results.json.

Correr (DESPUÉS de exp058):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp058_adaptive_value_memory.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle74_adaptive_value_memory
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle74_adaptive_value_memory')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp058_adaptive_value_memory', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_EXPERTS = Source(tier=1, ref="prediction with expert advice / tracking the best expert (fixed-share, multiplicative weights)", obtained=False,
                   claim=("Un meta-algoritmo que selecciona entre expertos según su desempeño observado logra "
                          "NO-REGRET respecto del mejor experto en retrospectiva (y del mejor en cada SEGMENTO bajo "
                          "switching/fixed-share). Vale aunque ningún experto fijo sea el mejor en todo el horizonte. "
                          "(Principio; converge con CYCLE 66 selector de estrategia.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (caveat CYCLE 73 decay-fijo + selector CYCLE 66)", obtained=True,
                claim=("El techo de CYCLE 73 (H-V4-5c) registró como blocker #1: 'el decay es FIJO; el óptimo "
                       "depende de la tasa de cambio -> falta decay ADAPTATIVO/meta'. CYCLE 66 mostró que ELEGIR la "
                       "estrategia (discreto) vence a modular la tasa. H-V4-5d aplica eso al estimador de valor."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp058 primero): " + results_path)
    st, ns = sm['stationary'], sm['nonstationary']
    full_s, dec_s, sel_s = st['lfu_full'], st['lfu_decay'], st['selector']
    full_n, dec_n, sel_n = ns['lfu_full'], ns['lfu_decay'], ns['selector']
    fd_s, fd_n = st['_selector_frac_decay'], ns['_selector_frac_decay']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim058 = ("exp058 (propio, {n} seeds, numpy): selector full<->decay gateado por el hit-rate reciente de cada "
                "experto (endógeno). ESTAC selector {ss} iguala a full {fs} (mejor; usa decay {fds}%). NO-ESTAC "
                "selector {sn} iguala a decay {dn} (mejor; usa decay {fdn}%). Ningún fijo es el mejor en ambos; el "
                "selector logra NO-REGRET. Detecta el régimen de su sorpresa.").format(
                    n=n_seeds, ss=_f(sel_s), fs=_f(full_s), fds=int(round(fd_s * 100)), sn=_f(sel_n), dn=_f(dec_n),
                    fdn=int(round(fd_n * 100)))
    S_EXP058 = Source(tier=5, ref="cognia_x/experiments/exp058_adaptive_value_memory", obtained=True, claim=claim058)
    for src in (S_EXPERTS, S_TREE, S_EXP058):
        ledger.add_source(src)
    notes.append("3 fuentes (S_EXPERTS tier1 expert-advice/no-regret; S_TREE tier5 caveat CYCLE 73 + selector 66; S_EXP058 tier5 dato propio).")

    ev_for = [S_EXP058.ref, S_TREE.ref]
    ev_against = [S_EXP058.ref]
    adv = ("{V} (CIERRA el sub-arco 72-73-74; cierra la muleta 'decay fijo' del 73): CYCLE 73 mostró el crossover "
           "(full gana sin cambio, decay con cambio) pero con decay FIJO. exp058 hace que el estimador ELIJA su tasa "
           "de olvido: corre AMBOS expertos en sombra y usa el de mayor hit-rate RECIENTE (EMA de sus PROPIOS "
           "aciertos -- endógeno, sin oráculo ni aviso de régimen). Resultado NO-REGRET: en ESTACIONARIO selector {ss} "
           "iguala al mejor (full {fs}; supera al fijo equivocado decay {ds}); en NO-ESTACIONARIO selector {sn} iguala "
           "al mejor (decay {dn}; supera a full {fn}). Ningún experto FIJO es el mejor en AMBOS, el selector sí. El "
           "diagnóstico confirma detección ENDÓGENA del régimen: usó decay {fdn}% del tiempo en no-estac. vs sólo "
           "{fds}% en estac. EVIDENCIA EN CONTRA (caveats honestos): (1) el selector NO supera al mejor experto (es "
           "selección, no mejora) y hereda el techo del oráculo; su valor es la ROBUSTEZ entre regímenes, no un techo "
           "más alto. (2) Sólo DOS expertos (full/decay); un continuo de tasas necesitaría más expertos o un meta-"
           "continuo (CYCLE 64 fue MIXTA ahí: el discreto es lo que funciona, cf. CYCLE 66). (3) cambio ABRUPTO "
           "recurrente; juguete (Pareto, n=50). CONCLUSIÓN: el estimador de valor endógeno elige QUÉ vale (frecuencia, "
           "72), CUÁNDO dejó de valer y a qué RITMO olvidar (selector, 74) -- todo de su propia experiencia. R-VALOR "
           "× OLVIDO queda cerrado endógenamente y SIN hiperparámetro de régimen.").format(
               V=status.upper(), ss=_f(sel_s), fs=_f(full_s), ds=_f(dec_s), sn=_f(sel_n), dn=_f(dec_n), fn=_f(full_n),
               fdn=int(round(fd_n * 100)), fds=int(round(fd_s * 100)))

    hyp = Hypothesis(
        id="H-V4-5d",
        statement=("Un meta-selector full<->decay gateado por el hit-rate reciente de cada experto (endógeno) logra "
                   "NO-REGRET en ambos regímenes: el estimador de valor elige su propia tasa de olvido sin saber el régimen."),
        prediction=("APOYADA si selector iguala al mejor experto en CADA régimen (full en estac., decay en no-estac., "
                    "dentro de 0.03) Y supera al experto FIJO equivocado en cada uno (+>0.02); REFUTADA si elige MAL "
                    "(peor que el fijo equivocado en algún régimen); MIXTA si adapta pero con regret. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp058_adaptive_value_memory")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5d")
        notes.append("H-V4-5d marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés dos asesores: uno se acuerda de TODO (bueno cuando los gustos no cambian) y otro sólo de lo "
                 "RECIENTE (bueno cuando cambian). No sabés si los gustos están cambiando. ¿A cuál le hacés caso?"),
        everyday=("Le hacés caso al que viene ACERTANDO últimamente. Si los gustos están quietos, el que se acuerda de "
                  "todo acierta más -> le hacés caso a ése. Si empiezan a cambiar, el de la memoria corta se recupera "
                  "primero y empieza a acertar más -> te pasás a ése. Así aciertas casi como el MEJOR asesor en cada "
                  "época, sin que nadie te avise de que la época cambió -- y eso ningún asesor fijo lo logra en las dos."),
        solutions=["selector (sigue al experto con mejor hit-rate reciente) -> no-regret: iguala al mejor en cada régimen",
                   "lfu_full (recuerda todo) -> mejor sin cambio, se confunde con cambio",
                   "lfu_decay (memoria corta) -> mejor con cambio, paga sin cambio",
                   "oracle_current (sabe el valor actual) -> cota superior; el selector hereda su techo, no lo supera"],
        principles=["elegir el experto por su desempeño observado reciente logra no-regret entre regímenes (expert-advice)",
                    "ningún hiperparámetro FIJO (decay) es óptimo en ambos regímenes; elegirlo endógenamente sí",
                    "la decisión es DISCRETA (cuál experto), no modular una tasa continua (cf. CYCLE 66 vs 64)",
                    "R-VALOR elige QUÉ vale (frecuencia), CUÁNDO dejó de valer y a qué RITMO olvidar -- todo endógeno"],
        adaptation=("El lab dirige la memoria con un estimador de valor que AUTO-selecciona su tasa de olvido por su "
                    "propio acierto reciente, sin hiperparámetro de régimen. Cierra el sub-arco R-VALOR-estimador "
                    "(72-73-74). Próximo: subir de frecuencia a un valor endógeno más rico (info-gain/confianza, "
                    "CYCLE 56-57) y/o escalar a un downstream no-IID; o pivotar a otra muleta del arco realismo."),
        measurement=("exp058: ESTAC selector {ss}~full {fs} (usa decay {fds}%) / NO-ESTAC selector {sn}~decay {dn} "
                     "(usa decay {fdn}%). {n} seeds.").format(
                         ss=_f(sel_s), fs=_f(full_s), fds=int(round(fd_s * 100)), sn=_f(sel_n), dn=_f(dec_n),
                         fdn=int(round(fd_n * 100)), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (hacele caso al asesor que viene acertando; así igualás al mejor en cada época).")

    kl = ("REAL (exp058): el estimador de valor ELIGE su tasa de olvido sin saber el régimen -- un selector full<->decay "
          "gateado por el hit-rate reciente de cada experto (endógeno) logra NO-REGRET: ESTAC selector {ss}~full {fs} "
          "(usa decay {fds}%); NO-ESTAC selector {sn}~decay {dn} (usa decay {fdn}%). Ningún decay fijo es el mejor en "
          "ambos; el selector sí. Cierra la muleta 'decay fijo' del CYCLE 73.").format(
              ss=_f(sel_s), fs=_f(full_s), fds=int(round(fd_s * 100)), sn=_f(sel_n), dn=_f(dec_n), fdn=int(round(fd_n * 100)))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x OLVIDO (cierre 72-73-74) — el estimador de valor AUTO-selecciona su tasa de olvido (no-regret)",
        known_limit=kl,
        blockers=[{"text": "el selector NO supera al mejor experto (selección, no mejora); hereda el techo del oráculo. Su valor es ROBUSTEZ entre regímenes", "kind": "diseno"},
                  {"text": "sólo DOS expertos (full/decay); un continuo de tasas necesitaría más expertos o un meta-continuo (CYCLE 64 MIXTA: el discreto es lo que funciona)", "kind": "diseno"},
                  {"text": "el valor estimado es FRECUENCIA pura; falta subir a info-gain/confianza (CYCLE 56-57) y a un downstream no-IID; cambio abrupto recurrente; juguete", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP058.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el estimador de valor auto-selecciona su tasa de olvido (no-regret); cierra el sub-arco 72-73-74.")

    dstmt = ("North-Star R-VALOR bajo realismo (CIERRA el sub-arco 72-73-74): el estimador de valor endógeno elige su "
             "PROPIA tasa de olvido. Un selector discreto full<->decay gateado por el hit-rate reciente de cada experto "
             "logra NO-REGRET: ESTAC selector {ss}~full {fs} (mejor; usa decay {fds}%), NO-ESTAC selector {sn}~decay "
             "{dn} (mejor; usa decay {fdn}%); ningún decay fijo es el mejor en ambos. Decisión: el lab AUTO-selecciona "
             "la tasa de olvido del estimador de valor por su propio acierto reciente, sin hiperparámetro de régimen. "
             "R-VALOR elige QUÉ vale (frecuencia, 72), CUÁNDO dejó de valer y a qué RITMO olvidar (selector, 74) -- todo "
             "de la propia experiencia. Próximo: valor endógeno más rico (info-gain/confianza) o escala no-IID.").format(
                 ss=_f(sel_s), fs=_f(full_s), fds=int(round(fd_s * 100)), sn=_f(sel_n), dn=_f(dec_n), fdn=int(round(fd_n * 100)))
    drat = ("exp058 (tier5, propio, {n} seeds): ESTAC selector {ss} iguala a full {fs}, supera a decay {ds}; NO-ESTAC "
            "selector {sn} iguala a decay {dn}, supera a full {fn}; usa decay {fds}%/{fdn}% (estac./no-estac.). "
            "Convergente con expert-advice/no-regret (tier1) y con el selector CYCLE 66 (tier5). {V}.").format(
                n=n_seeds, ss=_f(sel_s), fs=_f(full_s), ds=_f(dec_s), sn=_f(sel_n), dn=_f(dec_n), fn=_f(full_n),
                fds=int(round(fd_s * 100)), fdn=int(round(fd_n * 100)), V=status.upper())
    dec = Decision(id="D-V4-36", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP058), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-36 ACEPTADA por el ledger (tier5 exp058 + tier5 caveat CYCLE 73).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-36:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle74_adaptive_value_memory',
                                description='CYCLE 74 (RESET v4, H-V4-5d: el estimador de valor elige su tasa de olvido).')
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
    print("RESUMEN — CYCLE 74 (RESET v4): el estimador de valor elige su tasa de olvido (H-V4-5d) — cierra 72-73-74")
    print("=" * 78)
    print("veredicto H-V4-5d:", status.upper() if status else "?")
    print("  un selector full<->decay gateado por la sorpresa endógena logra NO-REGRET entre regímenes.")
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
