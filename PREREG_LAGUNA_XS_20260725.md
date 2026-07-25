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

## Resultado

_(pendiente — se rellena tras la corrida, sin tocar nada de lo de arriba)_
