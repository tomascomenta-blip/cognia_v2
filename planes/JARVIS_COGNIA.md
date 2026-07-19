# JARVIS PARA COGNIA — wake word "cerebro", pantalla, mouse e imágenes

**Fecha:** 2026-07-19
**Estado:** DISEÑO — nada implementado. Gates pre-registrados abajo.
**Hardware:** Ryzen 5 9600X (6c/12t), 31 GB RAM, RTX 5060 Ti 16 GB (sm_120), Windows 11.
**Pedido del dueño (literal, transcrito de voz):** *"yo diga cerebro, abreme esta pestaña
y haces todo"*, más captura de pantalla en tiempo real con detección de cambio de frames,
control de mouse tipo PyAutoGUI combinable con Playwright, y poder mandar/recibir imágenes
por el CLI.

Convención de citas: **[V]** = página abierta y leída durante esta investigación.
**[S]** = vista solo en resultados de búsqueda, NO abierta; tratar como no verificada.

---

## 0. Resumen ejecutivo (leer esto primero)

1. **Ningún proyecto tipo Jarvis conviene adoptarlo entero.** Se investigaron los
   candidatos más fuertes y ninguno sirve como base para Cognia. El mejor de todos por
   madurez es `isair/jarvis` (1.4k estrellas, 391 commits, 38 releases, v1.34.1 del
   7-may-2026, Windows nativo) **[V]**, pero tiene dos problemas que lo descartan como
   base: su licencia es *"free for personal use; commercial requires contact"* — no es
   open source utilizable — y **es un competidor de Cognia, no un componente**: trae su
   propio LLM, su propia memoria y sus propias tools. Adoptarlo significa tirar Cognia y
   quedarse con él. Además su control de escritorio es solo Chrome, no mouse/teclado
   general.
2. **El proyecto que la búsqueda vendía como ideal resultó humo.** `PanPenek/JarvisAi`
   aparecía descrito como "wake word + screen vision + 31 tools + fully offline", que es
   casi literalmente el pedido. Al abrir el repo: **1 estrella y 3 commits** **[V]**. No
   es un proyecto, es un fin de semana de alguien. Sirve solo como *referencia de
   arquitectura*, y vale para eso: su stack (openWakeWord + faster-whisper + Kokoro +
   PyAutoGUI) coincide con lo que la investigación por componente recomienda por separado.
3. **Conclusión honesta: hay que ensamblar componentes, no adoptar un producto.** Es más
   trabajo pero es la única ruta que respeta lo que Cognia ya es. La pila recomendada está
   en la sección 2.
4. **Nada de esto existe hoy en el repo.** Verificado con grep sobre el código real
   (excluyendo `venv312/`): `pyautogui` 0 archivos, `dxcam` 0, `mss` 0, `ImageGrab` 0,
   `pywinauto` 0, `whisper` 0, `sounddevice` 0, `pyaudio` 0, `porcupine` 0, `playwright` 0,
   `kokoro` 0, `piper` 0. `requirements.txt` no declara una sola dependencia de audio,
   visión ni automatización. **Esto es terreno virgen**, no "algo ya medio implementado".
   Conviene saberlo antes de estimar.
5. **La decisión técnica más importante del plan, y la más contraintuitiva:** para
   *"cerebro, abrime esta pestaña"* **no hace falta un modelo de visión**. Mirar píxeles es
   el camino lento, frágil y caro. Windows expone un árbol de accesibilidad (UI Automation)
   que dice qué ventanas, botones y pestañas existen, con sus nombres y coordenadas, de
   forma determinista y en milisegundos. La visión se reserva para lo que la accesibilidad
   no puede contestar ("¿qué dice este gráfico?"). Ver 2.4.

---

## 1. Qué se investigó y qué se encontró

### 1.1 Asistentes tipo Jarvis completos

