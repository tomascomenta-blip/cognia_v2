# Pre-registro GATE del especialista 7B (MoM fase 4)

CONGELADO ANTES DE MEDIR (2026-07-10). Decide si el escalado reactivo 3B→7B en
`generar_codigo` se PROMUEVE (flip `COGNIA_HEAVY_CODE` default→ON) o queda
detrás del kill-switch (negativa honesta).

## Diseño (congelado)

- **Suite**: `tasks_hard_v2.jsonl`, N=40, sha256 `0a69050f…` (SUITES_FROZEN.json).
  Tests OCULTOS = la métrica real de pass@1.
- **Mecanismo**: `benchmark_code --tasks-file tasks_hard_v2.jsonl --cascade 7b
  --seed 42` — GREEDY (sin BoN), determinista, cache_prompt=false. Etapa 1 = 3B
  (brazo A). Etapa 2 = reintenta en el 7B las que A falla (brazo B, cascada
  reactiva). Un run da A y B PAREADOS (recovered_cascade = b, c por construcción
  ≈0). Greedy aísla el efecto PURO del 7B bajo el MISMO protocolo con que se
  midió el 60% previo; el BoN de producción es una palanca ortogonal encima.
- **Matar llama-server entre etapas** lo maneja `swap_server_model` (para el 3B
  antes de cargar el 7B).

## Predicciones / gates (no ajustar post-hoc)

- **P-7B-1 (gate primario)**: recuperaciones `b = recovered_cascade ≥ 6` con
  `c = 0` (ninguna que A resolvía se rompe). b≥6/c=0 ⇒ McNemar exacto p≤0.031
  < 0.05. Con N=40 y tasa de recuperación ~20% esperada (~8), es alcanzable.
- **P-7B-2 (no-regresión dura, OBLIGATORIA)**: `c = 0` estricto. Si `c>0` (el
  7B rompe una que el 3B pasaba), REFUTAR — la cascada reactiva no debe poder
  empeorar (solo reintenta lo ya fallado). c>0 sería un bug del mecanismo.
- **P-7B-3 (velocidad en fáciles)**: en un subset FÁCIL (dif<0.30), el 7B se
  invoca 0 veces (el disparador reactivo solo dispara donde el 3B falla, y en
  producción el pre-filtro de dificultad además lo veta). Se verifica con el
  test unitario ya verde + el conteo de escalados en el gate.
- **P-7B-4 (RAM)**: peak RSS con 3B+7B (peor caso de coexistencia en el swap)
  medido; compuerta informativa < 10GB en el i3 de 12GB. En producción el
  modo lazy-load-usar-cerrar mantiene RAM steady-state 0.

## Decisión

- **PROMOVER** (flip `COGNIA_HEAVY_CODE` default→ON) SOLO si P-7B-1 ✓ y
  P-7B-2 ✓. Verificación e2e real de `/hacer` con una tarea dura mostrando el
  escalado y el entregable que el 3B solo no producía.
- **NO promover** si b<6 o c>0: dejar el 7B detrás del kill-switch (default OFF)
  y documentar la negativa con su output — coherente con las negativas
  pre-registradas del programa. NO inflar el número.

## Qué NO afirma este gate

- No mide el flujo de producción con BoN (palanca ortogonal, ya medida
  +15.6pp). El gate aísla el efecto del 7B en greedy.
- El proxy tests-visibles vs ocultos (producción dispara por visibles) puede
  perder recuperaciones; se cuantifica en un smoke aparte (B-deploy) si el
  tiempo lo permite, sin bloquear el veredicto primario.
