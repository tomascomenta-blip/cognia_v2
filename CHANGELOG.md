# Cognia — Registro de Cambios

---

## [3.8.7] - 2026-07-11

### Docs — discoverability del MoM + robustez menor

- **README documenta `install-model` y los especialistas MoM.** El README no
  mencionaba `cognia install-model` (el stack recomendado: GGUF 3B + llama-server
  b9391 + expertos LoRA + portero 0.5B) ni sus opciones, así que los usuarios no
  descubrían el **portero** (turnos de charla ~3.3–3.9× más rápidos) ni el
  **escalado 7B de código** (`--with-heavy-code`, opt-in, +20pp). Agregados a la
  lista de subcomandos, una subsección "Especialistas (Mixture of Models)", y la
  fila del MoM en la tabla de Estado del proyecto (al día, Julio 2026).
- **`/resumir` acota su infer** (`cognia/cli.py`): el resumen es explícitamente de
  2-3 oraciones; se acota a `max_tokens=256` (sin `repeat_penalty`) para no gastar
  si el 3B degenera. Mismo patrón que `/plan crear`.

---

## [3.8.6] - 2026-07-11

### Robustez del agente — búsqueda pese a args ruidosos + cuelgue latente de /plan crear

- **`buscar` rescata la búsqueda cuando el 3B agrega spam a los args**
  (`cognia/agent/tools.py`): el modelo a veces llama `buscar CLAVE-FENIX tetas
  Incontri` (spam degenerado); el patrón literal no matcheaba y el tool devolvía
  "sin resultados" (falso negativo). Ahora, si el patrón multi-palabra no matcha,
  reintenta con el token IDENTIFICADOR distintivo (con guion/dígito), sin rescatar
  palabras comunes (evita falsos positivos). Reporta "(patron acotado a X)".
- **`/plan crear` acota su infer** (`cognia/cli.py`): el decompose (lista de 3-5
  pasos) usaba `orch.infer(prompt)` sin `max_tokens`; si el 3B degeneraba llenaba
  hasta el cap (~70s de basura). Ahora `max_tokens=160` + `temperature=0.0` (mismo
  patrón que el decompose del agente), sin `repeat_penalty`.

---

## [3.8.5] - 2026-07-11

### Fix CRÍTICO — revierte una regresión del agente introducida en 3.8.4

3.8.4 agregó `repeat_penalty=1.3` al paso ReAct del agente (junto con las cotas
del cuelgue). Un e2e del camino feliz —que debió correrse ANTES de 3.8.4— reveló
que ese `repeat_penalty` penalizaba los tokens de los nombres de herramienta (que
se repiten desde la doc de tools en el prompt) y empujaba al 3B a generar BASURA:
**tareas normales de `/hacer` 0/5 con `repeat_penalty`, 5/5 sin él** (write/calc/
json/append/python, mismo modelo y harness). Si actualizaste a 3.8.4, actualizá a
3.8.5: `pip install -U cognia-ai`.

- **Revertido** `repeat_penalty=1.3` del paso ReAct y del `_reinfer_fix`
  (`cognia/cli.py`). Se conservan las cotas del cuelgue que SÍ funcionan:
  `max_tokens=256` por paso + corte por no-progreso (`_FAIL_STREAK=3`). El
  parámetro `repeat_penalty` sigue en `orchestrator.infer` (extensión legítima del
  API), solo que el agente ya no lo usa. Verificado: 5/5 tareas normales + la
  tarea de búsqueda sigue terminando por el corte honesto.
- **Feature — 7B de código en el producto instalado** (`cognia/model_install.py`,
  `node/heavy_code.py`): `cognia install-model --with-heavy-code` (opt-in, ~4.7 GB)
  baja el 7B y persiste su ruta; el escalado reactivo 3B→7B (código duro +20pp)
  ahora se ACTIVA en instalaciones de usuario, no solo en el repo. Sin el flag,
  degrada al 3B como siempre.

---

## [3.8.4] - 2026-07-10

### Fix — Robustez del agente + REPL; feature — especialistas MoM (portero 0.5B, 7B de código)

Release de robustez sobre 3.8.3. Los especialistas MoM viajan como CÓDIGO en el
wheel y se ACTIVAN cuando los modelos del fleet están presentes (vía
`cognia install-model`); sin ellos DEGRADAN CON GRACIA al 3B (no rompen nada).

- **Fix — cuelgue del agente en tareas de búsqueda** (`cognia/cli.py`,
  `shattering/orchestrator.py`): en búsquedas el 3B degeneraba a temp=0 inventando
  nombres de tool basura DISTINTOS cada paso; el stuck-detector viejo (que cuenta
  acciones idénticas) no disparaba y el loop colgaba ~30 min. Fix en 3 capas:
  `max_tokens=256` + `repeat_penalty=1.3` en el paso ReAct (acota cada infer), y
  corte por no-progreso (`_FAIL_STREAK=3`: 3 acciones seguidas que fallan → cierre
  honesto). Repro end-to-end: la tarea termina en 188.8s / 3 pasos (antes colgaba).
- **Fix — REPL con stdin piped** (`cognia/cli.py`): `PromptSession` caía con
  `NoConsoleScreenBufferError` cuando no había consola Win32 (stdin redirigido) y
  el REPL entero moría al arrancar. Ahora cae a `input()`.
- **Feature — portero 0.5B (turnos rápidos)** (`node/speech_cascade.py`): router de
  turnos de charla/identidad al especialista 0.5B en un 2º server con LoRA estática;
  decode 3.33× media / 3.86× mediana pareada, ruta de deploy 90% (18/20), 0 FP
  sobre 422 prompts. Se activa con el GGUF 0.5B instalado; si falta, ruta al 3B.
- **Feature — escalado reactivo 3B→7B en código duro** (`node/heavy_code.py`,
  `cognia/agent/tools.py`): cuando el 3B FALLA los tests visibles de una tarea de
  código difícil, se reintenta con Qwen2.5-Coder-7B GREEDY en un server dedicado
  (:8092, lazy-load-usar-cerrar). Código duro 37.5→57.5% pass@1 (+20pp, p=0.0078).
  Default ON; `COGNIA_HEAVY_CODE=0` lo apaga; sin el GGUF 7B cae al 3B.
- **Robustez — estructura JSON (GBNF) y errores accionables** (`cognia/agent/`):
  gramática GBNF para el gap de formato (schema-fails 7→0, McNemar p=0.016) y
  parche determinista de error accionable (2→9/14) — sin GPU.

Tests de regresión nuevos: `tests/test_agent_step_budget.py` (corte por no-progreso
+ presupuesto del paso ReAct), harness de gates del portero y del 7B.

---

## [3.7.1] - 2026-07-01

### Fix — Agente (loop + herramientas) y backend; feature — pipeline tool-use

Publica los cambios acumulados desde 3.7.0 en el codigo empaquetado.

- **Agente mas robusto** (`cognia/agent/loop.py`, `cognia/agent/tools.py`,
  `cognia/__main__.py`, `cognia/cli.py`): loop que fija el objetivo, salva la prosa,
  detecta ciclos y usa stop-sequence en cada paso (elimina generate-then-discard);
  RESULTADO muestra ruta relativa al workspace; robustez de las herramientas.
- **Memoria / grafo de conocimiento** (`cognia/knowledge/graph.py`): 6 bugs de las
  herramientas de memoria/KG arreglados (auditados).
- **Backend** (`node/llama_backend.py`, `shattering/orchestrator.py`): ajustes de
  robustez del backend llama.cpp / orquestador.
- **Feature — fine-tune tool-use** (`cognia_v3/training/tooluse/`,
  `cognia_v3/training/kaggle/`): pipeline de generacion de trayectorias verificadas por
  ejecucion, banco de tareas y scripts de entreno en Kaggle.

---

## [3.5.1] - 2026-06-08

### Fix — Chat offline (sin Ollama) + `/doctor` instalado por pip

- **Bug: el chat dependia de Ollama.** Al escribir texto libre en el REPL, si no habia
  Ollama corriendo, daba `Ollama no disponible` aunque los shards INT4 locales estuvieran
  cargados. `model_router._llamar_shard_local` (NUEVO): cuando Ollama falla y no hay
  coordinador, usa `ShatteringOrchestrator(mode="local").infer()` (numpy, en-proceso) para
  responder con los shards locales. Verificado: responde texto coherente sin Ollama.
- **Bug: `/doctor` crasheaba instalado por pip** (`can't open file scripts/cognia_doctor.py`)
  porque `scripts/` no se empaqueta. Las diagnosticas se movieron a `cognia/doctor.py`
  (modulo del paquete, viaja en el wheel) y `/doctor` lo ejecuta en-proceso.
  `/update` y `/distill` degradan limpio cuando el script del repo no esta presente
  (sin traceback): `/update` sugiere `pip install -U cognia-ai`.

Tests de regresion nuevos: `tests/test_doctor_packaging.py`, `tests/test_model_router_local_fallback.py`.

---

## [3.5.0] - 2026-06-08

### UX — Onboarding simple (Local por defecto) + personalizacion

Hace que "descargar -> configurar -> ya" sea obvio, con eleccion clara entre correr
LOCAL (en este equipo, sin internet) o COMPARTIDO (red local).

- `cognia/first_run.py`: wizard reescrito a lenguaje plano; LOCAL es el default
  recomendado (antes el modo recomendado pedia una URL de coordinador que el usuario
  no tiene). Paso de personalizacion opcional (nombre / idioma / estilo) + pantalla
  "listo" con el modo y proximos pasos.
- `cognia/user_prefs.py` (NUEVO): preferencias explicitas (nombre/idioma/estilo/modo)
  persistidas en `~/.cognia/config.env`. `personalization_suffix` (puro) +
  `personalize_prompt` (no-op si no hay nada configurado, asi nunca altera el prompt
  canonico de un usuario nuevo).
- `cognia/__main__.py`: comando nuevo `cognia modo` para ver y cambiar el modo
  (local/compartido/memoria) y la personalizacion sin re-configurar todo.
- `cognia/cli.py`: el system prompt del path de streaming pasa por `personalize_prompt`.
- Desktop: endpoints `GET/POST /mode` y `/settings` (comparten el mismo `config.env`
  que el CLI); onboarding visual Local/Compartido; panel de ajustes con personalizacion,
  switch de modo y tema claro/oscuro.

Verificado: wizard end-to-end (HOME temporal), `cognia modo` ver/cambiar, endpoints con
TestClient. Suite completa 2421 passed, 1 skipped, 0 failed.

---

## [1.8.0] - 2026-05-12

