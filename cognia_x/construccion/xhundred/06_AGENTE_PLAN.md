# Agente MoM — Plan pre-registrado (programación, diseño, tool-calling)

**Fecha:** 2026-07-03 · **Base:** 4 informes (ingeniería-barata, Hermes, GLM-5.2, árbitro) +
mediciones propias del repo (nada re-derivado) · **Precedente:** flota MoM verificada
(`04_MOM_GROKKING.md` X1–X4, `05_DSPARK_ANALISIS.md` M1), CoT dirigido medido
(`cognia/agent/stepwise.py`), benchmark duro 40% pass@1 (`cognia_v3/eval/benchmark_code.py`) ·
**Estado:** PLAN PRE-REGISTRADO (benchmarks, umbrales y predicciones escritos ANTES de construir).
Las discrepancias entre informes se resuelven acá y quedan anotadas en itálica, estilo
`00_DISENO.md` §4.7. Desvíos posteriores van a `01_DESVIOS.md` append-only.

---

## 1. Auto-interrogación respondida: qué necesitamos y qué tenemos

**La pregunta que ordena todo:** ¿qué le falta a un 3B bien orquestado para actuar "cerca" de un
frontier en los 3 ejes elegidos — y cuánto de eso es andamiaje (config barata) vs capacidad
(imposible sin 4-5 órdenes más de cómputo)? La respuesta honesta de los 4 informes: en
**tool-calling single-turn** y en **tareas cortas con self-repair** la brecha es mayormente
andamiaje (xLAM-2-3b llega a 88.2% AST non-live; GLM-5.2 vs Opus en Terminal-Bench = 4 pts — el
loop domina, no el modelo crudo); en **código duro multi-archivo** (SWE/LiveCodeBench) es
capacidad y NO se promete; en **multi-turn agentic** el techo es bajo para TODOS (GLM-5.2 saca 27%
en tau3-banking — el frontier falla el 73% de las veces).

**Inventario verificado (qué tenemos, con ruta y número):**

| pieza | dónde vive | estado medido |
|---|---|---|
| backend 3B | Qwen2.5-3B Q4_K_M vía llama.cpp (`node/llama-server.exe` pin b9391, threads=3) | ~8 tok/s techo i3, ctx CLI 16k (nativo 32k); 0.5B = 35.9 tok/s (4.3×, exp021) |
| flota MoM | `cognia_x/mom/{fleet,selector,model}.py` + `manifest.json`; pesos en `construccion/xhundred/results_fleet/` | gen + 3 expertos 97.5M; experto gana su nicho 3/3 (Δbpb +0.17/+0.18/+0.30, X3); fuera de nicho se derrumba (+0.9..+3.5) |
| selector calibrado | `cognia_x/mom/selector.py` (temperature M1) | n-grams 96.7% acc, <5 ms; ECE 47.7%→**1.8%** (T=0.05); AUC misroute 0.868; selección pura ≈ oracle en 2/3 dominios (M1) |
| CoT dirigido | `cognia/agent/stepwise.py` + wiring `cli.py` | direct 0.3125 → CoT-por-turno **0.8125** (temp 0); sc-3 y system-CoT descartados con número; NUNCA empujar si el turno pide formato exacto (compliance 0.75→0.25) |
| pipeline QLoRA | `cognia_v3/training/kaggle/{train_qlora_kaggle,run_kaggle_training}.py` | corre en T4; ~2-4M tok de fine-tune por 30 min (00_DISENO §7) |
| tool-use ACCION previo | formato `ACCION: <tool> <args>` (líneas, NO JSON); `cognia/agent/loop.py` (`first_action_block`), `tools.py` (25 tools registradas), fine-tune 0.5B | de-risk +66.7% correct_tool; 13 bugs del agente arreglados (goal-drift, terminación, stop-seq); el fine-tune 3B quedó BLOQUEADO (verificación de teléfono Kaggle) — se declara |
| verificación de código generado | `cognia/agent/tool_synthesis.py` + `cognia/program_creator/sandbox_runner.py` | tools puras `run(args)->str`, scan estático de imports (allowlist) + sandbox subprocess con timeout; solo lo verificado entra al manifest — regla 9 de CLAUDE.md ya implementada |
| benchmark de código propio | `cognia_v3/eval/benchmark_code.py` | pass@1 con ejecución REAL, baseline medido **40%** (3B + fixes timeout/ctx16k) |
| router con verificador | `cognia_x/reason/router.py` (bandit, `mode="verifier"`) | anti-Goodhart medido (CYCLE 12: `mode="confidence"` secuestrado); regret ≈0.006-0.008 en toy con volumen |

