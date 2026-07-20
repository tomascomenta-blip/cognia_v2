# 13 — Teoría: RSI / self-scaffolding + auto-prompting en Cognia

**Corrida 2026-07-04 (/goal).** Cómo hacer que Cognia se AUTO-MEJORE sin poder
tocar los pesos del modelo (3B cuantizado, CPU, QLoRA bloqueado), y cómo optimiza
sus propios prompts (incluida la hipótesis "prompt menos detallado, más válido").

> La síntesis de la literatura (§1) se completa desde la investigación multi-agente
> lanzada en paralelo; esta versión fija la TEORÍA y el DISEÑO ya fundamentados en
> el código real del repo. Los números de la corrida real están en §6.

---

## 0. La tesis en una línea

Con los **pesos congelados**, el único grado de libertad para auto-mejorar es el
**andamiaje** (scaffolding): los prompts, el few-shot, las reglas, las
herramientas y la lógica del loop que envuelven al modelo. Cognia ya tiene un
lazo de auto-extensión **verificado** para HERRAMIENTAS (HERMES). RSI aquí =
**extender ese mismo patrón `generar → verificar → seleccionar → revertir` a los
PROMPTS**, con **medición real** como único árbitro. No es "el modelo se reescribe
a sí mismo"; es "el sistema reescribe lo que rodea al modelo, y solo conserva lo
que un benchmark demuestra que mejora".

Esto es exactamente lo que la literatura factible dice que se puede hacer sin
reentrenar: STOP (mejorar el scaffold con un LLM congelado), APE/OPRO/PromptBreeder
(generar y seleccionar prompts por puntaje), Darwin Gödel Machine (archivo
evolutivo gobernado por un benchmark). La restricción "no tocar pesos" no lo
impide — lo re-localiza al andamiaje.

---

## 1. Síntesis de literatura (investigación multi-agente, 2026-07-04)

Investigado con 14 agentes en paralelo; informes completos con fuentes en
`MANAGER_LOG` y scratchpad. Lo que fija el diseño:

### RSI / self-scaffolding
- **El eje que parte la familia:** *tocan los pesos* (Gödel machine — ideal
  irrealizable; SEAL — gradientes, ARC 20→72.5% pero **inaplicable sin fine-tune**)
  vs *solo tocan el andamiaje/código* (STOP, ADAS, AlphaEvolve, Voyager, **Darwin
  Gödel Machine**). El segundo bloque es el régimen de Cognia.
- **Darwin Gödel Machine (Sakana 2025)** — el más cercano: archivo evolutivo de
  agentes-código, LLM congelado reescribe el andamiaje, **el benchmark es el
  fitness**. SWE-bench **20→50%**, Polyglot **14.2→30.7%** en 80 iteraciones.
  Ablación: *self-modificación Y archivo open-ended* ambos necesarios. Se
  auto-descubrió: edición granular, **validar el parche antes de commitear**,
  memoria de errores, **best-of-N con juez**.
- **STOP (2023)** — advertencia dura: con un modelo DÉBIL el self-design **falla**
  (GPT-3.5 ~12% de éxito). ⇒ **el 3B NO debe ser su propio meta-agente.**
- **ADAS (2024)** — meta-agente programa agentes; las mejoras **transfieren entre
  modelos** (diseñado en GPT-3.5, gana también en GPT-4/Claude): invertir en el
  andamiaje paga aunque el 3B se reemplace.
- **Voyager (2023)** — skill library: una skill entra **solo si el entorno la
  verificó**; se recuperan top-k por similitud (controla el prefill).
- **Límites (vinculantes):** auto-corrección SIN feedback externo **degrada**
  (GSM8K 95.5→91.5%); "alignment tipping" bajo auto-evolución (uso de tools
  8%→0-2% en 1-3 rondas); reward hacking; model collapse. **El bucle solo mejora
  mientras el verificador sea más fuerte que el generador.**

### Auto-prompting
- **OPRO se ROMPE en modelos chicos** (réplica *Revisiting OPRO*): Mistral-7B
  37.5→**32.1**, LLaMa-70b 39.4→**28.0** — peor que zero-shot CoT. El 3B cae del
  lado donde OPRO no funciona como optimizador. **Confirma no usar el 3B para
  reescribir sus prompts.**
