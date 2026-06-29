# 00 — READINESS DE CONSTRUCCIÓN (GO / NO-GO honesto)

> **Veredicto:** **GO CONDICIONADO** a la práctica de construcción. No es un GO limpio: la
> construcción debe **arrancar por una fase de validación (M0)** que cierre los supuestos
> load-bearing que hoy están sin verificar. Documento honesto, anclado en el ledger REAL del
> lab (no en intuición). Fecha: 2026-06-28. Estado del lab al decidir: **CYCLE 155**.

---

## 1. La pregunta

El dueño pidió: *"continúa trabajando en cognia-x hasta que creas que podamos iniciar la
práctica de construcción; cuando creas que podamos, crea todos los planos a nivel experto,
detallados, honestos y con bases sólidas para construir."*

La decisión de **cuándo** está delegada al laboratorio. Este documento la toma y la justifica.

---

## 2. Criterios de readiness (definidos ANTES de mirar el veredicto)

Para declarar "listos para construir" exijo 5 criterios. Marco cada uno con evidencia REAL.

| # | Criterio | Estado | Evidencia |
|---|---|---|---|
| C1 | **La ciencia de fondo dejó de pagar por ciclo** (la investigación toy está saturada) | ✅ CUMPLE | STATUS_RVALOR §4: el toy lineal del keystone está SATURADO; 6 MIXTA seguidos (141-146) + arco downstream CERRADO (149-155). El lab mismo lo declara. Más ciclos en esta vena rinden poco. |
| C2 | **Los subsistemas centrales están demostrados en pequeño** (no de cero) | ✅ CUMPLE | Verificador real-chequeable (exp018, CYCLE 31/51-55), lazo de auto-mejora STaR robusto (CYCLE 48-50, base débil 0.30→0.78), política de coordinación no-regret (CYCLE 43), auto-evaluación+abstención (CYCLE 46), engine de hipótesis en código (CYCLE 22), router de meta-razonamiento (CYCLE 12-21). |
| C3 | **Las decisiones de arquitectura tienen evidencia** (alta confianza en dirección) | ✅ CUMPLE (dirección) / ⚠️ media (constantes) | architecture.md §1-7 con exp001-007 propios + literatura. Backbone híbrido, vocab moderado, Q4 base, triple-capa de aprendizaje continuo, FedEx-LoRA — todos fundados. **Caveat:** confianza MEDIA en las constantes de **ARQUITECTURA/MODELO** (ratio, ventana W, vocab, e\*, τ, %mix, TTFT — no medidas end-to-end). Las de **RUNTIME de inferencia** (tok/s, threads=3, Q4_K_M vs Q4_0, pin b9391) SÍ están medidas en el i3 (plano 07, confianza alta). |
| C4 | **El sustrato corre de verdad** (no es papel) | ✅ CUMPLE | v0 HybridLM verificado hoy: 1.56M params, ratio 3:1, forward+features+generate OK, entrena (loss 5.56→2.03 en 30 pasos). Tooling: llama.cpp b9391 + 6 GGUF + venv312 + sandbox_tester presentes. |
| C5 | **Los frentes que faltan REQUIEREN construir/escalar, no más toy** | ✅ CUMPLE | Los 3 frentes que moverían la aguja (STATUS §4): (a) valor aprendido en sistema REAL, (b) salir del oráculo con potencia —parcialmente hecho, deflacionario—, (c) SCALE (GPU). Dos son "constrúyelo"; uno es "consigue GPU". Ninguno es "más experimentos toy". |

**4.5 / 5 criterios cumplen.** El medio-cumplimiento de C3 (constantes sin medir) es lo que
convierte el GO en **condicionado**, no en NO-GO: las constantes se validan **construyendo** (M0),
no con más ciclos toy.

---

## 3. Veredicto

> **GO CONDICIONADO.** El laboratorio alcanzó el punto de inflexión donde el progreso real exige
> **construir y medir el sistema real**, no acumular ciclos en un toy saturado. La construcción
> es ahora el experimento de mayor valor. PERO debe **empezar por una fase de validación (M0)**
> que cierre los supuestos load-bearing antes de comprometer la arquitectura completa.

Por qué GO (no "seguir investigando"): el lab documentó explícitamente la saturación. Insistir en
el toy iría **contra la conclusión del propio lab** y rendiría poco. La frontera viva es física
(construir/escalar), no conceptual.

Por qué CONDICIONADO (no GO limpio): hay supuestos sin verificar que, si fallan, cambian la
arquitectura v1. Es deshonesto comprometer el backbone híbrido sin medir primero su viabilidad CPU.

---

## 4. Condiciones duras — los gates de validación (M0 del plan de build)

Estos NO son "más investigación": son la **primera fase de la construcción** (spikes de validación).
El plano `11_plan_maestro_build.md` los instancia como Milestone 0.

