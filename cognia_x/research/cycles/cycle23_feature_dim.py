r"""
cycle23_feature_dim.py — CICLO 23 a través del Investigation Engine (proceso end-to-end).

POR QUÉ: la directiva v2 exige que el método de investigación sea CÓDIGO ejecutable, no narrativa.
Este script POBLA el store del engine con TODOS los registros del CYCLE 23 (fuentes, hipótesis
refutada + hipótesis nueva abierta, analogía, techo, decisión) PASANDO por las compuertas reales:
  - EvidenceLedger.record_decision  -> rechaza decisiones importantes solo-opinión (OpinionOnlyError).
  - HypothesisRegistry.mark_refuted -> exige el MISMO DoD que apoyada/mixta (PrematureVerdictError):
    prediction + evidence_for>=1 + evidence_against>=1 + adversarial_verdict + experiment_ref.
  - analogy.extract_principles      -> exige 7 etapas / >=3 soluciones (IncompleteAnalogyError).
  - CeilingTracker.add              -> valida kinds + real_or_assumed (ValueError).
  - PermanentRecord.verify_no_loss  -> "pérdida de conocimiento = fallo" chequeable por contenido.

HEADLINE del ciclo: una hipótesis EMPÍRICA REFUTADA (H-CEIL-2) que afila una nueva (H-CEIL-3 abierta).
exp010 (d=24 fijo, lineal_puro, step-parity) ensancha el feature-map ELU+1 x4 (estado 576 -> 9216,
16x más estado) y el recall ENTRENADO NO se mueve (0.181 -> 0.181, +0.000; corridas más cortas dieron -0.002..+0.005, todas en el ruido ~0.01).
Esto REFUTA que el plateau (~0.18) sea de tamaño de estado/ancho y APUNTA a la FORMA del kernel
(Taylor/2do orden de Based) y/o optimización/init (mimetic init de Trockman) -> H-CEIL-3.

Reproducibilidad: REINICIA el store del ciclo al arrancar (flag --reset, default True). Re-correr
= mismos registros (idempotente por contenido: los datos son literales verificados, no aleatorios).
Toda cita/número viene de evidencia REAL (papers arXiv + exp010 corrido); nada inventado.

Correr:
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle23_feature_dim
Inspeccionar:
    venv312\Scripts\python.exe -m cognia_x.research.cli status   --store <store>
    venv312\Scripts\python.exe -m cognia_x.research.cli verify   --store <store>

Escalabilidad (§6): O(1) por registro escrito (append JSONL journaleado); verify_no_loss es O(n)
sobre el histórico de ESTE store. I/O-bound, trivial en 2c/4t sin GPU; el store es JSON portable.
"""
import argparse
import os
import shutil
import sys

from cognia_x.research.schema import (
    Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry, PrematureVerdictError
from cognia_x.research.analogy import extract_principles, IncompleteAnalogyError
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

# Store por defecto del ciclo: aislado del store general (cognia_x/research/store/) para que
# re-correr el ciclo no contamine ni dependa de otros ciclos. Gitignoreado (store/ del paquete).
DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle23_feature_dim'
)


def _safe_utf8():
    # POR QUÉ: en consolas Windows (cp1252) los acentos rompen; intentar UTF-8 sin fallar si no se puede.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Evidencia VERIFICADA del ciclo (papers arXiv reales + experimento propio corrido).