### Phase 19 — ARA: Adaptive Rank Amplification

Implementa expansion autonoma de capacidad del adapter ELC. Cuando el adapter satura
(plateau de loss con valor alto), inicializa slots nuevos en direcciones ortogonales
al espacio actual y hace fine-tuning. El FedAvg del coordinador maneja ranks variables.

#### Change 19.1 — Deteccion de saturacion y expansion ortogonal
- `node/rank_expansion.py` (NUEVO): `is_saturated(loss_history)` detecta plateau con
  varianza/media < 2% y loss > 0.05. `expand_lora_weights(A, B, n_new)` inicializa
  nuevas filas de A ortogonales al espacio actual (proyeccion al espacio nulo via QR),
  nuevas columnas de B en cero — delta permanece cero al inicio, se aprende con
  fine-tuning. `MAX_RANK=8` como hard cap.

#### Change 19.2 — LoRATrainer con expansion automatica
- `node/local_adapter.py`: `train()` captura loss history por epoca, detecta saturacion
  post-training, expande ambos pares (K y V) si corresponde, y hace `epochs//3` epocas
  adicionales de fine-tuning con el rank expandido. Sin cambios a la interfaz externa.

#### Change 19.3 — FedAvg variable-rank
- `coordinator/federated_store.py`: `_valid_blob()` acepta rank 4-8 (antes solo 4).
  `_pad_to_rank()` rellena con ceros hasta el rank maximo del batch antes de promediar.
  `aggregate()` dos pasadas: primera determina max_rank, segunda acumula con padding.
  El adapter global queda en el rank mas alto contribuido — nodos con rank menor
  contribuyen cero en las ranuras adicionales (comportamiento correcto).

---

## [1.7.0] - 2026-05-12

### Phase 18 — Sandbox real: AST analysis + runtime guard

Reemplaza la validacion por regex en sandbox_runner.py con dos capas independientes
que cubren los vectores de escape que el regex no detectaba.

#### Change 18.1 — AST-based analysis
- `cognia/program_creator/sandbox_runner.py`: `_SandboxVisitor` (NodeVisitor) detecta
  `import X`, `from X import`, `__import__("X")`, `importlib.import_module("X")`, y
  `os.<attr>` para attrs peligrosos. Imposible de eludir con split de strings o encoding.
  `BLOCKED_MODULES` y `BLOCKED_OS_ATTRS` son frozensets — fuente unica de verdad para
  ambas capas.

#### Change 18.2 — Runtime __import__ guard
- Prefija cada archivo temporal con `_RUNTIME_GUARD`: sobrescribe `builtins.__import__`
  con version que consulta `BLOCKED_MODULES` en tiempo de ejecucion. Bloquea escapes
  via `exec("import socket")`, `eval`, y cualquier import dinamico que el AST no vio.
  `builtins` incluido en `BLOCKED_MODULES` para impedir la remocion del guard.

---

## [1.6.0] - 2026-05-12

### Phase 17 — Contribution Economy: enforcement de tier y RPM por nodo

Cierra el circuito del modelo economico de contribucion. Los datos de tier ya existian
en BD; esta fase conecta el enforcement real: bloqueo por modelo no permitido y
rate limiting por contribucion (no por IP) en el endpoint de shattering.

#### Change 17.1 — SlidingWindowLimiter (nuevo modulo)
- `coordinator/rate_limiter.py` (NUEVO): ventana deslizante de 60s por `node_id`.
  Thread-safe via `threading.Lock` + `deque`. Sin dependencias externas.
  `check(key, limit) -> (allowed, retry_after)`. `evict_stale()` para limpieza.

#### Change 17.2 — Standard tier incluye modelos de Shattering
- `coordinator/contributor.py`: `standard.allowed_models` ahora incluye
  `logos-3.2-3b-q4`, `techne-3.2-3b-q4`, `rhetor-3.2-3b-q4`. Progresion de
  tiers: basic=qwen, standard=todo+shattering, premium=todo+100RPM.

#### Change 17.3 — Enforcement en shattering_infer
- `coordinator/app.py`: `require_contributor_or_admin` retorna `tier_info` completo.
  `/api/shattering/infer` verifica `allowed_models` (403 si modelo bloqueado por tier)
  y aplica RPM por `node_id` via `SlidingWindowLimiter` (429 + Retry-After si excedido).
  Admin y anon (COORDINATOR_KEY no seteado) bypass ambos checks. El limite por IP de
  `slowapi` permanece como backstop anti-DDoS independiente.

---

## [1.5.0] - 2026-05-11

### Phase 16 — Dynamic Quantization (INT4/INT8/FP16/FP32 por frecuencia de acceso)

Implementa cuantizacion dinamica de pesos en el shard engine. Cada peso del
transformador Qwen2 se envuelve en un `DynamicWeights` que trackea el conteo de
accesos y mantiene un cache en RAM a la precision adecuada, evitando la
dequantizacion nibble-packed repetida en cada llamada de inferencia.

#### Change 16.1 — Thresholds en model_constants.py
- `shattering/model_constants.py`: agrega `DYN_QUANT_THRESH_INT8=5`,
  `DYN_QUANT_THRESH_FP16=15`, `DYN_QUANT_THRESH_FP32=30`,
  `DYN_QUANT_IDLE_DECAY_S=300.0`. Fuente unica de verdad para todos los thresholds.

#### Change 16.2 — DynamicWeights y PrecisionManager (nuevo modulo)
- `shattering/dynamic_precision.py` (NUEVO): `DynamicWeights` wrappea cualquier
  `INT4Weights`. Comparte la misma interfaz `.linear(x)` -> drop-in replacement.
  Logica de tier: <5 accesos=INT4 (sin cache), 5-14=INT8 cache (int8+scale),
  15-29=FP16 cache (float16, cast barato a fp32), >=30=FP32 cache (matmul directo).
  Auto-decay: si el ultimo acceso es >300s, resetea contador y borra cache en la
  siguiente llamada. Hilo-seguro via RLock; matmul corre fuera del lock.
  `PrecisionManager`: registry de `DynamicWeights` por key "l{idx}_{nombre}".
  `decay_all(factor=0.3)` para llamar desde el ciclo de sueno.
  `stats()` retorna conteo por tier para monitoreo.

#### Change 16.3 — Integracion en ShardEngine
- `node/shard_engine.py`: `_load_real_weights()` crea un `PrecisionManager` y
  envuelve cada `INT4Weights` (q, k, v, o, gate, up, down por capa + lm_head) con
  `DynamicWeights` antes de pasarlos a `RealTransformerLayer`. La embedding table
  permanece en fp32 (ya dequantizada al cargarse). Agrega `decay_precision(factor)`
  y `precision_stats()`. `info()` incluye stats de precision cuando hay manager.
  `RealTransformerLayer` no necesita cambios: DynamicWeights tiene la misma
  firma de `.linear()`.

#### Change 16.4 — Orchestrator API
- `shattering/orchestrator.py`: agrega `decay_precision(factor=0.3)` que delega
  a todos los `ShardEngine` cargados. Punto de entrada para integracion futura
  con el ciclo de sueno o un trigger HTTP admin.

---

## [1.4.0] - 2026-05-11

### Phase 15 — Emotion Wheel: procesamiento emocional nocturno

Implementa el procesador de la rueda de Plutchik que se ejecuta durante el ciclo de
sueño. Analiza los episodios de las ultimas 24h, calcula la distribucion de las 8
emociones primarias, detecta desequilibrios (alta emocion negativa sin contrapeso
positivo, sesgo de positividad excesivo) y modula la importancia de los episodios
afectados para prevenir bucles de rumiacion y reforzar aprendizaje positivo.
No realiza llamadas a Ollama ni dependencias externas.

#### Change 15.1 — EmotionWheelProcessor (nuevo modulo)
- `cognia/memory/emotion_wheel.py` (NUEVO): `EmotionWheelProcessor.process(hours=24.0)`
  consulta hasta 500 episodios no olvidados, normaliza labels (joy/alegria/felicidad ->
  "joy", etc.) a las 8 primarias de Plutchik, acumula distribucion ponderada por
  `abs(emotion_score) * importance`. Detecta desequilibrio si la emocion dominante
  supera 35% del peso y su opuesta directa es <10%. Modula importancia: factor 1.08
  (dominante positiva, anti-olvido) o 0.92 (dominante negativa, anti-rumiacion),
  clamped a [0.1, 3.0]. Retorna `EmotionReport` dataclass con distribucion, dominante,
  intensidad media, desequilibrio detectado y count de episodios modulados.

#### Change 15.2 — Integracion en ciclo de sueño
- `cognia/cognia.py`: agrega PASO 8 en `_sleep_sync()` justo despues del ELC (paso 7).
  Instancia `EmotionWheelProcessor(self.db)` dentro del bloque try/except — un fallo
  del procesador nunca rompe el ciclo de sueno. Incluye linea "Emocion:" en el resumen
  con dominante, conteo de modulados y desequilibrio si hay.

---

## [1.3.0] - 2026-05-11

### Phase 14 — Federated Learning (FedAvg sobre adaptadores LoRA)

Implementa el primer ciclo de aprendizaje federado real de Cognia. Cada nodo
entrena un adaptador LoRA localmente durante el sueño (ELC, Fase 13) y lo
contribuye al coordinador. El coordinador ejecuta FedAvg ponderado y devuelve
un adaptador global que mejora la inferencia de todos los nodos participantes.
Los datos del usuario nunca salen del dispositivo; solo viajan deltas de
parámetros con ruido gaussiano añadido en el cliente.

#### Change 14.1 — FederatedStore: motor FedAvg + almacenamiento en coordinator.db
- `coordinator/federated_store.py` (NUEVO): motor de agregacion federada.
  `FederatedStore` almacena contribuciones como BLOBs en `coordinator.db`
  (misma DB que registry y ledger, sin rutas de filesystem). Validacion de
  forma npz antes de aceptar (claves: k_A, k_B, v_A, v_B; shapes exactas de
  Qwen2.5 ELC). `add_contribution(node_id, params_b, blob)` recibe la
  contribucion, verifica tier (none rechazado), descarta excedentes sobre
  MAX_PENDING=200. `aggregate()` ejecuta FedAvg ponderado por tier
  (basic=0.5, standard=1.0, premium=3.0); requiere MIN_CONTRIBUTORS=2;
  se dispara automaticamente cada AGGREGATE_EVERY_N=5 contribuciones.
  `get_global_adapter()` retorna blob npz del ultimo FedAvg. `stats()` para
  monitoreo. Limite de tamanio: 512 KB por contribucion.

