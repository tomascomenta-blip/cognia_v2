"""
cognia/lcd/arbiter.py — ARBITRO AI-nativo de LCD (plan 12, Fase 1/3).

El aporte de investigacion del paper (§4.2): dado un fallo end-to-end en un
pipeline heterogeneo, ATRIBUIR la falla a la etapa culpable y re-ejecutar SOLO
esa. Aca se instancia para el pipeline LCD con la MISMA estrategia que gano en
AG-ARB (07_ARBITRO_MEJORA_PAPER.md): verificacion por etapa con oraculos
ejecutables CERO-LLM, en cascada; la primera etapa que viola su contrato es la
culpable. NO un critico-VLM (que en AG-ARB dio 31% con sesgo de culpar al
artefacto terminal); el VLM queda como fallback para percepcion (sin oraculo).

Pipeline LCD y sus contratos (analogo a plan->design->code->test del agente):
    descripcion --[plan]--> escena --[geometria]--> posiciones --[render]--> PNG

  1. plan:      ¿la escena tiene TODOS los objetos que pidio la descripcion?
                (oraculo: parser de la descripcion vs nombres en la escena)
  2. geometria: ¿las POSICIONES satisfacen la relacion pedida y estan en canvas?
                (oraculo: _relation_ok + bounds; distingue de plan porque los
                 objetos SI estan, lo que falla es donde)
  3. render:    ¿el PNG existe y no esta vacio/degenerado?
                (oraculo: el archivo existe y tiene regiones distintas del fondo)

La cascada corre en ORDEN: la primera violacion es la culpa. Distinguir plan de
geometria es justo el 'render de control' del paper: si el objeto FALTA es plan;
si esta pero mal ubicado es geometria.

Concreto: funciones planas sobre la Scene ya existente; sin clases.
"""
from __future__ import annotations

from cognia.lcd.planner import _find_objects, _find_relation, _tokens
from cognia.lcd.scene import Scene
from cognia.lcd.tools_lcd import _relation_ok

STAGES = ("plan", "geometria", "render")


def _bounds_ok(scene: Scene) -> bool:
    """Todos los objetos con su centro dentro del canvas [0,1] (margen chico)."""
    for o in scene.objects:
        if not (-0.05 <= o.x <= 1.05 and -0.05 <= o.y <= 1.05):
            return False
    return True


def attribute_scene_failure(descripcion: str, scene: Scene,
                            render_ok: bool = None) -> dict:
    """Cascada de contratos: devuelve {stage, reason, contract} con la etapa
    culpable, o stage=None si todos los contratos pasan. render_ok=None deja el
    contrato de render sin evaluar (solo se llega si plan+geometria pasan).

    stage None = 'todos los contratos pasan' (mismo string que reconoce
    skill_capture como oraculo duro)."""
    toks = _tokens(descripcion)
    expected = [k for _, k in _find_objects(toks)]
    rel = _find_relation(descripcion)
    names = [o.name for o in scene.objects]

    # 1. plan: cobertura de objetos (¿estan los que se pidieron?)
    faltantes = [e for e in expected if e not in names]
    if faltantes:
        return {"stage": "plan", "reason": f"la escena no cubre objeto(s) pedido(s): {faltantes}",
                "contract": "descripcion->plan"}

    # 2. geometria: relacion satisfecha por las posiciones + objetos en canvas
    if not _bounds_ok(scene):
        return {"stage": "geometria", "reason": "objeto(s) fuera del canvas",
                "contract": "plan->geometria(bounds)"}
    if len(expected) >= 2 and rel:
        if not _relation_ok(scene, expected[0], rel, expected[1]):
            return {"stage": "geometria",
                    "reason": f"relacion '{rel}' no satisfecha por las posiciones "
                              f"({expected[0]} vs {expected[1]})",
                    "contract": "plan->geometria(relacion)"}

    # 3. render: el PNG salio (solo si se paso el flag)
    if render_ok is False:
        return {"stage": "render", "reason": "el render no produjo un PNG valido",
                "contract": "geometria->render"}

    return {"stage": None, "reason": "todos los contratos pasan", "contract": None}


# ── Inyeccion de fallos: ground-truth de atribucion (el dataset del arbitro) ──
# Corrompe la salida de UNA etapa conocida; el arbitro debe señalar ESA etapa.
# Es el unico 'dataset' honesto para medir atribucion (el mundo real no lo da).

def inject_fault(scene: Scene, stage: str) -> tuple:
    """Devuelve (scene_corrupta, render_ok) con un fallo seeded en `stage`.
    - plan: borra un objeto (queda faltante) -> el arbitro debe decir 'plan'.
    - geometria: rompe la relacion moviendo el sujeto al lado opuesto -> 'geometria'.
    - render: escena intacta pero render_ok=False -> 'render'.
    No muta la escena original (copia via JSON)."""
    import copy
    s = copy.deepcopy(scene)
    if stage == "plan":
        if len(s.objects) > 1:
            s.objects = s.objects[:-1]        # borra el ultimo objeto (el sujeto)
        return s, True
    if stage == "geometria":
        # colocar el sujeto EN el centro de la referencia viola TODA relacion
        # estricta (on: a.y<b.y; left: a.x<b.x; below: a.y>b.y; ... todas usan
        # una desigualdad que la igualdad rompe) sin sacar el objeto de la escena
        # (objetos presentes, posicion mala) -> fuerza culpa 'geometria', no 'plan'.
        if len(s.objects) >= 2:
            subj = s.objects[-1]
            base = s.objects[0]
            subj.x, subj.y = base.x, base.y
        return s, True
    if stage == "render":
        return s, False                       # escena OK, render fallo
    return s, True


def eval_attribution(specs, stages=STAGES) -> dict:
    """Para cada spec y cada etapa, inyecta el fallo de esa etapa y mide si el
    arbitro atribuye a la etapa correcta. Devuelve tasa de acierto global y la
    DISTRIBUCION de culpas (metrica de salud anti-colapso: si el arbitro culpa
    siempre a la misma etapa, aparece aca)."""
    from cognia.lcd.planner import plan as _plan
    total, correct = 0, 0
    confusion = {}                            # (true, pred) -> count
    culpas = {s: 0 for s in stages}
    for desc in specs:
        base = _plan(desc)
        if len(base.objects) < 2:
            continue
        for true_stage in stages:
            corrupt, render_ok = inject_fault(base, true_stage)
            verdict = attribute_scene_failure(desc, corrupt, render_ok=render_ok)
            pred = verdict["stage"]
            total += 1
            if pred == true_stage:
                correct += 1
            if pred in culpas:
                culpas[pred] += 1
            confusion[f"{true_stage}->{pred}"] = confusion.get(f"{true_stage}->{pred}", 0) + 1
    acc = correct / total if total else 0.0
    return {"accuracy": round(acc, 3), "total": total, "correct": correct,
            "culpa_distribution": culpas, "confusion": confusion}
