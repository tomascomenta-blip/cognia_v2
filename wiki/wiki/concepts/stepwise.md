---
title: Stepwise — CoT dirigido por turno
type: concept
tags: [cot, razonamiento, stepwise, 4b, fast-path]
updated: 2026-07-16
---

# Stepwise (CoT dirigido)

→ [[index]]

## Que es

`cognia/agent/stepwise.py` — razonamiento paso a paso inyectado POR TURNO
(no en el system prompt: medido, system-CoT y self-consistency-3 se
descartaron; el CoT por turno subio direct 0.31→0.81). v2 (ingles+logica+
tag por idioma) + decompose por dificultad: G2R 60→82 (+22pp, p=0.0002).

## Ruteo razonamiento→4B

El fast-path de chat (cli.py) manda los turnos de RAZONAMIENTO al
Qwen3.5-4B cuando el perfil hibrido lo permite (medido 92.5 vs 82 del 3B,
p~0, validado en vivo 2026-07-12). Leccion del programa: el razonamiento
por fine-tune dio CERO (E-RZN v1/v2, STaR 6 GPU-h = +0pp); la inferencia
dirigida dio +22pp.

## Links

- [[entities/hybrid_router]]
- [[concepts/colonia]]
