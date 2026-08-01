# PREREG — LoRAs públicos intercambiables para la flota (2026-08-01)

*Autorizado por el dueño en vivo ("investiga muchos loras para la flota y si
quieres haz pruebas con ellos"): red para descargar adapters y GPU para
inferencia de prueba. Inventario previo por workflow (8 agentes, 2026-08-01):
top-7 candidatos y huecos en la síntesis del task `wjea4xpfi`. Este prereg
fija las pruebas ANTES de descargar o correr nada. Revisión adversarial
pre-GPU obligatoria.*

## Lo que el inventario dejó claro (contexto, no lectura)

- **NO existe adapter público de código para gpt-oss-20b** (todo lo
  etiquetado era modelo fusionado). Competitive coding sobre Qwen-Coder:
  vacío. La expectativa global honesta es **nulos bien medidos**; el valor
  duradero es dejar PROBADO el pipeline PEFT→GGUF-LoRA→swap, prerequisito de
  entrenar LoRA propio.
- El MDE de generación en hard (n=80, ~10-13 tareas) hace SIN POTENCIA
  cualquier prueba de "LoRA generador mejora el banco": **no se corre
  ninguna**. Lo único con potencia es medir un adapter como SELECTOR/señal
  (reutiliza candidatos ya generados) o como gate técnico de actividad.

## FASE 0 — gate de ACTIVIDAD del pipeline (sin este PASS, todo lo demás es humo)

**Amenaza que ataca**: el no-op silencioso — `convert_lora_to_gguf.py` salta
tensores sin avisar y el server carga un adapter vacío sin error (feasibility
verificada en código de llama.cpp, 2026-08-01). Es "Cognia degrada en
silencio" aplicado a LoRAs.

| | |
|---|---|
| adapter | `ggml-org/LoRA-Deepthink-Reasoning-Qwen2.5-7B-Instruct-Q8_0-GGUF` (conversión oficial ggml-org: CERO conversión nuestra; existencia verificada por API 2026-08-01) |
| base ANCLADA | `C:\Users\usuario\.cognia\models\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf` (sharded, ya en disco) |
| server | llama-server de la flota, **VERIFICADO localmente (b10066, 86a9c79f8)**: `--lora`, `--lora-scaled FNAME:SCALE` y `--lora-init-without-apply` + `POST /lora-adapters` existen. Diseño elegido: **UN solo proceso** con `--lora-init-without-apply`, alternando escala por el endpoint (elimina la no-reproducibilidad entre arranques). El flag "-cram 0" del agente de feasibility NO existe en esta build: descartado |
| decodificación | determinista: temperature 0, top_k 1, seed 20260801, n_predict 128 |
| prompts | 3 fijos, escritos en el script antes de arrancar: razonamiento corto, código corto, neutro |

**Condiciones**: A = base sin adapter · B = adapter a escala 1.0 · C = adapter
a escala 0.0 (por `--lora-scaled` o por el endpoint de runtime, lo que exista).

**PASS pre-registrado (los 4 a la vez)**:
1. B ≠ A en al menos 1 de los 3 prompts (el adapter HACE algo);
2. C = A token a token en los 3 (la escala manda: a 0 es exactamente la base);
3. B coherente (sin bucles: ningún trigrama repetido >8 veces; longitud >0);
4. log del server sin errores de tensores/carga del adapter.

**Si FALLA cualquiera → se documenta y se PARA la vía de adapters
descargables** (las fases 1-2 dependen del pipeline). No hay reintento con
otro adapter hasta diagnosticar la causa.

## FASE 1 — RankEF como FABRICANTE DE SEÑAL sin ejecutar tests (la única prueba con potencia)

**Pregunta**: ¿un ranker entrenado con execution feedback
(`therealanonymous/Qwen2.5-Coder-14B-Instruct-ft-RankEF`, base coder-14B ya
en flota) lleva señal para elegir el candidato correcto SIN ejecutar nada —
el cuello histórico del goal — medida contra el AZAR?

**Potencia calculada ANTES (desde disco, `reparacion.json`; recomputable con
`scratchpad/potencia_rankef2.py`)**:

| | |
|---|---|
| pools TOTALES (bon+rep+pla) discriminantes en ocultos | **37** (mediana 8 candidatos) |
| AZAR esperado | 10.5 / 37 |
| **nulo simulado (10k réplicas, semilla 20260801): p95** | **15** · p99 = 17 |
| referencia superior (selector con tests ejecutables) | 35 / 37 |
| headroom sobre el selector ejecutable (pools bon) | +2 → **SIN POTENCIA para "batir al selector": no se afirma nada ahí, descriptivo** |

**Lectura pre-registrada**: VIVE si aciertos > 15 (p95 del nulo); KILL si
≤ 15. La comparación con el selector ejecutable es descriptiva. Éxito del
candidato elegido = su `pasa_oc` ya registrado (cero juicios nuevos; GPU solo
para el RANKING).

**Mecánica e instrumento**:
- Conversión: `convert_lora_to_gguf.py` con
  `--base-model-id Qwen/Qwen2.5-Coder-14B-Instruct` (o `--base` con la base
  descargada si la conversión exige el index completo — presupuestado).
  Outtype f16. Dry-run primero.
- Server: coder-14b GGUF de la flota + adapter (un adapter por proceso).
  Gate de actividad (como F0, condiciones A/B/C) ANTES de rankear nada.
- **RIESGO DECLARADO — formato del prompt de ranking no documentado** en el
  card del adapter. Mitigación pre-registrada: (a) inspeccionar el repo
  buscando el formato de entrenamiento; (b) si no aparece, DOS formatos
  fijos escritos antes de correr (F-A: enunciado + candidatos numerados +
  "answer with the number of the most likely correct candidate"; F-B: el
  mismo con instrucción de análisis breve previa), corridos AMBOS sobre los
  37 pools y reportados AMBOS. Si discrepan en el veredicto VIVE/KILL, se
  dice y NO se firma ninguno.
- Orden de candidatos aleatorizado por pool (semilla 20260801), permutación
  registrada (mata el sesgo posicional).
- Elección no parseable = fallo del MÉTODO (se reporta tasa); si >10% de los
  pools, se PARA y se reproduce a mano antes de analizar.
- Control de cordura pre-registrado: el MISMO protocolo con la base SIN
  adapter (¿el coder-14b pelado ya rankea sobre el azar? si base ≈ adapter,
  el adapter no aporta — se dice). Tres brazos: AZAR (simulado) / BASE /
  ADAPTER.

## FASE 2 — gate gpt-oss-20b + MXFP4 (solo si F0 PASS)

Adapter `artindnr/gpt-oss-20b-multilingual-thinking` (atención; no toca los
tensores MXFP4 — feasibility leída en código, ruta plausible-no-probada, cero
issues upstream). Conversión propia → gate de actividad A/B/C idéntico a F0
sobre gpt-oss servido con la config de la flota. **Solo actividad + una
no-regresión descriptiva** (20 tareas easy/medium ancladas: las 20 primeras
del orden de `frontier_k3_orden.json` que no sean hard, greedy, apareado
intra-corrida base-vs-adapter; se reporta el neto sin umbral — n chico,
descriptivo declarado). El objetivo es abrir o cerrar POR MEDICIÓN la ruta
"adapters sobre el pensador", no medir calidad.

## Qué NO se hace (pre-registrado)

- Ningún benchmark de generación con adapter en el banco (SIN POTENCIA).
- Nada de VL (VisJudge/relsim): bloqueados hasta que exista banco de pares
  control (el juez web está al nivel del azar y mediría el marco).
- No se adopta nada en producto en esta pasada: esto es medición.

## ENMIENDA 1 (2026-08-01, tras revisión adversarial pre-gasto: 3 BLOQUEA + 6 advertencias, TODAS aplicadas)

1. **[BLOQUEA] El umbral de F1 estaba corrompido por una heurística gratuita.**
   Verificado por el refutador con código propio: "elegir el ÚLTIMO candidato
   generado" saca **19/37** (el bucle de reparación PARA al acertar → la
   última posición está enriquecida: 47-53% vs 6-10% las anteriores). Un
   RankEF con 16-19 habría firmado VIVE siendo peor que gratis. Nulos
   pre-registrados AHORA (los tres de la casa): azar simulado (p95=15) ·
   último-generado (**19**) · más-largo (14) · primero (2). **Dos lecturas
   separadas: "lleva señal sobre el azar" si >15; "ÚTIL para el goal" solo
   si >19** (bate al mejor nulo gratuito). Solo la segunda abre vía.
