# 05 — Lazo de auto-mejora verificada (STaR) + guardia de diversidad

> **Propósito.** Especificar el **motor que evoluciona el sustrato sin reconstruirlo todo**: el lazo
> *act-and-verify* donde **muestrear = actuar** y **verificar = quedarse con lo correcto**, y luego
> **re-entrenar** sobre lo verificado (STaR / rejection-sampling imitativo). El plano define (a) el
> bucle iterado estable, (b) la **GUARDIA de diversidad OBLIGATORIA** (dedup de verificados + replay
> limpio de la verdad-semilla) que cura el *narrowing* y sube el FP-rate tolerable e\* de ~0.15 a
> ~0.50, (c) la extensión **multi-paso** (verificación de proceso + presupuesto adaptativo per-step +
> abstención + retry/backtracking), (d) el **anti-colapso** (filtro de corrección + gate NO circular:
> held-out rotativo + committee anti-Goodhart + snapshot del optimizer/modelo para rollback) y (e) el
> **monitor de diversidad** que dispara la alarma antes del colapso. Este lazo es el **consumidor** del
> verificador del plano 04; no lo reimplementa.

> **Anclaje de fuentes (verificado, no asumido):**
> - Lazo base que corre hoy (toy, `HybridLM` d=64 byte-level, suma): `cognia_x/experiments/exp016_verified_bootstrap/`
>   (`run.py:build_base/generate_pool/train_arm`, `addition_task.py`). H-LEARN-1, CYCLE 29.
> - Sustrato + amplificación: `exp034_substrate_amplify/run.py` (`build_starsets`, `chain_acc_greedy`).
>   H-V4-2, CYCLE 48.
> - Iterar el lazo (narrowing): `exp035_iterated_star/run.py` (`gen_and_measure`). H-V4-2b, CYCLE 49.
> - **Guardia (dedup+replay):** `exp036_diversity_guard/run.py` (`coverage_prompts`, `seed_correct`,
>   `run_loop`). H-V4-2c, CYCLE 50.
> - Generalización a verificador REAL: `exp037_iterated_real_verifier/` (CYCLE 51), `exp038_real_verifier_ceiling/`
>   (CYCLE 52, **el DoD demostrado en pequeño**), `exp039_noisy_real_verifier/` (CYCLE 53, e\*).
> - Gating endógeno/externo: `exp046_self_consistency_verifier/` (CYCLE 60), `exp047_gated_self_verifier/run.py`
>   (`filter_gated`, `_estimate_calibration`, CYCLE 62).
> - Multi-paso: `exp030_multistep_reasoning/` (proceso), `exp031_adaptive_perstep/` (presupuesto, 4.1×),
>   `exp032_abstention_noisy/` (abstención), `exp033_backtrack_retry/` (retry/backtracking). CYCLE 44-47.
> - Cierre downstream con guardia: `exp078_closed_loop_guard/` (CYCLE 94), `exp095_guard_diversity/` (CYCLE 111).
> - Gobernanza: `00_READINESS.md` (orden Apéndice A: verificador → **lazo** → expertos), plano `04_verificador.md`
>   (gate/hooks que este lazo invoca), `01_arquitectura_sistema.md`.

---

## 1. Propósito y alcance

### 1.1 Qué resuelve
- Da al sistema un **motor de auto-mejora autónomo**: el modelo genera (actúa), un verificador
  *chequeable* (plano 04) filtra lo correcto, y el modelo **se re-entrena sobre sus propias salidas
  verificadas**. Mejora el **sustrato barato** desde dentro, sin re-pre-entrenar desde cero ni datos
  externos nuevos — y por la composición `p^K` esa mejora del paso **rinde compuesto** en cadenas largas
  (exp034).
- Hace ese motor **estable a lo largo de rondas** con la **guardia de diversidad** (dedup + replay).
  **Matiz honesto (corregido en verificación adversarial):** el lazo iterado *plano* (sin guardia) **NO
  colapsó** a escala toy — exp035 (H-V4-2b, APOYADA) lo midió **estable** (`div_collapse=False`,
  `non_decreasing=True`): la diversidad **decae monótona** pero **no cruza** el umbral de colapso 0.5×, y
  la precisión por paso sube y platea. exp037 con verificador real también dio `plain_narrows=False`. Lo
  que la guardia compra **medido** es: (a) una **Pareto-mejora** de cobertura/precisión sobre el plano
  (exp036, no un rescate de un colapso); y (b) lo **load-bearing** de verdad — **tolerancia al FP del
  verificador** (exp039: el plano colapsa a e\*=0.0 bajo ruido, la guardia aguanta hasta e\*≈0.5). El
  *narrowing* (decaimiento de diversidad/cobertura) es la señal **temprana** que la guardia atenúa, no un
  colapso ya observado en el toy.
- Extiende el motor a **razonamiento multi-paso** (cadenas) sin que el error se componga, con
  presupuesto adaptativo, abstención y retry.
- Protege el lazo contra **colapso/reward-hack** con un **gate NO circular** (la línea roja H-SELF-2 de
  Cognia: evaluar sobre la misma DB que se auto-escribe) y rollback por snapshot.

### 1.2 Qué NO cubre (se delega)
- **Cómo se decide si un candidato es correcto** (sandbox, forma cerrada, hechos, FP-rate, calibración,
  abstención del verificador) → **plano 04**. Aquí el lazo **consume** `VerifyResult` y el **gate/hooks**
  (`evidence["fingerprint"]`, `replay_eval`) que el plano 04 expone; no reimplementa verificación.
- **El backbone** que genera (HybridLM, atención SWA, escala) → plano 02. Aquí el modelo es una caja con
  `generate()` + `forward(x,y)→loss`.
- **La inyección de hechos nuevos** (RAG doc-level vs LoRA, gate G3) → plano de aprendizaje continuo. El
  lazo entrena el sustrato/adapters con lo verificado; la *política* de hechos es de otro plano.
- **El director de expertos / routing** (fase tardía, orden Apéndice A): el lab concluyó (CYCLE 47, giro
  estratégico) que el lever NO es más routing sino **mejor sustrato + verificador** — exactamente lo que
  este plano construye **antes** de la jerarquía.

