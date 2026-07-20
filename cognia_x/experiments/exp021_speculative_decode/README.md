# exp021 — Velocidad de generación de texto para que Cognia X "hable rápido" (F-SPEED)

> **Objetivo:** subir los tok/s de decode (lo que limita hablar+gesticular en tiempo real).
> Todo medido sobre el hardware REAL (i3-10110U, 2c/4t, sin GPU, llama-server b9391,
> Qwen2.5-Coder-3B Q4_K_M, ~8.3 tok/s baseline). Método del lab: código que corre o no cuenta.

## Veredicto (mapa de levers, exploración exhaustiva)

| Camino | Lever | Resultado (medido) | Estado |
|---|---|---|---|
| Código/RAG | `ngram-mod` speculative | bit-idéntico, hasta 1.45× en repetición | ✅ shippeado (`node/llama_backend._spec_args`) |
| Habla social | base 0.5B (cascada) | **35.9 tok/s = 4.3×**; turnos sociales **sub-segundo** | ✅ shippeado (`node/speech_cascade`, opt-in) |
| Sustancia (3B) | cuantización Q3_K_S | 1.08× + **calidad rota** | ❌ refutado |
| Sustancia (3B) | draft model separado | **0.37×** (compite por banda) | ❌ refutado (cota: exp004) |
| Sustancia (3B) | difusión en CPU | pierde por banda (bloque/N<2.7) | ❌ refutado (cota física) |
| Sustancia (3B) | **cabeza MTP/EAGLE-3** | proyectado **2-3×** sin perder calidad | 🔒 GATED (autorización GPU) |

**Principio unificador (exp004):** el decode en CPU es *memory-bandwidth-bound* → cada token
≈ una lectura de los ~1.8 GiB de pesos. Difusión y speculative son DUALES (commitear varios
tokens por lectura). En el i3, el drafter debe costar ~0 banda (n-gram=0, cabeza=MB); un draft
separado o un modelo de difusión grande NO pagan. El lever dominante real es el TAMAÑO del
modelo (0.5B = 6× menos params → 4.3×), NO la cuantización.

## Scripts (qué mide cada uno)

| Script | Mide | Hallazgo clave |
|---|---|---|
| `bench_real.py` | ngram-* speculative en el server real | echo 1.45× (simple), ngram-mod bit-idéntico |
| `bench_draft.py` | warm: baseline vs ngram vs draft-0.5B | draft-0.5B **hunde** habla (0.37×) |
| `bench_small_base.py` | 0.5B corriendo solo | **35.9 tok/s** (4.3× el 3B) |
| `eval_speech_quality.py` | calidad 0.5B vs 3B (español) | 0.5B fluido pero poco fiable en hechos |
| `cost_model.py` | modelo de banda calibrado a exp004 | baseline=14.96 GiB/s; proyección heads 2-3× |
| `bench_quant.py` | Q3_K_S vs Q4_K_M | 1.08× + calidad rota → refutado |
| `cascade_router.py` | prototipo del router 0.5B↔3B | routing + demo e2e (artefacto histórico) |
| `bench_cascade_e2e.py` | latencia conversacional CON vs SIN | social ~4-5× sub-segundo; total 1.11× |
| `verify_spec_wiring.py` | e2e del wiring ngram-mod en el backend | CHECK OK |
| `analyze.py` | consolida → `results/verdict.json` | H-SPEED-1 = MIXTA |

## Docs
- `DESIGN.md` — el híbrido AR↔difusión (decoder de bloque-especulativo bandwidth-aware) y la
  descomposición del problema (cartero/lecturas).
- `EAGLE_MTP_SCOPING.md` — plan + gating del único lever vivo (cabeza EAGLE-3, 2-3×).
- `results/results.md` — informe completo (8 secciones de evidencia).
- `results/*.json` — datos crudos (verdad única por script).

## En producción (rama cognia-x)
- `node/llama_backend._spec_args()` → `--spec-type ngram-mod` por defecto (env `COGNIA_SPEC_TYPE`).
- `node/speech_cascade.py` → cascada 0.5B↔3B (opt-in `COGNIA_SPEECH_CASCADE=1`), warm-up al iniciar
  el REPL, routing endurecido (`classify_turn`). Wire en `cognia/cli.py`.
- Ledger: `cognia_x/research/cycles/cycle34_speculative_decode.py` (H-SPEED-1, D-SPEED-1).

## Reproducir (venv312, en orden)
```
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_real.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_draft.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_small_base.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\eval_speech_quality.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_quant.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_cascade_e2e.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\cost_model.py
.\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\analyze.py
.\venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle34_speculative_decode
```
(El draft 0.5B y el 0.5B-Instruct viven en `model_shards/` — gitignored.)

## Lo único pendiente (decisión del dueño)
Autorizar 1 sesión de Kaggle GPU para entrenar la cabeza EAGLE-3 → convertir a GGUF → medir el
2-3× real en el i3 (validar el riesgo CPU). Sin eso, el camino sustantivo del 3B se queda en su
techo de banda (~8 tok/s); los demás caminos ya están acelerados.
