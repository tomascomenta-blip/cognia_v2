r"""
cycle34_speculative_decode.py — CICLO 34 a través del Investigation Engine (frente NUEVO F-SPEED).

H-SPEED-1: en el sistema ACTUAL (i3 bandwidth-bound, Qwen2.5-Coder-3B Q4_K_M, llama-server b9391),
el speculative decoding sube tok/s de decode SIN re-entrenar la base, pero la ganancia es CONDICIONAL
al tipo de texto: n-gram (0 modelo extra, 0 entrenamiento) acelera texto repetitivo/codigo/RAG; el
HABLA natural general casi no se beneficia del n-gram y exige draft real o cabezas entrenables
(MTP/EAGLE, que el binario YA soporta). Difusion (DiffusionGemma) y speculative son DUALES: ambos
commitean varios tokens por lectura de pesos; en CPU bandwidth-bound (exp004) el drafter debe costar
~0 bytes -> n-gram o heads sobre la base congelada (no un draft model grande separado).

DERIVA el veredicto de exp021_speculative_decode/results/verdict.json. Pasa por las compuertas.

Correr (DESPUES de exp021 bench_real + bench_draft + analyze):
    venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\analyze.py
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle34_speculative_decode
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle34_speculative_decode')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp021_speculative_decode', 'results', 'verdict.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ── fuentes (verificadas en esta sesion; sin citas inventadas) ─────────────
S1 = Source(tier=3, ref="https://blog.google/innovation-and-ai/technology/developers-tools/diffusion-gemma-faster-text-generation/",
            obtained=True,
            claim=("DiffusionGemma (Google, doc oficial): generacion por difusion = bloques de tokens en "
                   "paralelo via denoising iterativo (fija los seguros, refina el resto); 4x mas rapido en GPU. "
                   "26B MoE, solo GPU -> inviable en i3, pero el PRINCIPIO (commit de bloque) es robable."))
S2 = Source(tier=1, ref="arXiv:2211.17192", obtained=True,
            claim=("Leviathan et al. 2023: speculative decoding = un drafter barato propone K tokens y el "
                   "modelo objetivo los VERIFICA en 1 forward batcheado; a temp=0 es lossless (misma "
                   "distribucion). Fundamento del peldano 1."))
S3 = Source(tier=1, ref="arXiv:2503.01840", obtained=True,
            claim=("EAGLE-3 2025: cabezas auto-regresivas livianas sobre el modelo objetivo (auto-especulacion); "
                   "3.0-6.5x en GPU, longitud de aceptacion 4-7.5 (en Qwen mas conservador, AL ~1.7-2.2). Son "
                   "'parametros entrenados modificables' que se bolt-onean sobre la base congelada."))
S_BW = Source(tier=5, ref="cognia_x/experiments/exp004_roofline_cpu", obtained=True,
              claim=("exp004: el decode en CPU es memory-bandwidth-bound (~15-22 GiB/s, satura a 2 hilos). "
                     "=> cada token AR ~= 1 lectura de los ~1.8 GiB de pesos; el techo de ~8 tok/s ES la banda."))


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        v = json.load(f)
    s = v.get('summary')
    if not s or 'status' not in s:
        raise SystemExit("verdict.json sin summary.status (corre analyze.py primero): " + results_path)
    status = s['status']
    base = s.get('baseline_tps')
    bestfree = s.get('best_free_gain') or {}
    bestspeech = s.get('best_speech') or {}

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S5 = Source(tier=5, ref="cognia_x/experiments/exp021_speculative_decode", obtained=True,
                claim=("exp021 (REAL, i3, Qwen3B Q4_K_M, llama-server b9391, temp=0): baseline~{b} tok/s. "
                       "Mejor ganancia GRATIS (ngram, 0 modelo extra): {fs} en '{fp}' = {fx}x (lossless). "
                       "Habla natural: mejor = {ss} {sx}x. {head}").format(
                           b=_fmt(base), fs=bestfree.get('strategy'), fp=bestfree.get('prompt'),
                           fx=bestfree.get('speedup'), ss=bestspeech.get('strategy'),
                           sx=bestspeech.get('speedup'), head=s.get('headline', '')))
    for src in (S1, S2, S3, S_BW, S5):
        ledger.add_source(src)
    notes.append("5 fuentes (S1 tier3 DiffusionGemma; S2 tier1 spec-decode; S3 tier1 EAGLE-3; "
                 "S_BW tier5 exp004; S5 tier5 exp021).")

    if status == 'apoyada':
        ev_for, ev_against = [S2.ref, S5.ref, S_BW.ref], [S1.ref]
        adv = ("APOYADA: speculative sube tok/s lossless en el sistema ACTUAL; n-gram da la ganancia gratis en "
               "repeticion/codigo Y el draft/heads acelera tambien el habla. Caveat: medido a n_predict=160, "
               "temp=0; la magnitud depende del corpus.")
    elif status == 'mixta':
        ev_for, ev_against = [S2.ref, S5.ref, S_BW.ref], [S1.ref]
        adv = ("MIXTA (CONDICIONAL al tipo de texto): n-gram acelera texto repetitivo/codigo/RAG GRATIS y "
               "lossless (ngram-mod es bit-identico al baseline en todos los prompts), pero el HABLA natural "
               "general casi no se beneficia del n-gram (~1.0-1.13x). El caso objetivo (hablar rapido) exige el "
               "peldano 2: draft real local o cabezas entrenables MTP/EAGLE (binario las soporta: draft-mtp/"
               "draft-eagle3). Coherente con exp004: el drafter debe costar ~0 banda; un draft model GRANDE "
               "separado se penaliza. Ataque considerado: 'quiza n-gram basta' -> REFUTADO por la medicion en "
               "habla (0.87-1.06x).")
    else:
        ev_for, ev_against = [S1.ref], [S5.ref, S2.ref]
        adv = ("REFUTADA en esta medicion: ningun metodo dio >1.15x lossless util en los prompts probados. "
               "Posible null de metodo (params de ngram, n_predict, corpus); reintentar con draft/heads.")

    hyp = Hypothesis(
        id="H-SPEED-1",
        statement=("En el sistema actual (i3 bandwidth-bound, Qwen3B Q4_K_M, llama-server), speculative decoding "
                   "sube tok/s de decode sin re-entrenar la base; la ganancia es CONDICIONAL al tipo de texto: "
                   "n-gram acelera repeticion/codigo gratis; el habla natural general exige draft/heads."),
        prediction=("ngram-* da >1.15x lossless en echo/codigo; en habla ~1.0-1.13x (ngram-mod bit-identico). "
                    "Refutado si ningun metodo supera 1.15x lossless en ningun caso real."),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp021_speculative_decode")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-SPEED-1")
        notes.append("H-SPEED-1 marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("El decode es un cartero que va a la RAM y vuelve con UNA carta (token) por viaje; el viaje "
                 "(leer 1.8 GiB de pesos) cuesta igual lleve 1 o K cartas. ¿Como entregar mas palabras por viaje?"),
        everyday=("Un ayudante (drafter) adivina las proximas casas y el cartero solo CONFIRMA en un viaje; si "
                  "acierta K, entrega K cartas por 1 viaje. Si el ayudante es un n-grama (mira lo ya dicho) "
                  "cuesta 0; si es una libreta entrenada (head MTP/EAGLE) cuesta unos gramos; si es OTRO cartero "
                  "(draft model grande) pelea por la misma carretera (banda) y casi no ayuda."),
        solutions=["n-gram: 0 modelo, 0 entrenamiento -> gratis en texto repetitivo (echo 1.45x), casi nada en habla",
                   "ngram-mod: bit-identico al baseline, gana siempre poco, riesgo 0 -> default seguro",
                   "draft model grande separado: compite por banda (exp004) -> penalizado en i3",
                   "cabezas MTP/EAGLE sobre base congelada: ~0 banda, aceleran habla general (peldano 2)",
                   "difusion (Gemma): commit de bloque, pero necesita modelo de difusion (26B GPU) -> inviable i3"],
        principles=["en CPU el cuello es la BANDA, no el computo: commitear K tokens por lectura de pesos",
                    "el drafter debe costar ~0 bytes (n-gram=0, head=MB); un draft grande separado no paga",
                    "difusion y speculative son DUALES; se importa el PRINCIPIO de bloque, no el modelo",
                    "n-gram es gratis pero estructural (repeticion); el habla general necesita params entrenables"],
        adaptation=("H-SPEED-1 {}: el hibrido viable en el i3 es 'block-speculative bandwidth-aware' = drafter "
                    "barato (n-gram hoy; MTP/EAGLE head manana) + base AR como verificador exacto.").format(status),
        measurement=("exp021 REAL: baseline~{b} tok/s; ngram echo hasta 1.45x lossless; habla ~1.0-1.13x; "
                     "proyeccion heads MTP/EAGLE 2-3x (modelo de banda calibrado a exp004).").format(b=_fmt(base)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogia 7 etapas registrada (cartero/banda).")

    ceilings.add(CeilingRecord(
        subsystem="Velocidad de decode (F-SPEED) — romper el techo de banda ~8 tok/s del AR puro",
        known_limit=("AR puro: ~8 tok/s = pared de banda (1 lectura de pesos/token, exp004). Speculative lo rompe "
                     "commiteando K_aceptado tokens por lectura: techo nuevo ~= K_aceptado·BW/W_base. Limitado por "
                     "(a) la aceptacion del drafter (n-gram: alta en repeticion, baja en habla) y (b) el coste de "
                     "banda del drafter (n-gram 0; head MB; draft grande penaliza). Difusion daria commit de bloque "
                     "pero requiere modelo de difusion (GPU)."),
        blockers=[{"text": "n-gram acepta poco en habla natural no repetitiva", "kind": "diseno"},
                  {"text": "no hay head MTP/EAGLE pre-entrenada para Qwen2.5-Coder-3B (hay que entrenar/convertir)", "kind": "historico"},
                  {"text": "modelo de difusion (DiffusionGemma) es 26B GPU -> inviable en i3", "kind": "fisico"}],
        real_or_assumed="real", evidence=[S5.ref, S_BW.ref, S2.ref]))
    notes.append("1 techo 'real' (F-SPEED: techo de banda roto por speculative; limites nombrados).")

    dstmt = ("Adoptar speculative decoding BANDWIDTH-AWARE en Cognia (el binario b9391 ya lo soporta): "
             "(1) ngram-mod por DEFECTO (bit-identico, gana siempre algo, coste 0); (2) ngram-simple/map-k para "
             "flujos repetitivos/codigo/RAG/JSON/tool-calls (hasta 1.45x lossless); (3) para acelerar HABLA "
             "general, integrar draft 0.5B local Y/O entrenar/conseguir una cabeza MTP/EAGLE para Qwen2.5-Coder-3B "
             "(draft-mtp/draft-eagle3). NO usar un draft model grande separado (compite por banda, exp004). Estas "
             "cabezas son la respuesta a 'parametros entrenados modificables que funcionan con el sistema actual'.")
    drat = ("exp021 REAL (i3): ngram gana gratis en repeticion/codigo (echo 1.45x lossless) pero ~1.0x en habla; "
            "proyeccion de banda (calibrada a exp004) da 2-3x para heads MTP/EAGLE. DiffusionGemma confirma el "
            "principio de commit-de-bloque pero su modelo es GPU. Difusion y speculative son duales.")
    dec = Decision(id="D-SPEED-1", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S5), _to_plain(S2), _to_plain(S_BW)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-SPEED-1 ACEPTADA por el ledger (tier5 exp021 + tier1 spec-decode + tier5 exp004).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-SPEED-1:", e); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle34_speculative_decode',
                                description='CYCLE 34 (H-SPEED-1: speculative decoding bandwidth-aware).')
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
    print("RESUMEN — CYCLE 34: speculative decoding bandwidth-aware (H-SPEED-1)")
    print("=" * 78)
    print("veredicto H-SPEED-1:", status.upper() if status else "?")
    print("  " + s.get('headline', ''))
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
