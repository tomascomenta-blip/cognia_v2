# PREREG — Velocidad de decode y salida de 200k tokens en RTX 5060 Ti 16 GB
**Fecha de congelación:** 2026-08-15 · **Estado:** CONGELADO antes de tocar la GPU
**Enmienda:** cualquier cambio posterior se escribe aquí con fecha y obliga a re-correr los brazos afectados.

---

## 0. Brazo nulo (la configuración de HOY, medida, no supuesta)

| campo | valor |
|---|---|
| Server | PID 22432, `C:\Users\usuario\.cognia\llama\llama-server.exe` |
| Modelo | Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf (5,38 GiB) |
| Flags | `--ctx-size 200192 --parallel 1 --n-gpu-layers 99 --threads 12 --cache-reuse 256 --cache-ram 1024 --prio 2 --flash-attn on --log-disable --spec-type ngram-mod` |
| VRAM | 12.424 / 16.311 MiB usados · 3.627 libres · driver 610.47 |
| Vía de salida larga | `/largo` modo PLANO, techo efectivo **6.536 tokens** (medido) |
| tok/s de decode | **NO MEDIDO** ← lo mide el paso P0 |
| tok/s reportado del 27B | 3,0 · **NO VERIFICADO, NO REPRODUCIBLE** (el GGUF no está en disco) |

## 1. Hipótesis, cada una falsable

- **H1 (fuga).** Los 3 tok/s no son el techo físico. Con η = 0,751 (calibrado sobre 27B IQ2_XXS → 35,8 tok/s en esta misma tarjeta), el 27B UD-Q3_K_XL debe dar 25,1 tok/s. **Predicción falsable:** el brazo nulo (Qwythos-9B Q4_K, 5,78 GB) debe dar **58 ± 12 tok/s**. Si da menos de 25, H1 se cae y el problema es de la máquina, no de la configuración.
- **H2 (mecanismo).** `-ngl 99` explícito impide a `--fit` recortar capas y provoca spill silencioso. **Predicción:** brazo A (`-ngl 99`) entre 8× y 16× por debajo del brazo B (`-ngl auto`), con el log de B mostrando 100% de capas en GPU y el de A mostrando >15.500 MiB de VRAM.
- **H3 (200k continuo imposible).** 27B UD-Q3_K_XL + KV q4_0 de 200.192 = 16.298 MiB > 14.550 de presupuesto. **Predicción:** `llama-fit-params -c 200192` recorta capas o contexto; `/props` devuelve un n_ctx menor al pedido.
- **H4 (secciones sí).** Con secciones de 8.192 tokens el KV no pasa de 144 MiB (27B q4_0) / 85 MiB (MoE q8_0). **Predicción:** VRAM PLANA durante toda una corrida de 200k, medida con nvidia-smi cada 60 s.
- **H5 (el MoE gana en velocidad).** MoE UD-IQ3_XXS ≥ 2,5× el 27B UD-Q3_K_XL en tok/s de decode, apareado intra-corrida.
- **H6 (la ventaja de calidad del 27B es indetectable a este presupuesto).** La diferencia en las 80 hard apareadas es **menor que el MDE** de 9,0 pts con 3 semillas.
- **H7 (el pipeline entrega el target).** `/largo --jerarquico --tokens N --secciones K` entrega ≥0,85·N tokens reales contados con el tokenizador, no con `len//4`.

## 2. Métrica primaria, declarada ANTES

- **Velocidad:** `timings.predicted_per_second` que devuelve el propio `/completion` del server. **Nunca el reloj del cliente.** Mediana de 3 repeticiones.
- **Salida larga:** tokens REALES del fichero de salida, contados con el tokenizador del modelo, dividido por los tokens pedidos. Secundaria: horas de pared con `time.monotonic`.
- **Calidad:** aciertos sobre las 80 hard comunes, **apareados por tarea**, brazos INTERCALADOS tarea a tarea (nunca en bloque).

## 3. Brazos

| # | brazo | modelo | flags que cambian |
|---|---|---|---|
| N | nulo | Qwythos-9B Q4_K | tal como está hoy |
| A | fuga | el que toque | `--n-gpu-layers 99` |
| B | sano | el que toque | `-ngl auto` + `--fit`, sin `--log-disable` |
| M | MoE | Qwen3.6-35B-A3B UD-IQ3_XXS | `-fa on -ctk q8_0 -ctv q8_0 -c 65536 -np 1` |
| D | denso | Qwen3.8-27B UD-Q3_K_XL | `-fa on -ctk q4_0 -ctv q4_0 -c 65536 -np 1` |

**Regla de intercalado:** M y D se alternan M-D-M-D-M-D. Solo los netos APAREADOS intra-corrida cuentan como evidencia (varianza entre corridas medida en esta casa: ±34 pts).

## 4. n y MDE — potencia calculada ANTES de matar ninguna vía

