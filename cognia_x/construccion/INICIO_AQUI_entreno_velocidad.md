# INICIO AQUÍ — Briefing para una sesión NUEVA (cero contexto)

> Si sos un Claude Code recién arrancado: **leé este archivo entero primero.** Cristaliza el contexto
> de una sesión previa que superó la ventana de 1M tokens. No re-derives lo que está acá; verificalo
> rápido y construí encima. Repo: `D:\Movido_desde_C\Downloads\cognia\cognia_v2`, rama `cognia-x`.

---

## 1. EL OBJETIVO (lo que el dueño quiere)

**Entrenar la IA del lab (cognia-x) optimizando al MÁXIMO la velocidad de entreno, que sea fácilmente
REENTRENABLE y rápida — y atacar LA RAÍZ del problema "más parámetros = más lento".**

Concretamente:
- Investigar y **escribir posibles soluciones** al "más params = más lento", **evaluarlas de forma
  autónoma** (medir de verdad), e **iterar hasta reducir el costo al máximo**.
- **REGLA DURA:** nunca tomar un "límite" como real hasta haber **probado 10 veces** que es el límite y
  **no un error tuyo**. Ir a la raíz.
- **NO sacrificar inteligencia por velocidad** — mantener calidad↔velocidad en un rango igualado (Pareto).
- Si sobra tiempo, **avanzar la construcción de cognia** (los planos, abajo), **guardando checkpoints
  siempre y documentando todo**.
- **AUTONOMÍA TOTAL:** no detenerse pase lo que pase; tomar la mejor decisión automáticamente. Únicos
  frenos (CLAUDE.md): tocar datos del usuario / romper producción / gastar dinero real / exponer secretos.

---

## 2. QUÉ ES ESTE PROYECTO (1 párrafo)

**cognia-x** es un laboratorio que rediseña una IA desde primeros principios, **CPU-first**, por evidencia
(nada se acepta por autoridad; cada pieza se mide). El modelo propio es **`HybridLM`**
(`cognia_x/model/hybrid.py`, PyTorch): byte-level, mezcla híbrida (mayoría capas de estado fijo/lineal +
minoría atención sliding-window). Tras 155 ciclos de investigación (arco R-VALOR, ver
`research/STATUS_RVALOR.md`) el lab pasó a **fase de construcción**: hay 13 planos expertos en
`cognia_x/construccion/` (ver `00_INDICE.md`). El `venv` del repo está roto → usar **`venv312\Scripts\
python.exe`** (Python 3.12) para todo.

---

## 3. HALLAZGOS CLAVE — NO re-derivar (verificar rápido y usar)

- **G1 MEDIDO (la raíz de "más params=más lento", ya medida en el i3):** el decode en CPU es
  **WEIGHT-READ-BOUND** — el costo dominante por token es **leer los pesos desde RAM** (bytes/token), no
  la atención. Medición real: Gemma-2-2B SWA vs Qwen-3B full, decode cae 8.1→3.7 vs 7.7→2.7 tok/s al
  crecer L; la SWA ahorra MODESTO (retención 0.60 vs 0.52). Detalle: `construccion/M0_G1_RESULTADO.md` +
  datos en `construccion/results_g1/`. **Implicación: el lever #1 de velocidad en CPU es TAMAÑO/
  cuantización del modelo (bytes/token), no el esquema de atención.** Esto es exactamente "más params =
  más lento" medido, y orienta la solución: hay que **desacoplar params de bytes-leídos-por-token**
  (cuantización, sparsity/MoE = leer solo params activos, distilación, RAG).
- **Decisión de backbone:** lean **RAMA B** (Transformer denso GQA + KV-cache 4-bit, maduro) para el v1;
  RAMA A (híbrido SWA+SSM) se justifica por contexto MUY largo/RAM, no por decode a L moderado. Falta
  cerrar con **G2** (¿el híbrido recupera recall a escala?).