#### Change 14.2 — Endpoints federados en coordinator/app.py
- `coordinator/app.py`: importa `FederatedStore`, instancia `_fed_store`.
  Tres endpoints nuevos bajo `/api/federated/`:
  - `POST /api/federated/contribute` (10/hour): acepta blob npz en body,
    valida X-Contributor-Token (HMAC), verifica tier != none, delega a
    `_fed_store.add_contribution()`.
  - `GET /api/federated/global` (30/hour): retorna blob npz del adaptador
    global como `application/octet-stream`. Requiere tier >= basic.
    HTTP 404 si aun no hay agregacion.
  - `GET /api/federated/stats` (admin): estadisticas de agregacion.

#### Change 14.3 — Contribucion y aplicacion en cognia/cognia.py
- `cognia/cognia.py`: `_run_elc_training()` ahora llama `_try_federated_sync()`
  tras el entrenamiento ELC local.
  `_try_federated_sync(adapter)`: lee `COGNIA_COORDINATOR_URL` y
  `COGNIA_CONTRIBUTOR_TOKEN` del entorno; si no estan presentes, no-op
  silencioso. Agrega ruido gaussiano (sigma=0.01) a los cuatro tensores del
  adapter antes de enviar (privacidad en cliente). Usa `urllib.request` (stdlib)
  para POST al coordinador y GET del adaptador global. Errores de red son
  silenciosos (el federado es opcional, no bloquea el ciclo de sueno).
  `_apply_global_adapter(blob)`: deserializa el adaptador global y lo cachea
  en `_adapter_store` con user_id="global" para inyeccion en shard_engine.
  Operacion completa: sin nuevas dependencias, sin PyTorch.

---

## [1.2.0] - 2026-05-07

### Phase 13 — Real Distributed Inference with Qwen2.5-Coder-3B (INT4)

Replaces the Llama 3.2-3B simulation baseline with Qwen2.5-Coder-3B-Instruct as the primary
model. Implements a fully functional auto-sharding pipeline: weights are quantized to INT4
on each device, shards communicate via the coordinator relay, and the client receives
articulated text via autoregressive sampling from real (vocab-size) logits.

#### Change 13.1 — INT4 nibble-packed quantization
- `shattering/quantization.py`: added `quantize_int4(W) -> (packed, scale)` and
  `dequantize_int4(packed, scale, orig_cols)`. Per-row symmetric, range [-8,7], 50% smaller
  than INT8. Two weights packed per byte (high nibble = even col, low nibble = odd col).
  Zero-padded to even column count before packing.

#### Change 13.2 — Qwen2.5-Coder-3B architecture constants
- `shattering/model_constants.py`: added `QWEN25_CODER_3B` dict (36 layers, hidden=2048,
  intermediate=8960, n_heads=16, n_kv_heads=8, head_dim=128, rope_theta=1M, vocab=151936,
  EOS=151645). Added `QWEN_SHARD_PRECISION` (all int4), `QWEN_SYSTEM_PROMPT`,
  `QWEN_USER_PROMPT` ChatML templates.

#### Change 13.3 — Qwen2 numpy INT4 forward pass
- `node/qwen2_ops.py` (NEW): `INT4Weights` dataclass with `from_float32()`, `dequantize()`,
  `linear()`. Qwen2 math primitives: `_rms_norm`, `_silu`, `_rotate_half`,
  `_precompute_rope`, `_apply_rope`. `RealTransformerLayer` with full Qwen2 decoder forward:
  RMSNorm → QKV (INT4) → RoPE → GQA (group expand K/V) → scaled dot-product (causal mask) →
  o_proj → residual → RMSNorm → SwiGLU MLP → residual.
- `node/shard_engine.py` (REWRITE): new wire protocol with `PTYPE_HIDDEN=0`,
  `PTYPE_TOKENS=1`, `PTYPE_LOGITS=2`. 12-byte header (type|reserved|shard_idx|dim0|dim1).
  `ShardConfig` extended with n_heads, n_kv_heads, head_dim, rope_theta, rms_norm_eps,
  vocab_size, eos_token_id. `_load_real_weights` uses `safetensors.numpy` + numpy only
  (no PyTorch). `process()` dispatches by PTYPE: shard 0 embeds token IDs, intermediate
  shards chain hidden states, last shard runs final RMSNorm + LM head and outputs
  PTYPE_LOGITS. Backward-compat aliases `encode_hidden_state`/`decode_hidden_state` kept.

#### Change 13.4 — Inference pipeline for Qwen
- `node/inference_pipeline.py`: default model changed to `qwen-coder-3b-q4`.
  Added `_QWEN_EOS_TOKENS = {151643, 151645}` and `_apply_qwen_template()` (ChatML format).
  `generate()` now formats prompts in ChatML, sends int32 token IDs as PTYPE_TOKENS,
  checks both Qwen EOS tokens, and passes `np.array([next_id], dtype=np.int32)` for each
  subsequent step (KV-cache assumed on device). `_single_forward_pass()` detects protocol
  version from wire byte 0 and handles both PTYPE_TOKENS input and PTYPE_LOGITS output.
  `_sample()` uses correct vocab_size=151936 and works with real (1, vocab_size) logits.
  `LightTokenizer.VOCAB_SIZE` updated to 151936.

#### Change 13.5 — Qwen in coordinator and downloader
- `coordinator/registry.py`: `QWEN25_CODER_3B` imported; `qwen-coder-3b-q4` added as
  primary model; `DEFAULT_MODEL` changed to `qwen-coder-3b-q4`.
- `node/downloader.py`: `_qwen25_coder_src()` factory added; `qwen-coder-3b-q4` added to
  `MODEL_CATALOG` pointing to `Qwen/Qwen2.5-Coder-3B-Instruct`.

#### Change 13.6 — Qwen manifest
- `shattering/manifests/cognia_qwen.json` (NEW): 4-shard manifest for
  Qwen2.5-Coder-3B-Instruct INT4. Layer ranges [0-8], [9-17], [18-26], [27-35].
  Shard 0 includes embed_tokens; shard 3 includes lm_head + final_norm. All bundled
  (no on-demand shards — full model needed for inference).

#### Change 13.7 — HF-to-shard conversion script
- `scripts/convert_hf_to_shards.py` (NEW): converts a local HF checkpoint directory into
  INT4 `.npz` shard files. Builds tensor map from `model.safetensors.index.json` or single
  `model.safetensors`. Quantizes each projection to INT4, packs normlayers as float32.
  Supports `--shard N` to convert a single shard. Prints size and next-step instructions.
  No PyTorch required — only `safetensors` and `numpy`.

---

## [1.1.0] - 2026-05-07

### Phase 12 — Production Hardening

Addresses all actionable pending decisions from Phases 7-8. Resolves MLA memory leak,
production log verbosity, multi-user isolation ambiguity, and missing optional dep pinning.

#### Change 12.1 — MLA KV-cache TTL eviction
- `shattering/mla.py`: `CompressedKVCache` gains `_last_access: Dict[str, float]` tracking.
  `put()` and `get()` update last-access timestamp via `time.monotonic()`.
  `clear()` now also removes the `_last_access` entry.
  New `evict_stale(max_age_seconds=3600.0) -> int`: removes all sessions idle longer than
  the threshold; logs at DEBUG; returns eviction count.
- `shattering/orchestrator.py`: `status()` now calls `_evict_mla_caches()` as housekeeping.
  New `_evict_mla_caches(max_age_seconds=3600.0)`: iterates all loaded engines, calls
  `kv_cache.evict_stale()` if present. No-op if no engines have an MLA cache attached.
  Prevents unbounded per-session memory growth in long-running local-mode deployments.

#### Change 12.2 — Optional dep pinning
- `requirements.txt`: added two commented optional entries documenting the minimum versions
  required for real-weight shard inference:
  `# torch>=2.1.0` and `# transformers>=4.40.0`.
  Both remain commented because simulation mode (the current default) does not need them.
  Uncomment when deploying with actual shard weights.

#### Change 12.3 — Production log level in packaged builds
- `cognia_desktop_api.py`: after reading `COGNIA_PACKAGED`, sets root logger to
  `logging.WARNING` when the flag is `"1"`. Suppresses all INFO-level startup noise
  (module load, KG init, episodic memory counts) that would otherwise appear in the
  end user's terminal when running the packaged Electron app.

#### Change 12.4 — Multi-user isolation warning
- `app/routes/user_data.py`: `DELETE /api/user/data` response now includes two new fields:
  `scope: "all"` and `warning: "Cognia is single-user. All episodic memory was deleted..."`.
  Any caller (script or UI) that inspects the response will see the scope explicitly.
- `docs/PRIVACY.md`: added "Single-user limitation" paragraph under the delete section,
  warning that the endpoint affects all stored data with no per-user scoping.

#### Tests
- `tests/test_phase12.py` (NEW): 12 tests:
  - `TestCompressedKVCacheEviction` (8 tests): evict all stale, keep fresh, partial eviction,
    empty cache no-op, clear removes last_access, put/get update timestamp.
  - `TestOrchestratorEvictMLA` (3 tests): no engines no crash, mock engine eviction,
    status() triggers eviction.
  - `TestUserDataDeleteWarning` (1 test): DELETE response contains scope/warning fields.

---

## [1.0.0-beta.1] - 2026-05-06

### Phase 10 — Beta Onboarding

#### Change 10.1 — Deteccion de Ollama con UI accionable
- `cognia_desktop_api.py`: `/ready` enriquecido — llama `GET /api/tags` de Ollama y
  retorna `{status, ollama, model, model_name}` en lugar de un probe binario. Siempre
  retorna 200 para que el polling de Electron no quede en retry loop.
- `cognia_desktop/main.js`: `waitForBackend()` cambiado de `/health` a `/ready`, parsea
  el JSON y resuelve con el objeto completo. `autoUpdater` importado e inicializado.
- `cognia_desktop/renderer/app.js`: `onReady(data)` — si `status !== "ready"`, muestra
  instrucciones accionables: "Install Ollama from ollama.ai" o "ollama pull llama3.2"
  en lugar del mensaje generico de error.

#### Change 10.2 — cognia_doctor: verificacion de modelo descargado
- `scripts/cognia_doctor.py`: nueva funcion `check_ollama_model()` — llama `/api/tags`
  y verifica si el modelo configurado (`COGNIA_OLLAMA_MODEL`, default `llama3.2`) esta
  descargado. Reporta `[OK]` o `[WARN]` con el comando exacto para descargarlo.

#### Change 10.3 — First-run: consentimiento de privacidad
- `cognia_desktop/renderer/index.html`: modal de privacidad oculto por defecto (clase
  `.privacy-modal`, sin inline styles para respetar CSP).