### 1.3 Alcance honesto
Todo lo demostrado es **DEMOSTRADO-PEQUEÑO**: `HybridLM` d=64 byte-level (vocab 256), tareas de suma
(exp016/034/035/036) y de expresiones con verificador-sandbox real (exp037/038/039), 2-4 seeds, R≤10
rondas, en CPU. La **transferencia a escala real** (modelo 1-3B, dominio código con suites Python, lazo
sobre GGUF/adapters LoRA en Kaggle) está **ASUMIDA**, no medida — SCALE=0%. Las constantes de umbral
(e\*≈0.15/0.50, `div_collapse < 0.5×`, márgenes) son **confianza media**: citadas del ledger toy, se
**re-miden** en el dominio objetivo (§5). El bootstrap base-débil→techo-alto sin colapso **sí** está
medido en pequeño con verificador real (exp038: 0.081→0.933, plateau, sin colapso) — esa es la prueba de
concepto del DoD, no la garantía a escala.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe | Corre | Cita |
|---|---|---|---|
| Lazo STaR de 1 ronda (genera→verifica→entrena), brazos con controles | Sí (toy) | Sí | `exp016_verified_bootstrap/run.py` (`generate_pool`, `train_arm`, `build_base`) |
| **El verificador ES el motor** (no el volumen ni el filtrado-per-se) | Sí | Sí | exp016 H-LEARN-1 APOYADA: `verified` único brazo con ganancia NETA; gap medio **+0.10** sobre `random_matched` (mismo N_keep + mismos pasos); `naive_all` no mejora |
| 1 ronda mejora el **paso por corrección** y **amplifica** en cadena (`p^K`) | Sí | Sí | exp034 H-V4-2 APOYADA: `verified` > `control` en paso; ratio cadena crece con K |
| Iterar el lazo: estable, diversidad **decae monótona** (sin colapsar) | Sí | Sí | exp035 H-V4-2b APOYADA "motor estable" (`div_collapse=False`); el decaimiento monótono **motiva** la guardia, pero NO hubo colapso en el toy |
| **Guardia dedup+replay** previene narrowing sin costo de precisión | Sí | Sí | exp036 H-V4-2c APOYADA (3 seeds): `plain_narrows=True`, `guard_keeps=True`, `no_prec_cost=True` |
| El lazo+guardia generaliza a **verificador REAL** (sandbox), sin reward-hack | Sí | Sí | exp037 H-V4-2d APOYADA: `real_guarded` 0.441→**0.941**, `no_hack=True`, `guard_keeps_cov=True` |
| **Bootstrap base débil → techo alto, plateau, SIN colapso** (el DoD) | Sí | Sí | exp038 H-V4-2e APOYADA: base **0.081 → final 0.933** (peak 0.941@r7), `plateaus=True`, `collapses=False` |
| La guardia **sube e\*** (tolerancia a FP del verificador) | Sí | Sí | exp039: e\* `plain=0.0 → guarded=0.5`; con guardia, net +0.155 aún a FP=0.50 |
| **Gating** endógeno/externo (el agente decide cuándo confiar en sí) | Sí | Sí | exp047 H-V4-2j: `filter_gated`/`_estimate_calibration` (probe barato + umbral) |
| Multi-paso: proceso / presupuesto adaptativo / abstención / retry | Sí | Parcial (exp031 **MIXTA**) | exp030/031(4.1× accuracy-ratio @Kmax, MIXTA)/032/033 (CYCLE 44-47) |
| **Lazo unificado como subsistema** (no scripts de experimento) | **No** | — | Este plano lo define (`cognia_x/selfimprove/`) |
| Lazo sobre **modelo real** (GGUF/LoRA) en Kaggle GPU | **No** | — | §5.5; ASUMIDO, no medido |
| Monitor de diversidad como servicio + alarma + rollback automático | **No** | — | Diseño nuevo aquí (§3.6/§3.7) |

**Lectura honesta.** El **algoritmo del lazo está demostrado de punta a punta en pequeño** —incluida la
generalización a un verificador-sandbox real (exp037/038) y la tolerancia al ruido del verificador con
guardia (exp039). Lo que **no** existe es: (a) el subsistema **empaquetado** (hoy son scripts
`expNNN/run.py` que comparten `build_base/generate_pool/train_arm`); (b) la corrida sobre **modelo real**
a escala (Kaggle); (c) el **monitor + rollback** automatizados. NO se parte de cero: se **extrae** el
bucle de `exp036.run_loop` + `exp035.gen_and_measure` a `cognia_x/selfimprove/`, se conecta al
`VerifierRegistry` del plano 04 en vez del oráculo de juguete, y se sustituye `train_arm` (torch-cpu
in-place) por un *trainer* que en producción es **fine-tune de adapter LoRA en Kaggle** (los nodos no
entrenan; restricción dura).

---

## 3. Diseño detallado

### 3.1 El bucle nuclear — `act → verify → keep → retrain`

Ubicación: `cognia_x/selfimprove/loop.py`. Estilo: funciones planas + dicts, igual densidad que
`exp036/run.py`. Sin frameworks. El bucle es **literalmente** `exp036.run_loop` generalizado: el oráculo
`T.oracle_correct` se reemplaza por `VerifierRegistry.verify()` (plano 04), y el filtro de aceptación es
`VerifyResult.ok is True`.