# NO inventar ni alterar ninguna cita/número: estos literales son la única fuente.
# Los números de S3 (mult1=0.181, mult4=0.181, +0.000, estado 576->9216) son los de la corrida
# canónica step-parity de exp010 (6000 steps, seed0, HEADLINE "PREDICCION REFUTADA"); cross-check
# exacto contra cognia_x/experiments/exp010_feature_dim/results/results.json (steps=6000).
# ---------------------------------------------------------------------------
S1 = Source(
    tier=1, ref="arXiv:2402.18668", obtained=True,
    claim=("Arora et al. 2024 (Based): la dimension del feature-map de la atencion lineal es el LEVER "
           "para recorrer la frontera de Pareto recall-memoria; Based usa un feature-map de 2do orden "
           "(Taylor), no un ELU+1 ancho."),
)
S2 = Source(
    tier=1, ref="arXiv:2410.11135", obtained=True,
    claim=("Trockman et al. 2024 (Mimetic Initialization): la pobre recall de SSMs en copy/AR puede "
           "deberse a DIFICULTADES DE ENTRENAMIENTO, no a limites de capacidad fundamentales ('la "
           "capacidad existia pero no se accedia por la inicializacion'); init estructurada (A~1, "
           "Delta~1, W_C^T W_B~I) hace que Mamba aprenda recall desde cero mucho mas facil."),
)
S3 = Source(
    tier=5, ref="cognia_x/experiments/exp010_feature_dim", obtained=True,
    claim=("exp010 (d=24 fijo, lineal_puro, step-parity 6000 steps, seed0, chance 0.0625): ensanchar "
           "el feature-map ELU+1 x4 (estado 576 -> 9216, 16x mas estado) NO sube el recall entrenado: "
           "baseline mult1=0.181 vs mult4=0.181 (delta +0.000, nulo; corridas mas cortas dieron "
           "-0.002..+0.005, todas dentro del ruido ~0.01). Ni el tamano "
           "de estado ni el ancho del feature-map mueven el plateau."),
)


