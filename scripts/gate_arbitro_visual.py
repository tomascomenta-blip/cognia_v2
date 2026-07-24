# -*- coding: utf-8 -*-
r"""
gate_arbitro_visual.py — GATE pre-registrado del arbitro visual (zero-shot).

QUE MIDE (pre-registrado, decidido ANTES de mirar los numeros): el lazo
diseno-a-codigo depende de UNA propiedad del arbitro — que una pagina MAS parecida
al mockup saque MAS nota que una menos parecida. Si eso no se cumple, el arbitro
empuja la reparacion en direccion equivocada y no sirve. Este gate mide esa
propiedad de forma objetiva y reproducible, sin necesitar juicios humanos (el
dueno no esta): compara pares EMPAREJADOS (imagen contra si misma) contra pares
NO-EMPAREJADOS (imagenes de categorias distintas).

GATE (criterio de PASA/KILL, fijado de antemano):
  1. separacion: media(emparejados) - media(no-emparejados) >= 3.0 puntos.
  2. sin inversiones: min(emparejados) > max(no-emparejados).
Si PASA -> el arbitro zero-shot sirve; NO hace falta entrenar un LoRA (y menos un
QLoRA, que en la 5060 Ti no fue el camino). Si NO pasa -> recien ahi se considera
alinear el arbitro, habiendo medido el gap primero.

LIMITE HONESTO: esto mide DISCRIMINACION (ranking), no la calibracion absoluta de
la nota (que tiene ~±1.5 de varianza en un VLM de 3B a temperatura; el gate de
fidelidad del lazo + el disyuntor la absorben). No mide "gusto humano": para eso
haria falta un set etiquetado por el dueno.

Uso:  COGNIA_VLM_URL=http://127.0.0.1:8081 venv312\Scripts\python.exe scripts\gate_arbitro_visual.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Correr desde scripts/ sin instalar el paquete: la raiz del repo al path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.program_creator.arbitro_visual import arbitrar_visual, vlm_disponible

D = Path.home() / "Desktop"

# Imagenes reales del escritorio, por categoria. Se eligen las que existan.
CATEGORIAS = {
    "dashboard": ["dashboard-cognia.png", "md_render.png", "rag1.png"],
    "juego":     ["f4_juego.png", "f5_anim_a.png"],
    "jarvis":    ["jarvis_orbes.png", "jarvis3d_a.png"],
    "grafo":     ["grafo_claro.png"],
}


def _existentes():
    out = {}
    for cat, nombres in CATEGORIAS.items():
        rutas = [str(D / n) for n in nombres if (D / n).exists()]
        if rutas:
            out[cat] = rutas
    return out


def _nota(idea, real, objetivo):
    r = arbitrar_visual(idea, screenshot=real, mockup=objetivo)
    return None if r is None else r.get("nota")


def main() -> int:
    ok, motivo = vlm_disponible()
    if not ok:
        print(f"[gate] No hay VLM vivo: {motivo}\n"
              f"       Arranca:  python scripts/servir_vlm.py", file=sys.stderr)
        return 2

    cats = _existentes()
    if len(cats) < 2:
        print("[gate] Faltan imagenes de al menos 2 categorias en el escritorio.",
              file=sys.stderr)
        return 2

    print("=== GATE arbitro visual (zero-shot) ===\n")

    emparejados, no_emparejados = [], []

    # Emparejados: cada imagen contra SI MISMA (fidelidad maxima esperada).
    print("EMPAREJADOS (imagen vs si misma):")
    for cat, rutas in cats.items():
        for r in rutas:
            n = _nota(cat, r, r)
            if n is not None:
                emparejados.append(n)
                print(f"  {n:4.1f}  {Path(r).name}  vs  (misma)")

    # No-emparejados: primera imagen de cada categoria vs primera de OTRA.
    print("\nNO-EMPAREJADOS (categorias distintas):")
    llaves = list(cats.keys())
    for i, ca in enumerate(llaves):
        for cb in llaves[i + 1:]:
            ra, rb = cats[ca][0], cats[cb][0]
            n = _nota(ca, rb, ra)   # objetivo=cat A, real=cat B (distinta)
            if n is not None:
                no_emparejados.append(n)
                print(f"  {n:4.1f}  objetivo={ca:9s} real={Path(rb).name}")

    if not emparejados or not no_emparejados:
        print("\n[gate] No se pudieron computar ambas clases.", file=sys.stderr)
        return 2

    m_emp = sum(emparejados) / len(emparejados)
    m_no  = sum(no_emparejados) / len(no_emparejados)
    separacion = m_emp - m_no
    min_emp, max_no = min(emparejados), max(no_emparejados)
    sin_inversion = min_emp > max_no

    print("\n--- Resultado ---")
    print(f"media emparejados   : {m_emp:.2f}  (n={len(emparejados)})")
    print(f"media no-emparejados: {m_no:.2f}  (n={len(no_emparejados)})")
    print(f"separacion          : {separacion:.2f}  (gate: >= 3.0)")
    print(f"min(emp)={min_emp:.1f}  max(no-emp)={max_no:.1f}  "
          f"sin inversion: {sin_inversion}  (gate: True)")

    pasa = separacion >= 3.0 and sin_inversion
    print(f"\nGATE: {'PASA ✅' if pasa else 'KILL ❌'}")
    if pasa:
        print("El arbitro zero-shot discrimina: NO hace falta entrenar un LoRA.")
    else:
        print("No discrimina lo suficiente: medir el gap y considerar alinear "
              "el arbitro (LoRA, NO QLoRA) — nunca antes de esta medida.")
    return 0 if pasa else 1


if __name__ == "__main__":
    sys.exit(main())
