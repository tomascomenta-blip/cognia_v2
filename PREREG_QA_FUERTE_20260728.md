# PREREG — QA más fuerte: ¿otro pensador rompe el techo del contrato interno?

**Fecha:** 2026-07-28, sesión nocturna 28→29. **Escrito ANTES de correr.**
**Vía que prueba:** la única alternativa viva que dejaron los tres KILL del
contrato autogenerado (memoria contrato-interno-al-azar): "held-out A MANO
**o un modelo más fuerte para el rol QA**". Los held-outs a mano ya existen
(brutal + fácil); esto mide la mitad "modelo más fuerte".

## Hipótesis y prior

- El techo medido es del PENSADOR (gpt-oss-20b): conserva sus propias
  invenciones aunque un filtro se las señale (FN 15/19; aciertos 8–10/24 en
  el corpus de la sonda; 3 KILL convergentes de prompt-engineering).
- Candidato QA: **OpenReasoning-Nemotron-14B** (Q4_K_M, ya instalado;
  especializado en razonamiento — el rol QA es razonar consecuencias, no
  escribir HTML). NO se toca el prompt: mismo modo `clasico`, mismo
  `b2_ab_contrato.py`, solo cambia el modelo servido en :8080.

## Diseño (corpus CONGELADO, cero generación de páginas)

- Corpus: las 24 páginas de b2_sonda_prompt con veredicto del banco ya
  registrado (19 aprobadas / 5 reprobadas — el FP se mide /5, límite
  conocido). Las mismas ejes que nocturna 27: FP, FN, aciertos /24.
- **Bloque G (control de deriva, primero, sin swap):** con gpt-oss-20b aún
  servido tras la corrida BoN, `b2_ab_contrato.py --modos clasico
  --etiqueta gposs_ctrl28`. Re-mide el baseline ESTA noche.
- **Bloque N:** swap a Nemotron (`servir_modelo.py --modelo OpenReasoning`),
  humo de 1 página (¿el JSON del contrato se extrae del output con
  razonamiento?; arreglos de plomería de parseo están permitidos y se
  documentan — no tocan el camino de gpt-oss), luego `--modos clasico
  --etiqueta nemotron14b` sobre el corpus completo.
- Bloques secuenciales (no se pueden servir dos 14B a la vez): la lectura
  usa umbrales ABSOLUTOS + el control G para acotar deriva, no una resta
  G−N pura (gate-e2e-flaky).

## Umbrales (fijados ahora)

| lectura | condición | veredicto |
|---|---|---|
| control G | aciertos fuera de [5,13]/24 | DERIVA ALTA: todo lo demás solo direccional |
| Nemotron | aciertos ≥ 17/24 ∧ FN ≤ 5/19 ∧ FP ≤ 2/5 | SEÑAL ÚTIL (vía QA-fuerte VIVA) |
| Nemotron | FN ≤ 4/19 ∧ FP ≤ 1/5 | PASA FUERTE: candidato a selector de BoN |
| Nemotron | aciertos ≤ 13/24 ∨ FN ≥ 8/19 | KILL: el techo no era solo del pensador chico |
| medio | resto | GRIS: se reporta, sin adopción |

- El juez (Playwright) es el mismo binario/commit en ambos bloques; el commit
  se registra en la config de cada corrida.
- Si SEÑAL ÚTIL y queda reloj: stretch direccional pre-declarado — generar
  contratos Nemotron para un subconjunto (~24) de las muestras GUARDADAS de
  la corrida BoN de esta noche y medir cuánto del techo A captura un selector
  Nemotron (sin GPU de páginas; solo contratos + replay). Sin umbral de
  adopción: alimenta el diseño del selector de producción de la próxima
  sesión.
- Nada de este prereg adopta código de producción esta noche.
