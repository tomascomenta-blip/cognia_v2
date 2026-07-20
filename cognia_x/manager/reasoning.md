# reasoning.md — el eje de Razonamiento de Cognia-X (track propio, nunca "terminado")

> §4 de la directiva: mantener un eje dedicado y continuo de razonamiento (lógica, causalidad,
> planificación, autocrítica, estimación de incertidumbre, primeros principios). Nunca cerrarlo.
> Encarnación medible: PILAR 5 (`cognia_x/reason/`, CYCLE 12-21). Este archivo es la vista de estado;
> el detalle vive en `cognia_x/reason/README.md` + `RESULTS.md` y `research_log.md`. Append-only.

## Qué se construyó y VALIDÓ (CYCLE 12-21) — sobre solvers sintéticos
El mecanismo central: un **router de meta-razonamiento** que NO razona por sí mismo sino que
**prueba cadenas de razonamiento y aprende cuál funciona** por tipo de problema, juzgado por un
**verificador real** (no por el propio modelo — examinador no-circular). Hitos:
- **CYCLE 12-14:** el router aprende qué cadena resuelve cada tipo; **compone** cadenas multi-paso
  (un programa de 2 cadenas resuelve tipos que ninguna sola resuelve).
- **CYCLE 15:** romper el "techo perfecto" — competencia graduada (el oracle cae < 1.0 → hay techo real).
- **CYCLE 16-17:** quitar la muleta del tipo — inferir la clase **desde el TEXTO**, robusto a
  **paráfrasis + vocabulario solapado** (no keyword trivial).
- **CYCLE 19-21:** el char-LM REAL entrenado como **encoder** del router; el **encoder supervisado por
  el verificador** le gana al bag-of-words. Cierre del sub-arco de texto.
- Invariantes ganados: **no-circularidad** (el examinador es independiente), **anti-Goodhart**
  (held-out rotativo + committee), el ruido del examinador modelado (CYCLE 13).

## Límite honesto de lo validado
Todo lo anterior está validado **SOBRE SOLVERS SINTÉTICOS**: las "cadenas" son procedimientos
hand-coded y el "preguntar al usuario" usa el ground-truth como oráculo. Eso es un mecanismo de
meta-razonamiento demostrado, **no razonamiento "de verdad"** todavía.

## Pendiente (F-REASON-REAL) — el frontier real
1. **Envolver el LM REAL** (no solvers de juguete): que las cadenas sean prompts/estrategias del
   char-LM o del backend GGUF sobre una tarea que el modelo SÍ pueda intentar (transformaciones de
   texto verificables si el modelo es chico), y que el router aprenda cuál funciona.
2. **Verificador real, no oráculo perfecto:** código→sandbox+oráculo; hechos→redundancia ≥2 fuentes;
   usuario simulado ruidoso **y caro** (costo asimétrico de preguntar).
3. **Paráfrasis natural, no plantillas** (CYCLE 17 usó plantillas+sinónimos): encoder aprendido o el
   propio LM como clasificador de tipo.
4. **Cadenas de largo >2 y descubrir sub-metas** (planificación real), no secuencias fijas.

## Relación con las prioridades
Razonamiento es prioridad #5 (debajo de eficiencia, aprendizaje continuo, adaptabilidad, creatividad).
Por eso el eje avanza como **track paralelo medible**, no como el objetivo principal — pero nunca se
declara terminado (§4). Su próximo ciclo compite en el backlog con F-RECALL-CEIL / F-LEARN-2 por
impacto × evidencia que falta.
