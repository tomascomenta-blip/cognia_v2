# PLAN MoM → rango GLM 5.2 (mandato del dueño 2026-07-09)

Objetivo: que el MoM de Cognia (base Qwen2.5-Coder-3B Q4_K_M en CPU) rinda
**al nivel de GLM 5.2 en las tareas del producto**, con el mapa completo de
modelos/expertos a entrenar, parámetros, temas, por qué, y las técnicas que
funcionan con los recursos actuales (CPU i3 2-cores local + Kaggle 1×T4
~30 GPU-h/semana).

## 0. La tesis del plan (MEDIDA, no opinión)

El programa ya corrió el experimento decisivo tres veces con pre-registro:

| corrida | qué destilaba | resultado |
|---|---|---|
| E-RZN v1/v2 (~6 GPU-h) | razonamiento (STaR, CoT verificado) | **0.0pp** |
| E-COD (~4.6 GPU-h) | búsqueda (BoN@8 verificado por tests) | **+2pp n.s.** |
| E2-FINAL/ACCION (v2) | **FORMATO** tool-calling + identidad | **G2A 20→99.3, G3 0→90** |

Y el andamiaje de inferencia (cero entrenamiento) dio: stepwise **+22pp**
razonamiento, BoN+juez **+10pp** código duro, ejemplo-concreto **+62pp**
tool-calling.

**Regla de diseño**: se entrena un experto SOLO donde el gap es de
FORMATO/hábito (verificable con oráculo determinista); la capacidad se
compra con cómputo en INFERENCIA. Todo experto entra con pre-registro,
gates congelados, McNemar pareado y duelo en deploy — o no entra.

## 1. Qué significa "rango GLM 5.2" (honesto)

GLM 5.2 es un modelo gigante generalista; un 3B local NO va a igualarlo en
conocimiento abierto ni en generación libre. El terreno de competencia es
**las tareas del producto**, medidas con gates pareados. Estado actual:

| eje | Cognia MoM (medido) | GLM 5.2 (medido en este repo) | estado |
|---|---|---|---|
| tool-calling agente | 86-99 (andamiaje+experto) | referencia del duelo 2026-07-03 | **ALCANZADO** |
| diseño/arquitectura | 96.1 | 93.7 | **ALCANZADO** |
| código duro pass@1 | 40→50 con BoN+juez | ~50 (gate del duelo) | **ALCANZADO con andamiaje** |
| razonamiento G2R | 82 (stepwise v2) | no medido pareado | brecha desconocida → medir |
| español G5 | **56** | no medido pareado | **brecha propia: formato** |
| salidas estructuradas (JSON/tablas) | no medido | — | **gap de formato: candidato** |
| velocidad | ~8 tok/s CPU | API remota | otra dimensión (§4) |

Faltan 2 cosas para cerrar el rango en producto: (a) expertos de FORMATO
para los ejes flojos (G5, estructurado), (b) medición pareada vs GLM 5.2 en
los ejes no medidos (no asumir: medir con los mismos gates congelados).

## 2. El fleet completo: modelos, parámetros, tema, por qué

Todos los expertos son **LoRA r16 all-linear sobre el 3B** (NO modelos
nuevos): ~30M parámetros entrenables, **57-60MB** el GGUF f16 del adapter,
deploy como **adapter VIVO** sobre Q4_K_M con hot-swap por request (2-41ms
medido). El re-quant después del merge ENTIERRA el delta (~0.4% ≈ error
NF4) — por eso adapter vivo, nunca merge+requant.

| # | experto | tema / funcionalidad | por qué (evidencia) | dataset (verificado por) | gate congelado | costo |
|---|---|---|---|---|---|---|
| 1 | **accion** (v2, DEPLOYED) | formato ACCION tool-calling + identidad Cognia | gap formato puro: 20→99.3 | ejecución real de tools | G2A×147, G3×20 | hecho |
| 2 | **accion v3** | + cierre-con-output, multi-tool encadenado, mensajes de error accionables | E8 mostró el hábito "listo" vacío (hoy parcheado determinista; el v3 lo hace nativo) | loop real: trazas con RESULTADO ejecutar + cierre correcto | G2A sin regresión + batería E 17/17 + suite nueva cierres×50 | ~1.5 GPU-h (replay cacheado) |
| 3 | ~~espanol (G5)~~ **CERRADO 2026-07-10 sin GPU** | — | el diagnóstico por clases (diag_g5.py) mostró que G5=56% era ARTEFACTO: es_espanol fallaba respuestas cortas correctas ('Feliz', '7'). Instrumento arreglado → **G5 real = 72%** y los fallos restantes son TODOS de contenido (capacidad) → sin gap de formato que un adapter pague | — | — | 0 (el fix del instrumento dio +16pp gratis) |
| 4 | **estructura** (JSON/tablas/schemas) | emitir JSON válido contra schema, tablas MD, YAML | formato 100% verificable (json.loads + jsonschema); es EL tipo de gap donde el adapter paga | generación + validación programática (yield-band) | suite JSON×100 nueva congelada, ≥+15pp p<0.05 | ~2 GPU-h |
| 5 | **portero 0.5B** (modelo aparte, único no-LoRA) | clasificar/rutear turnos triviales (saludo, sí/no, comandos) a respuesta directa sin tocar el 3B | velocidad: 0.5B = **4.3× tok/s medido** en CPU; el MoM gana latencia percibida en el 80% de turnos cortos | ruteo léxico ya existente + fallback: si duda, pasa al 3B (cero riesgo) | escala: exactitud de ruteo ≥95% en suite de turnos×200; nunca responde solo si confianza < umbral | ~1 GPU-h (Qwen2.5-0.5B + LoRA) |
| 6 | **cabezas MTP/EAGLE** (investigación) | 2-3× decode en CPU (único speculative que respeta el ancho de banda: draft separado medido 0.37× = HUNDE) | velocidad §4; proyección, no medición → pre-registrar | entrenar cabezas sobre corpus propio | gate: ≥1.8× tok/s e2e REAL sin caída de gates de calidad | ~4 GPU-h + riesgo alto |

