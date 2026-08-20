# Estado del arte: agentes de larga duracion con auto-lobotomia de contexto

Fecha: 2026-08-19. Alcance: literatura 2022-2026 sobre memoria de agentes, ingenieria de contexto,
verificacion y degradacion por longitud, filtrada por **una sola pregunta**: que sobrevive en un
LLM local de 27B denso, ~32k de contexto practico, **un solo slot** en una RTX 5060 Ti de 16 GB.

Regla del documento: cada tecnica lleva (1) problema real que resuelve, (2) evidencia con numeros,
(3) modo de fallo conocido, (4) veredicto para el 27B local. Donde la evidencia es de vendedor o
esta disputada, se dice. Donde no hay numeros, se dice "sin numeros" y se trata como hipotesis.

---

## 0. Los tres numeros que mandan sobre el diseno

Antes de las fichas, tres resultados que **deciden la arquitectura** y que casi ninguna propuesta
de "memoria de agentes" tiene en cuenta:

**(A) El horizonte multi-turno de un modelo de tu tamano es de ~8-15 pasos, no de horas.**
*The Illusion of Diminishing Returns* (NeurIPS 2025) mide el horizonte H(0.5): numero de pasos
que un modelo ejecuta antes de caer al 50% de exito, en una tarea de ejecucion pura (el plan y
el conocimiento se le dan hechos; solo tiene que ejecutar). Medido en modo multi-turno:
Qwen3-4B ~3 turnos, **Gemma3-27B ~8 turnos**, **Qwen3-32B ~15 turnos** (el mejor no-thinking).
Con razonamiento en un solo turno los numeros explotan (Claude 4 Sonnet 432 pasos, Grok 4 384,
GPT-5 2176) pero eso no aplica a un 27B denso local sin cadena larga.
→ https://arxiv.org/abs/2509.09677

**Consecuencia:** el ciclo de lobotomia no es una optimizacion, es la unica forma de que un 27B
haga mas de 15 pasos. Pero tambien implica que **el ciclo tiene que durar menos de ~8-15 acciones**,
o el propio ciclo se degrada antes de comprimir.

**(B) Los errores propios en el contexto envenenan los pasos siguientes ("self-conditioning").**
Mismo paper: con Qwen3-32B, la precision en el turno 100 pasa de ~85% (historial limpio) a ~70%
con 25% de errores inyectados en el historial y a ~55% con 50%. Y **escalar el modelo no lo
mitiga** en modelos no-thinking; los 200B+ (DeepSeek-V3, Kimi-K2, Qwen3-235B) tambien lo sufren.

**Consecuencia:** esto es el **argumento empirico mas fuerte a favor de destruir el contexto**.
No se trata solo de que el contexto sea caro: es que arrastrar la traza de tus propios fallos te
hace fallar mas. La lobotomia, si se hace bien, no es una perdida, es una **desinfeccion**.
Corolario duro: el resumen que se traspasa **no debe contener la traza de errores** salvo como
una linea explicita de "no intentar X, falla por Y".

**(C) La longitud sola degrada, aunque la recuperacion sea perfecta.**
*Context Length Alone Hurts LLM Performance Despite Perfect Retrieval* (Findings EMNLP 2025):
caidas de **13,9% a 85%** en 5 modelos (mate, QA, codigo) al alargar la entrada, **incluso cuando
el modelo recupera perfectamente toda la evidencia relevante** y **incluso cuando la evidencia se
coloca justo antes de la pregunta**. Persiste al sustituir los tokens irrelevantes por espacios en
blanco. Mitigacion barata y medida: **pedir al modelo que recite la evidencia antes de resolver**
(hasta +4% sobre un baseline ya fuerte en RULER con GPT-4o).
→ https://arxiv.org/abs/2510.05381

**Consecuencia:** "meterlo todo en 32k porque cabe" es un error medible. Y la recitacion previa
es un truco de una linea que ya puedes teclear en Cognia.

---

## 1. (a) Perdida de informacion en resumenes encadenados

**Lo que la literatura dice de verdad — y lo que no.**

No existe (a agosto 2026) un estudio limpio, ampliamente replicado, que mida "resumen de resumen
de resumen" en agentes con un protocolo controlado y numeros que aguanten. Lo que hay es:

- **Evidencia indirecta fuerte y solida**: la compresion es irreversible y no determinista. Anthropic
  describe la compactacion como "resumir y reiniciar la ventana", y explicita que su prompt de
  compactacion se calibra **primero maximizando recall** y solo despues precision — es decir,
  ellos mismos tratan la perdida como el riesgo dominante. La mitigacion que aplican **no es un
  resumen mejor: es re-leer del disco** los 5 ficheros mas recientes despues de compactar, y las
  notas estructuradas fuera del contexto.
  → https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

- **Evidencia indirecta de agente largo**: en *Effective harnesses for long-running agents*,
  Anthropic **no encadena resumenes**: cada sesion arranca leyendo `git log` + fichero de progreso
  + una lista de features en JSON (>200 entradas pass/fail), con instrucciones muy duras de que
  "es inaceptable borrar o editar tests". Es decir, el estado vive en **artefactos verificables y
  append-only**, no en prosa comprimida. El post **no da numeros** — es experiencia de ingenieria,
  no un experimento. Tratalo como tal.
  → https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

- **Evidencia cuantitativa lateral**: el par memory-tool + context-editing de Anthropic reporta
  **+39% sobre baseline** (context editing solo: **+29%**) y **-84% de tokens** en una eval interna
  de busqueda web de 100 turnos. Es **eval interna de vendedor**, no reproducible, pero la direccion
  es coherente: descartar resultados de herramienta viejos **mejora**, no empeora.
  → https://claude.com/blog/context-management

- **El resultado que mas se le parece, y es el mas util**: *LLMs Get Lost In Multi-Turn Conversation*
  (Laban et al., 2025; >200.000 conversaciones simuladas, 15 modelos, 6 tareas): caida media del
  **39%** de single-turn a multi-turn, descompuesta en **-15% de aptitud** y **+112% de
  no-fiabilidad** (varianza). La causa identificada: el modelo asume cosas pronto, produce una
  solucion prematura y **se apoya en ella**; cuando se equivoca, no se recupera.
  La recomendacion de los autores es literalmente **consolidar y reempezar en un turno limpio**.
  → https://arxiv.org/abs/2505.06120

