# Rediseño de la UI de Cognia — decisiones y plan (2026-08-17)

Pedido del dueño: que el CLI se vea y se comporte como sus capturas — marco verde en la
entrada, actividad de tool con degradado animado, tareas con casillas, bloques de diff con
fondo, y una **vista viva donde se ve qué hace cada agente de un workflow multiagente**, con
clic, capaz de interrumpir y de hablarle a un agente en curso.

Este fichero es la fuente canónica de **qué se decidió y por qué**. El estado de ejecución va
en `MANAGER_LOG.md`.

## Decisiones (16, tomadas por el dueño el 2026-08-17)

| # | Tema | Decisión |
|---|---|---|
| 1 | Pantalla | **Híbrido.** El chat sigue append-only. La vista de agentes es una pantalla aparte que se abre bajo demanda y devuelve el terminal como estaba. |
| 2 | Framework de la vista | **Textual**, dentro de `cognia/tui/`. `textual` pasa a dependencia dura (+11 MB reales). |
| 3 | Apertura | **Manual** (F2 o `/agentes`). En el scroll queda la línea con spinner. Cerrar la vista NO cancela nada. |
| 4 | Layout | **Un panel por agente**, en vivo, con **contenido** (el texto generándose), no solo estado. |
| 5 | Control | Mirar, **interrumpir** un agente o la corrida, y **hablarle** a un agente en curso. |
| 6 | Semántica de «hablarle» | **Cortar y volver a preguntar**: corta la generación, apendea el mensaje como turno del usuario y vuelve a llamar. Se tira lo generado y cuesta una llamada de presupuesto. El botón se llama «interrumpir y decir». |
| 7 | Terminal objetivo | **Windows Terminal**. El clic nunca es la única vía: todo tiene atajo de teclado. |
| 8 | Slots del backend | **llama-server con `--parallel 2`.** Con 1 slot los paneles paralelos son decorativos (uno genera, el otro espera turno). |
| 9 | Actividad de tool | **Shimmer animado** (onda gris→blanco) mientras corre; se apaga al terminar. Medido: 2,1 % de un core con 1 panel a 15 fps, 9,9 % con 8. |
| 10 | Descripción de tool | **Fija por herramienta** (qué es la tool), del catálogo. |
| 11 | Tareas ☑ ☒ ☐ | **Del plan del agente**, marcándose en vivo en el mismo bloque. |
| 12 | Diffs | **Fondo verde/rojo a todo el ancho, en todo diff del CLI.** |
| 13 | Móvil | **No se rompe y además ve los agentes**: hitos + progreso (arrancó, terminó, tokens, segundos). **No** contenido en vivo. |
| 14 | Paleta | **Manda el verde del REPL.** La TUI violeta se reviste después; el tema se unifica. |
| 15 | Motor | **Completo**: stream identificado por agente, cancelación cooperativa e inyección de mensajes. |
| 16 | Alcance | Es el look por defecto, no un flag. |
| 17 | Voz del modelo | **La respuesta va en color de texto normal.** Ni verde ni cyan: el color queda para la interfaz (marco, actividad, estados). `COGNIA_ACCENT` sigue configurable; cambia su defecto. |
| 18 | Banner | **El gato sube a visible**: el degradado arranca en un verde que se ve (~3:1 en oscuro) manteniendo la rampa. |
| 19 | Razonamiento | **Sigue verde.** La decisión 17 aplica solo a la respuesta final; el bloque de razonamiento es lo que distingue a Cognia y se ve de un vistazo. |

## Restricciones duras (medidas, no supuestas)

- **Textual deja mudo el canal del móvil.** Con la App abierta, `sys.stdout` es un
  `_PrintCapture`: 3 eventos emitidos → 0 líneas `@EV`. El sink tiene que escribir a
  `sys.__stdout__`. Sin eso, la vista rompe el control remoto (restricción dura del dueño).
- **`stream` sin `stream_options.include_usage` devuelve `usage = None`**, y el presupuesto de
  tokens del motor sumaría 0 **en silencio**. El body lo manda siempre que active stream.
  Criterio de corte de T1: el `usage` en stream tiene que cuadrar exacto con el del no-stream.
- **El corte es entre chunks, no instantáneo.** Entre el POST y el primer chunk (prefill) no hay
  checkpoint: con un prompt largo, el botón está muerto unos segundos. Abortar cuesta ~0,21 s y
  el slot vuelve a servir en ~0,42 s (medido contra :8080 con qwen2.5-coder-14b).
- **`emitir()` reparte en el hilo del emisor** y el Renderer no tenía lock: con `paralelo(cap=2)`
  dos handlers entran a la vez sobre el mismo `_status`.
- **El teléfono nunca podrá abrir la vista**: su sesión es otro proceso con stdout en un pipe.
  Lo máximo simétrico es un `/interrumpir <agente_id>` escrito por stdin.

## Plan por tandas

