# Plan de construcción: HERRAMIENTAS VIRTUALES PARA IAs — LCD + MOM como primera familia

> Adaptación del plan LCD+MOM al contexto de **cognia-x** (laboratorio CPU-first,
> basado en evidencia) con una **visión a futuro** explícita.
>
> **Reencuadre central (orden del dueño 2026-07-05):** el objetivo NO es un
> generador de imágenes para un humano. El objetivo es una **biblioteca de
> herramientas AI-nativas** — piezas que una IA (el agente MoM de Cognia, o
> cualquier modelo local) **invoca, inspecciona, edita y verifica** para producir
> salidas más controlables y correctas de las que puede dar sola. LCD (generación
> por escena estructurada) es la **primera familia concreta** de esas herramientas;
> el patrón que valida se reusa mucho más allá de las imágenes.
>
> **Todo el proceso — investigación, decisiones, mediciones, fallos — queda
> REGISTRADO** (MANAGER_LOG, memoria, RESULTADO.md por pieza), porque el registro
> ES parte del producto: cada herramienta verificada y su evidencia se vuelven un
> activo reusable para la próxima IA.

---

## 0. Qué es una "herramienta AI-nativa" (y por qué no es una herramienta para humanos)

Una herramienta para humanos optimiza una **GUI**: botones, previews, undo visual,
texto explicativo. Una herramienta AI-nativa optimiza el **contrato con un modelo**.
Las cuatro propiedades que la definen (y que el plan original NO tenía porque
asumía un dev humano al volante):

1. **E/S estructurada, no visual.** La interfaz es JSON/dataclass inspeccionable y
   editable por token, no un canvas. El scene graph de LCD (`scene.py`) es el
   ejemplo canónico: un dict de objetos/relaciones/cámara que el modelo lee, razona
   sobre él y modifica con una edición O(1) — no un espacio latente opaco.
2. **Verificable por oráculo ejecutable.** Cada herramienta trae su propio
   verificador determinista (cero-LLM cuando se puede) para que otra IA sepa si la
   salida es correcta sin "juzgar a ojo". Es la lección AG-ARB: verificación por
   etapa con oráculo > crítico-LLM.
3. **Componible en un lazo ReAct.** La herramienta se invoca vía el protocolo
   `ACCION:` del agente (registry de `cognia/agent/tools.py`), con args por `|`, y
   su resultado vuelve como `RESULTADO` que el modelo encadena. Nada de estado
   escondido que solo un humano pueda ver.
4. **Auto-mejorable (HERMES).** La herramienta puede ser generada, reparada y
   versionada por el propio sistema (`tool_synthesis.py`: scan + sandbox + tiers +
   rollback + repair-on-live-failure). Una IA que descubre que le falta una
   herramienta la construye, la verifica y la registra — sin humano.

**Consecuencia de diseño:** cada módulo del pipeline LCD del plan original se
reescribe como **una tool del registry** (o un grupo), con su verificador y su
formato ACCION, para que el agente MoM (y cualquier IA que hable el protocolo) las
use. No construimos "una app de imágenes"; poblamos el **registry de herramientas
AI-nativas** usando LCD como el primer dominio medible.

---

## 1. La decisión que hace todo viable (heredada, reafirmada para cognia-x)

El plan original ya acertó en lo esencial: **no entrenar casi nada; reutilizar
preentrenados; el aporte de investigación se concentra en el árbitro.** En
cognia-x esto se endurece por la restricción de hardware (i3, sin CUDA; la GPU es
Kaggle, intermitente) y por el método del repo (verificación REAL, sin overclaim).

| Etapa LCD | En cognia-x se resuelve con... | Estado hoy |
|-----------|-------------------------------|-----------|
| Planificación (prompt→escena) | El 3B local vía `plan_with_llm` (LayoutGPT-like) | **MEDIDO: 7/8 specs válidas** (`lcd/eval_llm_planner.py`); default de reglas para el número de control sin ruido |
| Geometría | Primitivas procedurales desde el scene graph | **HECHO** (`scene.py` + `renderer.py`) |
| Materiales/Iluminación | Reglas categoría→material; heurística de luz | MVP por reglas; módulo real = Fase 4 |
| Render aproximado | Rasterizador determinista → PNG (+ mapas de control cuando haya refinador) | **HECHO** (`renderer.py`) |
| Refinador neuronal | SD + ControlNet (preentrenado) — **requiere GPU** | FUERA en CPU, declarado; entra si aparece GPU |
| **Árbitro** (el aporte) | **Verificación por etapa (contratos, cero-LLM) > crítico-VLM** | **ESTUDIADO** (AG-ARB, `07_ARBITRO_MEJORA_PAPER.md`): 100% en etapas con oráculo vs 31% LLM |

