# exp049 — Alternativas a backpropagation, medidas de verdad (TAREA 2)

## Pregunta
¿Por qué backprop domina? ¿Alguna alternativa (forward-forward, predictive coding, target prop,
equilibrium prop, DFA, evolución) se le acerca en CALIDAD sin pagar un COSTO prohibitivo?
El repo solo tenía SDPC/DFA medido en calidad (SOLID PASS 0.978-0.983 vs BP) pero **el costo nunca
se midió** (memoria `sdpc-e1-verdict`). Las cifras "PC ~100×, FF ~2×" de `cognia_x/manager/hypotheses.md`
H-BIO-3 son de literatura, no medidas acá. Este experimento mide AMBAS cosas en un harness común.

## Protocolo (pre-registrado, antes de correr)
- Dataset: MNIST (60k/10k), normalización estándar (0.1307/0.3081), flatten 784.
- Arquitectura común (donde aplique): MLP 784→256→128→64→32→10 ReLU (idéntica al veredicto SDPC E1,
  para comparabilidad). Desviaciones por método se documentan en el módulo (EqProp usa su propia
  topología porque el settling multi-capa no converge; FF corre también una variante 784→500→500
  porque el método fue diseñado para capas anchas).
- Presupuesto: 5 epochs, batch 64 (= SDPC E1). ES no tiene "epochs" comparables → presupuesto de
  wall-clock = 3× el wall de BP en la misma máquina, reportando lo alcanzado.
- Seeds: 42, 7, 123. Decide el MIN ratio (precedente SDPC E1 solid).
- Métricas: (a) CALIDAD = test_acc final y ratio vs BP; (b) COSTO = wall-clock total mismo hardware,
  #updates, y desglose por época. Ambas de primera clase.
- Umbral (mismo que SDPC E1): ratio ≥ 0.95 = PASS de calidad. DESCARTE si ratio < 0.80 tras un (1)
  intento documentado de tuning, o si el costo > 20× BP sin ventaja de calidad.
- Un (1) pase de tuning permitido por método si falla el primer intento (precedente: SDPC necesitó
  He-init + Adam local), documentando qué se tocó.

## Métodos
| módulo | método | regla de crédito |
|---|---|---|
| methods/bp.py | Backprop (Adam) | gradiente exacto (baseline) |
| methods/dfa.py | Direct Feedback Alignment | feedback aleatorio fijo B_l (sin transporte de pesos) |
| methods/ff.py | Forward-Forward (Hinton 2022) | goodness local por capa, pos vs neg |
| methods/pc.py | Predictive coding (inference learning) | inferencia iterativa + updates locales |
| methods/dtp.py | Difference Target Propagation | inversas aprendidas propagan targets |
| methods/eqprop.py | Equilibrium Propagation | dos fases (free/nudged) sobre energía |
| methods/es.py | OpenAI-ES antitético | perturbaciones + fitness (sin gradiente) |

## Contrato de cada módulo
`train(data, cfg, seed, log) -> {"test_acc": float, "epoch_log": [...], "wall_s": float,
"updates": int, "extra": {...}}` — data = (x_train, y_train, x_test, y_test) ya en device.
Sin estado global; torch.manual_seed(seed) adentro; nada de autograd END-TO-END salvo bp.py
(autograd LOCAL por capa está permitido donde la regla es local — es cómputo local legítimo).

## Correr
```
venv312\Scripts\python.exe -m cognia_x.experiments.exp049_learning_rules.run_bench --smoke
venv312\Scripts\python.exe -m cognia_x.experiments.exp049_learning_rules.run_bench          # full local
```
Resultados → `results/results.json` (incremental, sobrevive cortes).