```python
# cognia_x/selfimprove/loop.py  (pseudocódigo fiel a exp036.run_loop)
def self_improve_round(model, prompts, verifier, guard, monitor, gate, cfg, rng):
    # 1) ACTUAR: muestrear K completaciones por prompt (= explorar). temperatura ALTA = diversidad.
    pool = generate_pool(model, prompts, cfg.K, cfg.temperature, cfg.top_k, "cpu")  # [(p, emitted, ...)]
    # 2) VERIFICAR: quedarse sólo con lo CORRECTO (señal de corrección, no volumen). plano 04.
    verified = [(p, e) for (p, e) in candidates(pool)
                if verifier.verify(to_candidate(p, e)).ok is True]
    # 3) MONITOR de diversidad ANTES de entrenar (cobertura/diversidad de ESTA ronda).
    div  = diversity_fraction(pool)            # exp035: |respuestas distintas| / |total|
    cov  = coverage_prompts(verified)          # exp036: nº de PROMPTS distintos verificados
    monitor.observe(round_idx, step=None, div=div, cov=cov)
    # 4) GUARDIA: dedup de verificados + replay LIMPIO de la verdad-semilla (OBLIGATORIA, §3.3).
    train_set = guard.build_train_set(verified)
    # 5) RE-ENTRENAR sobre lo verificado+guardado (imitación; NUNCA RL con auto-recompensa).
    snapshot = gate.snapshot(model)            # para rollback (anti-colapso, §3.5)
    if train_set:
        train_arm(model, train_set, cfg.star_steps, cfg.batch, cfg.star_lr, "cpu", rng)
    # 6) GATE NO CIRCULAR: medir en held-out DISJUNTO + committee; rollback si regresa (§3.5).
    ok, scores = gate.evaluate(model, committee_holdouts(round_idx))
    if not ok:
        model = gate.restore(snapshot)         # revertir la ronda
    monitor.observe(round_idx, step=scores.primary, div=div, cov=cov)
    return model, {"div": div, "cov": cov, "n_verified": len(verified), "gate": scores, "reverted": not ok}
```

**Por qué muestrear=actuar.** Una completación con `temperature>0` **es** una acción de exploración del
espacio de soluciones; el verificador es el **entorno** que da recompensa *chequeable* (no proxy). Esto
es RL **sin** los modos de fallo del RL: como sólo **imitamos** lo verificado (no maximizamos un score
diferenciable), el lazo **no hackea** el verificador débil (exp037 `no_hack=True` con verificador
real, **APOYADA**). El contrapunto *"RL hackea más que imitación"* **NO está demostrado in-lab**:
exp020 (H-LEARN-5) está **REFUTADA** (null de método — GRPO-lite tiny inestable/colapsa el modelo). La
preferencia por imitación es **precaución de diseño** (literatura RL + exp017 dose-response), no un hack
medido. Decisión dura igual: **imitación, nunca RL-con-auto-recompensa-online** (restricción del lab;
`00_READINESS.md`).

**Reutilizables verificados** (no reimplementar): `generate_pool` (batcheo por longitud de prompt, rápido
en CPU), `train_arm` (N pasos AdamW, **optimizer fresco por ronda**, clip 1.0), `build_base`
(`exp016/exp018`). `coverage_prompts`/`seed_correct` de `exp036`.

### 3.2 Por qué el filtro de CORRECCIÓN es el motor (no el volumen)

La columna vertebral del lazo es un resultado **con control decisivo**, no una intuición:
- **exp016** (H-LEARN-1): tres brazos desde el **mismo** base — `verified` (sólo correctas),
  `random_matched` (subconjunto **aleatorio** del mismo tamaño y mismos pasos → aísla volumen+filtrado),
  `naive_all` (todas, incl. incorrectas). `verified` es el **único** brazo con ganancia neta sobre su
  propio base en **todos** los seeds; gap medio **+0.10** (medido 0.1255) sobre `random_matched`, t-pareado
  p<0.05 (df=3). ⇒ el motor es la **señal de corrección**, no tener "menos datos" ni el acto de filtrar.
  **Caveat (del propio exp016):** **magnitud MODESTA** ("~+0.10, no substancial"), **n=4 seeds**, y bajo
  *final-round-only* el gap se invierte en un seed (por eso se usa media-sobre-rondas) — confianza media.
- **exp034** (H-V4-2): `verified` > `control` (subconjunto random de TODAS) en precisión POR PASO, y la
  ventaja **se amplifica** en cadena (ratio `verified/base` crece con K). exp034 **midió** la amplificación
  sólo hasta **K≤3** (`ratio_hi≈2.71`). La cifra `0.5^6=1.6% → 0.65^6=7.5%` (~4.7×) es una **proyección
  ilustrativa** con números redondos a K=6, **NO medida** — el principio "el paso barato rinde compuesto"
  es lo medido; el 4.7× concreto es ejemplo, no dato.

**Consecuencia de diseño:** el lazo **sólo** entrena con `ok is True`. Los `ok is False` se **descartan**
(no se entrenan como negativos: no hacemos contrastive/RL). Los `ok is None` (abstención del verificador,
plano 04 §3.5) **tampoco** se entrenan — ni positivo ni negativo. Esto preserva precisión a costa de
cobertura (exp032/exp046: la abstención calibrada sube precisión).

### 3.3 La GUARDIA de diversidad (OBLIGATORIA) — dedup + replay limpio

Ubicación: `cognia_x/selfimprove/guard.py`. **Es el corazón del plano.** El lazo iterado **sin** guardia
sufre *narrowing*: la diversidad de respuestas **decae monótona** ronda a ronda (exp035: diversidad
0.0398→0.0213) — el modelo se entrena sobre su propia distribución cada vez más estrecha. **Precisión
honesta:** a escala toy ese decaimiento **no llegó a colapso** (exp035 `div_collapse=False`, verdicto
"motor estable"); la guardia es una **Pareto-mejora preventiva** (exp036) y, sobre todo, el seguro contra
el FP del verificador (exp039, §abajo). Dos arreglos baratos, **medidos** (exp036):

1. **DEDUP de verificados.** Cada par `(prompt, answer)` único **una sola vez** por ronda (no por
   frecuencia). Evita que un puñado de aciertos fáciles domine el set y machaque los mismos patrones —
   y, crucial para el verificador, evita **amplificar un FP correlacionado** (si el verificador acepta
   por error un patrón, la repetición lo entrena con fuerza). Implementación fiel a exp036:
   ```python
   uniq = list(dict.fromkeys((bytes(p), bytes(e)) for (p, e) in verified))  # dedup, preserva orden
   ```
