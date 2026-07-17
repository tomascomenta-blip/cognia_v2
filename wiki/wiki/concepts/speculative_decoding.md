---
title: Speculative Decoding — linea CERRADA (el lever real es el tamano)
type: concept
tags: [speculative, draft, eagle3, ngram, velocidad, cerrado]
updated: 2026-07-16
---

# Speculative Decoding

→ [[index]]

## Estado: linea CERRADA por kill-gates medidos

En el hardware objetivo (i3 2 cores, CPU-only) el speculative decoding
clasico HUNDE el rendimiento — medido, no proyectado:

```
draft model separado   0.37x   (exp021/CYCLE34)
EAGLE3 (cabeza)        0.464x  (kill-gate 2026-07-10: base 4.42 -> 2.05
                       tok/s, bit-identico; el verify batcheado es
                       COMPUTE-bound en 2 cores; la proyeccion 2-3x era GPU)
```

El kill-gate ahorro 15-24 GPU-h de entrenamiento de cabeza. b9391 ni
soporta draft-eagle3 (eso es b9606).

## Lo unico speculative VIVO en produccion

Drafter ngram del propio llama-server: `COGNIA_SPEC_TYPE` default
`ngram-mod` (bit-identico, gratis) — node/llama_backend.py:303+ con
`_SPEC_NGRAM_ALLOWED` y draft-* PROHIBIDO en CPU.

## El lever real de velocidad en CPU

El TAMANO del modelo: el [[entities/portero_05b]] (0.5B) atiende turnos
triviales a 4.3x el 3B. Techo del hardware ~8-9 tok/s para el 3B
(bandwidth-bound); threads=3; Q4_K_M > Q4_0.

## Historia

La version anterior de esta pagina proponia spec decoding para compensar
el lm_head chunked del path shards numpy (~0.1 tok/s). Irrelevante hoy:
produccion corre llama.cpp a ~8 tok/s. Queda node/nano_draft.py como
experimento archivado.

## Links

- [[entities/portero_05b]]
- [[entities/llama_backend]]
