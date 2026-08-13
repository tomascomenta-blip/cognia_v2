# PREREG — Herramientas que se ofrecen solas leyendo el razonamiento

**Fecha:** 2026-08-13. **Idea:** del dueño. **Estado:** pre-registrado ANTES de medir.

## La idea

Hoy el modelo descubre herramientas de dos formas: las 12 de `CORE_TOOLS` que se le anuncian, y
`buscar_herramientas` si se le ocurre pedirlo. Las otras ~40 registradas son invisibles salvo que
pregunte.

Pero el modelo es un razonador: emite `reasoning_content` **antes** de actuar, y ese texto dice qué
está intentando. Hoy se descarta entero. La propuesta es leerlo y, cuando mencione algo que una
herramienta no anunciada resuelve, **ofrecérsela** — que la herramienta "levante la mano" en vez de
esperar a que él la busque.

## Por qué puede salir mal (y por eso se mide)

El único A/B duro de este repo dice que **46 herramientas en el catálogo bajan el camino feliz de
4,25/5 a 2,5/5**. Inyectar herramientas de forma proactiva puede reproducir esa degradación por la
puerta de atrás: más nombres en contexto, más distracción. Que la inyección sea "relevante" es una
hipótesis, no un hecho.

## Diseño

- **Brazo A (control):** catálogo CORE, sin inyección. Es lo que corre hoy.
- **Brazo B (proactivo):** CORE + hasta **2** herramientas ofrecidas según el `reasoning_content`,
  anexadas al resultado de la herramienta anterior (el turno `tool`, que es lo último que lee antes
  de volver a decidir).
- **Intercalado** A,B,A,B… para que cualquier deriva del sistema afecte a los dos brazos igual.
- **n = 3 repeticiones × 5 tareas × 2 brazos = 30 corridas.**

### Métricas

| | Qué |
|---|---|
| **Primaria** | tareas resueltas con postcondición verificada en disco |
| Secundaria | pasos hasta cerrar, tokens gastados |
| Mecánica | ¿usó la herramienta ofrecida cuando se le ofreció? |
| **Guardrail** | `e2e_happy_path` no puede bajar de 5/5 (test de NO degradación) |

### El banco

5 tareas cuya solución natural es una herramienta **fuera de CORE** pero que el modelo puede
resolver igual dando un rodeo con `ejecutar`. Así la inyección puede ayudar sin ser imprescindible —
si sólo midiéramos tareas imposibles sin la tool, el resultado estaría cocinado.

## Apuestas firmadas (antes de ver un solo número)

1. **La mecánica funciona**: cuando se le ofrece una herramienta, la usa en ≥50% de los casos.
2. **La primaria NO mejora de forma clara**: el modelo ya resuelve estas tareas con `ejecutar`.
   Espero un empate o una mejora dentro del ruido (±1 tarea).
3. **Sí mejora la secundaria**: menos pasos cuando acepta la oferta.
4. **El guardrail aguanta**: 2 herramientas no son 46; no espero degradación del camino feliz.
5. **Riesgo real que vigilo**: que ofrezca herramientas irrelevantes y le añada ruido — por eso el
   umbral de score y el tope de 2.

**Criterio de KILL:** si la primaria empeora, o si el camino feliz baja de 5/5, la vía se cierra y
queda apagada por defecto con su número escrito.

**Criterio de ADOPCIÓN:** primaria ≥ control Y secundaria mejor Y guardrail intacto.

Si sale empate en todo, se queda opt-in y se dice: implementada, medida, sin efecto demostrado.

---

# RESULTADO — KILL (2026-08-13, mismo día)

```
brazo A (control  ): 11/15 tareas resueltas
brazo B (proactivo):  5/15
neto B-A: -6 tareas
```

| tarea | control | proactivo |
|---|---|---|
| contar | 3/3 | 2/3 |
| py_ok | 3/3 | 2/3 |
| **copiar** | **3/3** | **0/3** |
| arbol | 2/3 | 1/3 |
| json_ok | 0/3 | 0/3 |

**La vía se cierra.** El criterio de KILL pre-registrado era "si la primaria empeora"; empeoró en las
cuatro tareas que discriminan, y en `copiar` de forma total.

## El mecanismo, que es lo que valía la pena aprender

En el log del brazo B aparecen estas dos líneas:

```
[permiso] /mapa-codigo — ejecutar? (s/n) >
[permiso] repo_map proyecto — ejecutar? (s/n) >
```

Ante *"copia origen.txt a respaldo.txt"* —que resuelve con `escribir_archivo` en un paso— el agente
que recibió una oferta **se fue a mapear el repositorio**. La herramienta ofrecida no le dio una
capacidad: le dio una idea, y la idea era mala.

Esto **reproduce el A/B del catálogo** (46 tools bajan el camino feliz de 4,25/5 a 2,5/5) con una
sola herramienta extra, y aporta un matiz que aquel no tenía: el daño no viene del *tamaño* del
catálogo, viene de **meter una opción nueva en el momento en que el modelo ya tenía un plan bueno**.
Sugerir a mitad de tarea es peor que sugerir al principio.

## Las apuestas, contra el resultado

| # | Apuesta | Veredicto |
|---|---|---|
| 1 | La mecánica funciona (usa lo ofrecido) | **Sí, y ese fue el problema** |
| 2 | La primaria no mejora de forma clara | **Acerté, pero corto: empeora mucho** |
| 3 | Mejora la secundaria (menos pasos) | **Falso** — tardó más en casi todas |
| 4 | El guardrail aguanta | sin correr: la primaria ya mató la vía |
| 5 | Riesgo de ofrecer irrelevantes | **Se materializó** |

## Fallo del banco, declarado

`json_ok` dio **0/3 en los dos brazos**: la tarea es demasiado difícil o está mal enunciada, y no
aporta nada al contraste. No lo contamina (afecta igual a ambos), pero reduce el n útil de 15 a 12
por brazo. Con 12, el −6 sigue siendo grande.

## Qué queda

El módulo se conserva **apagado por defecto** (`COGNIA_TOOLS_PROACTIVAS`), con este resultado
escrito al lado. No se borra por dos razones: la mecánica de leer `reasoning_content` funciona y
puede servir para otra cosa (telemetría, elegir qué recordar), y porque una vía muerta con su número
vale más que una vía nunca intentada.

**Lo que NO se debe hacer sin volver a medir:** subir el tope a 2 herramientas, bajar el umbral de
6,5, u ofrecer al inicio de la tarea en vez de a mitad. Esa última es la única variante que a mi
juicio merecería otro experimento.