2. **REPLAY limpio de la verdad-semilla.** Intercalar una fracción `replay_n` (default 128, exp036) de
   ejemplos **CORRECTOS de la VERDAD original** (datos semilla, **no** auto-generados) en cada ronda de
   entrenamiento. Es el ancla a la distribución real que frena la deriva:
   ```python
   train_set = uniq + replay_pairs          # replay_pairs = seed_correct(train_pairs, replay_n, rng)
   ```

**Evidencia (exp036, H-V4-2c APOYADA, 3 seeds, R=6, modelo propio):**

| Métrica (ronda final r=6) | PLANO | GUARDED |
|---|---|---|
| Precisión por paso (held-out) | 0.642 | **0.692** |
| Cobertura (prompts distintos verificados) | 184.7 | **201.7** |
| `plain_narrows` | True | — |
| `guard_keeps` (más cobertura/div que plano) | — | True |
| `no_prec_cost` (no sacrifica precisión) | — | True |

La guardia **mantiene la cobertura más alta** (201.7 vs 184.7) **y** la precisión **igual o mejor**
(0.692 ≥ 0.642) — no es un trade-off, es Pareto-dominante en este toy. Y sube la **tolerancia al ruido
del verificador**: e\* (FP-rate efectivo tolerable) pasa de **~0.15 sin guardia** (exp017, oráculo) /
tan bajo como **0.0** en el verificador real ruidoso (exp039 `plain`) a **~0.50 con guardia** (exp039
`guarded`: net **+0.155** aún con FP=0.50). **Confianza media** (toy). El downstream del lazo cerrado
real también apunta en esa dirección: exp078 (CYCLE 94, **APOYADA**) muestra que la guardia **rescata** la
asignación confidence-greedy sin perder yield; exp095 (CYCLE 111, verdicto **MIXTA**) sugiere —sin
cerrarlo— que con el filtro completo la alta diversidad del generador tiende al óptimo.

> **Regla dura del plano:** la guardia **no es opcional**. El motivo medido **no** es que el lazo plano
> colapse por sí solo (no lo hizo en el toy, exp035) sino que el plano **degrada la tolerancia a FP a casi
> cero** (exp039 `plain` e\*=0.0): con cualquier verificador real imperfecto, el lazo plano se va a
> auto-degradación. Toda corrida de auto-mejora **arranca con dedup+replay activos**.

**Config de la guardia (`cognia_x/selfimprove/config.py`, confianza media, re-medir §5):**
```python
REPLAY_N        = 128     # ejemplos semilla CORRECTOS re-inyectados por ronda (exp036)
REPLAY_FRAC     = None    # alternativa: fracción del train_set (re-calibrar a escala real)
DEDUP           = True    # (prompt,answer) único una vez por ronda — OBLIGATORIO
DIV_COLLAPSE_X  = 0.5     # alarma si diversidad < 0.5× la inicial (umbral de COLAPSO de exp035; en
                          # exp035 NO se cruzó -> lazo plano estable a escala toy; es un circuit-breaker, no un valor medido de fallo)
```

### 3.4 Multi-paso: que el error no se componga

Para razonamiento de **K pasos**, el cuello de botella es la **precisión POR PASO** (sub-arco 44-47): a
`p` por paso, una cadena de K pasos sale a `p^K`. El lazo mejora `p` (§3.2); además se orquesta la cadena
para no componer el error. Cuatro piezas, todas demostradas en pequeño (CYCLE 44-47):

- **Verificación de PROCESO (exp030, CYCLE 44).** Verificar **cada paso** (no sólo el resultado final)
  frena el *compounding*: un paso malo se detecta y corta antes de contaminar los siguientes. El lazo
  recoge para entrenar **sólo las trazas con todos los pasos verificados** (señal de proceso, no de
  outcome).
- **Presupuesto ADAPTATIVO per-step (exp031, CYCLE 45).** No gastar el mismo número de muestras en
  cada paso: asignar más cómputo donde el modelo está inseguro (señal de confianza/valor). **Precisión
  honesta:** exp031 es **MIXTA** (no APOYADA limpia) y `gains_grow=False` (la ventaja **no** crece
  monótona con K: pico a K=4, decae después). El "**4.1×**" es el **cociente de accuracy** adaptive/uniform
  a **igual cómputo total** en Kmax=8 (0.240/0.058), **NO** "eficiencia de cómputo a igual cobertura"; el
  rescate de cadenas largas es real pero el factor exacto es del toy. La señal de asignación es R-VALOR como
  **brújula decisional acotada** (no acelerador de loss; ledger 149-155).
- **ABSTENCIÓN calibrada (exp032/exp046, CYCLE 46/60).** Cuando la confianza del paso < umbral, **abstener**
  (no emitir) en vez de adivinar — sube la precisión condicional a costa de cobertura. En el lazo, una
  cadena abstenida **no** produce ejemplo de entrenamiento (mejor no-dato que dato-ruidoso).
- **RETRY / backtracking (exp033, CYCLE 47).** Ante un paso fallido, reintentar / retroceder recupera
  cobertura sin bajar precisión. El presupuesto de retry es parte del presupuesto adaptativo.

**Gating endógeno/externo (exp047, CYCLE 62).** Verificar **cada** candidato con el verificador externo
es caro. El lazo estima su **propia calibración** con un *probe* barato (`probe_frac=0.15` de los prompts,
unas pocas llamadas al verificador) y **decide**: si `calib_est ≥ calib_threshold` (default 0.65) usa el
filtro **endógeno** (auto-consistencia) en el grueso; si no, **cae al externo**. Resultado medido (exp047,
verdicto **MIXTA**): el gated **evita el colapso** en régimen débil (`weak_avoids_collapse=True`: gated
0.328 vs self-consistency 0.038) y **no pierde** en fuerte (gated 0.733 vs 0.592). **Caveat honesto:** la
**separación por régimen no es limpia** (en débil sólo elige endógeno 33% de las veces, en fuerte 92%; y
`weak_matches_verified=False` — no iguala al verificador externo puro). Lo robusto es "no colapsa"; el
ahorro endógeno es parcial. En el toy el target estaba en el prompt; **en producción** el probe son **N
llamadas reales al verificador** del plano 04 para calibrar, luego endógeno en el resto. **Confianza media**
(el mecanismo está medido; el ahorro real depende del costo del verificador del dominio).