| Proyecto | Estado real | Veredicto |
|---|---|---|
| `isair/jarvis` **[V]** | 1.4k ★, 391 commits, v1.34.1 (7-may-2026), Windows nativo, Whisper + Piper/Chatterbox + Ollama (gemma4:e2b), MCP para tools | **El mejor de todos**, pero licencia no comercial y reemplaza a Cognia. Usar como referencia de UX, no como base |
| `PanPenek/JarvisAi` **[V]** | **1 ★, 3 commits**, MIT, Windows 10/11, openWakeWord + faster-whisper + Kokoro + PyAutoGUI + OCR por PowerShell | Humo. Vale solo como plano de arquitectura |
| `open-jarvis/OpenJarvis` **[S]** | Ligado a "Intelligence Per Watt" (Hazy Research / Stanford SAIL) | No verificado. Revisar antes de descartar |
| Mycroft AI **[S]** | Histórico, la empresa cerró en 2023; continúa como OpenVoiceOS | No usar el original |

### 1.2 Wake word — el componente más crítico del pedido

- **openWakeWord** — open source, entrena palabras personalizadas en 20+ idiomas sin
  necesidad de datos reales (usa TTS sintético), corre en ONNX sobre CPU, se integra con
  Home Assistant / Rhasspy / OpenVoiceOS **[S]**. Requiere algo de trabajo de ML para
  entrenar **[S]**. **Gratis.**
- **Picovoice Porcupine** — el más maduro, entrenar una palabra toma menos de diez
  segundos en su consola web por transfer learning, soporta español **[S]**. Pero cuesta
  **6.000+ USD/año** para uso serio **[S]**. Descartado por costo.
- **LiveKit** publicó un entrenador de wake word personalizado *"in a single command"*
  sobre openWakeWord **[S]** — si funciona, elimina la única desventaja real de
  openWakeWord frente a Porcupine.

**Elección: openWakeWord**, entrenando "cerebro" con muestras sintéticas de TTS en español.
Segunda opción: Porcupine solo si openWakeWord no alcanza precisión aceptable y el dueño
acepta el costo.

### 1.3 Voz: STT y TTS

- **STT — faster-whisper.** Es la reimplementación de producción de Whisper, 4× más rápida
  en GPU con int8 **[S]**. Para español hay que quedarse con `large-v3`, que es el estándar
  de oro multilingüe **[S]**, pero pide ~10 GB de VRAM **[S]** y el 7B ya ocupa 6.3 GB
  medidos. **No entran los dos.** La salida es `large-v3-turbo` (~6 GB **[S]**) o `medium`.
  Ver el presupuesto de VRAM en 2.6.
- **NVIDIA Parakeet** es dramáticamente más rápido (RTFx >2000) **[S]** pero está orientado
  a inglés; no es la elección para español.
- **TTS — Piper** emite el primer audio en ~40 ms y sintetiza ~30× más rápido que tiempo
  real **[S]**, tiene voces en español y corre en CPU. Suena, en palabras de una de las
  comparativas, *"como un GPS de 2015"* **[S]**. **Kokoro-82M** (Apache 2.0, 82M params,
  2-3 GB o CPU) suena mucho más natural de lo que su tamaño sugiere **[S]**, pero su
  cobertura de español hay que verificarla. **XTTS v2** clona voz y suena humano pero es
  >10× más lento **[S]**.

**Elección: Piper para empezar** (latencia y CPU son lo que importa en un asistente por
voz), con Kokoro como mejora de calidad si tiene voz en español decente. Gate V1 abajo.

### 1.4 Control de escritorio — dónde casi todos se equivocan

El estado del arte en "computer use" son agentes de visión pura:

- **UI-TARS (ByteDance)** — Apache 2.0, modelos de 2B/7B/72B entrenados específicamente en
  capturas y secuencias de acciones de UI; procesa capturas como única entrada y genera
  clics y teclas; entiende patrones propios de Windows (cinta de opciones, barra de tareas,
  Explorador) **[S]**. UI-TARS-desktop tiene ~32k ★ **[S]**.
- **OmniParser (Microsoft)** — convierte una captura en elementos estructurados para que un
  modelo de visión pueda accionar sobre regiones concretas **[S]**.

