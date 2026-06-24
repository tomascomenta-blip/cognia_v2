# decomposition_tree.md — Árbol de descomposición raíz de Cognia-X (RESET v4)

> El artefacto que el prompt fundacional pedía como PRIMER paso y que no existía: la excavación
> recursiva de *"¿qué es realmente una inteligencia y por qué los enfoques actuales no llegan a la
> raíz?"*. Construido el 2026-06-24 por excavación multi-lente (6 lentes independientes) + auditoría
> adversarial por lente + síntesis, y **anclado contra el código del lab** (las lentes bajaron a los
> resultados reales y corrigieron 4 errores de fidelidad, ver §Correcciones). Conserva v1/v2/v3.
>
> Estatus de cada raíz: `convergente` (varias lentes bajan por caminos distintos = señal fuerte),
> `contestada` (lentes en conflicto), `síntoma` (degradada por la auditoría a capa intermedia).

## P0 — Marco (qué ES una inteligencia, podado a lo que sobrevivió a la auditoría)

> Una inteligencia es **un sistema auto-mantenido que, bajo recursos finitos y un mundo
> NO-estacionario, convierte experiencia escasa en competencia de predicción/control sobre
> situaciones nuevas — y para ello debe GENERAR su propio criterio de qué información importa.**

La pregunta-marco de cada lente ("¿es comprimir / predecir / adaptar / representar la raíz?") resultó,
según las 6 auditorías, un **proxy**. Detrás de los 6 árboles late un único hueco que todos rodean y
ninguno nombraba: **no existe una función de valor endógena que defina qué es "útil".**

## Las raíces (el árbol podado)

### R-VALOR — RAÍZ PRIMERA (convergente, 5/6 lentes)
**Ausencia de una teleología / función-de-valor ENDÓGENA que asigne valor a la información respecto de
un objetivo que el sistema persigue en el tiempo.**
- Baja de: predicción-compresión (utilidad exógena→endógena), adaptación-recursos (criterio aprendido
  de relevancia une R1/R3/R4/R5), agencia-causalidad (objetivo bajo intervención/shift), memoria-binding
  (rate-distortion temporal dirigido por utilidad predictiva), abstracción (Goodhart / proxy mal-alineado).
- Por qué es la raíz: comprimir es asimétrico; escribir/olvidar es selectivo; asignar cómputo exige
  saber dónde importa; consolidar exige saber qué proteger. **Todas son indefinibles sin un escalar de
  valor.** El valor de una traza = su información mutua esperada con consultas/recompensas FUTURAS.
- **No la resuelve un "verificador externo":** las 6 lentes se rescatan apelando a un examinador externo
  — el atajo que critican. El lab SOLO demostró verificador externo (exp017); valor endógeno nunca.

### R-INTERVENCIÓN — convergente, fuerte  · **medida real en exp022 (CYCLE 35)**
**La estructura causal/invariante solo es identificable si la distribución generadora VARÍA — por
intervención do(X), múltiples entornos, o shift. Un corpus observacional fijo no la contiene (límite
INFORMACIONAL, no de capacidad).**
- Baja de: predicción-compresión R1, agencia RAIZ-1, adaptación R5 (no-estacionariedad).
- Corrección verificada: do(X) **NO requiere cuerpo** — un verificador-que-ejecuta ya es intervención
  (exp020 corre un lazo GRPO acción→consecuencia→update).
- **CYCLE 35 (exp022):** una política PASIVA sobre un corpus confundido queda **PLANA** bajo intervención
  por más presupuesto que reciba (flatness ~0.013); solo las políticas que INTERVIENEN cruzan a ~1.0.
  → R-INTERVENCIÓN pasa a techo **real** en el ledger.

### R-PRIOR — convergente, fuerte (la raíz mejor defendida adversarialmente)
**La inducción desde k ejemplos es sub-determinada (no-free-lunch): un prior fuerte es matemáticamente
necesario; su CALIDAD (no su forma) fija la eficiencia muestral.**
- "Programa más corto / MDL / búsqueda de programas" es UNA apuesta de diseño (incomputable, NFL), no la
  raíz. Lo irreducible: hace falta un prior fuerte y bien elegido; de dónde sale (evolución/desarrollo/
  cultura) es la rama ausente. Tensión exploración-de-estructura ↔ prior: explorar tiene costo muestral
  combinatorio que ningún sustrato evita salvo que el prior lo pode.

