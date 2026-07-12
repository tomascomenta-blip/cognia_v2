# FLEET-30 — Investigación de modelos open-weight ≤7B (2026-07-11/12)

Corrida nocturna autónoma (mandato del dueño, deadline 05:30). Método: 8
agentes de búsqueda por especialidad + consolidador; **solo se listan scores
leídos de la fuente primaria** (model card HF / blog oficial / paper arXiv);
los reclamos de vendor solo-en-imagen quedan marcados. Los tok/s en el i3
son EXTRAPOLADOS del ~8 tok/s medido del 3B actual — NO medidos (el smoke
local los mide antes de adoptar).

## Shortlist consolidada (12)

| # | Modelo | Params | GGUF | Cuant CPU | Rol en el fleet | Licencia |
|---|--------|--------|------|-----------|-----------------|----------|
| 1 | Qwen3.5-4B | 4B | unsloth/Qwen3.5-4B-GGUF | Q4_K_M 2.74GB | código top (LCB v6 **55.8** vs 35.1 del Qwen3-4B) + math + generalista. **GATED: arch 2026 (early-fusion); el pin b9391 probablemente NO la carga** | Apache 2.0 |
| 2 | Qwen3-4B-Instruct-2507 | 4B | unsloth/Qwen3-4B-Instruct-2507-GGUF | Q4_K_M ~2.5GB | agente/tool-calling (BFCL-v3 **61.9**, MultiPL-E 76.8), upgrade SEGURO (arch qwen3 = b9391 OK, no-thinking) | Apache 2.0 |
| 3 | Qwen3-4B-Thinking-2507 | 4B | bartowski/Qwen_Qwen3-4B-Thinking-2507-GGUF | Q4_K_M ~2.5GB | razonamiento/math dura lazy (AIME25 **81.3**); tokens de thinking = minutos en CPU → solo lazy gated | Apache 2.0 |
| 4 | NextCoder-7B | 7.61B | Mungert/NextCoder-7B-GGUF | Q4_K_M 4.78GB | **[7B repair]** HumanEvalFix **81.1** vs 73.8 del Qwen2.5-Coder-7B actual (+7.3pp), Aider 65.7 vs 59.4; fine-tune SeleKT del MISMO 7B ya desplegado → drop-in exacto :8092 | MIT |
| 5 | Arctic-Text2SQL-R1-7B | 7B | mradermacher/Arctic-Text2SQL-R1-7B-GGUF | Q4_K_M 4.68GB | **[7B SQL]** BIRD-dev **68.9** (mejor 7B abierto), Spider 88.8; verificador gratis = ejecutar el SQL | Apache 2.0 |
| 6 | Mellum-4b-sft-all | 4B | JetBrains/Mellum-4b-sft-all-gguf | Q4_K_M ~2.4GB | FIM/autocompletado focal (SAFIM; especialista FIM 2025) | Apache 2.0 |
| 7 | Qwen2.5-Coder-1.5B **base** | 1.5B | QuantFactory/Qwen2.5-Coder-1.5B-GGUF | **Q8_0 ~1.9GB** (lección portero: Q4 hunde a los chicos) | FIM rápido (HumanEval-FIM 83.5; /infill de b9391) + generador barato de candidatos BoN | Apache 2.0 |
| 8 | xLAM-2-3b-fc-r | 3B | Salesforce/xLAM-2-3b-fc-r-gguf | Q4_K_M 1.93GB | function-calling multi-turn (BFCL **65.74**, multi-turn **55.62** = +20pp sobre Qwen3-4B; paper TinyLLM arXiv 2511.22138) | **CC-BY-NC-4.0 ⚠ solo fleet personal, NO empaquetable en PyPI** |
| 9 | VibeThinker-1.5B | 1.5B | mradermacher/VibeThinker-1.5B-GGUF | Q4_K_M ~1.1GB | math de competencia barata (AIME25 **74.4**) a ~15-20 tok/s est. | MIT |
| 10 | LFM2.5-1.2B-Instruct | 1.2B | unsloth/LFM2.5-1.2B-Instruct-GGUF | Q4_K_M 731MB | generalista rápido chat/instrucciones (IFEval **86.23** vs 73.68 del Qwen3-1.7B); arch conv CPU-friendly — smoke b9391 obligatorio | LFM Open v1.0 ⚠ |
| 11 | Qwen3-Embedding-0.6B | 0.6B | Qwen/Qwen3-Embedding-0.6B-GGUF | Q8_0 639MB | embedder RAG código+texto (MTEB-Code **75.41**); requiere `--pooling last` | Apache 2.0 |
| 12 | bge-reranker-v2-m3 | 0.57B | gpustack/bge-reranker-v2-m3-GGUF | Q8_0 ~0.6GB | reranker RAG (`/v1/rerank` de b9391) | Apache 2.0 |

