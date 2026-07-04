# Pulido de la herramienta AI-nativa de escena — edición total + física + auto-pruebas

**Fecha:** 2026-07-05 · CPU, sin GPU, determinista · Orden del dueño: "que pueda
editar TODO de un modelo, tenga buenas físicas, local y súper optimizado, y que
puedas hacer pruebas TÚ misma evaluando qué tanto se parecen; añade muchas
herramientas y servicios".

## Qué se agregó

### Edición TOTAL (una IA edita todo de la escena vía ACCION)
21 tools en `tools_lcd.py` (6 base + 15 nuevas): `escena_agregar/quitar/duplicar/
mover/rotar/escalar/material/capa/camara/luz/fondo/alinear/distribuir/relacionar/
fisica`, más las 6 base (`crear/editar/consultar/render_aprox/atribuir_fallo/
reejecutar_etapa`). Ya no se edita solo color/xy de un objeto: se agrega/quita/
duplica, se mueve/rota/escala, se cambia material/capa/cámara/luz/fondo, se
alinean/distribuyen grupos, y se relacionan objetos (con la aritmética del
planner, garantizando el oráculo de relación).

### Buenas FÍSICAS (local, determinista, sin GPU) — `physics.py`
`settle()` asienta cualquier escena a un estado plausible: gravedad (los objetos
caen hasta su soporte o el suelo, no flotan), soporte válido (un objeto ancho no
se apoya sobre uno angosto — una mesa cae al suelo y lo chico se apila encima),
colisión horizontal (se empujan aparte por densidad), estabilidad (centro sobre
la base). `physics_report()` es el oráculo cero-LLM (flotando/solapando/
inestables). Determinista (mismo input → mismo output). Tool `escena_fisica`.
Verificado real: escena mal armada (taza flotando, caja hundida, pelotas
solapadas) → `settle` en 2 iteraciones → `plausible=True`.

### Modelo de escena ampliado — `scene.py`
Objetos con identidad única (dos 'cup' distintas), rotación, material; +30
objetos nuevos (botella/laptop/reloj/gato/ventana/estante/...); DENSITY (soportes
pesados) + FLOATING (sol/nube/pájaro no caen) + MATERIALS + sinónimos es/en
(`canonical_name`). Roundtrip JSON compatible con escenas viejas.

### Servicios — `exporters.py`, `history.py`, `templates.py`, `tools_services.py`
Export/import (SVG determinista + JSON), undo/redo (`SceneHistory`, tope 30),
6 plantillas de escena (mesa_servida/cielo/sala/escritorio/naturaleza/pila_cajas).
5 tools: `escena_exportar/importar/deshacer/rehacer/plantilla`.

### AUTO-PRUEBAS ("hacer pruebas TÚ misma y evaluar qué tanto se parecen") — `selfplay.py`
- `similarity(a, b) ∈ [0,1]` cero-LLM determinista: match de objetos por tipo
  canónico (0.40) + IoU medio de cajas (0.35) + color (0.10) + relaciones (0.15).
  Calibrada: idénticas 1.0, taza-corrida 0.88, color-cambiado 0.95, falta-objeto
  0.65, relación-rota 0.68, distinta 0.0.
- `attempt_reproduce(target, desc, agent_fn, run_tool_fn)`: un agente (scripted,
  heurístico, o el 3B real) intenta reconstruir una escena objetivo emitiendo
  ACCIONes; se mide el parecido.

## Resultado medido (auto-prueba e2e con el modelo real, 6 escenas objetivo)

| Agente | Similitud media | Detalle |
|---|---|---|
| **scripted (techo)** | **1.000** | las tools + la métrica cierran el lazo |
| heurístico (solo tipos) | 0.508 | acierta objetos, no el layout |
| **3B REAL** | **0.903** | 0.90/0.90/1.00/0.97/0.65/1.00 por escena |

**El hallazgo (verificación real caza un bug del HARNESS):** en la primera
medición el 3B daba 0.153. La causa NO era el modelo: la métrica matcheaba por
nombre EXACTO, pero el target de "a red cup on a blue table" tiene nombres en
inglés (table/cup) y el 3B naturalmente traduce a español (mesa/taza) →
table≠mesa → similitud 0 aunque la escena estuviera bien armada. Con
`canonical_name` (sinónimos es/en) + acotar el prompt a N objetos exactos, el
3B salta a **0.903**. Lección: medir de verdad (no solo pytest) expone bugs del
propio evaluador; el número honesto es que el 3B reproduce escenas al ~90% con
estas tools.

## Súper optimizado (benchmark, 12 objetos, i3 CPU)
`settle` 1.8 ms · `render` 2.5 ms · `similarity` 0.7 ms por escena. Todo sub-3ms,
determinista, sin GPU. La física corta temprano (2-3 iteraciones típicas).

## Alcance honesto
- La física es 2D axis-aligned de "asentamiento" (estado de reposo plausible),
  no dinámica continua (velocidades/rebotes) — que es lo que una herramienta de
  EDICIÓN necesita, no un motor de juego. No hay concepto de "pared" (objetos
  montados como ventana se colocan por plantilla, no por gravedad).
- undo/redo trackea checkpoints de plantilla/import; una edición suelta posterior
  no se apila (declarado).
- El refinador neuronal fotorrealista sigue FUERA en CPU (el render es aproximado).

## Tests
134 tests LCD+fewshot+simple verdes (35 edit + 28 services + 18 physics/scene-ext
+ 7 selfplay + 46 base/arbiter/tools + fewshot). Eval e2e con números reales.
