# exp049 — RESULTADO: alternativas a backprop, medidas de verdad (TAREA 2)

**Fecha:** 2026-07-01 · **Hardware:** i3-10110U CPU (torch 2.12.0+cpu, 3 threads) ·
**Protocolo:** el pre-registrado en README.md (MNIST 60k/10k, MLP 784→256→128→64→32→10 donde aplica,
5 epochs, batch 64, seeds 42/7/123, decide el MIN ratio, umbral 0.95 = precedente SDPC E1) ·
**Datos crudos:** `results/results.json`

## Tabla de veredictos

| método | acc (mean / min) | ratio vs BP | costo wall | veredicto |
|---|---|---|---|---|
| **bp** (baseline) | 0.9746 / 0.9724 | 1.000 | 1.00× (21.9s) | — |
| **pc** (predictive coding) | 0.9706 / 0.9678 | **0.993** | 4.26× | **PASS — empata calidad** |
| **eqprop** | 0.9608 / 0.9602 | **0.985** | 4.94× | **PASS** (topología propia 784-256-10) |
| **dfa** | 0.9431 / 0.9385 | **0.963** | **1.17×** | **PASS — la alternativa BARATA** |
| **dtp** | 0.9356 / 0.9286 | 0.953 | 2.32× | PASS (justo) |
| ff (forward-forward) | 0.9228 / 0.9204 | 0.944 | 2.23× | NO CRUZA 0.95 (no descartado: >0.80) |
| es (OpenAI-ES) | 0.4909 / 0.4713 | 0.484 | 3× (budget) | **DESCARTADO** (<0.80) |

## Qué queda (con evidencia)

1. **La brecha de calidad de las reglas locales es chica en este régimen.** 4 de 6 alternativas
   cruzan el 95% de BP con el MIN de 3 seeds. PC prácticamente empata (99.3%).
2. **El costo real refuta la cifra heredada.** El repo tenía anotado (H-BIO-3, de literatura, sin
   medir) "PC ~100× el costo de backprop". Medido acá: **4.26×** (T=16 pasos de inferencia,
   vectorizado por batch, updates locales con Adam). La cifra de literatura asumía implementaciones
   no vectorizadas / hasta converger a equilibrio. H-BIO-3 actualizada en `manager/hypotheses.md`.
3. **DFA es la alternativa costo-competitiva**: 96.3% de BP a 1.17× — sin transporte de pesos ni
   backward global. PERO es frágil: el DFA de libro (salida He-init, lr parejo) **colapsa a 0.054**
   (bajo azar); necesitó salida-en-cero + B ortonormales (mismo síntoma que el SDPC del repo).
4. **Por qué domina backprop, visto desde los datos**: nadie le gana en costo (todas las
   alternativas pagan 1.17–4.94× wall para igual o menor calidad), varias son frágiles a la init o
   a hiperparámetros (DFA, DTP), y las que empatan calidad (PC, EqProp) pagan el costo de la
   inferencia iterativa. La ventaja de backprop no es mágica: es que computa el crédito exacto en
   UNA pasada. Las locales compran otras propiedades (paralelismo por capa, sin transporte de
   pesos, hardware alternativo) que en CPU/GPU convencional no se monetizan.

## Descartado / no cruzó

- **ES a esta escala: DESCARTADO** (0.48 con 3× el wall de BP, 244k params, N=30 antitético,
  σ=0.02). El gradiente estimado por 30 direcciones en R^244522 no alcanza. (ES sigue siendo válido
  donde no hay gradiente — RL, prompts — pero NO para entrenar pesos de esta escala.)
- **FF no cruza 0.95** (0.944 a 2.23×). La variante ancha 784-500-500 (extra) da 0.930 — a 5 epochs
  la angosta la alcanza; la preferencia por capas anchas se nota en epoch 1 (0.51 vs 0.42). Sin
  descarte formal (>0.80), pero sin razón medida para elegirla sobre DFA (mejor y más barata).

## Límites honestos (no extrapolar)

- Régimen: MLP ~270k params, MNIST, CPU. **Nada de esto habla de LMs a escala** — ahí el costo
  relativo puede cambiar (PC/EqProp iteran T veces por batch sobre TODO el modelo).
- PC usa W^T en la inferencia (transporte de pesos simétrico): elimina el backward global, no la
  simetría. EqProp y DFA sí evitan el transporte.
- Un (1) pase de tuning documentado se usó en dfa/pc/dtp (permitido por protocolo, precedente
  SDPC); ff/eqprop/es pasaron sin tuning.
- Walls medidos en máquina compartida (±ruido chico); el ORDEN de costos es robusto.
- El costo de SDPC (gap explícito del repo) queda cubierto por proxy: DFA con Adam local = 1.17×.

## Relación con lo previo del repo

- SDPC E1 (DFA con capa de "culpa"): calidad 0.978-0.983 — consistente con nuestro DFA 0.963
  (implementación distinta, mismo orden). Su costo, nunca medido, ahora tiene referencia: ~1.2×.
- `manager/decomposition_tree.md` podó la rama "learning-rules locales" por H-BIO-3; con las
  cifras corregidas, la poda por COSTO sigue siendo válida (nadie gana a BP), pero la poda por
  "100× prohibitivo" era exagerada 20×.
