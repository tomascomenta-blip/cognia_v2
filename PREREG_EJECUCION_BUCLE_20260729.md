# PREREG — Señal por EJECUCIÓN EN EL BUCLE, iteración 1 (sondear-observar-juzgar)

**Fecha:** 2026-07-29 ~07:00, sesión matinal 29. **Escrito ANTES de
implementar el runner y ANTES de correr.** Sustituye al
PREREG_EJECUCION_BUCLE_BORRADOR.md de esta misma mañana (misma idea, corpus
y umbrales cerrados). Es la vía que quedó como ÚNICA viva para fabricar
señal en tareas no vistas tras: 4 KILL del contrato ciego (corregido ×2,
validado, QA-fuerte con dos modelos — la enfermedad es el MARCO) y 2 vueltas
de consenso de votos (regla pre-fijada: no más variantes). Mecanismo medido
que este diseño ataca: las expectativas inventadas viven en los VALORES de
los checks (PREREG_CONSENSO2, lectura de mecanismo).

## Hipótesis (pre-declarada)

El contrato ciego obliga al pensador a PREDECIR valores exactos sin ver la
página comportarse → FN ~50% (condena sanos por inventos) con FP 32-50%.
Si el pensador OBSERVA el comportamiento real (acciones ejecutadas por
Playwright, valores leídos antes/después) y su tarea pasa a ser JUZGAR
conformidad de lo observado con el ENUNCIADO, el FN por invento debe caer.
El modo de fallo esperado se desplaza a FP-por-complacencia (bendecir lo
que ve); el A/B mide exactamente ese trade.

## Protocolo (tres fases por página)

1. **SONDEO (1 llamada LLM):** idea + inventario DOM (el MISMO
   `inventario_dom` del contrato ciego: mismo aislamiento, nunca el código).
   El pensador emite JSON con ≤6 sondas: cada una = nombre + secuencia de
   acciones (click/escribir/tecla/esperar, el schema del juez) + selectores
   a OBSERVAR. Sin ninguna aserción.
2. **EJECUCIÓN (Playwright, sin LLM):** página real; por sonda: snapshot de
   los selectores observados (conteo, texto visible, .value de inputs por
   JS) → acciones → 400 ms → snapshot posterior. Errores JS capturados. Una
   acción que crashea no mata la sonda: queda registrada como acción
   fallida y la sonda conserva sus snapshots.
3. **JUICIO (1 llamada LLM):** idea + transcript de lo observado (sin
   inventario, sin código). Por sonda un dictamen:
   `CORRECTO` / `INCORRECTO` (lo observado VIOLA una regla explícita del
   enunciado — la instrucción prohíbe acusar por estética o por
   expectativas no escritas) / `NO_CONCLUYENTE`.
4. **Veredicto del marco (regla del harness, NO del modelo):**
   REPRUEBA ⇔ ≥1 sonda con dictamen INCORRECTO. Sin sondas ejecutables o
   sin dictámenes parseables → SIN VEREDICTO (cuenta aparte, no como
   acierto ni fallo).

## Corpus y control (congelados)

- Las **24 páginas de b2_sonda_prompt** con veredicto del BANCO en disco
  (19 aprueba / 5 reprueba) — el mismo corpus de b2_ab_contrato y del
  QA-fuerte: baselines directamente comparables (gpt-oss ciego mismo-día:
  aciertos 8/24, FN 15/19; coder-14b: 10/24, FN 14/19, FP 0/5).
- **Control CONCURRENTE:** el contrato ciego clásico se RE-genera en la
  misma corrida, intercalado por página (deriva ~20 pts/12h — nada contra
  referencias históricas).
- Pensador: gpt-oss-20b (:8080, slots=1 y ctx verificados por el runner),
  temp 0.2, reasoning_effort=low, max_tokens 12000 (presupuesto cubre el
  pensamiento; margen 2-3×).
- FP/FN idénticos a b2_ab_contrato: FP = marco aprueba ∧ banco reprueba;
  FN = marco reprueba ∧ banco aprueba.

## Piloto de futilidad (pre-registrado; la lección de Nemotron)

6 páginas primero (el plan del piloto QA: segundas de cada tarea + terceras
de hoja y carrito). **KILL DE APTITUD sin correr el bloque** si:
- <4/6 páginas logran ≥1 sonda EJECUTADA con observación no vacía, o
- los dictámenes degeneran: veredicto del marco idéntico en 6/6 páginas
  (todo APRUEBA o todo REPRUEBA).

## Umbrales del bloque (fijados ahora; 24 páginas)

| lectura | veredicto |
|---|---|
| aciertos ≥ 16/24 **y** FP ≤ 1/5 | **VIVA**: primera señal autogenerada sobre el azar; validación obligatoria (96 muestras del BoN + banco fácil, prereg aparte) ANTES de declarar o cablear nada |
| aciertos 12–15/24 | GRIS: mejor que el ciego (8–10) pero sin señal usable; se reporta dónde falla (¿sondeo o juicio?) y la iteración 2 ataca ESA fase |
| aciertos ≤ 11/24 | KILL de la iteración 1 (indistinguible del ciego) |

