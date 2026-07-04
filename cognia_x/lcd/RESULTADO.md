# LCD mínimo — inicio del cambio de algoritmo de generación de imágenes (paper §11)

**Fecha:** 2026-07-04 · **run:** `python -m cognia_x.lcd.eval` · CPU, sin GPU.

## Qué es
El §11 del paper (trabajo futuro) pide como PRIMER paso "una versión mínima de
dos etapas (geometría + refinador) sobre escenas simples, para aislar si la
ganancia de control justifica el costo de coordinación". Esto es ese inicio: el
pipeline **plan → escena estructurada → render aproximado**, que reemplaza el
mapeo directo texto→píxeles por la construcción explícita de una escena (§3
"geometría antes que píxeles").

- `scene.py` — representación estructurada (objetos con posición/tamaño/material
  + relaciones; cámara/luz de primera clase). El núcleo de §5.
- `planner.py` — módulo de planificación (§4.1 mod 1): prompt → escena. Default
  por REGLAS (control exacto, medible sin ruido); hook `plan_with_llm` para usar
  el 3B como planner (el diseño del paper, LayoutGPT-like).
- `renderer.py` — render APROXIMADO determinista (§4.1 mod 5): rasteriza las
  primitivas con sombreado simple a PNG.

## Qué demuestra (las 2 propiedades diferenciadoras medibles en CPU)

**§8.1 Control composicional = 8/8 = 100%.** Para 8 specs (es/en, relaciones
on/left/right/above/below), la escena tiene TODOS los objetos, el conteo
correcto, y la relación satisfecha por las posiciones. Es exacto POR
CONSTRUCCIÓN — justo los modos de falla (objetos faltantes, posiciones
contradictorias) que la literatura documenta como recurrentes en difusión
monolítica (§1, §2.1).

**§8.2 Editabilidad selectiva = sí.** Cambiar el color/posición de UN objeto
(`scene.edit("cup", color="green")`) es O(1) y NO toca el resto ni regenera la
escena — la mesa queda idéntica. Es el diferenciador más claro de LCD: el
espacio latente de un modelo end-to-end no tiene puntos de edición alineados
por objeto. Ver `out/edit_before.png` vs `out/edit_after_green.png`.

## Alcance HONESTO (lo que NO es)
- El **refinador neuronal fotorrealista** (§4.1 mod 6, difusión condicionada por
  el render) queda FUERA DE ALCANCE en CPU sin GPU — declarado. El render de acá
  es la etapa "aproximada" (baja fidelidad), no la final. Por eso el eje que el
  paper mide contra difusión (FID/LPIPS de calidad perceptual) NO se toca; se
  miden control y editabilidad, que son las ganancias que LCD reclama y que este
  esqueleto SÍ entrega.
- El planner es de reglas (gramática acotada); el planner-LLM (§4.1 mod 1) está
  cableado (`plan_with_llm`) pero el default determinista mide el pipeline sin el
  ruido de formato del 3B.
- El **árbitro** (§4.2, credit assignment entre etapas) ya se estudió aparte en
  AG-ARB (`cognia_x/construccion/07_ARBITRO_MEJORA_PAPER.md`): verificación por
  etapa domina al crítico-LLM donde hay oráculo — aplicable a este pipeline
  cuando tenga las 6 etapas.

## Frontera / próximo (orden del paper §11)
1. injertar el refinador (si aparece GPU) sobre el render aproximado.
2. extender a materiales/iluminación como etapas separadas.
3. el árbitro AG-ARB sobre las etapas reales (contratos plan→geometría→render).