### 3.5 Anti-colapso: filtro de corrección + gate NO circular + rollback

Tres líneas de defensa contra el modo de fallo más caro (el lazo aprueba su propio ruido y diverge —
`H-SELF-2` de Cognia):

1. **Filtro de corrección (ya en §3.2).** Sólo se entrena `ok is True`. El verificador es **código /
   recuperación**, no el LLM juzgándose (no comparte parámetros con el generador) — la línea que separa
   "verificador chequeable" de "auto-recompensa".

2. **Gate NO circular (`cognia_x/selfimprove/gate.py`).** El gate que decide si la ronda **se acepta o se
   revierte** **nunca** mide sobre datos que el lazo generó o escribió. Tres mecanismos:
   - **Held-out rotativo.** Un set *gold* **disjunto** del pool de auto-generación (igual que
     `build_split()` parte train/test disjuntos en exp016/exp018), **particionado en shards** que **rotan**
     por ronda. Rotar evita que el lazo se sobre-ajuste a un held-out fijo (un held-out usado 50 veces
     deja de ser held-out). El gate mide en el shard de **esta** ronda, que no se tocó en las anteriores.
   - **Committee anti-Goodhart.** No un solo número: un **comité** de métricas/evaluadores
     (precisión por paso, accuracy de cadena greedy `chain_acc_greedy`, cobertura, y al menos un evaluador
     **independiente** del que entrena — patrón "examinador no circular" del router de meta-razonamiento,
     CYCLE 12-21). La ronda pasa sólo si **el comité concuerda**; si una métrica mejora y otra se desploma
     (firma de Goodhart/narrowing), **no** pasa. Esto encarna el anti-Goodhart del lab.
   - **Snapshot del optimizer + modelo → rollback.** Antes de entrenar cada ronda se guarda un snapshot
     (pesos + estado del optimizer; nota: el lazo usa **optimizer fresco por ronda**, así que el snapshot
     crítico son los **pesos**). Si el committee regresa más que `margin`, se **restaura** el snapshot (la
     ronda se descarta). Es el `gate + rollback` del método del lab — el lazo **nunca** avanza a un estado
     peor sin posibilidad de volver.

3. **El monitor (§3.6) como circuit-breaker.** Si la diversidad cae < `0.5×` la inicial (criterio de
   colapso de exp035) o la cobertura cae bajo la inicial (narrowing de exp036), el monitor **detiene** el
   lazo y emite alarma, aunque la precisión todavía aguante (el colapso de diversidad **precede** a la
   degradación de precisión).

```python
# cognia_x/selfimprove/gate.py  (esqueleto)
class NonCircularGate:
    def __init__(self, holdout_shards, committee, margin):
        self.shards, self.committee, self.margin = holdout_shards, committee, margin
        self.best = None
    def snapshot(self, model): return {"weights": clone_state(model)}     # rollback point
    def evaluate(self, model, shard):
        scores = self.committee.score(model, shard)                       # dict de métricas
        ok = (self.best is None) or (scores.primary >= self.best - self.margin
                                     and not scores.goodhart_flag)          # comité concuerda
        if ok: self.best = max(self.best or -1, scores.primary)
        return ok, scores
    def restore(self, snap): ...                                          # carga weights del snapshot
```

### 3.6 El monitor de diversidad (servicio + alarma)

Ubicación: `cognia_x/selfimprove/monitor.py`. Registra **por ronda** (JSON append-only, patrón
`results.json` del lab; o `storage/db_pool.py` si existe — sin `sqlite3.connect` directo):

- **Diversidad** = `|respuestas distintas| / |total generado|` (exp035 `gen_and_measure`). Señal de
  colapso si cae.
- **Cobertura** = nº de **prompts distintos** verificados (exp036 `coverage_prompts`). Señal de
  *narrowing* si cae.
- **n_verified / accept_rate** = cuánta data usable produce la ronda (si cae a 0, el lazo se quedó sin
  combustible).
- **Métricas del committee** (paso, cadena) y si la ronda fue **revertida**.

**Alarmas (circuit-breaker):**
```python
ALARM_DIV   = lambda div, div0: div < 0.5 * div0          # colapso de diversidad (exp035)
ALARM_COV   = lambda cov, cov1: cov < cov1                 # narrowing de cobertura (exp036)
ALARM_YIELD = lambda nver:       nver == 0                 # sin data verificada -> motor sin combustible
ALARM_REVERT= lambda reverts, k: reverts >= k             # k rondas seguidas revertidas -> parar
```
Al dispararse cualquiera, el lazo **se detiene** y deja el modelo en el **último snapshot bueno** del gate.

### 3.7 Configuración concreta (sin constantes mágicas dispersas)

`cognia_x/selfimprove/config.py` (un módulo auditado, análogo a `shattering/model_constants.py`). Valores
**confianza media**, del ledger toy, a re-medir §5:

```python
# --- generación (actuar) ---
ROUNDS          = 10      # exp038 plateó ~r7 con R=10; a escala re-calibrar
K               = 6       # completaciones por prompt (exploración)
TEMPERATURE     = 1.0     # alta = diversidad (la guardia la sostiene)
TOP_K           = 16      # (20 en el dominio expresiones, exp047)
N_PROMPTS       = 384     # prompts por ronda
# --- re-entrenar (imitar) ---
STAR_STEPS      = 200     # pasos de gradiente por ronda (toy); a escala = pasos de LoRA
STAR_LR         = 5e-4
BATCH           = 32
# --- guardia (OBLIGATORIA, §3.3) ---
REPLAY_N        = 128
DEDUP           = True
# --- gate / anti-colapso (§3.5) ---
MARGIN          = 0.03    # regresión tolerada antes de rollback (= margen de exp035/036)
HOLDOUT_SHARDS  = 5       # held-out rotativo disjunto del pool
COMMITTEE       = ["step_acc", "chain_acc_greedy", "coverage", "independent_eval"]
# --- multi-paso / gating (§3.4) ---
PROBE_FRAC      = 0.15    # fracción para estimar calibración (exp047)
CALIB_THRESHOLD = 0.65    # confiar en endógeno sólo si >=65% consistentes correctos (exp047)
TAU_CONSIST     = 0.5     # umbral de auto-consistencia
# --- tolerancia a FP del verificador (informativa, del plano 04) ---
E_STAR_NO_GUARD = 0.15    # exp017 (toy oráculo); tan bajo como 0.0 en verificador real ruidoso (exp039)
E_STAR_GUARD    = 0.50    # exp039 con dedup+replay
```