- Si el control concurrente ciego sale de su rango histórico (aciertos
  fuera de 6–12/24), la corrida se lee como direccional (instrumento o
  deriva anómala) — pre-declarado.
- Páginas SIN VEREDICTO del marco: si son >4/24, el veredicto del bloque
  es solo direccional (el marco no cubre el corpus).
- Secundarias (se reportan, no deciden): FN/19 y FP/5; nº de sondas
  ejecutables por página; distribución de dictámenes; **complacencia** =
  páginas banco-reprobadas con 0 INCORRECTO (el FP desagregado);
  concordancia con el ciego (¿fallan en las mismas?); tiempos.

## Presupuesto

Piloto: 6×2 llamadas (~30-60 s c/u a effort low) + 6 ejecuciones ≈ 15-20
min. Bloque: 24×2 llamadas + 24 contratos control + 48 ejecuciones/juzgados
≈ 60-75 min. La GPU de la fase 1 de la sonda tiene prioridad; este prereg
solo corre si el reloj de la sesión lo permite tras la fase 2 — si no,
queda listo para la próxima.

## PRIMERA ENMIENDA (2026-07-29 ~06:25 — tras la revisión adversarial, ANTES de correr)

Un agente (diseño + implementación, verificaciones ejecutadas: corpus 24 =
19/5 reproducido, dry-run completo del marco con LLM mock, fixtures de
Playwright). Dos BLOQUEA + arreglos, aplicados al runner:

1. **BLOQUEA — control comparable:** sin-contrato-usable en el control =
   REPRUEBA (convención M3 del gate del QA-fuerte, la de los baselines
   8/24 y 10/24); None queda reservado para infra. Además el brazo control
   corre bajo presupuesto de pared (estaba desnudo).
2. **BLOQUEA — desborde de contexto del juicio:** 16000 chars de transcript
   + max_tokens 12000 > ctx 16384 y el fallo era silencioso y sesgado
   contra páginas complejas. Transcript acotado a 9000 chars cortado por
   SONDAS ENTERAS (cortar por chars dejaba sondas sin dictamen con sesgo a
   APRUEBA).
3. **Piloto reforzado:** el plan garantiza ≥2 páginas REPROBADAS (queda en
   8 páginas, 6/2: las segundas/terceras crudo del corpus + las 2 primeras
   reprobadas — con <2, un marco PERFECTO daba veredicto idéntico en todas
   = falso KILL por "degenerado"); "degenerado" = veredicto idéntico con ≥n−1 veredictos;
   KILL adicional si <4 páginas logran veredicto (el todo-NO_CONCLUYENTE
   pasaba el piloto). "Ejecutada" exige ahora un selector observado sin
   error y con n>0 (el criterio anterior era vacuamente cierto).
4. **Juicio con datos:** las acciones fallidas sobre selectores que NO
   constan en el inventario se anotan en el transcript ("[selector NO
   consta...]") — observación del instrumento, sin fuga; el prompt de
   juicio remite a esa marca (antes pedía distinguir sin datos).
   Todo-NO_CONCLUYENTE → SIN VEREDICTO (la abstención total puntuaría
   19/24 gratis). Duplicados de dictamen: el último gana.
5. **Fidelidad y contexto:** ambos prompts declaran "página RECIÉN CARGADA
   por sonda, el estado no persiste; las reglas de HISTORIA van enteras
   dentro de una sonda"; errores de CARGA capturados (el contador arrancaba
   después del goto); snapshot lee `checked` en checkbox/radio; identidad
   del modelo verificada en /props (exige gpt-oss); acciones por sonda
   ≤25.
6. **Declaraciones:** el plan del piloto NO es el del piloto QA de
   Nemotron (aquel usaba páginas del brazo `base`, fuera del corpus 24);
   es propio: segundas crudo/full del corpus + la primera reprobada fuera
   del plan. Si alguna reprobada del bloque queda SIN VEREDICTO, el gate
   FP ≤ 1/5 se lee direccional (denominador encogido). Techo declarado del
   snapshot: estado en atributos/clases fuera de los selectores observados
   y muestreo 5×60 chars — bugs invisibles a esa lente quedan fuera del
   alcance de la iteración 1.

## Método

- Revisión adversarial (1-2 agentes) del prereg + runner ANTES de GPU.
- El runner verifica slots=1 y n_ctx al arrancar; Ollama neutralizado;
  guardado incremental + --reanudar; presupuesto de pared por celda.
- El pensador NUNCA ve: el contrato original, el held-out, el código de la
  página. Solo enunciado + inventario (sondeo) / enunciado + observaciones
  (juicio). Mismo aislamiento que el piloto QA.
- Los dictámenes crudos se guardan íntegros (auditoría del mecanismo:
  ¿dónde vive el error, en sondear mal o en juzgar mal?).
