# Cognia Comercial v1 — Spec (prompt mejorado por Claude a pedido del dueño)

> El dueño pidió: *"mejora tú mismo este prompt para que hagas mejor trabajo"*.
> Esto reescribe el brief de voz (con palabras cortadas) a un spec accionable y
> fija los supuestos. **Si algún supuesto está mal, corregime y ajusto.**

## Objetivo
Entregar la **versión comercial y funcional de Cognia**: instalable con **un solo
comando**, que corre **solo-local con el modelo 3B** (sin orquestación online), con
**todas sus funciones verificadas end-to-end**, cuyas optimizaciones funcionan con
**cualquier modelo**, y que **conserva la capacidad de aprender**.

## Interpretación del brief de voz (palabras resueltas)
| Dijiste (audio) | Interpreto |
|---|---|
| "mejora tú mismo este prompt" | Reescribir el brief a este spec (hecho). |
| "encontrar todas las funciones de cognia" | **Inventario exhaustivo** de features (CLI, tools del agente, memoria, skills, RSI/auto-prompting, imágenes). |
| "10 agentes a chequear end-to-end todas las funciones" | **Verificación E2E multi-agente** de cada función con el modelo real; reporte qué corre / qué no. |
| "el cadáver de imágenes beta" | El **creador/generador de imágenes beta** (tools LCD: escena/render/lápiz, oráculo cero-LLM). |
| "subir el pipi / el clic lanzable" | Publicar a **PyPI** (`cognia-ai`) el **CLI** lanzable. **IRREVERSIBLE → confirmo contigo antes de subir.** |
| "instalable con un solo comando, súper sencilla" | `pip install cognia-ai` (o script de 1 línea) que deja `cognia` listo. |
| "desactivar la orquestación online, solo el modelo 3 billones" | **Default solo-local**: correr únicamente con el **Qwen 3B GGUF** (llama.cpp); desactivar node/coordinator/shards por default. |
| "que las optimizaciones/prompt-systems/ERCI funcionen con otros modelos; hagas pass con otros modelos" | **Model-agnóstico**: verificar que prompt-systems + **RSI**/auto-prompting + few-shot + loop no dependen del 3B; probar con otro(s) modelo(s). |
| "entregar la versión comercializable, funcional, fácil de instalar y que aprenda" | Entregable final: **Cognia comercial que aprende**. |

## Alcance de esta corrida (checkpoints)
1. **Spec** (este archivo). ✔
2. **Inventario** de TODAS las funciones → catálogo estructurado.
3. **Verificación E2E** multi-agente (~10 agentes) de cada función con el 3B real,
   incluido el creador de imágenes beta. Reporte PASA/FALLA por función.
4. **Solo-local**: default sin orquestación online; correr únicamente con el 3B.
5. **Imágenes en el paquete**: incluir las tools LCD (hoy en `cognia_x`, **excluido**
   del paquete) o un puente, para que el `pip install` traiga el creador de imágenes.
6. **Empaquetado 1-comando**: verificar `pip install cognia-ai` limpio + instalación
   súper sencilla; arreglar lo que falle.
7. **Model-agnóstico**: auditar que ninguna optimización hardcodea el 3B; probar
   prompt-systems + RSI con otro(s) modelo(s).
8. **Aprende**: confirmar que RSI/skills/memoria/adaptive_prompt siguen activos en la
   build comercial.
9. **Publicar a PyPI** (bump de versión) — **solo tras tu confirmación** (irreversible).
10. **Cierre**: tests, MANAGER_LOG, memoria, commits+push.

## Supuestos (corregime si alguno está mal)
- **Paquete** = `cognia-ai` en PyPI (ya existe en 3.7.1); publicar = bump (p.ej. 4.0.0).
  **No subo nada a PyPI sin tu OK explícito** (es irreversible).
- **Modelo 3B** = `Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf` vía llama.cpp (el actual).
- **"Otros modelos"** para la prueba model-agnóstica: uso los GGUF que estén
  disponibles localmente / uno chico descargable; si no hay, audito la abstracción y
  lo reporto honesto (descargar modelos grandes en CPU es lento).
- **Desktop/Electron** (`cognia_desktop`) queda fuera de esta corrida (foco = CLI pip).
- **Cero-datos-personales / no romper prod Railway / no gastar dinero** siguen firmes.

## Reality-checks honestos (límites conocidos)
- **E2E model-dependent es serial**: hay UN llama-server local (CPU ~8 tok/s). Las
  funciones que dependen del modelo (chat, /hacer) se verifican en serie; las
  cero-LLM (memoria, skills, imágenes-oráculo, tool-registry, CLI, packaging) sí en
  paralelo. "10 agentes" cubren áreas distintas, no 10 inferencias simultáneas.
- **Model-agnóstico ≠ igual calidad**: un modelo distinto puede seguir el mismo
  andamiaje pero rendir distinto; verifico que CORRE y mido, sin prometer paridad.