**Lo nuevo respecto al plan original:** en cognia-x el árbitro NO es un VLM (Claude/
GPT-4V) sino la **cascada de contratos ejecutables** que ya se midió superior donde
hay oráculo. El VLM queda como *fallback* para las etapas sin oráculo determinista
(percepción). Esto baja el costo a ~cero y elimina la dependencia de una API externa
— coherente con "modelo local, barato, para el usuario común".

---

## 2. El catálogo de herramientas AI-nativas (lo que este plan produce)

Cada fila es una **tool registrable** (o un contrato), con su verificador. Este es
el entregable real: no "una imagen", sino estas piezas en el registry, usables por
cualquier IA que hable ACCION.

| Herramienta AI-nativa | Qué hace para la IA | Formato ACCION (borrador) | Verificador (oráculo) |
|----------------------|---------------------|---------------------------|----------------------|
| `escena_crear` | Materializa un scene graph desde una spec/plan | `escena_crear <spec-json o descripcion>` | conteo de objetos + relaciones satisfechas (cero-LLM, ya en `scene.py`) |
| `escena_editar` | Edición selectiva O(1) de un objeto sin tocar el resto | `escena_editar <id> \| <attr>=<valor>` | diff estructural: solo cambió el objeto pedido |
| `escena_consultar` | Inspección estructurada (qué hay, dónde, relaciones) | `escena_consultar <query>` | igualdad contra el estado real |
| `render_aprox` | Escena → PNG + mapas de control (depth/normal/seg) | `render_aprox <scene-id>` | el PNG existe y sus mapas son consistentes con la geometría |
| `refinar_neuronal` | Mapas de control → imagen fotorrealista (SD+ControlNet) | `refinar_neuronal <scene-id>` | **solo con GPU**; FID/LPIPS declarados FUERA en CPU |
| `atribuir_fallo` | Dado un fallo end-to-end, señala la ETAPA culpable | `atribuir_fallo <pipeline-json>` | tasa de atribución vs fallos inyectados (AG-ARB) |
| `reejecutar_etapa` | Re-corre SOLO la etapa culpable, no todo | `reejecutar_etapa <stage> <scene-id>` | el resto del pipeline queda idéntico |

**Patrón transversal (la generalización, §6):** `estructura → verifica por etapa →
re-ejecuta selectivo`. Es EL MISMO patrón que ya usa el agente MoM para código
(`generar_codigo` = BoN+juez por tests ejecutados; `contracts.py` = atribución por
etapa). LCD lo instancia en imágenes; validado ahí, es una **plantilla de
herramienta AI-nativa** reusable en cualquier dominio con etapas y oráculos.

---

## 3. Plan por fases (método cognia-x: CPU-first, medir, sin overclaim)

Se respeta la recomendación del §11 del paper: **empezar con 2 etapas** y expandir
solo si la ganancia se mide. Cada fase cierra con evidencia REAL (no solo pytest) y
su `RESULTADO.md`.

### Fase 0 — Contrato y andamiaje AI-nativo *(HECHO / consolidar)*
- El scene graph ya existe como dataclass/JSON (`scene.py`). **Falta**: registrarlo
  como tools (`escena_crear/editar/consultar`) en el registry para que el agente lo
  invoque vía ACCION, con su verificador enchufado a los reconocedores de oráculo de
  `skill_capture` (para que resolver una tarea con estas tools capture skill).
- **Entregable verificable:** `/hacer "arma una escena con una taza sobre una mesa"`
  dispara `escena_crear`, y el checker cero-LLM confirma objetos+relación.

### Fase 1 — MVP de 2 etapas como tools + su árbitro-contrato *(parcial)*
- `escena_crear` (geometría) + `render_aprox` ya corren. **Nuevo**: envolver la
  atribución de fallo (`atribuir_fallo`) como contrato plan→geometría→render usando
  `contracts.py`, con **fallos inyectados** como ground-truth (mover un objeto,
  borrar uno) y medir la tasa de atribución.