### 3.8 Frontera de aprendizaje (qué se entrena, dónde)

- **En CPU (i3)** corre todo el lazo toy (numpy/torch-cpu in-place, `train_arm`). Validación y desarrollo.
- **A escala real** el "re-entrenar" **no** ocurre en los nodos (restricción dura: sin PyTorch en nodos,
  QLoRA bloqueado en CPU). El paso 5 del bucle se vuelve: **fine-tune de un adapter LoRA r≤16 sobre las
  salidas verificadas en Kaggle GPU** (cuenta `anthuananthuan`, pipeline `cognia_v3/training/kaggle/`). El
  adapter se funde dentro de la **misma cuenca** (FedAvg SOLO sobre adapters LoRA, nunca params base;
  reconstruir ΔW = `B@A`, nunca promediar A y B por separado — `exp003/E3`). La **generación** (actuar) y
  la **verificación** corren en CPU con llama.cpp+GGUF; el **entrenamiento** (imitar) en Kaggle. El lazo es
  **asíncrono por rondas**, no online.

---

## 4. Decisiones y alternativas

| # | Decisión | Conservadora | Moderada (elegida) | Radical | Evidencia |
|---|---|---|---|---|---|
| D1 | Algoritmo que consume aceptaciones | — | **Imitación / STaR** (entrenar lo verificado) | RL con la señal del verificador (GRPO/PPO) | exp037 `no_hack=True` (imitación no se hackea, **APOYADA**). exp020 (RL hackea) está **REFUTADA** (null de método); imitación-sobre-RL = precaución (literatura RL + exp017), NO hack medido. |
| D2 | Guardia de diversidad | sin guardia (lazo plano) | **dedup + replay limpio** (OBLIGATORIA) | regularización entrópica / KL a base | exp035 narrowing → exp036 guardia Pareto-domina (cobertura↑, precisión↑); exp039 sube e\* 0.15→0.50. |
| D3 | Filtro de aceptación | aceptar todas (naive) | **sólo `ok is True`; `ok is None` no entrena** | proxy auto-generado como fitness | exp016 `naive_all` no mejora; restricción dura (nunca proxy como fitness); exp046 abstención sube precisión. |
| D4 | Gate de avance | sobre el mismo pool (circular) | **held-out rotativo + committee + rollback** | sin gate (confiar en el filtro) | `H-SELF-2` (evaluar sobre la DB auto-escrita = colapso); anti-Goodhart CYCLE 12-21. |
| D5 | Costo de verificación multi-paso | externo en todo (caro) | **gating endógeno/externo por calibración estimada** | endógeno en todo (barato, colapsa si mal-calib) | exp046 MIXTA (endógeno colapsa mal-calibrado) → exp047 (**también MIXTA**): gating **no colapsa**, pero la separación por régimen es imperfecta (débil elige endo 33%). |
| D6 | Dónde entrena a escala | in-place en nodo (imposible) | **adapter LoRA en Kaggle GPU; fusión en cuenca** | re-pre-entrenar base completo | Restricción dura (sin PyTorch/QLoRA en nodos); FedAvg sólo adapters (exp003). |
| D7 | Temperatura de generación | baja (segura, poca diversidad) | **alta + guardia que la sostiene** | muy alta sin guardia (narrowing/ruido) | exp095 (**MIXTA**): con guardia, alta diversidad del generador *tiende* al óptimo (no concluyente). |

**Por qué la guardia (D2) es no-negociable.** Es el arreglo medido que convierte el lazo de un motor que
**tolera apenas** un verificador imperfecto (plano, e\*=0.0) en uno que **lo tolera** (e\* hasta ≈0.50,
exp039). La justificación load-bearing es **esa tolerancia al FP**, no el narrowing per se (a escala toy el
plano fue estable, exp035 `div_collapse=False`). Con un verificador con FP>0.15 (lo normal en código/hechos
reales, plano 04) el lazo **plano** se va a auto-degradación; la guardia es lo que lo hace **robusto al
verificador real**, no sólo al oráculo. (Trade-off honesto: la guardia es Pareto-dominante en el toy, pero
ese Pareto se **re-mide** en el dominio real, A-L2/A-L3; no se hereda.)

---

## 5. Plan de validación (cómo se mide que funciona)

El criterio maestro: **bootstrap medible de un base débil sin colapso**, replicando exp038 fuera del toy.

### 5.1 Métricas primarias (las del ledger, no inventadas)
- **Ganancia neta de bootstrap:** `final − base` (held-out disjunto). DoD si `> margin` y `non_decreasing`.
- **Plateau, no colapso:** la curva por ronda sube y **platea** (`plateaus=True`, `collapses=False` como
  exp038), no cae tras el pico.
- **Cobertura/diversidad:** `coverage_prompts` y `diversity_fraction` **no** caen bajo la inicial
  (guardia frena narrowing; exp036).
- **Sin reward-hack:** tasa de soluciones **degeneradas/echo** aceptadas = 0 (`no_hack` como exp037).
- **Tolerancia a FP:** barrer FP-rate inyectado del verificador y medir e\* con/sin guardia (réplica
  exp039: el `guarded` debe seguir positivo donde el `plain` ya colapsó).

### 5.2 Experimentos de validación (estilo expNNN, CPU)
- **A-L1 (réplica empaquetada):** correr `cognia_x/selfimprove/` sobre la tarea de expresiones con el
  `CodeVerifier`/`ClosedFormVerifier` reales del plano 04 (no el oráculo de juguete). **CHECK:**
  reproduce exp038 (base débil → techo, plateau, sin colapso) con el verificador **empaquetado**.
