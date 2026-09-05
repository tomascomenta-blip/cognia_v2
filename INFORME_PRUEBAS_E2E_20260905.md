# Informe: cómo Cognia prueba su propio producto de punta a punta, qué se añadió en 4.28.0 y qué estrategias quedan

Fecha 2026-09-05. Pedido del dueño: hacer `renderizar` mucho más potente (chequear tras input o acciones que normalmente necesitan un humano, renderizar tras ciertas teclas, mostrar variables antes y después) y, en general, dar al CLI mayor capacidad de probar y evaluar end-to-end su propio producto.

## 1. Lo que ya existía (auditado en código)

| pieza | qué hace | límite que tenía |
|---|---|---|
| `agent/renderizador.py` (`renderizar`) | abre HTML/SVG/MD/JS/CSS/URL en Chromium headless (Playwright) o Edge/Chrome headless, guarda PNG, devuelve errores de consola y un resumen del DOM (título, texto, canvas) | una FOTO estática: sin teclas, sin clics, sin variables; no sabía qué se puede tocar en la página |
| `autoprueba.py` | compila → importa → ARRANCA con guion de stdin derivado de los `input()` + brazo B → sin_stubs; para HTML, `_contrato_web` (3 clics genéricos + teclas de juego, píxeles base vs activo) | el guion de stdin va de golpe y devuelve un solo stdout (no se ve qué contestó a cada tecla); el contrato web es genérico (no sabe qué DEBERÍA pasar) |
| `harness/revision_profunda.py` | antes de entregar: sintaxis → tests que cubren lo tocado → arranca el producto (autoprueba) y devuelve el fallo real al modelo | solo el contrato genérico: sin la prueba específica del producto |
| `harness/lazo_corto.py` | tras escribir, abre la página / importa el módulo en el mismo turno | idem, sin interacción |
| `arbitro.py` + VLM | juicio visual opcional | caro, no determinista |

## 2. Lo que se añadió

1. **Guion interactivo en `renderizar`** (`agent/renderizador_guion.py`, ~430 líneas): 19 operaciones (tecla, teclas, mantener, clic, dobleclic, escribir, tipear, ratón, arrastrar, scroll, espera, esperar, captura, var, js, assert, recargar), medición por acción (cambio de pantalla en fracción de píxeles, variables antes → después, errores de JS nuevos, capturas), asserts de cuatro formas, y el mapa de interacción final. Teclas con alias en castellano. Solo Playwright; sin él se dice exactamente eso.
2. **`ejecutar_guion`** (`agent/ejecucion_guionada.py`): programas de consola con teclado, entrada a entrada, salida segmentada, lector por trozos (los prompts sin salto de línea), timeout con kill del árbol, mismo sentinel que `ejecutar`.
3. **Guion propio persistido** (`<pagina>.guion.txt`) que la revisión profunda corre antes de entregar (`_fase_guion_html`): la prueba que el agente escribió para su producto se vuelve la compuerta de cierre, no el contrato genérico.
4. **Pistas al modelo** en el rol del agente nativo y en la descripción de `renderizar`: cómo probar sin humano y dónde guardar el guion.
5. Puertas: `/renderizar … | guion=…`, `/ejecutar-guion …`, `/ayuda` actualizada; ambas tecleadas en el REPL real (salida en `MANAGER_LOG.md`).

## 3. Evidencia

- 22 tests nuevos en verde: parser (sin navegador), Playwright real (canvas que escucha teclado: `window.score 0 → 3`, `player.x 20 → 140`, pantalla CAMBIO 0,3 %; clic que cambia el DOM; `fill` en un input; `Escape` provoca `console.error` y `assert sin errores` FALLA como debe), consola real (menú por `input()`: `>>> entrada: '5'` → `resultado: 9`), tool por `run_tool`, sentinel, revisión con guion que pasa y que falla.
- Tecleado en el REPL: `/renderizar scratchpad/repl_e2e/juego.html | vars=window.score,window.player.x | guion=tecla derecha*3; captura tras3; clic #boton; assert texto contiene "pulsado"; assert window.score == 3` → `asserts: 2/2 OK`, mapa con `canvas #c; button #boton 'Pulsar'`; `/ejecutar-guion … calc.py | entradas=1|4|5|q` → `resultado: 9 · rc=0`.
- Tarea real con el modelo (Qwen3.8-27B, `cognia hacer`, 326 s, ok=True): pedido un juego `esquiva.html` probado sin humano. El agente corrió `renderizar` con guion dos veces, guardó `esquiva.html.guion.txt` (7 pasos: tres `tecla ArrowRight`, `captura`, `assert window.puntos === 3`, `clic #reiniciar`, `assert window.puntos === 0`) y el log de la prueba; `window.puntos: 0 -> 1 -> 2 -> 3 -> 0`, `asserts: 2/2 OK`. La revisión profunda corrió ese guion al cerrar y ahora lo dice en su línea: `guion propio OK (7 pasos, esquiva.html.guion.txt)`.

## 4. Estrategias para seguir mejorando la auto-evaluación (ordenadas por valor/coste)

1. **Guion propio como contrato de cierre para TODO producto** (hecho para HTML). Extender a consola: `<script>.py.guion.txt` con `entradas` + patrones esperados por segmento (`espera: "resultado: 9"`), corrido por la revisión profunda con `ejecucion_guionada`. Coste bajo.
2. **Oráculo de regresión grabado**: `renderizar … | grabar=1` guarda junto al guion los valores finales de `vars` y la firma de la captura; la siguiente ejecución compara y dice qué cambió. Convierte cada producto en su propio banco. Coste bajo.
3. **Mapa de interacción → guion automático**: cuando no hay guion propio, generar uno determinista a partir del mapa (clic en cada control visible, teclas del esquema detectado) y reportar qué controles no hacen nada. Sustituye al contrato genérico de 3 clics. Coste medio.
4. **Cobertura de eventos**: instrumentar la página (`js` de arranque) para contar handlers registrados vs disparados durante el guion; "3 de 5 handlers nunca se ejecutaron" es una métrica de prueba honesta. Coste medio.
5. **Red y estado**: capturar requests fallidas (404/500) y `localStorage`/`sessionStorage` antes/después, como ya se hace con `vars`. Coste bajo.
6. **Servidor local automático**: si el producto es una app con backend (Flask/FastAPI), arrancarla con `ejecutar_fondo`, esperar el puerto y correr el guion contra `http://localhost:PUERTO`; hoy el agente tiene que hacerlo a mano. Coste medio.
7. **Juez visual solo como desempate**: el VLM del árbitro entra únicamente cuando el guion no puede decidir (canvas sin variables expuestas). Mantener la regla "el juez ejecuta, no opina".
8. **Métrica del banco**: en `banco_largo/` añadir a las 25 tareas la puntuación "el agente probó su producto sin humano" (guion presente y en verde) para medir si las pistas del rol cambian el comportamiento del modelo (n≥6, brazos intercalados).

## 5. Límites declarados

- El guion necesita Playwright; el backend Edge/Chrome del sistema sigue siendo solo captura.
- `mantener` (keydown largo) depende de que el juego lea `keydown`/`keyup` y no solo `keypress`.
- `ejecutar_guion` decide que el programa "espera teclado" por silencio (`pausa` ms): un programa que imprime en bucle sin leer nunca recibe la entrada al vencer `espera_max_ms` (5 s) y se dice como TIMEOUT.
- La revisión profunda corre el guion propio solo para HTML (la extensión a consola es la estrategia 1).