2. **[BLOQUEA] F0 re-mecanizada a UN solo proceso** (el criterio C=A entre
   dos procesos no lo garantiza el instrumento, y `--lora-scaled` revienta
   con rutas absolutas de Windows — verificado en el binario: el `:` de
   `C:` rompe el split FNAME:SCALE). Diseño final: arrancar con
   `--lora-init-without-apply --lora <ruta absoluta>` (sin escala en el
   flag); A = estado inicial (adapter cargado, NO aplicado), B = `POST
   /lora-adapters [{"id":0,"scale":1.0}]`, C = `POST ... scale 0.0`;
   `cache_prompt: false` en TODA petición (el KV cacheado bajo la escala
   anterior contaminaría en silencio). Rescate pre-registrado: si C≠A token
   a token, volcar logprobs en la primera divergencia; margen de argmax
   <1e-3 = límite del instrumento (el gate PASA con B≠A ∧ B≠C ∧ C≈A en
   logprobs), NO se mata la vía por eso.
3. **[BLOQUEA] F1 y el contexto: prohibido truncar, jamás.** Los pools
   grandes (~7.7k tokens solo de candidatos) no caben en el ctx 8192 por
   defecto. ANTES de rankear nada: tokenizar los 37 prompts completos vía
   `/tokenize` y fijar `--ctx` ≥ máximo + margen de generación (16384
   probable; verificar que el 14B + KV cabe, `--cache-type-k q8_0` si hace
   falta). Un pool que no quepa se EXCLUYE ENTERO (idéntico en los 3
   brazos) y **toda exclusión recomputa los nulos sobre el n analizado**
   (misma semilla, `potencia_rankef2.py`) reportando ambos denominadores.
