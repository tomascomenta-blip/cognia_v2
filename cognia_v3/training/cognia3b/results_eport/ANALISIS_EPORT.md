# E-PORT — APTO: el portero 0.5B aprende la identidad en 73 segundos

Kaggle 1×T4, 2.7 min de kernel total (v3; v1 cayó por torchao del env, v2
por OOM de logits con vocab 151k — MB=2 lo resolvió). El experto MÁS BARATO
del programa.

## Veredicto contra el pre-registro (PREREG_PORTERO.md)

| Predicción | resultado | veredicto |
|---|---|---|
| P-PORT-1 (gate): G3 identidad ≥ 90% | 0% → **95%** (n01=19, n10=0, p≈0.0) | **PASA** |
| P-PORT-2 (info): G1 reportado | 55% → 46% (n01=9, n10=18, p=0.12 n.s.) | reportado |

Train: LoRA r16 all-linear sobre Qwen2.5-0.5B-Instruct fp16, receta E-GROK,
e1_train (1344 pares, 767 con identidad Cognia), 109 steps, **72.7 s**,
loss 2.52→1.56, sin NaN.

## Lectura

1. **Tercera confirmación del gap de formato**: la identidad es hábito puro
   y el adapter la instala igual de bien en el 0.5B (0→95) que en el 3B
   (0→90 en deploy). Consistente con TODO el programa.
2. P-PORT-2: el adapter le cuesta ~9pp de G1 al 0.5B (n.s. pero direccional,
   n10=18 vs n01=9). Para el ROL del portero es aceptable — nunca debe
   atender turnos de conocimiento general — pero manda una regla de diseño:
   el router debe ser CONSERVADOR (whitelist de clases triviales: saludo,
   identidad, cortesía, sí/no de estado; ante cualquier otra cosa → 3B).
3. Velocidad: NO medida acá (GPU ≠ deploy); vale la medición CPU previa
   (exp021: 0.5B = 4.3× tok/s del 3B).

## Próximos pasos (fase 2, próxima sesión)

1. Convertir el adapter a GGUF f16 (convert_lora_to_gguf) + bajar el GGUF
   base del 0.5B (Q4_K_M ~400MB).
2. Router de portero en el CLI: whitelist léxica de turnos triviales
   (patrón fleet_router ya validado) + fallback SIEMPRE al 3B ante duda.
3. Gates e2e del producto: G3 en deploy ≥ 90, latencia percibida medida
   REAL en CPU (esperado ~4×), batería completa sin regresión.
4. Si pasa: asset al release fleet-v1 + install_model baja el stack portero.