- **A-L2 (guardia ablada):** lazo CON vs SIN guardia, R≥6. **CHECK:** `plain_narrows=True`,
  `guard_keeps=True`, `no_prec_cost=True` (reproduce exp036). Si la guardia **no** ayuda en el dominio
  nuevo → re-calibrar `REPLAY_N`/dedup antes de comprometer.
- **A-L3 (FP-rate sweep):** inyectar FP en el verificador (0, 0.15, 0.30, 0.50) y medir net con/sin
  guardia. **CHECK:** `guard_raises_eps_star=True`; e\*_guarded ≥ 0.30 en el dominio objetivo (no se
  hereda el 0.50 del toy; se **mide**).
- **A-L4 (gate no-circular):** correr el lazo con el gate sobre held-out rotativo + committee; **plantar**
  una regresión (verificador con FP alto deliberado) y verificar que el gate **revierte** la ronda
  (`reverted=True`) y el monitor dispara la alarma. **CHECK:** el lazo **no** avanza a un estado peor.
- **A-L5 (multi-paso):** cadenas K=1..6 con presupuesto adaptativo + abstención + retry. **CHECK:** la
  accuracy de cadena mejora y el presupuesto adaptativo da ≥2× eficiencia (réplica parcial exp031 4.1×).

### 5.3 Verificación REAL end-to-end (no sólo pytest, método del repo)
Cerrar con CLI real: correr el lazo completo `N` rondas y **mostrar el output real** por ronda
(`step`, `cov`, `div`, `n_verified`, `gate`, `reverted`), terminando con un CHECK explícito de bootstrap
(`final − base > margin`, plateau, sin colapso). Incluir **un caso de colapso forzado** (verificador con
FP=0.6) que **debe** disparar el rollback + alarma — la prueba de que el anti-colapso funciona, no sólo el
camino feliz. Tests de regresión: uno que falle sin la guardia (narrowing detectable) y pase con ella; uno
que falle sin el gate (avanza a estado peor) y pase con él.

### 5.4 CPU vs Kaggle
- **CPU (i3):** todo el lazo toy + A-L1…A-L5 (numpy/torch-cpu, `generate_pool`/`train_arm` in-place).
  `torch.set_num_threads(3)` (= `cpu_count−1`), como exp016/exp047. Desarrollo y todas las ablaciones.
- **Kaggle GPU:** sólo el **paso de re-entrenar a escala real** (fine-tune de adapter LoRA sobre las
  salidas verificadas, pipeline `cognia_v3/training/kaggle/`). La **generación** y **verificación** a
  escala corren en CPU (llama.cpp+GGUF + sandbox del plano 04). El lazo a escala es **asíncrono por
  rondas**: generar+verificar en CPU → exportar el set verificado → entrenar adapter en Kaggle →
  re-importar adapter → siguiente ronda. **No medido aún** (ASUMIDO, riesgo R1).

---

## 6. Lo que NO está probado / riesgos

| # | Riesgo | Severidad | Estado | Mitigación |
|---|---|---|---|---|
| R1 | **Transferencia toy→escala.** Todo medido es d=64 byte-level / suma-expresiones; el lazo sobre 1-3B con adapters LoRA en Kaggle **no** está medido. | Alta | **ASUMIDO** | A-L1 con verificador real empaquetado primero; escalar gradualmente; el bootstrap está probado en pequeño con verificador real (exp038), no a 1-3B. |
| R2 | **e\* heredado del toy.** 0.15/0.50 son de exp017/exp039 (toy); el FP-rate real de código/hechos puede exceder e\* del dominio. | Alta | **Confianza media** | A-L3 mide e\* por dominio; el verificador (plano 04) debe garantizar FP < e\*_medido **antes** de comprometer el lazo; si no, el lazo **no** corre en ese dominio. |
| R3 | **Verificador con FP sistemático** (no aleatorio) enseña el error y se compone (exp017: pasado e\* colapsa). La guardia acota la **amplificación**, no el sesgo. | Alta | Inherente | Gate no-circular + committee + `verifier_id` versionado (plano 04 R3); dedup evita amplificar el FP correlacionado; A-L4. |
| R4 | **Gate circular por error de implementación** (held-out que se filtra al pool). El modo H-SELF-2. | Alta | Mitigado por diseño | Disjunción estricta `build_split`; shards rotativos; persistencia separada de la memoria auto-escrita; test de regresión de fuga. |
| R5 | **Colapso silencioso de diversidad** que precede a la caída de precisión (el monitor mira la métrica equivocada). | Media | Mitigado | Monitor sobre **diversidad+cobertura** (no sólo precisión); alarma a `0.5×` inicial (exp035); circuit-breaker §3.6. |
| R6 | **Gating endógeno mal-calibrado** se usa donde no debe y colapsa (exp046 MIXTA). | Media | Mitigado | Probe + umbral `calib_threshold=0.65` (exp047); ante duda, caer al externo (conservador). El ahorro endógeno depende del costo del verificador real (no medido a escala). |
| R7 | **Asincronía CPU↔Kaggle** introduce deriva (el adapter entrenado en Kaggle no encaja con el modelo que generó en CPU si cambió). | Media | **PENDIENTE** | Versionar base+adapter por ronda; fusión sólo dentro de la misma cuenca; medir deriva en A-L1 a escala. |
| R8 | **Multi-paso a escala** (presupuesto adaptativo/retry) no medido fuera del toy; el costo de verificación por paso puede dominar. | Media | ASUMIDO | Gating endógeno (D5) para abaratar; A-L5 mide eficiencia; abstención antes que adivinar. |
| R9 | **Sin combustible:** un base demasiado débil (acc≈0) no produce verificados → el lazo no arranca (exp016 exige base en banda [0.20,0.50]; exp038 arrancó de 0.081 **porque** el verificador real daba señal). | Media | Conocido | Calibrar el base a una banda bootstrappable; si `n_verified=0` persistente, el monitor para (ALARM_YIELD). |
| R10 | **Throughput de generar+verificar en CPU a escala.** Los timings toy (exp038 ~200 s/seed para 10 rondas con un modelo de 201k params) **NO transfieren**. A 3B Q4_K_M (~8 tok/s decode en el i3) generar `K=6 × N_PROMPTS=384 = 2304` completaciones/ronda + ejecutar el sandbox por candidato es una pared de wall-clock de **horas por ronda**. Las constantes K/N_PROMPTS/ROUNDS del toy son inviables tal cual a escala. | Media-Alta | **OMITIDO (añadido en verificación)** | Recortar drásticamente K/N_PROMPTS/ROUNDS a escala; gating endógeno (D5) para abaratar verificación; generación batcheada por longitud; medir tok/s real y costo de sandbox por candidato en A-L1 ANTES de comprometer ROUNDS; tratar el presupuesto de generación como recurso escaso (interactúa con R9). |

