# OLMo × Loop × Chimera — RESULTADO (goal 2026-07-01/02, corrida nocturna hasta 05:30)

**Datos crudos:** `results_xolmo/`, `results_xarch/`, `results_xfinal/` · **Kernels:** `xolmo_kernel.py`,
`xarch_kernel.py`, `xfinal_kernel.py` (+ orquestadores `run_kaggle_*.py`) · **Hardware:** Kaggle T4 16GB free.

## 0. Ambigüedad Kimera/Chimera — RESUELTA (pedido explícito del dueño)

**"Kimera Transformer" NO existe como arquitectura publicada.** Kimera (MIT SPARK) es una librería de
SLAM métrico-semántico para robótica (arXiv:2401.06323). Los papers llamados "Chimera" existentes son
otra cosa (pipeline-parallelism SC'21; SSM sobre grafos; speculative decoding). **El nombre correcto en
este contexto es el Chimera INTERNO del repo** (fase 53: `cognia/context/band_router.py` LOCAL/MEDIA/GLOBAL,
`cognia/memory/hierarchical.py`; el whitepaper `chimera_transformer.md` citado en docs NO existe en el
repo — solo sobrevive la implementación). Ideas trasladables a nivel arquitectura: (a) atención banded
multi-nivel (LOCAL denso + GLOBAL escaso), (b) gating dinámico de bandas, (c) write-gate con presupuesto
fijo para memoria comprimida. Esta corrida probó (a); (b) y (c) quedan como frontera.

## 1. OLMo-1B tal cual — la línea base MEDIDA (no asumida)

OLMo-1B-hf (ventana nativa 2048, RoPE), wikitext-2, T4:
- PPL nativa: **17.3@512 → 14.7@1024 → 13.1@2048** (más contexto = mejor, dentro de ventana).
- **Colapso fuera de ventana** (PPL por bucket de posición en ventanas de 4096): dentro ~10.6-14.8;
  en 2048-2560 salta a **32.8**; 2560-3072 **537**; 3072-3584 **2602**; 3584-4096 **5013**.
  → La raíz del muro de contexto que la teoría CogniaX ya había señalado (RoPE OOD, memoria
  `cognia-context-ceiling-longctx`) queda **confirmada cuantitativamente en OLMo**: el colapso es
  posicional y catastrófico (~400×), no gradual.

## 2. Extensión de contexto zero-shot sobre OLMo (sin entrenar)

| técnica | PPL fuera de ventana (2048-4096) | costo in-window | veredicto |
|---|---|---|---|
| nada (base) | 32.8 → 5013 | — | el muro, medido |
| linear/PI ×2 | plana ~15-19 | **+50%** (19.7 vs 13.1) | **DESCARTADA zero-shot** (PI necesita fine-tune) |
| **dynamic-NTK ×2** | **plana 9.7-15** | **≈0** (12.94 vs 13.10) | **QUEDA: 2× contexto GRATIS** |

- Ronda 2 (`--v2`): passkey con harness ARREGLADO (v1 truncaba el needle → no concluyente, defecto
  documentado y corregido) + NTK ×4 hasta 8192. **[completar con results_xolmo v2]**

## 3. A/B de arquitecturas (tiny, desde cero, criterio PRE-registrado)

5 variantes, mismas dims (d=256, byte-level), mismos datos (es-wiki 9.2M bytes), mismos steps.
Criterio escrito ANTES de ver los datos (goal-state.md): C1 calidad ≤+0.03 bpb vs vanilla8;
C2 recall largo ≥90%; C3 menor degradación 512→1024; C4 tok/s.

| variante | params | bpb@512 | bpb@1024 | degradación | tok/s |
|---|---|---|---|---|---|
| vanilla8 (control) | 6.33M | 1.5555 | 1.6691 | +7.3% | 93.2k |
| **banded8 = Chimera 3:1** | 6.33M | **1.5488** | **1.5572** | **+0.5%** | 83.8k |
| vanilla2 | 1.58M | 1.6950 | 2.2010 | +30% | 335.5k |
| looped2x4 | 1.58M | 1.6538 | 2.0628 | +24.7% | 93.5k |
| banded_loop2x4 | 1.58M | 1.6608 | 1.8423 | +10.9% | 87.7k |

**H-CHIMERA (banded 3:1 SWA:global): PASA.** Iguala/mejora la calidad del control (C1) y su
extrapolación de largo es casi perfecta (+0.5% vs +7.3%): las capas SWA son inmunes al OOD posicional
por construcción (solo ven ventana local) y únicamente las 2 globales quedan expuestas — el mismo
mecanismo del hallazgo OLMo, ahora explotado por diseño. Nota honesta: a seq 512 banded es ~10% más
LENTO (la máscara de ventana materializada pierde contra el fast-path is_causal); su ventaja de costo
es asintótica en secuencias largas, acá se compró retención, no velocidad.

**H-LOOP (Universal/Looped Transformer): CAE por la barra pre-registrada.** El mecanismo existe:
looped2x4 le gana a su control de mismos params (1.6538 vs 1.6950) — iterar capas compartidas SÍ compra
profundidad efectiva sin params. Pero no alcanza a vanilla8+0.05 y paga el MISMO cómputo que vanilla8
(93.5k tok/s: el loop 4× anula la ventaja de tener 2 capas). **Aprendizaje:** a esta escala el cuello
es CÓMPUTO, no params — compartir pesos resuelve un problema que no teníamos. El loop quedaría
interesante solo si los params fueran el límite (p.ej. modelos en memoria mínima).

**C2 no discriminó** (todas ~azar 0.031 en MQAR n_pairs=200 a 1500 steps) — consistente con el
historial de grokking del repo (G2): el recall sintético duro no se aprende en corridas cortas.
Anotado; la decisión salió por C1+C3+C4 según la contingencia pre-registrada.

**Selección: banded 3:1 escalado** (regla: "solo H-CHIMERA → banded8 escalado").

## 4. FASE FINAL — entreno desde cero en T4 (sin pesos de OLMo)

Config: banded 3:1, d=512, 12 capas (~38M params), byte-level, es-wiki 20M bytes, 65M byte-tokens
(4000 steps × 32 × 512), AMP+compile+fused (receta XSPEED de la sesión anterior).
**[completar con results_xfinal: curva bpb, extrapolación ±NTK, muestras generadas]**

## 5. Cierre — qué validó y qué contradijo la teoría CogniaX

**[completar al final]** Parciales ya firmes:
- VALIDADO: la raíz RoPE-OOD del muro de contexto (predicha en `cognia-context-ceiling-longctx`,
  medida en OLMo con colapso 400×).
- VALIDADO: la dirección Chimera/HYDRA de bandas LOCAL/GLOBAL — trasladada a arquitectura gana en
  retención de largo sin ceder calidad.
- EXPANDIDO: dynamic-NTK como palanca zero-shot (no estaba en la teoría; 2× contexto gratis en OLMo).
- DESCARTADO: loop transformer como palanca general a esta escala (evidencia: mismo cómputo que el
  modelo profundo, calidad inferior); PI/linear zero-shot (+50% in-window).
- DEUDA HONESTA: recall sintético duro no discriminó en corridas cortas (grokking); passkey v1
  tenía un bug de harness (corregido en v2).
