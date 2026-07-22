# Plan — Construcción con imágenes/assets generados (juegos/web) + flota de micro-expertos

> Goal del dueño (2026-07-22, remote): que Cognia construya juegos/webs con **assets de imagen
> transparentes generados** (no "cuadrados CSS"), con una **flota de micro-expertos** que sirvan al
> cerebro grande, y un **motor de animación 2D por keyframes/capas**. Generación de imagen **en GPU**
> (RTX 5060 Ti 16GB); el resto sigue la filosofía del repo. Basado en 4 investigaciones verificadas
> (2026-07-22) + mapeo del código real. Este doc es el norte; cada fase cierra con verificación real.

## Principio rector aterrizado en lo que YA existe (evolucionar, no duplicar)
- Imágenes: `cognia/lcd/` es render procedural PIL (CPU), **sin difusión**. `renderer.render()` es el sink
  de píxeles; el refinador por difusión está declarado como hueco. → la difusión entra como subsistema
  GPU nuevo, aparte, y LCD queda como el motor determinista/vectorial complementario.
- Micro-expertos: `cognia/colonia/` (motor numpy) + `cognia/microexpertos/` (clasificadores byte-level
  ~0.8M) — **son clasificadores, no generativos ni LoRAs**. Sirven de *routers* (elegir estilo/experto),
  NO de expertos de lenguaje.
- LoRA fleet: **ya existe** `cognia/agent/fleet_router.py` + `node/fleet_registry.py` (elige adapter por
  reglas; hoy 1 experto "accion"/tool-calling) → base del experto de tooling.
- Infra LoRA de entrenamiento: `expert_forge/` (peft), `cognia_v3/training/` + `cognia_x/construccion/`
  (QLoRA kaggle/unsloth), `coordinator/federated_store.py` (FedAvg-LoRA). Madura.
- Juegos/web: `cognia/program_creator/generator.py:_build_prompt_web` genera UN index.html autocontenido,
  **prohíbe recursos externos** (solo SVG inline). Aquí se inyectan los assets (hueco: no hay puente).
- Animación: solo `cognia/lcd/animation.py` (GIF de física hardcodeado). Área más verde.

## Aclaración de escala (importante)
"1 millón de parámetros por experto" no aplica a roles de lenguaje. La arquitectura correcta y barata es
**1 base MiniCPM5-1B (Apache-2.0, arq. Llama) congelado + N LoRAs de decenas de MB intercambiables en
caliente** (vLLM multi-LoRA / PEFT hot-swap). El "1M" cabe como *micro-clasificador router* (estilo
idea_router), no como el experto que escribe. Esto ES el superorganismo del dueño, barato en VRAM.

---

## Subsistema A — Generación de assets transparentes (GPU)

**Método núcleo: LayerDiffuse** (lllyasviel, arXiv 2402.17113) — genera PNG **RGBA nativo** (transparencia
latente), incl. semitransparencias (vidrio/glow/pelo) que un recorte no logra. Implementación diffusers
**`rootonchair/diffuser_layerdiffuse` (MIT)** → encaja con orquestar en Python sin ComfyUI.

- **Base:** SDXL 1.0 base (fp16) + `layer_xl_transparent_attn` (LoRA rank-256, 709MB) + VAE transparente.
  VRAM ~8–12GB → holgado en 16GB. Dimensiones múltiplo de 64.