**Qué falta (los gaps que este plan construye):** (a) BoN+juez sobre el 3B — no existe;
(b) validador+repair de args de tool-call — el parser actual recorta el primer bloque ACCION
pero no valida ni repara argumentos; (c) contratos I/O entre etapas del pipeline /hacer;
(d) trigger crear-vs-reusar + trust tiers para las tools auto-generadas (hoy tool_synthesis
verifica pero no gobierna ciclo de vida); (e) los 3 benchmarks pre-registrados de §4 con sus
harness; (f) el harness del árbitro (§5).

**Rol honesto de la flota MoM en el agente:** los 97.5M NO son jueces semánticos (bpb 1.0-1.5,
deriva medida — P4 de 04_MOM §7). Sus dos usos v1, ambos medibles: (1) el **selector calibrado**
(ECE 1.8%) como detector de dominio para decidir QUÉ palanca de §2 aplicar (mismo patrón
stepwise: gate barato antes de gastar tokens); (2) **rank por bpb de dominio** como desempate de
candidatos BoN cuando no hay tests ejecutables — HIPÓTESIS pre-registrada, no promesa: predicción
= el rank por tests visibles gana al rank por bpb; el bpb solo desempata donde no hay oráculo. Si
el bpb-rank no supera a random en AG-CP1, se retira sin drama.

---

## 2. Ingeniería-barata NATIVA (catálogo priorizado con evidencia 3B-7B)

Regla de adopción heredada del método: cada palanca entra con evidencia externa EN NUESTRO RANGO
(3B-7B) + verificación en el benchmark propio antes de declararla adoptada. Los aceleradores de
paper no transfieren automáticamente (lección X2: TODOS fallaron contra sus papers).

| # | palanca | evidencia (rango 3B-7B) | entra v1 | por qué |
|---|---|---|---|---|
| 1 | **BoN N=8 + juez-verificador** (código) | Qwen2.5-Coder-3B: 10 candidatos + juez SLM = pass@1 0.361→0.521 (+15.6pp, 2602.11911); CodeRanker +5.1..+13.6pp | **SÍ** | mayor ROI medido del catálogo; jerarquía del juez: tests visibles (oráculo duro) > ranker barato > NUNCA autocrítica ciega |
| 2 | **Tests-como-especificación** (test-first) | +11.2pp MBPP con 1 test en prompt (2311.07599); TDD interactivo +45.7pp en 5 rondas (2404.10100); el cuello es instruction-following, no conocimiento — favorece chicos guiados | **SÍ** | gap de config, no de modelo; cuando la tarea es función/spec clara, generar el test ANTES del código |
| 3 | **Generate-then-structure** (separar pensar de formatear) | forzar JSON/schema durante el razonamiento degrada 10-30% (2604.13006, 2606.09410) | **SÍ** | auditoría hecha: el formato ACCION ya es lineal (no JSON) — ventaja estructural heredada; lo que falta es el paso 2: validador de args + repair con el error del parser (§6) |
| 4 | **Reflexion gated por verificación EXTERNA** | Reflexion 91% HumanEval CON feedback de ejecución real (no autocrítica); Reflect-Retry-Reward: el ciclo paga solo con veredicto de afuera | **SÍ** | ya alineado con el anti-Goodhart propio (CYCLE 12); el ciclo generate→critique→refine se activa SOLO si hay test/traceback real de por medio |
| 5 | **Patrón stepwise extendido** (detector barato de "cuándo aplica" por palanca) | propio, medido: 0.3125→0.8125 con detector regex; 16/16 activan, 4/4 no-razonamiento no | **SÍ** | es el multiplicador de las otras 4: BoN solo si verificable, test-first solo si hay spec, repair solo si hay error real — presupuesto dirigido, no palancas always-on |
| 6 | self-consistency k=3 | propio, medido: 0.6875 a 3× costo < CoT greedy 0.8125 | NO | perdió contra la alternativa más barata en NUESTRO bench — descartada con número |
| 7 | plan-then-execute como técnica aislada | sin evidencia aislada en 3B-7B (los papers evalúan harnesses completos) | NO (v1) | no asumir la ganancia sin medirla; el pipeline por etapas de §5/§6 la mide de rebote |
| 8 | juez LLM global sin verificador duro | literatura 2025-26 + CYCLE 12 propio: colapsa a gaming | NO | prohibido por diseño; solo fallback tras agotar oráculos (§5) |
| 9 | optimización evolutiva de prompts (DSPy/GEPA) | Hermes-self-evolution la usa con gates + PR humano | NO (v1) | cara en cómputo/gobernanza; re-abrir solo si CP4 muestra plateau de las palancas 1-5 |
| 10 | speculative decoding / draft | propio (exp021): draft separado 0.37×, hunde | NO | descartado con número en CPU bandwidth-bound; el lever de velocidad es el TAMAÑO despachado (MoM/cascada) |