- `cognia_desktop/renderer/app.js`: IIFE `checkPrivacyConsent()` — verifica
  `localStorage.privacyConsent_v1` al cargar; si no existe, muestra el modal.
- `cognia_desktop/renderer/style.css`: estilos del modal y badge via clases CSS.

#### Change 10.4 — Boton de feedback in-app
- `cognia_desktop/preload.js`: `openFeedback()` expuesto via contextBridge.
- `cognia_desktop/main.js`: handler `open-feedback` IPC que llama `shell.openExternal`
  apuntando a GitHub Issues.
- `cognia_desktop/renderer/index.html`: boton "Feedback" en el topbar.

### Phase 11 — Beta Distribution

#### Change 11.1 — Auto-update: electron-updater + GitHub Releases
- `cognia_desktop/package.json`: dependencia `electron-updater@^6.1.0` agregada.
- `cognia_desktop/electron-builder.config.js`: `publish: null` → provider GitHub
  apuntando a `tomascomenta-blip/cognia_v2`.
- `cognia_desktop/main.js`: `autoUpdater.checkForUpdatesAndNotify()` en `whenReady`;
  evento `update-downloaded` reenvía `update-available` al renderer.
- `cognia_desktop/renderer/app.js`: `onUpdateAvailable` listener muestra mensaje.

#### Change 11.2 — Release CI: GitHub Actions construye instaladores en cada tag
- `.github/workflows/release.yml`: nuevo workflow, se activa con tags `v*`. Builds
  Windows (.exe via NSIS) y Linux (.AppImage) en runners separados. Sube artefactos
  a GitHub Release via `softprops/action-gh-release`. Sin code signing (closed beta).

#### Change 11.3 — Docs: links de descarga reales
- `README.md`: seccion "Download" con tabla de plataformas antes de "Instalacion".
- `docs/INSTALL.md`: seccion "Download" como opcion primaria para beta testers.

---

## [0.9.0] - 2026-05-06

### Phase 9 — Security Hardening (pre-public launch)

#### Change 9.1 — SQL injection fix: emotion_filter parameterizado
- `cognia/memory/episodic.py`: `retrieve_similar()` — `emotion_filter` movido a lista
  de parámetros SQLite (`?`); el f-string solo interpola literales del sistema, nunca
  datos de usuario. Previene extracción de todo el histórico episódico vía injection.

#### Change 9.2 — XSS en renderer Electron: innerHTML → DOM API
- `cognia_desktop/renderer/app.js`: 3 ubicaciones donde `innerHTML` recibía datos de
  API (`sub_model`, `mode`, `reason`) y input de usuario (`prompt`) sin escapar.
  Reemplazadas con `document.createElement` + `textContent` + `createTextNode`.
  Un payload `"><img src=x onerror=alert(1)>` como sub_model ya no ejecuta script.

#### Change 9.3 — CORS wildcard restrictivo
- `app/main.py`: `allow_origins=["*"]` → `["http://localhost:3000", "http://localhost:8765"]`.
  Cualquier origen externo deja de recibir `Access-Control-Allow-Origin` en respuestas.

#### Change 9.4 — Prompt injection: delimitadores estructurales en hipótesis
- `cognia/reasoning/hypothesis.py`: `generate()` — `desc_a`, `hechos_a`, `desc_b`,
  `hechos_b` (datos almacenados, controlables por atacante vía `learn()`) ahora
  envueltos en marcadores `<<USER_DATA_START>>` / `<<USER_DATA_END>>`. System prompt
  reforzado: instruye al LLM a ignorar instrucciones dentro de esos delimitadores.
  Estrategia: aislamiento estructural (no filtrado de keywords — frágil).

#### Change 9.5 — Auth opcional en web_app.py
- `web_app.py`: middleware `@app.before_request` lee `COGNIA_WEB_API_KEY` env var.
  Si está configurada, todos los endpoints `/api/*` requieren header `X-Api-Key`.
  Si no está configurada, comportamiento anterior (no-op). Afecta 23 endpoints Flask.

#### Change 9.6 — Rate limiting de feedback + prevención de doble aplicación
- `cognia/cognia.py`: `apply_feedback()` — ventana deslizante de 60 segundos con
  límite de 10 llamadas; IDs ya procesados bloqueados con set en memoria. Previene
  que un atacante boost arbitrariamente `feedback_weight` de memorias inyectadas.
  Estado en RAM: se resetea al reiniciar (sin cambio de schema).

#### Change 9.7 — SSRF: validación de OLLAMA_URL
- `security/ollama_url.py` (NEW): `validate_ollama_url(url)` — permite solo
  localhost/127.0.0.1/::1; bloquea 169.254.x.x (AWS/GCP metadata), IPs privadas
  y públicas. Retorna fallback con WARNING si URL es rechazada.
- `cognia/language_engine.py`: `LanguageEngine.__init__` ahora llama
  `validate_ollama_url()` antes de asignar `self.ollama_url`.
- `shattering/orchestrator.py`: `ShatteringOrchestrator.__init__` idem.

#### Tests
- `tests/test_phase9_security.py` (NEW): 20 tests nuevos cubriendo los 5 cambios
  con comportamiento verificable (9.1, 9.5, 9.6, 9.7 tienen tests; 9.2 y 9.3 son
  JS/config sin tests automatizados).
- Suite completa: 144 passed (124 previos + 20 nuevos), 0 warnings, 0 failures.

---

## [0.7.1] - 2026-05-06

### Change 7.6 — Orchestrator functional backend + Distillation CLI

Root cause: `shattering/orchestrator.py` retornaba string labels de simulacion
(`[Simulation] ...`) en lugar de texto real. Todos los archivos de soporte de Fase 7
(NPQ, RST, MLA, Micro-MoE, Distillation) ya existian y estaban completos; el unico
componente roto era la ruta de inferencia local del orchestrator.

- `shattering/orchestrator.py`:
  - Eliminado `_simulate_response()` stub que retornaba etiquetas de modo
  - `_local_infer()` ahora llama `_ollama_infer()` en lugar del stub
  - `_run_shard_chain()` corregido: bug de tuple unpacking (`engine.forward()` retorna
    `(result, ms)` tuple; codigo anterior verificaba `hasattr(out, "shape")` que es
    False para tuples, dejando `hidden` sin actualizar entre shards); ahora maneja
    tuple/dict/array correctamente; llama `_ollama_infer()` al final para texto real
  - RST quality mode (n_passes >= 2): `_ollama_infer()` hace dos llamadas Ollama:
    primera respuesta + auto-refinamiento; simula el beneficio de profundidad iterativa
    de RST sin pesos reales
  - Agregados `_SYSTEM_PROMPTS` y `_TEMPERATURES` por dominio:
    logos temperature=0.3, techne=0.15, rhetor=0.7
  - `_call_ollama()`: POST a /api/generate, timeout=90s, captura toda excepcion
  - `_unavailable_response()`: mensaje accionable cuando Ollama no esta disponible
  - `__init__` acepta `ollama_url` y `ollama_model` con fallback a env vars
    `COGNIA_OLLAMA_URL` / `COGNIA_OLLAMA_MODEL` / `OLLAMA_URL`
- `scripts/distill.py` (NEW): CLI completo para el pipeline de destilacion SRDN;
  argumentos: --db, --output, --model, --ollama, --epochs, --min-fw, --min-access,
  --limit, --dry-run, --checkpoint-dir; paso 1: query_gold_episodes; paso 2:
  build_training_dataset con razonamientos via Ollama; paso 3: SRDNTrainer curriculum
  logos->techne->rhetor; reporta stats por dominio (n_examples, mean_loss, elapsed)
- `cognia/cli.py`: agregados comandos `distill` (dry-run) y `distill run` (entrenamiento
  completo); seccion SISTEMA del HELP_TEXT actualizada con ambas variantes

---

## [0.8.0] - 2026-05-07

### Change 8.6 -- Packaging
- `cognia_desktop/electron-builder.config.js` (NEW): extended electron-builder config; NSIS (Win), DMG (macOS), AppImage (Linux); optional code signing via CSC_LINK env vars; extraResources includes Python source
- `scripts/build_release.ps1` (NEW): Windows release build script; checks Node/Python, sets version, runs electron-builder, reports artifact path
- `scripts/build_release.sh` (NEW): Linux/macOS release build script; auto-detects platform, same steps as PowerShell variant
- `cognia_desktop/package.json`: added `build:win`, `build:mac`, `build:linux` scripts pointing to new config
- `cognia_desktop/main.js`: passes `COGNIA_PACKAGED=1` env var to Python backend in packaged builds
- `cognia_desktop_api.py`: reads `COGNIA_PACKAGED` env var; no behavior change in dev mode; sets up suppression path for packaged crash details

### Change 8.5 -- Documentation
- `docs/INSTALL.md` (NEW): installation guide; one-command install, manual steps, env vars reference, update instructions
- `docs/PRIVACY.md` (NEW): privacy policy; local-first design, opt-in external connections, GDPR data access/delete endpoints
- `docs/SECURITY.md` (NEW): security policy; vulnerability reporting, data at rest, network, API security, known limitations
- `docs/TROUBLESHOOTING.md` (NEW): common issues with diagnosis commands, Ollama, SQLite, shard workers, encryption, streaming
- `README.md`: updated phase status table (Phases 1-8 with actual state); updated install section to reference install scripts; added documentation index table

### Change 8.4 -- Update mechanism
- `cognia/migrations/__init__.py` (NEW): package; exports MigrationRunner, run_migrations
- `cognia/migrations/runner.py` (NEW): versioned SQLite migration runner; reads/writes schema_version table; migrations 1-3 (feedback_weight, encrypted_at flag, schema_version metadata columns); idempotent
- `scripts/cognia_update.py` (NEW): `cognia update` command; git pull + pip install -r requirements.txt + DB migrations; --skip-git, --skip-pip flags
- `cognia/database.py`: calls `run_migrations(path)` after `init_db()` via try/except (non-blocking)
- `cognia/cli.py`: added `update` command invoking `scripts/cognia_update.py`; added SISTEMA section to HELP_TEXT