**NO se entrenan** (líneas cerradas con medición): experto razonamiento
(E-RZN×2), experto código-capacidad (E-COD), experto LCD (el gap era de
tools, cerrado con código 80→100%). Merges TIES/DARE entre adapters: se
pre-registran cuando haya ≥2 expertos conviviendo (hoy: accion + próximos).

## 3. La otra mitad del rango: capacidad por INFERENCIA (cero GPU)

Lo que ya está y se mantiene (es lo que cerró los ejes 1-3): stepwise CoT
por turno (v2, +22pp), BoN+juez con early-stop lossless, repair dirigido
con traceback real, decompose por dificultad, RAG 3-bandas
LOCAL/MEDIA/GLOBAL, HERMES self-tooling, skills con decay. Extensiones de
bajo costo pendientes de medir: self-consistency k=3 SOLO en ítems con
dificultad alta (gate: G2R +5pp sin 3× de latencia media — el gating por
dificultad ya existe), y verificador-por-etapa del árbitro LCD generalizado
a tareas multi-paso.

## 4. Velocidad (para "alcanzar" también hay que correr)

Techo físico medido: CPU i3 bandwidth-bound ~8 tok/s con Q4_K_M b9391
threads=3. Palancas EN ORDEN de costo/beneficio:
1. **Portero 0.5B** (experto #5): 4.3× en los turnos que rutea — barato y medido.
2. **Prompt/KV descuento**: cache_prompt=true en chat interactivo (ya activo;
   los benchmarks van sin cache por determinismo).
3. **Cabezas MTP** (experto #6): 2-3× proyectado, único speculative viable
   en CPU (draft separado 0.37×, spec-decode clásico descartado) — riesgo
   alto, pre-registrar.
4. GPU opcional del usuario: llama-server ya soporta offload si hay CUDA —
   no es plan, es configuración.

## 5. Técnicas de entrenamiento con los recursos actuales (todas ya validadas acá)

- **Receta E-GROK**: 1 epoch, lr 3e-4, warmup 10% (LambdaLR), LoRA r16
  all-linear, packing SEQ 1024, unsloth NF4 en T4 (+22% tok/s vs HF puro).
- **Replay anti-olvido**: mezcla ~35% de datos generales cacheados (DC-4);
  sin esto el experto olvida G1 (E2-FINAL v1: −8pp por 2 epochs).
- **Datasets verificados por ejecución/oráculo, nunca por LLM-juez**, con
  **banda de yield pre-registrada** que ABORTA si el generador es trivial o
  imposible (lección E-RZN v1: yield 86% = señal cero).
- **Pipeline**: dataset en CPU local (o in-kernel) → kernel Kaggle
  (dataset versionado + kernel push + monitor + download; PYTHONUTF8=1;
  detached con Start-Process en Windows) → GGUF f16 del adapter
  (convert_lora_to_gguf) → duelo en deploy con McNemar → si gana, asset al
  release fleet-v1 + adapters.json.
- **Suites congeladas por sha256 ANTES de medir**; McNemar pareado; regla
  del instrumento: cache_prompt=false y matar llama-server entre brazos.
- **Presupuesto**: ~30 GPU-h/semana Kaggle. El plan completo (#2,3,4,5)
  ≈ 6.5 GPU-h + gates locales ≈ 1 semana de cuota con margen. #6 (MTP) solo
  si los 4 primeros cierran.

## 6. Orden de ejecución y criterio de corte

1. ~~espanol~~ CERRADO: el gap era del INSTRUMENTO (es_espanol vs respuestas
   cortas); G5 real = 72% y el resto es capacidad. Método confirmado: medir
   el gap POR CLASES antes de gastar GPU cazó esto en 2 min de CPU.
2. **estructura** (#4): PRIMERO medir el gap por clases (diag como G5/LCD);
   solo si es de formato → suite JSON×100 + kernel.
3. **accion v3** (#2): trazas de cierre-con-output del loop real.
4. **portero 0.5B** (#5): velocidad percibida.
5. Medición pareada vs GLM 5.2 en G2R y estructurado (los ejes sin duelo).
6. **MTP** (#6) solo con 1-5 cerrados y cuota sobrante.

Corte honesto por experto: si el gate pre-registrado FALLA una vez, se
ajusta UNA vez (dataset o detector, no el gate); si falla de nuevo, la
línea se cierra y se documenta — el patrón E-RZN/E-COD: un negativo limpio
vale más que un adapter dudoso en producción.
