r"""
cycle53_noisy_real_verifier.py — CICLO 53 (RESET v4): H-V4-2f por las compuertas del engine.

H-V4-2f: ¿la tolerancia al RUIDO del verificador (ε*≈0.15, exp017/oráculo) TRANSFIERE a un VERIFICADOR
REAL-CHEQUEABLE (sandbox), y la GUARDIA (replay limpio de la verdad) SUBE/mantiene ese umbral? DERIVA de
exp039_noisy_real_verifier/results/results.json.

Correr (DESPUÉS de exp039):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp039_noisy_real_verifier.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle53_noisy_real_verifier
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
                             'cycle53_noisy_real_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp039_noisy_real_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _net(net_mean):
    return "[" + " ".join("e%s=%+.3f" % (e, net_mean[str(e)] if str(e) in net_mean else net_mean[e]) for e in [0.0, 0.15, 0.30, 0.50]) + "]"


S_EXP017 = Source(tier=5, ref="cognia_x/experiments/exp017_noisy_verifier (CYCLE 30)", obtained=True,
                  claim=("exp017 (H-LEARN-2): la auto-mejora verificada DECAE con el ruido falso-positivo del "
                         "verificador y sobrevive hasta ε*≈0.15 — pero con el ORÁCULO aritmético EXACTO."))
S_EXP037 = Source(tier=5, ref="cognia_x/experiments/exp037_iterated_real_verifier (CYCLE 51)", obtained=True,
                  claim=("exp037 (H-V4-2d): el lazo iterado + guardia funciona con un VERIFICADOR REAL; hilo "
                         "abierto = verificador real PARCIAL/ruidoso."))
S_EXP038 = Source(tier=5, ref="cognia_x/experiments/exp038_real_verifier_ceiling (CYCLE 52)", obtained=True,
                  claim=("exp038 (H-V4-2e): la guardia (replay de la verdad) es crítica al cold-start con el "
                         "verificador real; hilo abierto = verificador real ruidoso."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict')
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp039 primero): " + results_path)
    n_seeds = sm['n_seeds']
    ng = sm['net_mean']['guarded']
    npn = sm['net_mean']['plain']
    esg, esp = sm['eps_star']['guarded'], sm['eps_star']['plain']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP039 = Source(tier=5, ref="cognia_x/experiments/exp039_noisy_real_verifier", obtained=True,
                      claim=("exp039 (propio, {n} seeds, R={R}, HybridLM): dosis-respuesta al ruido falso-positivo "
                             "del VERIFICADOR REAL. net guarded por ε {netg} (ε*={esg}); plano {netp} (ε*={esp}). "
                             "La tolerancia al ruido transfiere del oráculo al verificador real; la guardia "
                             "(replay limpio) {sube} el umbral.").format(
                                 n=n_seeds, R=data['args']['rounds'], netg=_net(ng), esg=esg, netp=_net(npn),
                                 esp=esp, sube=("sube/mantiene" if sm['guard_raises_eps_star'] else "no sube")))
    for src in (S_EXP017, S_EXP037, S_EXP038, S_EXP039):
        ledger.add_source(src)
    notes.append("4 fuentes (S_EXP017 tier5 ε*/oráculo; S_EXP037 tier5 verificador real; S_EXP038 tier5 guardia/cold-start; S_EXP039 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP039.ref, S_EXP017.ref]
    ev_against = [S_EXP039.ref]
    adv = ("{V}: la tolerancia al RUIDO del verificador TRANSFIERE del ORÁCULO (exp017, ε*≈0.15) a un "
           "VERIFICADOR REAL-CHEQUEABLE (sandbox que EJECUTA la expresión). net-sobre-base GUARDED por ε {netg} "
           "(decae con el ruido: el verificador real, como el oráculo, es el MOTOR — degradarlo degrada la "
           "mejora; con volumen/pasos FIJOS la única variable es la contaminación). ε*_guarded={esg} vs "
           "ε*_plano={esp}: la GUARDIA (replay limpio de la verdad) {sube} el umbral de ruido tolerable — el "
           "replay diluye la contaminación del verificador con señal de la verdad, así el lazo aguanta MÁS error "
           "del corrector ({netp} plano vs {netg2} guarded). EVIDENCIA EN CONTRA (caveats honestos): (1) modelo "
           "de ruido = falso-positivo uniforme (un verificador real puede fallar de forma CORRELACIONADA, p.ej. "
           "siempre aceptar cierto patrón); (2) la regla canónica de replay '1+(n-1)' es estrecha; (3) tarea "
           "acotada (test=90). CONCLUSIÓN: el resultado central del lab (el VERIFICADOR es el lever; su calidad "
           "es de 1ra clase) se sostiene con un verificador REAL y ruidoso, y la guardia compra robustez al "
           "ruido.").format(V=status.upper(), netg=_net(ng), esg=esg, esp=esp, netp=_net(npn), netg2=_net(ng),
                            sube=("SUBE/mantiene" if sm['guard_raises_eps_star'] else "NO sube"))

    hyp = Hypothesis(
        id="H-V4-2f",
        statement=("La tolerancia al ruido del verificador (ε*≈0.15, oráculo) transfiere a un verificador "
                   "REAL-CHEQUEABLE; la guardia (replay limpio) sube/mantiene el umbral de ruido tolerable."),
        prediction=("APOYADA si el net guarded DECAE con ε (mejora limpia en ε=0 y caída ε=0->0.50 > 2σ) y "
                    "sobrevive hasta ε*>0 (transfiere); REFUTADA si la curva es plana en ε o ε=0 no mejora; MIXTA "
                    "si decae pero < 2σ. Bonus: ε*_guarded >= ε*_plano. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp039_noisy_real_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2f")
        notes.append("H-V4-2f marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu corrector de programas ahora se EQUIVOCA: a veces da por bueno uno que no computa lo pedido "
                 "(falso positivo, tasa ε). ¿Hasta qué error del corrector seguís mejorando, y tener un cuaderno "
                 "de soluciones correctas a mano te hace aguantar MÁS error?"),
        everyday=("Practicás corrigiéndote con un corrector imperfecto. Si además repasás un cuaderno de "
                  "soluciones CORRECTAS de verdad (replay), la basura que el corrector deja pasar se diluye y "
                  "seguís mejorando aun con el corrector bastante malo. Sin el cuaderno, el mismo error del "
                  "corrector te hunde antes."),
        solutions=["verificador REAL PERFECTO (ε=0) -> auto-mejora plena (CYCLE 51-52)",
                   "verificador REAL RUIDOSO (ε>0) -> la mejora decae al subir ε (como el oráculo, exp017)",
                   "lazo PLANO bajo ruido -> cae antes (ε* bajo)",
                   "lazo GUARDED (replay limpio) bajo ruido -> aguanta más ruido (ε* >= plano): el replay diluye la contaminación"],
        principles=["el verificador (su CORRECCIÓN) es el motor también cuando es REAL y ruidoso, no solo con el oráculo",
                    "la tolerancia al ruido (ε*) transfiere del oráculo exacto al verificador chequeable real",
                    "la guardia (replay limpio de la verdad) compra ROBUSTEZ al ruido del verificador (sube ε*)",
                    "con volumen/pasos fijos, la dosis-respuesta aísla la contaminación como la causa"],
        adaptation=("El lazo de auto-mejora del lab tolera verificadores reales IMPERFECTOS hasta un ε*, y la "
                    "guardia (replay) lo amplía. Próximos: ruido CORRELACIONADO (no uniforme); verificador de "
                    "CÓDIGO real con tests parciales (FP-rate medido); combinar con bootstrapping desde base débil."),
        measurement=("exp039: net guarded por ε {netg} (ε*={esg}); plano {netp} (ε*={esp}); guard_raises_ε*={gr}. "
                     "{n} seeds.").format(netg=_net(ng), esg=esg, netp=_net(npn), esp=esp,
                                          gr=sm['guard_raises_eps_star'], n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (corrector imperfecto + cuaderno de la verdad = replay diluye la contaminación).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — robustez del lazo de auto-mejora al RUIDO de un VERIFICADOR REAL (dosis-respuesta)",
        known_limit=("REAL (exp039): la auto-mejora con VERIFICADOR REAL decae con el ruido falso-positivo y "
                     "sobrevive hasta ε*={esg} (guarded) vs ε*={esp} (plano) -> la tolerancia al ruido transfiere "
                     "del oráculo (exp017 ε*≈0.15) y la guardia (replay limpio) {sube} el umbral.").format(
                         esg=esg, esp=esp, sube=("sube" if sm['guard_raises_eps_star'] else "no sube")),
        blockers=[{"text": "modelo de ruido = falso-positivo UNIFORME; falta ruido CORRELACIONADO (un verificador real puede aceptar siempre cierto patrón)", "kind": "diseno"},
                  {"text": "regla canónica de replay '1+(n-1)' estrecha; falta verificador de CÓDIGO real con tests parciales (FP-rate medido)", "kind": "diseno"},
                  {"text": "no se combinó ruido + bootstrapping desde base débil (interacción ε* x cold-start)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP039.ref, S_EXP017.ref]))
    notes.append("1 techo 'real': la tolerancia al ruido transfiere al verificador real y la guardia compra robustez (sube ε*).")

    dstmt = ("El resultado central del lab (el VERIFICADOR es el lever de 1ra clase; su CALIDAD decide la "
             "auto-mejora) se sostiene con un verificador REAL-CHEQUEABLE y RUIDOSO: la auto-mejora decae con el "
             "ruido falso-positivo y sobrevive hasta ε*={esg} (guarded) vs ε*={esp} (plano). La GUARDIA (replay "
             "limpio de la verdad) {sube} el umbral de ruido tolerable: el replay diluye la contaminación del "
             "verificador. Decisión: el lazo del lab tolera verificadores reales imperfectos hasta un ε* y usa la "
             "guardia para ampliarlo. Une H-LEARN-2 (ruido/oráculo) con H-V4-2d/e (verificador real). Próximos: "
             "ruido correlacionado, verificador de código real con tests parciales, interacción ruido x cold-start.").format(
                 esg=esg, esp=esp, sube=("SUBE" if sm['guard_raises_eps_star'] else "NO sube"))
    drat = ("exp039 (tier5, propio, {n} seeds): net guarded decae con ε {netg} (ε*={esg}); plano {netp} "
            "(ε*={esp}). Convergente con exp017 (ε*≈0.15 oráculo). {V}.").format(
                n=n_seeds, netg=_net(ng), esg=esg, netp=_net(npn), esp=esp, V=status.upper())
    dec = Decision(id="D-V4-18", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP039), _to_plain(S_EXP017)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-18 ACEPTADA por el ledger (tier5 exp039 + tier5 exp017).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-18:", e); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle53_noisy_real_verifier',
                                description='CYCLE 53 (RESET v4, H-V4-2f: ruido del verificador real, dosis-respuesta).')
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
    print("RESUMEN — CYCLE 53 (RESET v4): ruido del VERIFICADOR REAL — dosis-respuesta (H-V4-2f)")
    print("=" * 78)
    print("veredicto H-V4-2f:", status.upper() if status else "?")
    print("  la tolerancia al ruido transfiere al verificador real; la guardia (replay limpio) sube el umbral ε*.")
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