4. **`--sin-draft` OBLIGATORIO en F0/F1/F2**: `servir_modelo.py` auto-engancha
   el draft 0.5B por matching de nombre; el batching especulativo rompe la
   comparación token-exacta y el adapter no se aplica al draft (patrón de
   aceptación distinto entre brazos = señal falsa).
5. **ADAPTER−BASE con estadístico y potencia declaradas**: test de signos
   sobre pools discordantes; con n=37 el MDE apareado es ~+6-8 netos →
   **contraste probablemente SIN POTENCIA: se declara descriptivo** salvo
   efecto ≥ MDE. El titular nunca atribuye al adapter lo que pueda ser del
   14B pelado.
6. **Formatos de prompt**: si F-A y F-B discrepan en el veredicto, el cierre
   es **"sin veredicto: señal frágil al prompt"** (eso ya es un dato final).
   Cualquier formato adicional exige ENMIENDA previa. La regla del 10% no
   parseable aplica POR formato y POR brazo.
7. **Qué ve el ranker**: SOLO enunciado + `_code` de cada candidato. Nunca
   `crudo`, `contraejemplo`, `instrumento`, `segundos` ni `tok_*` (metadatos
   correlacionados con el veredicto). Candidatos vacíos se incluyen tal
   cual (consistente con el azar simulado, que ya los incluye).
8. **Determinismo entre arranques**: donde un diseño obligue a procesos
   separados, gate previo A1=A2 (correr el brazo A dos veces desde dos
   arranques y exigir identidad token a token antes de comparar nada).
9. **F2 acotada a humo de rotura gorda**: n_predict holgado (≥ p99 de
   tokens de salida del frontier en esas 20 tareas), `finish_reason` por
   muestra, tasa de truncado POR BRAZO junto al neto (un adapter "thinking"
   alarga el razonamiento: truncado asimétrico = regresión falsa). Solo un
   efecto ≥8/20 o rotura (vacías, 0/20) recibe lectura verbal.

## ENMIENDA 2 (2026-08-01, hallazgo de instrumento en la primera corrida F0)

La corrida 1 de F0 (guardada en `b4_loras/f0_gate.json`) FALLÓ el criterio
literal "C==A" y el patrón diagnostica el porqué: **A == B byte-exacto en los
3 prompts y C ≠ ambos** — en b10066, el estado inicial con
`--lora-init-without-apply` queda con el adapter YA a escala 1.0 (el GET
/lora-adapters lo reporta así). Mi supuesto "inicial = no aplicado" era
falso; la ACTIVIDAD del adapter y el mando de la escala quedaron demostrados
de rebote (escala 0 ≠ escala 1; y dos corridas a escala 1 en momentos
distintos del MISMO proceso salieron byte-idénticas: el determinismo
intra-proceso se confirma). Protocolo corregido, mismo espíritu:
**S0₁ = POST escala 0 → S1 = POST escala 1 → S0₂ = POST escala 0.**
PASS = S1 ≠ S0₁ en ≥1 prompt ∧ S0₁ == S0₂ token a token en los 3 (ida y
vuelta de escala reproducible) ∧ S1 coherente ∧ log limpio. El resto de la
enmienda 1 no cambia.

## ENMIENDA 3 (2026-08-01, tras la corrida 1 de F1: dos defectos de MI instrumento)

*Estado al escribirla (se declara: estos números ya se vieron): corrida 1 en
crudo dio BASE_FA 14/37, BASE_FB 14/37, ADAPTER_FA 10/37 con 4 no parseables
(11% → PARAR pre-registrado disparado; ADAPTER_FB no llegó a correr).*

1. **Mi nulo "último-generado" estaba mal computado** (11): lo calculé sobre
   el orden BARAJADO del pool — que es otra elección al azar — en vez del
   orden de GENERACIÓN, que es la heurística gratuita real (la que el
   refutador midió en 19/37). Se recomputa del crudo sobre los pools
   analizados y ESE es el umbral de "ÚTIL". Ninguna elección del ranker
   cambia; solo el listón contra el que se lee.
