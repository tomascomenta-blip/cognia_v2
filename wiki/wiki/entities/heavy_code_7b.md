---
title: Heavy Code 7B — especialista de capacidad (:8092)
type: entity
tags: [7b, heavy-code, cascada, mom, capacidad]
updated: 2026-07-16
---

# Heavy Code 7B

→ [[index]]

## Que es

`node/heavy_code.py` — Qwen2.5-Coder-7B Q4_K_M, el unico especialista de
CAPACIDAD del sistema. En cascada 3B→7B sube codigo duro 40→60% pass@1
(+20pp medido). Corre como 2o server dedicado en :8092 para no tocar el
fleet del 3B (:8088). Base pura (lora_path=None): aporta capacidad cruda.

## Politica de RAM

LAZY-LOAD-USAR-CERRAR: el caller hace close() tras la tarea → RAM en reposo
0. El i3 tiene ~12GB (3B 1.93GB + 7B 4.68GB + portero + KVs = riesgo OOM);
keep-warm solo opt-in `COGNIA_HEAVY_KEEPWARM`.

## Decision de entrada

Entra en GREEDY cuando el 3B fallo sus tests visibles ([[concepts/colonia]]).
Leccion del deploy (3 e2e fallidos): el juez best-of-N con tests visibles
debiles descartaba el candidato correcto del 7B — greedy directo reproduce
el gate. Instalacion opt-in: `cognia install-model --with-heavy-code`
(~4.7 GB); sin el modelo degrada al 3B sin romper nada.

## Kill-switch

Default ON desde 2026-07-10 (gate 8/8, probe 4/4, e2e PASS);
`COGNIA_HEAVY_CODE=0` lo apaga.

## Links

- [[concepts/colonia]]
- [[entities/fleet_registry]]
- [[entities/llama_backend]]