## Descartes clave (con motivo)

- **Seed-Coder-8B / xLAM-2-8b / ToolACE-2-8B / LoopTool-8B**: >7B (fuera de límite).
- **Qwen3.6 (abr 2026)**: NO tiene tamaños ≤7B (GitHub oficial: solo 35B-A3B y 27B). El "Qwen3.6 Coder 4B" de blogs es alucinación.
- **SmolLM3-3B**: la ganancia exige modo reasoning (miles de tokens a 8 tok/s); sin reasoning (LCB 15.2) no supera al 3B actual.
- **SWE-Dev-7B / SWE-agent-LM-7B / OpenReasoning-Nemotron-7B**: 3er-4to slot 7B; loop agéntico = minutos por bug en CPU.
- **DeepSeek-Coder-6.7B / StarCoder2 / CodeGemma-2B / Llama-3.2 / DeepSeek-R1-Distill**: dominados por candidatos del shortlist.
- **Gemma 4 E4B**: 4.98GB (más que el 7B actual), BFCL "mid-80s" NO verificado, arch abr-2026 vs pin.
- **aiXcoder-7B**: licencia bloqueante. **Qwen2.5-Coder-3B base**: Qwen Research License (el ÚNICO no-Apache de la familia).
- **OmniSQL-7B** (BIRD 63.9 < Arctic 68.9): plan B de SQL.

## Dudosos (verificar antes de decidir)

- **Qwen3.5-4B**: scores top probablemente CON thinking; arch nueva → smoke b9391 con kill honesto.
- **SLM-SQL-1.5B** (BIRD 67.08/params récord): SIN GGUF publicado + score con self-consistency; convertir y gatear si SQL se vuelve prioridad.
- **Hammer2.1-3b / Arch-Agent-3B**: scores solo-en-imagen del vendor; A/B secundario del slot FC (Hammer2.1 = misma base que el agente actual).
- **Phi-4-mini-reasoning** (MATH-500 94.6): semi-verificado (agregadores).
- Scores FALSOS cazados (no propagar): XiYanSQL-3B "75.63 BIRD" (card real: 55.08); AIME "91.3" de Qwen3.5 es del flagship 397B.

## Implicaciones para el MoM

1. **Mesa redonda**: NextCoder-7B (repair especializado) es el participante ideal para reparar candidatos fallidos del 3B — familia idéntica al 7B actual, footprint idéntico, MIT.
2. **BFCL/harness**: los scores varían fuerte entre harness (Qwen3-4B: 61.9 oficial / 50.9 en otro paper) — comparar candidatos solo dentro del mismo paper; el gate propio es el que vale.
3. **Formato**: el stack ya cierra JSON con GBNF; el valor de los FC-models está en SELECCIÓN de tool y args multi-turn.
4. **Velocidad**: nada ≤4B nuevo es más rápido que el 3B actual salvo los ≤1.5B; el slot "más inteligencia por token" es Qwen3.5-4B si pasa el smoke.
