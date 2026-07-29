# PREREG — Gate de confirmación del modo BoN cableado (K=4 + selector held-out)

**Fecha:** 2026-07-28 ~22:20, nocturna 28→29 (segunda noche). **Escrito ANTES
de correr.** La arquitectura BoN+señal ya quedó VALIDADA como experimento
(PREREG_BON_HELDOUT: techo +7, selector captura todo). Esto NO re-litiga esa
pregunta: mide que el CABLEADO de producción (`cognia/program_creator/bon.py`,
modo env-gated COGNIA_BON_K/COGNIA_BON_SELECTOR, commit de esta noche)
reproduce el efecto de punta a punta. Es un A/B de confirmación de ingeniería.

## Qué cambia respecto del experimento validado (declarado, no escondido)

1. El runner llama a `bon.construir_bon` (el módulo de producción que usará
   /construir), no al harness de investigación. El selector interno del modo
   es el mismo criterio que capturó el 100% del margen (aprobado held-out >
   checks held-out > s menor).
2. **Sin fallback a create_program dentro de las muestras:** construir_bon
   corre construir_para_mockup puro; una réplica que no produce HTML cuenta
   como muestra reprobada (en el experimento, 12/96 muestras llegaron por el
   fallback del harness). Es una propiedad real del modo cableado: se mide
   como es.
3. **Sin semillas por muestra:** producción no re-semilla; la diversidad
   viene del estado aleatorio natural entre réplicas (misma fuente: rehacer
   el pipeline entero).

## Diseño

- Banco brutal (4 tareas), R=6 réplicas, K=4, tareas ROTADAS por réplica
  (intercalado a nivel tarea). 24 ensayos objetivo, 96 generaciones.
- Por ensayo: `bon.construir_bon(idea, k=4, contrato_selector=held_out,
  guardar_muestras=dir, llm=None, usar_mockup_imagen=False, verbose=False)`.
  El modo juzga cada muestra con el held-out (queda en `res.bon`); el runner
  juzga cada muestra guardada con el contrato ORIGINAL. estricto(muestra) =
  original ∧ held-out. No se re-juzga el held-out (se lee del meta del modo:
  mismo juez, mismo commit, cero duplicación).
- **Control = muestra s=1 del propio ensayo** (mismo reloj, misma corrida —
  el diseño intra-ensayo del experimento validado). **Resultado del modo =
  estricto de la muestra ELEGIDA por el modo.**
- Infra (mismas reglas que PREREG_BON_HELDOUT + 1ª enmienda): EXCEPCIÓN del
  harness, juez crasheado, backend degradado/≠8080 → infra; "sin HTML" con
  backend sano = reprobado legítimo. Fallback de Ollama neutralizado (módulo
  + env). Ensayos incompletos fuera del apareado.
- Guardado incremental POR ENSAYO + `--reanudar` (+ `--acepta-commit` con la
  misma regla de siempre); corrida DESACOPLADA.
- **Presupuesto de pared duro por ensayo** (K × COGNIA_PRESUPUESTO_CELDA,
  default 20 min/celda, `cognia/presupuesto_pared.py`): el goteo lento de
  tokens no dispara el timeout por chunk (celda >45 min en b2_ab_gap);
  el desborde cae como EXCEPCIÓN → infra, pre-declarado.

## Métricas y umbrales (fijados ahora; 24 ensayos objetivo)

- **B — neto del modo** (elegida estricta vs control s1, resta apareada):

| B | veredicto |
|---|---|
| ≥ +4 | **CONFIRMADO**: el cableado reproduce el efecto; el modo queda listo para gates |
| +2..+3 | GRIS: el modo funciona pero el efecto llegó recortado — investigar el recorte (p. ej. el no-fallback) antes de usarlo en gates |
| ≤ +1 | NO CONFIRMA: bug de cableado o el efecto no transfiere — el modo NO se usa hasta diagnosticar |

- Secundarias (se reportan, no deciden): A techo pass@4 y pérdida C = A−B
  (sanidad del selector: C ≤ 1 esperado); nº de muestras sin HTML (mide el
  coste real del no-fallback); FP del original (D, actualiza memoria);
  composición de elegidas por s.
- Cortes parciales: veredicto con ensayos COMPLETOS; R<3 completas = solo
  direccional (regla de siempre).
- Presupuesto: 96 gens × ~85 s + 96 juzgados originales × ~12 s + 96
  held-out internos × ~12 s ≈ 3.0–3.4 h. Si el reloj de la sesión corta,
  `--solo-resumen` lee el parcial.

## Revisión

Revisión adversarial (1 agente, lente implementación+diseño) del prereg +
runner + bon.py ANTES de encender la flota. Los tests unitarios de bon.py
(10, sin GPU) ya están en verde.