- **Pregunta que decide el proyecto:** ¿la representación estructurada + verificación
  por etapa le da a una IA *control y diagnóstico* que el mapeo directo no da? Ya hay
  evidencia parcial (control 8/8, editabilidad O(1)); esta fase agrega la **atribución
  medida**. Si la atribución colapsa (siempre culpa a la misma etapa), se replantea
  barato aquí — es el riesgo #1.
- **Entregable:** dado un fallo inyectado, `atribuir_fallo` señala la etapa correcta
  con tasa medida, y `reejecutar_etapa` re-corre solo esa.

### Fase 2 — El planificador-LLM como tool de primera clase *(medido, productizar)*
- `plan_with_llm` ya mide 7/8. **Nuevo**: exponerlo como la ruta por defecto de
  `escena_crear` cuando el pedido es lenguaje natural (con el default de reglas como
  fallback/oráculo), aplicando la lección "ejemplo concreto > instrucción abstracta"
  (few-shot de escenas JSON reales, igual que el +62pp de BFCL).
- **Entregable:** texto libre → escena editable, con el 3B haciendo la planificación
  y el checker cero-LLM vigilando el formato.

### Fase 3 — El árbitro AI-nativo completo *(el aporte de investigación)*
- Implementar la cascada de contratos en las 4/6 etapas con oráculo ejecutable
  (plan→geometría→render→edición); VLM solo como fallback para percepción.
- **Registrar la distribución de culpas** como métrica de salud (anti "colapso de
  expertos"), tal como exige el plan original y confirma AG-ARB (más contexto EMPEORA
  al juez chico — hallazgo ya medido).
- **Entregable:** `atribuir_fallo` con tasa de atribución por etapa + histograma de
  culpas, sobre fallos inyectados, todo logueado.

### Fase 4 — Expansión selectiva y refinador *(abierto, gated por GPU/evidencia)*
- Materiales/iluminación como etapas reales; multi-ControlNet; geometría con IA
  (TripoSR) por objeto; **refinador neuronal** (SD+ControlNet) — todo condicionado a
  que aparezca GPU y a que las Fases 1-3 validen la hipótesis.
- Video: estados de escena como keyframes, interpolación de **parámetros** (no
  píxeles) — la apuesta del paper puesta a prueba.

---

## 4. Integración con cognia (lo que lo vuelve AI-nativo de verdad)

- **Registry:** las tools de escena/render/árbitro se registran en
  `cognia/agent/tools.py` (o se sintetizan vía HERMES) → invocables por el agente MoM
  y por cualquier IA que hable ACCION.
- **HERMES:** las variantes (nuevos verificadores, nuevas relaciones espaciales) las
  puede **generar y reparar el propio sistema** (scan+sandbox+tiers). El registro de
  cada tool verificada alimenta la **biblioteca reusable** que el dueño pide.
- **Skills:** resolver una tarea de generación con estas tools + oráculo duro captura
  una skill nivel-2 (procedimiento reusable), vía los reconocedores de oráculo
  pluggables ya construidos (`skill_capture.py`).
- **Modo sencillo:** para el usuario común, `escena_crear` "solo funciona"; el árbitro
  y las tools de introspección viven en modo avanzado.
- **Router por dificultad:** planificación fácil → 3B; escenas complejas o el árbitro
  con muchas etapas → escalar (7B / Fable 5 en la orquestación de esta corrida).

---

## 5. Estrategia de datos (casi cero, heredada)

- **Planificador:** few-shot, cero dataset (7/8 ya medido). Si se afina: pares
  prompt→JSON sintéticos verificados por el checker cero-LLM (auto-etiquetado por
  oráculo — barato y limpio).
- **Refinador:** cero datos (ControlNet ya entrenado).
- **Árbitro:** el dataset ES los **fallos inyectados** (ground-truth de atribución
  que el mundo real no da). Este es el activo de investigación.
- **Registro como dato:** cada corrida (escena, veredicto, culpa, tiempo) se loguea a
  JSONL append-only → el corpus para recalibrar umbrales y para que la próxima IA
  reuse la evidencia.

---

## 6. Visión a futuro (por qué esto trasciende las imágenes)

