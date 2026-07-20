r"""
cycle24_kernel_init.py — CICLO 24 a través del Investigation Engine (proceso end-to-end).

POR QUÉ: la directiva (v2/v3) exige que el método de investigación sea CÓDIGO, no narrativa, y que
el veredicto pase por las compuertas reales. Este ciclo cierra (o afila) H-CEIL-3: ¿el plateau de
recall del mezclador lineal (~0.18) se levanta con la FORMA del kernel (Taylor 2do orden) y/o la
mimetic init, NO con el mero ancho del ELU+1 (refutado en exp010)?

DISEÑO DEL REGISTRO (mejora sobre cycle23): en vez de hardcodear los números del experimento como
literales, este ciclo LEE `exp011_kernel_init/results/results.json` y DERIVA el veredicto del
`summary` del experimento. Así el registro es CORRECTO POR CONSTRUCCIÓN (sin error de transcripción)
y honesto: los números vienen de la corrida con seed fijo, no de la memoria del agente. Los enunciados
e hipótesis (literatura tier-1) sí son literales conocidos. Pasa por las MISMAS compuertas que cycle23:
  - HypothesisRegistry.mark_{supported,refuted,mixta} -> mismo DoD (PrematureVerdictError).
  - EvidenceLedger.record_decision  -> rechaza decisión importante solo-opinión (OpinionOnlyError).
  - analogy.extract_principles      -> 7 etapas / >=3 soluciones (IncompleteAnalogyError).
  - CeilingTracker.add              -> valida kinds + real_or_assumed.
  - PermanentRecord.verify_no_loss  -> "pérdida de conocimiento = fallo" chequeable.

VEREDICTO (derivado del summary de exp011, honesto):
  - summary.lifts no vacío           -> H-CEIL-3 APOYADA (algún lever levanta el plateau a steps iguales).
  - summary.all_near_floor           -> H-CEIL-3 MIXTA (piso de optim/budget: no separa el efecto).
  - ni una ni otra                   -> H-CEIL-3 REFUTADA a esta escala (+ genera H-CEIL-4: el cuello
                                        es más profundo — profundidad/escala/optimizador/híbrido).

Correr (DESPUÉS de exp011):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp011_kernel_init.run --steps 3000 --per_config_sec 2400
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle24_kernel_init
Inspeccionar:
    venv312\Scripts\python.exe -m cognia_x.research.cli status --store cognia_x/research/store/cycle24_kernel_init
    venv312\Scripts\python.exe -m cognia_x.research.cli verify --store cognia_x/research/store/cycle24_kernel_init

Escalabilidad (§6): O(1) por registro escrito (append JSONL); verify_no_loss O(n) sobre ESTE store;
lee un results.json chico una vez. I/O-bound, trivial en 2c/4t sin GPU; el store es JSON portable.
"""
import argparse
import json
import os
import shutil
import sys

