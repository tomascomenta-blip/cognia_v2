# BORRADOR de prereg — Sonda del prompt QUE EL LAZO ARMA (ladrón de ~17 pts)

**Estado: BORRADOR, 2026-07-28 (nocturna 28→29, segunda noche). NO corre
esta noche** — la GPU la consume el gate de confirmación del BoN. Se deja
diseñado porque la materia prima se está capturando AHORA (volcado pasivo
COGNIA_DUMP_PROMPTS en la corrida b2_bon_gate: ~96 prompts del lazo con su
outcome estricto por muestra). Antes de correr: completar umbrales, enmendar
con revisión adversarial y convertir en PREREG con fecha.

## El hueco (medido)

- GAP con control concurrente (2026-07-28): sistema 15/23 (65%) vs crudo
  19/23 (83%) — el envoltorio AÚN roba ~17 pts.
- Dos sondas del prompt DIRECTO no transfirieron al lazo (fix2 v2 neto −5,
  v3 neto −4): el prompt directo NO es el prompt del lazo. Regla dura de
  esas dos derrotas: **sondear el prompt QUE EL LAZO ARMA o no sondear.**

## Diseño (esqueleto)

1. **Materia prima:** `b2_bon_gate/prompts/prompts.jsonl` — cada prompt del
   lazo (lenguaje=html, con system/temperatura/effort) alineable por orden y
   timestamps con las muestras del gate (que tienen estricto). Verificar la
   alineación ANTES de diseñar ablaciones (nº prompts html ≈ nº muestras).
2. **Descomposición:** diff estructural entre el prompt del lazo y el prompt
   crudo (idea sola) sobre los 96 capturados: ¿qué secciones añade el lazo y
   con qué variación? (brief de visión, hints de feromona, REQUIRED, reglas
   dashboard condicionales, formato). Salida: lista de PIEZAS con frecuencia.
3. **Ablaciones por REPLAY (sin lazo):** re-ejecutar contra el modelo el
   prompt capturado ÍNTEGRO (brazo L), el prompt crudo (brazo C, control
   concurrente), y L menos UNA pieza por brazo (L-brief, L-hints, ...).
   Juez estricto (original ∧ held-out). Intercalado a nivel tarea, n≥6 por
   brazo. El par (L, C) replica el GAP con instrumento nuevo: si L ≈ C, el
   ladrón NO está en el texto del prompt (está en el flujo del lazo:
   parseo, reintentos, validaciones) y las ablaciones no aplican.
4. **Lectura:** la pieza cuya ablación cierra el gap más de X pts (umbral a
   fijar en el prereg final) es el ladrón; fix condicional y A/B de
   confirmación EN el lazo (la lección de fix2: el fix se mide en el lazo,
   nunca solo en el replay).

## Descomposición HECHA (2026-07-28, sobre los primeros capturados reales)

Estructura del prompt QUE EL LAZO ARMA (capturas de b2_bon_gate; el paso 2
del esqueleto queda adelantado):

1. **Idea + brief de visión concatenados** en la línea `for: **idea. TARGET
   LOOK, match it: brief**` — el brief (~600-700 chars) vive DENTRO del
   bold de la idea, no como sección aparte.
2. **CRITICAL RULES** (~15 reglas, incluye las dashboard condicionales del
   fix 1a50bbc).
3. **REQUIRED component N** — el troceo por comas de la idea CRUDA (sin el
   brief). **La mutilación de enumeraciones sigue EN PRODUCCIÓN y es
   visible en la captura:** "component 1: ...las minas estan en las celdas
   6" / "component 2: 12 y 18. Al hacer click..." (la enumeración "6, 12 y
   18" partida en tres pedazos; el último componente además truncado a
   media palabra: "(cla"). La escalera del 27 midió este troceo en −2
   netas EN SONDA DIRECTA; aquí está la evidencia de cómo luce en el lazo
   real.
4. **Patrones de feromona** (bloques HTML/JS de ejemplo, ~2-3k chars — SIN
   CARGO en la escalera, pero es el trozo más grande del prompt).
5. **Formato de respuesta** (Title/Description/HTML Code — SIN CARGO).

Piezas candidatas para las ablaciones del prereg final, por prior: (a) el
troceo REQUIRED (mutilación medida −2 en directo, fix nunca transferido),
(b) el brief dentro del bold (¿confunde el "Reproduce LITERALLY" con el
copy del brief?), (c) los patrones de feromona (tamaño vs valor). La
corrida v2 del gate deja ~96 prompts con outcome estricto para
cuantificar frecuencias y correlaciones ANTES de gastar GPU en ablaciones.

## Exploratorio sobre los 96 capturados de la corrida v2 (2026-07-29, sin GPU)

Con los 96 prompts alineados a sus outcomes estricto: **el LARGO del prompt
no separa nada** — mediana 5995 chars en aprobadas, 5898 en reprobadas,
6071 en espirales de backend; y es PLANO por posición (s1 5996 → s4 5918),
así que la hipótesis "la feromona engorda el prompt en s3/s4 y por eso s4
nunca gana" queda DESCARTADA con datos (dos horas de GPU ahorradas). Las
ablaciones del prereg final deben ser por CONTENIDO de pieza, no por
tamaño.

## Riesgos ya conocidos a heredar en el prereg final

- Deriva sistémica ~20 pts/12h → todos los brazos concurrentes e
  intercalados; nada contra referencias históricas.
- El replay no es el lazo (parseo/reintentos/fallbacks quedan fuera): el
  paso 3 solo ATRIBUYE; la confirmación es siempre en el lazo.
- Presupuesto de pared por celda (cognia/presupuesto_pared.py) desde el
  arranque.
