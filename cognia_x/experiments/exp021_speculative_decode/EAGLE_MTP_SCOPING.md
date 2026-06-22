# Scoping — cabeza MTP/EAGLE-3 para Qwen2.5-Coder-3B (CYCLE 8, F-SPEED)

> El lever GENERAL para habla rápida **y** precisa (sin perder calidad del 3B). exp021
> proyectó **2.1–3.0× (17.7–24.8 tok/s)** bajo el modelo de banda. Es la respuesta a
> "parámetros entrenados modificables que funcionan con el sistema actual": una cabeza
> pequeña (2–5% del 3B) sobre la base congelada, que el binario b9391 ya carga
> (`--spec-type draft-eagle3 -md head.gguf`).

## Qué es y por qué encaja en el i3
- EAGLE-3 (SafeAILab, NeurIPS'25): una cabeza auto-regresiva liviana que extrapola los
  hidden-states del target para proponer varios tokens; el 3B los **verifica** → lossless.
- Es el ÚNICO speculative que respeta la pared de banda (exp004): la cabeza es ~2–5% del
  3B → coste de banda extra ~0, comparte la lectura de pesos del 3B. (Un draft model
  separado, en cambio, mide **0.37×** en el i3 — exp021.)

## Coste de entrenamiento (datos reales)
- Repo oficial: `github.com/SafeAILab/EAGLE` (EAGLE-1/2/3). Entrena SOLO la cabeza
  (target congelado), con las activaciones del 3B como supervisión.
- Datos: ShareGPT + UltraChat (~54K ej. en una impl). Para Cognia: **ShareGPT-es +
  corpus de código** (para no degradar el dominio Coder/español).
- Tiempo: ~1h26m en **1×H100** (config completa); la cabeza converge rápido (es chica).
- Hardware Cognia: **Kaggle** (cuenta anthuananthuan) = 30h/sem gratis, P100 16GB o
  T4×2, 9h/sesión. Pipeline ya existe en `cognia_v3/training/kaggle/`.
  - Estimación P100 (~8–12× más lento que H100 en esta carga): ~12–17h → 2 sesiones de
    9h con checkpoint/resume, dentro de la cuota semanal. **Factible pero no trivial.**

## Conversión a GGUF (para que el binario lo cargue)
- `convert_hf_to_gguf.py` (de llama.cpp) con la **metadata del target** (requerido para
  draft standalone EAGLE3/DFlash). **No está en el repo** (solo tenemos el binario
  pre-compilado b9391) → hay que clonar el fuente de llama.cpp para el script.
- Resultado: `head.gguf` → `llama-server --spec-type draft-eagle3 -md head.gguf`.

## EL RIESGO CRÍTICO (validar PRIMERO, antes de gastar GPU)
**EAGLE3-en-CPU está SIN VALIDAR.** La proyección de 2–3× asume aceptación ~2.4–3.4 y
banda-de-cabeza ~0; el modelo de banda lo favorece, PERO:
- nadie ha benchmarkeado EAGLE3 en CPU para un 3B denso;
- el único benchmark real de speculative que encontré (Qwen3.6-A3B en RTX3090) dio
  **0 speedup neto en TODAS las configs** (era MoE, caso distinto, pero es una alerta).

→ **Regla de oro (validar la suposición más riesgosa, lo más barato):** ANTES de
entrenar una cabeza custom (12–17h GPU), conseguir CUALQUIER head EAGLE3 ya entrenada
para un Qwen2.5 (si existe en HF) y **medirla en el i3** para confirmar que el speedup
CPU es real. Si no existe, entrenar una cabeza MÍNIMA (1 sesión, pocos steps) como PoC,
convertir, y benchmarkear en el i3. **Go/no-go sobre el speedup CPU MEDIDO**, no
proyectado.

## Plan por pasos (gated)
1. **(CPU, barato)** Buscar head EAGLE3/MTP pública para Qwen2.5-3B/Coder-3B en HF. Si hay
   → convertir a GGUF y medir en el i3 (reusar `bench_draft.py` con `--spec-type
   draft-eagle3`). **Esto decide todo.**
2. Si no hay head pública → PoC: entrenar cabeza mínima en Kaggle (1 sesión) sobre
   ShareGPT-es+código, convertir, medir en i3.
3. Si el speedup CPU se confirma (>1.5×) → entrenar la cabeza de calidad (2 sesiones
   Kaggle, checkpoint/resume) y wire en `node/llama_backend.py` (permitir `draft-eagle3`
   con head local; hoy `_spec_args()` solo permite `ngram-*`).
4. Si NO se confirma en CPU → documentar el null y quedarse con: cascada 0.5B (habla
   social) + ngram-mod (código/RAG) + el 3B AR para sustancia.

## Gating (CLAUDE.md)
- Entrenamiento real en Kaggle = tiempo/cuota GPU → **requiere autorización del dueño**
  antes de lanzar (no se ejecuta autónomo).
- Clonar el fuente de llama.cpp solo para `convert_hf_to_gguf.py` (sin tocar el binario
  pineado b9391).

## Hallazgo de búsqueda (paso 1 ejecutado)
Hay heads EAGLE3 públicas para muchos Qwen (Qwen2.5-**14B**-Instruct, Qwen3-8B, Qwen3-a3B,
Qwen3-14B, Qwen3.6-27B…) **pero NINGUNA para Qwen2.5-Coder-3B ni Qwen2.5-3B-Instruct**. Como
las heads son específicas del target (entrenadas sobre SUS hidden-states), una de 14B **no
sirve** para nuestro 3B. ⇒ la validación CPU gratis y directa **no es posible** para nuestro
modelo. La validación barata del MECANISMO requeriría una head de un modelo lo bastante chico
para correr en el i3 (target + head); los targets con head pública son ≥7B (pesados para 2c).

## Veredicto de scoping
**FACTIBLE y de alto valor (lever general 2–3×), pero GATED y con riesgo CPU sin validar.**
- No hay atajo gratis: el lever requiere **entrenar** una cabeza para el 3B-Coder en Kaggle
  (12–17h, 2 sesiones; **necesita autorización del dueño** por cuota GPU) y/o **validar el
  mecanismo EAGLE3-en-CPU** con una head de modelo chico (a buscar).
- Mientras tanto, los levers REALIZADOS hoy (gratis, medidos) son: **cascada 0.5B** (habla
  social, ~28 tok/s) + **ngram-mod** (código/RAG, bit-idéntico) + el **3B AR** para sustancia.
- **Recomendación al dueño:** si querés el 2–3× general, autorizá una sesión Kaggle para un
  **PoC de head mínima** (pocos steps) → convertir → medir en el i3. Eso vuelve la proyección
  un dato real o un null honesto con bajo costo, antes de la cabeza de calidad.
