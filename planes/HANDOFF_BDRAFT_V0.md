# PROMPT DE HANDOFF — continuar el entrenamiento del BDraft (v0 → G3)

Copiar desde aquí hacia abajo en una sesión nueva de Claude Code abierta en
`C:\Users\usuario\Desktop\cognia_v2`:

---

Continúa el entrenamiento del Cognia-BDraft (v0 hasta el gate G3). Lee PRIMERO:
`planes/DSPARK_GEMMA_DRAFT_MODEL.md` (plan pre-registrado con gates), `bbrain.md`,
y la memoria canónica del proyecto (cognia-mapa-subsistemas). CLAUDE.md manda.

## ESTADO al 2026-07-18 (todo verificado y commiteado, HEAD=8283711)

- **G0 COMPLETO: PASS** — bitsandbytes 0.49.2 NF4 funciona en Windows nativo sm_120
  (sin WSL2). El 7B HF está en `C:\Users\usuario\.cognia\models_hf\qwen2.5-7b-instruct\`
  (14.2 GB): carga NF4 en 8.6s / 5.85 GB VRAM, genera coherente, y un train-step del
  draft con hidden states reales corrió OK.
- **G2: PASS 4.33×** (techo teórico medido; kill-gate era 1.5×).
- **Pipeline completo commiteado y verificado adversarialmente (sin fraude de métricas)**:
  `bdraft/gen_dataset.py` (datos regenerados por el 7B vía llama-server :8088),
  `bdraft/real_data.py` (RealBatcher, split 98/2 por sha1 sin fuga),
  `bdraft/train_real.py` (7B NF4 congelado + embeddings/head compartidos + chunked-CE +
  checkpoint/--resume + eval G3). 26 tests bdraft verdes.
- **EN CURSO (background)**: `python -m bdraft.gen_dataset --n 12000 --workers 4`
  escribiendo `~/.cognia/bdraft_data/v0.jsonl` (REANUDABLE: si murió, relanzar el mismo
  comando con `.\venv312\Scripts\python.exe`; sigue desde donde iba). Tarda horas.
  Requiere el llama-server 7B vivo en :8088 (si no está: `/velocidad` lo documenta;
  arranca solo al usar el chat de cognia, o revisar LLAMA_* en ~/.cognia/config.env).

## SECUENCIA RESTANTE (en orden, con sus gates)

1. **Esperar/verificar el dataset**: `~/.cognia/bdraft_data/v0.jsonl` con ~12000 líneas
   y su `.done`. Espot-check honesto: 5 líneas al azar con respuestas no vacías.
2. **Apagar el llama-server** para liberar VRAM antes de entrenar:
   `from cognia.perf_profiles import kill_llama_server` (o taskkill llama-server.exe).
3. **Entrenar hasta el checkpoint G3** (usar `venv312gpu`, NUNCA venv312 para esto):
   ```
   .\venv312gpu\Scripts\python.exe -m bdraft.train_real
       --data C:\Users\usuario\.cognia\bdraft_data\v0.jsonl
       --target-dir C:\Users\usuario\.cognia\models_hf\qwen2.5-7b-instruct
       --tokens-budget 15000000
   ```
   (correr en background con timeout largo; log en ~/.cognia/bdraft_ckpt/train_log.jsonl;
   si se corta: mismo comando + `--resume`). Estimación: 2-6 h en la RTX 5060 Ti.
4. **Veredicto G3 pre-registrado** (lo imprime el script al agotar budget):
   top1_acc ≥ 30% **y** τ_greedy ≥ 1.5 → PASS. FAIL → 1 solo reintento con lr/datos
   ajustados (máx +5h) o KILL de la Pista 1 (reportar honesto igual).
   OJO: esta τ es "teacher-forced" (caveat declarado en el docstring de train_real) —
   en el MANAGER_LOG llamarla así; la τ real la exige G4a con loop de verificación.
5. **Si G3 PASS**: continuar el run v0 completo relanzando con
   `--tokens-budget 150000000 --resume` (15-30 h, tope duro pre-registrado 60 h GPU).
6. **Al terminar v0**: medir G4a/G4b/G4c según la sección 3 del plan (pipeline propio
   draft→verify), y si pasan, conectar el checkpoint a `/velocidad`:
   `set_config_value('COGNIA_BDRAFT_CKPT', <ruta>)` desbloquea los modos
   `gemma` y `difusion-dspark` (cognia/velocity.py ya los gatea por esa env).
7. **Cierre de sesión SIEMPRE**: números reales (ganen o pierdan) al MANAGER_LOG.md,
   commit + push (auth gh ya configurada), y el Stop hook del cerebro anti-daños
   exigirá actualizar la memoria cognia-mapa-subsistemas + regenerar bbrain
   (`.\venv312\Scripts\python.exe -m cognia bbrain`) — cumplirlo, no ignorarlo.

## REGLAS DURAS DE ESTA MÁQUINA
- venv312 = tests/CLI (torch CPU). venv312gpu = SOLO entrenamiento (torch cu128).
- PYTHONUTF8=1 en todo. hf-xet se cuelga en esta red: descargas con curl.exe al CDN.
- Los gates pre-registrados MANDAN: no extender presupuestos sin re-registrar por
  escrito. Honestidad sobre resultados negativos — el método es el producto.