*Discrepancia resuelta (dónde vive la ganancia de BoN): el informe ingeniería-barata reporta que
BoN "puro" satura rápido y el juez sostiene la ganancia; nuestro juez v1 es el más barato no-circular
disponible (tests visibles ejecutados en sandbox), NO un ranker aprendido — el ranker fine-tuneado
es v2 condicionado a que CP1 muestre que los tests visibles no alcanzan.*

---

## 3. Auto-herramientas estilo HERMES (principios extraídos, SIN copiar)

Hermes-agent (NousResearch, MIT, 208k stars) valida en producción un ciclo
**crear→validar→registrar→reusar→evolucionar** para capacidades del agente. Extraemos los
principios y los aplicamos sobre la infraestructura PROPIA (tool_synthesis + sandbox_runner +
skills.py) — no se copia código ni formato.

1. **Skill = composición de tools existentes, no código libre.** Hermes crea "skills" que
   envuelven tools ya presentes en un procedimiento (SKILL.md), no sintetiza ejecutables
   arbitrarios. Adoptamos la separación en DOS niveles que ya existe en el repo y se formaliza:
   **nivel-1 tools ejecutables** (puras `run(args)->str`, allowlist de imports + sandbox con
   timeout — `tool_synthesis.py`, regla 9, sin cambios) y **nivel-2 skills procedurales**
   (markdown con frontmatter, `cognia/agent/skills.py` ya lee el formato; el agente puede
   ESCRIBIRLAS: son instrucciones, no código — blast radius cero por construcción).
2. **Gate crear-vs-reusar por metadata.** Antes de sintetizar: buscar por nombre+descripción
   (≤60 chars) en el registry; match parcial → editar la existente, no duplicar. Barato (un dict
   lookup + difflib) y ataca la acumulación de ruido.
3. **Trigger de creación medible.** Tras ≥4 tool-calls exitosos en una tarea cerrada con
   verificación real, o tras resolver un error (traceback→fix), ofrecer persistir el camino como
   skill nivel-2. El umbral 4 se pre-registra y se ajusta con datos de uso, no por intuición.
4. **La brecha que Hermes NO cierra y nosotros SÍ (diferenciador):** Hermes persiste el skill
   porque "la tarea salió bien"; Voyager verifica por ejecución real antes de guardar. Adoptamos
   lo segundo: **nada se registra sin corrida verificada** — nivel-1 ya lo hace (sandbox + output
   esperado); nivel-2 exige que la traza que originó el skill haya cerrado con oráculo duro
   (tests verdes / assert del bench), no con autoevaluación.
5. **Trust tiers + blocklist duro NO evadible.** Tres niveles: `builtin` (las 25 de tools.py) >
   `verified` (generadas, pasaron sandbox + N usos exitosos) > `staged` (generadas, aún sin usos).
   Blocklist de patrones peligrosos (rm -rf, dd a disco, pipe-a-shell de URL, escritura fuera del
   workspace) SIEMPRE activo — explícitamente NO imitamos el diseño de Hermes de saltear el check
   "porque hay contenedor" (su propio issue de diseño): defensa en profundidad, contenedor o no.
   `ejecutar` ya tiene bloqueos y `resolve_write_path` ya confina escrituras al workspace — se
   extiende, no se reinventa.