- **TRAMPA (issue #124):** LayerDiffuse SDXL solo va sobre SDXL base / realistas suaves. Sobre finetunes
  desviados (Pony/NoobAI/Illustrious) **rompe** (fondo sólido). → **router de estilo**:
  - estilo compatible con SDXL base → LayerDiffuse nativo.
  - estilo exige finetune incompatible → **generar sobre fondo neutro + BiRefNet** (recorte SOTA, abierto).
- **LoRAs de estilo** (verificados): pixel art `nerijs/pixel-art-xl` (SDXL, sin trigger, ×8 nearest-neighbor);
  "normal"/assets: Game Icon (Civitai 141066), Flux flat game assets (1039062); **Plants vs Zombies**:
  `Civitai 175527` (SDXL, triggers `pvz, cartoon` → compatible con transparencia nativa) — ¡existe!
- **Consistencia** (sprite sets): seed fija + LoRA de familia + ControlNet(OpenPose/Depth) + IPAdapter.
- **Prompt del experto de imágenes:** el micro-experto de imágenes escribe el prompt detallado
  ("objeto aislado, centrado, fondo neutro plano, sin sombra", negativos anti-escena).

## Subsistema B — Flota de micro-expertos (MiniCPM5-1B + LoRAs por rol)
Base residente ligero **MiniCPM5-1B** (Apache-2.0). Servido vía vLLM multi-LoRA (o PEFT hot-swap para
prototipo). Router por rol emitido por el cerebro 14B (o por `fleet_router` existente). Roles:
1. **Tooling/workflows** — parte de `openbmb/MiniCPM4-MCP` (ya bate a GPT-4o en tool-calling) o adapter
   community sobre MiniCPM5-1B; entrenar con xLAM/Glaive si se quiere propio. Cablea a `fleet_router`.
2. **Imágenes** — LoRA de "escribir prompt de difusión" (datasets `poloclub/diffusiondb` CC0,
   `Gustavosta/Stable-Diffusion-Prompts`) + micro-clasificador "elegir estilo/modelo" (idea_router-like).
3. **Organizador de capas / rig** (ver C).
4. **Animador de capas** (ver C) — nota: el núcleo es determinista, el modelo solo *selecciona*.
Entrenamiento QLoRA de un 1B ≈ 4–6GB VRAM, viable en la 5060 Ti (probado en T4 16GB). Usar Unsloth
(skill oficial OpenBMB). Existe infra de entrenamiento en el repo para reusar.

## Subsistema C — Motor de animación 2D por keyframes/capas
- **Formato de datos:** adoptar el modelo **DragonBones/Spine** (huesos jerárquicos → slots/draw-order →
  attachments PNG; timelines con keyframes `{t, valor, curva Bézier}`; setup pose separada de animaciones
  para *retargeting*). JSON propio estilo DragonBones (documentado, runtime JS abierto = PixiJS).
- **Motor de animación = 100% determinista** (interpolar Bézier, forward kinematics, retargeting, ARAP,
  composición de capas con alfa). **NADA de IA aquí** (coherente con "interpolar es matemática").
- **Rigging automático (lo difícil):** referencia canónica **AnimatedDrawings de Meta (MIT)** — detección
  → pose/joints → segmentación guiada → triangulación → binding ARAP → animación por **retargeting de un
  banco de movimientos BVH**. El "experto que organiza/riggea" = detección+pose (modelo) + malla/binding
  (determinista). Maduro solo para **humanoides frontales**; objetos/criaturas → human-in-the-loop.
- **Render:** web con **PixiJS** (WebGL, batching) o Canvas 2D para rig rígido simple; mismo asset corre
  en motores 2D (Godot/Phaser) vía runtimes DragonBones.

## Subsistema D — Puente a juegos/web (`program_creator`)
Modificar `_build_prompt_web` (y el pipeline de juegos) para **permitir e inyectar** `<img>`/
`background-image`/sprites transparentes producidos por A, y animaciones de C (JSON + PixiJS embebido),
en vez de prohibir recursos externos. Puente hoy inexistente (hueco claro).

---

## Fases (cada una: verificación real + commit; sin romper lo existente)
- **F0 — Investigación + mapeo** ✅ (este doc + 4 informes + mapa de código).
- **F1 — Backend de imágenes transparentes (GPU)** — nuevo módulo diffusers+SDXL+LayerDiffuse; generar 1
  PNG RGBA real y verificar el canal alfa. Router LayerDiffuse-nativo vs generar+BiRefNet. *En curso.*
- **F2 — LoRAs de estilo + experto de imágenes** — cablear pixel-art / PvZ / game-icon; el micro-experto
  escribe el prompt; producir un set de assets consistente.
- **F3 — Flota MiniCPM: experto de tooling** — MiniCPM5-1B + adapter MCP, servido y enrutado por
  `fleet_router`; el cerebro 14B delega workflows a él.
- **F4 — Puente program_creator** — juegos/web consumen assets (D).
- **F5 — Motor de animación por keyframes** — formato DragonBones-like + motor determinista + runtime
  PixiJS; auto-rig humanoide (AnimatedDrawings) como experto opcional.
- **F6 — Cableado + verificación E2E** — todos los expertos enrutados; un juego/web de demo con assets
  transparentes + una animación por keyframes.

## Restricciones / honestidades
- La difusión y el fine-tune viven en **GPU (venv312gpu)**, deliberadamente fuera de "sin PyTorch en
  nodos" (autorizado por el dueño para imagen/entrenamiento). Los nodos siguen CPU.
- Licencias a auditar antes de uso comercial: FLUX.1-dev (no comercial), RMBG-2.0 (no comercial → usar
  BiRefNet/BEN2), LoRAs de Civitai (permiso variable). LayerDiffuse core y SDXL base: abiertos.
- Auto-rig arbitrario y etiquetado semántico de partes: experimental → human-in-the-loop desde F5.
- Es un build **multi-sesión**. No inflar: pocas piezas excelentes, verificadas, por fase.
