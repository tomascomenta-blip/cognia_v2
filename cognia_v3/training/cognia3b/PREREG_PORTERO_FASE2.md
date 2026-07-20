# Pre-registro PORTERO FASE 2 — deploy del 0.5B en el CLI (router + gates e2e)

CONGELADO ANTES DE MEDIR (2026-07-10 ~06:40). Continúa PREREG_PORTERO.md:
E-PORT resultó APTO (P-PORT-1: G3 identidad 0→95%, n01=19 n10=0 p≈0; P-PORT-2
informativo: G1 55→46 n.s. → el portero atiende SOLO turnos triviales).

## Diseño congelado (antes de medir)

- **Modelo**: Qwen2.5-0.5B-Instruct Q4_K_M (GGUF oficial de Qwen) + LoRA
  `cognia_portero05b_f16.gguf` (convert_lora_to_gguf b9391, f16) aplicada
  ESTÁTICA (`--lora`, scale 1.0) en un **segundo llama-server** (b9391,
  puerto 8090, ctx 4096, mismos threads).
- **Activación**: por PRESENCIA de archivos en
  `~/.cognia/models/qwen-0.5b-portero/` (o `PORTERO_GGUF_PATH`/
  `PORTERO_LORA_PATH`). Kill-switch: `COGNIA_PORTERO=0`.
- **Router** (whitelist léxica determinista, patrón fleet_router,
  reencarnado sobre `speech_cascade.classify_turn`):
  turnos que van al portero = identidad (`is_identity_turn`, cobertura G3
  20/20 y 0 FP ya medidas en GATES_CLI_VNEXT) + saludo/cortesía explícitos
  (tokens fuertes por substring con tope de largo; acks débiles tipo
  «sí/no/ok/vale» SOLO como turno completo — fix del FP dormido `\bno\b`).
  TODO lo demás (y toda duda/falla del server) → 3B. Los turnos de agente
  y /largo NUNCA pasan por el portero.
- **Prompt del portero**: mínimo (sin historia, sin HYDRA, sin stepwise):
  system «Eres un asistente útil.» — o «You are a helpful assistant.» si el
  turno matchea la heurística léxica de inglés — + turno del usuario crudo.
  Es el MISMO formato del instrumento G3 del kernel (medido 95%).

## Instrumentos (los mismos del programa)

- Suites congeladas: g3_identidad (20), g1_general (100), g2_accion (147),
  g2_razonamiento (100), g2_razonamiento_logica (50), g5_espanol (25).
- Generación: greedy (temp 0), `cache_prompt=false`, oráculos de
  `suite_oracle`. **Matar llama-server entre brazos.** McNemar pareado.
- Latencia: `timings.predicted_per_second` (decode) + wall por turno, en
  los MISMOS ítems, pareado portero-vs-3B.

## Gates (congelados; medir DESPUÉS de commitear este archivo)

- **P-PORT-3 (gate G3 en deploy)**: G3 por la RUTA REAL del CLI (router →
  portero server, prompt del deploy) ≥ **90%** (18/20).
  Si falla: identidad NO se rutea al portero (queda en 3B+accion, G3=100
  medido); el portero solo podría quedar para saludo/cortesía si la
  batería pasa. UNA iteración permitida (p.ej. system por idioma) y
  re-corrida; si falla de nuevo → línea identidad-al-portero CERRADA.
- **P-PORT-4 (cobertura)**: los 20/20 ítems de G3 rutean al portero con el
  router nuevo (la base ya está medida: is_identity_turn 20/20).
- **P-PORT-5 (0 falsos positivos)**: 0 de los 422 prompts no-triviales
  (g1+g2a+g2r+g2rlog+g5) rutean al portero. El scan es determinista y sin
  modelo: si FP>0 se endurece la whitelist y se re-corre el scan (se
  reporta el número de iteraciones); el gate final exige 0.
- **P-PORT-6 (latencia, la razón de existir del portero)**: decode tok/s
  pareado en los ítems G3 ruteados: portero ≥ **3.0×** el 3B+accion
  (esperado 3.5–4.3×: smoke 27.6 tok/s vs ~8 tok/s del 3B; exp021 predijo
  4.3×). Se reporta también wall end-to-end por turno y tiempo de arranque
  del server (smoke: 2.1 s).
- **P-PORT-7 (batería del producto)**: e2e_bateria_final **17/17** con el
  portero integrado (sin regresión de ningún check).
- **No-regresión estructural de G1/G2**: garantizada por P-PORT-5 (ningún
  prompt no-trivial cambia de camino) — no se re-mide G1 completo.

## Promoción (si TODOS los gates pasan)

Asset `cognia_portero05b_f16.gguf` al release fleet-v1 de GitHub +
`install_portero()` en `cognia install-model` (base 0.5B de HF, adapter del
release) + e2e de instalación. PyPI NO se toca sin autorización explícita.

## Qué NO afirma esta fase

- No mejora la CALIDAD de ningún gate (G3 en deploy puede bajar de 100 a
  ≥90 a cambio de ~4× la velocidad en turnos triviales; trade pre-aceptado
  por el dueño en el mandato de fase 2).
- No toca el camino del agente, /largo, ni el fleet del 3B.