| Tanda | Entrega visible | Criterio de corte |
|---|---|---|
| **T0** habilitante | Nada visible. Eventos `WorkflowInicio/AgenteInicio/AgenteFin/WorkflowFin` con identidad de agente (`agente_id` sellado por ContextVar), lock en el renderer, allowlist del móvil, `'critica'` que faltaba en el envelope. | El móvil ve lo mismo que antes y la suite pasa. |
| **T1** stream + corte | Un script imprime el texto de cada agente saliendo palabra a palabra con su `agente_id` delante. | `usage` en stream == `usage` sin stream, exacto. Si no, no se pasa a T2. |
| **T2** control en el motor | Script que interrumpe el agente 2 y le manda un mensaje al 3, en una corrida real. | Un agente cancelado **no** queda cacheado como bueno en el journal. |
| **T3** sink honesto | Con la App abierta, un cliente WS del remoto sigue recibiendo líneas (hoy recibe 0). | El test que hoy da 0/3 da 3/3. |
| **T4** runner ← riesgo | Durante un `/workflow`, `F2` abre una App mínima y al salir el prompt vuelve entero. | **Lo firma el dueño en Windows Terminal.** Si el terminal queda en raw mode, plan B: la vista es un proceso aparte contra un socket de la corrida. |
| **T5a** pantalla (mirar) | Carril de paneles por agente con el texto vivo y shimmer. | Los SVG headless muestran texto real de 3 agentes sin mezclarse, y `sys.stdout is sys.__stdout__` al cerrar. |
| **T5b** pantalla (actuar) | `x`, `ctrl+x` e `Input` cableados contra T2. | Interrumpir desde la vista deja `AgenteFin(ok=False)` en el journal **y** en el móvil. |
| **T6** móvil + empaquetado | Bloque plegable por agente en el teléfono; `pip install cognia-ai` trae la vista sin extras. | 0 líneas de JSON crudo con `quien="cognia"` en el `.jsonl` del remoto. |

Tamaño honesto: ~1.100 líneas de producción + ~800 de test. El camino crítico **no es Textual**
(la pantalla ya se probó headless): es T1–T4, que son motor y CLI.

## Lo que no va a ser como suena

- **El panel no muestra a un agente usando herramientas.** `agente()` es UNA llamada al LLM con
  `response_format`; el panel muestra su prosa generándose. Meter el bucle con tools dentro de
  `agente()` es otro proyecto (2-4 días), tira el contrato de validación por schema e invalida la
  clave de cache.
- **El móvil ve hitos, no contenido.** Asimetría deliberada (decisión 13).
- **Con 1 slot, «paralelo» es una cola.** De ahí la decisión 8.

## Gate barato mientras dure el trabajo

```
venv312\Scripts\python.exe -m pytest tests/test_tui_*.py tests/test_ux_events.py \
    tests/test_remoto*.py tests/test_workflows_*.py tests/test_marco_prompt.py -q
```

Nunca la suite completa durante el bucle (11 min). La suite entera, como última compuerta.

---

## Estado de ejecución (actualizado 2026-08-17)

| Tanda | Estado | Lo que quedó medido |
|---|---|---|
| **T0** eventos con identidad | ✅ | `agente_id = <run_id>#<fase>.<indice>@<n>`, sellado por ContextVar. Verificado con un productor ajeno al motor bajo `paralelo(cap=2)`. |
| **T0b** los 6 defectos del revisor | ✅ | Contrafactual por fix: revertido en el fichero real, el defecto vuelve. 323 tests. |
| **T1** stream SSE | ✅ | `usage` en stream == no-stream, exacto (44/29/73). |
| **T1b** el corte que no cortaba | ✅ | Cancelación fuera de banda: de 5,01 s a **16 ms** con el backend mudo. Los tests viejos la hacían parecer funcional (disparaban con datos ya llegados). |
| **T1c** TLS, la cola y el reloj | ✅ | HTTPS arreglado, no degradado. 12/12 índices de corte sin `tool_calls` ejecutables. Timeout devuelto a semántica de inactividad. |
| **T2** control por agente | ✅ | Corte en **0,025 s** reproducible; resume re-llama al cancelado; «hablarle» verificado (respondió `CARPINCHO`). |
| **T2b** honestidad del control | ✅ | Cancelar deja de decir «ningún paso devolvió resultado». El corte pasó de cobrar 0 a cobrar exacto (132 frames = 132 tokens de `/tokenize`, 3/3). 772 tests. |
| **paleta** verde unificado | ⏳ | Termina con capturas PNG del REPL y SVG de la TUI. |
| **T3** sink honesto + puente | ✅ | 0/3 → **3/3** líneas `@EV` con la App abierta; e2e con el pipeline real del móvil 0/8 → **8/8**. El test viejo *pasaba sin vigilar nada*: `App._print` solo reenvía al stdout real en modo headless, o sea que el arnés era la condición que ocultaba el bug. De paso: `cli.py:1558` metía cada comando en un `redirect_stdout` (el móvil nunca vio esos eventos) y el handler de logs pintaba ANSI crudo sobre la pantalla alterna. Puente entregado: 921 líneas, descarte **visible** y atribuido al agente, despertador coalescido (8 wakeups / 1.610 eventos). |
| **T4** runner (workflow al hilo, teclado al principal) | ⬜ | La tanda de riesgo. La firma el dueño en Windows Terminal. |
| **T5a/b** la pantalla | ⬜ | Carril de paneles, shimmer, clic, `x` / `ctrl+x` / Input. |
| **T6** móvil por agente + empaquetado | ⬜ | `textual` a dependencia dura. |

### Deuda declarada, con su número

- **El prompt del turno cortado no se cobra.** Los tokens generados sí (exacto, por frames). Lo que falta está acotado por `max_repreguntas(8) × prompt_tokens` por agente y **contado** en `presupuesto.sin_prompt()`, que tica también cuando el corte cae en pleno prefill.
- **`interactivo=True` no lo enciende ningún consumidor todavía.** `/workflow` y la tool `workflow` corren por el camino no-interactivo, byte-idéntico al histórico. Lo encenderá la vista (T4).
- **Con `total_slots=1` el paralelismo es una cola.** Decisión 8: arrancar con `--parallel 2`, midiendo antes el coste en contexto por agente.
- **El tope de pared del stream** es un estrechamiento nuevo si algún llamador pasa `timeout=` chico. Hoy nadie lo pasa (`espera >= 300` ⇒ pared ≥ 1200 s).