**Por qué NO son la respuesta para este pedido.** Un UI-TARS 7B ocupa la VRAM que ya tiene
el Qwen 7B, tarda segundos por acción y falla de formas impredecibles. Para *"abrime esta
pestaña"* eso es usar un cohete para cruzar la calle. Windows ya expone **UI Automation**,
el árbol de accesibilidad, vía `uiautomation`/`pywinauto`: da la lista de ventanas,
pestañas y botones con nombre y coordenadas, es determinista, tarda milisegundos y no gasta
VRAM. Y para el navegador, **Playwright** controla pestañas por API real, sin adivinar.

**Elección: arquitectura en tres capas, de barata a cara.**
1. **Playwright** para todo lo que sea navegador (abrir/cerrar/cambiar pestañas, navegar).
2. **UI Automation** (`uiautomation`) para el resto del escritorio (abrir apps, menús,
   ventanas).
3. **PyAutoGUI + visión** solo como último recurso, cuando las dos anteriores no ven el
   elemento (apps que dibujan su propia UI, juegos, Electron mal etiquetado).

Esto invierte la prioridad respecto de lo que hacen los proyectos de moda, y es lo correcto
para este caso de uso.

### 1.5 Captura de pantalla y detección de cambios

- **DXcam** — usa la Desktop Duplication API de DirectX, alcanza **240+ FPS** **[S]**,
  Windows exclusivo. `mss` da 30-60 FPS y es multiplataforma **[S]**. Para Windows nativo
  DXcam gana sin discusión. (Existe **BetterCam** como fork mantenido **[S]**; verificar
  cuál está más vivo, porque DXcam tuvo períodos sin mantenimiento.)
- **Detección de cambio de frame** — el enfoque correcto es *perceptual hashing*: se calcula
  un hash de cada frame y se compara con el anterior; si la distancia de Hamming supera un
  umbral, es un cambio de escena **[S]**. Es *"muy eficiente computacionalmente comparado
  con otros métodos de detección"* **[S]** y convierte a grises, así que ignora cambios de
  color puro. PySceneDetect implementa esto como `HashDetector` **[S]**.

