# Fleet de expertos LoRA (estilo XHUNDRED) — diseño VALIDADO en deploy

**Estado 2026-07-07: la arquitectura de deploy está VERIFICADA con experimento
real en el CLI local; los expertos se entrenan cuando el programa E-MIX/E2-E4
produzca la base mergeada (y con la receta que gane E-GROK).**

## Arquitectura (medida, no especulada)

UN solo `llama-server` (b9391, el binario pineado del deploy) con:
- la base `cognia-3b` Q4_K_M (post E5), y
- N adapters GGUF f16 (`convert_lora_to_gguf.py` b9391, ~7-8 MB c/u)
  cargados con `--lora-init-without-apply`.

El router activa el experto POR TAREA vía `POST /lora-adapters`
(`[{"id": k, "scale": 1.0}]`, resto scale 0.0).

## Lo MEDIDO hoy (base Qwen2.5-Coder-3B Q4_K_M + adapter tooluse v4)

- `GET/POST /lora-adapters` funciona en el b9391 local: swap **2-41 ms**.
- El efecto del adapter es real post-swap: en `search_word` la base elige
  `leer_archivo` (mal) y con scale 1.0 elige `escribir_archivo` (bien);
  4/4 ítems probados con `cache_prompt: false`.
- **Regla obligatoria del router**: tras un swap, la request debe ir con
  `cache_prompt: false` (o slot dedicado por experto): el KV cache calculado
  con otros pesos efectivos es matemáticamente inválido y llama.cpp no lo
  invalida solo (verificado: la 2ª gen post-swap reusó cache y salió en 2.3 s
  vs 41 s de prefill — sospechosamente idéntica a la previa).

## Expertos previstos (cada uno con SU gate congelado)

| Experto | Datos | Gate |
|---|---|---|
| accion (tool-calling) | tooluse_train_v3 (795, anti-ciclo incl.) | G2A (147, congelada) |
| agente-no-cicla | subset anti-ciclo + trayectorias oficina | bench_estancamiento + cierres G2A |
| razonamiento | D4 CoT-por-turno (STaR) | G2R (100, congelada) |
| codigo-python | D3 verificado por pytest | suite por construir (pass@1) |
| codigo-js | D3 verificado por node | suite por construir |
| imagenes-LCD | tools escena_* (cognia/lcd) | oráculo escena (existente, cero-LLM) |
| generalista | mezcla E2 (identidad+es) | G1+G3+G5 |

Anti-catástrofe del generalista: el router defaultea a scale 0.0 (base
mergeada sola) cuando ninguna regla matchea — la base YA pasa G1/G3/G5 por
construcción (gates de E2-E4), así que el fleet nunca rinde menos que la base.

## Router (capa fina, sin framework)

Reglas léxicas deterministas (mismo patrón que `hint` del agent loop) +
fallback base. NO usar matching semántico difuso para elegir experto: la
lección medida de skills (umbral 0.35 matcheaba cualquier cosa en español;
re-calibrado a 0.48 y aun así con residuo) aplica 1:1 acá.

## Pendientes con dependencia dura

1. Base mergeada final (E-MIX → E2-E4 → E5). 2. Receta de train por experto
(E-GROK decide la palanca de data-efficiency). 3. Merges TIES/DARE/soup entre
adapters: experimento posterior — hipótesis: un merge accion+razonamiento
mantiene ambos gates; se pre-registra cuando existan ambos adapters.

## Tooling E5 local (verificado 2026-07-07)

`node/llama-tools-b9391/` (gitignoreado, regenerable): `llama-perplexity.exe`
y `llama-quantize.exe` del tag b9391 EXACTO (version: 9391 7fb1e70b5),
descargados del release oficial win-cpu-x64. Con esto la cadena E5 corre
completa: merge DC-9 (Kaggle) → convert_hf_to_gguf b9391 → llama-quantize
Q4_K_M → eval_g4_cli.py (decode) + llama-perplexity (corrida aparte del gate).