### Change 8.3 -- Security hardening
- `scripts/migrate_db_encrypt.py` (NEW): column-level AES-256-GCM encryption migration for `episodic_memory.observation` and `.notes`; idempotent (skips CGN1-prefixed rows); --dry-run mode; passphrase via COGNIA_ENCRYPT_PASSPHRASE or --passphrase
- `app/routes/user_data.py` (NEW): GDPR data endpoints; `GET /api/user/data/export` and `DELETE /api/user/data`; require X-Admin-Key header matching COGNIA_ADMIN_KEY; fail-safe (503) if COGNIA_ADMIN_KEY not set
- `app/main.py`: registers user_data_router at /api prefix
- `coordinator/app.py`: (C2) logs WARNING on startup if COORDINATOR_KEY is empty; (C3) /ready endpoint no longer exposes raw exception text in HTTP 503 detail
- `scripts/audit_deps.py` (NEW): wraps pip-audit; exits 0 if pip-audit not installed (non-blocking for dev); exits 1 on vulnerabilities found
- `.github/workflows/ci.yml`: added "Audit dependencies" step (pip install pip-audit + pip-audit --requirement, `|| true` so it is advisory)
- `.env.example`: added COGNIA_ADMIN_KEY and COGNIA_ENCRYPT_PASSPHRASE with descriptions

---

## [0.8.0] - 2026-05-06

### Change 8.2 -- UX Messages
- `cognia/ux/__init__.py` (NEW): package; exports UXMessages
- `cognia/ux/messages.py` (NEW): all user-facing strings centralized as UXMessages class
  constants; separates internal log strings (which stay in-place) from UI copy
- `cognia_desktop/renderer/app.js`: "Backend ready. Type a prompt..." -> "Ready. Type a
  message and press Send."; backend-error handler no longer exposes internal msg param;
  route error -> generic user message; stream error -> generic user message; status panel
  shows formatted summary via _formatStatus() instead of raw JSON.stringify; added
  _formatStatus() helper
- `cognia_desktop/renderer/index.html`: "connecting..." -> "starting"; "Backend starting...
  please wait." -> "Starting up..."; "Orchestrator status" -> "System"; "Loading..." ->
  "Loading system information..."
- `cognia_desktop/main.js`: pythonProc exit handler sends generic user message instead of
  "Python exited with code N"; waitForBackend reject path sends same generic message
- `cognia_desktop_api.py`: /ready exception handler no longer passes str(exc) to HTTPException
  detail; replaced with fixed user-facing string
- `node/shard_engine.py`: added module-level logger; converted 4 print() calls to
  logger.debug/info/warning -- simulation init, ready message, real-weight load start,
  ImportError fallback
- All 124 tests pass

### Change 8.1 -- Installer
- `install.ps1` (NEW): Windows PowerShell one-command installer; checks Python 3.11+,
  installs pip dependencies, checks Ollama availability, installs Node.js/Electron deps
  if present, creates .env from .env.example; [OK]/[FAIL]/[WARN]/[SKIP] per step
- `install.sh` (NEW): Linux/macOS bash equivalent with ANSI color output; same check
  sequence as install.ps1; set -e for fail-fast
- `scripts/cognia_doctor.py` (NEW): standalone diagnostics script; checks Python version,
  required/optional packages, Ollama reachability, .env present, DB writable, model_shards
  directory; exits 0 if all pass, 1 if any [FAIL]; importable for programmatic use
- `cognia/cli.py`: added `doctor` REPL command; invokes scripts/cognia_doctor.py via
  subprocess.run using the same Python interpreter
- All 124 tests pass

### Added
- Fase 8 Commercial Release agregada al ROADMAP.md (6 cambios, estado TODO)

### Auditoria de preparacion para produccion (Paso 0 -- sin cambios de codigo)

Archivos analizados: `cognia_desktop_api.py`, `cognia_desktop/renderer/app.js`,
`cognia_desktop/renderer/index.html`, `cognia_desktop/main.js`, `security/key_manager.py`,
`cognia/database.py`, `.env.example`, `README.md`, `node/shard_engine.py`, `cognia/cognia.py`

#### Hallazgos CRITICOS

- **C1 -- DB en texto plano**: `cognia_memory.db` se almacena sin cifrado por defecto.
  Todas las observaciones episodicas, vectores y notas del usuario son legibles con
  cualquier lector de SQLite. key_manager.py implementa AES-256-GCM pero requiere
  `unlock()` manual -- el cifrado es opt-in, no el default.

- **C2 -- COORDINATOR_KEY vacio por defecto**: `.env.example` linea 21 define
  `COORDINATOR_KEY=` (cadena vacia). Los endpoints protegidos por `require_admin` aceptan
  cualquier token si la variable no esta configurada, dejando la API de administracion
  abierta en instalaciones por defecto.

- **C3 -- Excepcion cruda expuesta al renderer**: `cognia_desktop_api.py` linea 151
  usa `raise HTTPException(status_code=503, detail=str(exc))`. El mensaje de excepcion
  interna (rutas de archivo, nombres de modulo, stack parcial) llega al renderer de
  Electron y puede mostrarse al usuario o filtrarse en logs del cliente.

#### Hallazgos ALTOS

- **A1 -- Sin endpoint de eliminacion de datos**: no existe ninguna ruta
  `DELETE /user/data` ni equivalente. El usuario no tiene mecanismo para borrar lo
  que Cognia almacena sobre el.

- **A2 -- Sin endpoint de exportacion de datos**: no existe `GET /user/data/export`.
  El usuario no puede inspeccionar ni descargar su propio historial episodico.

- **A3 -- Sin instalador**: la instalacion requiere 8+ pasos manuales (Python 3.11+,
  pip, git, Ollama, Node.js, npm install, variables de entorno, uvicorn). No hay
  `install.ps1`, `install.sh` ni `cognia doctor` para diagnosticar problemas.

- **A4 -- Terminologia tecnica en la UI**: `cognia_desktop/main.js` emite los strings
  "Backend ready", "Backend starting", "Backend error", "Python exited with code N"
  directamente al renderer. `app.js` linea 211 muestra `JSON.stringify(s, null, 2)` del
  estado interno completo en el panel de Status. `index.html` linea 29 usa "Orchestrator
  status" como titulo de panel visible al usuario.

#### Hallazgos MEDIOS

- **M1**: `node/shard_engine.py` emite prints con "[ShardEngine]", indices de capa y
  numeros de shard a stdout, redirigidos por Electron al log del proceso.

- **M2**: `cognia/cognia.py` emite 12 prints de arranque con nombres de modulo internos
  (EpisodicMemory, KnowledgeGraph, etc.) visibles en la consola del usuario.

- **M3**: `app.js` linea 208 muestra "Loading..." sin contexto -- el usuario no sabe
  que esta cargando ni cuanto tardara.

- **M4**: No existe directorio `docs/`. Faltan INSTALL.md, PRIVACY.md,
  TROUBLESHOOTING.md, SECURITY.md.

- **M5**: No hay comando `cognia update` ni framework de migracion de schema documentado.
  Actualizaciones manuales pueden dejar el DB en estado inconsistente.

- **M6**: `index.html` linea 29: "Orchestrator status" como titulo de panel expone
  nomenclatura de arquitectura interna al usuario final.

- **M7**: `app.js` linea 211: el panel de Status muestra el JSON interno completo del
  orquestador, incluyendo nombres de sub-modelos, contadores de expertos y estado MoE.

- **M8**: `security/key_manager.py` usa XOR+HMAC como fallback cuando `cryptography`
  no esta instalado. La documentacion de instalacion no advierte que sin `cryptography`
  el cifrado es debil.

---

## [0.7.0] - 2026-05-06

### Change 7.5 — Distillation Pipeline (SRDN)
- `shattering/distillation/__init__.py` (NEW): package exports
- `shattering/distillation/data_generator.py` (NEW): query_gold_episodes() queries
  episodic_memory for episodes with feedback_weight >= 1.0 and access_count >= 3;
  generate_reasoning_chains() calls Ollama /api/generate with stream=False for each
  episode; build_training_dataset() chains both + optionally writes NDJSON output;
  training_weight = min(feedback_weight / 1.0, 2.0)
- `shattering/distillation/losses.py` (NEW): sequence_level_loss(student_logits,
  teacher_tokens) — cross-entropy averaged over positions with vocab padding;
  consistency_loss(outputs_dict, prompt) — mean pairwise MSE between sub-model
  softmax distributions; combined_loss = 0.7*seq + 0.3*cons * training_weight
- `shattering/distillation/trainer.py` (NEW): SRDNTrainer dataclass; curriculum_order
  ["logos", "techne", "rhetor"]; train(dataset) iterates domains in order; train_epoch
  processes examples in batches of 32; simulation mode: deterministic random logits +
  word-hash teacher tokens; save_checkpoint writes JSON metadata; _filter_domain selects
  label-matched examples or falls back to full dataset; TrainingStats dataclass
- All 124 tests pass

### Change 7.3 — Multi-Head Latent Attention (MLA)
- `shattering/mla.py` (NEW): CompressedKVCache — per-session dict of (c_kv, position)
  tuples, keyed by (session_id, layer_idx); get/put/clear/active_sessions API.
  MLAModule — drop-in for LlamaAttention; W_DKV(3072,512) compresses KV to d_c=512;
  W_UK/W_UV upsample K/V; W_DQ/W_UQ compress/upsample Q; scaled dot-product + GQA
  head repeat; simulation mode caches zero latents (exercises lifecycle, wastes no RAM).
  patch_shard_engine_mla(engine, kv_cache) — replaces layer.self_attn with MLAModule,
  attaches _kv_cache to engine; clear_cache(session_id) delegates to cache.clear().
- `node/shard_engine.py`: ShardConfig gains `precision: str = "fp32"` (from 7.1);
  ShardEngine.__init__ adds `_kv_cache = None`; new `forward(hidden, session_id, input_ids)`
  wrapper over process(); `clear_cache(session_id)` real method (also patched dynamically
  by patch_shard_engine_mla for backward compat)
- `shattering/__init__.py`: exports MLAModule, CompressedKVCache, patch_shard_engine_mla
- All 124 tests pass

### Change 7.2 — Recursive Shared Transformers (RST)
- `shattering/recursive_context.py` (NEW): `RecursiveContext` class.
  `reset()` zeroes context vector. `inject(h)` adds alpha * context to hidden state.
  `update(h)` mean-pools h, optionally projects through W_proj, then applies LayerNorm.
  `load_weights(W_proj, ln_gamma, ln_beta)` loads trained projection (sim mode = identity).
  alpha defaults to RST_ALPHA_INIT (0.1) for stable initialization.
- `node/inference_pipeline.py`: extracted `_single_forward_pass()` helper from
  `_forward_through_swarm()`; `_forward_through_swarm()` now accepts `n_passes: int = 1`;
  when n_passes > 1: instantiates RecursiveContext, loops K times with inject/update around
  each `_single_forward_pass()` call
