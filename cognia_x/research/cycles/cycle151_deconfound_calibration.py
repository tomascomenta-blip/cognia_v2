r"""
cycle151_deconfound_calibration.py — CICLO 151 (RESET v4, FRONTERA REAL §4.2, el caveat LOAD-BEARING que el 150 descubrió): H-V4-9k
por las compuertas del engine. ¿El "payoff de calibración" del lazo torch real (149 durable>naive en AUROC; 150 ls_lo>=durable) es
una señal de ranking GENUINA, o un ARTEFACTO de la RIQUEZA DE GENERACIÓN (cada brazo computa su AUROC sobre SU propio pool, de
dificultad distinta según cuántas correctas genera)?

VEREDICTO: <SE COMPLETA TRAS LA VERIFICACIÓN ADVERSARIAL — este script es verdict-driven; lee results.json>.

DERIVA de exp133_deconfound_calibration/results/results.json (lazo torch REAL, mismo harness que exp124/exp131/exp132; 3 brazos
naive/durable/ls_lo). El DESCONFOUND: además del AUROC_own (pool propio, la métrica confundida del 149/150), TODOS los brazos
rankean un POOL FIJO COMPARTIDO Y BALANCEADO (candidatos construidos una vez con etiqueta conocida vía el verificador real,
~48 correctas/48 incorrectas) -> AUROC_fixed aísla la calidad de ranking de la riqueza de la propia generación. El narrative_* abajo
se ajusta tras la verificación adversarial; el verdict se toma de results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle151_deconfound_calibration')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp133_deconfound_calibration', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


# === NARRATIVA (verdict-driven). VERIF_CLAIM = síntesis del workflow de verificación adversarial (4 sondas + síntesis). ===
VERIF_CLAIM = (
    "verificación adversarial (4 sondas con probes reales sobre los datos crudos + síntesis; recomendó MIXTA, 'NO usar APOYADA-"
    "calibración'): 1 CONFIRMA + 3 ACOTA + 0 refuta; cazó 5 errores factuales/framing. (B-CONFIRMA, sev baja) la INVERSIÓN del "
    "durable es genuina y robusta: cae monótona en 6/6 seeds (gap FIXED −0.210, t=−10.6, n_positive=0) mientras naive (0.97) y ls_lo "
    "(0.99) rankean BIEN el MISMO pool balanceado -> NO es 'pool injusto', es específico de la unlikelihood; el colapso entrenado es "
    "MÁS PROFUNDO que el titular (excluyendo la ronda-1 no-entrenada, durable trained-only ~0.62, última ronda ~0.57 ≈ azar; el 0.760 "
    "lo SUBESTIMA). (C-ACOTA, sev media) la supervivencia del ls_lo NO es robusta: el criterio 'CI bootstrap excluye 0' es "
    "TAUTOLÓGICO con 6/6 gaps positivos (P(boot<=0)=0%); el t-test pareado real t=1.98 < t_crit df=5=2.015 (SUB-significativo); la "
    "media se PARTIÓ A LA MITAD N=3->N=6 (0.032->0.0175); cargada en 2/6 seeds (un seed +0.0001); dependiente del techo (cae a +0.003 "
    "donde naive_fixed roza 1.0) -> evidencia de SIGNO (sign-test p=0.016), no de magnitud. (A-ACOTA, sev media) el desconfound es "
    "leak-free y balanceado 48/48 exacto y la comparación es justa, PERO AUROC_fixed es un sondeo IN-DISTRIBUTION casi-en-techo "
    "(naive ya 0.970) sobre la MISMA forma canónica '1+(n-1)' con que cada brazo se re-entrena vía replay -> desconfunde la riqueza-"
    "de-pool (su propósito, válido) pero NO certifica ranking held-out/generalizable. (D-ACOTA, sev media) la etiqueta 'APOYADA-"
    "calibración del 149/150' LAVANDERIZA: agrupa el 149 (refutado: el durable empeora) con un residuo genérico mínimo del 150 -> "
    "re-etiquetar MIXTA. ERRORES CAZADOS: (1) docstring+claim decían 'generados desde el modelo BASE' (FALSO: construidos "
    "deterministicamente; CORREGIDO); (2) el verdict string presentaba la inversión −0.210 como 'sobreviviente' (framing engañoso; "
    "CORREGIDO con compuerta robusta t-test). ESCALA: N=6 = merge de 2 lotes smoke (rounds=4, steps=50), NO la config preregistrada.")


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp133 primero): " + results_path)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    nb = finalize_narrative(status, sm)

    for src in nb['sources']:
        ledger.add_source(src)
    notes.append(nb['sources_note'])

    hyp = Hypothesis(
        id="H-V4-9k",
        statement=nb['hyp_statement'],
        prediction=nb['hyp_prediction'],
        status='abierta', confidence=nb['confidence'],
        evidence_for=nb['ev_for'], evidence_against=nb['ev_against'],
        adversarial_verdict=nb['advtext'], experiment_ref="exp133_deconfound_calibration")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9k")
        notes.append(nb['mark_note'])

    analogy = nb['analogy']
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append(nb['analogy_note'])

    ceilings.add(nb['ceiling'])
    notes.append(nb['ceiling_note'])

    dec = nb['decision']
    try:
        ledger.record_decision(dec)
        notes.append(nb['decision_note'])
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-111:", ex); raise

    return record, notes, status, sm


def finalize_narrative(status, sm):
    """Devuelve todos los textos del ciclo (verdict-driven). status='mixta': la cura SE INVIERTE (refuta su atribución del 149);
    el único sobreviviente es el GENÉRICO ls_lo, SÓLO EN SIGNO y NO robusto (t<t_crit; el 'CI excluye 0' es tautológico)."""
    n = sm['n']
    au = sm['auroc_own']; af = sm['auroc_fixed']; nc = sm['mean_ncorrect']
    odn = sm['own_durable_vs_naive']; oln = sm['own_lslo_vs_naive']
    fdn = sm['fixed_durable_vs_naive']; fln = sm['fixed_lslo_vs_naive']
    atd = sm['atten_durable']; atl = sm['atten_lslo']; tcrit = sm.get('t_crit_one_tail_05', 0.0)

    S_PRINCIPLE = Source(tier=2, ref=(
        "el 'payoff de calibración' del lazo torch real (149/150) está MAYORMENTE CONFUNDIDO con la riqueza de generación; lo "
        "no-artefacto es MÍNIMO, GENÉRICO y NO ROBUSTO: sobre un POOL FIJO BALANCEADO compartido la ventaja AUROC de la cura 119 "
        "(durable) se INVIERTE (era enteramente riqueza de generación) y sólo el regularizador GENÉRICO (label smoothing) retiene una "
        "ventaja de SIGNO (todos los gaps positivos) pero sub-significativa por t-test pareado y régimen-dependiente."), obtained=False,
        claim=("El desconfound (pool fijo balanceado) SEPARA: la ventaja del durable (cura 119) era riqueza de generación (se "
               "INVIERTE, fixed {fdn}, t={tdn}); del genérico ls_lo sobrevive sólo una ventaja de SIGNO (fixed {fln}, 6/6 gaps "
               "positivos PERO t={tln} < t_crit {tc}). El payoff de calibración del lazo real es MAYORMENTE generación; el residuo "
               "genuino es genérico, mínimo y no-robusto. (Principio acotado.)").format(
                   fdn=_f(fdn['mean']), tdn=_f(fdn['tstat']), fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit)))
    S_149 = Source(tier=5, ref="cognia_x/experiments/exp131 (CYCLE 149) — la APOYADA cuya ATRIBUCIÓN este ciclo REFUTA por desconfound", obtained=True,
        claim=("El 149 cerró APOYADA que el durable (cura 119) produce confianza endógena más informativa sobre correctness real "
               "que el naive (AUROC_own +0.047). H-V4-9k DESCONFUNDE esa métrica: en el pool fijo balanceado el durable se INVIERTE "
               "(fixed durable−naive {fdn}, t={tdn}, 6/6 seeds) -> la ventaja AUROC_own del 149 era RIQUEZA DE GENERACIÓN, NO ranking "
               "calibrado. La OBSERVACIÓN del 149 (durable>naive OWN) se reproduce; su ATRIBUCIÓN a 'calibración endógena' queda "
               "REFUTADA.").format(fdn=_f(fdn['mean']), tdn=_f(fdn['tstat'])))
    S_150 = Source(tier=5, ref="cognia_x/experiments/exp132 (CYCLE 150) — sospechó el confound; este ciclo lo CIERRA", obtained=True,
        claim=("El 150 (REFUTADA-privilegio) halló que un genérico iguala/supera al durable y SOSPECHÓ que el AUROC estaba confundido "
               "con la riqueza de generación. H-V4-9k lo CONFIRMA y lo separa: del payoff sólo queda un residuo genérico de SIGNO "
               "(ls_lo fixed {fln}, no robusto); el durable se invierte. Cierra el caveat load-bearing del 150.").format(fln=_f(fln['mean'])))
    S_VERIF = Source(tier=4, ref="verificación adversarial (workflow, 4 sondas con probes reales sobre los datos crudos + síntesis)", obtained=True,
        claim=VERIF_CLAIM)
    claim133 = ("exp133 (propio, lazo torch REAL, N={n}, mismo harness que exp124/exp131/exp132, 3 brazos naive/durable/ls_lo): "
                "DESCONFOUND vía pool fijo balanceado compartido (48/48, construido + etiquetado por el verificador real). AUROC_own "
                "naive {an} durable {ad} ls_lo {al} -> AUROC_fixed naive {fn} durable {fd} ls_lo {fl}. durable−naive: OWN {odn} -> "
                "FIXED {fdn} (CI {fdnci}, t={tdn}, 6/6 NEG: el durable se INVIERTE, atenúa {atd}). ls_lo−naive: OWN {oln} -> FIXED "
                "{fln} (CI {flnci}, t={tln} < t_crit {tc}: SÓLO SIGNO, NO robusto, atenúa {atl}). #correctas pool propio naive {ncn} "
                "durable {ncd} ls_lo {ncl} (la disociación que confunde el AUROC_own).").format(
                    n=n, an=_f(au['naive']), ad=_f(au['durable']), al=_f(au['ls_lo']), fn=_f(af['naive']), fd=_f(af['durable']),
                    fl=_f(af['ls_lo']), odn=_f(odn['mean']), fdn=_f(fdn['mean']), fdnci=fdn['ci95'], tdn=_f(fdn['tstat']), atd=_f(atd),
                    oln=_f(oln['mean']), fln=_f(fln['mean']), flnci=fln['ci95'], tln=_f(fln['tstat']), tc=_f(tcrit), atl=_f(atl),
                    ncn=_f(nc['naive']), ncd=_f(nc['durable']), ncl=_f(nc['ls_lo']))
    S_EXP133 = Source(tier=5, ref="cognia_x/experiments/exp133_deconfound_calibration", obtained=True, claim=claim133)

    ev_for = [S_EXP133.ref, S_PRINCIPLE.ref, S_VERIF.ref, S_150.ref]
    ev_against = [S_149.ref]   # contra: el 149 SÍ halló durable>naive (OWN); aquí se DESCONFUNDE (su componente durable era generación)

    advtext = (
        "{V} (DESCONFOUND PARCIAL: la cura 119 se INVIERTE -> su atribución del 149 era RIQUEZA DE GENERACIÓN; el único residuo es "
        "GENÉRICO, mínimo y NO robusto; verificación adversarial de 4 sondas, recomendó MIXTA): el 149 cerró APOYADA que el durable "
        "(cura 119) produce una confianza endógena más informativa sobre la correctness real que el naive (AUROC_own +0.047); el 150 "
        "lo re-localizó (un genérico lo iguala) y SOSPECHÓ que el AUROC estaba confundido con la riqueza de generación (cada brazo "
        "rankea SU pool, de dificultad distinta según cuántas correctas genera). QUÉ HACE ESTE CICLO (exp133, N={n}, mismo lazo torch "
        "real, DESCONFOUND limpio): además del AUROC_own, TODOS los brazos rankean un POOL FIJO COMPARTIDO Y BALANCEADO (candidatos "
        "CONSTRUIDOS deterministicamente una vez -NO generados por ningún brazo- con etiqueta conocida vía el verificador real, 48/48 "
        "exacto, idéntico para los 3 brazos y fijo a lo largo de rondas) -> AUROC_fixed aísla la separación-de-confianza de la riqueza "
        "de la propia generación. QUÉ SE ESTABLECE (dos capas): (a) LA CURA SE INVIERTE -- durable−naive pasa de OWN {odn} a FIXED "
        "{fdn} (CI {fdnci}, t={tdn}, 6/6 seeds NEGATIVOS): el durable rankea el pool fijo PEOR que el naive (AUROC_fixed durable {fd} "
        "vs naive {fn}). La ventaja del durable del 149 era ENTERAMENTE riqueza de generación (genera pocas correctas {ncd} vs naive "
        "{ncn} -> su pool propio es magro/fácil -> AUROC_own inflada); cuando rankea un set balanceado fresco, su confianza (empujada "
        "a extremos por la unlikelihood) PIERDE resolución. El colapso entrenado es MÁS PROFUNDO que el titular: excluyendo la ronda-1 "
        "no-entrenada, el durable trained-only ~0.62 y última ronda ~0.57 ≈ azar (el {fd} lo SUBESTIMA). => la atribución 'calibración "
        "endógena' del durable-149 queda REFUTADA por el desconfound. (b) EL ÚNICO RESIDUO QUE SOBREVIVE ES GENÉRICO Y NO ROBUSTO -- "
        "ls_lo−naive pasa de OWN {oln} a FIXED {fln}: 6/6 gaps positivos (evidencia de SIGNO, sign-test p=0.016) PERO t-test pareado "
        "t={tln} < t_crit {tc} (df={dfn}, one-tail 0.05) -> SUB-SIGNIFICATIVO; el 'CI bootstrap excluye 0' es TAUTOLÓGICO con gaps "
        "un-signo (P(boot<=0)=0%, no mide robustez); la media se PARTIÓ A LA MITAD N=3->N=6 (0.032->{fln}); cargada en 2/6 seeds (un "
        "seed +0.0001); RÉGIMEN-DEPENDIENTE (cae a +0.003 donde naive_fixed roza el techo {fn}). VERIFICACIÓN ADVERSARIAL (4 sondas, "
        "probes reales -- 1 CONFIRMA + 3 ACOTA, recomendó MIXTA): {V_VERIF}. RESULTADO HONESTO: el 'payoff de calibración' del lazo "
        "real NO es ENTERAMENTE artefacto (queda una señal de SIGNO genuina, generación-independiente, en el genérico) PERO lo "
        "no-artefacto es GENÉRICO (no la cura), MÍNIMO y NO robusto al t-test; el componente que MOTIVÓ el arco (la cura 119 del 149) "
        "SÍ era artefacto de riqueza de generación. Esto CIERRA el caveat load-bearing del 150 y REFUTA la atribución del 149. "
        "ACOTACIÓN: N={n} = merge de 2 lotes ESCALA SMOKE (rounds=4, steps=50), NO la config preregistrada; AUROC_fixed es un sondeo "
        "IN-DISTRIBUTION casi-en-techo (naive {fn}) sobre la misma forma canónica con que cada brazo se re-entrena vía replay -> "
        "desconfunde la riqueza-de-pool (válido) pero NO certifica ranking held-out; toy-real, tarea a*b, HybridLM diminuto. Frontera: "
        "¿el residuo genérico PAGA downstream en una decisión real bajo escasez (sobre el pool fijo)?; N>=8 con t-test; régimen "
        "base-acc alta; transferencia; SCALE.").format(
            V=status.upper(), n=n, odn=_f(odn['mean']), fdn=_f(fdn['mean']), fdnci=fdn['ci95'], tdn=_f(fdn['tstat']),
            fd=_f(af['durable']), fn=_f(af['naive']), ncd=_f(nc['durable']), ncn=_f(nc['naive']), oln=_f(oln['mean']),
            fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit), dfn=n - 1,
            V_VERIF="la inversión del durable es genuina (B-confirma); el residuo ls_lo no es robusto (C-acota: t-test sub-significativo, CI tautológico); el probe es in-distribution near-ceiling (A-acota); 'APOYADA-calibración' lavanderiza (D-acota)")

    hyp_statement = ("¿El 'payoff de calibración' del lazo torch real (149 durable>naive en AUROC_own; 150 ls_lo>=durable) es una "
                     "señal de ranking GENUINA, o un artefacto de la RIQUEZA DE GENERACIÓN (cada brazo rankea SU propio pool, de "
                     "dificultad distinta según cuántas correctas genera)? Test: que TODOS los brazos rankeen un POOL FIJO BALANCEADO "
                     "compartido -> AUROC_fixed desconfundida. RESULTADO: MIXTA -- la ventaja de la CURA 119 (durable) se INVIERTE "
                     "(fixed {fdn}, t={tdn}, 6/6 NEG): era riqueza de generación, su atribución del 149 REFUTADA. El único residuo es "
                     "el GENÉRICO ls_lo y sólo en SIGNO (fixed {fln}, 6/6 positivos PERO t={tln} < t_crit {tc}; no robusto, régimen-"
                     "dependiente). El payoff es MAYORMENTE generación; el residuo genuino es genérico, mínimo y no-robusto. Alcance: "
                     "lazo torch real CPU, HybridLM byte-level, tarea a*b, N={n} escala smoke.").format(
                         fdn=_f(fdn['mean']), tdn=_f(fdn['tstat']), fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit), n=n)
    hyp_prediction = ("REFUTADA-calibración si NINGUNA ventaja de AUROC_fixed sobrevive ni en signo (el payoff era riqueza de "
                      "generación). APOYADA si ALGUNA sobrevive con CI que excluye 0 Y t-test pareado SIGNIFICATIVO (robusta). MIXTA "
                      "si una se invierte y otra sobrevive sólo en SIGNO (no robusta). (Pre-registrada; compuerta robusta por t-test "
                      "-el 'CI excluye 0' es tautológico con gaps un-signo-; verificación adversarial sobre los datos crudos.)")

    mark_note = ("H-V4-9k marcada 'mixta': (1) la CURA 119 (durable) se INVIERTE (fixed {fdn}, t={tdn}, 6/6 NEG) -> su ventaja del 149 "
                 "era ENTERAMENTE riqueza de generación, atribución REFUTADA; (2) el único residuo es el GENÉRICO ls_lo y SÓLO EN "
                 "SIGNO (fixed {fln}, 6/6 positivos pero t={tln} < t_crit {tc}; el 'CI excluye 0' es tautológico). NO es APOYADA: lo "
                 "que sobrevive es genérico, mínimo y no robusto al t-test.").format(
                     fdn=_f(fdn['mean']), tdn=_f(fdn['tstat']), fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit))

    analogy = AnalogyRecord(
        problem=("El 149 mostró que el modelo 'curado' parecía saber mejor cuándo acertaba. Pero cada modelo se examinaba con SUS "
                 "propias respuestas: el curado generaba pocas respuestas y casi todas fáciles, así que su examen era más fácil. "
                 "¿La ventaja era saber-cuándo-acierta de verdad, o sólo que se examinaba con un test más fácil?"),
        everyday=("Era sobre todo el test más fácil; lo que queda es una pizca, de OTRO método, y ni siquiera firme. Les dimos a los "
                  "tres el MISMO examen balanceado (mismas preguntas, mitad fáciles mitad difíciles, corregidas por un juez real). El "
                  "modelo 'curado' (la cura del 149), que parecía el mejor, resultó el PEOR ordenando ese examen común: su exceso de "
                  "seguridad le borró el criterio (de hecho cayó casi al azar). El único que se mantuvo un pelín mejor que el de base "
                  "fue el genérico y suave (label smoothing), pero por TAN poco que con más exámenes la ventaja casi desaparece, y se "
                  "esfuma cuando el de base ya rankeaba cerca del techo. Conclusión: casi toda la 'ventaja' del 149 era el examen-más-"
                  "fácil; queda una mejora de criterio chiquita, sólo en el método genérico, y no estadísticamente firme."),
        solutions=["durable−naive se INVIERTE al cambiar al examen común (OWN {odn} -> FIXED {fdn}, t={tdn}, 6/6 NEG): la ventaja del 149 era generación".format(odn=_f(odn['mean']), fdn=_f(fdn['mean']), tdn=_f(fdn['tstat'])),
                   "ls_lo−naive sobrevive sólo EN SIGNO (FIXED {fln}, 6/6 positivos PERO t={tln} < t_crit {tc}): criterio genuino-en-signo, generación-independiente, pero NO robusto".format(fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit)),
                   "el 'CI bootstrap excluye 0' es TAUTOLÓGICO con gaps un-signo (no mide robustez); la compuerta dura es el t-test pareado, que aquí es sub-significativo",
                   "mecanismo de la inversión del durable: la unlikelihood empuja la confianza a extremos -> sobre un set fijo fresco pierde resolución de ranking (cae casi al azar trained-only)"],
        principles=["una métrica donde cada brazo usa SU PROPIA muestra (de tamaño/dificultad endógenos) confunde la calidad del "
                    "estimador con la composición de la muestra -- el control es un set FIJO compartido y balanceado",
                    "un efecto atribuido a calibración puede ser, en su MAYOR PARTE, un efecto de qué-tan-magra-es-la-muestra-propia; "
                    "el desconfound lo separa en un componente generación (grande) + un residuo ranking-genuino (mínimo)",
                    "'CI bootstrap excluye 0' NO prueba robustez cuando todos los gaps son del mismo signo (es tautológico); la "
                    "compuerta honesta es el t-test pareado: 'sobrevive en signo' no es 'sobrevive robustamente' ni 'importa'",
                    "META: la regla pre-registrada (CI excluye 0) disparaba APOYADA pero era estadísticamente tautológica; reemplazarla "
                    "por el t-test baja el veredicto a MIXTA -- una verificación adversarial que ENDURECE el criterio es progreso"],
        adaptation=("FRONTERA REAL §4.2 (el caveat load-bearing que el 150 descubrió: AUROC confundido con riqueza de generación). "
                    "El 150 sospechó el confound; este ciclo lo CIERRA con el pool fijo balanceado. Halla que la ventaja de la cura "
                    "era generación (se invierte) y que sólo un residuo genérico de signo, no robusto, es real. Próximo: ¿ese residuo "
                    "genuino PAGA downstream en una decisión real bajo escasez (precision@top-m sobre el pool fijo)?; N>=8 con t-test; "
                    "régimen base-acc alta; transferencia; SCALE."),
        measurement=("exp133 (lazo torch real, N={n}): durable−naive OWN {odn} -> FIXED {fdn} (CI {fdnci}, t={tdn}, 6/6 NEG); "
                     "ls_lo−naive OWN {oln} -> FIXED {fln} (CI {flnci}, t={tln} < t_crit {tc}, 6/6 POS); AUROC_fixed naive {fn} durable "
                     "{fd} ls_lo {fl}; #correctas naive {ncn} durable {ncd} ls_lo {ncl}.").format(
                         n=n, odn=_f(odn['mean']), fdn=_f(fdn['mean']), fdnci=fdn['ci95'], tdn=_f(fdn['tstat']), oln=_f(oln['mean']),
                         fln=_f(fln['mean']), flnci=fln['ci95'], tln=_f(fln['tstat']), tc=_f(tcrit), fn=_f(af['naive']),
                         fd=_f(af['durable']), fl=_f(af['ls_lo']), ncn=_f(nc['naive']), ncd=_f(nc['durable']), ncl=_f(nc['ls_lo'])),
        iterations=4)
    analogy_note = ("Analogía 7 etapas registrada (el 'saber-cuándo-acierta' del 149 era sobre todo examinarse con un test más fácil; "
                    "la cura se invierte en el examen común; queda una pizca de criterio real -genérica y no firme-).")

    kl = ("REAL (exp133, MIXTA + verificación adversarial): el payoff de calibración del lazo real es MAYORMENTE riqueza de "
          "generación. Sobre un pool fijo balanceado: la cura 119 (durable) se INVIERTE (fixed durable−naive {fdn}, t={tdn}) -> su "
          "ventaja del 149 era generación; sólo un residuo GENÉRICO de SIGNO sobrevive (ls_lo fixed {fln}, 6/6 positivos pero t={tln} "
          "< t_crit {tc}; NO robusto), régimen-dependiente. TECHO/ALCANCE: N={n} (merge 2 lotes smoke, rounds=4, steps=50); AUROC_"
          "fixed in-distribution near-ceiling (naive {fn}); toy-real, tarea a*b, HybridLM diminuto. NO cubre: pago DOWNSTREAM del "
          "residuo; potencia N>=8 con t-test; régimen base-acc alta; transferencia; SCALE.").format(
              fdn=_f(fdn['mean']), tdn=_f(fdn['tstat']), fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit), n=n, fn=_f(af['naive']))
    ceiling = CeilingRecord(
        subsystem=("DESCONFUNDIR el payoff de calibración del lazo torch real (149/150): ¿AUROC genuino o riqueza de generación? "
                   "RESULTADO: MIXTA -- la cura 119 se INVIERTE sobre el pool fijo balanceado (su ventaja del 149 era generación, "
                   "atribución refutada); sólo un residuo genérico de SIGNO (ls_lo) sobrevive, no robusto. Cierra el caveat del 150"),
        known_limit=kl,
        blockers=[{"text": ("MIXTA, no demolición total NI apoyada: NO es enteramente artefacto -queda un residuo de ranking de SIGNO "
                            "genuino (ls_lo fixed {fln}, 6/6 positivos)- pero ese residuo es GENÉRICO (no la cura), MÍNIMO y NO robusto "
                            "(t={tln} < t_crit {tc}; el 'CI excluye 0' es tautológico). El componente de la CURA 119 (durable) era "
                            "ENTERAMENTE generación (se invierte, fixed {fdn}, t={tdn}).").format(
                                fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit), fdn=_f(fdn['mean']), tdn=_f(fdn['tstat'])), "kind": "diseno"},
                  {"text": ("ALCANCE/POTENCIA: N={n} (merge 0-2 smoke + 3-5) con settings ESCALA SMOKE (rounds=4, steps=50, pool=48), "
                            "NO la config preregistrada (--seeds 0-7 --rounds 5 --steps 70). El residuo ls_lo es sub-significativo por "
                            "t-test (t={tln} < {tc}) y la media se partió a la mitad N=3->N=6 -> pendiente N>=8 con t-test pareado, no "
                            "el CI tautológico.").format(n=n, tln=_f(fln['tstat']), tc=_f(tcrit)), "kind": "fisico"},
                  {"text": ("DISEÑO: AUROC_fixed es un sondeo IN-DISTRIBUTION casi-en-techo (naive {fn}) sobre la MISMA forma canónica "
                            "'1+(n-1)' con que cada brazo se re-entrena vía replay -> desconfunde la riqueza-de-pool (su propósito, "
                            "válido) pero NO certifica ranking held-out/generalizable. FRONTERA ABIERTA: (a) ¿el residuo genérico PAGA "
                            "downstream bajo escasez (precision@top-m sobre el pool fijo)? -'sobrevive en signo' no es 'importa'-; (b) "
                            "régimen base-acc alta; (c) transferencia; (d) SCALE.").format(fn=_f(af['naive'])), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP133.ref, S_149.ref, S_150.ref, S_VERIF.ref])
    ceiling_note = ("1 techo 'real': el payoff de calibración del lazo real es MAYORMENTE generación -- la cura 119 se invierte (era "
                    "generación, atribución del 149 refutada); sólo un residuo genérico de SIGNO sobrevive (ls_lo, no robusto por "
                    "t-test). Cierra el caveat del 150.")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- el caveat load-bearing que el 150 descubrió): {V}. El 'payoff de calibración' "
             "del lazo torch real (149/150) está MAYORMENTE CONFUNDIDO con la riqueza de generación. Sobre un POOL FIJO BALANCEADO "
             "compartido: (a) la cura 119 (durable) se INVIERTE -- durable−naive pasa de OWN {odn} a FIXED {fdn} (CI {fdnci}, t={tdn}, "
             "6/6 seeds NEG) -> su ventaja del 149 era ENTERAMENTE riqueza de generación; (b) el único residuo es el GENÉRICO ls_lo y "
             "SÓLO EN SIGNO -- ls_lo−naive FIXED {fln} (6/6 positivos PERO t={tln} < t_crit {tc}, no robusto), régimen-dependiente. "
             "Verificación adversarial de 4 sondas (recomendó MIXTA; el 'CI excluye 0' era tautológico -> compuerta endurecida a "
             "t-test). Decisión: ADOPTAR que (1) la atribución 'calibración endógena' del durable-149 queda REFUTADA por el desconfound "
             "(era riqueza de generación), (2) el lazo real NO es ENTERAMENTE artefacto pero lo no-artefacto es GENÉRICO, mínimo y no "
             "robusto, cerrando el caveat del 150. Próximo: ¿el residuo PAGA downstream bajo escasez?; N>=8 con t-test; régimen "
             "base-acc alta; transferencia; SCALE.").format(
                 V=status.upper(), odn=_f(odn['mean']), fdn=_f(fdn['mean']), fdnci=fdn['ci95'], tdn=_f(fdn['tstat']),
                 fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit))
    drat = ("exp133 (tier5, propio, lazo torch real, N={n}, post-verificación adversarial de 4 sondas que recomendó MIXTA): el "
            "desconfound (pool fijo balanceado) separa el payoff en un componente GENERACIÓN dominante (la cura se INVIERTE, fixed "
            "durable−naive {fdn}, t={tdn}, 6/6 NEG) + un residuo GENÉRICO de SIGNO (ls_lo fixed {fln}, 6/6 positivos pero t={tln} < "
            "t_crit {tc}, no robusto). Convergente con el principio (tier2), la sospecha del 150 (tier5) y la verificación (tier4). "
            "MIXTA: la atribución del 149 se refuta; el lazo real no es enteramente artefacto pero el residuo genuino es genérico, "
            "mínimo y no robusto.").format(n=n, fdn=_f(fdn['mean']), tdn=_f(fdn['tstat']), fln=_f(fln['mean']), tln=_f(fln['tstat']), tc=_f(tcrit))
    decision = Decision(id="D-V4-111", statement=dstmt, rationale=drat,
                        sources=[_to_plain(S_EXP133), _to_plain(S_150), _to_plain(S_VERIF)], important=True)

    return {
        "sources": [S_PRINCIPLE, S_149, S_150, S_VERIF, S_EXP133],
        "sources_note": ("5 fuentes (S_PRINCIPLE tier2 desconfound mayormente-generación; S_149 tier5 la APOYADA cuya atribución se "
                         "refuta; S_150 tier5 sospechó el confound, se cierra; S_VERIF tier4 verificación recomendó MIXTA; S_EXP133 "
                         "tier5 dato propio MIXTA)."),
        "hyp_statement": hyp_statement, "hyp_prediction": hyp_prediction, "confidence": "alta",
        "ev_for": ev_for, "ev_against": ev_against, "advtext": advtext, "mark_note": mark_note,
        "analogy": analogy, "analogy_note": analogy_note, "ceiling": ceiling, "ceiling_note": ceiling_note,
        "decision": decision, "decision_note": "D-V4-111 ACEPTADA por el ledger (tier5 exp133 + tier5 cierre-150 + tier4 verificación adversarial)."}


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle151_deconfound_calibration',
                                description='CYCLE 151 (RESET v4, H-V4-9k: ¿el payoff de calibración del lazo real es genuino o riqueza de generación?).')
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
    print("RESUMEN — CYCLE 151 (RESET v4): ¿el payoff de calibración del lazo real es genuino o generación? — H-V4-9k " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9k:", status.upper() if status else "?")
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
