r"""
cycle152_downstream_payoff.py — CICLO 152 (RESET v4, FRONTERA REAL §4.2, la pregunta viva que el 151 dejó EXPLÍCITA): H-V4-9l por
las compuertas del engine. ¿El residuo de calibración GENÉRICO (ls_lo) que el 151 halló sobrevive en AUROC_fixed sólo en SIGNO
(no robusto) PAGA DOWNSTREAM en una DECISIÓN real bajo escasez (precision@top-m sobre un pool fijo balanceado)? + ¿sobrevive sobre
candidatos HELD-OUT (forma novel '2+(n-2)', atacando la acotación in-distribution de la sonda-A del 151)?

VEREDICTO: <SE COMPLETA TRAS LA VERIFICACIÓN ADVERSARIAL — este script es verdict-driven; lee results.json>.

DERIVA de exp134_downstream_payoff/results/results.json (lazo torch REAL, N=6, mismo harness; 3 brazos; 2 pools fijos balanceados
INDIST/HELDOUT; precision@top-m barrido). El narrative_* abajo se ajusta tras la verificación adversarial; el verdict de results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle152_downstream_payoff')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp134_downstream_payoff', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _bestg(sm, pool):
    """gap ls_lo−naive en el mejor m de escasez del pool (best_m; las claves de payoff_gap son strings por JSON)."""
    bm = sm['best_m'][pool]
    return sm['payoff_gap'][pool]['ls_lo'][str(bm)], bm


VERIF_CLAIM = (
    "verificación adversarial (4 sondas + síntesis; recomendó MIXTA, design_valid=False, 'NO REFUTADA-plana'): 1 CONFIRMA + 2 ACOTA "
    "+ 1 REFUTA. (A-REFUTA, sev ALTA -el hallazgo principal-): el test NO valida la tesis de escasez (123). El pool es BALANCEADO "
    "50/50 (base-rate 0.50, el POLO OPUESTO a la escasez q≈0.08 de 123/exp107) y precision@top-m está TOPADA en 1.0; por la PROPIA "
    "lección de exp124 (que abandonó el m-absoluto por f=m/#correct porque 'm<<#correctas satura: hallar pocas correctas es trivial'), "
    "con #correct=48 todo m<=8 → f<=0.17 = régimen TRIVIAL/abundancia, y el grid (m_max=24) sólo llega a f=0.5; el f≈1 calibración-"
    "crítico (m≈48) quedó FUERA. exp134 REGRESÓ al m-absoluto que exp124 ya había desechado → el régimen de escasez de 123 NUNCA se "
    "testeó. (B-CONFIRMA, sev baja): la saturación de INDIST es genuina (no bug) -naive payoff=1.0 EXACTO en m<=12, gaps por-seed "
    "[0,0,0,0,0,0]; pool 50/50 + naive near-perfecto → top-m escaso trivialmente correcto para ambos- PERO es un ARTEFACTO DE TECHO de "
    "_payoff_at_m, NO 'ls_lo no aporta in-distribution' (su AUROC SÍ supera al naive, +0.018 6/6). (C-ACOTA, sev media): la señal "
    "HELDOUT es REAL-PERO-DÉBIL/NO-ROBUSTA, no 'genuina' -m=6 gaps [0.042,0,0.083,0,0.042,0] = 3/6 positivos/3/6 empate-cero/0 "
    "negativos; t=2.0 < t_crit 2.015; el CI [0.007,0.056] excluye 0 sólo por DISCRETIZACIÓN (0.5^6<2.5%), NO es fuerza independiente; "
    "frágil a leave-one-out. (D-ACOTA, sev media): 'REFUTADA / tampoco paga en la decisión' SOBRE-VENDE la negatividad -fusiona INDIST-"
    "saturado (no-informativo, no negativo) con evidencia adversa, e iguala al durable (robustamente NEGATIVO -confirma su inversión "
    "del 151 fuera-de-forma: indist m=8 −0.042 t=−2.70, heldout todo m negativo-) con ls_lo (borderline-FAVORABLE)-> son "
    "cualitativamente distintos. ERRORES CAZADOS: m-absoluto mislabel 'escasez' (contradice exp124); overstatement de negatividad; "
    "overclaim 'genuina' del heldout; criterio APOYADA inalcanzable por construcción en INDIST. PRÓXIMO (153): pool fijo COMPARTIDO de "
    "BAJA base-rate (q≈0.1) o medir a f≈1, preservando el desconfound del 151; subir N; reportar f=m/#correct.")


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp134 primero): " + results_path)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    nb = finalize_narrative(status, sm)
    for src in nb['sources']:
        ledger.add_source(src)
    notes.append(nb['sources_note'])

    hyp = Hypothesis(id="H-V4-9l", statement=nb['hyp_statement'], prediction=nb['hyp_prediction'],
                     status='abierta', confidence=nb['confidence'], evidence_for=nb['ev_for'],
                     evidence_against=nb['ev_against'], adversarial_verdict=nb['advtext'],
                     experiment_ref="exp134_downstream_payoff")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9l")
        notes.append(nb['mark_note'])

    analogy = nb['analogy']
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append(nb['analogy_note'])

    ceilings.add(nb['ceiling'])
    notes.append(nb['ceiling_note'])

    try:
        ledger.record_decision(nb['decision'])
        notes.append(nb['decision_note'])
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-112:", ex); raise

    return record, notes, status, sm


def finalize_narrative(status, sm):
    """status='mixta' (MIXTA-deflacionaria/ACOTADA): el residuo NO paga ROBUSTAMENTE, PERO el test está ACOTADO por SATURACIÓN
    (INDIST no-informativo) y NO testea la escasez real de 123 (pool 50/50, no q-bajo); HELDOUT borderline; durable robustamente NEG."""
    au = sm['auroc']; nsp = sm['naive_scarce_payoff']; sat = sm['saturated']; tcrit = sm.get('t_crit_one_tail_05', 0.0)
    gh, bh = _bestg(sm, 'heldout')
    fbh = sm['f_grid']['heldout'][str(bh)]
    bi = sm['best_m']['indist']; di = sm['payoff_gap']['indist']['durable'][str(bi)]
    fmax = max(sm['f_grid']['heldout'][str(m)] for m in sm['m_grid'])
    ncorr = sm['ncorrect_mean']['heldout']

    S_PRINCIPLE = Source(tier=2, ref=(
        "el residuo de calibración GENÉRICO que sobrevive un desconfound (151) NO rinde una ventaja DECISIONAL ROBUSTA bajo el test "
        "medido (precision@top-m sobre un pool balanceado) -- pero ese test está ACOTADO por SATURACIÓN (donde el baseline ya rankea "
        "el tope perfecto no hay decisión que ganar) y NO instancia la escasez (q bajo) donde la tesis brújula-decisional vive; el "
        "régimen discriminante queda sin testear."), obtained=False,
        claim=("Sobre un pool fijo balanceado 50/50, el residuo ls_lo NO paga downstream robustamente (INDIST saturado → gap cero "
               "estructural; HELDOUT borderline no-robusto, t={tln}<{tc}). PERO el test NO mide la escasez de 123 (f<={fmax}, nunca "
               "f≈1) → ACOTADO, no refutación. El durable es robustamente NEGATIVO (confirma su inversión del 151). (Principio "
               "acotado.)").format(tln=_f(gh['tstat']), tc=_f(tcrit), fmax=_f(fmax)))
    S_151 = Source(tier=5, ref="cognia_x/experiments/exp133 (CYCLE 151) — el residuo cuyo PAGO DOWNSTREAM este ciclo intenta medir", obtained=True,
        claim=("El 151 halló que del payoff de calibración del lazo real sólo SOBREVIVE un residuo GENÉRICO (ls_lo) en AUROC, en SIGNO "
               "y no robusto, y que la cura 119 (durable) se INVIERTE. H-V4-9l intenta el pago DOWNSTREAM de ese residuo: NO paga "
               "robustamente; y el durable se INVIERTE TAMBIÉN downstream (robustamente negativo) -> consistente con el 151, también "
               "sobre forma HELD-OUT (novel)."))
    S_VERIF = Source(tier=4, ref="verificación adversarial (workflow, 4 sondas con probes reales sobre los datos crudos + síntesis)", obtained=True,
        claim=VERIF_CLAIM)
    claim134 = ("exp134 (propio, lazo torch REAL, N={n}, mismo harness; 2 pools fijos balanceados 48/48 INDIST -forma canónica- y "
                "HELDOUT -forma novel '2+(n-2)' no entrenada-; precision@top-m). AUROC_fixed indist naive {ani} durable {adi} ls_lo "
                "{ali}; heldout naive {anh} durable {adh} ls_lo {alh} (sanity vs 151: el durable se invierte en AMBOS). DECISIÓN: "
                "INDIST SATURADO (naive precision@top-m de escasez {nsi}=techo → gap ls_lo CERO ESTRUCTURAL, no informativo). HELDOUT "
                "informativo (naive {nsh}<1): ls_lo−naive mejor m={bh} (f={fbh}) {ghm} (CI {ghci}, t={ght} < t_crit {tc}; {ghp}/{ghn} "
                "seeds+, 0 neg) → DÉBIL BORDERLINE no-robusto. durable robustamente NEGATIVO (indist m={bi} {dim}, t={dit}). f<={fmax} "
                "(nunca f≈1) → la escasez de 123 sin testear.").format(
                    n=sm['n'], ani=_f(au['indist']['naive']), adi=_f(au['indist']['durable']), ali=_f(au['indist']['ls_lo']),
                    anh=_f(au['heldout']['naive']), adh=_f(au['heldout']['durable']), alh=_f(au['heldout']['ls_lo']),
                    nsi=_f(nsp['indist']), nsh=_f(nsp['heldout']), bh=bh, fbh=_f(fbh), ghm=_f(gh['mean']), ghci=gh['ci95'],
                    ght=_f(gh['tstat']), tc=_f(tcrit), ghp=gh['n_positive'], ghn=gh['n'], bi=bi, dim=_f(di['mean']),
                    dit=_f(di['tstat']), fmax=_f(fmax))
    S_EXP134 = Source(tier=5, ref="cognia_x/experiments/exp134_downstream_payoff", obtained=True, claim=claim134)

    ev_for = [S_EXP134.ref, S_151.ref, S_VERIF.ref]
    ev_against = [S_PRINCIPLE.ref]   # contra-consideración: el test está ACOTADO (no refuta la tesis; el régimen escaso sin testear)

    advtext = (
        "{V}-downstream (NO-paga-ROBUSTAMENTE pero ACOTADO por saturación; NO refutación-plana; verificación adversarial de 4 sondas "
        "recomendó MIXTA, design_valid=False): el 151 dejó EXPLÍCITA la pregunta -¿el residuo genérico ls_lo (único superviviente del "
        "desconfound, en AUROC sólo en signo) PAGA DOWNSTREAM en una decisión bajo escasez (la tesis brújula-decisional 123)?-. "
        "exp134 (N={n}, mismo lazo real, 2 pools fijos balanceados 48/48: INDIST forma canónica + HELDOUT forma novel '2+(n-2)' no "
        "entrenada -ataca la acotación in-distribution de la sonda-A del 151-; precision@top-m). QUÉ SE ESTABLECE: (a) el residuo NO "
        "PAGA ROBUSTAMENTE: falla CI+t-test+6/6 en ambos pools. (b) PERO el cierre honesto es MIXTA-ACOTADA, no refutación-plana, por "
        "dos defectos de DISEÑO que la verificación cazó (sonda-A, sev ALTA, REFUTA): (b1) el pool es BALANCEADO 50/50 -NO escaso- y "
        "precision@top-m está TOPADA en 1.0 → INDIST está SATURADO (naive {nsi} en m de escasez → gap CERO ESTRUCTURAL, criterio "
        "APOYADA inalcanzable ahí); (b2) por la PROPIA lección de exp124 (f=m/#correct; m<<#correct es trivial), con #correct≈{ncorr} "
        "todo m de escasez → f<={fmax} (régimen trivial); el f≈1 calibración-crítico NUNCA se midió → la tesis 123 (q bajo) quedó SIN "
        "TESTEAR. (c) En el único pool informativo (HELDOUT, naive {nsh}<1, con headroom): ls_lo−naive mejor m={bh} (f={fbh}) {ghm} "
        "(CI {ghci}, t={ght} < t_crit {tc}; {ghp}/{ghn} seeds+, 0 negativos) → señal DÉBIL BORDERLINE no-robusta (falla por margen "
        "0.015 + empates-en-cero, NO por evidencia adversa; el CI excluye 0 sólo por DISCRETIZACIÓN, no es fuerza independiente). "
        "(d) El durable (cura 119) es ROBUSTAMENTE NEGATIVO en AMBOS pools (indist m={bi} {dim}, t={dit}; heldout también) → confirma "
        "su INVERSIÓN del 151, ahora también DOWNSTREAM y fuera-de-forma (un hallazgo POSITIVO robusto, distinto del ls_lo borderline-"
        "favorable). RESULTADO HONESTO: el payoff del lazo real es generación + un residuo genérico que NO paga robustamente bajo "
        "escasez en el régimen medido, con una traza positiva borderline donde hay headroom (heldout) y el régimen de escasez REAL "
        "(q bajo / f≈1) SIN TESTEAR. ACOTACIÓN: N={n} smoke; toy-real, tarea a*b. PRÓXIMO (153): rehacer el test sobre un pool fijo "
        "COMPARTIDO de BAJA base-rate (q≈0.1) o a f≈1 (preservando el desconfound del 151); subir N; reportar f=m/#correct.").format(
            V=status.upper(), n=sm['n'], nsi=_f(nsp['indist']), ncorr=_f(ncorr), fmax=_f(fmax), nsh=_f(nsp['heldout']), bh=bh,
            fbh=_f(fbh), ghm=_f(gh['mean']), ghci=gh['ci95'], ght=_f(gh['tstat']), tc=_f(tcrit), ghp=gh['n_positive'],
            ghn=gh['n'], bi=bi, dim=_f(di['mean']), dit=_f(di['tstat']))

    hyp_statement = ("¿El residuo de calibración GENÉRICO (ls_lo, único superviviente del desconfound del 151) PAGA DOWNSTREAM en una "
                     "decisión real bajo escasez (precision@top-m sobre un pool fijo balanceado), y sobre candidatos HELD-OUT (forma "
                     "novel)? RESULTADO: MIXTA-ACOTADA -- NO paga ROBUSTAMENTE (falla CI+t-test+6/6), PERO el test está SATURADO "
                     "(INDIST no-informativo, precision@top-m topada en 1.0) y NO instancia la escasez de 123 (pool 50/50, f<={fmax}, "
                     "nunca f≈1); HELDOUT (informativo) da señal DÉBIL BORDERLINE no-robusta (m={bh}, t={ght}<{tc}); el durable es "
                     "robustamente NEGATIVO (confirma su inversión del 151 downstream). Alcance: lazo torch real CPU, N={n} smoke, "
                     "tarea a*b.").format(fmax=_f(fmax), bh=bh, ght=_f(gh['tstat']), tc=_f(tcrit), n=sm['n'])
    hyp_prediction = ("APOYADA-downstream si el residuo paga ROBUSTO (CI excl 0 + t-test + 6/6) en escasez en un pool INFORMATIVO. "
                      "REFUTADA si un pool informativo muestra claro no-pago. MIXTA si todos los pools informativos están saturados "
                      "(inconcluso) o la señal es borderline. (Pre-registrada; con detección de SATURACIÓN -un pool near-ceiling es "
                      "no-informativo, su gap es cero estructural-; verificación adversarial sobre los datos crudos.)")

    mark_note = ("H-V4-9l marcada 'mixta' (MIXTA-deflacionaria/ACOTADA): el residuo genérico NO paga ROBUSTAMENTE bajo escasez, PERO "
                 "(1) INDIST está SATURADO (no-informativo, gap cero estructural) y (2) el pool 50/50 NO es escaso (f<={fmax}, la "
                 "tesis 123 sin testear) → no es refutación-plana. HELDOUT borderline no-robusto (m={bh}, t={ght}<{tc}). El durable "
                 "robustamente NEGATIVO (confirma 151). El régimen de escasez real → CYCLE 153.").format(
                     fmax=_f(fmax), bh=bh, ght=_f(gh['tstat']), tc=_f(tcrit))

    analogy = AnalogyRecord(
        problem=("El 151 dejó una pizca de criterio real (genérico) que ordena un poco mejor que el baseline. ¿Esa pizca SIRVE para "
                 "DECIDIR mejor -elegir las pocas respuestas a someter- cuando hay que elegir bajo escasez?"),
        everyday=("No se pudo contestar bien porque el examen era demasiado fácil. Para 'decidir' les pedimos someter las respuestas "
                  "más confiadas y medir cuántas eran correctas. Pero el conjunto tenía MITAD correctas (no escaso) y el modelo ya "
                  "ordenaba casi perfecto: las pocas más confiadas eran trivialmente correctas para TODOS -> nadie podía ganar ahí "
                  "(saturado). Sólo cuando cambiamos a un examen de FORMA no vista (más difícil, con margen) la pizca genérica asomó "
                  "-un poquito mejor que el baseline- pero TAN al borde que no es firme. Y el modelo 'curado' (la cura del 151) "
                  "DECIDIÓ peor en todos lados, confirmando su problema. Conclusión honesta: en el examen fácil no se puede medir; en "
                  "el difícil la pizca asoma pero no firme; y el examen DE VERDAD escaso (pocas correctas, donde elegir bien importa) "
                  "ni siquiera lo dimos -> queda para el próximo ciclo."),
        solutions=["INDIST saturado: naive precision@top-m de escasez {nsi}=techo -> gap ls_lo CERO ESTRUCTURAL (no informativo)".format(nsi=_f(nsp['indist'])),
                   "HELDOUT (con headroom): ls_lo−naive m={bh} {ghm} (t={ght} < t_crit {tc}, {ghp}/{ghn} seeds+, 0 neg) -> débil borderline, no robusto".format(bh=bh, ghm=_f(gh['mean']), ght=_f(gh['tstat']), tc=_f(tcrit), ghp=gh['n_positive'], ghn=gh['n']),
                   "el pool 50/50 NO es escaso (f<={fmax}, nunca f≈1) -> la tesis 123 (calibración paga bajo escasez) sin testear".format(fmax=_f(fmax)),
                   "el durable (cura 119) ROBUSTAMENTE NEGATIVO downstream (indist m={bi} {dim}, t={dit}) -> confirma su inversión del 151 fuera-de-forma".format(bi=bi, dim=_f(di['mean']), dit=_f(di['tstat']))],
        principles=["precision@top-m está TOPADA en 1.0: si el baseline ya rankea el tope perfecto, la métrica SATURA y el gap es "
                    "CERO ESTRUCTURAL -> un pool near-ceiling es NO-INFORMATIVO para el test decisional (no negativo)",
                    "'m chico' NO es 'escasez': la escasez decisional es f=m/#correct≈1 (o base-rate baja), no presupuesto absoluto "
                    "chico (que es trivial: hallar pocas correctas entre muchas es fácil) -- lección de exp124, re-aprendida",
                    "una métrica saturada NO puede ni APOYAR ni REFUTAR: el veredicto honesto sobre un pool saturado es INCONCLUSO, "
                    "no refutación; sólo los pools informativos (con headroom) cuentan",
                    "META: la verificación adversarial cazó un DEFECTO DE DISEÑO (no de prosa) -> el ciclo se re-etiqueta ACOTADA y "
                    "siembra el diseño correcto del siguiente; un ciclo que descubre que midió mal el régimen es progreso honesto"],
        adaptation=("FRONTERA REAL §4.2 (la pregunta viva del 151: ¿el residuo paga downstream?). Intento fallido-instructivo: el pool "
                    "balanceado (necesario para el desconfound) SATURA la decisión y NO instancia la escasez. PRÓXIMO (153): pool fijo "
                    "COMPARTIDO de BAJA base-rate (q≈0.1) o medir a f≈1, preservando el desconfound del 151; subir N; reportar f."),
        measurement=("exp134 (lazo torch real, N={n}): INDIST saturado (naive_scarce {nsi}); HELDOUT informativo ls_lo m={bh} {ghm} "
                     "(t={ght}<{tc}); durable indist m={bi} {dim} (t={dit}); AUROC indist {ani}/{adi}/{ali}, heldout {anh}/{adh}/{alh}; "
                     "f<={fmax}.").format(n=sm['n'], nsi=_f(nsp['indist']), bh=bh, ghm=_f(gh['mean']), ght=_f(gh['tstat']),
                         tc=_f(tcrit), bi=bi, dim=_f(di['mean']), dit=_f(di['tstat']), ani=_f(au['indist']['naive']),
                         adi=_f(au['indist']['durable']), ali=_f(au['indist']['ls_lo']), anh=_f(au['heldout']['naive']),
                         adh=_f(au['heldout']['durable']), alh=_f(au['heldout']['ls_lo']), fmax=_f(fmax)),
        iterations=3)
    analogy_note = ("Analogía 7 etapas registrada (el examen era demasiado fácil -saturado- para medir si la pizca de criterio sirve "
                    "para decidir; sólo asoma en el examen difícil -heldout- pero no firme; el examen escaso real queda para el 153).")

    kl = ("REAL (exp134, MIXTA-ACOTADA + verificación adversarial design_valid=False): el residuo genérico (ls_lo) NO paga "
          "ROBUSTAMENTE downstream en el test medido, PERO el test está SATURADO (INDIST no-informativo, precision@top-m topada en "
          "1.0) y NO instancia la escasez de 123 (pool 50/50, f<={fmax}). HELDOUT borderline no-robusto (m={bh}, t={ght}<{tc}). "
          "durable robustamente NEGATIVO (confirma 151). TECHO/ALCANCE: N={n} smoke; AUROC near-ceiling in-distribution; toy-real. NO "
          "cubre: el régimen de ESCASEZ REAL (q bajo / f≈1) -> CYCLE 153.").format(
              fmax=_f(fmax), bh=bh, ght=_f(gh['tstat']), tc=_f(tcrit), n=sm['n'])
    ceiling = CeilingRecord(
        subsystem=("PAGO DOWNSTREAM del residuo de calibración del 151: ¿paga en una decisión bajo escasez (precision@top-m)? "
                   "RESULTADO: MIXTA-ACOTADA -- NO paga robustamente en el régimen medido, pero el test SATURA (INDIST no-informativo) "
                   "y NO instancia la escasez real (pool 50/50); HELDOUT borderline; durable robustamente NEG. La escasez real → 153"),
        known_limit=kl,
        blockers=[{"text": ("DEFECTO DE DISEÑO (cazado por verificación, sev ALTA): el pool balanceado 50/50 -necesario para el "
                            "desconfound del 151- SATURA precision@top-m (INDIST naive {nsi}=techo → gap cero estructural) y NO es "
                            "escaso (f<={fmax}, nunca f≈1). El test NO valida la tesis 123 (q bajo). Honestidad: ACOTADA, no "
                            "refutación-plana.").format(nsi=_f(nsp['indist']), fmax=_f(fmax)), "kind": "diseno"},
                  {"text": ("HELDOUT (único informativo) da señal DÉBIL BORDERLINE no-robusta: m={bh} {ghm} (t={ght} < t_crit {tc}; "
                            "{ghp}/{ghn} seeds+, 0 neg; CI excluye 0 sólo por discretización). Falla robustez por margen, NO por "
                            "evidencia adversa. Pendiente N mayor.").format(bh=bh, ghm=_f(gh['mean']), ght=_f(gh['tstat']),
                            tc=_f(tcrit), ghp=gh['n_positive'], ghn=gh['n']), "kind": "fisico"},
                  {"text": ("FRONTERA ABIERTA (CYCLE 153): rehacer el downstream sobre un pool fijo COMPARTIDO de BAJA base-rate "
                            "(q≈0.1) o a f≈1, preservando el desconfound; subir N; reportar f=m/#correct. Sólo ahí precision@top-m "
                            "discrimina ranking y deja de saturar. La inversión robusta del durable downstream SÍ es un hallazgo "
                            "firme (confirma 151)."), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP134.ref, S_151.ref, S_VERIF.ref])
    ceiling_note = ("1 techo 'real': el pago downstream del residuo es MIXTA-ACOTADA -- el test balanceado SATURA y no instancia la "
                    "escasez real; HELDOUT borderline; durable robustamente NEG (confirma 151). El régimen escaso real → CYCLE 153.")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- la pregunta viva del 151): {V}. ¿El residuo genérico (ls_lo) PAGA DOWNSTREAM "
             "bajo escasez? exp134 (2 pools fijos balanceados 48/48, precision@top-m): NO paga ROBUSTAMENTE, PERO el test está "
             "SATURADO (INDIST naive {nsi}=techo → gap cero estructural, no-informativo) y NO instancia la escasez de 123 (pool 50/50, "
             "f<={fmax}, nunca f≈1) → MIXTA-ACOTADA, no refutación-plana. HELDOUT (informativo) borderline no-robusto (m={bh}, "
             "t={ght}<{tc}). El durable (cura 119) robustamente NEGATIVO downstream (confirma su inversión del 151 fuera-de-forma). "
             "Verificación adversarial de 4 sondas (design_valid=False, recomendó MIXTA). Decisión: ADOPTAR que (1) el residuo NO paga "
             "robustamente en el régimen medido, (2) PERO la tesis brújula-decisional (123) bajo ESCASEZ REAL queda SIN TESTEAR "
             "-defecto de diseño: el pool balanceado satura y no es escaso-, (3) la inversión del durable se CONFIRMA downstream. "
             "Próximo (153): pool fijo COMPARTIDO de BAJA base-rate o f≈1, preservando el desconfound; subir N.").format(
                 V=status.upper(), nsi=_f(nsp['indist']), fmax=_f(fmax), bh=bh, ght=_f(gh['tstat']), tc=_f(tcrit))
    drat = ("exp134 (tier5, propio, lazo torch real, N={n}, post-verificación adversarial de 4 sondas que recomendó MIXTA, "
            "design_valid=False): el residuo genérico NO paga robustamente (falla CI+t-test+6/6), PERO el test SATURA (INDIST "
            "no-informativo) y NO instancia la escasez (pool 50/50, f<={fmax}); HELDOUT borderline; durable robustamente NEG (confirma "
            "151). Convergente con el principio (tier2), el 151 (tier5) y la verificación (tier4). MIXTA-ACOTADA: no refutación-plana; "
            "el régimen escaso real sin testear (153).").format(n=sm['n'], fmax=_f(fmax))
    decision = Decision(id="D-V4-112", statement=dstmt, rationale=drat,
                        sources=[_to_plain(S_EXP134), _to_plain(S_151), _to_plain(S_VERIF)], important=True)

    return {
        "sources": [S_PRINCIPLE, S_151, S_VERIF, S_EXP134],
        "sources_note": ("4 fuentes (S_PRINCIPLE tier2 residuo no-paga-robusto pero test acotado; S_151 tier5 el residuo cuyo pago se "
                         "mide + la inversión que se confirma; S_VERIF tier4 verificación recomendó MIXTA design_valid=False; S_EXP134 "
                         "tier5 dato propio MIXTA-acotada)."),
        "hyp_statement": hyp_statement, "hyp_prediction": hyp_prediction, "confidence": "media",
        "ev_for": ev_for, "ev_against": ev_against, "advtext": advtext, "mark_note": mark_note,
        "analogy": analogy, "analogy_note": analogy_note, "ceiling": ceiling, "ceiling_note": ceiling_note,
        "decision": decision, "decision_note": "D-V4-112 ACEPTADA por el ledger (tier5 exp134 + tier5 151 + tier4 verificación adversarial)."}


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle152_downstream_payoff',
                                description='CYCLE 152 (RESET v4, H-V4-9l: ¿el residuo de calibración paga DOWNSTREAM bajo escasez?).')
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
    print("RESUMEN — CYCLE 152 (RESET v4): ¿el residuo paga DOWNSTREAM bajo escasez? — H-V4-9l " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9l:", status.upper() if status else "?")
    for n_ in notes:
        print("  CHECK ", n_)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