El patrón `IR estructurada → verificación por etapa → re-ejecución selectiva` es una
**plantilla de herramienta AI-nativa** independiente del dominio:

| Dominio | IR estructurada | Verificador | Ya existe en cognia |
|---------|-----------------|-------------|---------------------|
| Imágenes (LCD) | scene graph | conteo/relación + AG-ARB | `lcd/` + `contracts.py` |
| Código (MoM) | plan/firma/tests | ejecución de tests | `candidates.py` + `contracts.py` |
| Web full-stack | árbol de archivos + rutas + DOM | server real + checker DOM | `bench_design.py` (por extender) |
| Documentos largos | outline/secciones | coherencia por bordes | `/largo` + sidecar |

La biblioteca de tools AI-nativas que salga de LCD es la **prueba de que el patrón se
generaliza**. La meta a largo plazo: un **registry de primitivas AI-nativas** (crear/
editar/consultar una IR; verificar una etapa; atribuir un fallo; re-ejecutar selectivo)
que cualquier modelo local invoque para volverse más controlable y correcto de lo que
su tamaño paramétrico permitiría solo. Eso es "hacer mejores a las IAs con herramientas
que no son para humanos": darle al 3B un andamiaje AI-nativo que cierra la brecha con
modelos 100× más grandes en las tareas donde el cuello es control/verificación, no
capacidad bruta.

---

## 7. Cómputo y costo (realismo cognia-x)

- Fases 0-3 corren en el **i3, CPU, sin GPU** (todo determinista o el 3B local ya
  desplegado). Cero costo marginal, cero API externa.
- Solo la Fase 4 (refinador SD+ControlNet, geometría IA) necesita GPU (16-24GB) →
  Kaggle/alquiler, gated por evidencia previa.
- El árbitro es contratos ejecutables (cero-LLM) + fallback VLM opcional → no depende
  de una API para funcionar.

---

## 8. Riesgos (heredados, aterrizados a cognia-x)

1. **El árbitro colapsa** (culpa siempre a la misma etapa). Mitigación: distribución
   de culpas como métrica desde el día 1 (ya es hallazgo AG-ARB: más contexto lo
   empeora). Es el riesgo #1.
2. **El refinador enmascara las etapas previas** (si SD "arregla" todo, el control es
   ilusorio). Mitigación: medir cuánto cambia la imagen final ante cambios en etapas
   tempranas; si no cambia, el control estructurado no aporta. (Solo aplica en Fase 4.)
3. **Ganancia de control ≠ mejor calidad percibida.** El protocolo mide control y
   editabilidad (lo que LCD reclama), y declara FUERA la calidad perceptual sin GPU —
   sin prometer FID.
4. **Sobre-ingeniería del registry.** Riesgo cognia-x: no abstraer de más. Las tools
   son funciones planas con su verificador; nada de frameworks.

---

## 9. Primeros pasos concretos (esta corrida)

1. Registrar `escena_crear/editar/consultar` como tools ACCION sobre el `scene.py`
   existente, con su checker cero-LLM enchufado a los reconocedores de oráculo.
2. Envolver `atribuir_fallo` como cascada de contratos plan→geometría→render con
   fallos inyectados como ground-truth; medir la tasa de atribución + la distribución
   de culpas.
3. Exponer el planner-LLM (7/8 ya medido) como ruta por defecto de `escena_crear` en
   lenguaje natural, con few-shot concreto.
4. Verificación e2e REAL: `/hacer` sobre una tarea de escena con el modelo de verdad,
   mostrando que las tools se invocan, el oráculo verifica, y (si aplica) se captura la
   skill. Loguear TODO (MANAGER_LOG + JSONL + RESULTADO.md).

Si esos 4 pasos cierran con evidencia, tenemos la **primera familia de herramientas
AI-nativas** verificada y registrada — el núcleo del que crece la biblioteca.

---

## 10. Registro (requisito del dueño: todo queda documentado)

Cada pieza cierra con: entrada en `MANAGER_LOG.md` (append-only), `RESULTADO.md` en su
carpeta con el número real y el alcance honesto, memoria persistente con la lección
durable, y el JSONL de telemetría. **El registro no es burocracia: es el mecanismo por
el que cada herramienta verificada se vuelve un activo reusable para la próxima IA** —
que es, textualmente, el objetivo de esta línea de trabajo.