- **BootstrapFewShot (DSPy) = el ganador costo-efectivo:** no inventa ejemplos,
  **cura las trazas que el propio verificador marcó correctas** y las inyecta como
  few-shot. Es *exactamente* el lever ya medido aquí (2 ejemplos concretos:
  24→86%), sistematizado. Es la forma más literal de "la IA mejora sus propios
  prompts".
- **Compresión paga doble en modelos chicos:** sobre-instruir **DEGRADA** (un 4B:
  fallos críticos 2.4-7.5% → **4.8-45.5%** al agregar instrucciones). "Prompt menos
  detallado, más válido" tiene respaldo empírico — puede SUBIR accuracy, no solo
  bajar costo. LLMLingua: hasta 20× compresión con ~1.5 pts de caída.
- **PromptBreeder:** el prompt óptimo suele ser **corto y contra-intuitivo**
  (ganó "SOLUTION:"). Operador Lamarckian = inferir el prompt desde trazas OK.
- **Trampas:** overfitting al benchmark (→ held-out), no-transferencia entre
  modelos (→ validar en el modelo destino), crítico débil (→ gate por señal
  externa), cuantización cambia el óptimo (→ medir en el binario real).

**Convergencia:** población N=1-3, **mutaciones dirigidas (no muestreo ciego)**,
fitness = **verificador determinista externo** barato, eval agéntica cara solo como
compuerta final. Copiar el **mecanismo**, nunca el **presupuesto** (DGM = 80 iter ×
2 semanas). Todo esto es exactamente lo implementado en §4.

---

## 2. Qué es factible en Cognia (el filtro duro)

| Recurso | Estado | Consecuencia de diseño |
|---|---|---|
| Pesos del modelo | **Congelados** (QLoRA bloqueado en CPU i3) | Solo se evoluciona el andamiaje, no el modelo. |
| Evaluación | **CARA**: ~34 s/item, 200 items = ~112 min | Dev chico para iterar; test held-out para reportar. Presupuesto de evals es la restricción activa. |
| Optimizador candidato | El **mismo 3B débil** | NO se confía en el 3B para reescribir el prompt (OPRO puro es frágil con optimizador débil). Mutaciones concretas + árbitro empírico. |
| Prefill | **Caro** (cada token de prompt cuesta en cada paso) | El costo (tokens) es un objetivo, no solo la accuracy → gate Pareto. Esto motiva "menos detallado, más válido". |
| Self-tooling | **Ya existe y verificado** (HERMES, sandbox) | El patrón de auto-mejora ya está probado para tools; se reusa para prompts. |

**Conclusión:** el mecanismo factible es **búsqueda evolutiva/APE de andamiaje con
LLM congelado, gate de no-regresión sobre DEV, y reporte honesto sobre TEST
held-out**, minimizando evals. No Gödel machine formal (irreal), no OPRO puro
(optimizador débil), no fine-tuning (bloqueado).

---

## 3. El patrón unificador: RSI = HERMES extendido de tools a prompts

Cognia ya corre este lazo para HERRAMIENTAS (`cognia/agent/tool_synthesis.py`):

```
proponer código de tool → verificar en sandbox (ejecución real + scan estático)
                         → registrar SOLO si pasa → rollback si una versión sale peor
```

`handle_live_failure` incluso repara una tool ante un fallo en vivo y revierte si
el fix no sobrevive. **Eso ya es auto-mejora verificada.** Lo que faltaba: el mismo
lazo para los **PROMPTS**. La simetría es exacta:

| HERMES (tools, ya existe) | prompt_evolution (prompts, nuevo) |
|---|---|
| propone `def run(args)` | propone un `Scaffold` (system+fewshot+repair) |
| verifica en sandbox (ejecuta) | puntúa contra el modelo real en DEV |
| registra si pasa el test | adopta si pasa el gate de no-regresión |
| `rollback_tool` si empeora | mantiene incumbente si el candidato no mejora |
| `record_tool_use` (telemetría) | buckets de error dirigen la próxima mutación |