---

## 7. Definición de Hecho (DoD) + dependencias

### 7.1 DoD verificable
- [ ] `cognia_x/selfimprove/` con `loop.py` (bucle act-verify-keep-retrain), `guard.py` (dedup+replay),
      `gate.py` (`NonCircularGate`: held-out rotativo + committee + snapshot/rollback), `monitor.py`
      (diversidad/cobertura/yield + alarmas), `config.py`.
- [ ] El lazo **consume** el `VerifierRegistry`/`VerifyResult` del plano 04 (no reimplementa verificación;
      `ok is True` entrena, `ok is None`/`False` no).
- [ ] **Guardia OBLIGATORIA activa por defecto** (dedup + `REPLAY_N` semilla-verdad); ablación A-L2
      reproduce `plain_narrows / guard_keeps / no_prec_cost` (exp036).
- [ ] **Bootstrap medible sin colapso** (el DoD nuclear): sobre la tarea con verificador real, base débil →
      techo, `non_decreasing`, `plateaus=True`, `collapses=False`, cobertura no cae (réplica exp037/038).
- [ ] **e\* medido por dominio** (A-L3): `guard_raises_eps_star=True`; el lazo sólo se habilita donde el
      verificador (plano 04) garantiza FP < e\*_medido.
- [ ] **Gate no-circular demostrado** (A-L4): regresión plantada → ronda **revertida** + alarma; held-out
      rotativo disjunto; persistencia separada (db_pool o JSON append-only).
- [ ] **Multi-paso** (A-L5): cadena mejora; presupuesto adaptativo da ≥2× eficiencia; abstención/retry
      operativos; gating endógeno/externo no colapsa (exp047).
- [ ] **Verificación REAL (CLI):** corrida completa con output por ronda + CHECK de bootstrap, **incluido
      el caso de colapso forzado** que dispara rollback. Sin mocks.
- [ ] Tests de regresión (sin-guardia→narrowing falla / con-guardia pasa; sin-gate→avanza-peor falla /
      con-gate pasa); suite dirigida verde (`venv312\Scripts\python.exe -m pytest cognia_x/selfimprove/tests -q`).
- [ ] Entrada en `MANAGER_LOG.md` + commit enfocado con cómo-se-verificó.

### 7.2 Dependencias
- **Plano 04 (PRIMERO, orden Apéndice A):** `cognia_x/verify/` (`VerifierRegistry`, `VerifyResult`,
  gate/hooks `evidence["fingerprint"]`, `replay_eval`). El lazo **no construye** sin un verificador cuyo
  FP-rate esté medido < e\*. **Esta es la dependencia bloqueante.**
- **Existentes (verificadas):** `cognia_x/experiments/exp016/exp018` (`build_base/generate_pool/train_arm`,
  `addition_task`/`expression_task`), `cognia_x/model/hybrid.py` (`HybridLM`), `venv312` (Python 3.12).
- **Plano 02 (backbone):** provee el modelo a escala (HybridLM/GGUF) que el lazo mejora; el lazo trata el
  modelo como caja `generate()`+`forward(x,y)→loss`.
- **Kaggle GPU:** `cognia_v3/training/kaggle/` para el fine-tune de adapter a escala (los nodos no
  entrenan; restricción dura). Infra opcional: `storage/db_pool.py` para ledgers; si no, JSON append-only.

### 7.3 Riesgos de cierre (resumen ejecutivo honesto)
El **algoritmo del lazo + guardia está demostrado de punta a punta en pequeño**, incluida la
generalización a un **verificador-sandbox real** (exp037), el **bootstrap base-débil→techo-alto sin
colapso** (exp038: 0.081→0.933, plateau) y la **tolerancia a FP** que la guardia compra (exp039: e\*
0.0→0.50) — **confianza alta en dirección, media en constantes**. Lo no probado es la **escala** (1-3B,
LoRA en Kaggle, dominio código/hechos con suites reales) y la **asincronía CPU↔Kaggle** (R1/R7), ambas
ASUMIDAS. La **dependencia bloqueante es el plano 04**: el lazo amplifica lo que el verificador acepta —
si el FP-rate del verificador real no está medido y < e\*, **no encender el lazo**, porque un verificador
sesgado convierte el motor de auto-mejora en un motor de auto-degradación (R3). La guardia es **obligatoria
y no negociable**: es lo que hace el motor robusto a un verificador imperfecto.

**Rama de fallback (qué hacer si la escala no transfiere).** Si A-L1 muestra que el lazo **no** bootstrappea
a 1-3B (R1), o si la asincronía CPU↔Kaggle introduce deriva inmanejable (R7), o si el throughput de
generar+verificar en CPU es prohibitivo (R10): **degradar a fine-tune por lotes OFFLINE** — curar un set
verificado **una vez** (no online por rondas), entrenar el adapter LoRA en Kaggle, evaluar con el mismo gate
no-circular, y desplegar sin lazo iterado. En el peor caso, el sistema **sigue siendo útil sin
auto-mejora**: GGUF base + verificador-gate + RAG doc-level (plano de aprendizaje continuo), que no depende
de este lazo. La auto-mejora iterada es una **mejora opcional sobre un sistema que ya funciona**, no un
prerequisito — el orden Apéndice A (verificador PRIMERO) garantiza ese piso.
