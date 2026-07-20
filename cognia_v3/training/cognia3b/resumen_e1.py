"""Cierre de E1: aplica la REGLA PRE-REGISTRADA sobre e1_results.json.

Regla (TEORIA Parte 7 s7.2 + kernel E1): entre los brazos que PASAN
G1 (no-regresion: delta >= -4pp y sin regresion significativa McNemar) +
G3 (identidad >= 18/20) + G5 (espanol: acc >= base - 4pp), gana el de mayor
correct_tool en tooluse; empate -> mayor tok/s de training.
Tambien falsa las predicciones P-E1a..d del docstring del kernel.

Correr: .\\venv312\\Scripts\\python.exe cognia_v3\\training\\cognia3b\\resumen_e1.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# default E1; pasar otro JSON como argv[1] (p.ej. results_e1b/e1b_results.json,
# que trae la MISMA estructura de evals/veredictos; "train" viene de E1)
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "results_e1", "e1_results.json")
TRAIN_PATH = os.path.join(HERE, "results_e1", "e1_results.json")


def acc(items: dict) -> float:
    return sum(items.values()) / len(items) if items else 0.0


def main():
    with open(PATH, encoding="utf-8") as f:
        R = json.load(f)
    if not R.get("train") and os.path.exists(TRAIN_PATH) and PATH != TRAIN_PATH:
        with open(TRAIN_PATH, encoding="utf-8") as f:
            R["train"] = json.load(f).get("train", {})  # tok/s vienen de E1
    print(f"E1 {R.get('started_utc')} | suites_hash_ok={R.get('suites_hash_ok')} "
          f"| wall={R.get('wall_total_min')} min")
    print("\n== TRAIN ==")
    for arm, t in R.get("train", {}).items():
        print(f"  {arm:12s} {json.dumps(t, ensure_ascii=False)[:150]}")

    base = R["evals"].get("base", {}).get("items", {})
    if not base:
        print("SIN EVAL BASE — kernel incompleto")
        return 1
    print(f"\n== BASE ==  g1={acc(base.get('g1', {})):.1%} g3={acc(base.get('g3', {})):.1%} "
          f"g5={acc(base.get('g5', {})):.1%} tooluse={acc(base.get('tooluse', {})):.0%}")

    print("\n== BRAZOS (gates canonicos) ==")
    candidatos = []
    for arm, ver in R.get("veredictos", {}).items():
        g1, g3, g5 = ver.get("g1", {}), ver.get("g3", {}), ver.get("g5", {})
        tu = ver.get("tooluse", {})
        pasa_g1 = (g1.get("delta_pp", -99) >= -4 and
                   not (g1.get("p", 1) < 0.05 and g1.get("delta_pp", 0) < 0))
        pasa_g3 = g3.get("acc_brazo", 0) >= 0.9
        pasa_g5 = g5.get("acc_brazo", 0) >= g5.get("acc_base", 1) - 0.04
        pasa = pasa_g1 and pasa_g3 and pasa_g5
        tok_s = (R["train"].get(arm) or {}).get("tok_s_util", 0)
        print(f"  {arm:12s} G1 {g1.get('delta_pp', '?'):>6}pp p={g1.get('p', '?'):<7} "
              f"[{'PASA' if pasa_g1 else 'FALLA'}] | G3 {g3.get('acc_brazo', 0):.0%} "
              f"[{'PASA' if pasa_g3 else 'FALLA'}] | G5 {g5.get('acc_brazo', 0):.0%} "
              f"[{'PASA' if pasa_g5 else 'FALLA'}] | tooluse "
              f"{tu.get('acc_brazo', 0):.0%} (base {tu.get('acc_base', 0):.0%}) "
              f"| {tok_s} tok/s | {'CANDIDATO' if pasa else 'descartado'}")
        if pasa:
            candidatos.append((tu.get("acc_brazo", 0), tok_s, arm))

    print("\n== PREDICCIONES ==")
    v = R.get("veredictos", {})
    tr = R.get("train", {})
    tu_a = (v.get("u_r16_all", {}).get("tooluse", {}) or {}).get("acc_brazo")
    tu_b = (v.get("u_r8_qkvo", {}).get("tooluse", {}) or {}).get("acc_brazo")
    if tu_a is not None and tu_b is not None:
        print(f"  P-E1a (r16_all > r8_qkvo en tooluse): {tu_a:.0%} vs {tu_b:.0%} "
              f"-> {'CONFIRMADA (direccional)' if tu_a > tu_b else 'REFUTADA'}")
    tok_dora = (tr.get("t_dora_r16") or {}).get("tok_s_util")
    tok_t16 = (tr.get("t_r16_all") or {}).get("tok_s_util")
    if tok_dora and tok_t16:
        costo = 1 - tok_dora / tok_t16
        print(f"  P-E1b (DoRA cuesta >=15% tok/s): costo {costo:.0%} vs t_r16_all "
              f"-> {'CONFIRMADA' if costo >= 0.15 else 'REFUTADA'}")
    l_u = (tr.get("u_r16_all") or {}).get("loss_fin")
    l_t = (tr.get("t_r16_all") or {}).get("loss_fin")
    if l_u and l_t:
        d = abs(l_u - l_t) / l_t
        print(f"  P-E1d (loss unsloth vs transformers +-1%): {l_u} vs {l_t} "
              f"({d:.1%}) -> {'EQUIVALENTES' if d <= 0.01 else 'DIVERGEN (revisar)'}"
              " [nota: mb distinto 8 vs 4, comparacion aproximada]")

    if candidatos:
        candidatos.sort(reverse=True)
        print(f"\n>>> METODO COLUMNA (regla pre-registrada): {candidatos[0][2]} "
              f"(tooluse {candidatos[0][0]:.0%}, {candidatos[0][1]} tok/s)")
    else:
        print("\n>>> NINGUN brazo paso G1+G3+G5 — rama de fallo pre-registrada: "
              "revisar lr/epochs (arbol de decision, Parte 7)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