6. **Carga perezosa por metadata.** Con ctx 16k del 3B, el prompt lleva solo nombre+doc de una
   línea por tool/skill (ya es así: `build_tools_doc()`); el cuerpo del skill se inyecta solo al
   invocarlo. Principio Hermes (~3k tokens de metadata) adaptado a un contexto 60× más chico.
7. **Evolución con gates, sin auto-commit.** Versión semver en el manifest de generated_tools;
   una tool `staged` que falla 2 veces se degrada/retira; ninguna edición de skill a mitad de
   tarea. El equivalente al GEPA de Hermes (mutación+gates) queda fuera de v1 (§2 #9).

*Discrepancia resuelta (aprobación humana): Hermes usa staging con aprobación explícita; nuestro
modo Manager Autónomo no puede depender de un humano en el loop. Resolución: la aprobación humana
se reemplaza por un gate MÁS duro que el de Hermes — verificación por ejecución real (punto 4) +
tiers + blocklist. Lo que Hermes resuelve con gobernanza, nosotros lo resolvemos con oráculos.*

---

## 4. Benchmarks pre-registrados + qué significa "cerca de GLM 5.2"

**Resolución del nombre:** GLM-5.2 existe (Zhipu/Z.ai, MoE ~753B, 2026-06-13, MIT). NO publica
los benchmarks clásicos (HumanEval/MBPP/LiveCodeBench/BFCL) — publica SWE-bench Pro 62.1%,
Terminal-Bench 2.1 81.0%, tau3-banking 27%, AIME 99.2%, GPQA-D 91.2%. Proxies declarados donde
5.2 calla: GLM-4.7 (LiveCodeBench-v6 84.9%, SWE Verified 73.8%) y GLM-4.5 (BFCL v3 76.7%, líder).

**Definición honesta de "cerca":** se define POR EJE y ANTES de correr, con la brecha
andamiaje-vs-capacidad de los informes. "Cerca" NUNCA significa paridad global con un MoE 753B —
significa: en el eje donde el andamiaje domina (tool-calling single-turn, tareas cortas
verificables), quedar a ≥85% del score del GLM de referencia; en el eje donde domina la capacidad
(código duro), se declara NO-cerca y se mide la serie interna. Cualquier claim fuera de estas
definiciones es overclaim y no se hace.

### Eje 1 — Tool-calling: BFCL-v3 slice single-turn

- **Benchmark:** slice congelada de BFCL v3: categorías non-live AST (simple, multiple, parallel,
  parallel-multiple) + live simple — 200 items estratificados, seed fija, checker AST oficial
  (sin ejecución de APIs → corre en CPU pelada). Multi-turn queda FUERA del claim (declarado:
  xLAM-2-3b 55.6%, Qwen3-4B 35.2%, y el frontier mismo saca 27% en tau3 — techo bajo universal).
- **Número GLM:** 76.7% overall BFCL-v3 (GLM-4.5, proxy — 5.2 no publica; se declara la
  asimetría slice-vs-overall: nuestra slice es más fácil que el overall de ellos, por eso el
  umbral se fija sobre el número de ellos SIN descuento).
- **Baseline 3B pelado (predicción congelada):** 45-55% en la slice (Qwen3-4B prompt-based hace
  62% overall con multi-turn hundiéndolo; nuestro 3B es menor y sin fine-tune de FC).
- **Umbral "cerca" PRE-REGISTRADO: ≥65.2% (= 0.85 × 76.7) en la slice** con el agente v1
  (generate-then-structure + validador/repair de args + few-shot ACCION + stepwise-gate).
  Stretch: ≥75% (paridad nominal, alcanzable: xLAM-2-3b-fc-r logra 88.2% AST con fine-tune —
  nuestro tope sin fine-tune debería quedar entre ambos).
- **Presupuesto:** CPU local 4-6 h (nocturno, 200 items × ~2 gen con repair a 8 tok/s);
  T4 ~40 min (3B GGUF offload). Harness: `cognia_v3/eval/bench_bfcl_slice.py` (nuevo).

### Eje 2 — Programación: benchmark duro propio + declaración NO-cerca en LCB/SWE

- **Declaración pre-registrada:** en LiveCodeBench (GLM-4.7: 84.9%) y SWE-bench Pro (GLM-5.2:
  62.1%) NO estamos cerca y no vamos a estarlo con andamiaje — un 3B queda típicamente <10-15%
  ahí; la brecha es de capacidad (4-5 órdenes de cómputo). Se publica la brecha, no se maquilla.
- **Métrica operativa:** `benchmark_code.py` propio (pass@1, ejecución real, greedy) — la misma
  razón por la que Zhipu abandonó HumanEval/MBPP (saturación frontier) nos habilita a usar la
  serie interna como métrica del eje.
- **Baseline medido (no estimado):** 40% pass@1 (3B + fixes timeout/ctx).
- **Umbral v1 PRE-REGISTRADO: ≥55% pass@1** con BoN-8 + juez (tests visibles) + test-first +
  repair-loop gated. Aritmética declarada: +15.6pp medidos en literatura con juez SLM sobre un
  3B coder; nuestro 3B no es coder-tuned → tomamos +15pp como techo y exigimos el piso 55%.
  Stretch: ≥60%. Falsación: si BoN-8+juez da <+8pp, la palanca #1 no transfiere y se reporta.
- **Presupuesto:** CPU 6-8 h nocturno (BoN-8 multiplica generación) o T4 ~35 min; ejecución de
  tests siempre local en sandbox.

### Eje 3 — Diseño (web/UI por spec textual, verificador duro)

- **Benchmark propio congelado ANTES de construir el agente:** 25 specs textuales → página
  HTML/CSS single-file; score = % de asserts DUROS pasados (parser DOM: elementos/atributos
  requeridos; reglas CSS presentes; meta viewport; a11y computable: alt/labels/jerarquía de
  headings; validez sintáctica). CERO juez LLM (anti-Goodhart estructural). Las 25 specs + sus
  asserts se congelan en el repo ANTES de tocar el agente (si no, el bench se contamina con lo
  que el agente sabe hacer).
- **Número GLM:** NO existe benchmark de diseño publicado para GLM-5.2 (declarado). Supuesto
  explícito no medido: un frontier satura asserts duros de este tipo (≈98-100%). El eje se mide
  contra el bar absoluto, no contra GLM.
- **Baseline 3B pelado (predicción congelada):** 55-65% de asserts.
- **Umbral "cerca" PRE-REGISTRADO: ≥85% de asserts** con agente v1 (BoN-4 + repair dirigido por
  assert fallido — el assert ES el traceback del diseño). Stretch: ≥92%.
- **Presupuesto:** CPU 2-3 h; T4 ~20 min. Harness: `cognia_v3/eval/bench_design.py` (nuevo).

**Regla transversal:** los 3 harness corren con `venv312`, reportan JSON con conteos reales, y el
baseline pelado se corre ANTES que cualquier palanca (CP0, §7) — sin baseline propio medido no hay
claim. Riesgo de contaminación declarado: BFCL puede estar en el pretraining de Qwen2.5; mitigación
parcial = reportar por categoría y comparar contra el baseline pelado propio (el Δ del andamiaje
es nuestro, la contaminación afecta ambos brazos por igual).

---

## 5. Árbitro LCD+MOM en el dominio agente: el experimento más barato que lo falsea

**Qué afirma el paper del dueño (§4.2):** un árbitro que atribuye la falla al módulo culpable en
un pipeline multi-etapa, formulado como "el componente menos precedented", con verificación por
etapa como hipótesis frente al gradiente end-to-end.

**El experimento (AG-ARB, pre-registrado):**
- **Setup:** 30 tareas del benchmark duro propio, cada una corrida por el pipeline
  plan→diseño→código→test→reparación con UNA falla INYECTADA en etapa conocida (mutación seeded:
  plan que omite un requisito, diseño con firma incompatible, código con bug lógico, test con
  assert equivocado — ground truth de etapa culpable por construcción, estilo mutation testing).
- **Brazos:** (i) **verificación por etapa**: contratos I/O + oráculos duros (¿el diseño
  referencia todos los objetos del plan? ¿compila? ¿pasa el test de la etapa?) — atribución =
  primer contrato violado; (ii) **árbitro-LLM global**: el 3B juzga desde la salida final "qué
  etapa falló"; (iii) árbitro-LLM con traza completa en contexto.
- **Métricas:** accuracy de atribución de etapa (30 casos) + éxito de reparación downstream
  usando la atribución de cada brazo (re-correr SOLO la etapa señalada).
- **Predicción congelada:** (i) ≥80% en etapas con oráculo ejecutable; (ii) ≤55% — Who&When midió
  53.5% con jueces FRONTIER (o1/R1), un 3B no debería superarlos; (iii) mejora sobre (ii) pero
  <(i). **Falsación honesta en ambas direcciones:** si (ii)≥(i), el árbitro-LLM revive y la
  formulación original del paper gana; si (i) gana, el árbitro del paper se re-especifica como
  cascada contratos-primero con LLM solo de fallback.
- **Presupuesto:** ~2-3 h CPU (las 30 trazas reusan el harness del benchmark duro); 0 GPU.

**Cómo esto MEJORA el paper del dueño (concreto):**
1. **Prior-art que le falta citar** (§4.2 dice "menos precedented" — ya no lo es): Zhang et al.
   ICML 2025 "Which Agent Causes Task Failures and When?" + dataset Who&When (2505.00212);
   AgenTracer (2509.03312: atribuidor liviano entrenado > LLM-juez grande — apoya la tesis MoM de
   componentes chicos especializados); "From Flat Logs to Causal Graphs" (2602.23701); MAST
   (taxonomía de fallas, 1600+ trazas); la dicotomía PRM/ORM con el hallazgo ORPS (2412.15118:
   ejecución verificable + crítica > PRM aprendido); Design-by-Contract para agentes (2510.12120 —
   formaliza los "contratos de entrada/salida" que el paper describe informalmente en §4.1);
   reward hacking en jueces (2606.04923 — respalda con literatura el hallazgo propio CYCLE 12).
2. **Formulación testeable que el paper puede adoptar:** "la verificación por etapa domina al
   crítico global ⟺ (a) existe oráculo ejecutable barato en ≥1 etapa Y (b) las etapas son
   semánticamente heterogéneas y no sustituibles; en pipelines cortos sin oráculo intermedio,
   reintentar la cadena completa domina a instrumentarla". AG-ARB es exactamente el test de esa
   bicondicional en el dominio agente, y la analogía del paper (geometría≠materiales≠iluminación)
   cumple (b) por construcción — lo que falta medir es (a) en su dominio.
3. **El concepto "blame function"** (comparar salida por etapa contra referencia y detectar si
   una etapa posterior reparó o dañó) ya está formalizado — citar en vez de re-derivar, y usar
   la nomenclatura estándar hace el paper indexable en la conversación correcta.

---

## 6. Arquitectura del agente v1 (módulos, dónde vive cada cosa, flujo)

**Principio rector (heredado y medido):** detector barato → palanca cara solo si aplica →
verificación real → señal no-circular. Cero frameworks; funciones planas y registries simples
como el código vecino.

| módulo | ruta | qué hace | estado |
|---|---|---|---|
| loop del agente | `cognia/agent/loop.py` | parsing ACCION (`first_action_block`), step-budget dinámico | EXISTE — se extiende con hooks de contratos |
| registry de tools | `cognia/agent/tools.py` | 25 tools `@tool(...)`, `build_tools_doc()`, `run_tool()` | EXISTE — se agrega campo `tier` |
| detectores | `cognia/agent/stepwise.py` | CoT-gate medido; se agregan `bon_applies()`, `tests_first_applies()`, `repair_applies()` (regex, cero LLM) | EXISTE — extender |
| candidatos BoN + juez | `cognia/agent/candidates.py` | genera N candidatos (temp>0), ejecuta tests visibles en sandbox, rank: tests > bpb-MoM (desempate, hipótesis §1) > primero | NUEVO |
| estructura de tool-calls | `cognia/agent/structure.py` | generate-then-structure: extrae/valida args del bloque ACCION contra la firma de la tool; si inválido → 1 retry con el error del parser en el prompt | NUEVO |
| contratos por etapa | `cognia/agent/contracts.py` | checkers baratos plan→diseño (cobertura de entidades), diseño→código (firmas via `ast.parse`), código→test (ejecución) — la base de AG-ARB | NUEVO |
| ciclo de vida de auto-tools | `cognia/agent/tool_synthesis.py` + `skills.py` | ya verifica en sandbox; se agregan: gate crear-vs-reusar, trigger ≥4 calls, tiers, blocklist duro, degradación de `staged` | EXISTE — extender |
| selector de dominio | `cognia_x/mom/selector.py` (T=0.05) | detector de dominio calibrado para elegir palanca/experto; fallback asimétrico ya medido | EXISTE — se importa, no se toca |
| flota MoM | `cognia_x/mom/fleet.py` | carga perezosa de expertos; bpb-scorer para el desempate de candidates.py | EXISTE |
| benchmarks | `cognia_v3/eval/{benchmark_code.py, bench_bfcl_slice.py, bench_design.py, bench_arbitro.py}` | los 4 harness de §4-§5 | 1 EXISTE + 3 NUEVOS |

**Flujo de un turno /hacer (v1):** pedido → `stepwise`/selector deciden palancas (¿CoT? ¿test-first?
¿BoN?) → si tarea de código con spec clara: generar test primero → generar plan/diseño/código con
contratos I/O verificados en cada transición (`contracts.py`) → si BoN aplica: N candidatos
rankeados por tests en sandbox (`candidates.py`) → tool-calls parseados y validados
(`structure.py`, retry con error real) → si falla un oráculo: repair gated con el
traceback/assert real (nunca autocrítica ciega) → cierre con verificación real y, si la traza
amerita (trigger §3.3), oferta de persistir skill nivel-2.

**Restricciones respetadas:** sin PyTorch en nodos (la flota MoM corre torch solo en la máquina
de investigación; el agente de producción usa llama.cpp + el selector puro-Python); sin
`sqlite3.connect` directo; sin constantes de modelo hardcodeadas; regla 9 en toda tool generada.

---

## 7. Plan de construcción por checkpoints (presupuestos + regulación de modelos)

Regla de cierre por checkpoint (método del repo): pytest dirigido + corrida CLI real con output
mostrado + commit enfocado + push. Ningún checkpoint se declara sin su verificación e2e.

| CP | entregable | gate de salida | presupuesto | modelo |
|---|---|---|---|---|
| **CP0** | 3 harness de bench (§4) + specs/asserts de diseño congelados + baselines PELADOS medidos en los 3 ejes | 3 JSON de baseline con conteos reales; specs commiteadas ANTES de tocar el agente | CPU 8-12 h (nocturno ×2) + 0 T4 | scaffolding de datasets/parsers: **haiku**; checkers y asserts (son el oráculo — no pueden estar mal): **Fable**; harness code: **sonnet** |
| **CP1** | palancas 1-5 de §2 (`candidates.py`, `structure.py`, extensión stepwise) + re-bench ejes 1 y 2 | eje-2 ≥+8pp sobre baseline O reporte de no-transferencia; eje-1 mejora medible del formato | CPU 6-10 h de bench + dev | módulos con tests: **sonnet**; decisión de adopción por palanca (leer números, adoptar/retirar): **Fable** |
| **CP2** | ciclo de vida auto-tools (§3): tiers, trigger, blocklist, gate crear-vs-reusar; 3 tools generadas e2e como prueba | 1 tool nivel-1 y 1 skill nivel-2 creadas, verificadas y reusadas en corrida CLI real; blocklist con test de regresión por patrón | CPU 4-6 h | blocklist y modelo de seguridad: **Fable** (no delegable); resto: **sonnet** |
| **CP3** | AG-ARB (§5): `contracts.py` + `bench_arbitro.py` + corrida de los 3 brazos | los 3 accuracies reportados contra la predicción congelada; veredicto para el paper escrito | CPU 3-4 h | inyección de fallas y análisis: **Fable**; harness mecánico: **sonnet** |
| **CP4** | corrida completa pre-registrada de §4 (3 ejes con agente v1) + informe honesto vs umbrales + memoria | cada eje: número final vs umbral "cerca", con brazo pelado y brazo v1 en el mismo JSON | CPU 12-16 h (nocturnos) o 2 sesiones T4 (~1.5 h) | corridas: **haiku** (lanzar/vigilar); informe y claims: **Fable** |
| **CP5** (condicional) | QLoRA tool-calling del 3B SOLO si CP4 muestra que el formato sigue siendo el cuello (errores de parseo >15% residual) | gate económico: pipeline existente, riesgo = verificación de teléfono Kaggle (bloqueó el 3B antes — se declara, no se promete) | 1-2 sesiones T4 (30-60 min) | dataset verificado-por-ejecución: **sonnet**; go/no-go: **Fable** |

**Regulación de modelos (regla general):** haiku = mecánico y reversible (corridas, conversiones,
logs); sonnet = código con tests donde el diseño ya está fijado; Fable = todo lo que fija
oráculos, umbrales, seguridad o claims — porque un oráculo mal escrito envenena TODOS los números
de después, y un claim mal calibrado viola §8. Presupuesto total estimado: ~35-50 h de CPU i3
(mayormente nocturnas) + ≤3 sesiones T4 — dentro de la quota semanal sin tocar XHUNDRED.

---

## 8. Riesgos y qué NO prometer

| # | riesgo / promesa prohibida | por qué / mitigación |
|---|---|---|
| P1 | **NO prometer "cerca de GLM-5.2" global** | GLM-5.2 es un MoE 753B; "cerca" existe SOLO por-eje según §4; cualquier titular sin el eje y el umbral es overclaim |
| P2 | **NO prometer SWE-bench / LiveCodeBench** | brecha de capacidad, no de andamiaje (<10-15% típico de un 3B vs 62-85%); declarado en §4 eje-2 y se publica así |
| P3 | **NO prometer multi-turn agentic competitivo** | el frontier mismo saca 27% en tau3-banking; nuestra apuesta es no PERDER puntos (goal-drift ya arreglado), no ganar paridad |
| P4 | **BoN+juez puede no transferir** (+15.6pp es de un 3B coder-tuned) | falsación en CP1: <+8pp → se reporta no-transferencia y se retira; el bench propio decide, no el paper |
| P5 | **bpb-MoM como ranker puede no superar a random** | hipótesis declarada §1; se mide en CP1 y se retira sin drama — la flota conserva su rol de selector de dominio |
| P6 | **Contaminación de BFCL en Qwen2.5** | no negable; mitigación: el claim central es el Δ andamiaje (pelado vs v1, misma contaminación en ambos brazos) + reporte por categoría |
| P7 | **Goodhart sobre los asserts de diseño** | asserts congelados ANTES de construir (CP0); si el agente los ve durante el desarrollo, el bench muere — disciplina de no-mirar declarada |
| P8 | **Auto-tools: prompt injection vía output de tools / TOCTOU registro→uso** | tools nivel-1 puras (sin red/fs/ctx) + blocklist duro SIEMPRE (no imitar el skip de Hermes) + tiers con degradación; residual declarado: un skill nivel-2 malicioso solo puede persuadir, no ejecutar |
| P9 | **NO prometer velocidad de conversación 4×** | lección exp021 vigente: 4.3× es del turno ruteado al chico; total medido 1.11× |
| P10 | **Kaggle puede bloquear el QLoRA 3B otra vez** (verificación de teléfono) | CP5 es condicional y con fallback (0.5B ya entrenado); no hay promesa que dependa de él |
| P11 | **El wall CPU del i3 infla los benchs** (8 tok/s) | presupuestos de §4 asumen corridas nocturnas; si un harness excede 2× su presupuesto, se recorta el N de items ANTES de correr, no después de ver números |
| P12 | **Riesgo de re-litigar CYCLE 47** | "más orquestación no mueve la aguja" sigue vigente: cada palanca entra por número en NUESTRO bench, y el orden verificador→expertos→router no se invierte |

---

**Cierre del pre-registro.** Este documento se congela antes de CP0. Los umbrales de §4, las
predicciones de §5 y los gates de §7 no se editan después de ver resultados; desvíos van a
`01_DESVIOS.md` append-only con fecha y razón.
