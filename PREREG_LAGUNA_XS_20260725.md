# PRE-REGISTRO — Gate de Laguna XS 2.1

**Escrito el 2026-07-25 ANTES de correr una sola generación con Laguna.**
Existe para que el criterio no se elija después de ver el resultado.

## Qué se prueba

Laguna XS 2.1 (Poolside, 33B total / 3B activados por token, MoE, Q4_K_M = 20 GB)
como constructor web, contra los modelos que ya están en la flota.

Es el único movimiento disponible que ataca la **razón 5.2** del informe — "el
conocimiento vive en los pesos, el ruteo no lo fabrica" — porque mete 33B de
conocimiento paramétrico donde hoy hay 8B-20B.

## Cómo se sirve, y por qué no por llama.cpp

`llama-server` instalado: **b10066**, sin la cadena `laguna` en sus binarios.
La página oficial del GGUF exige compilar del PR `ggml-org/llama.cpp#25165`, y
esta máquina no tiene cmake, CUDA Toolkit ni MSVC. Se sirve por **Ollama**
(runtime propio, API OpenAI en `:11434/v1`), decisión del dueño el 2026-07-25.

Consecuencia aceptada: Ollama es un segundo backend, justo lo que la Fase A
eliminó. Mitigación: la auditoría de `cognia/backend_activo.py` nombra modelo y
puerto en cada petición, así que no puede volver a ser silencioso. Y es
**medición, no producción**.

## Condiciones

- Mismas 6 tareas y **los mismos contratos pre-escritos** de
  `scripts/b1_tareas.json` (escritos antes de que existiera ningún código).
- Mismo camino de generación (`generator._call_llm` con
  `COGNIA_CONSTRUCTOR_URL`), mismo juez ejecutable.
- **n = 3** por tarea. `aprobado` = mayoría de las 3.
- La flota se **para** antes: Laguna necesita ~20 GB y llama-server tiene los
  16 GB de VRAM tomados.

## Comparación (ya medida, misma metodología)

| modelo | resultado |
|---|---|
| gpt-oss-20b | **6/6** |
| qwen2.5-coder-14b | 3/6 |
| UIGEN-X-8B | 3/6 |
| OpenReasoning-Nemotron-14B | 1/6 |

## CRITERIO — decidido AHORA

**PASA** si cumple las dos:
1. **≥ 5/6 tareas** (iguala o supera a gpt-oss-20b dentro del margen de n=3).
2. **Latencia mediana por tarea ≤ 180 s.** Es el techo que ya se toleró de
   OpenReasoning-14B (202 s fue su peor caso). Por encima, no cabe en un lazo
   que hace 1-3 rondas de reparación.

**KILL** si cualquiera:
1. **≤ 3/6** — no supera a lo que ya hay servido, y cuesta 20 GB de RAM y un
   segundo backend.
2. **No carga**, o decodifica a **< 2 tok/s** (con 31 GB de RAM y 20 GB de
   modelo, el riesgo real es el swap a disco: es lo que mató a
   `colibri-glm52-descartado`).

**ZONA GRIS (4/6):** no se adopta con esta evidencia. Se repite con n=6 antes de
decidir, según la regla de `gate-e2e-flaky`.

## Qué NO prueba este gate

- No mide Laguna como **agente** ni en tareas largas, que es para lo que
  Poolside lo entrenó. Mide construcción web de un solo turno, que es el cuello
  medido de ESTE proyecto.
- No mide calidad estética. El juez ejecuta, no mira.
- n=3 sigue por debajo del n≥6 que pide la regla del repo. Un resultado en la
  zona gris no es concluyente y está declarado como tal arriba.

## Resultado (2026-07-25, nada de lo de arriba se tocó)

### Números

| modelo | tareas (mayoría de n=3) |
|---|---|
| **gpt-oss-20b** | **6/6** |
| Laguna XS 2.1 (33B) — corrida bruta | 4/6 |
| Laguna XS 2.1 (33B) — tras re-correr las muestras que murieron por plomería | **5/6** |
| qwen2.5-coder-14b | 4/6 |
| UIGEN-X-8B | 3/6 |
| OpenReasoning-Nemotron-14B | 1/6 |

Latencia de Laguna: 30-57 s por tarea. **Muy por debajo** del techo de 180 s.
Carga y decodifica sin problema con los expertos en RAM.

### Por qué hay dos números para Laguna, y por qué el corregido es el válido

En la corrida bruta, `semaforo` salió 1/3. Al mirar el detalle —no el
resultado— **2 de esas 3 muestras nunca llegaron a generar**: murieron con
`el modelo no devolvio HTML`, y el aviso ruidoso de la Fase A2 mostró la cadena
completa (`ni constructor, ni backend inyectado, ni llm_local respondieron`).
La única muestra que corrió de verdad, **pasó**.

Se re-corrieron las 3 por el harness real: **2/3, mayoría → PASA**. Eso mueve a
Laguna de 4/6 a 5/6.

Es una exclusión *post-hoc*, y se declara como tal. Lo que la hace legítima:
(a) se excluyen fallos del HARNESS, no del modelo — llamadas directas a Ollama
con la misma idea devuelven HTML válido con fences en 2/2; (b) se re-midió en
vez de inferir; (c) se habría hecho igual en la dirección contraria.

**Confound declarado, no barrido:** el camino de Ollama tiene una tasa de fallo
intermitente de **≈14 % (3 de 21 muestras)**. Dos hipótesis mías sobre su causa
resultaron falsas al medirlas (nombre del modelo; `num_ctx` truncando — ambas
descartadas: las llamadas directas devuelven `done_reason=stop`). Siguiendo el
disyuntor de reparación del repo, se deja **documentado y acotado** en vez de
seguir parcheando a ciegas.

### Veredicto según el criterio escrito

**PASA por la letra** (≥5/6 y latencia ≤180 s). Pero eso NO es la conclusión
útil, y decirlo sin más sería engañoso:

> **Laguna XS 2.1 (33B) no supera a gpt-oss-20b (20B): 5/6 contra 6/6.**
> 13B extra de parámetros, 20 GB de RAM y un segundo backend **no compraron
> nada medible** en este banco.

### La razón por la que este gate NO decide nada

**El banco está saturado.** gpt-oss-20b hace 6/6: no hay cabecera donde ver
diferencias arriba. Un modelo que ya toca el techo no puede mostrar cuánto le
sobra, y uno que queda a una tarea no puede distinguirse del ruido con n=3.

Es exactamente el mismo error que invalidó el «+0» del router oráculo, y lo
cometí dos veces en la misma sesión.

**El gate se repite sobre `scripts/b1_tareas_duras.json`** (8 tareas
composicionales, no saturadas). Hasta ese número, la pregunta *"¿compra algo
tener 33B en los pesos?"* sigue **sin responder**.

### Lo que sí queda establecido

1. Laguna XS 2.1 **corre en esta máquina** con soltura: 30-57 s por tarea, con
   los expertos en RAM y 16 GB de VRAM. La duda de `laguna-xs-candidato.md`
   («no medido en esta GPU») queda resuelta: **cabe y funciona**.
2. La nota de memoria decía que llama.cpp lo soportaba con «soporte maduro».
   **Falso**: b10066 no lo reconoce; hizo falta Ollama.
3. Su coste operativo real es alto: obliga a **parar la flota entera** (necesita
   la RAM), o sea que no puede convivir con el constructor ni con el árbitro.
