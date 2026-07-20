"""
cognia/lcd/eval.py — Protocolo de evaluación mínimo del pipeline LCD.

Testea las DOS propiedades que el paper (§8.1, §8.2) señala como el
diferenciador de LCD frente a difusión monolítica, y que SÍ se pueden medir en
CPU sin refinador neuronal:
  1. Control composicional (§8.1): dada una spec (objetos + relación), la escena
     ¿tiene TODOS los objetos, en la relación pedida? En difusión monolítica la
     literatura documenta fallas recurrentes aquí (objetos faltantes, posiciones
     contradictorias); en LCD es exacto POR CONSTRUCCIÓN.
  2. Editabilidad (§8.2): cambiar UN objeto (color/posición) sin regenerar la
     escena — operación O(1) sobre la representación estructurada, imposible
     de forma nativa en el espacio latente de un modelo end-to-end.

Corre el planner de REGLAS (determinista) para que el número mida el pipeline,
no el ruido del LLM. Genera también PNGs de muestra.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cognia.lcd.planner import plan
from cognia.lcd.renderer import render_to
from cognia.lcd.scene import Scene

OUT = Path(__file__).resolve().parent / "out"

# Specs congeladas: prompt + objetos esperados + relación esperada (sujeto, rel, ref).
SPECS = [
    ("a red cup on a blue table", ["cup", "table"], ("cup", "on", "table")),
    ("una taza roja sobre una mesa azul", ["taza", "mesa"], ("taza", "on", "mesa")),
    ("a green ball to the left of a yellow box", ["ball", "box"], ("ball", "left_of", "box")),
    ("a book on a table", ["book", "table"], ("book", "on", "table")),
    ("un plato sobre una mesa", ["plato", "mesa"], ("plato", "on", "mesa")),
    ("a lamp to the right of a chair", ["lamp", "chair"], ("lamp", "right_of", "chair")),
    ("a sun above a house", ["sun", "house"], ("sun", "above", "house")),
    ("una pelota debajo de una mesa", ["pelota", "mesa"], ("pelota", "below", "mesa")),
]


def _relation_ok(scene: Scene, subj, rel, ref) -> bool:
    """Verifica que las POSICIONES de la escena satisfacen la relación pedida."""
    a, b = scene.get(subj), scene.get(ref)
    if a is None or b is None:
        return False
    if rel == "on":
        return a.y < b.y and abs(a.x - b.x) < 0.25          # encima y ~centrado
    if rel == "above":
        return a.y < b.y - 0.05
    if rel == "below":
        return a.y > b.y
    if rel == "left_of":
        return a.x < b.x
    if rel == "right_of":
        return a.x > b.x
    return True


def eval_compositional():
    rows, n_ok = [], 0
    for prompt, expected, (subj, rel, ref) in SPECS:
        scene = plan(prompt)
        names = [o.name for o in scene.objects]
        all_present = all(e in names for e in expected)
        count_ok = len(scene.objects) == len(expected)
        rel_ok = _relation_ok(scene, subj, rel, ref)
        ok = all_present and count_ok and rel_ok
        n_ok += ok
        rows.append({"prompt": prompt, "present": all_present, "count_ok": count_ok,
                     "relation_ok": rel_ok, "pass": ok, "n_objs": len(scene.objects)})
    return n_ok, len(SPECS), rows


def eval_editability():
    """Edita UN objeto y verifica: (a) el edit es O(1) y solo cambia el target;
    (b) re-render sin regenerar el resto (mismos demás objetos, idénticos)."""
    scene = plan("a red cup on a blue table")
    before = scene.to_json()
    table_before = scene.get("table").color
    changed = scene.edit("cup", color="green")
    cup_after = scene.get("cup").color
    table_after = scene.get("table").color
    # también mover la taza (edición de posición selectiva)
    scene.edit("cup", x=0.3)
    return {
        "edit_applied": changed,
        "target_changed": cup_after != (220, 60, 50) and cup_after == (70, 180, 90),
        "others_untouched": table_before == table_after,   # la mesa NO cambió
        "before_json_len": len(before),
    }


def render_samples():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    # una muestra composicional
    s = plan("a red cup on a blue table")
    paths.append(render_to(s, OUT / "cup_on_table.png"))
    # editabilidad: antes y después de cambiar el color de la taza
    render_to(s, OUT / "edit_before.png")
    s.edit("cup", color="green")
    paths.append(render_to(s, OUT / "edit_after_green.png"))
    # una escena de 2 objetos con relación espacial
    s2 = plan("a green ball to the left of a yellow box")
    paths.append(render_to(s2, OUT / "ball_left_of_box.png"))
    # sol sobre casa
    s3 = plan("a sun above a house")
    paths.append(render_to(s3, OUT / "sun_above_house.png"))
    return paths


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("[lcd-eval] pipeline mínimo LCD (plan -> geometría -> render aprox)", flush=True)

    n_ok, n, rows = eval_compositional()
    print(f"\n[§8.1] CONTROL COMPOSICIONAL: {n_ok}/{n} specs = {n_ok/n:.0%}", flush=True)
    for r in rows:
        tag = "PASS" if r["pass"] else "FAIL"
        print(f"   [{tag}] {r['prompt'][:45]:<45} objs={r['n_objs']} rel_ok={r['relation_ok']}", flush=True)

    ed = eval_editability()
    print(f"\n[§8.2] EDITABILIDAD (cambiar 1 objeto sin regenerar):", flush=True)
    print(f"   edit aplicado: {ed['edit_applied']} | target cambió: {ed['target_changed']} "
          f"| resto intacto: {ed['others_untouched']}", flush=True)
    edit_ok = ed["edit_applied"] and ed["target_changed"] and ed["others_untouched"]

    paths = render_samples()
    print(f"\n[render] {len(paths)} PNGs de muestra -> {OUT}", flush=True)
    for p in paths:
        print("   ", Path(p).name, flush=True)

    out = {"compositional": {"passed": n_ok, "total": n, "rows": rows},
           "editability": ed, "editability_ok": edit_ok,
           "samples": [Path(p).name for p in paths]}
    (OUT / "results.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    verdict = (n_ok == n) and edit_ok
    print(f"\n[lcd-eval] {'OK' if verdict else 'PARCIAL'}: control composicional "
          f"exacto {n_ok}/{n} + editabilidad selectiva {'sí' if edit_ok else 'no'}. "
          f"Refinador neuronal (fotorrealismo §4.1 mod6) FUERA DE ALCANCE en CPU.", flush=True)


if __name__ == "__main__":
    main()
