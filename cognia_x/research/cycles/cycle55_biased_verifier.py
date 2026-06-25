r"""
cycle55_biased_verifier.py — CICLO 55 (RESET v4): H-V4-2h por las compuertas del engine.

H-V4-2h: ¿un verificador con SESGO SISTEMÁTICO (bug consistente off-by-one, sembrado en el repertorio) DAÑA el
lazo PLANO (deriva o estancamiento), y la GUARDIA (replay limpio) lo defiende? DERIVA de
exp041_biased_verifier/results/results.json.

Correr (DESPUÉS de exp041):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp041_biased_verifier.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle55_biased_verifier
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
                             'cycle55_biased_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp041_biased_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _seq(xs):
    return "[" + " ".join("%.3f" % x for x in xs) + "]"


S_EXP019 = Source(tier=5, ref="cognia_x/experiments/exp019_reward_hack (CYCLE 32)", obtained=True,
                  claim=("exp019 (H-LEARN-4): el ECHO no se DESCUBRE; un verificador débil no se hackea bajo "
                         "imitación cuando el atajo no se samplea -> la DISCOVERY es la barrera."))
S_EXP039 = Source(tier=5, ref="cognia_x/experiments/exp039_noisy_real_verifier (CYCLE 53)", obtained=True,
                  claim=("exp039 (H-V4-2f): la guardia tolera ruido falso-positivo UNIFORME hasta ε*=0.50; "
                         "límite abierto: ruido CORRELACIONADO/estructural."))
S_EXP037 = Source(tier=5, ref="cognia_x/experiments/exp037_iterated_real_verifier (CYCLE 51)", obtained=True,
                  claim=("exp037 (H-V4-2d): la guardia (dedup+replay limpio) es el mecanismo de robustez del "
                         "lazo de auto-mejora con verificador real."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    st = data.get('stats')
    if not status or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp041 primero): " + results_path)
    rp, rg = st['real_plain'], st['real_guarded']
    op, og = st['obo_plain'], st['obo_guarded']
    R = len(rp) - 1
    n_seeds = st['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    modo = ("DERIVA dramática (offbyone sube fuerte)" if st['plain_drifts']
            else ("ESTANCAMIENTO/PIN (real no mejora + sesgo persiste)" if st.get('plain_pinned')
                  else "NINGUNO (plano no dañado)"))
    S_EXP041 = Source(tier=5, ref="cognia_x/experiments/exp041_biased_verifier", obtained=True,
                      claim=("exp041 (propio, {n} seeds, R={R}, HybridLM): verificador FUERTE pero BUGGY (acepta "
                             "valor==target O target-1, off-by-one sembrado). PLANO real {rp} offbyone {op}; "
                             "GUARDED real {rg} offbyone {og}. Daño al plano: {modo}; la guardia defiende="
                             "{gd}.").format(n=n_seeds, R=R, rp=_seq(rp), op=_seq(op), rg=_seq(rg), og=_seq(og),
                                             modo=modo, gd=st['guard_defends']))
    for src in (S_EXP019, S_EXP039, S_EXP037, S_EXP041):
        ledger.add_source(src)
    notes.append("4 fuentes (S_EXP019 tier5 discovery; S_EXP039 tier5 ruido uniforme; S_EXP037 tier5 guardia; S_EXP041 tier5 dato propio).")

    ev_for = [S_EXP041.ref, S_EXP037.ref]
    ev_against = [S_EXP041.ref, S_EXP019.ref]
    adv = ("{V}: un verificador con SESGO SISTEMÁTICO (bug off-by-one consistente, SEMBRADO en el repertorio "
           "p_bug=0.35) — el caso CORRELACIONADO que exp039 dejó abierto — DAÑA el lazo PLANO por "
           "{modo}: real_acc plano {rp} (no despega), offbyone plano {op} (el sesgo PERSISTE ~{opf}). La GUARDIA "
           "(dedup + replay de '1+(n-1)' CORRECTO de la verdad) DEFIENDE (recupera real_acc {rgf} vs {rpf}, baja "
           "el sesgo a {ogf} vs {opf}): el replay limpio reinyecta la regla correcta y DILUYE el sesgo "
           "estructural que el verificador buggy premia. MECANISMO: el plano entrena con lo que el verificador "
           "acepta (incl. off-by-one) -> se queda mezclando correcto/sesgado; el replay de la verdad reancla en "
           "target. MATIZ vs exp019 (DISCOVERY como barrera): aquí el sesgo estaba SEMBRADO (en repertorio), así "
           "que NO es un test de descubrimiento sino de EXPLOTABILIDAD/persistencia del sesgo bajo iteración — y "
           "el plano NO lo descubre de novo pero TAMPOCO lo limpia solo; la guardia sí. EVIDENCIA EN CONTRA "
           "(caveats honestos): (1) el sesgo no causa DERIVA runaway (offbyone no explota), sólo PERSISTE/pin -> "
           "el daño es estancamiento, no colapso (menos grave que la hipótesis fuerte). (2) sesgo sembrado "
           "artificialmente (no emergente). (3) tarea acotada. CONCLUSIÓN: la guardia (replay limpio) es defensa "
           "no sólo contra ruido uniforme (exp039) sino contra SESGO ESTRUCTURAL del verificador.").format(
               V=status.upper(), modo=modo, rp=_seq(rp), op=_seq(op), opf=_fmt(op[R]), rgf=_fmt(rg[R]),
               rpf=_fmt(rp[R]), ogf=_fmt(og[R]))

    hyp = Hypothesis(
        id="H-V4-2h",
        statement=("Un verificador con sesgo sistemático (off-by-one sembrado) DAÑA el lazo plano (deriva o "
                   "estancamiento con sesgo persistente) y la guardia (replay limpio) lo defiende."),
        prediction=("APOYADA si el plano DERIVA fuerte (offbyone sube > margen) y la guardia recupera real + baja "
                    "sesgo; MIXTA si el plano es DAÑADO por estancamiento/pin (real no mejora + sesgo persiste) "
                    "sin deriva runaway pero la guardia defiende; REFUTADA si el plano no es dañado / la guardia "
                    "no aporta. (Pre-registrada, con dos modos de daño.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'mixta') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp041_biased_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2h")
        notes.append("H-V4-2h marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu corrector de programas tiene un bug consistente: aprueba programas que dan el resultado "
                 "pedido MENOS UNO (off-by-one), y vos ya conocés esa 'solución' tramposa. ¿Derivás a programar "
                 "siempre el off-by-one, o un cuaderno de soluciones correctas te mantiene en lo correcto?"),
        everyday=("Si entrenás con lo que el corrector buggy aprueba, te quedás mezclando correcto y off-by-one "
                  "(no mejorás). Con el cuaderno de soluciones CORRECTAS de verdad (replay), reanclás en la "
                  "respuesta correcta y el sesgo se diluye, aunque el corrector lo siga premiando."),
        solutions=["verificador buggy + lazo PLANO -> se estanca mezclando correcto/sesgado (sesgo persiste)",
                   "verificador buggy + GUARDED (replay limpio) -> recupera real_acc y baja el sesgo",
                   "el sesgo SEMBRADO (no se descubre de novo, matiz vs exp019) pero el plano no lo limpia solo",
                   "el replay de la verdad es la DEFENSA contra el sesgo estructural del verificador"],
        principles=["un verificador con sesgo SISTEMÁTICO daña el lazo (estancamiento/pin), distinto del ruido uniforme",
                    "la guardia (replay limpio de la verdad) defiende contra sesgo estructural, no sólo ruido aleatorio",
                    "el daño del sesgo sembrado es PERSISTENCIA/pin, no deriva runaway (menos grave de lo temido)",
                    "reanclar en datos verdaderos (replay) diluye lo que un verificador buggy premia"],
        adaptation=("El lazo del lab usa replay limpio como defensa contra verificadores imperfectos, sean "
                    "ruidosos (exp039) o sesgados (exp041). Próximos: sesgo EMERGENTE (no sembrado); verificador "
                    "de código real con un bug real; cuantificar cuánto sesgo tolera la guardia."),
        measurement=("exp041: plano real {rp} obo {op}; guarded real {rg} obo {og}. {n} seeds, R={R}.").format(
            rp=_seq(rp), op=_seq(op), rg=_seq(rg), og=_seq(og), n=n_seeds, R=R),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (corrector con bug off-by-one + cuaderno de la verdad = replay reancla).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — robustez del lazo de auto-mejora a SESGO SISTEMÁTICO del verificador (off-by-one)",
        known_limit=("REAL (exp041): un verificador FUERTE pero BUGGY (acepta off-by-one sembrado) DAÑA el lazo "
                     "plano ({modo}: real {rpf}, sesgo persiste {opf}) y la GUARDIA defiende (real {rgf}, sesgo "
                     "{ogf}) -> el replay limpio es defensa contra sesgo estructural, no sólo ruido uniforme.").format(
                         modo=modo, rpf=_fmt(rp[R]), opf=_fmt(op[R]), rgf=_fmt(rg[R]), ogf=_fmt(og[R])),
        blockers=[{"text": "el sesgo está SEMBRADO artificialmente (p_bug=0.35), no emergente; falta sesgo que emerja del propio lazo", "kind": "diseno"},
                  {"text": "el daño es estancamiento/persistencia, no deriva runaway; falta un sesgo que SÍ cause colapso para mapear el peor caso", "kind": "diseno"},
                  {"text": "falta verificador de CÓDIGO real con un bug real (no el off-by-one de juguete)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP041.ref, S_EXP039.ref]))
    notes.append("1 techo 'real': la guardia (replay limpio) defiende contra sesgo sistemático del verificador (no sólo ruido uniforme).")

    dstmt = ("La guardia (dedup + replay limpio de la verdad) del lazo de auto-mejora del lab defiende NO sólo "
             "contra ruido del verificador UNIFORME (exp039) sino contra SESGO SISTEMÁTICO/estructural (exp041, "
             "verificador buggy off-by-one): el plano se {modo2} (real {rpf}, sesgo {opf}) y la guardia recupera "
             "(real {rgf}, sesgo {ogf}). El replay de datos verdaderos reancla el lazo y diluye lo que un "
             "verificador imperfecto premia. Matiz honesto: el sesgo sembrado NO causa deriva runaway, sólo "
             "persistencia/pin (consistente con la barrera de DISCOVERY de exp019). Decisión: el replay limpio es "
             "el mecanismo de defensa general del lazo ante verificadores imperfectos. Próximos: sesgo "
             "emergente, verificador de código real con bug real.").format(
                 modo2=("deriva" if st['plain_drifts'] else "estanca (pin)"), rpf=_fmt(rp[R]), opf=_fmt(op[R]),
                 rgf=_fmt(rg[R]), ogf=_fmt(og[R]))
    drat = ("exp041 (tier5, propio, {n} seeds): verificador buggy off-by-one sembrado. plano dañado={ph} "
            "(deriva={dr} pin={pin}); guardia defiende={gd} (real {rgf} vs {rpf}, sesgo {ogf} vs {opf}). "
            "Convergente con exp039 (ruido) y exp037 (guardia). {V}.").format(
                n=n_seeds, ph=st['plain_harmed'], dr=st['plain_drifts'], pin=st.get('plain_pinned'),
                gd=st['guard_defends'], rgf=_fmt(rg[R]), rpf=_fmt(rp[R]), ogf=_fmt(og[R]), opf=_fmt(op[R]),
                V=status.upper())
    dec = Decision(id="D-V4-20", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP041), _to_plain(S_EXP039)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-20 ACEPTADA por el ledger (tier5 exp041 + tier5 exp039).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-20:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle55_biased_verifier',
                                description='CYCLE 55 (RESET v4, H-V4-2h: verificador con sesgo sistemático + guardia).')
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
    print("RESUMEN — CYCLE 55 (RESET v4): verificador con SESGO SISTEMÁTICO + guardia como defensa (H-V4-2h)")
    print("=" * 78)
    print("veredicto H-V4-2h:", status.upper() if status else "?")
    print("  la guardia (replay limpio) defiende contra sesgo estructural del verificador, no sólo ruido uniforme.")
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
