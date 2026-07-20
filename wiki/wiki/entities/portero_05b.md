---
title: Portero 0.5B — fast-path de turnos sociales (:8090)
type: entity
tags: [portero, 0.5b, speech, velocidad, identidad]
updated: 2026-07-16
---

# Portero 0.5B

→ [[index]]

## Que es

`node/speech_cascade.py` — un 0.5B rapido (~28-36 tok/s, 4.3x el 3B en el
i3 bandwidth-bound) atiende los turnos SOCIALES/triviales (saludo,
cortesia, identidad); todo lo sustantivo escala al 3B. El 0.5B es fluido
pero poco fiable en hechos (exp021) → `classify_turn()` es CONSERVADOR:
ante la duda, 3B.

## Dos modos

1. **PORTERO** (default por presencia): 0.5B + LoRA de identidad
   (`cognia_portero05b_f16.gguf`, E-PORT: G3 identidad 0→95%) en
   `~/.cognia/models/qwen-0.5b-portero/`. Base Q8_0 (hallazgo: Q4_K_M
   hunde G3 del 0.5B 95→80). Kill-switch `COGNIA_PORTERO=0`. Ante
   CUALQUIER falla cae al 3B y no reintenta cada turno.
2. **Cascada legado** (opt-in `COGNIA_SPEECH_CASCADE=1`): 0.5B pelado,
   solo turnos sociales (la base dice "Qwen" si le preguntan identidad).

## Por que no speculative decoding

Draft model separado mide 0.37x en CPU; EAGLE3 mide 0.464x en el i3
2-cores (verify batcheado compute-bound). La velocidad real en CPU viene
del TAMANO del modelo — por eso un 0.5B entero para turnos triviales.

## Links

- [[entities/llama_backend]]
- [[concepts/install_model]]