- **G2 (recall del híbrido a escala) — SIN cerrar, y reveló el PRIMER objetivo concreto del goal:** se
  relanzó en una T4 (`construccion/m0_g2_recall_colab.py`, data-gen ya vectorizada y verificada correcta)
  pero **el entreno salió MUY LENTO: ~1 paso/seg en la T4, GPU subutilizada** — el config 1/12 (lineal-
  puro, que no hace early-stop) no terminó en 9 min. La sesión se detuvo para liberar la GPU. **Esto ES
  el caso #1 del problema "entreno lento":** ~1 step/s para un modelo de 9.5M en una T4 es ~10-50× más
  lento de lo esperado → casi seguro **GPU ociosa por algún cuello** (sospechas a profilar: data-gen
  numpy en CPU + `.to(device)` por paso; SIN AMP/bf16; SIN `torch.compile`; batch chico=64; el
  `LinearAttention` parallel O(L²) re-crea la máscara `tril` cada forward; eval cada 666 pasos). **Primer
  win del nuevo session: PROFILAR y arreglar esto** (es exactamente "optimizar la velocidad de entreno"
  y aplica la regla 10×: no aceptar "la T4 es así de lenta" sin descartar estos errores propios). Una
  vez rápido, G2 cierra en minutos. Veredicto esperado de G2: si el híbrido necesita atención mayoritaria
  → confirma RAMA B (converge con G1). Smoke local: `m0_g2_recall_colab.py --smoke`.

---

## 4. INFRAESTRUCTURA DE ENTRENO (cómo entrenás de verdad)

- **GPU = Google Colab vía CLI `colab` (google-colab-cli)** — ya instalado y **autenticado** (oauth2,
  cuenta `tomascomenta@gmail.com`). Binario: `C:\Users\Tomanquito\.local\bin\colab.exe`. Comandos:
  - `colab --auth oauth2 new -s NAME --gpu T4` (provisiona; Colab FREE = **1 GPU a la vez**).
  - `colab --auth oauth2 upload -s NAME LOCAL /content/REMOTO` · `exec -s NAME -f SCRIPT.py --timeout N`
    · `download -s NAME /content/REMOTO LOCAL` · `sessions` · `stop -s NAME` · `ls -s NAME /content`.
  - **CRÍTICO:** usá **PowerShell** (no Git Bash) para comandos con rutas `/content/...` — Git Bash las
    mangléa a `C:/Program Files/Git/content/...` y el upload falla.
  - **Patrón headless robusto** (runs >10 min): subir el script + un launcher que lo lanza **desacoplado**
    (`subprocess.Popen(..., start_new_session=True)`, log a `/content/g2.log`) → exec del launcher
    (vuelve rápido) → **pollear** con un checker (`pgrep` + tail del log) → `download` el resultado →
    `stop`. (Hay launcher/checker de ejemplo del run de G2; replicar el patrón.) Detalle:
    `construccion/COLAB_GPU_SETUP.md`.
  - También está el **MCP fork** `colab-proxy-mcp` registrado en Claude Code (modo navegador, interactivo).
- **CPU local:** i3-10110U, 2c/4t, sin CUDA, ~12 GB RAM. Sirve para experimentos chicos + inferencia
  llama.cpp (`node/llama-server.exe`, pin b9391, ~8 tok/s 3B Q4). NO entrena a escala.
- **Kaggle** también disponible (cuenta `anthuananthuan`, token en `~/.kaggle`; pipeline en
  `cognia_v3/training/kaggle/`). Sesiones más largas/predecibles que Colab free para batch.

---

## 5. EL PROBLEMA TÉCNICO RAÍZ + las palancas de DESACOPLE

"Más params = más lento" es físico (más compute + más bytes a mover) PERO la **relación se puede
DESACOPLAR**. Palancas a investigar/implementar/medir (cada una: velocidad Y calidad):
1. **Sparsity / MoE (compute condicional):** tiempo ∝ params ACTIVOS, no totales. La respuesta raíz a
   "escalar params totales sin escalar tiempo".
2. **Cuantización:** tiempo ∝ bytes/param (4-bit, ternario b1.58 — pero ojo: int8 naïve sin kernel fue
   8-10× más LENTO, exp007; la velocidad de baja precisión EXIGE kernels).