- `shattering/orchestrator.py`: `__init__` gains `n_recursive_passes: int = DEFAULT_RST_PASSES`;
  `_run_shard_chain()` gains `n_passes` param; when n_passes > 1 uses RecursiveContext
  around the local engine loop
- `shattering/__init__.py`: exports RecursiveContext, DEFAULT_RST_PASSES
- All 124 tests pass

### Change 7.1 — Neural Precision Quantization (NPQ)
- `shattering/quantization.py` (NEW): pure-numpy INT8 and ternary quantization.
  `quantize_int8(W)` — per-row symmetric INT8; scale stored as float32 per row.
  `dequantize_int8(q, scale)` — recovers float32.
  `quantize_ternary(W)` — per-row ternary; threshold = mean(|W|); scale = mean of
  non-zero |W| per row. `dequantize_ternary(q, scale)` — recovers float32.
- `shattering/moe_layer.py`: added `QuantizedStorage` dataclass (q, scale, mode +
  dequantize()); MoEExpert gains `_q_gate/_q_up/_q_down` QuantizedStorage slots,
  `load_weights_int8()`, `load_weights_ternary()`, `_get_weights()` (resolves FP32 or
  dequantizes); `forward()` calls `_get_weights()` instead of referencing `_W_*` directly;
  `perturb_from()` calls `_get_weights()` on source so it works on quantized experts too
- `node/shard_engine.py`: `ShardConfig` gains `precision: str = "fp32"` field
- `shattering/fragment_manager.py`: `load(spec, precision=None)` — auto-resolves
  precision from SHARD_PRECISION when not explicit; `load_all()` forwards precision;
  imported SHARD_PRECISION from model_constants
- `shattering/__init__.py`: exports QuantizedStorage, quantize_*/dequantize_*, SHARD_PRECISION
- All 124 tests pass

### Change 7.4 — Micro-MoE (16 experts, domain-clustered)
- `shattering/model_constants.py`: added MICRO_MOE_NUM_EXPERTS=16, MICRO_MOE_TOP_K=2,
  MICRO_MOE_INTERMEDIATE_DIM=4096, DOMAIN_EXPERT_CLUSTERS (logos:0-4, techne:5-9, rhetor:10-15),
  SHARD_PRECISION, DEFAULT_RST_PASSES, RST_ALPHA_INIT, MLA_D_C/D_C_PRIME/N_HEADS constants
- `shattering/moe_layer.py`: ShatteringMoEConfig defaults updated (num_experts=16, top_k=2,
  intermediate_dim=4096); added domain_clusters field; _default_expert_names() generates
  16 names from DOMAIN_EXPERT_CLUSTERS; convert_ffn_to_moe() now takes primary_domain (str)
  instead of primary_expert_idx (int) — same-domain experts get noise_scale, cross-domain
  experts get noise_scale*3.0; patch_shard_engine() updated to match; router stats still
  track primary (top-1) only to preserve fractions-sum-to-1 invariant across tests
- `tests/test_shattering.py`: updated test_all_zeros_input_no_crash shape assertion from
  (5,1) to (5, self.cfg.top_k) — was hardcoded for old top_k=1 default
- All 124 tests pass

### Added
- Fase 7 SRDN (Sparse-Recursive Distillation Network) agregada al ROADMAP.md

### Analisis realizado (archivos leidos, sin cambios de codigo)
- shattering/moe_layer.py: 3 expertos (LOGOS/TECHNE/RHETOR), top_k=1 Switch-style,
  hidden_dim=3072, intermediate_dim=8192, modo simulacion activo
- shattering/model_constants.py: total_layers=28, hidden_dim=3072, n_shards=4,
  layers_per_shard=7, vocab_size=32000, size_per_shard_gb=0.40
- shattering/fragment_manager.py: max 2 sub-modelos en RAM, LRU a nivel sub-modelo
- shattering/orchestrator.py: modos local/distributed/auto, todas las rutas en simulacion
- shattering/router.py: keyword regex v1.1, 65+57+50 keywords (post-Change 5.1)
- node/inference_pipeline.py: loop token a token, sin KV cache, forward stateless
- node/shard_engine.py: modo real torch.float16, modo sim numpy delays, 7 capas/shard
- cognia/consolidation_engine.py: pipeline 6 fases, feedback_weight controla todas las fases
- cognia_desktop_api.py: SSE via ainfer() + word-split, delay artificial 20ms/palabra
- cognia/memory/episodic.py: factor de score (0.70 + 0.30*feedback_weight)
- requirements.txt: sin torch/transformers pineados, sin bitsandbytes/GPTQ

### Baseline de metricas (pre-Fase-7)
- hidden_dim=3072, total_layers=28, n_shards=4, layers_per_shard=7
- MoE actual: num_experts=3, top_k=1
- Memoria por shard (sim FP32): trivial; real FP16: ~1.6 GB/shard
- Memoria por experto MoE (FP32): ~288 MB; 3 expertos: ~864 MB/capa, ~24.2 GB/28 capas
- Objetivo post-NPQ (INT8/ternario mixto): ~117 MB/capa, ~3.3 GB/28 capas
- Objetivo post-Micro-MoE (16 exp, intermediate=4096, INT8): ~576 MB/shard
- KV cache (GQA estandar T=512): ~28 MB; post-MLA (d_c=512): ~14 MB
- FLOPs activos por token/capa: 100.7 MFLOP (denso); 50.3 MFLOP post-Micro-MoE (top-2, dim/2)
- Routing: regex de keywords; sin routing semantico; sin feedback loop

---

## [2026-05-06] ROADMAP Fase 6 — Optimización Avanzada

### Cambio 6.1 — FAISS Approximate Nearest Neighbour
**Archivos:** `cognia/memory/episodic_fast.py`

- `VectorCache.__init__`: añadido `self._faiss_index = None`
- `VectorCache._build_locked()`: tras construir `_matrix`, intenta `import faiss`; si disponible, construye `IndexFlatIP(dominant_dim)` y añade todos los vectores normalizados
- `VectorCache.search()`: usa FAISS si disponible (candidatos = `min(max(top_k*5, 50), N)` para permitir re-ranking por score ponderado); si no, fallback a numpy dot product
- `requirements.txt`: añadido comentario `# faiss-cpu>=1.7.4  # optional`

### Cambio 6.2 — Script de Checksums SHA-256
**Archivos:** `scripts/generate_manifest_checksums.py` (nuevo)

- Script CLI con `--manifest` y `--hf-token`
- Descarga cada shard del manifest via HuggingFace (con autenticación opcional), computa SHA-256 streaming (bloques de 1 MB), y parchea el JSON en-place
- Skip automático de URLs con `${ENV_VAR}` (placeholders)
- Reporta "unchanged" / "patched" por shard; cuenta total de cambios al finalizar

### Cambio 6.3 — Dockerfile + docker-compose + .dockerignore
**Archivos:** `Dockerfile` (nuevo), `docker-compose.yml` (nuevo), `.dockerignore` (nuevo)

- `Dockerfile`: `python:3.12-slim`, WORKDIR /app, instala requirements, expone 8000, CMD uvicorn app.main:app
- `docker-compose.yml`: servicios `cognia` (puerto 8000), `coordinator` (puerto 8001), `ollama` (imagen oficial, puerto 11434, volumen persistente); todos con `restart: unless-stopped`
- `.dockerignore`: excluye `__pycache__/`, `*.db`, `model_shards/`, `venv/`, `.env`, `.git/`, `node_modules/`

### Cambio 6.4 — Prometheus Metrics
**Archivos:** `app/main.py`, `coordinator/app.py`, `coordinator/relay.py`, `cognia/cognia.py`, `cognia/reasoning/hypothesis.py`, `requirements.txt`

- `requirements.txt`: añadido `prometheus-fastapi-instrumentator>=6.1`
- `app/main.py`: `Instrumentator().instrument(app).expose(app)` (con try/except ImportError)
- `coordinator/app.py`: mismo `Instrumentator` setup + contador `shattering_infer_requests_total{sub_model}` incrementado en `POST /api/shattering/infer`
- `coordinator/relay.py`: gauge `relay_sessions_active` actualizado en `create_session()` y `_purge_expired()`
- `cognia/cognia.py`: contador `cognia_sleep_cycles_total` (incrementado en `_sleep_sync()`) + `cognia_episodes_stored_total` (incrementado tras `episodic.store()` en modo aprendizaje)
- `cognia/reasoning/hypothesis.py`: contador `cognia_ollama_errors_total` (incrementado en `_OllamaCircuitBreaker.call()` en el bloque `except`)
- Todos los contadores usan `try/except ImportError` para no romper si `prometheus-client` no está instalado

---

## [2026-05-04] Sesión de revisión y corrección de bugs

### BUG #1 — CRÍTICO: `NameError: pattern_info` en `sleep()`
**Archivo:** `cognia/cognia.py` — método `sleep()`  
**Síntoma:** Cada llamada a `dormir` (o `sleep()`) terminaba con un `NameError` porque la variable `pattern_info` se referenciaba en el `return` final (línea 886) sin haber sido definida en ningún lugar del método.  
**Causa raíz:** Código preparado para integrar un `_goal_engine.run_pattern_batch()` que nunca llegó a implementarse; la variable quedó referenciada pero no inicializada.  
**Corrección:** Se añadió `pattern_info = ""` al inicio del bloque de hipótesis espontáneas, antes de cualquier `try/except`. La variable queda vacía por defecto y puede asignarse cuando el motor de patrones esté implementado.  
**Impacto:** El ciclo de sueño (consolidación, olvido, hipótesis, investigación autónoma) estaba completamente roto. Esta corrección restaura el funcionamiento básico del sistema.

---

### BUG #2 — CRÍTICO: `NameError: context` en bypass de preguntas sociales
**Archivo:** `language_engine.py` — método `respond()`, Stage 0.5  
**Síntoma:** Cualquier pregunta de tipo "social" (saludo, "¿qué eres?", "hola", etc.) causaba un `NameError` porque el campo `tiene_contexto` del `EngineResult` de retorno usaba `bool(context)`, pero `context` solo se define en la línea 485 (Stage 3/4), que nunca se alcanza en el bypass social.  
**Causa raíz:** El bypass social (Stage 0.5) sale del método antes de que `context` sea construido. Se copió un campo del bloque LLM completo sin adaptar al contexto del bypass.  
**Corrección:** Se reemplazó `bool(context)` por `bool(pre_built_context)`, que sí existe como parámetro del método desde el inicio.  
**Impacto:** Cognia fallaba al responder cualquier saludo o pregunta de identidad — el punto de entrada más común para usuarios nuevos.

---

