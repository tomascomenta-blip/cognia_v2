# PREREG — LoRA propio de Qwythos-9B sobre trazas de Cognia (2026-08-09)

*Este prereg se CONGELA antes de entrenar. Cualquier cambio posterior es una
ENMIENDA numerada, jamás una edición en silencio. Los gates F0/F1 y la regla
KILL se leen tal como están escritos aquí. Hereda el instrumento probado de
`PREREG_LORAS_20260801.md` (pipeline PEFT→GGUF→hot-swap PASS; ruta de
atención-solo ABIERTA) y las lecciones de memoria: métrica primaria apareada,
tres nulos donde aplique, nulo de instrumento antes de la primaria, varianza
entre corridas ±34 pts, brazo envenenado → re-baselinear.*

## Objeto y vía

Un LoRA de **FORMATO/USO-DE-TOOLS** (no de conocimiento) entrenado con
conversaciones chatml REALES y VERIFICADAS del agente nativo de Cognia:

- Base EXACTA: `huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated`
  (familia Qwen3.5, bf16 19,3 GB) en `~/.cognia/models/qwythos-9b-base/`
  (`scripts/descargar_qwythos_hf.py`). **PROHIBIDO** entrenar sobre un
  pariente "parecido" (Qwen3.5-9B-Base, etc.): el adapter se convierte
  contra la base exacta del GGUF servido o no vale.
- QLoRA 4bit nf4 + double quant + gradient checkpointing, LoRA r16/alpha32
  **SOLO q/k/v/o** (el conversor b10066 revienta con tensores MLP/expertos;
  la ruta atención-solo está probada 192/192). 1 epoch, lr 3e-4, warmup 10%
  + cosine, batch 1 × grad-accum 16, seed 20260809, seq-len 8192 con
  DESCARTE reportado de ejemplos más largos
  (`scripts/entrenar_lora_qwythos.py`).
- Render y masking con `apply_chat_template` del repo base (la MISMA
  plantilla que llama-server aplica con `--jinja`): labels solo en los spans
  emitidos por el assistant. Ejemplos cuyo render de prefijo no sea prefijo
  del render completo se descartan contados (`plantilla_inconsistente`).
- Conversión: `convert_lora_to_gguf.py` (b10066, ya en
  `~/.cognia/llama/convert/`) con `--base` local, outtype f16.
- Despliegue SOLO si todo PASS: `adapters.json` con
  `nativo_compatible: true` (guard A3 + `marcar_kv_sucio()` ya cableados).

**Trampas heredadas (no re-descubrir):** jamás `--lora-scaled` (el `:` de
`C:` rompe el split en Windows) — siempre el endpoint runtime; server de
gates SIN draft (`--sin-draft`); `--parallel 1` + verificación
`/props total_slots==1`; `cache_prompt:false` en la primera request tras
cada swap (KV contaminado, medido 2026-07-07).

## F-1 · Dataset mínimo (gate de volumen, ANTES de entrenar)

- **PASS:** ≥300 conversaciones selladas post-dedupe
  (`trazas_a_dataset.py --reporte`) **y** ≥15 ejemplos por tool en posición
  de llamada para las 10 tools más usadas del histograma del reporte.
- Sello de evidencia REAL exigido: `verificar_ws == true` o
  `contrato_ok == true` o `gate == "e2e_ok"`. El `status:"completa"` NO
  alcanza (caso 202316).
- **FAIL → NO se entrena.** Se amplía el banco (el cuello es fabricar señal,
  no el constructor); el resto del subsistema pasa a fase 2. La captura y el
  dataset sobreviven.

## F-2 · Smoke de memoria (la estimación es hipótesis, no dato)

```
venv312gpu\Scripts\python.exe scripts\entrenar_lora_qwythos.py --smoke ^
  --dataset %USERPROFILE%\.cognia\data\datasets\qwythos_tools_v1.jsonl
```
- Carga 4bit + 5 pasos forward/backward con el **ejemplo p95** del dataset.
- **PASS:** sin OOM y `torch.cuda.max_memory_allocated` < **15,0 GiB**
  (resultado en `b4_loras/f2_smoke_qwythos_tools_v1.json`).
- **FAIL →** escalera de contingencia pre-registrada, en orden: (1) seq-len
  8192→6144→4096 con descarte reportado; (2) `paged_adamw_8bit` + ubatch
  menor; (3) ruta Kaggle ya probada con la MISMA base y el MISMO masking;
  (4) KILL del entrenamiento local — se documenta aquí y el subsistema
  entrega captura+dataset.
- Se corre con la **flota APAGADA** (`cognia flota parar`); el trainer
  aborta visible si nvidia-smi reporta >2000 MiB ajenos.

## F0 · Actividad (anti no-op silencioso)

