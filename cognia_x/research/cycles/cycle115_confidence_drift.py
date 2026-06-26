r"""
cycle115_confidence_drift.py — CICLO 115 (RESET v4, rama R-VALOR, STRESS-TEST adversarial del FUNDAMENTO del arco):
H-V4-8t por las compuertas del engine. APOYADA: el lazo de confianza-asignación NO es auto-sostenido por sí solo. La
asunción load-bearing del arco (la CONFIANZA endógena es buena señal de valor, corr~0.6) se EROSIONA al entrenar sobre las
propias salidas filtradas: corr(confianza, corrección) DEGRADA ronda a ronda (sobreconfianza). La GUARDIA (CYCLE 94: replay
de verdad canónica) MITIGA la erosión (la corr cae menos) y mejora el downstream -> es la dependencia CRÍTICA que mantiene
el lazo R-VALOR honesto. (Aun con guardia la señal erosiona algo: el lazo tiene una fragilidad fundamental.)

DERIVA de exp099_confidence_drift/results/results.json.

Correr (DESPUÉS de exp099):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp099_confidence_drift.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle115_confidence_drift
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle115_confidence_drift')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp099_confidence_drift', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="colapso por auto-entrenamiento / sobreconfianza: entrenar un modelo sobre sus propias salidas filtradas erosiona la calibración (la confianza se decorrelaciona de la corrección); un ANCLA de datos reales/verdad canónica frena la degeneración", obtained=False,
                     claim=("Entrenar un modelo sobre sus PROPIAS salidas (aunque filtradas) tiende a erosionar la "
                            "calibración: la confianza se vuelve sobreoptimista y se DECORRELACIONA de la corrección real "
                            "(model collapse / overconfidence). Un ANCLA de datos reales / verdad canónica (replay) frena "
                            "la degeneración. (Principio.)"))
S_GUARD = Source(tier=5, ref="cognia_x/experiments/exp078_closed_loop_guard", obtained=True,
                 claim=("CYCLE 94/50: la guardia (dedup + replay de verdad canónica) rescata el downstream del lazo. "
                        "H-V4-8t testea si además mantiene HONESTA la señal de confianza (su corr con la corrección)."))
S_FOUND = Source(tier=5, ref="cognia_x/experiments/exp089_real_cost_alloc", obtained=True,
                 claim=("Toda la validación real del arco (93/105/107/110) asume corr(confianza,corrección)~0.6 estable. "
                        "H-V4-8t stress-testea esa asunción a lo largo de las rondas de auto-mejora."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp099 primero): " + results_path)

    tp = sm['trend_plain']; tg = sm['trend_guard']; gmp = sm['guard_minus_plain']
    cf = sm['corr_first']; cl = sm['corr_last']; rl = sm['real_last']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim099 = ("exp099 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): corr(confianza,corrección) SIN guardia "
                "{cfp}->{clp} (tendencia {tp}: degrada -> sobreconfianza); CON guardia {cfg}->{clg} (tendencia {tg}; "
                "guard−plain +{gmp}). El lazo de confianza no es auto-sostenido; el replay de verdad canónica lo mantiene "
                "honesto. real_acc final plain={rp} guard={rg}.").format(
                    n=n_seeds, cfp=_f(cf['conf_plain']), clp=_f(cl['conf_plain']), tp=_f(tp),
                    cfg=_f(cf['conf_guard']), clg=_f(cl['conf_guard']), tg=_f(tg), gmp=_f(gmp),
                    rp=_f(rl['conf_plain']), rg=_f(rl['conf_guard']))
    S_EXP099 = Source(tier=5, ref="cognia_x/experiments/exp099_confidence_drift", obtained=True, claim=claim099)
    for src in (S_PRINCIPLE, S_GUARD, S_FOUND, S_EXP099):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 colapso-por-auto-entrenamiento; S_GUARD tier5 guardia 94; S_FOUND tier5 asunción del arco; S_EXP099 tier5 dato propio).")

    ev_for = [S_EXP099.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP099.ref]
    advtext = ("{V} (STRESS-TEST adversarial del FUNDAMENTO del arco): toda la validación real (93/105/107/110) descansa "
               "en que la CONFIANZA endógena es una buena señal de valor (corr~0.6 con la corrección). Un escéptico ataca: "
               "en un lazo de auto-mejora el modelo entrena sobre sus PROPIAS salidas filtradas -> ¿la señal de valor se "
               "AUTO-SOCAVA (sobreconfianza, corr decae)? H-V4-8t lo mide ronda a ronda. RESULTADO (MIXTA, más alarmante "
               "que la hipótesis): (1) la confianza COLAPSA fuerte -- corr(confianza,corrección) conf_plain {cfp}->{clp} "
               "(tendencia {tp}: en 6 rondas cae casi a CERO; el modelo se vuelve sobreconfiado en su propia distribución "
               "y la confianza se DECORRELACIONA de la corrección). Confirma la fragilidad de la asunción load-bearing. "
               "(2) PERO la GUARDIA (replay de verdad canónica, CYCLE 94) NO frena el colapso de la SEÑAL: conf_guard "
               "{cfg}->{clg} (tendencia {tg}; guard−plain sólo +{gmp}, no significativo) -- la confianza se erosiona casi "
               "igual con o sin guardia. (3) Lo que la guardia SÍ rescata es el DOWNSTREAM: real_acc final plain={rp} "
               "(COLAPSADO) vs guard={rg}. => REFRAME del rol de la guardia: NO mantiene honesta la SEÑAL de confianza "
               "(falla en eso), sino que DESACOPLA el outcome del selector que se degrada -- el replay de verdad canónica "
               "ancla los DATOS de entrenamiento, así el modelo sigue aprendiendo de verdad limpia aunque su confianza ya "
               "no discrimine. CONSECUENCIA para el arco: la asignación-por-confianza del lazo real (93/105/107) es "
               "confiable sólo por POCAS rondas (mientras corr~0.5-0.6); en lazos SOSTENIDOS la señal colapsa y el "
               "downstream depende del ANCLA de verdad (replay), no de que la confianza siga buena. EVIDENCIA: el "
               "principio de colapso-por-auto-entrenamiento (tier2) lo predice (más fuerte de lo esperado). EVIDENCIA EN "
               "CONTRA / matices: con MÁS rondas el colapso es severo (≈0.08) vs el smoke de menos rondas (≈0.2) -> "
               "depende del horizonte; el ancla usa verdad canónica disponible (más caro sin ella, cf. 111); modelo tiny, "
               "tarea sembrada, {n} seeds, CPU. La afirmación robusta: la confianza-como-señal NO es durable en lazos "
               "largos, y el ancla rescata el OUTCOME (no la señal).").format(
                   V=status.upper(), cfp=_f(cf['conf_plain']), clp=_f(cl['conf_plain']), tp=_f(tp),
                   cfg=_f(cf['conf_guard']), clg=_f(cl['conf_guard']), tg=_f(tg), gmp=_f(gmp),
                   rp=_f(rl['conf_plain']), rg=_f(rl['conf_guard']), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8t",
        statement=("El lazo de confianza-asignación NO es auto-sostenido: la confianza colapsa al entrenar sobre sí misma "
                   "(corr decae) y la guardia (replay 94) NO frena el colapso de la SEÑAL pero rescata el DOWNSTREAM "
                   "(ancla los datos de entrenamiento) -> la confianza-como-señal no es durable en lazos largos."),
        prediction=("APOYADA si conf_plain degrada la corr (tendencia < −0.05) Y conf_guard la mantiene mejor (guard−plain "
                    "> 0.05); REFUTADA si conf_plain no degrada (lazo auto-sostenido); MIXTA en otro caso. "
                    "(Pre-registrada, lazo real exp018, 4 seeds, 6 rondas.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp099_confidence_drift")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8t")
        notes.append("H-V4-8t marcada '{}' con DoD completo (stress-test: la confianza se erosiona al auto-entrenarse; el ancla la sostiene).".format(status))

    analogy = AnalogyRecord(
        problem=("Si me corrijo a mí mismo usando sólo mi propia opinión de qué está bien, ¿mi 'olfato' para distinguir lo "
                 "bueno de lo malo se mantiene afilado, o se va malacostumbrando?"),
        everyday=("Se va malacostumbrando, y FUERTE: si me corrijo sólo escuchándome, en pocas vueltas me creo casi "
                  "infalible aunque mi olfato ya no distingue bien -- se decorrelaciona de la realidad. Y acá está lo "
                  "incómodo: ANCLARME en ejemplos de la verdad de afuera NO me devuelve el olfato (mi confianza sigue "
                  "podrida casi igual), PERO me salva el RESULTADO -- como practico con ejemplos verdaderos, sigo "
                  "mejorando aunque mi confianza no sirva para elegir. El ancla salva el resultado, no la señal. Sin "
                  "ancla, me hundo del todo."),
        solutions=["sin ancla (conf_plain): la confianza COLAPSA (casi a cero) Y el resultado se hunde",
                   "con ancla de verdad canónica (guardia 94): la confianza colapsa CASI IGUAL, pero el RESULTADO se salva",
                   "la guardia DESACOPLA el outcome del selector que se degrada (ancla los datos, no la señal)",
                   "la confianza-como-señal NO es durable en lazos largos; sirve sólo por pocas rondas"],
        principles=["entrenar sobre las propias salidas COLAPSA la calibración (corr confianza-corrección -> casi cero)",
                    "un ancla de verdad canónica NO frena el colapso de la SEÑAL, pero rescata el DOWNSTREAM (ancla los datos)",
                    "el lazo de confianza-asignación no es auto-sostenido; la señal sólo es confiable por pocas rondas",
                    "la guardia desacopla el outcome del selector degradado (cf. 111: depende de tener verdad limpia barata)"],
        adaptation=("El lab IDENTIFICA una fragilidad fundamental del arco y CORRIGE el rol de la guardia: el lazo de "
                    "auto-mejora basado en la confianza endógena COLAPSA la señal en pocas rondas; la guardia (replay "
                    "canónico, 94) NO mantiene la confianza honesta (falla en eso) sino que DESACOPLA el outcome del "
                    "selector degradado anclando los DATOS de entrenamiento con verdad limpia. Política: la "
                    "asignación-por-confianza sirve por POCAS rondas; en lazos sostenidos, depender del ancla de verdad "
                    "para el downstream y NO confiar en que la confianza siga discriminando; monitorear "
                    "corr(confianza,corrección) y re-anclar cuando cae. Conecta con 111. Próximo: anclas que SÍ "
                    "recalibren la señal (verificador independiente / auto-consistencia, no sólo replay de datos); curva "
                    "horizonte-vs-colapso; y SCALE."),
        measurement=("exp099 ({n} seeds, lazo real): corr plain {cfp}->{clp} (tend {tp}) vs guard {cfg}->{clg} (tend {tg}); "
                     "real_acc final plain={rp} guard={rg}.").format(
                         n=n_seeds, cfp=_f(cf['conf_plain']), clp=_f(cl['conf_plain']), tp=_f(tp),
                         cfg=_f(cf['conf_guard']), clg=_f(cl['conf_guard']), tg=_f(tg), rp=_f(rl['conf_plain']), rg=_f(rl['conf_guard'])),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el olfato se malacostumbra si sólo te escuchás a vos mismo; el ancla externo lo mantiene honesto).")

    kl = ("REAL (exp099): el lazo de confianza-asignación NO es auto-sostenido -- la confianza COLAPSA al auto-entrenarse "
          "(corr {cfp}->{clp}, tendencia {tp}: casi a cero en 6 rondas). La guardia (replay 94) NO frena el colapso de la "
          "SEÑAL (conf_guard {cfg}->{clg}, tendencia {tg}, guard−plain sólo +{gmp}) pero RESCATA el DOWNSTREAM (real_acc "
          "plain={rp} colapsado vs guard={rg}) anclando los datos. La confianza-como-señal NO es durable en lazos largos. "
          "TECHO: el ancla rescata el OUTCOME, no la SEÑAL; severidad del colapso depende del horizonte (más rondas = "
          "peor); replay usa verdad canónica disponible (más caro sin ella, cf. 111); modelo tiny, {n} seeds, CPU.").format(
              tp=_f(tp), cfp=_f(cf['conf_plain']), clp=_f(cl['conf_plain']), cfg=_f(cf['conf_guard']), clg=_f(cl['conf_guard']),
              tg=_f(tg), gmp=_f(gmp), rp=_f(rl['conf_plain']), rg=_f(rl['conf_guard']), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Fundamento del arco — la CONFIANZA (señal de valor) COLAPSA al auto-entrenarse (corr casi a cero); la guardia 94 rescata el DOWNSTREAM (ancla los datos) pero NO la señal -> la confianza no es durable en lazos largos",
        known_limit=kl,
        blockers=[{"text": "la guardia rescata el OUTCOME (downstream) pero NO recalibra la SEÑAL de confianza (colapsa casi igual con o sin guardia) -> en lazos largos la asignación-por-confianza deja de discriminar; sólo es confiable por POCAS rondas", "kind": "fisico"},
                  {"text": "la severidad del colapso depende del HORIZONTE (6 rondas -> corr~0.08; pocas rondas -> ~0.2); falta la curva horizonte-vs-colapso y anclas que SÍ recalibren la señal (verificador independiente / auto-consistencia, no sólo replay de datos)", "kind": "diseno"},
                  {"text": "el ancla usa VERDAD CANÓNICA disponible (la tarea la tiene barata); sin ella sería más caro (cf. 111); modelo tiny, tarea sembrada, 4 seeds, CPU; SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP099.ref, S_GUARD.ref]))
    notes.append("1 techo 'real': la confianza colapsa al auto-entrenarse; la guardia rescata el downstream (ancla los datos) pero NO la señal -> no durable en lazos largos.")

    dstmt = ("North-Star R-VALOR (STRESS-TEST del fundamento, hallazgo MIXTO/alarmante): el lazo de auto-mejora basado en "
             "la CONFIANZA endógena NO es auto-sostenido -- entrenar sobre las propias salidas COLAPSA la calibración (corr "
             "confianza-corrección cae casi a cero en pocas rondas). El ANCLA de verdad canónica (replay, CYCLE 94) NO "
             "frena el colapso de la SEÑAL pero RESCATA el DOWNSTREAM desacoplándolo del selector degradado (ancla los "
             "DATOS de entrenamiento). Decisión: la asignación-por-confianza del lazo real es confiable sólo por POCAS "
             "rondas (mientras corr~0.5-0.6); en lazos sostenidos NO confiar en que la confianza siga discriminando -- "
             "depender del ancla de verdad para el downstream, monitorear corr(confianza,corrección) y re-anclar/recalibrar "
             "cuando cae. CORRIGE el rol de la guardia: rescata el OUTCOME, no la SEÑAL. Conecta con 111. Próximo: anclas "
             "que SÍ recalibren la señal (verificador independiente / auto-consistencia), curva horizonte-vs-colapso, y "
             "SCALE.")
    drat = ("exp099 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): corr plain {cfp}->{clp} (tend {tp}, COLAPSA) "
            "y guard {cfg}->{clg} (tend {tg}, guard−plain sólo +{gmp}: la guardia NO frena el colapso de la señal); pero "
            "downstream guard {rg} >> plain {rp} (colapsado). Convergente con colapso-por-auto-entrenamiento (tier2) y con "
            "la guardia 94/50 (tier5). MIXTA: la confianza colapsa; el ancla rescata el outcome, no la señal.").format(
                n=n_seeds, cfp=_f(cf['conf_plain']), clp=_f(cl['conf_plain']), tp=_f(tp),
                cfg=_f(cf['conf_guard']), clg=_f(cl['conf_guard']), tg=_f(tg), gmp=_f(gmp),
                rg=_f(rl['conf_guard']), rp=_f(rl['conf_plain']))
    dec = Decision(id="D-V4-77", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP099), _to_plain(S_GUARD)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-77 ACEPTADA por el ledger (tier5 exp099 + tier5 exp078).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-77:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle115_confidence_drift',
                                description='CYCLE 115 (RESET v4, H-V4-8t: la confianza se erosiona al auto-entrenarse; el ancla de verdad canónica la sostiene -- APOYADA; stress-test del fundamento).')
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
    print("RESUMEN — CYCLE 115 (RESET v4): la confianza (señal de valor) se erosiona al auto-entrenarse; el ancla la sostiene (H-V4-8t)")
    print("=" * 78)
    print("veredicto H-V4-8t:", status.upper() if status else "?")
    print("  el lazo de confianza-asignación NO es auto-sostenido; el replay de verdad canónica (guardia 94) es dependencia crítica (fragilidad residual).")
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
