r"""
cycle32_reward_hack.py — CICLO 32 a través del Investigation Engine (frente F-LEARN-2).

H-LEARN-4: ¿un verificador real DÉBIL es EXPLOTABLE (reward-hack) cuando el atajo (echo del target) está en
el repertorio del modelo? Resuelve el cabo de CYCLE 31 (el hack no emergió porque el atajo no era alcanzable).
exp019 SIEMBRA el atajo (base con mezcla real+echo) y compara weak (acepta el echo) vs strong (lo rechaza).

DERIVA el veredicto de exp019_reward_hack/results/results.json (degenerate y real_acc finales por brazo).
Pasa por las compuertas. Hallazgo esperado/honesto: en un loop STaR de IMITACIÓN (copia lo verificado-
aceptado), el reward-hack NO emerge fácilmente — a diferencia de RL (que MAXIMIZA la aceptación y caza el
atajo). Refina la preocupación de reward-hacking: es más una patología de RL-maximización que de imitación.

Correr (DESPUÉS de exp019):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp019_reward_hack.run --seeds 0,1,2 --p_echo 0.35
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle32_reward_hack
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle32_reward_hack')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp019_reward_hack', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


S1 = Source(tier=1, ref="arXiv:1606.06565", obtained=True,
            claim=("Amodei et al. 2016 (Concrete Problems in AI Safety): reward hacking — un agente que "
                   "MAXIMIZA una recompensa/verificador imperfecto explota atajos triviales. Predice que un "
                   "verificador débil sería gameado SI el agente maximiza su aceptación."))
S2 = Source(tier=1, ref="arXiv:2203.14465", obtained=True,
            claim=("Zelikman et al. 2022 (STaR): el bootstrapping verificado IMITA (fine-tune sobre) las "
                   "auto-generaciones aceptadas — no maximiza la aceptación con RL. Distingue imitación de "
                   "maximización: la imitación copia salidas aceptadas, no caza el atajo más barato."))


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp019 primero): " + results_path)
    s = data['summary']
    ledger, hyps, ceilings, record = EvidenceLedger(store), HypothesisRegistry(store), CeilingTracker(store), PermanentRecord(store)
    notes = []
    status = s.get('status')
    fin = s.get('final', {})
    base_deg = s.get('base_degenerate')
    deg_gap = s.get('deg_gap_weak_minus_strong')
    real_gap = s.get('real_gap_strong_minus_weak')

    S3 = Source(tier=5, ref="cognia_x/experiments/exp019_reward_hack", obtained=True,
                claim=("exp019 (atajo echo SEMBRADO en el base, p_echo=0.35, base degenerate={bd}; test held-out "
                       "DISJUNTO, n=3, loop STaR de imitación, temp alta): weak degenerate(final)={wd} vs strong "
                       "{sd} (gap {dg}); real_acc strong={sr} vs weak={wr} (gap {rg}). hacked={hk}. {verdict}").format(
                           bd=_fmt(base_deg), wd=_fmt(fin.get('weak', {}).get('degen')),
                           sd=_fmt(fin.get('strong', {}).get('degen')), dg=_fmt(deg_gap),
                           sr=_fmt(fin.get('strong', {}).get('real')), wr=_fmt(fin.get('weak', {}).get('real')),
                           rg=_fmt(real_gap), hk=s.get('hacked'), verdict=s.get('verdict', '')))
    for src in (S1, S2, S3):
        ledger.add_source(src)
    notes.append("3 fuentes (S1 tier1 reward-hacking/Amodei; S2 tier1 STaR/imitación; S3 tier5 exp019).")

    if status == 'apoyada':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        adv = ("APOYADA: con el atajo en el repertorio, el verificador DÉBIL se REWARD-HACKEA (degenerate weak "
               ">> strong, gap {dg}; real_acc strong > weak, gap {rg}) y el FUERTE lo suprime -> un verificador "
               "real débil ES explotable cuando el exploit es alcanzable (Amodei 2016). CYCLE 31 no lo vio "
               "porque el atajo no estaba en el repertorio.").format(dg=_fmt(deg_gap), rg=_fmt(real_gap))
    elif status == 'refutada':
        ev_for, ev_against = [S2.ref, S3.ref], [S1.ref]
        adv = ("REFUTADA (con insight): aun con el atajo SEMBRADO en el repertorio, el verificador DÉBIL NO se "
               "reward-hackea en un loop STaR de IMITACIÓN (degenerate weak={wd} ~ strong={sd}, base {bd}; no "
               "domina el echo). RAZÓN (refina Amodei 2016): la imitación COPIA las auto-generaciones aceptadas, "
               "no MAXIMIZA la aceptación como RL -> no caza el atajo más barato; mientras el camino honesto sea "
               "viable y se genere, el weak lo refuerza igual. Matiz secundario: el FUERTE igual da MÁS real_acc "
               "(señal de entrenamiento más pura, real_gap {rg}). -> el reward-hack es más una patología de "
               "RL-maximización que de verified-imitation a esta escala.").format(
                   wd=_fmt(fin.get('weak', {}).get('degen')), sd=_fmt(fin.get('strong', {}).get('degen')),
                   bd=_fmt(base_deg), rg=_fmt(real_gap))
    else:
        ev_for, ev_against = [S1.ref], [S3.ref, S2.ref]
        adv = ("MIXTA: hack parcial — el degenerate del weak sube algo pero el gap con strong o el efecto en "
               "real no cruza el umbral; señal ambigua a esta escala.")

    hyp = Hypothesis(
        id="H-LEARN-4",
        statement=("Un verificador real DÉBIL es EXPLOTABLE (reward-hack: el echo del target domina) cuando el "
                   "atajo está en el repertorio del modelo; el verificador FUERTE lo suprime."),
        prediction=("weak.degenerate(final) >> strong.degenerate(final) y weak.real_acc < strong.real_acc. "
                    "Refutado si weak no se hackea aun con el atajo sembrado."),
        status='abierta', confidence='media', evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp019_reward_hack")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-LEARN-4")
        notes.append("H-LEARN-4 marcada '{}' con DoD completo.".format(status))
    else:
        notes.append("H-LEARN-4 queda 'abierta'.")

    analogy = AnalogyRecord(
        problem=("Si tu solucionario es DÉBIL (acepta respuestas triviales) y vos CONOCÉS el truco, ¿lo usás? "
                 "Depende de si solo COPIÁS tus ejercicios aprobados (imitación) o si MAXIMIZÁS aprobar (RL)."),
        everyday=("Un estudiante que solo repasa sus ejercicios aprobados (imitación) no necesariamente abusa "
                  "del truco si ya resuelve bien; uno que SOLO busca el sello de aprobado (maximizar) abusa del "
                  "solucionario débil. El verificador fuerte cierra el truco en ambos casos."),
        solutions=["RL que maximiza la aceptación + verificador débil -> abusa del atajo (Amodei)",
                   "STaR/imitación + verificador débil -> NO necesariamente abusa (copia lo aceptado honesto)",
                   "verificador FUERTE -> cierra el atajo y da señal más pura (más competencia real)",
                   "medir degenerate separado de real_acc detecta el abuso"],
        principles=["el reward-hack depende del OBJETIVO (maximizar) más que de la mera debilidad del verificador",
                    "la imitación de salidas verificadas es más robusta al atajo que la maximización RL",
                    "un verificador fuerte cierra el atajo Y purifica la señal (más competencia real)"],
        adaptation=("H-LEARN-4 {}: a esta escala el reward-hack {} en el loop STaR de imitación.").format(
            status, "EMERGE (verificador débil explotable)" if status == 'apoyada' else "NO emerge (imitación robusta)"),
        measurement="exp019: weak degen={} vs strong={} (base {}); real strong={} vs weak={}.".format(
            _fmt(fin.get('weak', {}).get('degen')), _fmt(fin.get('strong', {}).get('degen')), _fmt(base_deg),
            _fmt(fin.get('strong', {}).get('real')), _fmt(fin.get('weak', {}).get('real'))),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada.")

    ceilings.add(CeilingRecord(
        subsystem="Explotabilidad del verificador débil bajo STaR-imitación (reward-hack) — F-LEARN-2",
        known_limit=("exp019: el reward-hack del verificador débil {}. En un loop de IMITACIÓN (STaR), copiar "
                     "lo verificado-aceptado no caza el atajo como RL-maximización. Aun así, un verificador "
                     "FUERTE es preferible (cierra el atajo + señal más pura). Específico de escala tiny + "
                     "loop no-RL.").format("EMERGE (débil explotable)" if status == 'apoyada'
                                           else "NO emerge a esta escala (imitación robusta; sería RL-específico)"),
        blockers=[{"text": "reward-hack requiere maximización (RL) + exploit alcanzable + más barato que el honesto", "kind": "diseno"}],
        real_or_assumed="asumido", evidence=[S1.ref, S2.ref, S3.ref]))
    notes.append("1 techo 'asumido' (condiciones del reward-hack).")

    if status == 'refutada':
        dstmt = ("La auto-mejora STaR (imitación de verificado-aceptado) de Cognia-X es ROBUSTA al reward-hack "
                 "del verificador débil a esta escala (no caza el atajo como RL). Aun así, preferir verificadores "
                 "FUERTES (cierran el atajo y dan señal más pura). El riesgo de reward-hack es RL-específico -> "
                 "tenerlo en cuenta SI se pasa a RL/maximización.")
        drat = ("exp019: weak degenerate ~ strong aun con el atajo sembrado; el FUERTE da más real_acc. "
                "Imitación != maximización (STaR vs RL).")
    elif status == 'apoyada':
        dstmt = ("Exigir verificadores FUERTES: un verificador real débil ES explotable (reward-hack) cuando el "
                 "exploit es alcanzable (exp019). Junto con D-LEARN-2/3, la calidad/fuerza del verificador es "
                 "requisito de primera clase para la auto-mejora.")
        drat = ("exp019: weak se hackea (degenerate gap {}), strong lo suprime.").format(_fmt(deg_gap))
    else:
        dstmt = ("Señal mixta sobre el reward-hack a esta escala; no decidir aún (ver verdict).")
        drat = s.get('verdict', '')
    dec = Decision(id="D-LEARN-4", statement=dstmt, rationale=drat, sources=[_to_plain(S3), _to_plain(S2)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-LEARN-4 ACEPTADA por el ledger (tier5 S3 + tier1 S2).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-LEARN-4:", e); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle32_reward_hack',
                                description='CYCLE 32 (H-LEARN-4: explotabilidad del verificador débil).')
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
    print("RESUMEN — CYCLE 32: explotabilidad del verificador débil / reward-hack (H-LEARN-4)")
    print("=" * 78)
    print("veredicto H-LEARN-4:", status.upper() if status else "?")
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