### R-SUSTRATO/CRÉDITO — contestada (núcleo sobrevive)
**El compromiso con asignación de crédito GLOBAL-diferenciable (backprop denso) se cuela sin
cuestionarse (supuesto colado #1 en 5/6 lentes).**
- Contestación dura (verificada como deriva): "online ⇒ local" y "backprop no puede online" se refutan
  con H-BIO-3 del lab (predictive-coding ~100× más caro en CPU). Lo que sobrevive: el sustrato
  denso-**síncrono** lo impone la ECONOMÍA DEL ENTRENAMIENTO (batch grande, compute-bound), no backprop
  per se. El falso dilema continuo-vs-discreto NO sobrevive.

### R-CAPACIDAD (techo de recall = d²) — SÍNTOMA, refutado por el propio lab
**Anclar la raíz en el techo de recall = d²/pigeonhole es citar un bound que el lab YA refutó**
(exp010: 16× el estado → +0.0003; Tipo D, suposición heredada). La raíz real debajo es R-VALOR (qué
vale la pena escribir) + el costo de optimización.

### R-COSTO-FÍSICO (bytes/token) — SÍNTOMA de régimen
Verificado (exp004/006) pero **acotado a inferencia batch-1-CPU**; a batch grande (donde se decide el
sustrato) es compute-bound (óptimo opuesto). "Landauer" estaba mal etiquetado (transporte ~pJ/bit, no
borrado). Es síntoma del lock-in económico hardware-software-incentivos.

## EL VERDADERO PRIMER PROBLEMA: R-VALOR
La ausencia de una función-de-valor **endógena** — un criterio, generado por el propio sistema
persiguiendo un objetivo en un mundo no-estacionario, de qué información merece predecirse, escribirse,
recordarse u olvidarse. Es la raíz que, resuelta, **desbloquea las demás a la vez**: cada raíz superior
es un caso de R-VALOR sin un valor que la aterrice.

> **Honestidad de confianza:** que R-VALOR sea la convergencia = confianza **ALTA** (5/6 lentes, robusto
> a auditoría). Que sea **resoluble** (que un valor endógeno sea construible y no solo otra reetiqueta de
> "meta externa") = confianza **BAJA**; es lo que el reset debe atacar empíricamente.

## Veredicto sobre la deriva (tesis previa del lab)
**"Bytes-por-token / híbrido" es un SÍNTOMA, no una raíz.** (1) Eficiencia sobre la familia conocida.
(2) Diagnosticada desde el régimen equivocado (inferencia batch-1; el sustrato se decide en
entrenamiento, compute-bound). (3) Síntoma del lock-in económico. El híbrido optimiza el transporte
dentro de un mínimo local; **no toca ninguna de las 3 raíces convergentes**. Sobrevive como restricción
de **viabilidad** (todo corre en CPU finita), NO como dirección a la raíz.

**Qué sobrevive de los 34 ciclos:** exp017 (verificador externo funciona — reinterpretado: marca dónde
está el hueco), exp001/004/006 (viabilidad CPU), exp010+C-02 (el lab ya refutó d² — honestidad
anti-Goodhart), y la **metodología research-as-code** (el activo más valioso). **Qué queda en cuestión:**
la tesis central como rumbo; toda raíz anclada en d²; las conclusiones de exp019/020 sobre reward-hack
(refutadas, citadas al revés por una lente); el rival nunca entretenido **inteligencia = control/acción**
(active inference / empowerment).

## Hipótesis v4 (backlog del reset)
- **H-V4-1 · P0** — valor endógeno (info-gain) vs predicción pasiva, bajo intervención, sin verificador
  externo. → **exp022/CYCLE 35: MIXTA** (R-INTERVENCIÓN demostrada; valor-específico no aislado).
- **H-V4-1b · P0** (hija) — aislar info-gain vs azar-activo en régimen presupuesto-chico / ruido-alto /
  espacio-grande (donde el azar NO alcance).
- **H-V4-2 · P0** — identificabilidad causal SIN cuerpo: el brazo que interviene recupera la dirección
  que el pasivo con 100× más datos no puede (SCM de juguete).
- **H-V4-3 · P1** — calidad del prior > forma: equivarianza correcta iguala a MDL a fracción del costo.
- **H-V4-4 · P1** — limpieza de deriva: techo de recall es de optimización (currículo mueve el plateau).
- **H-V4-5 · P1** — escribir≡olvidar (rate-distortion dirigido por valor); quitar la utilidad mata la
  ventaja (ablación que ata la memoria a R-VALOR).
- **H-V4-6 · P2** — limpieza: reward-hack no es la barrera temida (exp019/020 refutadas).

## Correcciones de fidelidad que la auditoría cazó contra el código (no inventar, verificar)
1. El techo de recall = d² estaba refutado por exp010 (16× estado → +0.0003); citarlo como raíz es deriva.
2. "No hay do() en el repo" es FALSO: exp020 corre un lazo GRPO acción→consecuencia→update.
3. La lente agencia citó exp019/020 (REFUTADAS) como si confirmaran el reward-hack.
4. "Backprop es la patología / local es la cura" contradice H-BIO-3 (predictive-coding ~100× más caro en CPU).

## Las 6 lentes (entradas de excavación)
predicción-compresión · adaptación-bajo-recursos-finitos · agencia/causalidad/objetivos ·
física/termodinámica/eficiencia · abstracción/generalización-muestra-eficiente ·
memoria/representación/binding/tiempo. Detalle adversarial por lente: ver `research_log.md` (CYCLE 35) y
el journal del workflow `cogniax-v4-decomposition-tree`.