### BUG #3 — MENOR: `except Exception: pass` silencia errores en `sleep()`
**Archivo:** `cognia/cognia.py` — método `sleep()`, bloque de hipótesis espontáneas  
**Síntoma:** Si el módulo de hipótesis fallaba (p.ej. por un error en `self.semantic.list_all()` o en `cosine_similarity()`), el error desaparecía sin dejar rastro en los logs.  
**Corrección:** Cambiado `except Exception: pass` por `except Exception as _e: logger.warning(...)` para registrar el fallo con contexto.  
**Impacto:** Facilita el diagnóstico cuando el ciclo de sueño genera 0 hipótesis de forma inexplicada.

---

### MEJORA #1 — Logging en sustitución silenciosa de predicados del KG
**Archivo:** `cognia/knowledge/graph.py` — método `add_triple()`  
**Situación anterior:** Si `add_triple()` recibía un predicado no reconocido (no en `VALID_RELATIONS`), lo reemplazaba silenciosamente por `"related_to"` sin ningún log, dificultando detectar errores en la extracción de triplas.  
**Corrección:** Se añadió un `_kg_logger.debug(...)` que registra el predicado original y los nodos afectados antes de la sustitución. El comportamiento de negocio no cambia.  
**Impacto:** Permite identificar qué predicados llegan incorrectos desde los extractores de triplas sin cambiar la lógica de almacenamiento.

---

---

## [2026-05-05] Arquitectura Shattering — Fases 1 a 5

### FASE 1 — Infraestructura base del swarm distribuido

**Nuevos archivos:**
- `shattering/__init__.py` — paquete con exports centralizados
- `shattering/manifest.py` — schema `FragmentSpec` / `AppManifest` + loader JSON con soporte `${ENV_VAR}`
- `shattering/fragment_manager.py` — gestor LRU de shards en RAM (máx. 2 sub-modelos simultáneos)
- `shattering/manifests/cognia_code.json` — bundle TECHNE/0-3 + LOGOS/0
- `shattering/manifests/cognia_desktop.json` — bundle LOGOS/0-3
- `shattering/manifests/cognia_writing.json` — bundle RHETOR/0-3 + LOGOS/0
- `shattering/manifests/cognia_android.json` — bundle LOGOS/0-1 (≤1 GB)
- `shattering/manifests/cognia_writing_android.json` — bundle RHETOR/0-1 (≤1 GB)

**Archivos modificados:**
- `coordinator/registry.py` — agregados logos/techne/rhetor-3.2-3b-q4 al catálogo, `SHATTERING_MODELS`, `DEFAULT_SUBMODEL`
- `coordinator/relay.py` — corregido `send_to_client()` (antes loopeaba al shard 0), agregados `result_data`, `result_ready`, `send_to_shard0()`, `reset_result()`
- `coordinator/app.py` — nuevo endpoint `POST /api/session/{session_id}/infer`
- `node/inference_pipeline.py` — reemplazado stub WS por llamada HTTP real al coordinador
- `node/shard_engine.py` — agregado `position_ids` en forward real (necesario para RoPE de Llama)
- `node/downloader.py` — agregados logos/techne/rhetor al `MODEL_CATALOG`
- `requirements.txt` — agregado `websockets>=12.0`

**Decisiones arquitectónicas fijadas:**
- Modelo base: Llama 3.2-3B-Instruct Q4_K_M
- 3 sub-modelos: LOGOS (razonamiento), TECHNE (código), RHETOR (escritura)
- MoE Easy path: copias densas + especialización por prompt
- Android: llama.cpp vía NDK + React Native/Expo
- Routing: cascada secuencial, sin fusión de pesos

---

### FASE 2 — Router global + Orquestador

**Nuevos archivos:**
- `shattering/router.py` — `GlobalRouter`: heurísticas de keywords → TECHNE/LOGOS/RHETOR. `RouteDecision` con score por dominio y confianza 0–100%.
- `shattering/orchestrator.py` — `ShatteringOrchestrator`: `infer()`, `ainfer()`, `route_only()`, `preload()`, `status()`. Modos: local / distributed / auto. Fallback a simulación sin pesos reales.

**Archivos modificados:**
- `coordinator/app.py` — 3 nuevos endpoints:
  - `GET /api/shattering/route?prompt=` → routing sin inferencia
  - `GET /api/shattering/status` → estado del swarm por sub-modelo
  - `POST /api/shattering/infer` → routing + inferencia distribuida en un solo call
- `shattering/__init__.py` — exports: `GlobalRouter`, `RouteDecision`, `ShatteringOrchestrator`, `InferResult`

---

### FASE 3 — Entry points de las apps

**Nuevos archivos:**
- `cognia_code.py` — CLI para consultas de código/técnicas (manifest TECHNE). Modos: one-shot, `--status`, `--route TEXT`, REPL interactivo con `/help /status /preload /mode /route /clear /exit`.
- `cognia_writing.py` — GUI PyQt6 para escritura (manifest RHETOR). Ventana con prompt/respuesta, botones Generate/Route/Clear, workers QThread (no bloquea la UI). Fallback a REPL si PyQt6 no está instalado.
- `cognia_desktop_api.py` — FastAPI local en puerto 8765. Endpoints: `POST /infer`, `GET /route`, `GET /status`, `GET /health`. Usado como bridge por el app Electron.
- `cognia_desktop/main.js` — Proceso principal Electron: spawna uvicorn, polling `/health` hasta listo, maneja IPC renderer → HTTP → Python.
- `cognia_desktop/preload.js` — contextBridge: expone `window.cognia.{infer, route, status, onReady, onError}`.
- `cognia_desktop/renderer/index.html` — Shell del chat UI.
- `cognia_desktop/renderer/app.js` — Lógica del chat: burbujas, indicador thinking, panel de routing, toggle status.
- `cognia_desktop/renderer/style.css` — Tema oscuro con colores por sub-modelo (LOGOS azul, TECHNE verde, RHETOR naranja).
- `cognia_desktop/package.json` — Electron 31, electron-builder, concurrently.

---

### FASE 4 — Capa MoE verdadera (token-level routing)

**Nuevo archivo:**
- `shattering/moe_layer.py` — Implementación completa de Mixture-of-Experts:
  - `ShatteringMoEConfig` — hiperparámetros: `num_experts=3`, `top_k=1|2`, `hidden_dim=3072`, `intermediate_dim=8192`, coeficientes de aux_loss y z_loss.
  - `MoERouter` — Linear(3072→3) + softmax + top-k. Aux loss estilo Switch Transformer. `routing_stats()` / `reset_stats()`.
  - `MoEExpert` — FFN SwiGLU (gate/up/down). `simulation=True` → pass-through sin alocar RAM. `load_weights()`, `perturb_from()`.
  - `MoELayer` — dispatch disperso; top-k=1 (Switch) y top-k=2 (GShard) soportados. Devuelve `(output, aux_loss)`.
  - `convert_ffn_to_moe(llama_mlp)` — convierte una capa densa a MoE: copia pesos al expert primario, init ruidosa en los demás.
  - `patch_shard_engine(engine, config)` — reemplaza `.mlp` → `_TorchMoEAdapter(MoELayer)` en un ShardEngine real.

**Archivos modificados:**
- `shattering/__init__.py` — exports: `ShatteringMoEConfig`, `MoERouter`, `MoEExpert`, `MoELayer`, `convert_ffn_to_moe`, `patch_shard_engine`

---

### FASE 5 — Hardening

**`node/downloader.py`** — Descargas reanudables:
- `_download_file()` chequea archivo parcial `.tmp`, envía `Range: bytes=N-` header.
- HTTP 206 → append mode (reanuda). HTTP 200 (servidor ignora Range) → reinicia desde cero.
- El `.tmp` NO se borra en caso de error — se conserva para el próximo intento.

**`coordinator/relay.py`** — Recuperación de errores:
- Nuevo `mark_failed(reason)` en `InferenceSession`: setea `failed=True`, guarda razón, dispara `result_ready` inmediatamente → los callers HTTP fallan en milisegundos en vez de esperar el timeout de 60s.
- `reset_result()` ahora también limpia `failed` / `fail_reason`.
- `handle_relay_ws`: `WebSocketDisconnect` y `Exception` llaman a `mark_failed()` con razón + logean con nivel WARNING/ERROR.
- Logger a nivel de módulo agregado.

**`coordinator/app.py`** — Fail-fast:
- `/api/session/{id}/infer` y `/api/shattering/infer` verifican `session.failed` tras `result_ready` → HTTP 503 con razón en vez de retornar datos corruptos.

**`node/inference_pipeline.py`** — Bridge async/sync + caché:
- `async def agenerate()`: wrapper async usando `asyncio.get_running_loop().run_in_executor()` (compatible Python 3.10+, evita el deprecated `get_event_loop()`).
- `_get_model_config()`: cachea el resultado tras el primer fetch exitoso (antes se llamaba por cada token dentro del loop de generación vía `_embed()`).
- `except Exception: pass` silencioso en `_forward_through_swarm` reemplazado por `logger.warning`.
- Logger a nivel de módulo e import de `asyncio` agregados.

---

---

## [2026-05-05] ROADMAP Phase 1 — Estabilidad Critica

### 1.1 — Columna `feedback_weight` + migracion de schema
**Archivo:** `cognia/database.py`
Nuevo runner de migracion: detecta si la columna falta en DBs existentes y la agrega sin romper datos. La tabla `schema_version` registra la version aplicada.

### 1.2 — Circuit breaker para Ollama + presupuesto de 30s en sleep
**Archivos:** `cognia/reasoning/hypothesis.py`, `cognia/cognia.py`, `cognia/research_engine/researcher.py`
Timeout de 5s por llamada; el breaker se abre tras 3 fallos consecutivos y espera 60s antes de reintentar. El ciclo de sueño tiene un techo de 30s para no bloquear el event loop.

### 1.3 — `threading.RLock` en VectorCache
**Archivo:** `cognia/memory/episodic_fast.py`
Lock en build/search/invalidate para evitar condiciones de carrera cuando varios hilos acumulan episodios durante el sueño.

### 1.4 — Eviccion + insert atomicos en FragmentManager
**Archivo:** `shattering/fragment_manager.py`
El antiguo patron TOCTOU (check-then-act sin lock) reemplazado por una seccion critica unica que evita race condition en LRU.

### 1.5 — Limpieza periodica de sesiones relay expiradas
**Archivos:** `coordinator/relay.py`, `coordinator/app.py`
`_cleanup_loop()` en background purga sesiones inactivas cada 30s para evitar memory leak en deployments de larga duracion.

