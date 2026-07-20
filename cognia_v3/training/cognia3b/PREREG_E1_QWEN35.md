# PREREG — E1: Qwen3.5-4B no-think como cerebro de código (COLONIA)

**CONGELADO ANTES DE CORRER (2026-07-12, corrida COLONIA→CASI-GRANDE).**

## Hipótesis
Qwen3.5-4B (feb-2026, LCB v6 55.8 verificado en card) trae CAPACIDAD CRUDA
de una generación nueva — la única palanca no cerrada del programa (las 6
negativas cerraron fine-tune y scaling INTRA-familia 2024). Si en el
protocolo RAW supera al 3B, se convierte en generador del BoN / cerebro de
código de la colonia. Calibración medida: prefill `<think>\n\n</think>\n\n`
en el turno del asistente elimina el thinking (5s vs 26s+, output limpio).

## Método
- Suite congelada `tasks_hard_v2.jsonl` N=40 (misma del gate 7B), tests
  OCULTOS, protocolo RAW: greedy, max_tokens 640, cache_prompt=false,
  prompt del gate (SYSTEM_PROMPT + build_prompt) + prefill no-think.
- Server: fleet_registry qwen35_4b (:8097, b9391). Persistencia incremental.
- Comparables ya medidos (mismo protocolo): 3B RAW 15/40 (37.5%),
  cascada 3B→7B 23/40 (57.5%), referencia GLM 5.2 ~50% (~20/40).

## Gates (congelados)
- **E1-KILL**: ≥ 16/40 (supera al 3B RAW) → la línea sigue (E2 cross-family
  BoN, adapter ACCION/identidad en Kaggle si toma rol de agente).
- **E1-MAYOR (info)**: ≥ 21/40 = supera la referencia GLM 5.2 en el eje
  con UN modelo de 2.7GB → cerebro de código de la colonia.
- **E1-LAT (info)**: segundos/tarea (a 4.5 tok/s el costo real del 4B).

## Regla de corte
< 16/40 → línea cerrada (7ª negativa: la generación 2026 tampoco mueve el
eje en este hardware), documentar y seguir con E2/E3 sin este modelo.