### G1 — A-018 (RIESGO P0): ¿el ahorro de banda de SSM/SWA se materializa con kernels CPU reales?
- **Por qué load-bearing:** TODA la viabilidad CPU-first del backbone híbrido asume que los kernels
  de llama.cpp entregan el ahorro de banda teórico. Precedente de que puede fallar: **exp007 midió
  que int8 naïve es 8-10× MÁS LENTO sin kernels especializados** (el ahorro de bytes no se
  materializa solo). El mismo patrón puede aplicar a SSM/SWA.
- **Cómo cerrarlo:** A/B "SWA vs atención full" en GGUF real, midiendo tok/s(L) + RAM de KV en el i3.
- **Bloqueo honesto:** los 6 GGUF locales son **Qwen2.5 = atención FULL**; falta un GGUF SWA-nativo
  (Gemma-2/3, Mistral-SWA, Phi-3). El binario y el resto del tooling NO faltan. → M0 baja un GGUF SWA
  y corre el A/B, O declara el fallback.
- **Rama de fallback (ya prevista en architecture.md):** si A-018 NO se sostiene en CPU, la v1 usa
  el **conservador**: Transformer denso pequeño GQA + KV-cache cuantizado 4-bit (maduro en llama.cpp
  HOY). El plano de backbone documenta AMBAS ramas; la construcción no se bloquea por A-018.

### G2 — Fragilidad de recall del híbrido a carga alta (C-01 residual / H-HYB-3)
- **Qué:** exp014/exp015 mostraron que el híbrido *naive interleaved* NO recupera recall robustamente
  a d chico / np alto (platea ~0.18); solo la atención pura cruza (0.88-0.95). La "resolución" de la
  contradicción eficiencia↔recall es **condicional**, no general.
- **Implicación de build:** el ratio atención:lineal y el *arreglo* (lineal-primero vs atención-primero)
  son decisiones que M0 debe fijar con un barrido a la escala objetivo, no heredar del toy.

### G3 — E4: inyección de hechos nuevos (RAG doc-level vs LoRA vs kNN-LM)
- **Qué:** la decisión de aprendizaje continuo (triple capa) está apoyada en literatura, sin exp propio.
- **Implicación:** M0 corre el A/B barato (RAG/kNN son CPU) para fijar la política de inyección.

---

## 5. Caveats honestos que la construcción NO puede esconder

1. **SCALE = 0%, hardware-bloqueado.** Todo el thesis (arquitectura + R-VALOR) está validado en
   juguete (numpy + HybridLM tiny). La transferencia a escala real es la mayor incógnita, confianza
   MEDIA. El i3 (2c/4t, sin CUDA) NO entrena a escala → **todo entrenamiento grande va a Kaggle GPU**
   (cuenta configurada). El i3 solo hace inferencia (llama.cpp, techo ~8 tok/s 3B Q4) + experimentos.
2. **R-VALOR es una BRÚJULA, no un acelerador.** El arco downstream (149-155) cerró del lado RANKING:
   el residuo del lazo real es discriminación, NO calibración. La tesis 123 (la calibración paga en la
   decisión bajo escasez) sigue **intacta pero NO confirmada en el lazo real** — sólida solo en
   toy/oráculo. El build la usa como heurística decisional acotada, sin sobre-apoyarse en ella.
3. **Las constantes son confianza MEDIA.** Ratios (3:1-4:1), ventana (W~1024), vocab (32-64k),
   umbrales % — citados de literatura, NO medidos end-to-end en el target. M0 + telemetría los fijan.
4. **Docs de gobernanza desfasados ~115 ciclos.** `hypotheses.md`/`assumptions.md`/`contradictions.md`/
   `future_work.md` quedaron congelados ~CYCLE 35-55; el ledger vivo es `research_log.md` +
   `decomposition_tree.md` + STATUS_RVALOR. La construcción se ancla en los vivos. (Tarea de higiene
   en M0: sincronizarlos o marcarlos STALE en cabecera.)
5. **Piezas de la visión PENDIENTES de implementar** (no demostradas ni en pequeño): separación en
   dos núcleos (razonamiento↔comunicación), pizarra/memoria compartida, comunicación-por-necesidad,
   jerarquía de expertos como tal. El build las trata como objetivos de fase tardía, después del
   verificador + lazo (el orden que el Apéndice A demostró que paga).

---

## 6. Qué significa "construir" aquí (alcance honesto)

NO significa "entrenar un GPT-4 en el i3". Significa: **ensamblar el sistema mínimo viable
end-to-end que encarne la arquitectura objetivo sobre lo ya demostrado**, con el orden que el lab
probó que paga (verificador → lazo de auto-mejora → expertos), CPU-first para inferencia + Kaggle
para entrenamiento, validando las constantes a medida que se comprometen. Los planos detallan cada
subsistema, su DoD, sus riesgos y la secuencia de milestones.

---

## 7. Decisión

**Procedo a producir TODOS los planos** (carpeta `cognia_x/construccion/`), a nivel experto,
detallados, honestos y con M0 como gate de validación. La construcción puede empezar por M0 sin
esperar más ciclos de investigación toy.