RSI de Cognia = **ambos lazos operando sobre un modelo congelado**: evoluciona las
herramientas Y los prompts que las manejan, con medición como árbitro. Es el
análogo a la Darwin Gödel Machine a nivel de andamiaje (archivo de mejoras
gobernado por un benchmark), acotado a lo que corre en CPU.

---

## 4. Auto-prompting: el diseño concreto (implementado)

**Módulo `cognia/agent/prompt_evolution.py`** (ya en el repo, 11 tests verdes):

- **`Scaffold`**: `(system_prompt, fewshot[], repair_hint)`. La semilla == el
  andamiaje v1 medido (86% en la slice). `token_cost()` = proxy de prefill.
- **`score_scaffold`**: corre el andamiaje sobre items con el modelo real
  (callable `generate` inyectable → testeable con backend falso). Devuelve
  accuracy + **buckets de error** + costo. El oráculo es el checker AST congelado
  de BFCL (cero cambios al juez → no se puede hacer trampa).
- **`bootstrap_exemplars` (DSPy BootstrapFewShot, el mecanismo #1):** corre el 3B
  sobre un set HARVEST, **se queda con las respuestas que el oráculo marca
  correctas**, y las usa como few-shot **verificados y solo-formato** (sin el
  schema pesado → baratos en prefill). Prioriza categorías débiles y respuestas
  cortas. Es "la IA mejora su prompt con sus propios éxitos". Anti-leakage:
  harvest ⟂ tune ⟂ test.
- **Operadores de mutación keyed a los buckets de error medidos** (STOP-style:
  leer el fallo → proponer el remedio):
  - `value_error:string` → regla "copiá los strings EXACTOS".
  - `wrong_func_name` → regla "nombres de función EXACTOS".
  - `wrong_count` (paralelas) → regla "UNA llamada por acción, contá".
  - + few-shot dirigidos (paralela-múltiple, string-exacto).
  - **`compress_system` y `minimal_system`** → recortan / minimizan el
    system-prompt (eje "menos, más válido"; respaldado por que sobre-instruir daña
    al 3B). Compiten como candidatos de pleno derecho: pueden ganar por accuracy,
    no solo por costo.
- **NO usa el 3B para proponer mutaciones** (OPRO falla en modelos chicos): la
  inteligencia está en los operadores concretos + el árbitro empírico, no en pedirle
  al 3B débil que se auto-optimice. Esta es la lección central de la investigación.
- **`evolve`**: búsqueda APE/PromptBreeder sobre DEV. Cada ronda propone
  mutaciones, las puntúa, y **adopta la mejor que pase el gate**:
  - Acepta si sube accuracy > `min_gain`, **o** (Pareto) si iguala accuracy con
    **menos costo** → así "menos detallado, más válido" se acepta *cuando la
    evidencia lo respalda*, no por fe.
- **Separación DEV/TEST** (`cognia_v3/eval/bfcl_split.py`): el optimizador SOLO ve
  DEV (40 items); el número honesto se mide sobre TEST held-out (160) → no
  overfittea la slice (la trampa #1 de la literatura de prompt-optimization).
- **Persistencia gated**: el ganador se publica para el loop en vivo **solo si NO
  regresiona en TEST**. Si overfittea DEV y empeora en held-out, se descarta y se
  reporta honestamente.

**Runner real** `cognia_v3/eval/run_prompt_evolution.py` (`--smoke/--fast/--full`,
escritura incremental para corte-seguro).

### "Un prompt menos detallado se vuelve más válido" — las dos caras

1. **Lado sistema (compresión):** el operador `compress_system` + gate Pareto
   buscan el andamiaje MÁS CORTO que mantiene la accuracy. Motivado por el prefill
   caro y respaldado por LLMLingua. Medible: costo en tokens ↓ con accuracy ≥.
2. **Lado usuario (inducción/expansión):** un prompt vago del usuario se vuelve
   efectivo porque el ANDAMIAJE aprendido compensa (few-shot + reglas hacen que
   el 3B no necesite que el usuario detalle el formato). Ya visto aquí: 2 ejemplos
   concretos > cualquier instrucción abstracta (24%→86%). Extensión opcional:
   `task_rewrite` (APE instruction-induction) que expande la tarea terse a una
   precisa desde un banco aprendido de pares vago→preciso.

---

## 5. Integración con el loop actual de Cognia

- **Loop agéntico (`cli.py` `_run_agent_task`):** ya inyecta few-shot dirigido
  (`fewshot.py`) y carga tools auto-generadas (`load_generated_tools`). Se agrega
  `prompt_evolution.load_best()` → las REGLAS genéricas de tool-calling que la
  evolución demuestre (nombres/strings/conteo exactos) se pliegan al `TOOLS_DOC`
  del loop. **Con medición, no por fe**: la transferencia BFCL→loop-en-vivo se
  declara como plausible y se valida en un puñado de tareas e2e reales, no se
  asume.
- **Looped Transformer (xarch/xfinal):** el auto-prompting requiere un modelo que
  siga instrucciones; el tiny entrenado desde cero NO lo es. El análogo aplicable
  ahí no es "optimizar el prompt" sino **cómputo adaptativo** (cuántas vueltas del
  loop gastar por token/tarea) — se trata como nota exploratoria honesta (§CP9),
  no como integración de prompts.

---

## CP9 — El "loop transformer" como sustrato (nota exploratoria honesta)

El dueño pidió implementar esto "con el actual loop transformer". Hay dos lecturas
y conviene separarlas, porque colapsarlas produce claims falsos:

**Lectura A — el LOOP AGÉNTICO (`_run_agent_task`).** Es *el* loop de Cognia como
agente: ReAct con presupuesto dinámico de pasos. **Este es el target real** y ya
está integrado (§5, CP7): las reglas de tool-calling que la evolución valida se
pliegan a su `TOOLS_DOC`. Auto-prompting aplica de lleno porque el 3B Qwen SÍ sigue
instrucciones.

**Lectura B — el LOOPED TRANSFORMER (xarch/xfinal, `looped2x4`).** Es una
*arquitectura*: pocas capas con pesos COMPARTIDOS iteradas N vueltas (Universal/
Looped TF; Dehghani 2018, Giannou 2023), medida en T4 (xarch: `looped2x4` supera a
`vanilla2` con los mismos params → compra profundidad efectiva sin params). Acá el
auto-prompting **no aplica y decir lo contrario sería deshonesto**: ese tiny está
entrenado desde cero sobre wiki/code/stories (37-97M), **no sigue instrucciones** —
no hay "prompt" que optimizar en el sentido de APE/OPRO. Un system-prompt o few-shot
no significan nada para un modelo que nunca vio el paradigma instrucción→respuesta.

**El análogo correcto y honesto para B: cómputo adaptativo, no optimización de
prompts.** Lo que en un modelo grande hace el prompt ("pensá más", "step by step"),
en un looped transformer lo hace el **número de vueltas**: gastar más loops = más
"pensamiento" por token. La versión RSI de esto es **halting adaptativo** (ACT,
Graves 2016; PonderNet): que el modelo APRENDA cuántas vueltas gastar por token/
posición según dificultad, en vez de un N fijo. Eso es "self-improvement" del
cómputo (data-dependent depth), medible con un oráculo barato (loss/accuracy vs
FLOPs), y encaja con el hallazgo de F-SPEED (en CPU bandwidth-bound, el tamaño y el
cómputo por token son las palancas). **Puente conceptual:** "un prompt menos
detallado más válido" (lado A) ≙ "menos vueltas que bastan" (lado B) — ambos son el
mismo principio de *asignar el mínimo cómputo/contexto que resuelve la tarea*, con
gate empírico. Pero son mecanismos DISTINTOS; no se implementan con el mismo código.

**Estado:** Lectura A implementada y medida (§4-6). Lectura B queda como
experimento CPU-first bien acotado y NO ejecutado en esta corrida (halting
adaptativo sobre el tiny: baseline N fijo vs N aprendido, misma calidad con menos
FLOPs). Marcarlo hecho sin correrlo sería el tipo de overclaim que el método del
repo prohíbe.

---

## 6. Resultado de la corrida real (antes/después)

Corrida `--fast` (`ap_fast_v3`, 2026-07-04, Qwen2.5-Coder-3B-Q4_K_M, ~92 min de
generación real). DEV=20 (harvest 10 / tune 10), **TEST held-out=50** (10/cat).
Todos los números medidos con el 3B de verdad; el gate y el reporte usan el checker
AST congelado + McNemar.

**Trayectoria (DEV/tune):** el bootstrap cosechó 2 exemplars verificados pero NO
superó a la semilla en tune → arrancó de `v1_seed`. La evolución adoptó
`v1_seed+min` (**system-prompt mínimo**) vía el gate Pareto: misma accuracy (0.900)
con menos costo. Camino aceptado: `v1_seed → v1_seed+min`.

**TEST held-out (antes/después HONESTO):**

| | accuracy | costo prompt (tokens) |
|---|---|---|
| Semilla v1 (afinada a mano) | **0.800** | 936 |
| Ganador `v1_seed+min` | **0.800** | **699 (−25%)** |
| Delta | **+0.000** | −237 |

**Veredicto McNemar:** el ganador arregla 1 item y rompe 1 (neto 0) → **p=1.0, NO
significativo**. Por categoría no hay cambio material (parallel_multiple 7/10,
live_simple 5/10 en ambos). Persistido en vivo: **NO** (el gate exige mejora de
accuracy significativa; correctamente no toca el andamiaje live).

**Lectura honesta:**
1. **Ganancia real: COSTO, no accuracy.** La evolución **descubrió con el modelo
   real que un system-prompt 25% más corto rinde EXACTAMENTE igual** que el v1
   afinado a mano sobre tareas held-out. Es una demostración empírica directa de
   *"un prompt menos detallado se vuelve (igual de) válido para la IA"*: un óptimo
   de Pareto (misma calidad, −25% de prefill) — dinero gratis en un sistema
   CPU-bound con prefill caro. Coincide con la evidencia (sobre-instruir no ayuda
   a un 3B; LLMLingua).
2. **En accuracy NO superó al baseline fuerte** (0.80 = 0.80), y el método lo dice
   sin adornos: el árbitro McNemar reporta "sin mejora demostrada" en vez de vender
   el ruido. Ese es exactamente el valor del método — **la MEDICIÓN honesta**, no
   un número inflado. El v1 (few-shot=2 + repair) ya es un andamiaje fuerte; los
   fallos restantes (value-formatting en parallel_multiple/live_simple) no los
   cracó la búsqueda en un tune de 10 items.
3. **El ciclo review→fix pagó:** sin los 5 fixes, esta misma corrida habría
   reportado un flip dentro del ruido como "mejora" y habría publicado un andamiaje
   contaminado por el bootstrap truncado. El árbitro estadístico convirtió un
   resultado potencialmente engañoso en uno honesto.

**Frontera:** más presupuesto de eval (tune/test más grandes, `--full`) para
detectar mejoras chicas con poder estadístico; operadores dirigidos a los buckets
value-formatting que dominan el 20% restante; y compounding entre corridas (archivo
DGM). El andamiaje mínimo validado (−25% costo, misma calidad) queda disponible como
optimización de costo si se decide adoptarlo (no auto-persistido por el gate
conservador de accuracy).

---

## 7. Trampas declaradas (de la literatura, aplicadas aquí)

1. **Overfitting al benchmark** → separación DEV/TEST + persistencia gated en test.
2. **El optimizador débil** (el 3B) propone mal → mutaciones concretas + árbitro
   empírico, no OPRO puro.
3. **No-transferencia entre modelos/tareas** → el andamiaje ganador es específico
   del 3B+BFCL; su uso en el loop en vivo se valida, no se extrapola.
4. **Costo de eval** (el cuello real) → dev chico, evals presupuestadas, escritura
   incremental corte-segura.
5. **Goodhart** → el oráculo (checker AST) es congelado e inmodificable por el
   optimizador; solo cambia el andamiaje de generación.