**Elección: DXcam capturando a baja tasa (2-4 FPS es más que suficiente para "momentos
importantes") + dHash con umbral de Hamming.** Capturar a 240 FPS para tirar el 99% sería
absurdo; la gracia es capturar poco y guardar menos.

### 1.6 Visión e imágenes en el CLI

- **Qwen3-VL** (2B / 8B / 32B) reemplazó a Qwen2.5-VL en la cima; el de 8B maneja OCR,
  gráficos y **capturas de pantalla** mejor que su predecesor en todos los benchmarks
  **[S]**. Hay GGUF y llama.cpp lo soporta desde el 30-oct-2025 vía `llama-mtmd-cli` **[S]**.
  Es la elección obvia para "mirá esta captura y decime qué dice".
- **Imágenes dentro de la terminal**: la investigación **no pudo confirmar** qué protocolo
  gráfico soporta Windows Terminal en 2026 (sixel / kitty / iTerm2 inline). Queda como
  incógnita declarada D3 y hay que probarlo a mano, no asumirlo.

---

## 2. Diseño propuesto para Cognia

### 2.1 Principio rector

Cognia ya tiene motor de lenguaje, memoria episódica, grafo de conocimiento, CLI y
enrutado. **Nada de lo que se agregue puede reemplazar eso.** Todo lo nuevo entra como
subsistemas periféricos que hablan con el núcleo existente por las interfaces que ya usa
el CLI (`responder_articulado`, los slash commands, el registro de tools). Si un componente
exige ser el centro, se descarta: por eso se descarta `isair/jarvis`.

### 2.2 Módulos nuevos

```
cognia/voz/
    wake.py         openWakeWord escuchando "cerebro" en un hilo, ~0.1 core
    stt.py          faster-whisper, carga perezosa, se descarga tras N segundos ocioso
    tts.py          Piper (CPU), cola de reproducción, interrumpible
    sesion.py       máquina de estados: DORMIDO -> DESPIERTO -> ESCUCHANDO -> PENSANDO -> HABLANDO

cognia/pantalla/
    captura.py      DXcam, 2-4 FPS configurable, region o pantalla completa
    cambios.py      dHash + distancia de Hamming; emite eventos "cambio de escena"
    memoria_visual.py  guarda solo los frames que superan el umbral, con TTL y tope de disco

cognia/control/
    navegador.py    Playwright (capa 1): pestañas, navegación, clics por selector
    escritorio.py   uiautomation (capa 2): apps, ventanas, menús por nombre
    raton.py        PyAutoGUI (capa 3): último recurso, con confirmación
    permisos.py     gate de seguridad: qué acciones requieren confirmación explícita

cognia/vision/
    vlm.py          Qwen3-VL por llama.cpp (mtmd), carga y descarga bajo demanda
    terminal.py     mostrar imagenes en el CLI (protocolo a determinar, ver D3)
```

### 2.3 El flujo de "cerebro, abrime esta pestaña"

```
1. wake.py detecta "cerebro"                        (CPU, siempre activo, ~0 VRAM)
2. sesion.py pasa a ESCUCHANDO, tts.py hace un beep corto
3. stt.py transcribe hasta el silencio              (GPU, carga perezosa)
4. el texto entra al motor de Cognia por la MISMA puerta que el CLI
5. el motor decide que es una accion, no una charla, y elige la herramienta
6. control/navegador.py ejecuta                     (determinista, sin visión)
7. tts.py confirma en voz
```

El paso 5 es donde se apoya en lo que Cognia ya tiene (`decision_gate`, el registro de
tools). No se construye un cerebro nuevo: se le dan manos al que ya está.

### 2.4 Por qué la capa de accesibilidad va primero

Para "abrime esta pestaña", la capa 1 (Playwright) resuelve en ~50 ms con certeza. Un
agente de visión necesitaría: capturar, redimensionar, tokenizar la imagen (cientos de
tokens), inferir con un 7B-VL (segundos), obtener coordenadas aproximadas, clickear y
esperar a ver si acertó. Es dos órdenes de magnitud más caro y falible. La visión se usa
para lo que solo la visión puede hacer: **describir**, no **accionar**.

### 2.5 Seguridad (no negociable)

Cognia con mouse y teclado es Cognia capaz de borrar archivos, mandar mensajes y comprar
cosas. `control/permisos.py` es obligatorio desde el día uno, no un extra:

- Lista blanca de acciones que se ejecutan sin preguntar (abrir pestaña, buscar, leer).
- Confirmación hablada obligatoria para: cerrar sin guardar, borrar, enviar, pagar,
  cualquier cosa en una ventana de banco o de correo.
- La captura de pantalla continua **jamás** sale del disco local y respeta la restricción
  dura del repo (cero datos personales centralizados). Pausa automática cuando la ventana
  activa es un gestor de contraseñas o una ventana de incógnito.
- Tope de disco y TTL para la memoria visual, con borrado real.

### 2.6 Presupuesto de VRAM (16 GB, medido donde dice medido)

| Componente | VRAM | Nota |
|---|---|---|
| Qwen2.5-7B Q4_K_M + KV 16k | **6.3 GB** | medido con nvidia-smi en esta máquina |
| faster-whisper large-v3-turbo | ~6 GB **[S]** | carga perezosa, se descarga al minuto ocioso |
| Piper TTS | ~0 | CPU |
| openWakeWord | ~0 | CPU, ONNX |
| DXcam + dHash | ~0 | CPU |
| Qwen3-VL 8B Q4 | ~6 GB **[S]** | **NO entra a la vez que STT**; swap bajo demanda |

**Conclusión dura: no entran los tres modelos juntos.** El plan exige un gestor de
residencia que mantenga el 7B siempre cargado y haga swap de STT y VLM según haga falta.
Si el swap resulta demasiado lento, la alternativa es `whisper medium` (~2.5 GB) y aceptar
algo menos de precisión en español. Esto se mide en el gate J2, no se asume.

---

## 3. Gates pre-registrados (definidos ANTES de escribir código)

| Gate | Qué mide | Umbral | Si falla |
|---|---|---|---|
| **J0** entorno | openWakeWord, faster-whisper, Piper, DXcam y uiautomation instalan y corren en Windows 11 nativo con Python 3.12 | los 5 | el que falle se reemplaza por su segunda opción antes de seguir |
| **J1** wake word | "cerebro" entrenado: falsos positivos en 8 h de uso normal, y detección real a 3 m con ruido de fondo | ≤2 falsos positivos por hora **y** ≥90% de detección | probar Porcupine (con su costo) o cambiar la palabra por una menos común |
| **J2** VRAM y swap | tiempo de swap STT↔VLM con el 7B residente | swap ≤3 s y sin OOM | bajar a whisper medium; si aun así falla, STT en CPU |
| **J3** latencia e2e | de terminar de hablar a que empiece la respuesta hablada, en "cerebro, abrime una pestaña" | ≤2.5 s mediana de 10 intentos | perfilar y atacar el componente dominante |
| **J4** acción correcta | 20 comandos de escritorio guionados (abrir pestaña, buscar, cambiar ventana, cerrar) | ≥18/20 sin intervención | revisar la capa 1/2 antes de agregar visión |
| **J5** pantalla | 1 h de captura continua a 3 FPS: uso de CPU y frames guardados tras el filtro dHash | CPU ≤8% de un core **y** ≤200 frames/h guardados | subir el umbral de Hamming o bajar los FPS |
| **J6** visión | 10 capturas reales: el VLM responde correctamente qué hay en pantalla | ≥8/10 | probar Qwen3-VL 32B si la VRAM lo permite, o descartar la visión |

**Presupuesto pre-registrado:** las fases 1 y 2 (secciones 4.1 y 4.2) antes de decidir si
se sigue. Cualquier extensión se re-registra por escrito, igual que en el plan DSPARK.

---

## 4. Plan de implementación por fases

### 4.1 Fase 1 — La voz (el corazón del pedido)
1. `cognia/voz/wake.py` con openWakeWord y un modelo de "cerebro" entrenado con TTS
   sintético. Gate J1.
2. `cognia/voz/stt.py` con faster-whisper y carga perezosa. Gate J2.
3. `cognia/voz/tts.py` con Piper y voz en español.
4. `cognia/voz/sesion.py` con la máquina de estados y un slash command `/voz` para
   encender y apagar todo.
5. Prueba CLI real: decir "cerebro, ¿qué hora es?" y que conteste hablando. Gate J3.

**Entregable:** Cognia escucha y contesta por voz. Todavía no toca nada del sistema.

### 4.2 Fase 2 — Las manos
1. `cognia/control/permisos.py` **primero**, antes que cualquier capacidad de acción.
2. `cognia/control/navegador.py` con Playwright.
3. `cognia/control/escritorio.py` con uiautomation.
4. Registrar ambas como tools del motor de Cognia.
5. Gate J4 con los 20 comandos guionados.

**Entregable:** "cerebro, abrime esta pestaña" funciona de punta a punta.

### 4.3 Fase 3 — Los ojos
1. `cognia/pantalla/captura.py` + `cambios.py` + `memoria_visual.py`. Gate J5.
2. `cognia/vision/vlm.py` con Qwen3-VL bajo demanda. Gate J6.
3. `cognia/vision/terminal.py` para mostrar imágenes en el CLI, tras resolver D3.
4. Integrar la memoria visual con la memoria episódica que Cognia ya tiene.

**Entregable:** "cerebro, ¿qué estoy viendo?" y "cerebro, ¿qué hice hace una hora?".

### 4.4 Fase 4 — El último recurso
1. `cognia/control/raton.py` con PyAutoGUI, siempre detrás de confirmación.
2. Solo si J4 mostró casos que las capas 1 y 2 no cubren.

---

## 5. Riesgos e incógnitas declaradas

1. **D1 — Español en el wake word.** openWakeWord entrena con TTS sintético; que funcione
   bien con una palabra española y la voz real del dueño está por verse. "Cerebro" tiene
   tres sílabas y es razonablemente distintiva, pero aparece en conversación normal: ojo
   con los falsos positivos. Alternativa si molesta: una palabra compuesta ("oye cerebro").
2. **D2 — VRAM.** El 7B ya ocupa 6.3 GB medidos. STT y VLM no entran juntos. El plan
   depende de que el swap sea aceptable; si no lo es, hay que degradar algo. Gate J2.
3. **D3 — Imágenes en la terminal.** No se pudo verificar qué protocolo gráfico soporta
   Windows Terminal en 2026. Es el punto más flojo de esta investigación. Probar a mano
   sixel y el protocolo de kitty antes de diseñar nada encima.
4. **D4 — DXcam mantenido.** Existe BetterCam como fork **[S]**; verificar cuál está vivo
   antes de casarse con uno.
5. **D5 — Fuentes secundarias.** Buena parte de los números de esta investigación viene de
   blogs y comparativas, no de mediciones propias. Ninguno vale hasta reproducirlo en esta
   máquina bajo los gates de la sección 3.
6. **D6 — Alcance.** Esto es un proyecto grande, comparable en tamaño al BDraft. Compite
   por el mismo hardware: mientras se entrena el BDraft, la GPU no está para Whisper ni
   para el VLM. Conviene decidir el orden explícitamente en vez de intentar todo a la vez.

---

## 6. Nota de método: qué produjo esta investigación

Esta investigación se hizo **sin** los workflows multi-agente de Claude: se lanzaron y
fallaron enteros por límite de sesión (8 de 8 agentes). Lo que hay acá salió de búsqueda
web propia con verificación directa de los repos.

Se corrió también **Cognia** sobre la misma pregunta, según la norma de evaluar el producto
con trabajo real. **Resultado honesto: falló.** `investigador.buscar_duckduckgo` devolvió
`None` en las tres consultas (búsqueda web rota o bloqueada), Wikipedia devolvió el artículo
genérico "Asistente virtual" sin relación con la pregunta, y la síntesis final —con
`investigado: False`, o sea sin fuentes— **alucinó una API que no existe**: propuso
`from pynput import microphone`, y `pynput` no tiene módulo de micrófono.

Contraste con la medición anterior (auditoría de código): ahí Cognia acertó el diagnóstico
en 13 segundos. La diferencia es que en aquel caso se le dio el material y solo tenía que
razonar; acá tenía que buscarlo. **Cognia razona bien sobre material dado y no sabe
investigar.** Arreglar `buscar_duckduckgo` es el ítem número uno para que Cognia pueda
reemplazar a los workflows en tareas de investigación, seguido de anclar la respuesta a las
fuentes recuperadas para que no invente APIs cuando no encuentra nada.

---

## 7. Fuentes

**Abiertas y leídas [V]:**
- https://github.com/isair/jarvis — el asistente más maduro; licencia no comercial
- https://github.com/PanPenek/JarvisAi — 1 estrella, 3 commits; solo referencia de arquitectura

**Vistas solo en resultados de búsqueda [S] (no citar como leídas):**
- https://github.com/bytedance/ui-tars-desktop y https://github.com/microsoft/omniparser
- https://github.com/ra1nty/DXcam y https://github.com/Justanormalpaster/BetterCam
- https://openwakeword.com/ · https://livekit.com/blog/livekit-wakeword
- https://picovoice.ai/products/voice/wake-word/ (costo) · https://picovoice.ai/docs/porcupine/
- https://www.scenedetect.com/docs/latest/api/detectors.html (HashDetector)
- https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks
- https://localaimaster.com/blog/best-local-tts-models · https://ollama.com/library/qwen3-vl
- https://unsloth.ai/docs/models/tutorials/qwen3-how-to-run-and-fine-tune/qwen3-vl-how-to-run-and-fine-tune
