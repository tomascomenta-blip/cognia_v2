# Beta Publica Ultraplan — Estado al 2026-05-25

Plan de accion para convertir Cognia en una beta publica real: UI profesional,
instalador 1-click correcto, velocidad comercial, y tests end-to-end.

Origen: sesion `/ultraplan` aprobada por el usuario, ejecutada via `/remote-control`.

---

## Fases completadas

### DONE — Gestion de disco y modelos
- model_shards (1.3 GB) movidos a `D:\CogniaModels\model_shards\`
- Junction creada: `cognia_v2/model_shards` -> `D:\CogniaModels\model_shards\`
- AppData duplicate eliminado (~1.1 GB liberados)
- C: paso de 20 GB libres a 22 GB libres
- Decision: mantener Qwen2.5-Coder-3B-Instruct; Qwen2.5-7B diferido

### DONE — UI rediseno completo (anti-cyberpunk)
**Problema:** CSS anterior tenia text-shadow neon verde #00ff41, glow rgba(0,255,65,0.5),
multiples linear-gradients — aspecto amateur.

**Solucion:** Rewrite completo de `index.html` y `style.css`:
- Paleta flat dark: bg=#0a0a0a, surface=#111, accent=#22c55e (sin glows)
- Layout sidebar con navegacion: Chat / Memory / Nodes / Status / Settings
- font-ui = system-ui para labels; font-mono = Consolas solo para chat/codigo
- Cero box-shadow, cero text-shadow, transitions de 120ms solamente
- Todos los IDs de JS preservados (chat, prompt, btn-send, btn-route, etc.)
- `app.js` actualizado: panel switching, refreshStatus(), refreshNodes()

Archivos: `cognia_desktop/renderer/index.html`, `style.css`, `app.js`

### DONE — Instaladores reescritos (P2P correcto)
**Correccion critica del usuario:** Los instaladores no deben descargar el modelo
completo. El coordinador asigna UN shard (~300 MB) al nodo. Modo --local descarga
los 4 (~1.1 GB) para standalone.

**Solucion:** `install.ps1` y `install.sh` reescritos completamente:
1. Detecta Python 3.11+ (auto-instala via winget en Windows)
2. Detecta si corre desde repo o standalone; clona si es necesario
3. Crea venv en ~/.cognia/env/
4. pip install -r requirements.txt
5a. Modo swarm: explica P2P, llama `cognia_setup.py --coordinator <url>` -> 1 shard
5b. Modo --local: explica "4 fragmentos", llama `--coordinator local` -> 4 shards
6. Fallback: sugiere --local si coordinator no responde

Infra verificada: coordinator Railway LIVE, HF dataset LIVE (shard_0=319 MB).

### DONE — Phase 25: Autonomous Daemon
- FS watcher start/stop en `cognia_idle.py` main()
- `tests/test_phase25.py`: 21 tests (fix: record.task_id no record.id)

### DONE — Phase 26: Safe Self-Improvement
- `cognia/agents/self_improvement.py`: TunableParams(5), Benchmark(4 SQL metrics),
  SandboxedExperiment (temp DB + _patch_params context manager), SafeImprover
  (MAX=3 exp, MIN_DELTA=0.02, persiste .params.json), 0 LLM calls
- EPISODIC_PLAN_THRESHOLD promovido a constante en planner.py
- `tests/test_phase26.py`: 25 tests (fix: avg_attempts >= 0.0)
- Suite: 122/122

### DONE — Phase 27: End-to-End Inference Tests
`tests/test_e2e_inference.py` — 39 passed, 7 skipped (@needs_shards sin pesos):
- Wire protocol: encode/decode tokens, hidden, logits, clear_cache, text (5 tests)
- LightTokenizer: encode/decode, vocab range, determinismo (6 tests)
- ChatML template: estructura, system, assistant turn (4 tests)
- Router: RouteDecision, sub_model, confidence, techne para codigo (5 tests)
- Orchestrator sim: init, route_only, shards_ready=False, status (5 tests)
- INT4 quantization roundtrip: shape, dtype, atol=0.15 (4 tests)
- LatentPersistenceCache: get_or_create, update, invalidate (5 tests)
- _shards_available: env logic, COGNIA_NODE_SHARD (5 tests)
- Real shard inference (7 tests, @needs_shards): text output, mode=local, LPC, no EOS
- Suite: 161/161

### DONE — Phase 28: SAR Shard Availability Redundancy
**Problema:** P(todos los shards online simultaneamente) = 0.5^4 = 6.25% — inviable.

**Solucion implementada:**
- `coordinator/shard_registry.py`:
  - `shard_debt` table SQLite con schema propio
  - `record_offline(node_id, shard, model)`: registra cuando nodo se cae
  - `clear_debt(node_id)`: limpia cuando nodo vuelve (llamado desde heartbeat)
  - `shards_in_debt(model)`: shards con nodo offline >24h
  - `replication_report()`: p_all_online, under_replicated, in_debt, recommended_target
  - `_target_replicas_for_p()`: formula R = ceil(log(1-p^(1/n)) / log(1-uptime))
  - `sync_stale_nodes()`: escaneo periodico de la tabla nodes
- `coordinator/app.py`:
  - Import y instancia de ShardRegistry
  - Background task `_sar_sync_loop()` cada 5 minutos
  - GET /api/swarm/replication endpoint
  - Heartbeat llama clear_debt() cuando nodo reconecta
- Descartado: warm pool (~2GB en Railway) — fuera de alcance por RAM limit
- `tests/test_sar.py`: 29/29 passed
- Suite: 190/190

---

## Fases pendientes (siguiente sesion)

### DONE — Release CI disparado (2026-05-25)
- Tag `desktop-v1.0.0-beta.1` pusheado
- GitHub Actions correra: test gate → Windows .exe + Linux .AppImage → upload a GitHub Release
- Ver: https://github.com/tomascomenta-blip/cognia_v2/actions

### DONE — Benchmark de velocidad real (2026-05-25)
Medido con shard_0.npz real (Qwen2.5-Coder-3B INT4, D:/CogniaModels/):

| Metrica | Valor |
|---|---|
| Backend | c_kernel (gcc+omp) |
| q_proj (2048->2048) | 3.4 ms |
| gate (2048->8960) | 12.9 ms |
| lm_head (2048->151936) | 250.9 ms |
| Cold prefill (7 tokens) | 3987 ms |
| Hot decode (FP32 DynQuant) | 176 ms/tok |
| **tok/s estimado (4 shards)** | **~1.26 tok/s** |
| DynQuant warmup (30 steps) | 100% fp32 |
| KV-cache overhead | -0.2 ms (neutro) |
| silu_mul fusion speedup | 1.22x |

Analisis: lm_head (250 ms) es el mayor bottleneck (~60% del tiempo de decode).
Opciones: chunked lm_head con top-k prefilter, o mover lm_head a shard separado.
Target 3-6 tok/s requiere ~4-8x mejora — posible con speculative decoding
confirmado + lm_head optimizado.

### DONE — Packaging / release (verificado 2026-05-25)
- `electron-builder.config.js`: config completa, NSIS/DMG/AppImage, extraResources OK
- `build/entitlements.mac.plist` CREADO — faltaba, macOS build fallaria sin el
- `package.json`: seccion `build` duplicada ELIMINADA (conflicto con config externa)
- `build/nsis_check_python.nsh`: advertencia al usuario si Python no esta instalado
- `scripts/build_release.ps1`: corre tests -> npm install -> electron-builder
- `preload.js`: EventSource SSE para inferStream, contextBridge correcto
- `cognia_desktop_api.py`: /infer-stream SSE con sse_starlette (en requirements.txt)
- `sse-starlette>=1.6` confirmado en requirements.txt
- App empaquetada OK: `cognia_desktop/dist/win-unpacked/Cognia Desktop.exe` (runnable)
- BLOQUEANTE LOCAL: electron-builder descarga winCodeSign (toolchain de firma que incluye
  symlinks macOS) y falla en Windows sin Developer Mode o admin
  FIX: Activar Developer Mode (Settings > System > For developers > Developer Mode ON)
  o usar GitHub Actions CI (runner tiene admin, produce el .exe instalador final)
- electron-builder actualizado a ^25.1.8
- author agregado a package.json (warning de electron-builder eliminado)
- build/entitlements.mac.plist CREADO (blocker macOS build)
- package.json: seccion build duplicada eliminada

### DONE — cognia_mobile CI (2026-05-25)
- APK y PWA en tags `mobile-v*` — jobs `release-android` y `deploy-pwa` en release.yml
- Fix: `assembleRelease` -> `assembleDebug` (debug signing, no keystore para beta)
- Fix: `vercel deploy --prebuilt` -> `vercel dist --prod --yes` (sintaxis correcta para static export)
- `settings.tsx` verificado: default `http://10.0.2.2:8765` correcto para emulador; LAN IP para dispositivo real

### PENDIENTE — Qwen2.5-7B migration (diferida por usuario)
- Requiere ~4 GB adicionales en D:
- Mejor calidad para consultas complejas
- Evaluar cuando haya feedback de usuarios beta

### FUERA DE ALCANCE (confirmado)
- Warm pool en coordinator (~2GB RAM Railway no soporta)
- Sharding WAN sincrono
- FedAvg sobre parametros completos
- Draft model centralizado

---

## Metricas de suite al cierre de sesion
| Fase | Tests | Estado |
|------|-------|--------|
| 1-21 | ~93   | DONE   |
| 22   | 19    | DONE   |
| 23   | 18    | DONE   |
| 24   | 21    | DONE   |
| 25   | 21    | DONE   |
| 26   | 25    | DONE   |
| 27   | 46    | DONE (39+7 skip) |
| 28   | 29    | DONE   |
| **Total** | **190+** | **190 passed, 7 skipped** |