### 1.6 — Limpieza de `.tmp` solo en errores 4xx
**Archivo:** `node/downloader.py`
Errores 4xx (recurso no existe) → borra el `.tmp`. Errores 5xx o de red → lo conserva para reanudar en el siguiente intento.

### 1.7 — Truncacion de input en router
**Archivo:** `shattering/router.py`
El router solo analiza los primeros 2000 caracteres para evitar coste O(L x K) en documentos largos.

---

## [2026-05-05] ROADMAP Phase 2 — Hardening de Seguridad

### 2.1 — CORS restringido a localhost
**Archivos:** `cognia_desktop_api.py`, `coordinator/app.py`
`allow_origins` configurado a `["http://localhost", "http://127.0.0.1"]`. Variable de entorno `COORDINATOR_ALLOWED_ORIGINS` para sobreescribir en produccion.

### 2.2 — Autenticacion admin en endpoints criticos
**Archivo:** `coordinator/app.py`
`require_admin` en `DELETE /node`, `GET /pending_sessions`, `POST /shattering/infer`. Token via header `X-Admin-Token` validado contra `COORDINATOR_ADMIN_TOKEN` env var.

### 2.3 — Rate limiting con slowapi
**Archivos:** `coordinator/app.py`, `requirements.txt`
200/min en registro y heartbeat; 60/min en sesiones y routing; 10/min en inferencia. Agregado `slowapi>=0.1.9` a requirements.

### 2.4 — Dependencia `cryptography>=41.0.0`
**Archivos:** `requirements.txt`, `security/key_manager.py`
Warning mejorado cuando la libreria no esta instalada; version minima que incluye fixes de CVE recientes.

### 2.5 — `.env.example` y proteccion de `.env`
**Archivos:** `.env.example` (nuevo), `.gitignore`
Todas las variables de entorno documentadas en `.env.example`. `.env` agregado a `.gitignore` para evitar filtrar credenciales.

---

## [2026-05-05] ROADMAP Phase 3 — Performance

### 3.1 — VectorCache: invalidacion con debounce de 3s
**Archivos:** `cognia/memory/episodic_fast.py`, `cognia/memory/episodic.py`
`mark_dirty()` + flag `_dirty_since`. Rebuild solo si han pasado 3s desde el ultimo dirty. 200 `store()` durante el sueño = maximo 1 rebuild en vez de 200.

### 3.2 — Sleep no bloqueante (async)
**Archivos:** `cognia/cognia.py`, `app/routes/chat.py`
`sleep()` renombrado a `_sleep_sync()`; nuevo `async def sleep()` usa `run_in_executor`. El event loop de uvicorn ya no se bloquea durante los 30-90s del ciclo de consolidacion.

### 3.3 — Consolidacion O(N log N) con multiplicacion matricial
**Archivo:** `cognia/consolidation_engine.py`
`_consolidate_batch()`: reemplazado el doble loop Python por `M @ M.T` (BLAS). 200 episodios = 19,900 iteraciones Python → 1 operacion de algebra lineal (10-50x mas rapido).

### 3.4 — TTL de 300s en cache de config del modelo
**Archivo:** `node/inference_pipeline.py`
`_get_model_config()` almacena `(cfg, timestamp)` y refresca tras 300s. `invalidate_config_cache()` disponible para callers que saben que el coordinador cambio.

---

## [2026-05-06] ROADMAP Phase 4 — Tests y CI

### 4.1 — Suite de tests para Shattering
**Archivo:** `tests/test_shattering.py` (nuevo, 53 tests)
Cubre: `GlobalRouter` (routing por dominio, truncacion, fallback), `ManifestLoader` (5 manifests, ENV_VAR, FragmentSpec), `FragmentManager` (carga, eviccion LRU, is_loaded), `MoERouter` (shapes, pesos normalizados, stats), `MoELayer` (simulacion, aux_loss, top_k=2), `ShatteringOrchestrator` (infer, route_only, status). Todo en modo simulacion — no requiere pesos reales.

### 4.2 — Suite de tests para ConsolidationEngine
**Archivo:** `tests/test_consolidation.py` (nuevo, 20 tests)
Cubre: `init_db()` en DB nueva, migracion de DB vieja sin `feedback_weight`, idempotencia, tabla `schema_version`; `_phase_purge` (marcado forgotten, respeto a labels protegidos y confianza alta); `_phase_weaken` (reduccion de importancia, minimo respetado); `_phase_consolidate` (fusion de episodios similares, ignorar disimilares); `run_full_cycle` (DB vacia, resultado tipado, campos presentes, ciclo completo con datos).

### 4.3 — CI con GitHub Actions
**Archivo:** `.github/workflows/ci.yml` (nuevo)
Trigger: push + PR en `main`. Matrix: Python 3.11 y 3.12. Cache de pip por hash de requirements.txt. Comando: `pytest tests/ -x --tb=short`.

### Bugs corregidos durante la implementacion de Phase 4

- **`cognia_v2/__init__.py`**: imports relativos erroneos en la raiz del proyecto → `ImportError` al correr pytest. Limpiado a stub con solo `__version__`.
- **sys.path collision** (`tests/conftest.py`, `test_fase2.py`, `test_consolidation.py`): agregar `ROOT/cognia` a `sys.path` hace que Python importe `cognia.py` como modulo standalone en vez de `cognia.cognia` miembro del paquete, rompiendo todos los imports relativos. Eliminado de todos los archivos afectados.
- **`cognia/consolidation_engine.py:_phase_semantic_dedup`**: `conn.close()` no se llamaba si el query fallaba con `OperationalError` → file lock en Windows. Corregido con `try/finally`.
- **`tests/test_consolidation.py` + `tests/test_fase2.py`**: 8 patrones `sqlite3.connect(path)` inline sin cerrar → `PermissionError` en `os.unlink` en Windows. Todos corregidos con variable explicita + `.close()`. Agregado helper `_unlink_db()` con WAL checkpoint para `TestRunFullCycle`.
- **Schema de test `semantic_memory`**: faltaban columnas `vector` y `associations` requeridas por `_phase_semantic_dedup`. Agregadas al helper `_full_schema`.

**Estado final: 124 tests pasan (test_shattering: 53, test_consolidation: 20, test_fase2: 37, test_fase3: 14).**

---

---

## [2026-05-06] ROADMAP Phase 5 — Escalabilidad y Features Completos

### 5.1 — Expansion de keywords del router
**Archivo:** `shattering/router.py`
Agregados 21 keywords a TECHNE (model, training, neural, tensor, gpu, machine learning, deep learning, django, fastapi, react, vue, kubernetes, serverless, pandas, numpy, spark, postgresql, mongodb, llm, fine-tune, embedding), 17 a RHETOR (marketing, campaign, brand, pitch, copywriting, proposal, memo, screenplay, dialogue, documentation, manual, guide, tutorial, specification, propuesta, borrador, introduccion), 15 a LOGOS (algebra, calculus, geometry, proof, physics, chemistry, biology, quantum, ethics, sociology, economics, estadistica, demostrar, analizar, explicar). Agregada constante `router_version = "1.1"`.

### 5.2 — Constantes de arquitectura centralizadas
**Archivos:** `shattering/model_constants.py` (nuevo), `shattering/fragment_manager.py`, `coordinator/registry.py`, `node/downloader.py`, `shattering/moe_layer.py`
`LLAMA_32_3B` dict centraliza total_layers=28, hidden_dim=3072, intermediate_dim=8192, n_shards=4, layers_per_shard=7, vocab_size=32000, size_per_shard_gb=0.40, params_b=3.2. Los 4 archivos existentes ahora importan de `shattering.model_constants` en vez de repetir los numeros. `shattering/__init__.py` exporta `LLAMA_32_3B`.

### 5.3 — Streaming de inferencia en Desktop App
**Archivos:** `cognia_desktop_api.py`, `cognia_desktop/preload.js`, `cognia_desktop/renderer/app.js`, `requirements.txt`
- `GET /infer-stream?prompt=...` → `EventSourceResponse` via `sse-starlette`. Genera tokens palabra-a-palabra con delay de 20ms simulado; evento final incluye sub_model, confidence, latency_ms, mode.
- `window.cognia.inferStream(prompt, onToken, onDone)` en preload.js via `EventSource` directa al backend (puerto 8765). Retorna funcion `cancel()`.
- `sendPrompt()` en app.js reemplazado: crea una burbuja que crece token por token; la linea de meta se llena al recibir el evento `done`.
- `sse-starlette>=1.6` agregado a requirements.txt.

### 5.4 — Monitoreo de desbalance MoE
**Archivos:** `shattering/moe_layer.py`, `shattering/orchestrator.py`
`MoELayer.check_balance(warn_threshold=2.0)` computa fraction/expected por expert, loguea WARNING si algun expert supera 2x la fraccion esperada, retorna `{"imbalance_ratios": {...}, "max_ratio": float}`. `ShatteringOrchestrator.status()` llama a `check_balance()` sobre cada engine cargado y agrega `"moe_balance"` al resultado si hay engines MoE activos.

### 5.5 — Readiness probes para produccion
**Archivos:** `coordinator/app.py`, `cognia_desktop_api.py`, `railway.toml`
- `GET /ready` en coordinator: verifica `SELECT 1` en el registry DB + que el cleanup task este corriendo → 200 / 503.
- `GET /ready` en desktop API: llama `_orch.status()` sin excepcion → 200 / 503.
- `railway.toml`: `healthcheckPath` cambiado de `/api/health` a `/ready`.
- Ambos endpoints `/ready` no tienen rate limiting (excluidos de slowapi).

---

## Estado del sistema tras los cambios

| Componente | Estado |
|---|---|
| `sleep()` / ciclo de sueño | ✅ Funcional |
| Respuestas sociales (Stage 0.5) | ✅ Funcional |
| VectorCache (invalidación) | ✅ Ya corregido (hash incluye importance+confidence) |
| KG — sustitución de predicados | ✅ Ahora logeado |
| Bare `except` en hipótesis | ✅ Ahora logeado |

---

## Bugs conocidos pendientes (sin corrección en esta sesión)

- **DB schema migration**: no hay validación ni migración automática entre versiones del schema. Si `cognia_memory.db` viene de una versión anterior con columnas faltantes, los INSERTs fallan silenciosamente.
- **CognitiveProfile no integrado completamente**: `AttentionSystem` solo se reconstruye cuando se aplica feedback; los cambios de peso no se validan en tests de integración.
- **FatigueMonitor sin reset de estado**: si el módulo falla en `__init__`, el dict de adaptaciones queda hardcodeado y el throttling nunca funciona.