def run(store):
    """Puebla el store del engine con los registros del CYCLE 23 a través de las compuertas reales."""
    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)

    notes = []  # líneas de CHECK para el RESUMEN final.

    # --- 1) FUENTES (todas obtained=True) -----------------------------------
    for s in (S1, S2, S3):
        ledger.add_source(s)
    notes.append("3 fuentes registradas (S1/S2 tier1 papers Based+Mimetic; S3 tier5 exp010 propio).")

    # --- 2) HIPÓTESIS H-CEIL-2 (EMPÍRICA, status='refutada', DoD completo) ---
    # evidence_for=[S1] (Based predice que el feature dim es el lever); evidence_against=[S3]
    # (exp010 refuta el ANCHO). Se citan las refs (trazables al store de sources).
    hyp = Hypothesis(
        id="H-CEIL-2",
        statement=("El plateau del recall lineal entrenado (~0.18, exp009) se levanta ENSANCHANDO el "
                   "feature-map de la atencion lineal (lever 'feature dimension' de Based)."),
        prediction=("A d fijo, un feature-map mas ancho (mult>1) da mayor recall entrenado que el "
                    "baseline ELU+1. REFUTADO si el ancho no mueve el recall."),
        status='abierta',  # se transiciona a 'refutada' vía el registro (gate DoD).
        confidence='media',
        evidence_for=[S1.ref],
        evidence_against=[S3.ref],
        adversarial_verdict=(
            "REFUTADA para el ANCHO: mult=4 da 16x mas estado (576->9216) y el recall NO se mueve "
            "(0.181->0.181, +0.000). Esto ademas REFUTA que el plateau sea un limite "
            "de tamano de estado/capacidad cruda, y APUNTA a la FORMA del feature-map (kernel) y/o "
            "optimizacion/init: Based usa kernel Taylor (no ELU+1 ancho), Trockman usa mimetic init. "
            "El fracaso afina la pregunta -> H-CEIL-3."),
        experiment_ref="exp010_feature_dim",
    )
    hyps.add(hyp)
    # mark_refuted enforza el MISMO DoD (prediction + evidence_for>=1 + evidence_against>=1 +
    # adversarial_verdict + experiment_ref). No bypassea ninguna compuerta.
    h_final = hyps.mark_refuted("H-CEIL-2")
    assert h_final.status == 'refutada', "H-CEIL-2 no quedó 'refutada'"
    notes.append("H-CEIL-2 marcada 'refutada' con DoD completo (gate de veredicto no-prematuro pasado).")

    # --- 3) HIPÓTESIS NUEVA H-CEIL-3 (ABIERTA, generada por el fracaso) ------
    # POR QUÉ status='abierta' y NO se marca: aún no tiene experimento corrido. evidence_against y
    # experiment_ref vacíos son legítimos para una hipótesis ABIERTA (el gate DoD solo aplica al MARCAR
    # un veredicto). El fracaso de H-CEIL-2 es la información que la genera: el cuello no es ancho.
    hyp_new = Hypothesis(
        id="H-CEIL-3",
        statement=("El plateau del recall lineal se levanta con un KERNEL mas rico (feature-map "
                   "Taylor/2do orden, Based) y/o mimetic init (Trockman 2024) a presupuesto de pasos "
                   "igual — NO con el mero ancho del ELU+1."),
        prediction=("Un feature-map Taylor (o init mimetica) sube el recall lineal entrenado por encima "
                    "de ~0.18 a d fijo, con steps iguales. Refutado si tampoco lo mueve."),
        status='abierta',
        confidence='baja',
        evidence_for=[S1.ref, S2.ref],
        evidence_against=[],      # legítimo vacío: hipótesis ABIERTA sin experimento aún (no se marca).
        adversarial_verdict='',
        experiment_ref='',         # sin experimento corrido todavía: por eso queda 'abierta'.
    )
    hyps.add(hyp_new)
    notes.append("H-CEIL-3 añadida 'abierta' (generada por el fracaso de H-CEIL-2; sin experimento aún).")

    # --- 4) ANALOGÍA (7 etapas, >=3 soluciones) -----------------------------
    analogy = AnalogyRecord(
        problem=("Un mezclador lineal entrena pero su recall se estanca muy por debajo de su capacidad "
                 "teorica; ?se arregla agrandando la libreta?"),
        everyday=("Tu agenda se llena rapido aunque tenga muchas paginas en blanco: el problema no es "
                  "cuantas paginas hay, sino COMO anotas (taquigrafia mala) y como buscas."),
        solutions=[
            "comprar una agenda mas grande (mas paginas = mas ancho/estado) -> exp010 dice que casi no ayuda",
            "cambiar el SISTEMA de anotacion (taquigrafia mejor = kernel Taylor) -> hipotesis abierta",
            "ordenar la agenda desde el principio con un indice (mimetic init) -> hipotesis abierta",
            "entrenar mas tiempo / mejor (optimizacion)",
        ],
        principles=[
            "mas almacen no es mas recuperacion si la CODIFICACION es pobre",
            "la forma de la representacion (kernel) importa mas que su tamano",
            "la init/optimizacion puede desbloquear capacidad ya presente",
        ],
        adaptation=("no ensanchar el ELU+1 (refutado); probar feature-map Taylor + mimetic init a "
                    "steps iguales."),
        measurement="exp010: mult1=0.181 vs mult4=0.181 (delta +0.000, null).",
        iterations=1,
    )
    # extract_principles enforza etapas 1-3 (problem, everyday, >=3 soluciones) antes de principles.
    principles = extract_principles(analogy)
    assert len(analogy.solutions) >= 3, "se requieren >=3 soluciones"
    assert len(principles) >= 3, "extract_principles no devolvió los principios"
    # La analogía no es un store del engine con compuerta de escritura propia; se journaliza como
    # 'analogies' para que verify_no_loss la cubra (pérdida = fallo, igual que el resto).
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios extraidos.".format(
        len(analogy.solutions), len(principles)))

    # --- 5) TECHO — ACTUALIZA el cuadro del techo de recall (asumido) -------
    # exp010 refuta que el plateau sea de tamaño de estado/ancho -> el límite efectivo es la FORMA del
    # kernel y/o optim/init: ASUMIDO/mejorable, no informacional. blockers diseno (ELU+1 base pobre)
    # + historico (init estandar no accede a la capacidad). real_or_assumed='asumido' (backlog refutar).
    ceiling = CeilingRecord(
        subsystem="Recall entrenado del mezclador lineal — el cuello NO es tamano de estado",
        known_limit=("exp010 refuta que el plateau (~0.18) sea de tamano de estado o ancho de "
                     "feature-map (16x estado -> +0.000). El limite efectivo es la FORMA del kernel "
                     "(ELU+1 vs Taylor) y/o optimizacion/init (Trockman 2024) -> ASUMIDO/mejorable, no "
                     "informacional."),
        blockers=[
            {"text": ("el feature-map ELU+1 puede ser una base pobre para recall asociativo; Based usa "
                      "2do orden (Taylor)"), "kind": "diseno"},
            {"text": ("la init estandar no accede a la capacidad de recall (Trockman: mimetic init la "
                      "desbloquea)"), "kind": "historico"},
        ],
        real_or_assumed="asumido",
        evidence=[S1.ref, S2.ref, S3.ref],
    )
    ceilings.add(ceiling)
    notes.append("1 techo 'asumido' añadido: el cuello del recall lineal NO es tamano de estado (forma/init).")

    # --- 6) DECISIÓN D-CEIL-2 (debe pasar el gate del ledger) ---------------
    # Registrar una MEJORA DESCARTADA (como pide la directiva). Cita tier-5 S3 + tier-1 S1 (ambas
    # obtenidas) -> funda; NO debe lanzar OpinionOnlyError.
    decision = Decision(
        id="D-CEIL-2",
        statement=("Descartar 'ensanchar el feature-map ELU+1' como via para subir el recall del "
                   "mezclador lineal; redirigir el esfuerzo a kernel Taylor + mimetic init (H-CEIL-3)."),
        rationale=("exp010: x4 ancho = 16x estado no movio el recall (+0.000). El cuello no es ancho ni "
                   "tamano de estado, sino la forma del kernel y la optimizacion/init (Based usa Taylor; "
                   "Trockman, mimetic init)."),
        sources=[_to_plain(S3), _to_plain(S1)],
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-CEIL-2 ACEPTADA por el ledger (tier5 S3 + tier1 S1 obtenidas -> funda; sin OpinionOnlyError).")
    except OpinionOnlyError as e:
        # No debería pasar con esta evidencia; si pasa, es un fallo de contenido a reportar (no debilitar el gate).
        print("ERROR: el ledger RECHAZÓ D-CEIL-2 (no debería con tier5+tier1): {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes


def _to_plain(obj):
    """schema.to_dict para dataclasses del engine; pasa dicts tal cual (los sources de la decisión)."""
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle23_feature_dim',
        description='CYCLE 23 (feature dim refutada -> kernel/init) a través del Investigation Engine — reproducible.')
    p.add_argument('--store', default=DEFAULT_STORE, help='dir de datos del ciclo')
    p.add_argument('--reset', dest='reset', action='store_true', default=True,
                   help='REINICIA el store del ciclo antes de poblar (default: True, idempotente)')
    p.add_argument('--no-reset', dest='reset', action='store_false',
                   help='NO reinicia (append sobre el store existente)')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        # POR QUÉ: re-correr = mismos registros. Sin reset, el append-only duplicaría todo el ciclo.
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes = run(store)

    # verify_no_loss(): "pérdida de conocimiento = fallo", chequeable por contenido.
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 23: feature dim del lineal REFUTADA -> kernel/init [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("")
    for n in notes:
        print("  CHECK  {}".format(n))
    print("")

    # Conteos vivos por store.
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    assumed = ceilings.assumed_limits()
    print("  {:<12}: {} (backlog de refutación)".format('asumidos', len(assumed)))
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
    print("  verify_no_loss = FAIL (un store tiene menos registros vivos que los journaleados)")
    print("=" * 78)
    return 1


if __name__ == '__main__':
    sys.exit(main())