from cognia_x.research.schema import (
    Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle24_kernel_init'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp011_kernel_init', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# Literatura tier-1 (constante, conocida — NO depende del resultado).
S1 = Source(
    tier=1, ref="arXiv:2402.18668", obtained=True,
    claim=("Arora et al. 2024 (Based): lo que recorre la frontera de recall NO es el ANCHO del "
           "feature-map sino su FORMA — el feature-map de 2do orden de Taylor (phi(q).phi(k) ~ "
           "exp(q.k)) es 'most effective' en recall MQAR; los mapas simples tipo ELU+1 caen por debajo."),
)
S2 = Source(
    tier=1, ref="arXiv:2410.11135", obtained=True,
    claim=("Trockman et al. 2024 (Mimetic Initialization): el recall pobre de los mezcladores de "
           "estado puede ser de OPTIMIZACION/INIT, no de capacidad; una init estructurada cerca de "
           "una copia desbloquea recall ya presente."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _load_summary(results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (¿exp011 terminó? corré el experimento primero): "
                         + results_path)
    return data, data['summary']


def _verdict_from_summary(summary):
    """Mapea el summary de exp011 -> (status, etiqueta). Honesto: floor->mixta, lifts->apoyada, else->refutada."""
    if summary.get('all_near_floor'):
        return 'mixta', 'PISO (optim/budget): no separa el efecto kernel/init del piso de aprendibilidad'
    if summary.get('lifts'):
        return 'apoyada', 'algún lever ({}) levanta el plateau a steps iguales'.format(
            ' y '.join(summary['lifts']))
    return 'refutada', 'ni el kernel Taylor ni la mimetic init levantan el plateau a esta escala'


def run(store, results_path):
    data, summary = _load_summary(results_path)
    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    base = summary.get('baseline_acc')
    acc = summary.get('acc_by_name', {})
    taylor = acc.get('taylor')
    matched = acc.get('elu_matched')
    mimetic = acc.get('elu_mimetic')
    dtaylor = summary.get('delta_taylor')
    dmimetic = summary.get('delta_mimetic')
    tvm = summary.get('taylor_vs_matched')
    status, label = _verdict_from_summary(summary)

    # --- S3: dato propio (tier 5), números DERIVADOS de la corrida (no inventados) ---
    s3_claim = (
        "exp011 (d=24 fijo, lineal_puro, n_heads=1, n_pairs=16, seed0, steps={steps}, step-parity, "
        "chance {chance}): baseline ELU+1={base}, taylor={taylor} (delta {dt}), "
        "elu_matched(dim~{matched_mult}*dh, igual dim que taylor)={matched}, "
        "mimetic={mimetic} (delta {dmim}). taylor_vs_matched={tvm}. {kernel} | {init}"
    ).format(
        steps=data.get('steps'), chance=_fmt(summary.get('chance')),
        base=_fmt(base), taylor=_fmt(taylor), dt=_fmt(dtaylor),
        matched_mult=data.get('matched_mult'), matched=_fmt(matched),
        mimetic=_fmt(mimetic), dmim=_fmt(dmimetic), tvm=_fmt(tvm),
        kernel=summary.get('kernel_verdict', ''), init=summary.get('init_verdict', ''),
    )
    S3 = Source(tier=5, ref="cognia_x/experiments/exp011_kernel_init", obtained=True, claim=s3_claim)
    for s in (S1, S2, S3):
        ledger.add_source(s)
    notes.append("3 fuentes (S1/S2 tier1 Based+Mimetic; S3 tier5 exp011 propio, números de results.json).")

    # --- H-CEIL-3: veredicto derivado del experimento, por la compuerta DoD ---
    # evidence_for/against siempre >=1 (refutar-antes-de-aceptar). Para 'apoyada': el lever nulo o el
    # caveat de escala es el contra. Para 'refutada': la literatura que lo predecía es el a-favor.
    if status == 'apoyada':
        ev_for = [S1.ref, S2.ref, S3.ref]
        ev_against = [S3.ref]  # el caveat honesto (escala tiny / el lever que NO levantó) vive en el veredicto
        adv = ("APOYADA a esta escala: {label}. Evidencia propia: baseline={base}, taylor={taylor} "
               "(delta {dt}), mimetic={mimetic} (delta {dmim}), taylor_vs_matched={tvm}. {kernel}. "
               "CAVEAT (contra): escala tiny (d=24, steps={steps}); generaliza solo como dirección hasta "
               "repetir a mayor escala/seed.").format(
                   label=label, base=_fmt(base), taylor=_fmt(taylor), dt=_fmt(dtaylor),
                   mimetic=_fmt(mimetic), dmim=_fmt(dmimetic), tvm=_fmt(tvm),
                   kernel=summary.get('kernel_verdict', ''), steps=data.get('steps'))
    elif status == 'mixta':
        ev_for = [S1.ref, S2.ref]
        ev_against = [S3.ref]
        adv = ("MIXTA: {label}. baseline={base}, taylor={taylor}, mimetic={mimetic} — todo cerca del "
               "azar ({chance}); a esta escala no se separa el efecto del piso de optim/budget. NO es "
               "evidencia ni a favor ni en contra del kernel/init.").format(
                   label=label, base=_fmt(base), taylor=_fmt(taylor), mimetic=_fmt(mimetic),
                   chance=_fmt(summary.get('chance')))
    else:  # refutada
        ev_for = [S1.ref, S2.ref]   # la literatura predecía que ayudaría: es el 'a favor' que NO se cumplió
        ev_against = [S3.ref]
        adv = ("REFUTADA a esta escala: {label}. baseline={base}, taylor={taylor} (delta {dt}), "
               "elu_matched={matched}, mimetic={mimetic} (delta {dmim}). El plateau (~0.18) NO se mueve "
               "ni con la FORMA del kernel (Taylor) ni con la INIT (mimetic) ni con el ANCHO (exp010). "
               "El cuello es más profundo -> H-CEIL-4. {kernel}").format(
                   label=label, base=_fmt(base), taylor=_fmt(taylor), dt=_fmt(dtaylor),
                   matched=_fmt(matched), mimetic=_fmt(mimetic), dmim=_fmt(dmimetic),
                   kernel=summary.get('kernel_verdict', ''))

    hyp = Hypothesis(
        id="H-CEIL-3",
        statement=("El plateau de recall del lineal (~0.18) se levanta con un KERNEL más rico (Taylor "
                   "2do orden, Based) y/o mimetic init (Trockman 2024) a presupuesto de pasos IGUAL — "
                   "NO con el mero ancho del ELU+1 (refutado en exp010)."),
        prediction=("A d=24 fijo y steps iguales, algún lever {taylor, mimetic} sube el recall entrenado "
                    "por encima de ~0.18. Refutado si ninguno lo mueve."),
        status='abierta',
        confidence='media',
        evidence_for=ev_for,
        evidence_against=ev_against,
        adversarial_verdict=adv,
        experiment_ref="exp011_kernel_init",
    )
    hyps.add(hyp)
    marker = {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]
    h_final = marker("H-CEIL-3")
    assert h_final.status == status, "H-CEIL-3 no quedó '{}'".format(status)
    notes.append("H-CEIL-3 marcada '{}' con DoD completo (gate no-prematuro pasado).".format(status))

    # --- Hipótesis hija SOLO si se refutó (el fracaso afila la siguiente, como CYCLE 23) ---
    if status == 'refutada':
        h4 = Hypothesis(
            id="H-CEIL-4",
            statement=("Si ni ancho (exp010) ni forma del kernel ni init (exp011) levantan el plateau a "
                       "esta escala tiny, el cuello del recall lineal entrenado es de PROFUNDIDAD/ESCALA "
                       "u OPTIMIZADOR — o requiere la capa de ATENCIÓN del híbrido (no se resuelve con un "
                       "mezclador de estado fijo a d=24)."),
            prediction=("Subir profundidad/d/steps, o cambiar el optimizador, o añadir 1 capa de atención "
                        "(híbrido) sube el recall por encima de ~0.18 donde el lineal puro a d=24 no puede. "
                        "Refutado si tampoco."),
            status='abierta',
            confidence='baja',
            evidence_for=[S1.ref, S2.ref],
            evidence_against=[],   # legítimo vacío: hipótesis ABIERTA sin experimento aún.
            adversarial_verdict='',
            experiment_ref='',
        )
        hyps.add(h4)
        notes.append("H-CEIL-4 añadida 'abierta' (generada por la refutación de H-CEIL-3).")

    # --- Analogía (7 etapas, >=3 soluciones), adaptada al resultado real ---
    analogy = AnalogyRecord(
        problem=("La libreta (mezclador lineal) se llena rápido aunque tenga páginas en blanco. exp010: "
                 "más páginas (ancho) no ayuda. ¿Ayuda mejor taquigrafía (kernel Taylor) o un índice "
                 "inicial (mimetic init)?"),
        everyday=("Recuerdas mal no por falta de páginas sino por CÓMO anotas y cómo arrancas la libreta. "
                  "Probás: (a) taquigrafía más expresiva, (b) un índice prearmado, (c) una libreta gigante."),
        solutions=[
            "comprar una libreta más grande (más ancho/estado) -> exp010 dice que casi no ayuda",
            "cambiar el SISTEMA de anotación (kernel Taylor 2do orden) -> exp011 lo mide",
            "armar un índice desde el inicio (mimetic init) -> exp011 lo mide",
            "si nada de eso alcanza: la libreta de tamaño fijo NO es el medio para esto (hace falta atención)",
        ],
        principles=[
            "más almacén no es más recuperación si la codificación es pobre (exp010)",
            "la forma de la representación (kernel) y el arranque (init) pueden importar más que el tamaño",
            "cuando forma+init+tamaño no alcanzan, el cuello es estructural (profundidad/atención), no del feature-map",
        ],
        adaptation=("veredicto de exp011: H-CEIL-3 {} -> {}").format(status, label),
        measurement=("exp011: baseline={}, taylor={}, elu_matched={}, mimetic={} (chance={}).").format(
            _fmt(base), _fmt(taylor), _fmt(matched), _fmt(mimetic), _fmt(summary.get('chance'))),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- Techo: el plateau de recall, actualizado con el resultado (sigue 'asumido' = mejorable) ---
    if status == 'apoyada':
        klimit = ("exp011 muestra que el plateau (~0.18) SÍ se levanta con {} a steps iguales (no era "
                  "tamaño de estado, exp010): el límite era de FORMA/INIT, ASUMIDO/mejorable, no informacional."
                  ).format(' y '.join(summary.get('lifts', [])))
        blockers = [{"text": "el feature-map/optim accede ahora a recall antes inaccesible", "kind": "diseno"}]
    elif status == 'mixta':
        klimit = ("exp011 inconcluso (piso de optim/budget a esta escala): no separa kernel/init del piso "
                  "de aprendibilidad. El plateau sigue ASUMIDO; falta budget/escala para distinguir.")
        blockers = [{"text": "budget/escala insuficiente para separar el efecto a d=24", "kind": "historico"}]
    else:
        klimit = ("exp011 REFUTA que forma del kernel (Taylor) o init (mimetic) levanten el plateau (~0.18) "
                  "a d=24; junto a exp010 (ancho) -> el cuello del recall lineal entrenado a esta escala NO "
                  "es del feature-map. Suspecto: profundidad/escala/optimizador o la capa de atención (H-CEIL-4). "
                  "Sigue ASUMIDO (no probado informacional).")
        blockers = [
            {"text": "ni ancho (exp010) ni forma (taylor) ni init (mimetic) mueven el recall a d=24", "kind": "diseno"},
            {"text": "posible límite de profundidad/escala/optimizador del mezclador de estado fijo", "kind": "historico"},
        ]
    ceiling = CeilingRecord(
        subsystem="Recall entrenado del mezclador lineal a d=24 — forma del kernel vs init (exp011)",
        known_limit=klimit,
        blockers=blockers,
        real_or_assumed="asumido",
        evidence=[S1.ref, S2.ref, S3.ref],
    )
    ceilings.add(ceiling)
    notes.append("1 techo 'asumido' actualizado con el veredicto de exp011 (status={}).".format(status))

    # --- Decisión D-CEIL-3: aceptar o descartar los levers según el resultado (gate del ledger) ---
    if status == 'apoyada':
        dstmt = ("Adoptar {} como mecanismo de recall del mezclador lineal de Cognia-X (levanta el plateau "
                 "a steps iguales; el ancho del ELU+1 queda descartado, exp010).").format(
                     ' y '.join(summary.get('lifts', [])))
        drat = ("exp011: baseline={}, taylor={}, mimetic={} (chance={}); el/los lever(s) {} superan el "
                "plateau ~0.18 a steps iguales, controlando tamaño con elu_matched.").format(
                    _fmt(base), _fmt(taylor), _fmt(mimetic), _fmt(summary.get('chance')),
                    ' y '.join(summary.get('lifts', [])))
    elif status == 'mixta':
        dstmt = ("NO decidir sobre kernel/init aún: exp011 quedó en el piso de optim/budget a d=24. "
                 "Backlog: repetir con más budget/escala antes de adoptar o descartar.")
        drat = ("exp011 inconcluso (todo cerca del azar {}); decidir ahora sería optimizar sin evidencia "
                "que separe el efecto.").format(_fmt(summary.get('chance')))
    else:
        dstmt = ("Descartar 'forma del kernel (Taylor) + mimetic init' como vía para subir el recall del "
                 "mezclador lineal a d=24 (exp011); junto al ancho (exp010), redirigir a "
                 "profundidad/escala/optimizador o a la capa de atención del híbrido (H-CEIL-4).")
        drat = ("exp011: baseline={}, taylor={} (delta {}), mimetic={} (delta {}); ningún lever supera el "
                "plateau ~0.18 a steps iguales. El cuello no es del feature-map a esta escala.").format(
                    _fmt(base), _fmt(taylor), _fmt(dtaylor), _fmt(mimetic), _fmt(dmimetic))
    decision = Decision(
        id="D-CEIL-3",
        statement=dstmt,
        rationale=drat,
        sources=[_to_plain(S3), _to_plain(S1)],   # tier5 propio + tier1 paper -> funda (no OpinionOnlyError)
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-CEIL-3 ACEPTADA por el ledger (tier5 S3 + tier1 S1 -> funda; sin OpinionOnlyError).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-CEIL-3 (no debería con tier5+tier1): {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes, status, label


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle24_kernel_init',
        description='CYCLE 24 (kernel Taylor + mimetic init -> H-CEIL-3) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS, help='results.json de exp011')
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, status, label = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 24: kernel Taylor + mimetic init -> H-CEIL-3 [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("veredicto H-CEIL-3: {}  ({})".format(status.upper(), label))
    print("")
    for n in notes:
        print("  CHECK  {}".format(n))
    print("")

    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  {:<12}: {} (backlog de refutación)".format('asumidos', len(ceilings.assumed_limits())))
    print("")

    print("  verify_no_loss:")
    for d in res['details']:
        flag = 'OK' if d['ok'] else 'FAIL'
        print("    [{}] {:<12} journaled={} live={} missing={}".format(
            flag, d['store'], d['journaled'], d['live'], d.get('missing', 0)))
    print("")
    if res['ok']:
        print("  verify_no_loss = OK (sin pérdida de conocimiento)")
        print("=" * 78)
        return 0
    print("  verify_no_loss = FAIL")
    print("=" * 78)
    return 1


if __name__ == '__main__':
    sys.exit(main())
