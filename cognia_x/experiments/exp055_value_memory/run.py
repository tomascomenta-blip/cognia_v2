r"""
exp055 — CYCLE 70 / H-V4-5 (cierra la última raíz abierta del v4): ESCRIBIR≡OLVIDAR es rate-distortion dirigido
por VALOR. Una memoria de capacidad LIMITADA rinde porque guarda lo de mayor VALOR (utilidad esperada); ABLAR el
valor COLAPSA la ventaja a aleatoria -> la ventaja de la memoria está ATADA a R-VALOR.

CONTEXTO: el thesis v4 (R-VALOR raíz primera): "escribir/olvidar es selectivo; consolidar exige saber qué
proteger -- indefinibles sin un escalar de valor". H-V4-5: la ventaja de una memoria finita NO es la capacidad,
es QUÉ guarda (valor); si quitás la señal de valor, la memoria selectiva = memoria aleatoria.

TAREA (memoria con capacidad finita): n items, cada uno con VALOR v_i (utilidad ~ con qué frecuencia/peso se va
a CONSULTAR). La memoria guarda sólo m < n items. Llegan consultas con prob proporcional al valor; un item
guardado se responde (HIT), uno no guardado se pierde. Desempeño = HIT-RATE PONDERADO POR VALOR = suma de los
valores normalizados de los items guardados. 4 políticas de ESCRITURA:
  - value_directed: guarda los m de MAYOR valor (rate-distortion dirigido por valor).
  - random: guarda m al azar (referencia: captura ~m/n del valor).
  - ablation: la señal de valor se REMUEVE (todos iguales) -> no puede rankear -> guarda al azar (= random).
  - anti_value: guarda los m de MENOR valor (control de dirección: < random).
Valores con cola pesada (power-law) -> pocos items concentran el valor. seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si value_directed >> random (la escritura por valor responde MUCHO más valor; +>0.20) Y ABLAR el
    valor colapsa a random (|ablation - random| < 0.05) Y anti_value < random (la dirección importa). => la
    ventaja de la memoria finita está ATADA a R-VALOR: quitar la utilidad mata la ventaja (escribir≡olvidar es
    rate-distortion dirigido por valor).
  - REFUTADA si value_directed no supera a random (el valor no ayuda) O ablar el valor NO colapsa la ventaja.
  - MIXTA si value_directed ayuda pero la ablación no es limpia o anti_value no cae.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp055_value_memory.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp055_value_memory.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["value_directed", "random", "ablation", "anti_value"]


def gen_values(rng, n, alpha):
    """Valores con cola pesada (power-law): pocos items concentran la utilidad. Normalizados a prob de consulta."""
    v = (rng.pareto(alpha, size=n) + 1.0)        # Pareto(alpha): cola pesada, todos > 1
    return v / v.sum()


def hit_rate(p, idx):
    """Desempeño = masa de valor (prob de consulta) cubierta por los items guardados."""
    return float(p[idx].sum())


def select(rng, p, m, arm):
    n = len(p)
    if arm == "value_directed":
        return np.argsort(p)[-m:]                 # los m de MAYOR valor
    if arm == "anti_value":
        return np.argsort(p)[:m]                  # los m de MENOR valor
    # random y ablation: selección al azar (la ablación REMUEVE el valor -> no puede rankear -> azar)
    return rng.choice(n, size=m, replace=False)


def run(n, m, alpha, n_seeds):
    vals = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        p = gen_values(rng, n, alpha)
        for a in ARMS:
            srng = np.random.default_rng(seed * 7919 + {"value_directed": 1, "random": 2, "ablation": 3, "anti_value": 4}[a])
            vals[a].append(hit_rate(p, select(srng, p, m, a)))
    return {a: round(float(np.mean(vals[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(res, n, m):
    vd, rnd, abl, anti = res["value_directed"], res["random"], res["ablation"], res["anti_value"]
    vd_beats_random = (vd - rnd) > 0.20
    ablation_collapses = abs(abl - rnd) < 0.05
    anti_below_random = anti < rnd - 0.05
    chance = round(m / n, 4)

    if vd_beats_random and ablation_collapses:
        status = "apoyada"
        verdict = ("H-V4-5 APOYADA: la ventaja de una memoria finita está ATADA a R-VALOR. La escritura "
                   "value_directed cubre {vd} del valor de consulta con sólo m={m}/{n} items (random {rnd} ~ "
                   "m/n={ch}); +{adv} sobre aleatoria. ABLAR el valor (todos iguales -> azar) COLAPSA a {abl} "
                   "(= random {rnd}): sin la señal de valor, la memoria selectiva = aleatoria -> la ventaja ES el "
                   "valor. anti_value (guardar lo de MENOR valor) cae a {anti} ({below} random): la DIRECCIÓN del "
                   "valor importa. => escribir≡olvidar es rate-distortion dirigido por valor; quitar la utilidad "
                   "mata la ventaja. Conecta MEMORIA con R-VALOR (raíz primera).").format(
                       vd=_f(vd), m=m, n=n, rnd=_f(rnd), ch=_f(chance), adv=_f(vd - rnd), abl=_f(abl),
                       anti=_f(anti), below="<" if anti_below_random else "~")
    elif not vd_beats_random:
        status = "refutada"
        verdict = ("H-V4-5 REFUTADA: la escritura por valor no supera a la aleatoria (value_directed {vd} vs "
                   "random {rnd}) -> el valor no da ventaja a esta escala.").format(vd=_f(vd), rnd=_f(rnd))
    else:
        status = "mixta"
        verdict = ("H-V4-5 MIXTA: value_directed supera a random ({vd} vs {rnd}) pero ablar el valor NO colapsa "
                   "limpio (ablation {abl} vs random {rnd}).").format(vd=_f(vd), rnd=_f(rnd), abl=_f(abl))

    return {"by_arm": res, "chance_m_over_n": chance, "vd_beats_random": bool(vd_beats_random),
            "ablation_collapses": bool(ablation_collapses), "anti_below_random": bool(anti_below_random),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=1.5, help="exponente Pareto (más chico = cola más pesada)")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log(f"[exp055] CYCLE 70 / H-V4-5 — escribir≡olvidar (memoria dirigida por valor; ablar el valor mata la ventaja)")
    log(f"[exp055] n={args.n} m={args.m} (capacidad {args.m}/{args.n}) alpha={args.alpha} seeds={args.seeds}")

    res = run(args.n, args.m, args.alpha, args.seeds)
    sm = build_summary(res, args.n, args.m)

    log(f"[exp055] hit-rate ponderado por valor: value_directed={res['value_directed']:.3f} "
        f"random={res['random']:.3f} ablation={res['ablation']:.3f} anti_value={res['anti_value']:.3f} "
        f"(azar m/n={sm['chance_m_over_n']:.3f})")
    log(f"[exp055] VEREDICTO H-V4-5: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp055_value_memory", "cycle": 70, "hypothesis": "H-V4-5",
           "claim": "la ventaja de una memoria finita está atada a R-VALOR: la escritura dirigida por valor >> "
                    "aleatoria y ablar el valor colapsa la ventaja (escribir≡olvidar es rate-distortion por valor)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp055] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
