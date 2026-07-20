r"""
cycle33_rl_vs_imitation.py — CICLO 33 a través del Investigation Engine (frente F-LEARN-2).

H-LEARN-5: el reward-hack del verificador DÉBIL, ¿emerge bajo RL-MAXIMIZACIÓN pero NO bajo IMITACIÓN, con
el MISMO verificador y atajo? Contrapunto causal que cierra el insight de H-LEARN-4 (CYCLE 32): si la
imitación no se hackea porque COPIA lo aceptado (no maximiza), entonces RL (GRPO-lite, que usa la señal
NEGATIVA de lo rechazado) DEBERÍA hackearse con el mismo verificador débil.

DERIVA el veredicto de exp020_rl_vs_imitation/results/results.json. Pasa por las compuertas.
Nota de método: GRPO-lite a escala tiny es INESTABLE (colapsa con muchos pasos); se estabilizó (ventajas
normalizadas, pocos pasos, lr chico) -> el resultado puede ser DIRECCIONAL (modesto) más que catastrófico.

Correr (DESPUÉS de exp020):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp020_rl_vs_imitation.run --seeds 0,1,2
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle33_rl_vs_imitation
"""
import argparse
import json
import os
import shutil
import sys

from cognia_x.research.schema import Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle33_rl_vs_imitation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp020_rl_vs_imitation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


S1 = Source(tier=1, ref="arXiv:1606.06565", obtained=True,
            claim=("Amodei et al. 2016: reward hacking — un agente que MAXIMIZA una recompensa imperfecta "
                   "explota atajos. Predice que RL-maximización + verificador débil se gamea."))