| medida | n | MDE | decisión que soporta |
|---|---|---|---|
| tok/s decode | 3 rep/celda | ±5% (efecto esperado 3,0×) | sobradísima |
| tok/s vs KV | 5 profundidades × 3 rep | ±8% de pendiente | suficiente |
| tokens entregados/pedidos | 3 pedidos distintos | ±0,08 | suficiente |
| **calidad, 80 hard, 1 semilla** | 80 pares | **±15,7 pts** | inútil |
| **calidad, 3 semillas** | 240 pares | **±9,0 pts** | **el presupuesto adoptado** |
| calidad, 6 semillas | 480 pares | ±6,4 pts | +4 h de GPU |

**Consecuencia declarada por adelantado:** la ventaja esperada del 27B (3 pts de índice AA ≈ 4-6 pts de banco) **está por debajo del MDE incluso con 6 semillas**. Si el resultado cae dentro de la banda, el veredicto pre-registrado es **«indistinguible»**, no «empatan» ni «gana el 27B por poco». Y con indistinguible, manda la velocidad.

## 5. KILLs pre-registrados

- **K0.** Si el brazo nulo (Qwythos-9B, 5,78 GB) da **< 25 tok/s** → la máquina está degradada, H1 se cae, se para todo y se diagnostica el hardware antes de descargar nada.
- **K1.** Si el brazo B (`-ngl auto`) **no** supera al brazo A por ≥4× → `-ngl 99` no es la causa, se abre el escenario CPU y se pide al dueño la línea de comando exacta con la que vio 3 tok/s.
- **K2.** Si `/largo --jerarquico --tokens 20000 --secciones 8` entrega **< 0,60** del target → la arquitectura por secciones no está lista; se arreglan los huecos antes de gastar un minuto más de GPU.
- **K3.** Si el MoE UD-IQ3_XXS da **< 30 tok/s** en decode → la proyección de 76,1 (escalada del ancla de 87,37) es falsa; se re-abre el 27B como candidato principal.
- **K4.** Si el log de arranque muestra `flash_attn not supported, set to disabled` → toda la aritmética de KV cuantizado se cae; se recalcula con KV f16 y probablemente no cabe nada.
- **K5.** Si el 27B UD-Q3_K_XL bate al MoE por **≥ +9 pts** en las 80 hard apareadas → se revierte la recomendación y se acepta 1,5 h más de pared.
- **K6.** Si en una corrida de 200k la VRAM **no es plana** (crece más de 300 MiB entre la sección 1 y la 20) → H4 se cae, hay fuga de KV entre secciones y la vía se replantea.

## 6. Prohibiciones (aprendidas a golpes, no negociables)

1. **Nunca `-ngl 99`.** Siempre `-ngl auto` + `--fit`. El flag está armado en producción ahora mismo.
2. **Nunca `--log-disable` al medir.** Usar `--log-file`. Sin el log no se lee el reparto de capas, ni `n_rs_seq`, ni `flash_attn`.
3. **`-ctk` y `-ctv` SIEMPRE del mismo tipo.** `ggml/src/ggml-cuda/fattn.cu:443` → `if (K->type != V->type) return BEST_FATTN_KERNEL_NONE;`. Tipos distintos **desactivan flash-attention entera** en CUDA, sin avisar.
4. **`LLAMA_SERVER_PORT` explícito** en toda medición (`node/llama_backend.py:101` tiene default 8080, donde vive el cerebro del dueño **y** tailscaled). Instancias de prueba en **:8091**.
5. **Nunca `--context-shift`** con este modelo: en un híbrido borra el medio solo de las capas de atención y deja intacto el estado recurrente → corrupción semántica silenciosa. Además se auto-desactiva si carga el mmproj.
6. **`--spec-type none` en toda medición de velocidad base.** MTP decae con la longitud de salida y en MoE **resta** (−6% a −45% medido). Si se mide, se mide aparte y leyendo `n_rs_seq > 0` en el arranque (se recorta a 0 con un LOG_DEBUG invisible).
7. **Verificar en disco, no contra la respuesta del modelo.** Los tokens se cuentan con el tokenizador sobre el fichero escrito, nunca con `len(texto)//4` ni con el banner de `/largo`.

## 7. Lo que se declara NO VERIFICADO

- Los 3 tok/s del 27B: no reproducibles, el GGUF no está en la máquina.
- η = 0,751: calibrado sobre una medición de TERCEROS de un Qwen3.**6**-27B, no del 3.8, y sin saber a qué profundidad de KV.
- 76,1 tok/s del MoE UD-IQ3_XXS: escalado por tamaño de fichero desde un ancla de terceros en Vulkan (87,37 @ IQ2_M). No es una medición nuestra.
- Los 200.000 tokens de `/largo`: medidos con backend FALSO. Es un techo alcanzable del instrumento, **no una garantía con el modelo real**.
- Overhead de compute buffers = 1.000 MiB: extrapolado del 9B, no medido en un 27B/35B.
- Coherencia a 200k tokens: **no existe ningún banco público**. LongBench-Write topa en «>4.000 palabras». Cualquier afirmación sobre calidad a esa escala es opinión.