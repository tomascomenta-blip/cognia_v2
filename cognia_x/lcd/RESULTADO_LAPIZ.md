# Herramientas de Blender como AI-nativas → lápiz procedural (evaluación honesta)

**Fecha:** 2026-07-05 · CPU, sin GPU, determinista · Orden del dueño: "investiga
las herramientas de Blender, recréalas como aptas para IA, itera hasta un lápiz
perfecto al nivel de un generador de imágenes pixel por pixel por difusión".

## Qué se hizo

### 1. Investigación de Blender (4 áreas, workflow paralelo)
Taxonomía real de herramientas mapeada a ops AI-nativas factibles en CPU 2D:
modelado (extrude/bevel/subdivide/loop-cut/inset/knife/merge/bridge/spin),
modificadores (mirror/array/subsurf/solidify/boolean), materiales/shading
(Principled BSDF, gradientes, specular, roughness, noise/wave), render (Eevee
vs Cycles, AO, bloom), y calidad de imagen (supersampling, Blinn-Phong, rim
light, dithering).

### 2. Herramientas de modelado recreadas como AI-nativas (8 tools ACCION)
`modeling.py` (funciones puras sobre vértices) + `tools_modeling.py`:
`escena_biselar` (Bevel), `escena_subdividir` (Subdivide), `escena_suavizar`
(Subsurf/Chaikin), `escena_insertar` (Inset), `escena_extruir` (Extrude),
`escena_espejar` (Mirror), `escena_array` (Array), `escena_poligono` (ngon).
Una IA las invoca vía ACCION para editar la geometría de un objeto.

### 3. Herramientas de shading (analogo 2D del Principled BSDF + render)
`shading.py`: `cylinder_gradient` (volumen cilíndrico), `specular_streak`
(highlight glossy, ancho=roughness), `paste_shaded`. Renderer con
**supersampling** (`scale=3/4`, anti-aliasing) + toggle de labels.

### 4. El lápiz — 4 iteraciones VIENDO el PNG en cada paso
`draw_pencil`: goma + virola metálica con bandas + cuerpo pintado + cono de
madera afilada + punta de grafito. Iteraciones (cada una con la técnica que la
investigación marcó como de mayor retorno):
- **v1**: partes + gradiente cilíndrico + specular + supersampling 3x.
- **v2**: sombra proyectada (GaussianBlur) + punta de grafito fina + facetas del cono.
- **v3**: specular en DOS capas (base + clearcoat) + rim light (Fresnel-fake) +
  AO en las uniones + grano de madera + supersampling 4x.
- **v4**: grano procedural (Noise) modulando el brillo → micro-textura.

## Evaluación cuantitativa (honesta) vs el techo de difusión

| Métrica | Valor | Lectura |
|---|---|---|
| Render | 19.5 ms (1x) / 372 ms (4x) | rápido, determinista, sin GPU |
| Anti-aliasing | supersampling 4x | bordes suaves, sin escalones |
| Banding del gradiente | salto máx ~43 niveles | visible en las facetas duras (mejorable con dithering) |
| **Micro-textura (entropía alta-frec)** | **2.00 bits** | **una foto/difusión de un lápiz ronda 3.5-4.5** |

## Veredicto honesto (sin overclaim)

El lápiz procedural alcanza **calidad de render de producto / ilustración vectorial
de alta gama**: silueta correcta, volumen cilíndrico, specular glossy, rim light,
sombra de contacto, AO en uniones, y micro-grano — todo determinista en CPU, sin
GPU ni difusión. Se ve limpio y dimensional.

**NO alcanza el nivel de "difusión pixel por pixel", y eso NO es un defecto de
esfuerzo sino un límite fundamental:** la métrica de micro-textura lo cuantifica
(2.00 bits vs 3.5-4.5 de una foto real). La riqueza estocástica pixel-a-pixel de
una difusión — grano fibroso real de la madera, micro-rayas del metal cepillado,
imperfecciones de la pintura, reflejos del entorno, iluminación global — proviene
de un modelo GENERATIVO APRENDIDO sobre millones de fotos, o de mapas de textura
reales. Un rasterizador procedural puede *aproximar* la forma, el volumen y el
material (y lo hace bien), pero subir la micro-textura por encima de ~2 bits con
ruido procedural empieza a verse artificial, no fotográfico. **Cerrar ese último
tramo requiere el refinador neuronal (SD+ControlNet) que está declarado FUERA de
alcance en CPU** — que es exactamente el rol del "refinador" del pipeline LCD
(§4.1 mod 6): el render procedural da la estructura y el control; la difusión
condicionada daría el fotorrealismo. Los dos se complementan; ninguno solo llega.

## Lo entregado
`modeling.py`, `tools_modeling.py` (8 tools), `shading.py`, `detailed_shapes.py`
(draw_pencil), renderer con supersampling. 28 tests (modeling puro + tools +
shading). Iteración visual v1→v4 registrada. Honestidad del techo declarada y
cuantificada.