S2 = Source(tier=1, ref="arXiv:2203.14465", obtained=True,
            claim=("Zelikman et al. 2022 (STaR): el bootstrapping verificado IMITA lo aceptado (no maximiza "
                   "la aceptación). La distinción imitación-vs-maximización es la variable de este experimento."))


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp020 primero): " + results_path)
    s = data['summary']
    ledger, hyps, ceilings, record = EvidenceLedger(store), HypothesisRegistry(store), CeilingTracker(store), PermanentRecord(store)
    notes = []
    status = s.get('status')
    f = s.get('final', {})
    base_deg = s.get('base_degenerate')

    def deg(a):
        return _fmt(f.get(a, {}).get('degen'))

    S3 = Source(tier=5, ref="cognia_x/experiments/exp020_rl_vs_imitation", obtained=True,
                claim=("exp020 (MISMO verificador débil + atajo sembrado que exp019; sólo cambia el ALGORITMO: "
                       "imitación STaR vs GRPO-lite RL; n=3): degenerate(final) imit_weak={iw}, rl_weak={rw}, "
                       "rl_strong={rs} (base {bd}); directional={dir}, hacks={hk}. {verdict}").format(
                           iw=deg('imit_weak'), rw=deg('rl_weak'), rs=deg('rl_strong'), bd=_fmt(base_deg),
                           dir=s.get('directional'), hk=s.get('rlweak_hacks'), verdict=s.get('verdict', '')))
    for src in (S1, S2, S3):
        ledger.add_source(src)
    notes.append("3 fuentes (S1 tier1 reward-hacking; S2 tier1 STaR/imitación; S3 tier5 exp020).")

    if status == 'apoyada':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        adv = ("APOYADA: el MISMO verificador débil + atajo se REWARD-HACKEA bajo RL-MAXIMIZACIÓN (rl_weak "
               "degenerate={rw}) pero NO bajo IMITACIÓN (imit_weak={iw}) ni con verificador fuerte (rl_strong "
               "={rs}) -> CONFIRMA causalmente que el reward-hack es patología de RL-maximización, no del "
               "verificador débil per se (cierra H-LEARN-4).").format(rw=deg('rl_weak'), iw=deg('imit_weak'), rs=deg('rl_strong'))
    elif status == 'mixta':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        adv = ("MIXTA (DIRECCIONAL): rl_weak es el MÁS echo-prone en todos los seeds (degenerate {rw} > imit "
               "{iw} > rl_strong {rs}) y su real_acc es menor -> apoyo DIRECCIONAL de que RL-maximización es más "
               "hack-prone que la imitación (consistente con la distinción de H-LEARN-4), PERO el efecto es "
               "MODESTO (no catastrófico) a escala tiny y el GRPO-lite es INESTABLE (colapsa con más pasos). "
               "Mecanismo apoyado direccionalmente; demostración fuerte requiere RL estabilizado (KL-reg, "
               "on-policy) o mayor escala.").format(rw=deg('rl_weak'), iw=deg('imit_weak'), rs=deg('rl_strong'))
    else:
        ev_for, ev_against = [S2.ref], [S3.ref, S1.ref]
        adv = ("REFUTADA a esta escala: RL-maximización (GRPO-lite) no separa de la imitación (rl_weak "
               "degenerate={rw} ~ imit {iw}) -> el hack no se demuestra con este GRPO-lite (inestable/ruidoso) "
               "a este tamaño. Null de MÉTODO (no del mecanismo): el RL estable requeriría más ingeniería.").format(
                   rw=deg('rl_weak'), iw=deg('imit_weak'))

    hyp = Hypothesis(
        id="H-LEARN-5",
        statement=("El reward-hack del verificador DÉBIL emerge bajo RL-MAXIMIZACIÓN (GRPO) pero NO bajo "
                   "IMITACIÓN (STaR), con el MISMO verificador y atajo -> el hack es patología de RL, no del "
                   "verificador débil per se."),
        prediction=("rl_weak.degenerate >> imit_weak y >> rl_strong. Refutado si rl_weak no separa de imit."),
        status='abierta', confidence='baja' if status == 'mixta' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp020_rl_vs_imitation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-LEARN-5")
        notes.append("H-LEARN-5 marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Mismo solucionario débil y mismo truco conocido: ¿lo abusa el que COPIA sus ejercicios "
                 "aprobados (imitación) o el que MAXIMIZA el sello de aprobado (RL)?"),
        everyday=("El que maximiza aprobar penaliza sus intentos fallados -> deriva al truco fiable; el que "
                  "solo copia lo aprobado no penaliza fallos -> no deriva. El objetivo (maximizar) crea el abuso."),
        solutions=["RL-maximización + verificador débil -> deriva al atajo (penaliza fallos)",
                   "imitación + verificador débil -> no deriva (copia lo aceptado honesto)",
                   "verificador fuerte -> cierra el atajo en ambos",
                   "a escala tiny el RL es inestable -> la señal es direccional, no catastrófica"],
        principles=["el reward-hack lo crea el OBJETIVO (maximizar), no la mera debilidad del verificador",
                    "la imitación es estructuralmente más robusta al atajo que la maximización RL",
                    "demostrar el hack RL limpio requiere RL estable (KL/on-policy) o escala mayor"],
        adaptation=("H-LEARN-5 {}: el contrapunto RL {} la distinción imitación-vs-maximización de H-LEARN-4.").format(
            status, "confirma" if status == 'apoyada' else ("apoya direccionalmente" if status == 'mixta' else "no logra demostrar (método)")),
        measurement="exp020: degen imit={} rl_weak={} rl_strong={} (base {}).".format(
            deg('imit_weak'), deg('rl_weak'), deg('rl_strong'), _fmt(base_deg)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada.")

    ceilings.add(CeilingRecord(
        subsystem="Reward-hack bajo RL-maximización vs imitación (F-LEARN-2) — método RL a escala tiny",
        known_limit=("exp020: el contrapunto RL {}. GRPO-lite a escala tiny es INESTABLE (colapsa con muchos "
                     "pasos; señal débil con pocos) -> demostrar el hack RL fuerte requiere RL estabilizado "
                     "(KL-reg, on-policy, baseline) o mayor escala. La distinción imitación-vs-maximización "
                     "(H-LEARN-4) {}.").format(
                         "apoya direccionalmente que RL es más hack-prone" if status == 'mixta'
                         else ("confirma el hack RL" if status == 'apoyada' else "no se demostró con este método"),
                         "se mantiene" if status in ('apoyada', 'mixta') else "queda abierta"),
        blockers=[{"text": "GRPO-lite inestable a escala tiny (colapso con muchos pasos / señal débil con pocos)", "kind": "diseno"}],
        real_or_assumed="asumido", evidence=[S1.ref, S2.ref, S3.ref]))
    notes.append("1 techo 'asumido' (método RL a escala tiny).")

    if status == 'mixta':
        dstmt = ("Apoyo DIRECCIONAL de que RL-maximización es más hack-prone que la imitación STaR (mismo "
                 "verificador débil); la imitación es la opción más SEGURA para la auto-mejora de Cognia-X. "
                 "Demostrar el hack RL fuerte requiere RL estable (KL/on-policy) -> future work; no adoptar RL "
                 "sin esa salvaguarda.")
        drat = ("exp020: rl_weak el más echo-prone (degen {} > imit {} > rl_strong {}) pero modesto; GRPO-lite inestable.").format(
            deg('rl_weak'), deg('imit_weak'), deg('rl_strong'))
    elif status == 'apoyada':
        dstmt = ("Confirmado: RL-maximización + verificador débil se reward-hackea; la imitación NO. Preferir "
                 "imitación STaR para auto-mejora; si se usa RL, exigir verificador fuerte + salvaguardas (KL).")
        drat = ("exp020: rl_weak se hackea, imit no, rl_strong no.")
    else:
        dstmt = ("El contrapunto RL no se pudo demostrar con GRPO-lite a escala tiny (inestable). La distinción "
                 "imitación-vs-maximización queda como hipótesis con apoyo de literatura; future work: RL estable.")
        drat = s.get('verdict', '')
    dec = Decision(id="D-LEARN-5", statement=dstmt, rationale=drat, sources=[_to_plain(S3), _to_plain(S2)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-LEARN-5 ACEPTADA por el ledger (tier5 S3 + tier1 S2).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-LEARN-5:", e); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle33_rl_vs_imitation',
                                description='CYCLE 33 (H-LEARN-5: RL-maximización vs imitación / reward-hack).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    ledger, hyps, ceilings, record, notes, status, s = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 33: RL-maximización vs imitación / reward-hack (H-LEARN-5)")
    print("=" * 78)
    print("veredicto H-LEARN-5:", status.upper() if status else "?")
    print("  " + s.get('verdict', ''))
    print("")
    for n in notes:
        print("  CHECK ", n)
    print("")
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