Adaptación mínima de `scripts/b4_lora_f0_gate.py` (ya parametriza `--url` y
`--salida`): se agrega un **4º prompt con tool-schema en el cuerpo** (la
conducta entrenada es tool-calling; los 3 prompts actuales quedan).
Protocolo intacto: **S0→S1→S0** por `POST /lora-adapters`, decodificación
determinista, `cache_prompt:false` siempre.

```
llama-server.exe --model ...Qwythos...Q4_K.gguf --port 8090 --ctx-size 16384 ^
  --parallel 1 --n-gpu-layers 99 --flash-attn on --jinja ^
  --lora %USERPROFILE%\.cognia\loras\qwythos-tools-v1-f16.gguf --lora-init-without-apply
venv312\Scripts\python.exe scripts\b4_lora_f0_gate.py --url http://127.0.0.1:8090 ^
  --salida f0_qwythos_tools_v1.json
```

- **Puerto 8090 SOLO con flota Y oficina apagadas** (colisión C3 del plan:
  8090 es el portero de `cognia/oficina/identidad.py`; el gate corre
  [GPU-EXCL] con todo lo demás abajo).
- **PASS = B≠A en ≥1 prompt Y C==A token a token Y B coherente Y log
  limpio.** Rescate heredado: divergencia C≠A con margen de argmax <1e-3 =
  límite del instrumento, no KILL.
- **FAIL → KILL inmediato de la conversión** (adapter roto o no-op): volver
  a (c), no se corre F1.

## F1 · Gate e2e APAREADO ON/OFF — `scripts/b4_lora_qwythos_e2e_ab.py`

- **Banco (20 tareas):** las 5 del e2e clásico + **15 held-out de
  `banco_trazas`** jamás vistas en el dataset — **split por PLANTILLA, no
  por índice** (lección split-disjunto: 11,4% de fuga por índice). Sin las
  15 held-out la corrida NO es la oficial (el script lo declara en el JSON).
- **n = 6 pares por brazo, brazos INTERCALADOS**, orden interno de cada par
  pre-sorteado con **seed 20260809** (el plan se imprime y se guarda ANTES
  de correr). Mismo server vivo: ON = scale 1.0, OFF = scale 0.0 por el
  endpoint runtime — el OFF es el MISMO proceso a escala 0 (el
  contrafactual). `marcar_kv_sucio()` tras CADA swap, también OFF→OFF.
- **Nulo de instrumento (se lee ANTES que la primaria):** 2 pares OFF/OFF
  intercalados en posiciones sorteadas. Si algún |d_nulo| > 1 tarea →
  **INSTRUMENTO_SUCIO: la corrida no cuenta** (no se lee la primaria).
- **Primaria pre-declarada:** neto APAREADO intra-par
  `d_i = aciertos_ON_i − aciertos_OFF_i` sobre las 20 tareas.
  **Éxito = mediana(d) ≥ 0 Y d_i ≥ 0 en ≥5/6 pares Y Σd > 0.** Los niveles
  absolutos entre corridas NO son evidencia (±34 pts).
- **MDE declarado:** ~3 tareas (15 pp) por par; se reporta SIEMPRE junto al
  resultado. Un "sin efecto" con este MDE se declara **NO DETERMINADO**, no
  KILL de la vía.
- **Guard-rail intocable:** `scripts/e2e_happy_path.py` debe dar **5/5 con
  el adapter ON en 2 corridas**. Un 4/5 concentrado en la misma tarea =
  regresión (fallos concentrados = regresión; dispersos = ruido).

## Regla KILL (congelada, sin apelación)

1. **F0 FAIL** → el adapter no pasa a producción; se vuelve a (c).
2. **F1:** mediana(d) < 0, **o** e2e clásico < 5/5 con ON en ≥2 corridas,
   **o** algún par con d_i ≤ −3 → **el `adapters.json` NO se instala** (o se
   instala sin `nativo_compatible`); resultados a `b4_loras/` y sección
   RESULTADOS aquí. La captura y el dataset SOBREVIVEN al KILL.
3. **Brazo envenenado** (bug de arnés descubierto a mitad): enmienda a este
   prereg y re-correr TODO con baseline post-fix (jamás mezclar corridas
   pre/post-fix).

## Qué NO se hace

- No leer la primaria antes del nulo de instrumento; no comparar niveles
  entre corridas.
- No entrenar ni medir con la flota u oficina encendidas.
- No truncar ejemplos a mitad de tool_call (se descartan, contados).
- No instalar `adapters.json` en producción antes de F0+F1 PASS.
- No renderizar ChatML a mano; no entrenar gate/up/down/embeddings.
- No commitear trazas ni datasets al repo.

## RESULTADOS

*(vacío a propósito: se llena en la ola 3, después de correr los gates; los
JSON quedan en `b4_loras/`.)*
