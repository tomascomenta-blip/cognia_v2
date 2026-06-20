# long_context.md — contexto y respuestas extremadamente largos en Cognia-X

> §CONTEXTO EXTREMADAMENTE LARGO + §RESPUESTAS LARGAS de la directiva. No asumir que la ventana de
> contexto actual es óptima ni que la generación estrictamente secuencial lo es. Este archivo separa
> lo que YA tiene mecanismo medido de lo que es PENDIENTE (F-LONGCTX). Append-only.

## El problema, en preguntas (la directiva)
- ¿Es necesario recordar TODO? ¿Qué debe recordarse, qué comprimirse, qué reconstruirse, qué
  archivarse, qué sintetizarse? — la respuesta por default "guardar todo en la ventana" NO se asume.

## Lo que Cognia-X YA aporta al contexto largo (mecanismo de COSTE, medido)
- **El híbrido es la historia de coste del contexto largo.** La atención full tiene KV-cache O(L) y
  cómputo O(L²): inviable en CPU a L grande. El backbone híbrido lo evita:
  - capas **lineales**: estado recurrente de tamaño **FIJO** (O(1) en L) → "recordar comprimido" a
    costo constante por token. exp001: 70× más barato que full a L=4096; exp005: híbrido = 12-15% del full.
  - capas de **atención sliding-window (SWA, W~1024)**: KV-cache O(W) en vez de O(L) (H-SEQ-3, Gemma-3:
    KV 60%→<15% a 32K sin perder perplejidad) → "recordar exacto pero solo lo reciente".
  - 1-2 capas globales escasas para el recall de largo alcance que la tarea exija (D-007).

## Lo que el contexto largo CUESTA en CALIDAD (la línea de techo de recall)
- El estado fijo "recuerda comprimido" pero su **recall asociativo está acotado** (exp002 ~d²/32; cota
  entrenada efectiva ~0.18, exp009). Por eso el contexto largo en un mezclador de estado fijo PIERDE
  recall a alta carga — y por eso hace falta la atención (C-01/C-02 en `contradictions.md`). La línea
  H-CEIL-1/2/3 investiga si ese techo se levanta (forma del kernel/init) o es estructural → define
  cuánto contexto largo puede sostener el componente barato antes de necesitar atención.

## HYDRA a nivel de sistema (reinterpretación, ver C-05)
- HYDRA como atención de red es inviable; la reinterpretación viable es un **enrutador de
  contexto/memoria de 3 bandas** — LOCAL (ventana inmediata) / MEDIA (resumen/SWA) / GLOBAL (memoria
  recuperable, RAG document-level) — construido SOBRE el routing existente. Es el análogo "qué
  recordar / qué comprimir / qué archivar" de la directiva, hecho arquitectura.

## Respuestas extremadamente largas (PENDIENTE, sin experimento aún)
- Mantener coherencia/consistencia/objetivos/memoria durante una generación muy larga NO se asume
  resuelto por la generación secuencial token-a-token. Direcciones a explorar (F-LONGCTX): planificar
  antes de generar (boceto→relleno), verificar contra los objetivos durante la generación, anclar
  hechos en memoria recuperable en vez de en la ventana.

## Estado honesto
- COSTE del contexto largo: mecanismo medido (híbrido lineal+SWA). **CALIDAD** (recall a alta carga) y
  **respuestas largas coherentes**: PENDIENTE — dependen de la línea de techo de recall y de F-LONGCTX.
  No hay aún un experimento propio de Cognia-X a L extremo end-to-end; es backlog declarado.
