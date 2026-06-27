r"""
cycle144_variance_prior.py — CICLO 144 (RESET v4, rama control/acción, CARACTERIZA el hallazgo NETO de 138: la corrección por
VARIANZA-PRIOR v): H-V4-10p por las compuertas del engine.

VEREDICTO: MIXTA (mi hipótesis -w·v·ctrl la elección robusta que bate a AMBOS- REFUTADA; mapa de régimen honesto tras verificación
adversarial de 2 agentes; 14mo ciclo). El experimento AUTO-DOCUMENTA.

QUÉ HAY: la varianza-prior v MODULA el valor bajo heterogeneidad (params clean, monótono). PERO la verificación re-acotó TODO:
  (1) 'incluir v bate al keystone' es en gran medida DEFINICIONAL (el oracle=w²·v·ctrl CONTIENE v; sacarlo invierte el signo); lo
      genuino es la estimabilidad de v̂=Var(x), CONTAMINADA por el control (corr con b²); bajo BAJA heterogeneidad el v̂ ruidoso DAÑA.
  (2) el claim de 138 ('el cuadrado w² DAÑA bajo estimación') NO se refuta -- se CONFIRMA regime-específicamente (con ŵ RUIDOSO el
      cuadrado daña); mi 1ra versión muestreó el rincón limpio y lo llamó 'wash' por error.
  (3) a BAJA heterogeneidad el cuadrado AYUDA -> el cuadrado es REGIME-DEPENDENT (ayuda baja-het, wash alta-het+limpio, daña ŵ-ruidoso).
  (4) la elección robusta a través del eje es la EFE-COMPLETA w²·v·ctrl, NO la simplificada w·v·ctrl que yo proponía.

=> RESULTADO HONESTO: la varianza-prior v importa bajo heterogeneidad (pero 'incluir v' es casi definicional + v̂ contaminado); la
forma robusta es la EFE-completa w²·v·ctrl; el cuadrado es regime-dependent (138 CONFIRMADO, no refutado). MIXTA EXITOSA: la
verificación cazó mi overclaim BIDIRECCIONAL y protegió la AUTOCONSISTENCIA con 138 (que yo contradecía erróneamente).

DERIVA de exp128_variance_prior/results/results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle144_variance_prior')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp128_variance_prior', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la varianza-prior v MODULA el valor de un modo (la forma EFE-óptima es w²·v·ctrl), pero (a) 'incluir v' beneficiar sobre el keystone w·ctrl es DEFINICIONAL -- el oracle contiene v; lo genuino es que v̂=Var(x) es estimable PERO contaminado por el control (b²), y bajo baja heterogeneidad el v̂ ruidoso DAÑA; (b) la cuestión w vs w² es REGIME-DEPENDENT -- el cuadrado AYUDA a baja heterogeneidad, es un WASH a alta heterogeneidad + estimación limpia, y DAÑA con ŵ ruidoso (confirma 138); la forma robusta a través del eje es la EFE-completa w²·v·ctrl, no la simplificada w·v·ctrl.", obtained=False,
                     claim=("La varianza-prior v modula el valor (forma robusta = EFE-completa w²·v·ctrl); 'incluir v' sobre el "
                            "keystone es casi definicional + v̂ contaminado; el cuadrado es regime-dependent (ayuda baja-het, daña "
                            "ŵ-ruidoso). (Principio; mapa de régimen.)"))
S_C138 = Source(tier=5, ref="cognia_x/experiments/exp122_active_inference (CYCLE 138, hallazgo neto: la corrección robusta es v, el cuadrado daña bajo estimación)", obtained=True,
                claim=("CYCLE 138 (exp122, MIXTA): la corrección empírica robusta sobre el keystone es la varianza-prior v (w·v·ctrl), "
                       "y el cuadrado de la forma EFE-óptima (w²·v·ctrl) DAÑA bajo params estimados (amplifica el ruido de ŵ). "
                       "H-V4-10p caracteriza esto: el daño del cuadrado es REGIME-DEPENDENT (138 confirmado en el régimen ruidoso), "
                       "no universal; y 'incluir v' es casi definicional."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 2 agentes (lentes tautología-definicional / robustez-régimen; probes reales numpy, incluido el sustrato de 138)", obtained=True,
                 claim=("La verificación adversarial (14mo ciclo) CAZÓ mi overclaim BIDIRECCIONAL: (1) 'incluir v bate al keystone' "
                        "es DEFINICIONAL (sacar v del oracle invierte el signo); v̂=Var(x) está contaminado por el control (corr con "
                        "b²~0.2-0.6) y DAÑA a baja heterogeneidad. (2) mi 'refutación de 138' (el cuadrado es un wash) era falsa -- "
                        "muestreé el rincón limpio; con ŵ ruidoso el cuadrado DAÑA (138 confirmado), y a baja heterogeneidad AYUDA "
                        "-> regime-dependent; la forma robusta es la EFE-completa w²·v·ctrl. Protegió la autoconsistencia con 138."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp128 primero): " + results_path)

    vps = sm['v_pays_strong_clean']; shn = sm['square_harms_noisy_sgmax']; shl = sm['square_helps_lowhet']
    cvt = sm['corr_vhat_vtrue']; cvb = sm['corr_vhat_b2']; vlp = sm['vhat_lowhet_penalty']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim128 = ("exp128 (propio, {n} seeds, numpy, post-verificación de 2 agentes): {V}. La varianza-prior v modula el valor "
                "(clean v_corr-keystone +{vps} strong, monótono) PERO 'incluir v' es casi DEFINICIONAL (el oracle contiene v) + v̂ "
                "CONTAMINADO (corr v_true {cvt}, corr b² {cvb}; daña a baja-het, penalty {vlp}); el cuadrado es REGIME-DEPENDENT "
                "(daña con ŵ ruidoso +{shn} -138 CONFIRMADO-, ayuda a baja-het +{shl}); la forma robusta es la EFE-completa "
                "w²·v·ctrl, no la w·v·ctrl que yo proponía.").format(
                    n=n_seeds, V=status.upper(), vps=_f(vps), cvt=_f(cvt), cvb=_f(cvb), vlp=_f(vlp), shn=_f(shn), shl=_f(shl))
    S_EXP128 = Source(tier=5, ref="cognia_x/experiments/exp128_variance_prior", obtained=True, claim=claim128)
    for src in (S_PRINCIPLE, S_C138, S_VERIF, S_EXP128):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 v modula el valor; incluir-v definicional + v̂ contaminado; cuadrado regime-dependent; S_C138 tier5 hallazgo neto de 138; S_VERIF tier4 verificación adversarial -overclaim bidireccional cazado-; S_EXP128 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP128.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP128.ref, S_VERIF.ref]
    advtext = ("{V} (CARACTERIZA el hallazgo neto de 138 -la corrección por varianza-prior v-; mapa de régimen honesto tras "
               "verificación adversarial de 2 agentes, 14mo ciclo): mi HIPÓTESIS era que w·v·ctrl (relevancia × varianza-prior × "
               "controlabilidad) es la elección PRÁCTICA robusta -- el punto dulce que BATE al keystone w·ctrl Y a la forma "
               "EFE-óptima w²·v·ctrl. RESULTADO: HIPÓTESIS REFUTADA + mapa de régimen. La varianza-prior v MODULA el valor bajo "
               "heterogeneidad (params clean: v_corr-keystone +{vps} a varianza strong, monótono). PERO la verificación re-acotó "
               "BIDIRECCIONALMENTE: (1) 'incluir v bate al keystone' es en gran medida DEFINICIONAL -- el oracle (w²·v·ctrl) "
               "CONTIENE v; sacar v del oracle INVIERTE el signo de la 'ventaja' (factor-matching algebraico). Lo genuino es la "
               "estimabilidad de v̂=Var(x) (corr con v_true {cvt} bajo heterogeneidad fuerte) PERO está CONTAMINADO por el control "
               "(corr con b² {cvb}: Var(x) conflaciona la varianza-prior con la varianza inducida por u), y bajo BAJA "
               "heterogeneidad el v̂ ruidoso DAÑA (keystone > v_corr, penalty {vlp}). (2) mi 'refutación de 138' (que el cuadrado es "
               "un WASH) era FALSA/deshonesta -- muestreé el rincón LIMPIO (σ_g=0.5, T≥25); con ŵ RUIDOSO (σ_g alto, T chico) el "
               "cuadrado DAÑA (v_corr-efe +{shn}) -> 138 CONFIRMADO regime-específicamente, NO refutado. (3) PERO a BAJA "
               "heterogeneidad el cuadrado AYUDA (efe bate a v_corr +{shl}) -> el cuadrado NO es 'siempre daña' (138) NI 'wash' "
               "(mi error): es REGIME-DEPENDENT. (4) la elección REALMENTE robusta a través del eje es la forma EFE-COMPLETA "
               "w²·v·ctrl (efe), que DOMINA débilmente todo; w·v·ctrl es una simplificación justificada SÓLO bajo heterogeneidad "
               "fuerte + estimación limpia. => RESULTADO HONESTO: mi hipótesis (w·v·ctrl bate a ambos) está REFUTADA; la forma "
               "robusta es la EFE-completa w²·v·ctrl; 'incluir v' es casi definicional con un v̂ contaminado; y el daño del cuadrado "
               "de 138 está CONFIRMADO (regime-específico). MIXTA EXITOSA: la verificación cazó mi overclaim BIDIRECCIONAL "
               "(definicional + refutación-deshonesta de un ciclo previo) y PROTEGIÓ LA AUTOCONSISTENCIA del ledger con 138 -- que "
               "yo contradecía erróneamente. Frontera: la varianza-prior como saliencia/atención en un sustrato real; SCALE.").format(
                   V=status.upper(), vps=_f(vps), cvt=_f(cvt), cvb=_f(cvb), vlp=_f(vlp), shn=_f(shn), shl=_f(shl))

    hyp = Hypothesis(
        id="H-V4-10p",
        statement=("¿Es w·v·ctrl (relevancia × varianza-prior × controlabilidad) la elección PRÁCTICA robusta para un agente bajo "
                   "estimación, que bate al keystone w·ctrl (incluye v) Y a la forma EFE-óptima w²·v·ctrl (el cuadrado amplifica el "
                   "ruido de ŵ)? RESULTADO: REFUTADA -- la forma robusta a través del eje es la EFE-completa w²·v·ctrl; 'incluir v' "
                   "es casi definicional + v̂ contaminado; el cuadrado es regime-dependent (ayuda baja-het, daña ŵ-ruidoso -138-). "
                   "v modula el valor bajo heterogeneidad. Alcance: numpy, lineal."),
        prediction=("APOYADA si w·v·ctrl bate a AMBOS (keystone y efe) robustamente. REFUTADA si NO (la EFE-completa domina, o "
                    "incluir v es definicional, o el cuadrado no es un wash). MIXTA si v modula pero el mapa de régimen es "
                    "complejo. (Pre-registrada; verificación adversarial de 2 agentes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp128_variance_prior")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10p")
        notes.append("H-V4-10p marcada '{}': mi hipótesis (w·v·ctrl bate a ambos) REFUTADA; la forma robusta es la EFE-completa w²·v·ctrl; 'incluir v' es casi definicional + v̂ contaminado por control; el cuadrado es regime-dependent (138 CONFIRMADO, no refutado). La verificación cazó mi overclaim bidireccional y protegió la autoconsistencia con 138.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenías una receta sofisticada para decidir qué vale la pena tocar (importancia × cuánto-varía × cuánto-podés-mover) "
                 "y querías mostrar que una versión SIMPLIFICADA de ella es la mejor en la práctica. ¿Lo es?"),
        everyday=("No -- y la honestidad es el resultado. Primero: 'agregar cuánto-varía mejora' suena a hallazgo pero es casi "
                  "trampa, porque la respuesta CORRECTA ya incluye cuánto-varía; sacarlo de la respuesta correcta invierte el "
                  "resultado. Y medir 'cuánto-varía' de los datos sale sucio (se mezcla con cuánto-lo-moviste), así que a veces "
                  "EMPEORA. Segundo: yo había dicho que 'elevar la importancia al cuadrado no cambia nada' -- pero eso sólo pasa en "
                  "un rincón cómodo; cuando tus datos son ruidosos, el cuadrado SÍ hace daño (justo lo que un ciclo anterior ya "
                  "había dicho, y yo lo estaba contradiciendo sin querer), y cuando todo varía parecido, el cuadrado hasta AYUDA. "
                  "Moraleja: la receta COMPLETA es la robusta; la simplificada sólo sirve en un rincón; y antes de 'refutar' un "
                  "resultado previo hay que revisar que no estés mirando sólo el rincón que te conviene."),
        solutions=["la forma robusta a través de los regímenes es la EFE-completa w²·v·ctrl, no la simplificada w·v·ctrl",
                   "'incluir la varianza-prior v' sobre el keystone es casi DEFINICIONAL (el oracle contiene v); el v̂=Var(x) estimado está contaminado por el control y daña a baja heterogeneidad",
                   "el cuadrado es REGIME-DEPENDENT: ayuda a baja heterogeneidad, es un wash a alta-het+limpio, y DAÑA con ŵ ruidoso (138 confirmado)",
                   "antes de REFUTAR un ciclo previo (138), barrer el régimen completo -- yo muestreé el rincón limpio y lo 'refuté' por error"],
        principles=["la forma robusta del valor a través de regímenes es la EFE-completa w²·v·ctrl; las simplificaciones sólo valen en rincones",
                    "una ventaja que se INVIERTE al sacar el factor del oracle es DEFINICIONAL, no un hallazgo (factor-matching algebraico)",
                    "un estimador 'endógeno' (v̂=Var(x)) puede estar CONTAMINADO por otra causa (el control) -> medir la contaminación (corr) antes de declararlo load-bearing",
                    "META: 14mo ciclo seguido con verificación adversarial -- aquí cazó un overclaim BIDIRECCIONAL (definicional + refutación-deshonesta de un ciclo previo) y protegió la autoconsistencia del ledger con 138"],
        adaptation=("Este ciclo intentaba caracterizar el hallazgo neto de 138 (la corrección por varianza-prior v) y mostrar que la "
                    "forma simplificada w·v·ctrl es la práctica robusta. RESULTADO MIXTO honesto que me CORRIGE: (1) 'incluir v' es "
                    "casi definicional (el oracle contiene v) y el v̂ estimado está contaminado por el control (daña a baja "
                    "heterogeneidad); (2) mi 'refutación' del claim de 138 (que el cuadrado es un wash) era falsa -- con ŵ ruidoso "
                    "el cuadrado DAÑA (138 confirmado), y a baja heterogeneidad AYUDA -> regime-dependent; (3) la forma robusta a "
                    "través del eje es la EFE-completa w²·v·ctrl, NO la simplificada. APORTE: el mapa de régimen honesto + la "
                    "vindicación de 138 (su mecanismo es correcto, regime-específico). META-LECCIÓN: 14mo ciclo seguido con "
                    "verificación adversarial -- aquí protegió la AUTOCONSISTENCIA del ledger (cazó que yo refutaba erróneamente un "
                    "ciclo previo). Próximo: la varianza-prior como saliencia/atención en un sustrato no-juguete; SCALE."),
        measurement=("exp128 ({n} seeds): v modula (clean v_corr-keystone +{vps} strong, monótono); 'incluir v' definicional "
                     "(invierte al sacar v del oracle); v̂ contaminado (corr v_true {cvt}, corr b² {cvb}, penalty baja-het {vlp}); el "
                     "cuadrado regime-dependent (daña ŵ-ruidoso +{shn}, ayuda baja-het +{shl}); efe-completa domina.").format(
                         n=n_seeds, vps=_f(vps), cvt=_f(cvt), cvb=_f(cvb), vlp=_f(vlp), shn=_f(shn), shl=_f(shl)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la receta completa es la robusta; 'agregar cuánto-varía' es casi trampa -el oracle ya lo contiene-; antes de refutar un ciclo previo, revisar que no mires sólo el rincón cómodo).")

    kl = ("REAL (exp128, {V} post-verificación adversarial de 2 agentes): la varianza-prior v modula el valor bajo heterogeneidad, "
          "PERO la forma robusta a través de los regímenes es la EFE-completa w²·v·ctrl (no la simplificada w·v·ctrl que la hipótesis "
          "proponía). 'incluir v' sobre el keystone es casi DEFINICIONAL (el oracle contiene v); v̂=Var(x) es estimable (corr v_true "
          "{cvt}) pero CONTAMINADO por el control (corr b² {cvb}) y DAÑA a baja heterogeneidad. El cuadrado es REGIME-DEPENDENT: daña "
          "con ŵ ruidoso (+{shn}, 138 CONFIRMADO), ayuda a baja-het (+{shl}). TECHO/ALCANCE: numpy/toy, sustrato lineal de 138, "
          "oracle=w²·v·ctrl por construcción. Frontera: la varianza-prior como saliencia en un sustrato real; SCALE.").format(
              V=status.upper(), cvt=_f(cvt), cvb=_f(cvb), shn=_f(shn), shl=_f(shl))
    ceilings.add(CeilingRecord(
        subsystem="CORRECCIÓN por VARIANZA-PRIOR v del keystone R-VALOR (caracteriza el hallazgo neto de 138) — la varianza-prior v modula el valor bajo heterogeneidad, PERO la forma robusta a través de los regímenes es la EFE-COMPLETA w²·v·ctrl, no la simplificada w·v·ctrl. 'incluir v' es casi definicional (el oracle contiene v); v̂=Var(x) está contaminado por el control y daña a baja heterogeneidad; el cuadrado es REGIME-DEPENDENT (daña con ŵ ruidoso -138 confirmado-, ayuda a baja-het). Mi hipótesis (w·v·ctrl bate a ambos) REFUTADA. Alcance: numpy, lineal",
        known_limit=kl,
        blockers=[{"text": "DEFINICIONAL + ESTIMADOR CONTAMINADO: (a) 'incluir v bate al keystone' es factor-matching algebraico -- el oracle (w²·v·ctrl) CONTIENE v; sacar v del oracle INVIERTE el signo de la 'ventaja'. (b) lo genuino es que v̂=Var(x) es estimable (corr con v_true {cvt} bajo heterogeneidad fuerte) PERO CONTAMINADO por el control: Var(x)≈(b²+v)/(1-a²) conflaciona la varianza-prior con la varianza inducida por u (corr con b² {cvb}); bajo BAJA heterogeneidad el v̂ ruidoso DAÑA (penalty {vlp})".format(cvt=_f(cvt), cvb=_f(cvb), vlp=_f(vlp)), "kind": "diseno"},
        {"text": "CUADRADO REGIME-DEPENDENT + 138 CONFIRMADO (auto-corrección): mi 1ra versión 'refutaba' el claim de 138 (el cuadrado daña bajo estimación) llamándolo 'wash' -- pero MUESTREÉ EL RINCÓN LIMPIO (σ_g=0.5, T≥25). Con ŵ RUIDOSO (σ_g alto, T chico) el cuadrado DAÑA (v_corr-efe +{shn}) -> 138 CONFIRMADO regime-específicamente. A BAJA heterogeneidad el cuadrado AYUDA (efe-v_corr +{shl}). => el cuadrado es REGIME-DEPENDENT (ayuda baja-het, wash alta-het+limpio, daña ŵ-ruidoso); la forma ROBUSTA a través del eje es la EFE-completa w²·v·ctrl, no la simplificada w·v·ctrl. La verificación protegió la AUTOCONSISTENCIA con 138".format(shn=_f(shn), shl=_f(shl)), "kind": "diseno"},
        {"text": "ALCANCE: numpy/toy, sustrato lineal-gaussiano de 138 (modos independientes, costo de control cuadrático); el oracle=w²·v·ctrl (término pragmático de la EFE) por construcción. NO cubre: sustrato acoplado (137)/no-lineal (135-136); la varianza-prior como mecanismo de SALIENCIA/atención en un modelo real; el lazo real; SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP128.ref, S_C138.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la varianza-prior v modula el valor pero la forma robusta es la EFE-completa w²·v·ctrl; 'incluir v' es definicional + v̂ contaminado; el cuadrado es regime-dependent (138 confirmado). Mi hipótesis refutada.")

    dstmt = ("North-Star R-VALOR (CARACTERIZA el hallazgo neto de 138 -corrección por varianza-prior v-): {V}. Mi hipótesis (w·v·ctrl "
             "es la elección robusta que bate al keystone Y a la EFE-óptima) REFUTADA. La varianza-prior v modula el valor bajo "
             "heterogeneidad, pero (1) 'incluir v' es casi DEFINICIONAL (el oracle contiene v) + v̂=Var(x) contaminado por el control "
             "(corr b² {cvb}, daña a baja-het); (2) el cuadrado es REGIME-DEPENDENT (daña con ŵ ruidoso +{shn} -138 CONFIRMADO-, "
             "ayuda a baja-het +{shl}); (3) la forma robusta a través del eje es la EFE-COMPLETA w²·v·ctrl. Decisión: adoptar la "
             "EFE-completa w²·v·ctrl como forma robusta; reconocer que el daño del cuadrado de 138 es regime-específico (confirmado, "
             "no refutado). META-DECISIÓN: 14mo ciclo con verificación adversarial (cazó un overclaim bidireccional + protegió la "
             "autoconsistencia con 138). Próximo: la varianza-prior como saliencia en un sustrato real; SCALE.").format(
                 V=status.upper(), cvb=_f(cvb), shn=_f(shn), shl=_f(shl))
    drat = ("exp128 (tier5, propio, {n} seeds, numpy, post-verificación de 2 agentes): la varianza-prior v modula el valor pero la "
            "forma robusta es la EFE-completa w²·v·ctrl, no la w·v·ctrl que yo proponía (REFUTADA); 'incluir v' es definicional + v̂ "
            "contaminado; el cuadrado es regime-dependent (138 confirmado en el régimen ruidoso, no refutado). Convergente con el "
            "principio (tier2) y la verificación (tier4); caracteriza -y vindica- el hallazgo neto de 138 (tier5). MIXTA: mapa de "
            "régimen honesto que corrige mi overclaim bidireccional.").format(n=n_seeds)
    dec = Decision(id="D-V4-106", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP128), _to_plain(S_C138), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-106 ACEPTADA por el ledger (tier5 exp128 + tier5 exp122/C138 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-106:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle144_variance_prior',
                                description='CYCLE 144 (RESET v4, H-V4-10p MIXTA: mi hipótesis -w·v·ctrl la elección robusta- REFUTADA; la forma robusta es la EFE-completa w²·v·ctrl; incluir v es definicional + v̂ contaminado; el cuadrado es regime-dependent -138 confirmado-; 14mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 144 (RESET v4): la forma robusta es la EFE-completa w²·v·ctrl (mi hipótesis w·v·ctrl REFUTADA; 138 confirmado) — H-V4-10p " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-10p:", status.upper() if status else "?")
    print("  La varianza-prior v modula el valor bajo heterogeneidad, PERO: 'incluir v' es casi definicional (el oracle contiene v) + v̂=Var(x) contaminado por el control (daña a baja-het); el cuadrado es REGIME-DEPENDENT (daña con ŵ ruidoso -138 CONFIRMADO-, ayuda a baja-het); la forma robusta es la EFE-completa w²·v·ctrl, no la w·v·ctrl que la hipótesis proponía (REFUTADA). La verificación cazó mi overclaim bidireccional y protegió la autoconsistencia con 138.")
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
