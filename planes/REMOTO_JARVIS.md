# Plan — Control remoto "Jarvis": voz 3D, RAG 3D, flujos n8n y pulido

Prompt del dueño reescrito y ordenado en unidades entregables y verificables.
Apagado programado: 21/07/2026 04:30 (tarea `CogniaApagado0430`). Trabajar
lento pero seguro, commitear cada unidad verificada, gastar tokens con cabeza.

## Objetivo
Convertir el control remoto en una consola tipo Jarvis: se escucha a Cognia,
se ve el "cerebro" y los expertos en 3D, la memoria (RAG) es un cilindro 3D
navegable, los flujos se editan estilo n8n, y el chat se lee limpio.

## Bloque A — Base y pulido (rápido, alto valor)
1. **Formato de salida.** Renderizar markdown de Cognia (`**negrita**`, `##`,
   ` ``` bloques ```, `` `inline` ``, listas, enlaces) de forma legible.
   Eliminar los globos: cada respuesta se muestra como UN solo bloque continuo,
   no una burbuja por línea. Los archivos que crea se ven expandibles (ya hay
   base con los bloques de actividad).
2. **Grafo más claro.** Etiquetas legibles (texto real de los conceptos, no
   ids), menos saturación, leyenda de temas; que se entienda de un vistazo.
3. **Oficina isométrica no carga → arreglar.** Diagnosticar el arranque del
   subproceso `cognia.oficina` y el iframe; dejarla cargando de verdad.
4. **Anti-estancamiento.** Reforzar el corte cuando un agente se atasca.
5. **Límite de tokens en GPU ↑.** Subir el tope de salida/contexto en
   `node/llama_backend.py` (n_predict / ctx) dentro de lo que la VRAM aguante.

## Bloque B — Jarvis: visualización de voz 3D
6. **Escena 3D** (fondo negro vibrante): cerebro central verde y más grande;
   alrededor, los expertos y demás modelos, cada uno de un color. Zoom a cada
   uno. Opacados cuando no "hablan"; se encienden al hablar. Al dispararse una
   acción a un experto: esfera de energía (blanco + color del experto) que
   viaja desde el cerebro hasta ese experto.
7. **Voz.** Poder escuchar lo que dice Cognia (TTS del navegador) y a cada
   experto cuando actúa.
8. **Filtro en el chat.** Ver todos (cerebro + expertos), solo cerebro, una
   cantidad, o un experto concreto — cada uno con su color.
9. **Click en Jarvis** despeja el menú a modo minimizado: acciones, workflows,
   grafo, oficina, imágenes, todo en pequeño.

## Bloque C — RAG 3D (memoria)
10. **Cilindro 3D** por pisos = temas, conectados por una línea vertical; cada
    piso con color pastel semitransparente único; los nodos (esferas) en
    colores vívidos. Mover / rotar / zoom, y toggle a vista 2D. Se abre al
    hacer click en Jarvis. Cada experto puede tener su propio grafo sin chocar
    con el sistema actual.

## Bloque D — Flujos estilo n8n
11. Editor visual de nodos, ver/editar/guardar sencillo; a la derecha Cognia
    resume qué hace cada flujo.

## Bloque E — Pruebas E2E
12. Casos fáciles y difíciles de punta a punta; arreglar lo que falle; entregar
    pulido y funcional.

## Orden de ejecución
A(1→5) primero (base sólida y barata), luego B, C, D, y E como cierre.
Cada unidad: implementar → verificar REAL (navegador / CLI) → commit → push.