2. **Desajuste de plantilla, diagnosticado reproduciendo los 4 no parseables
   a mano** (regla del 10% cumplida): el adapter fue entrenado vía
   llama-factory con chat template; el runner preguntaba por `/completion`
   CRUDO. Bajo el adapter, el modelo continúa el prompt redactando
   instrucciones y el número llega tarde (fuera de los 16 tokens de FA) o
   degenera en bucle (abc384_g). El brazo BASE lo tolera; el ADAPTER no:
   asimetría de instrumento contra el adapter. **Corrección pre-registrada:
   corrida 2 con el chat template de la base aplicado por el server
   (`/v1/chat/completions`), idéntico en AMBOS brazos y ambos formatos;
   n_predict de FA sube a 64; los cuatro conteos completos (incl.
   ADAPTER_FB). La corrida 1 en crudo queda reportada como
   instrumento-degradado (no se descarta en silencio); la lectura
   VIVE/KILL se hace sobre la corrida 2.**

## RESULTADOS (2026-08-01 tarde — programa completo, GPU bajada)

**F0 — PASS** (`b4_loras/f0_gate.json`): pipeline GGUF-LoRA + hot-swap
PROBADO sobre qwen2.5-7b q4_k_m. Adapter activo (S1≠S0 en 3/3), ida y vuelta
de escala byte-exacta, salidas coherentes. Hallazgo de instrumento
(enmienda 2): en b10066 `--lora-init-without-apply` arranca YA aplicado a
escala 1.

**F1 — KILL por las dos lecturas, en ambos formatos** (`f1_rankef.json`
corrida 1 cruda / `f1_rankef_v2.json` corrida 2 con chat template, la que
decide). Nulos sobre los 37 pools (0 excluidos por contexto): azar 10.45
(p95=15, p99=16), **último-generado 19** (el listón de utilidad; mi corrida
1 lo computaba mal sobre el orden barajado — corregido, coincide con el
recomputo del refutador), más-largo 14, primero 2.

| brazo × formato (corrida 2) | aciertos | inválidos |
|---|---|---|
| BASE_FA / BASE_FB | 14/37 · 14/37 | 0 · 1 |
| **ADAPTER_FA** | **6/37** | **0** |
| ADAPTER_FB | 3/37 | 11 (30% → PARAR; reproducido: alucina candidatos inexistentes, bucles) |

Ni el adapter ni la base superan el p95 del azar; el adapter con parsing
perfecto queda POR DEBAJO del azar. Limitación declarada y de serie: el
formato de entrenamiento de RankEF no está documentado — no se distingue
"no sabe rankear" de "nuestro prompt no es su tarea"; ambas cierran la
ADOPCIÓN, que es lo que se medía. Dato colateral: el coder-14B pelado
tampoco rankea sin ejecutar (14/37). **La señal sin sandbox sigue sin
existir en esta flota — coherente con las 11 vías muertas de web.**

**F2 — el gate quedó MEDIDO en sus dos mitades**:
- Adapter público con `target_parameters` de EXPERTOS: **CERRADO en b10066**
  — el conversor revienta RUIDOSO (`Can not map tensor
  '...mlp.experts.base_layer.weight'`), no silencioso. Mejor de lo temido.
- Ruta de SOLO ATENCIÓN sobre MXFP4 (quimera declarada: el mismo adapter
  filtrado a q/k/v/o, 192/192 tensores convertidos): **ABIERTA — gate de
  actividad PASS** sobre gpt-oss-20b MXFP4 (`f2_gate.json`). La
  no-regresión de 20 tareas NO se corrió: con la quimera el número de
  calidad no significa nada (declarado); el gate técnico era el entregable.

**La lectura del programa entero**: ningún LoRA público descargable compró
nada medible hoy — como el inventario anticipó. Lo que queda ABIERTO y
PROBADO es el prerequisito de la vía real: pipeline PEFT→GGUF→hot-swap
verificado end-to-end, y la ruta de adapters de atención sobre el pensador
(gpt-oss MXFP4) funciona. Entrenar LoRA PROPIO con examen propio ya no
tiene riesgo de instrumento desconocido.

## Presupuesto y orden

F0: descarga ~100-400MB + ~15 min de server 7B. F1: conversión + ~45-90 min
de server 14B (37×2 formatos×2 brazos ≈ 150 rankings cortos). F2: descarga +
conversión + ~30 min de 20B. Orden: F0 → F1 → F2. Revisión adversarial de
este prereg ANTES de la primera descarga; suite completa no aplica (sin
cambios de producto); los scripts nuevos van a `scripts/` con el prefijo
`b4_lora_`.
