r"""
cycle46_abstention_noisy.py — CICLO 46 (RESET v4): H-V4-1k por las compuertas del engine.

H-V4-1k: ¿ABSTENERSE (decir "no sé") cuando ningún sample de un paso verifica convierte errores silenciosos
en abstenciones flagueadas, subiendo la PRECISIÓN-sobre-respondidas — incluso con verificador RUIDOSO per-step?
Cierra los dos cabos de exp031: el commit-de-basura que descarrila y el verificador perfecto. DERIVA de
exp032_abstention_noisy/results/results.json.

RESULTADO REAL: MIXTA (lever de HONESTIDAD, dependiente de régimen; 4 seeds). Curva K|vnoise->COMMIT/PREC/COV:
  2|0.0:0.252/1.000/0.248  2|0.1:0.217/0.647/0.317  2|0.2:0.169/0.295/0.338
  4|0.0:0.050/1.000/0.050  4|0.1:0.054/0.293/0.081  4|0.2:0.037/0.146/0.123
  6|0.0:0.013/1.000/0.010  6|0.1:0.002/0.125/0.017  6|0.2:0.004/0.083/0.021
  - FUNCIONA FUERTE a cadenas cortas + verificador decente: mejor régimen K=2/vn=0 -> precisión 1.000 vs
    commit 0.252 (+0.748) con cobertura útil 0.248; a vn=0.1 precisión 0.647 vs 0.217 (+0.43). Abstenerse hace
    que lo RESPONDIDO sea mucho más confiable (con verificador perfecto, las respondidas son 100% correctas).
  - PERO colapsa en el régimen DURO: a K=6 la cobertura cae a ~0.01-0.02 (abstiene casi todo) y bajo ruido la
    precisión se erosiona (falsos positivos pasan). En K=6/vn=0.1 gain +0.123 < margen y cobertura inútil.
  => abstenerse es un lever real de HONESTIDAD (precisión por cobertura) pero dependiente de régimen: paga con
     cadenas cortas y verificador decente; en cadenas largas o ruidosas abstiene todo / se deja engañar.

Correr (DESPUÉS de exp032):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp032_abstention_noisy.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle46_abstention_noisy
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle46_abstention_noisy')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp032_abstention_noisy', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_ABST = Source(tier=1, ref="selective-prediction/abstention", obtained=False,
                claim=("La predicción selectiva (abstenerse bajo baja confianza) sube la precisión sobre lo "
                       "respondido a costa de cobertura; un sistema honesto sabe cuándo NO sabe. (Principio, no "
                       "re-obtenido esta sesión.)"))
S_EXP031 = Source(tier=5, ref="cognia_x/experiments/exp031_adaptive_perstep", obtained=True,
                  claim=("exp031 (CYCLE 45): cuando un paso agota su presupuesto sin verificar, step-wise "
                         "commitea uno malo y descarrila en silencio; el verificador per-step era perfecto."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp032 primero): " + results_path)
    status = v.lower()
    curve = st['curve']
    hard = st['at_hard']
    best_key = st['best_regime']
    best = st['best']
    n_seeds = st['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP032 = Source(tier=5, ref="cognia_x/experiments/exp032_abstention_noisy", obtained=True,
                      claim=("exp032 (propio, {n} seeds, modelo HybridLM, cadena mod 20, verificador RUIDOSO "
                             "per-step): abstenerse cuando un paso no verifica sube la PRECISIÓN-sobre-respondidas. "
                             "Mejor régimen [{bk}]: precisión {bp} vs commit-siempre {bc} (+{bg}) con cobertura "
                             "{bv}. Régimen duro [K{km}/vn{vm}]: la cobertura colapsa a {hv} (abstiene todo) y "
                             "la precisión se erosiona bajo ruido.").format(
                                 n=n_seeds, bk=best_key, bp=_fmt(best['precision']), bc=_fmt(best['commit_always']),
                                 bg=_fmt(best['prec_gain']), bv=_fmt(best['coverage']), km=st['Kmax'],
                                 vm=st['vmod'], hv=_fmt(hard['coverage'])))
    for src in (S_ABST, S_EXP031, S_EXP032):
        ledger.add_source(src)
    notes.append("3 fuentes (S_ABST tier1 predicción selectiva; S_EXP031 tier5 commit-de-basura descarrila; S_EXP032 tier5 dato propio).")

    ev_for = [S_EXP032.ref]          # abstenerse SÍ sube la precisión-sobre-respondidas (lever real)
    ev_against = [S_EXP032.ref, S_EXP031.ref]   # pero la cobertura colapsa a K largo y la precisión se erosiona con ruido
    adv = ("MIXTA, lever de HONESTIDAD dependiente de régimen. A FAVOR: abstenerse cuando un paso no verifica "
           "convierte el error silencioso (commitear basura y descarrilar) en una abstención flagueada, subiendo "
           "FUERTE la precisión-sobre-respondidas — mejor régimen [{bk}]: precisión {bp} vs commit-siempre {bc} "
           "(+{bg}) con cobertura útil {bv}; con verificador perfecto lo respondido es 100% correcto. EN CONTRA "
           "(la razón del MIXTA): en el régimen DURO (K={km}, ruido {vm}) la cobertura COLAPSA a {hv} (abstiene "
           "casi todo -> inútil) y bajo ruido la precisión se erosiona (los falsos positivos pasan el filtro). "
           "Ataques considerados: (1) '¿la precisión 1.0 a vn=0 es trivial?' -> sí por construcción (verificador "
           "perfecto -> respondidas=verificadas=correctas); lo no-trivial es que la precisión sigue MUY por "
           "encima del commit-siempre a ruido MODERADO (0.647 vs 0.217 a vn=0.1, K=2). (2) '¿es sólo cambiar la "
           "métrica?' -> no: es precisión/cobertura, el trade-off real de la predicción selectiva. LECCIÓN: "
           "abstenerse es un lever real de honestidad (saber cuándo NO sé), pero su utilidad cae con la longitud "
           "(toda cadena larga tiene algún paso que falla -> abstiene todo) y con el ruido del verificador "
           "(conecta con 41/43: el lever depende de la calidad del verificador).").format(
               bk=best_key, bp=_fmt(best['precision']), bc=_fmt(best['commit_always']), bg=_fmt(best['prec_gain']),
               bv=_fmt(best['coverage']), km=st['Kmax'], vm=st['vmod'], hv=_fmt(hard['coverage']))

    hyp = Hypothesis(
        id="H-V4-1k",
        statement=("Abstenerse cuando un paso no verifica (con verificador ruidoso per-step) sube la precisión "
                   "sobre las cadenas respondidas vs commitear-siempre, a costa de cobertura."),
        prediction=("APOYADA si precisión-respondidas − accuracy-commit >= 0.15 en Kmax y ruido moderado con "
                    "cobertura >= 0.2; REFUTADA si no sube la precisión o abstiene todo en todo régimen; MIXTA "
                    "si sube fuerte pero la cobertura colapsa salvo en cadenas cortas/verificador bueno. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp032_abstention_noisy")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1k")
        notes.append("H-V4-1k marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("En una cuenta larga, si en un paso NINGÚN intento te convence, ¿escribís cualquier número o "
                 "decís 'no estoy seguro'?"),
        everyday=("Escribir cualquier número arrastra el error hasta el final (respuesta segura... y mal). Decir "
                  "'no sé' en ese paso cuesta no entregar esa cuenta, pero las que SÍ entregás son mucho más "
                  "confiables. Un buen estudiante sabe cuándo NO sabe — salvo que su 'sensación de seguridad' "
                  "(el verificador) esté rota, o el problema sea tan largo que SIEMPRE dude en algún paso."),
        solutions=["abstenerse al no verificar -> precisión-sobre-respondidas alta (1.0 con verificador perfecto)",
                   "commitear-siempre -> respuesta para todo pero descarrila (accuracy baja, error silencioso)",
                   "cadena LARGA -> casi siempre hay un paso que falla -> abstiene todo (cobertura ~0)",
                   "verificador RUIDOSO -> los falsos positivos pasan el filtro -> la precisión se erosiona"],
        principles=["abstenerse intercambia COBERTURA por PRECISIÓN: lo respondido es más confiable (honestidad)",
                    "convierte errores SILENCIOSOS en abstenciones FLAGUEADAS (saber cuándo no sé)",
                    "la utilidad del lever cae con la longitud de cadena (toda cadena larga falla en algún paso)",
                    "y con el ruido del verificador (la abstención es tan buena como el verificador que la dispara)"],
        adaptation=("Da al integrador un modo HONESTO: abstenerse por paso en vez de arrastrar error. Para que "
                    "sirva en cadenas largas hace falta (a) mejorar la precisión por paso (más presupuesto / "
                    "mejor modelo) y (b) un verificador confiable o la política adaptativa de 43 disparando la "
                    "abstención. Próximo: backtracking (reintentar un paso fallido en vez de abstener la cadena "
                    "entera) para recuperar cobertura sin perder precisión."),
        measurement=("exp032: mejor régimen [{bk}] precisión {bp} vs commit {bc} (+{bg}), cobertura {bv}; "
                     "régimen duro [K{km}/vn{vm}] cobertura {hv}. {n} seeds.").format(
                         bk=best_key, bp=_fmt(best['precision']), bc=_fmt(best['commit_always']),
                         bg=_fmt(best['prec_gain']), bv=_fmt(best['coverage']), km=st['Kmax'], vm=st['vmod'],
                         hv=_fmt(hard['coverage']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (cuenta larga: decir 'no sé' en vez de arrastrar el error).")

    ceilings.add(CeilingRecord(
        subsystem="Multi-paso — ABSTENCIÓN calibrada como lever de honestidad (precisión por cobertura)",
        known_limit=("REAL (exp032): abstenerse cuando un paso no verifica sube fuerte la precisión-sobre-"
                     "respondidas (mejor régimen [{bk}]: {bp} vs commit {bc}, +{bg}, cobertura {bv}). Cota: la "
                     "utilidad COLAPSA en cadenas largas (a K={km} la cobertura cae a {hv}: abstiene todo) y bajo "
                     "ruido del verificador (la precisión se erosiona por falsos positivos).").format(
                         bk=best_key, bp=_fmt(best['precision']), bc=_fmt(best['commit_always']),
                         bg=_fmt(best['prec_gain']), bv=_fmt(best['coverage']), km=st['Kmax'],
                         hv=_fmt(hard['coverage'])),
        blockers=[{"text": "cobertura colapsa en cadenas largas (toda cadena larga falla en algún paso); falta BACKTRACKING (reintentar el paso) en vez de abstener la cadena entera", "kind": "diseno"},
                  {"text": "la abstención hereda el ruido del verificador (falsos positivos pasan); conviene dispararla con la política adaptativa calibrada de 43", "kind": "diseno"},
                  {"text": "precisión 1.0 a verificador perfecto es por construcción; el valor real está en el régimen ruidoso (precisión alta pero <1)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP032.ref, S_EXP031.ref]))
    notes.append("1 techo 'real': abstención sube la precisión (honestidad) pero la cobertura colapsa a K largo / la precisión se erosiona con ruido.")

    dstmt = ("El integrador multi-paso gana un modo HONESTO: abstenerse cuando un paso no verifica convierte "
             "errores silenciosos en abstenciones flagueadas, subiendo fuerte la precisión-sobre-respondidas "
             "(predicción selectiva). PERO es dependiente de régimen: la cobertura colapsa en cadenas largas "
             "(toda cadena larga falla en algún paso -> abstiene todo) y la precisión se erosiona con el ruido "
             "del verificador. Decisión: el integrador ofrecerá abstención como lever de honestidad, pero para "
             "recuperar cobertura en cadenas largas el próximo paso es BACKTRACKING (reintentar el paso fallido) "
             "y disparar la abstención con la política adaptativa calibrada de 43. Cierra el barrido de realismos "
             "del integrador multi-paso (proceso 44 + presupuesto adaptativo 45 + abstención honesta 46).")
    drat = ("exp032 (tier5, propio, {n} seeds): mejor régimen [{bk}] precisión {bp} vs commit {bc} (+{bg}), "
            "cobertura {bv}; régimen duro K={km} cobertura colapsa a {hv}. Convergente con predicción selectiva "
            "y con 41/43 (el lever depende de la calidad del verificador). MIXTA pre-registrada.").format(
                n=n_seeds, bk=best_key, bp=_fmt(best['precision']), bc=_fmt(best['commit_always']),
                bg=_fmt(best['prec_gain']), bv=_fmt(best['coverage']), km=st['Kmax'], hv=_fmt(hard['coverage']))
    dec = Decision(id="D-V4-11", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP032), _to_plain(S_EXP031)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-11 ACEPTADA por el ledger (tier5 exp032 + tier5 exp031).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-11:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle46_abstention_noisy',
                                description='CYCLE 46 (RESET v4, H-V4-1k: abstención calibrada + verificador ruidoso per-step).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 46 (RESET v4): abstención calibrada + verificador ruidoso per-step (H-V4-1k)")
    print("=" * 78)
    print("veredicto H-V4-1k:", status.upper() if status else "?")
    print("  abstenerse sube la precisión-sobre-respondidas (honestidad); cobertura colapsa a K largo / con ruido.")
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
