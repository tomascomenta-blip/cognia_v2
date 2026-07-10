# Pre-registro E-PORT — portero 0.5B del MoM (PLAN_MOM_GLM52 #5)

CONGELADO ANTES DE CORRER (2026-07-10 ~02:00). Único experto del plan que
sobrevivió los diagnósticos por clases de esta noche (español: gap era del
instrumento; estructura: 83% base, sin gap; código/razonamiento: cerrados).

## Qué es

Un **modelo aparte** (Qwen2.5-0.5B-Instruct, no LoRA del 3B): atiende los
turnos TRIVIALES del chat (saludo, identidad, sí/no, cortesía) a **4.3×
la velocidad** del 3B en CPU (medido, exp021/F-SPEED: el tamaño del modelo
es EL lever en CPU bandwidth-bound). El router léxico decide qué le llega;
ante cualquier duda pasa al 3B (fallback = cero riesgo de calidad).

## Esta corrida (kernel `cognia-eport`, <1 GPU-h)

Entrena LoRA r16 all-linear (receta E-GROK: 1 epoch, lr 3e-4, warmup 10%)
sobre el 0.5B con `e1_train.jsonl` (dataset emix ya en Kaggle: 1344 pares
generales+identidad, 767 mencionan Cognia) y evalúa PAREADO base-vs-adapter
en las suites congeladas.

## Predicciones (gates)

- **P-PORT-1 (gate de promoción)**: G3 identidad (0.5B+adapter) ≥ **90%**
  (18/20). El 0.5B base dice "Qwen"/nada → se espera salto tipo ACCION
  (gap de FORMATO/hábito puro, donde el adapter SÍ paga — 2 positivas
  previas del programa).
- **P-PORT-2 (informativo, no gate)**: G1×100 del 0.5B+adapter se REPORTA
  para diseñar el umbral del router (qué clase de turnos puede atender).
  No se interpreta como éxito/fracaso: el portero no es un generalista.

Si P-PORT-1 falla una vez: se ajusta el mix (más peso identidad) y se
re-corre UNA vez; si falla de nuevo, línea cerrada (patrón del programa).

## Qué NO afirma esta corrida

- No mide la velocidad (ya medida en CPU: 4.3×; el kernel corre en GPU y
  ese número no aplica al deploy).
- No integra el router al CLI (fase 2: regla léxica + fallback + gates e2e
  del producto, con el patrón fleet ya validado).