**Veredicto operativo (y es una prescripcion de diseno, no una opinion):**
la compresion acumulativa se evita **no comprimiendo mejor, sino no comprimiendo el resumen**.
Cada ciclo debe regenerar su contexto desde **fuentes primarias reconstruibles** (ficheros, git log,
notas append-only, tests que pasan/fallan) y no desde el resumen del ciclo anterior. La unica capa
que puede reescribirse en sitio es la de **estado/plan**; objetivo, restricciones, decisiones y
hechos permanentes deben ser **append-only con provenance**, nunca resumidos.

Aviso: circulan varios preprints 2026 (rate-distortion de compactacion, "proactive memory
extraction", compactacion paralela) que afirman crecimiento **super-lineal** del error con el
numero de compactaciones. No he podido verificar sus numeros de forma independiente; **no los uses
como evidencia**, uselos como hipotesis a falsificar en tu propio banco.

---

## 2. (b) ¿Un critico del MISMO modelo detecta las alucinaciones del ejecutor?

**Respuesta corta: no de forma fiable, y menos aun a 27B. Esta es la parte mejor documentada
de todo el encargo, y toda la evidencia apunta al mismo sitio.**

| Trabajo | Resultado | URL |
|---|---|---|
| Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet* (ICLR 2024) | La auto-correccion **intrinseca** (sin feedback externo) **no mejora y a menudo degrada**: aritmetica, QA de libro cerrado, generacion de codigo, planificacion, coloreado de grafos | https://openreview.net/pdf?id=IkmD3fKBPQ |
| Kamoi et al., *When Can LLMs Actually Correct Their Own Mistakes?* (TACL 2024) | Survey critico: las mejoras publicadas se explican por **feedback externo fiable** o por fugas de la etiqueta oracle. Sin oraculo, no hay ganancia | https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00713/125177/ |
| *Critique Ability of LLMs* / CriticBench (3.000 consultas anotadas: mate, codigo, QA) | La capacidad de critica **emerge solo con escala suficiente**; la **auto-critica es especialmente dificil**; y la precision de la critica **cae justo donde el modelo esta mas incierto** — o sea, falla precisamente donde haria falta | https://arxiv.org/abs/2310.04815 |
| *Small Language Models Need Strong Verifiers to Self-Correct Reasoning* | Modelos ≤13B: ganancias reales **solo con un verificador GPT-4**; con **auto-verificador debil** el sistema no sabe **cuando** corregir y se rompe | https://arxiv.org/abs/2404.17140 |
| *Self-Preference Bias in LLM-as-a-Judge* | Los jueces **prefieren su propio texto**; en ArenaHard el sesgo va de **-38% a +90%**. Correlaciona con la capacidad de **auto-reconocimiento** del modelo | https://arxiv.org/abs/2410.21819 |
| DeltaBench, *Can LLMs Detect Errors in Long CoT Reasoning?* | PRMs y modelos criticos existentes tienen **limites claros** detectando errores en cadenas largas de QwQ / DeepSeek-R1 | https://arxiv.org/abs/2502.19361 |
| CriticGPT (*LLM Critics Help Catch LLM Bugs*, OpenAI) | Lo mas favorable que hay: criticas del modelo preferidas al humano en **63%**; pero **el critico alucina bugs**, y el equipo humano+critico alucina menos que el critico solo. Y requirio **RLHF dedicado**, no prompting | https://arxiv.org/abs/2407.00215 |
| SCoRe (ICLR 2025) | Se puede **entrenar** la auto-correccion con RL multi-turno: **+15,6% MATH, +9,1% HumanEval**. Confirma la regla al reves: hace falta entrenamiento, no un prompt de "revisa tu respuesta" | https://proceedings.iclr.cc/paper_files/paper/2025/file/871ac99fdc5282d0301934d23945ebaa-Paper-Conference.pdf |
| Verificacion **comparativa** vs absoluta | Los LLM son verificadores debiles puntuando en absoluto, pero **mejoran claramente comparando respuestas entre si** (A vs B). Es el hallazgo mas accionable para un critico local | https://arxiv.org/html/2506.18203v1 |

Esto **coincide exactamente** con lo ya medido en este proyecto ("cinco instrumentos aprobaron algo
roto en una noche", "el juez tiene que ejecutar", "el contrato interno esta al nivel del azar").
No es una coincidencia: es el mismo fenomeno, documentado por otros.

**Prescripcion para el agente critico separado, en orden de valor medido:**

1. **Verificador que EJECUTA** (tests, compilador, linter, `grep`, asserts, arranque de la app,
   diff contra golden). No es un LLM. Es la unica senal que la literatura respalda sin asteriscos.
   Esto es lo que hacen Reflexion (tests unitarios), Voyager (el entorno de Minecraft) y el harness
   de agentes largos de Anthropic (test e2e antes de cada trabajo nuevo).
2. **Critico en modo COMPARATIVO**, no puntuador: darle A y B y que elija, en vez de "¿esta bien?".
   Convierte una tarea donde el modelo esta al azar en una donde tiene senal.
3. **Critico de OTRA FAMILIA** si es posible (aqui: Qwen3.8-27B ejecutando y Qwythos-9B criticando
   —o al reves— no elimina el sesgo, pero rompe el auto-reconocimiento que alimenta el
   self-preference bias). Con un solo slot esto cuesta una recarga de modelo; el 9B a 200-400 ms
   por reformulacion hace viable un critico barato **si el juicio es comparativo o ejecutable**.
4. **Senales sin LLM**: entropia semantica (Farquhar et al., *Nature* 2024) detecta confabulaciones
   muestreando y agrupando por significado, con AUROC/AURAC superiores a P(True) y a self-check.
   Es caro con un solo slot (N muestras), pero es una senal **independiente del juicio del modelo**.
   → https://www.nature.com/articles/s41586-024-07421-0
5. **Lo que NO funciona**: "eres un critico severo, revisa tu propia respuesta" con el mismo modelo,
   mismo prompt, misma sesion. Eso esta falsado. Si lo pones, ponlo como brazo de control.

---

## 3. (c) Atencion a instrucciones al fondo del contexto

- **Lost in the Middle** (Liu et al., TACL 2024): la precision sigue una **U** con la posicion de
  la informacion relevante — alta al principio y al final, ~20-30 puntos mas baja en el medio, en
  QA multi-documento y recuperacion clave-valor. → https://arxiv.org/abs/2307.03172
- **Context Rot** (Chroma, 2025; **18 modelos**: Claude Opus 4/Sonnet 4/3.7/3.5, o3, GPT-4.1 y
  variantes, Gemini 2.5 Pro/Flash, **Qwen3-235B/32B/8B**): la degradacion es **no uniforme** y
  depende de la similitud aguja-pregunta, de los distractores (1 distractor ya baja; 4 compone) y
  de la estructura del pajar. Hallazgo contraintuitivo: **barajar el pajar MEJORA el rendimiento**
  frente a un texto coherente. En LongMemEval, el mismo modelo con prompt enfocado de 300 tokens
  vs el completo de 113k muestra un hueco pronunciado. Tasas de negativa: Claude Opus 4 2,89%,
  GPT-4.1 2,55%, GPT-3.5 Turbo 60,29%. → https://www.trychroma.com/research/context-rot
- **La longitud sola** (seccion 0-C): la degradacion persiste **con la evidencia inmediatamente
  antes de la pregunta**. Poner la instruccion al final **no te salva** de la longitud.
- **BABILong** (NeurIPS 2024): los LLM sin ajuste se degradan bruscamente pasados ~10.000 tokens;
  GPT-4 usa efectivamente ~10-20% de su ventana de 128k. → https://arxiv.org/abs/2406.10149

**Prescripcion:** en un 32k practico esto significa (i) **repetir la restriccion critica al final**
—el canal de estado que ya subiste de recall 0,07 a 1,00 es exactamente esto y la literatura lo
respalda—, (ii) **recitar la evidencia antes de resolver** (+4% medido, coste ~1 llamada corta),
(iii) mantener el contexto **muy por debajo** de los 32k por politica, no por limite, y (iv) no
asumir que "cabe" implica "se usa".

---

## 4. Fichas por tecnica

### 4.1 MemGPT / Letta — memoria jerarquica con paginacion y auto-edicion
1. **Problema real**: la ventana finita como memoria principal; el agente pagina hacia/desde
   almacenamiento externo llamando funciones (`core_memory_append`, `archival_memory_search`).
   La metafora es SO: contexto = RAM, archivo = disco.
2. **Evidencia**: introdujo el benchmark DMR, donde reporta ~93,4% (superado despues por Zep con
   94,8%). Letta reporta **74,0% en LoCoMo con GPT-4o-mini** guardando el historial como ficheros
   con busqueda semantica. **No ha publicado LongMemEval.** Los benchmarks son de sus propios
   autores o de competidores; ver 4.5 sobre lo poco que valen.
   → https://arxiv.org/abs/2310.08560 · https://arxiv.org/abs/2501.13956
3. **Modo de fallo**: **el agente decide mal que paginar**. Toda la arquitectura depende de que el
   LLM invoque las funciones de memoria correctas en el momento correcto — precisamente el tipo de
   decision meta que un modelo pequeno hace peor. Y el fallo es **silencioso**: nadie emite error
   cuando el agente no guarda algo importante.
4. **27B local**: **el patron si, la auto-edicion autonoma no.** Copia la jerarquia (bloques
   fijos siempre en contexto + archivo paginable). Pero **no dejes que el 27B decida solo** que
   escribir en la memoria permanente: hazlo en el paso de compresion, con un esquema fijo, y
   verificalo. La paginacion con 1 slot es barata (es I/O de disco, no tokens) — esto encaja bien.

### 4.2 CoALA — arquitecturas cognitivas para agentes de lenguaje
1. **Problema real**: **vocabulario y taxonomia**, no rendimiento. Separa memoria en *working /
   episodic / semantic / procedural* y el espacio de accion en **internas** (razonar, recuperar,
   aprender) vs **externas** (grounding).
2. **Evidencia**: **ninguna**. Es un marco conceptual y una revision retrospectiva.
   → https://arxiv.org/abs/2309.02427
3. **Modo de fallo**: se cita como si fuera un resultado. No lo es.
4. **27B local**: **util como esquema de la jerarquia por persistencia que pide el dueno**, y nada
   mas. Mapea directo: objetivo/restricciones = semantica permanente; decisiones = episodica
   append-only; estado/plan = working; flujos aprendidos = procedimental (esto ultimo ya lo tienes
   medido en `flujos-aprendidos-con-examen`, 1305x mas barato que el agente).

### 4.3 Generative Agents — memory stream + reflection + recuperacion
1. **Problema real**: coherencia de comportamiento a lo largo de dias simulados. Recuperacion
   puntuada por **recencia × importancia × relevancia**; **reflexiones** que sintetizan
   observaciones en creencias de alto nivel.
2. **Evidencia**: ablaciones que muestran que quitar memoria, reflexion o planificacion degrada la
   **credibilidad** juzgada por humanos. **La metrica es credibilidad, no correccion de tarea.**
   → https://arxiv.org/abs/2304.03442
3. **Modo de fallo**: (i) la puntuacion de "importancia" la asigna el propio LLM y es ruidosa;
   (ii) las reflexiones son **resumenes de resumenes con otro nombre** — heredan todo el problema
   de la seccion 1; (iii) el sistema no tiene verificador: una reflexion falsa se convierte en
   creencia permanente. Esto es exactamente el vector de "memory poisoning por alucinacion propia".
4. **27B local**: **importa la recuperacion (recencia/importancia/relevancia), rechaza la
   reflexion sin verificacion.** Una reflexion solo debe ascender a "hecho permanente" si pasa un
   examen (esto ya lo aprendiste con `skills-autocapturadas-envenenan`: una traza de atasco
   ascendida a procedimiento verificado envenena tareas ajenas).

### 4.4 Reflexion — refuerzo verbal
1. **Problema real**: convertir un fallo observado en una instruccion textual para el siguiente
   intento, sin tocar pesos.
2. **Evidencia**: **91% pass@1 en HumanEval** (vs 80% de GPT-4), **130/134 en ALFWorld**.
   → https://arxiv.org/abs/2303.11366
3. **Modo de fallo**: **depende de una senal externa fiable** (tests unitarios, exito del entorno).
   Los propios autores lo dicen; y con auto-evaluacion cae en minimos locales (WebShop). La memoria
   es una ventana deslizante de tamano fijo.
4. **27B local**: **si, y es la pieza mas barata de todas** — *siempre que la senal la de un
   ejecutor, no el modelo*. En Cognia esto es una linea de "lecciones" append-only por ciclo,
   alimentada solo por resultados de tests/comandos. Cruza con (0-B): las lecciones deben entrar
   como **restricciones positivas** ("usa X"), no como traza de error.

### 4.5 Voyager — biblioteca de skills
1. **Problema real**: acumular capacidad como **codigo ejecutable reutilizable** en vez de como
   texto. Curriculum automatico + skill library + prompting iterativo con feedback de ejecucion.
2. **Evidencia**: **3,3× mas items unicos, 2,3× mas distancia, 15,3× mas rapido al nivel madera**
   (8,5× piedra, 6,4× hierro), unico en llegar a diamante. → https://arxiv.org/abs/2305.16291
3. **Modo de fallo**: **la auto-verificacion la hace GPT-4**. Una skill mal verificada entra en la
   biblioteca y contamina todo lo que la recupere. Depende fuertemente de la calidad del modelo.
4. **27B local**: **si — es la mejor forma de memoria procedimental** porque una skill es codigo y
   **el codigo se puede re-verificar en cualquier momento con coste ~0 de tokens**. Regla dura:
   ninguna skill entra en la biblioteca sin un test que la acompane y que corra en el arranque del
   ciclo siguiente. Ya tienes la infraestructura (`flujos-aprendidos-con-examen`).

### 4.6 A-MEM / Mem0 / Zep-Graphiti — memoria agentica y grafos temporales
1. **Problema real**: extraer hechos de la conversacion, deduplicar, actualizar creencias
   contradictorias y recuperar por relevancia sin cargar todo el historial. Zep/Graphiti anade
   **validez temporal** (un hecho vale entre t0 y t1), que es lo que ninguno de los otros tiene.
2. **Evidencia (y su calidad)**:
   - **Mem0**: LoCoMo, **66,9% vs 52,9%** de la memoria de OpenAI (+26% relativo), **p95 1,44 s vs
     17,12 s** (-91%), **~1,8k tokens/conversacion vs 26k** (-90%). → https://arxiv.org/abs/2504.19413
   - **Zep**: **DMR 94,8% vs 93,4%** de MemGPT; **+18,5%** en LongMemEval con **-90% de latencia**.
     → https://arxiv.org/abs/2501.13956
   - **A-MEM** (NeurIPS 2025, notas estilo Zettelkasten con enlaces y evolucion de memoria):
     multi-hop **ROUGE-L 44,27 vs 18,09**, METEOR 23,43 vs 7,61, SBERT 70,49 vs 52,30; **-85..93%**
     de tokens en operaciones de memoria. → https://arxiv.org/abs/2502.12110
3. **Modo de fallo — y aqui hay que ser duro**:
   **el benchmark esta roto y las cifras estan disputadas entre los propios vendedores.**
   - LoCoMo usa conversaciones de **16k-26k tokens**: caben enteras en la ventana de casi cualquier
     modelo actual. **No mide memoria de largo plazo; mide recuperacion dentro de la ventana.**
   - Zep reprodujo la evaluacion de Mem0 y obtuvo **75,14% para Zep** frente al **65,99%** que Mem0
     habia reportado para Zep — atribuido a errores de implementacion del competidor.
     → https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
   - En sentido contrario, un issue en el repo de papers de Zep corrige el **84% de LoCoMo que Zep
     reclamaba a 58,44%**. → https://github.com/getzep/zep-papers/issues/5
   - Hay issues abiertos de gente que **no reproduce** los numeros de la plataforma Mem0, incluido
     que la plataforma usaba la fecha/hora actual en lugar de los timestamps del dataset.
     → https://github.com/mem0ai/mem0/issues/3944
   **Conclusion: ninguna de estas tres cifras sirve para decidir nada.** Lo que si sirve es el
   *mecanismo*: extraccion tipada + deduplicacion + validez temporal + recuperacion selectiva.
   Segundo modo de fallo, real y documentado: **una alucinacion escrita en memoria pasa a ser
   tratada como hecho verificado por todas las corridas siguientes** (memory poisoning; el vector
   no necesita atacante, basta el propio modelo).
4. **27B local**: **copia el mecanismo, ignora los benchmarks, y anade lo que ninguno tiene:
   provenance obligatoria.** Concretamente: extraccion a **esquema tipado** (no prosa),
   deduplicacion, **validez temporal explicita** (lo mejor de Zep, y es lo que evita el "resumen de
   resumen": un hecho no se reescribe, se **invalida y se anade el nuevo**), y cada entrada con
   `{fuente, ciclo, comando_que_lo_produjo, estado_de_validacion, confianza}`. Un grafo completo es
   sobre-ingenieria para 1 slot; **SQLite + FTS + campos de validez** cubre el 90% del valor.

### 4.7 LangGraph — checkpointer y human-in-the-loop
1. **Problema real**: **durabilidad y reanudacion**, no memoria. Guarda un `StateSnapshot` en cada
   super-step (valores de canales, siguiente nodo, config, metadatos, tareas pendientes),
   indexado por `thread_id`; permite `interrupt`, reanudar exactamente donde se paro, y **time
   travel**: reinvocar desde un `checkpoint_id` anterior, bifurcando.
   → https://docs.langchain.com/oss/python/langgraph/persistence
2. **Evidencia**: **ninguna de calidad**. Es infraestructura, no una tecnica con numeros.
3. **Modo de fallo**: el checkpoint guarda el **estado del grafo**, no el estado del mundo
   (ficheros, procesos, GPU). Reanudar un checkpoint sobre un mundo que cambio produce
   inconsistencias silenciosas. Y el volumen de checkpoints crece sin limite.
4. **27B local**: **el patron es obligatorio; la libreria no.** Lo que necesitas de aqui es:
   (i) **estado serializado y versionado por ciclo** (esto es literalmente lo que permite reanudar
   despues de la lobotomia), (ii) **fork/replay desde un ciclo anterior** — que es la mejor forma de
   hacer un contrafactual honesto de "¿el ciclo N-1 fue el que rompio esto?", y (iii) un punto de
   interrupcion humano. Con el 84% de acciones ramificables que ya mediste
   (`reparto-reversibilidad-medido`), el fork/replay es viable de verdad.

### 4.8 Compactacion de Claude Code y lo que Anthropic publico
1. **Problema real**: el agente se queda sin ventana en mitad de la tarea.
2. **Evidencia y mecanismos**:
   - **Compactacion**: resumir el historial y reiniciar la ventana con el resumen **mas los 5
     ficheros mas recientemente accedidos, re-leidos del disco**. Calibrar el prompt maximizando
     recall primero. Sin numeros publicos.
   - **Notas estructuradas**: el ejemplo de Claude jugando a Pokemon mantiene tallies precisos
     ("llevo 1.234 pasos entrenando en la Ruta 1, Pikachu subio 8 niveles de 10") **fuera** del
     contexto, y las relee tras cada reset. Es el mismo mecanismo que tu canal de estado.
   - **Recuperacion just-in-time**: guardar **identificadores** (rutas, queries) y cargar el dato
     en tiempo de ejecucion con `head`/`tail`/`grep`, no precargar.
   - **Sub-agentes**: contexto limpio por sub-agente, que devuelve **1.000-2.000 tokens** de
     resumen condensado al orquestador.
   - **Context editing / memory tool**: **+39%** (memoria+edicion), **+29%** (solo edicion),
     **-84% tokens** en eval interna de 100 turnos. **Eval interna.**
   - **Agent Skills** (estandar abierto, dic-2025): **divulgacion progresiva** en tres niveles —
     al arranque solo nombre+descripcion (**~80 tokens por skill**), instrucciones completas al
     activarse, scripts y referencias solo durante la ejecucion.
   → https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents ·
     https://claude.com/blog/context-management · https://platform.claude.com/docs/en/build-with-claude/context-editing
3. **Modo de fallo**: la compactacion **es** el resumen encadenado si no se re-lee del disco. El
   propio Anthropic lo mitiga con artefactos externos, no con mejores resumenes. Los sub-agentes
   pierden matiz: el resumen de 1-2k tokens es un cuello de botella deliberado.
4. **27B local**: **este es el diseno de referencia mas cercano a lo que pide el dueno**, y todas
   sus piezas son teclables en Cognia hoy. La divulgacion progresiva de Skills (~80 tokens de
   indice) es especialmente valiosa a 32k: puedes tener 100 capacidades por 8k tokens de indice, y
   eso ya es demasiado — a 32k el indice debe ser de **decenas**, no de cientos.

### 4.9 Sub-agentes y multiagente con contextos destruidos
1. **Problema real**: aislar contexto sucio (busquedas, exploracion, lecturas largas) para que no
   contamine al orquestador.
2. **Evidencia — y es contradictoria, a proposito**:
   - **A favor**: el sistema de investigacion multiagente de Anthropic supera al agente unico
     (Opus 4) en **+90,2%** en su eval interna. Pero: usa **~15× mas tokens** que un chat, y
     **el uso de tokens explica el 80% de la varianza de rendimiento**. Es decir: buena parte de la
     ganancia es **comprar computo**, no arquitectura. → https://www.anthropic.com/engineering/multi-agent-research-system
   - **En contra**: Cognition, *Don't Build Multi-Agents* (jun-2025): en cuanto hay decisiones
     dispersas y contexto no compartido, el sistema es fragil; recomienda **un solo hilo con un LLM
     de compresion dedicado**, y sub-agentes solo como consultores efimeros que devuelven un string.
     → https://cognition.com/blog/dont-build-multi-agents
   Las dos posturas se publicaron con 24 h de diferencia. Coinciden en una cosa: **un solo escritor**.
3. **Modo de fallo**: decisiones dispersas, escritores concurrentes, y el resumen de 1-2k tokens
   como unico canal (el sub-agente decide que es importante sin conocer el objetivo completo).
4. **27B local**: **el argumento del +90,2% NO te aplica** — se compra con 15× tokens y tu tienes
   **un slot**; el paralelismo real no existe aqui, asi que pagarias el 15× en **tiempo de pared**
   (y tu propia leccion "el contexto grande es un RELOJ" dice que en local los tokens son segundos).
   **Lo que si aplica**: sub-agentes **secuenciales** con contexto destruido al terminar, como
   forma de **aislamiento**, no de paralelismo. Un solo escritor del estado. Y el contrato de
   salida del sub-agente debe ser **estructurado y tipado**, no un resumen libre.

### 4.10 RAG con provenance / atribucion
1. **Problema real**: que cada afirmacion se pueda rastrear a una fuente, y que se detecte cuando
   no la tiene.
2. **Evidencia**: **ALCE** define **citation precision** y **citation recall** con un modelo NLI:
   recall = ¿la concatenacion de los documentos citados implica la frase?; precision = ¿sigue
   implicandola si quito uno? Correlacion humano/automatico kappa 0,698 (recall) y 0,525
   (precision). Hallazgo central: **incluso los modelos avanzados producen afirmaciones fluidas sin
   soporte**. → https://arxiv.org/abs/2305.14627
   Alternativa sin segundo modelo: atribucion por internos del modelo (MIRAGE) →
   https://arxiv.org/abs/2406.13663
3. **Modo de fallo**: el modelo cita la fuente **correcta** para una afirmacion **falsa**, o cita
   por proximidad. La citacion es una condicion necesaria, no suficiente.
4. **27B local**: **si, y es la pieza barata del sistema anti-alucinacion.** No necesitas un NLI
   entrenado: la forma barata es hacer **la provenance no-generativa**. Es decir, el hecho no se
   "cita": el hecho **es** `{valor, comando_exacto_que_lo_produjo, salida_cruda, hash}`. Un hecho
   que no puede reproducirse ejecutando su comando **no es un hecho**, es una hipotesis, y va a otra
   tabla con confianza baja. Esto convierte "anti-alucinacion" de un problema de NLP a un problema
   de contabilidad — que es donde se puede ganar.

### 4.11 Verificadores, PRMs y self-consistency
1. **Problema real**: convertir computo extra en acierto sin entrenar el generador.
2. **Evidencia**:
   - **Self-consistency** (muestreo + voto mayoritario): GSM8K **+17,9**, SVAMP **+11,0**,
     AQuA **+12,2**, StrategyQA **+6,4**, ARC-c **+3,9**. → https://arxiv.org/abs/2203.11171
   - **ThinkPRM** (PRM generativo): con **1%** de las etiquetas de proceso de PRM800K supera a PRMs
     discriminativos entrenados con el 100% en **+8%** y **+4,5%** fuera de dominio, y a
     LLM-as-judge en **+7,2%**. → https://arxiv.org/abs/2504.16828
   - **Verificacion comparativa > absoluta** (ver seccion 2).
3. **Modo de fallo**: self-consistency **solo funciona si la respuesta es una entidad comparable**
   (un numero, una etiqueta). En codigo o prosa, "la mayoria" no esta definida. Y con un verificador
   debil, best-of-N **selecciona el error mas confiado**.
4. **27B local**: **self-consistency es caro con 1 slot** (N pasadas = N× segundos de pared) y esto
   ya lo mediste: BoN replica **+21,00 sobre el azar en LiveCodeBench** *cuando hay senal real*, y
   **reparar no bate a remuestrear a iso-computo (57 vs 57)**. El cuello no es el metodo: es
   fabricar senal. **Aplica self-consistency solo donde la salida sea un token comparable**
   (¿esta hecho el subobjetivo? si/no; ¿que hipotesis?) y **nunca** como verificacion de codigo.

### 4.12 Sleep-time compute
1. **Problema real**: hacer el trabajo de preparacion del contexto **antes** de que llegue la
   consulta, amortizandolo.
2. **Evidencia**: **~5× menos computo en test-time** para la misma precision en Stateful
   GSM-Symbolic y Stateful AIME; **hasta +18%** de precision al escalar el computo offline;
   **~2,5× menos coste por consulta** cuando varias consultas comparten el mismo contexto.
   → https://arxiv.org/abs/2504.13171
3. **Modo de fallo**: si no aciertas que se va a preguntar, es computo tirado. Solo gana cuando el
   contexto es estable y las consultas son predecibles.
4. **27B local**: **encaja perfecto con el ciclo de lobotomia y con tener 1 slot ocioso.**
   El paso de compresion **es** sleep-time compute: en vez de "resumir", pre-computar lo que el
   ciclo siguiente va a necesitar (indice de ficheros tocados, hipotesis vivas, siguiente comando,
   invariantes a re-verificar). Y como el objetivo del agente es estable durante horas, la
   condicion "contexto estable" se cumple. **Esta es probablemente la tecnica mas infravalorada
   del lote para tu caso.**

### 4.13 SWE-agent y agentes de larga duracion
1. **Problema real**: interfaz agente-ordenador (ACI) — como se le presentan los ficheros y comandos
   al modelo determina el rendimiento tanto como el modelo.
2. **Evidencia**: SWE-agent, **12,5% pass@1 en SWE-bench** (2024) — cifra ya superada, pero el punto
   sigue en pie: **la ACI, no el modelo, fue el delta**. → https://arxiv.org/abs/2405.15793
   **METR**: el horizonte de tarea al **50%** de fiabilidad se dobla cada ~7 meses (~4 meses en
   2024-25); **el horizonte al 80% es 4-6× mas corto**. → https://arxiv.org/abs/2503.14499
   Alta varianza al remuestrear la misma traza con el mismo setup.
3. **Modo de fallo**: el "lucky pass" (resolver por el motivo equivocado) y la varianza entre
   corridas — cosa que ya tienes medida en este proyecto (**±34 puntos entre corridas**).
4. **27B local**: **la leccion aplicable es la del 80%**: si disenas para el 50% de exito, en la
   practica tienes 4-6× menos horizonte util. Diseña los ciclos para que **fallar sea barato y
   detectable**, no para que no fallen.

### 4.14 Alternativas recurrentes: RMT, state-space, Titans
1. **Problema real**: memoria en los pesos/estado en vez de en el prompt.
2. **Evidencia**: **RMT con GPT-2 (137M)** resuelve BABILong hasta **11,1 millones de tokens** con
   >90% de acierto, superando ampliamente a GPT-4 — que se degrada bruscamente pasados ~10k y usa
   efectivamente ~10-20% de sus 128k. ARMT escala a **50M**.
   → https://arxiv.org/abs/2402.10790 · https://arxiv.org/abs/2407.04841
   **Titans** (NeurIPS 2025): modulo de memoria neuronal a largo plazo entrenado **en test-time**
   con sorpresa + momentum + decaimiento; >2M tokens.
   → https://arxiv.org/abs/2501.00663
3. **Modo de fallo — el que mata**: **esos numeros son con fine-tuning en la tarea**. RMT con GPT-2
   gana a GPT-4 en BABILong porque **se entreno en BABILong**; no es un modelo general. Titans
   requiere entrenar la arquitectura. Ninguno tiene un checkpoint de 27B instruido y utilizable.
4. **27B local**: **KILL, con matiz.** No hay via para usar esto con Qwen3.8-27B en llama.cpp; no
   existe el modelo. El matiz que **si** te llevas: la evidencia de RMT demuestra que **un estado
   recurrente pequeno y de tamano fijo puede sostener millones de tokens de tarea** — que es
   exactamente la apuesta arquitectonica del ciclo de lobotomia, solo que implementada en texto y
   ficheros en vez de en activaciones. Es el mismo teorema, en otro sustrato. Y el sustrato de texto
   tiene una ventaja que el de activaciones no: **es inspeccionable y verificable**.

---

## 5. Tabla comparativa

Columnas: **Evidencia** = calidad de la evidencia publica (A = paper revisado con numeros
reproducibles / B = paper con numeros pero de los autores del sistema / C = disputado o eval interna
de vendedor / D = sin numeros). **VRAM** = si aumenta la VRAM en 1 slot. **Aplica** = veredicto para
27B / 32k / 1 slot.

| Tecnica | Resuelve | Numero clave | Evidencia | Modo de fallo | VRAM | Aplica al 27B/32k/1slot |
|---|---|---|---|---|---|---|
| Lobotomia + estado externo (compaction+notas, Anthropic) | Horizonte > ventana | +39% / -84% tokens (interna); Pokemon multi-hora | C | La compactacion **es** resumen encadenado si no se re-lee del disco | No | **SI — nucleo del diseno** |
| Auto-conditioning: contexto limpio | Los errores propios degradan | 85% → 70% → 55% (Qwen3-32B, turno 100) | A | Perder contexto util al limpiar | No | **SI — la justificacion empirica** |
| Horizonte multi-turno corto | Cuanto dura un ciclo | Gemma3-27B ~8, Qwen3-32B ~15 turnos | A | — | No | **SI — fija el largo del ciclo** |
| Memoria jerarquica MemGPT/Letta | Ventana finita | DMR ~93,4%; LoCoMo 74,0% | B | El agente pagina mal, en silencio | No | Patron si; auto-edicion autonoma no |
| CoALA | Taxonomia de memoria | — | D | Citarlo como resultado | No | Solo como esquema |
| Generative Agents (stream+reflexion) | Coherencia larga | Ablaciones sobre **credibilidad** | B | Reflexion = resumen encadenado sin verificar | No | Recuperacion si; reflexion solo con examen |
| Reflexion | Aprender del fallo | HumanEval 91% vs 80%; ALFWorld 130/134 | A | Inutil sin senal externa; minimos locales | No | **SI, con ejecutor como senal** |
| Voyager (skill library) | Memoria procedimental | 3,3× items; 15,3× madera; unico diamante | A | Skill mal verificada contamina | No | **SI — la skill es codigo re-verificable** |
| Mem0 | Extraccion+dedup | 66,9% vs 52,9%; -91% p95; -90% tokens | **C (disputado)** | LoCoMo cabe en la ventana; no reproducido | No | Mecanismo si, cifras no |
| Zep / Graphiti | Validez temporal de hechos | DMR 94,8; LongMemEval +18,5% | **C (disputado)** | Coste de mantener el grafo; cifras corregidas a la baja | No | **Validez temporal SI**; grafo completo = sobre-ingenieria |
| A-MEM | Enlaces y evolucion de notas | multi-hop ROUGE-L 44,3 vs 18,1 | B (sobre LoCoMo) | Mismo caveat de benchmark | No | Mecanismo si |
| LangGraph checkpointer / HITL | Reanudar y bifurcar | — | D | El checkpoint no captura el mundo | No | **Patron SI** (fork/replay = contrafactual) |
| Sub-agentes con contexto destruido | Aislar contexto sucio | +90,2% pero **15× tokens**, 80% de la varianza = tokens | C | Decision dispersa; resumen de 1-2k como cuello | No (secuencial) | **Secuenciales SI**; paralelos NO (1 slot) |
| Multi-agente paralelo | Amplitud | idem | C / contradicho por Cognition | Fragilidad, escritores multiples | Si (N modelos) | **NO** |
| RAG con provenance (ALCE) | Rastrear afirmaciones | kappa 0,698 / 0,525 | A | Cita correcta para afirmacion falsa | No | **SI, en version no-generativa** |
| Self-consistency | Convertir computo en acierto | GSM8K +17,9 | A | Indefinido en codigo/prosa; caro con 1 slot | No | Solo para salidas comparables |
| PRM / verificador entrenado | Senal de proceso | ThinkPRM +8 / +4,5 OOD / +7,2 vs judge | A | Requiere entrenar; DeltaBench muestra limites | Si (2º modelo) | Dificil; usar verificador **ejecutable** |
| Critico del **mismo** modelo | (pretende) cazar errores | Degrada sin oraculo; ≤13B necesitan verificador fuerte; sesgo -38%..+90% | A | **Aprueba trabajo roto** | No | **NO — usar como brazo de control** |
| Critico **comparativo** (A vs B) | Cazar errores con senal | Verificacion por comparacion > absoluta | A | Sigue sin ser oraculo | No | **SI — la version viable del critico** |
| Entropia semantica | Detectar confabulacion | AUROC > P(True)/self-check (Nature) | A | N muestras = N× pared con 1 slot | No | Puntual, en afirmaciones criticas |
| Sleep-time compute | Amortizar preparacion | ~5× menos computo test-time; +18% | A | Inutil si no aciertas la consulta | No | **SI — es el paso de compresion bien hecho** |
| Agent Skills / divulgacion progresiva | Indice barato de capacidades | ~80 tokens por skill | D | Un indice grande vuelve a llenar la ventana | No | SI, con decenas de skills, no cientos |
| RMT / ARMT / Titans | Memoria en el estado | RMT-GPT2 11,1M tokens; ARMT 50M | A | **Requiere fine-tuning; no hay 27B instruido** | — | **NO (via cerrada)** |

---

## 6. Lo que la literatura NO cubre y tendras que medir tu

1. **Cuantos ciclos de lobotomia aguanta una restriccion antes de evaporarse.** Nadie lo ha medido.
   Tu ya tienes el instrumento: el experimento del canal de estado (recall 0,07 → 1,00, 0 de 5
   restricciones supervivientes sin canal). Extiendelo al eje **numero de ciclos**: 1, 3, 10, 30.
   **Metrica primaria: fraccion de restricciones del ciclo 1 verificables en el ciclo N.**
   Brazo nulo obligatorio: contexto continuo sin lobotomia (que morira por ventana, y ese es el
   punto de comparacion honesto).
2. **Si un critico Qwythos-9B mejora sobre el azar juzgando salidas de Qwen3.8-27B**, en modo
   comparativo y en modo absoluto. La literatura predice: absoluto ≈ azar, comparativo > azar.
   Es una prediccion falsable en una tarde y decide si el "agente critico separado" existe o no.
3. **El coste real de la lobotomia en segundos de pared** con 1 slot: prefill del estado
   reconstruido en cada ciclo vs mantener el KV. Con la leccion "el contexto grande es un RELOJ",
   la lobotomia **puede salir mas cara** si el estado reconstruido es grande. Numero a medir:
   tokens del estado recuperado × ciclos vs tokens de un contexto continuo.
4. **Si la degradacion por self-conditioning aparece en Qwen3.8-27B** con el protocolo de
   arXiv:2509.09677 (inyectar 0%/25%/50% de errores en el historial). Si aparece, la lobotomia esta
   justificada por dos vias independientes; si no, solo por la ventana.

---

## 7. Consecuencias de diseno (lo que se deriva de todo lo anterior)

Sin proponer implementacion — solo lo que la evidencia obliga:

1. **El ciclo dura menos de ~10 acciones**, no "hasta que se llene la ventana". (0-A)
2. **El estado se reconstruye de artefactos primarios, no del resumen anterior.** Objetivo,
   restricciones, decisiones y hechos permanentes son **append-only con validez temporal**;
   estado y plan se reescriben; la charla se tira. (1, 4.6)
3. **La traza de errores no viaja entre ciclos**; viaja la **leccion positiva** derivada. (0-B)
4. **Las restricciones criticas se repiten al final del contexto** y el agente **recita la
   evidencia antes de actuar**. (3)
5. **El verificador ejecuta.** El critico LLM solo se usa en modo comparativo, y preferentemente de
   otra familia. Un critico del mismo modelo en la misma sesion es un brazo de control, no un
   instrumento. (2)
6. **Un hecho sin comando reproducible no es un hecho.** La provenance es contabilidad, no NLP. (4.10)
7. **Los sub-agentes son secuenciales y su salida es tipada**, no un resumen libre; el paralelismo
   no existe con 1 slot y su ganancia publicada se compra con 15× tokens. (4.9)
8. **La compresion se disena como sleep-time compute**: no "resume el pasado", sino "pre-computa lo
   que el ciclo siguiente va a necesitar". (4.12)
9. **VRAM constante sale gratis** si el ciclo no cambia de modelo: la lobotomia es I/O de disco y
   prefill, no carga de pesos. El unico riesgo de VRAM es el critico de otra familia — que en 1
   slot cuesta **recarga de modelo**, es decir, tiempo, no memoria. (hardware)
10. **Todo lo anterior es teclable en Cognia hoy** y no depende de ninguna libreria de las citadas.

---

## 8. Fuentes

Degradacion por longitud y posicion
- Liu et al., *Lost in the Middle* — https://arxiv.org/abs/2307.03172
- Chroma, *Context Rot* (18 modelos) — https://www.trychroma.com/research/context-rot
- *Context Length Alone Hurts LLM Performance Despite Perfect Retrieval* — https://arxiv.org/abs/2510.05381
- *BABILong* (NeurIPS 2024) — https://arxiv.org/abs/2406.10149
- *In Search of Needles in a 11M Haystack* (RMT) — https://arxiv.org/abs/2402.10790
- Wu et al., *LongMemEval* (ICLR 2025) — https://arxiv.org/abs/2410.10813

Horizonte largo y auto-condicionamiento
- *The Illusion of Diminishing Returns* (NeurIPS 2025) — https://arxiv.org/abs/2509.09677
- Laban et al., *LLMs Get Lost In Multi-Turn Conversation* — https://arxiv.org/abs/2505.06120
- METR, *Measuring AI Ability to Complete Long Tasks* — https://arxiv.org/abs/2503.14499

Memoria de agentes
- Packer et al., *MemGPT* — https://arxiv.org/abs/2310.08560
- Sumers et al., *CoALA* — https://arxiv.org/abs/2309.02427
- Park et al., *Generative Agents* — https://arxiv.org/abs/2304.03442
- Shinn et al., *Reflexion* — https://arxiv.org/abs/2303.11366
- Wang et al., *Voyager* — https://arxiv.org/abs/2305.16291
- Chhikara et al., *Mem0* — https://arxiv.org/abs/2504.19413
- Rasmussen et al., *Zep* — https://arxiv.org/abs/2501.13956
- Xu et al., *A-MEM* (NeurIPS 2025) — https://arxiv.org/abs/2502.12110
- Zep, *Is Mem0 Really SOTA?* — https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
- Correccion del 84%→58,44% de Zep — https://github.com/getzep/zep-papers/issues/5
- No-reproduccion de Mem0 — https://github.com/mem0ai/mem0/issues/3944
- LangGraph persistence / time travel — https://docs.langchain.com/oss/python/langgraph/persistence

Ingenieria de contexto (industria)
- Anthropic, *Effective context engineering for AI agents* — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, *Effective harnesses for long-running agents* — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, *Managing context on the Claude Developer Platform* (+39% / -84%) — https://claude.com/blog/context-management
- Anthropic, context editing (docs) — https://platform.claude.com/docs/en/build-with-claude/context-editing
- Anthropic, *How we built our multi-agent research system* — https://www.anthropic.com/engineering/multi-agent-research-system
- Cognition, *Don't Build Multi-Agents* — https://cognition.com/blog/dont-build-multi-agents

Verificacion, critica y alucinacion
- Huang et al., *LLMs Cannot Self-Correct Reasoning Yet* (ICLR 2024) — https://openreview.net/pdf?id=IkmD3fKBPQ
- Kamoi et al., *When Can LLMs Actually Correct Their Own Mistakes?* (TACL 2024) — https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00713/125177/
- *Critique Ability of LLMs* / CriticBench — https://arxiv.org/abs/2310.04815
- *Small Language Models Need Strong Verifiers to Self-Correct Reasoning* — https://arxiv.org/abs/2404.17140
- *Self-Preference Bias in LLM-as-a-Judge* — https://arxiv.org/abs/2410.21819
- DeltaBench, *Can LLMs Detect Errors in Long CoT Reasoning?* — https://arxiv.org/abs/2502.19361
- McAleese et al., *LLM Critics Help Catch LLM Bugs* (CriticGPT) — https://arxiv.org/abs/2407.00215
- Kumar et al., *SCoRe* (ICLR 2025) — https://proceedings.iclr.cc/paper_files/paper/2025/file/871ac99fdc5282d0301934d23945ebaa-Paper-Conference.pdf
- *Shrinking the Generation-Verification Gap with Weak Verifiers* — https://arxiv.org/abs/2506.18203
- Wang et al., *Self-Consistency* — https://arxiv.org/abs/2203.11171
- Khalifa et al., *Process Reward Models That Think* (ThinkPRM) — https://arxiv.org/abs/2504.16828
- Farquhar et al., *Detecting hallucinations using semantic entropy* (Nature 2024) — https://www.nature.com/articles/s41586-024-07421-0
- Gao et al., *ALCE* — https://arxiv.org/abs/2305.14627
- *MIRAGE: Model Internals-based Answer Attribution* — https://arxiv.org/abs/2406.13663

Computo y arquitectura
- Lin et al., *Sleep-time Compute* — https://arxiv.org/abs/2504.13171
- Yang et al., *SWE-agent* — https://arxiv.org/abs/2405.15793
- Behrouz et al., *Titans* (NeurIPS 2025) — https://arxiv.org/abs/2501.00663
- *Associative Recurrent Memory Transformer* — https://arxiv.org/abs/2407.04841

---

## 9. Nota de honestidad sobre este documento

- Las cifras marcadas **A** las he verificado contra el paper o su pagina oficial.
- Las marcadas **C** son de vendedor o estan activamente disputadas entre partes interesadas; las
  incluyo **porque el dueno preguntaba por ellas**, no porque decidan nada.
- He **excluido a proposito** una docena de preprints de 2026 que aparecieron en las busquedas
  (compactacion paralela, rate-distortion de memoria, memoria tipada con provenance, control-plane
  placement) porque no pude verificar sus numeros de forma independiente. Si alguno resulta ser
  real y relevante, el hueco que llenan esta senalado en la seccion 6.
- Ningun numero de este documento sustituye a una medicion en esta maquina. Casi todos los papers
  citados usan modelos de frontera o GPUs de datacenter; **el unico dato del lote que es
  directamente de tu clase de hardware y tamano de modelo es el horizonte de Gemma3-27B (~8 turnos)
  y Qwen3-32B (~15 turnos)**, y es el que mas debe pesar en el diseno.