3. **Distilación / small-strong:** meter la calidad de un modelo grande en uno chico.
4. **RAG / memoria externa:** sacar los "params de conocimiento" a un índice → el modelo queda chico.
5. **Entreno eficiente:** AMP/bf16, `torch.compile`, flash-attention, gradient checkpointing, optimizador
   fused, **muP** (transferencia de hiperparámetros → no re-tunear al escalar = reentrenable), **LoRA/
   PEFT** (entrenar pocos params = reentrenable y rápido), batch grande + LR scaling, **data-efficiency**
   (menos pasos para converger).
Para "rápido + reentrenable" el combo más directo: **LoRA/adapters + AMP + compile + checkpoints
atómicos reanudables**, sobre un base chico/cuantizado, con MoE/distilación/RAG para la inteligencia.

---

## 6. REGLAS DEL MÉTODO (innegociables)

- **10× antes de aceptar un límite:** si algo parece un muro de velocidad, probá ≥10 variantes/causas y
  descartá error propio (config, medición, deadline, data-gen lenta, GPU ociosa) ANTES de declararlo límite.
- **Calidad↔velocidad MATCHED:** cada optimización mide AMBOS (p.ej. recall acc / loss Y tok-s o
  step-time). No se acepta una optimización que hunda la inteligencia.
- **Verificación REAL** (no solo pytest): medir en hardware, mostrar números. Distinguir PROBADO/ASUMIDO;
  cero overclaims. Es el método del lab.
- **Checkpoints + documentación SIEMPRE.** Logs append-only en `cognia_x/manager/manager_log.md`.
  Commit + push (`origin cognia-x`) cada unidad verificada. Mensajes detallados (qué/por qué/cómo se
  verificó) + línea `Co-Authored-By`.
- **Autonomía total**, mejor decisión automática, no parar — salvo las 4 líneas duras (datos usuario /
  producción / dinero / secretos). Ver CLAUDE.md "Modo Manager Autónomo".

---

## 7. ORDEN DE LECTURA (para profundizar, en este orden)

1. `CLAUDE.md` (raíz) — reglas del repo + método obligatorio.
2. `cognia_x/construccion/00_INDICE.md` → `00_READINESS.md` → `11_plan_maestro_build.md` (qué construir).
3. `cognia_x/construccion/M0_G1_RESULTADO.md` (la raíz "más params=más lento", MEDIDA).
4. `cognia_x/construccion/COLAB_GPU_SETUP.md` (infra de entreno GPU).
5. `cognia_x/manager/manager_log.md` (últimas entradas — bitácora de lo hecho).
6. `cognia_x/research/STATUS_RVALOR.md` (la ciencia del lab, si hace falta contexto profundo).
7. `cognia_x/model/hybrid.py` + `cognia_x/train/recall_task.py` (el modelo + una tarea de eval).

---

## 8. PRIMER PASO SUGERIDO (para arrancar con tracción)

1. Verificá el entorno: `venv312\Scripts\python.exe -c "import torch; print(torch.__version__)"` y
   `colab --auth oauth2 whoami` (debe imprimir tu email = GPU lista).
2. Cerrá G2: buscá/recuperá `g2_recall_results.json` o re-corrélo en T4 (patrón headless del §4).
3. **Caracterizá EMPÍRICAMENTE la curva params↔velocidad**: entrená `HybridLM` a tamaños crecientes en la
   T4 y medí step-time + decode tok/s vs #params. Esa curva medida es "la raíz" — el baseline contra el
   que vas a probar las palancas del §5. (10× rule: confirmá que la pendiente es real y no artefacto de
   GPU ociosa / data-gen lenta / batch chico.)
4. De ahí, andá por las palancas (LoRA + AMP + compile como base rápida-reentrenable; luego MoE/cuant/
   distil para desacoplar), midiendo calidad↔velocidad, con checkpoints + docs + commits.

> Resumen en una línea: **medí la raíz, desacoplá params de bytes/token-y-FLOPs con sparsity+cuant+LoRA+
> distil+RAG, sin hundir la calidad, verificando 10× cada muro, entrenando en la T4 de Colab, con
> checkpoints y docs siempre.**
