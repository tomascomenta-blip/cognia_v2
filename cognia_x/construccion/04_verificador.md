# 04 — Infraestructura de verificadores real-chequeables (la pieza de 1ra clase)

> **Propósito.** Especificar el subsistema **más demostrado del lab y el PRIMERO a construir**: una
> infraestructura de **verificadores por dominio** que deciden, de forma *chequeable* (ejecutando,
> calculando o corroborando — nunca opinando), si un candidato generado es correcto. Define la
> **interfaz común** `verify(candidato) → {ok, confianza, evidencia}`, los tres verificadores de
> arranque (código→sandbox, forma-cerrada→cálculo exacto, hechos→redundancia ≥2 fuentes), la
> **calibración + abstención** (saber cuándo no se sabe), **cómo medir el FP-rate real** de cada uno,
> y el **gate NO circular** que protege el lazo de auto-mejora (plano 05). El lever dominante de todo
> el sistema es la **CALIDAD** del verificador (FP-rate efectivo < e\*); este plano lo hace medible y
> defendible.

> **Anclaje de fuentes (verificado, no asumido):**
> - Código que corre hoy: `cognia_v3/core/sandbox_tester.py` (`SandboxTester.test_module_from_code`),
>   `cognia_v3/interfaces/code_executor.py` (`validate_python`, `run_python`,
>   `validate_generated_module_imports`, `BLOCKED_IMPORTS_PYTHON`, `ALLOWED_IMPORTS_GENERATED`,
>   `TIMEOUT`).
> - Evidencia experimental propia: `cognia_x/experiments/exp018_real_verifier/` (H-LEARN-3 **APOYADA**,
>   CYCLE 31), `exp017_noisy_verifier` (H-LEARN-2 **APOYADA**, curva FP→colapso, CYCLE 30).
> - **ADVERTENCIA (corrección del verificador adversarial):** `exp019_reward_hack` (H-LEARN-4) y
>   `exp020_rl_vs_imitation` (H-LEARN-5) están **REFUTADAS** en el ledger (`results.json:status="refutada"`),
>   NO apoyadas. exp019: el verificador débil **NO se hackeó aun con el atajo sembrado** (degenerate
>   weak=0.085 ~ strong=0.004) → "no explotable a esta escala". exp020: RL-maximización **NO se separó**
>   de imitación (rl_weak=0.059 ~ imit_weak=0.115) → "el hack NO se demuestra con GRPO-lite a este tamaño".
>   Por tanto, las afirmaciones "RL hackea / imitación no" y "el verificador débil es explotable" son un
>   **riesgo TEÓRICO/de literatura NO reproducido en el toy del lab**, no un resultado medido. La elección
>   de imitación (D1) sigue siendo correcta como **precaución**, pero NO está demostrada empíricamente por
>   exp019/020. El motor del verificador se sostiene en exp017+exp018 (ambas apoyadas), no en exp019/020.
> - Gobernanza: `00_READINESS.md` (GO CONDICIONADO; orden Apéndice A: verificador → lazo → expertos),
>   `01_arquitectura_sistema.md` (este verificador es la caja `VERIFICADOR` del flujo).

---

## 1. Propósito y alcance

### 1.1 Qué resuelve
- Da al sistema una **fuente de verdad ejecutable** por dominio: un candidato no se acepta porque "suena
  bien", sino porque **corre y pasa tests** (código), **calcula el valor exacto** (forma cerrada) o
  **coincide con ≥2 fuentes independientes** (hechos). Esto es lo que el lab probó que convierte
  orquestación en mejora real (Apéndice A; `00_READINESS.md §C2`).
- Expone **una interfaz común** para que el lazo de auto-mejora (plano 05), el router de bandas
  (plano 01 §router) y el director de expertos (fase tardía) consuman verificación sin conocer el
  dominio interno.
- Hace **medible la calidad** del verificador (FP-rate por dominio) y la convierte en el **gate** que
  el lazo respeta — con **abstención calibrada** cuando el verificador no está seguro.

### 1.2 Qué NO cubre (se delega)
- El **lazo STaR** que consume las aceptaciones (imitación, guardia de diversidad, dedup+replay como
  *política de entrenamiento*) → **plano 05**. Aquí sólo se define el **gate** y el **hook de guardia**
  que el lazo invoca.
- La **inyección de hechos nuevos** (RAG doc-level vs LoRA vs kNN-LM, gate G3) → plano de aprendizaje
  continuo. El `FactVerifier` de aquí **consume** el índice de recuperación; no decide la política de
  inyección.
- El **backbone** que genera los candidatos → plano 02.

### 1.3 Alcance honesto
Lo demostrado es **DEMOSTRADO-PEQUEÑO** (toy byte-level, `HybridLM` d=64, aritmética/expresiones). La
transferencia del verificador de **forma cerrada** (exp018) al verificador de **código real** (suite de
tests Python sobre funciones de varias líneas) y a **hechos** está **ASUMIDA**, no medida. Las
constantes de umbral (e\*, τ de abstención) son **confianza media**: citadas del ledger toy, se
**re-miden** sobre conjuntos *gold* del dominio real (§5). SCALE = 0%.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe | Corre | Cita |
|---|---|---|---|
| Sandbox de código (AST + blocklist + allowlist + subprocess+timeout) | Sí | Sí | `cognia_v3/core/sandbox_tester.py` + `cognia_v3/interfaces/code_executor.py` |
| Allowlist de imports para código auto-generado (regla 9) | Sí | Sí | `code_executor.validate_generated_module_imports` (AST, rechaza relativos) + `ALLOWED_IMPORTS_GENERATED` (29 módulos stdlib) |
| Blocklist de imports peligrosos | Sí | Sí | `code_executor.BLOCKED_IMPORTS_PYTHON` (os.system, subprocess, socket, ctypes, pickle, …) + `__import__` |
| Ejecución aislada con env limpio + timeout | Sí | Sí | `code_executor.run_python` (subprocess, `PYTHONPATH=""`, `HOME/TMPDIR=tempdir`, `TIMEOUT["python"]=15s`, `MAX_OUTPUT_CHARS=4000`) |
| Verificador de forma cerrada chequeable (intérprete propio, sin `eval`) | Sí (toy) | Sí | `exp018_real_verifier/expression_task.py:interpret/verify` (gramática `NUM \| a OP b`, allowlist `b"0123456789+*"`) |
| Evidencia: el verificador ES el motor de la auto-mejora | Sí | Sí | exp018 APOYADA: verified 0.848 vs naive 0.668 (base 0.719, **+0.130**, 3 seeds, margen 0.105) |
| Evidencia: FP-rate decide (dosis-respuesta) | Sí | Sí | exp017 (H-LEARN-2): el net-sobre-base decae con la tasa de FP; existe eps\* > 0 |
| ~~Evidencia: verificador débil es explotable SI el atajo está en el repertorio~~ | **No** | — | exp019 (H-LEARN-4) **REFUTADA**: el débil **NO** se hackeó aun con el atajo sembrado (weak=0.085 ~ strong=0.004) → no explotable a esta escala. Es riesgo teórico, no medido. |
| ~~Evidencia: imitación NO se hackea, RL-maximización SÍ~~ | **No** | — | exp020 (H-LEARN-5) **REFUTADA**: RL **NO** se separó de imitación (rl=0.059 ~ imit=0.115); "el hack NO se demuestra con GRPO-lite a este tamaño". La preferencia por imitación es **precaución/literatura**, no demostrada aquí. |
| Verificadores con **interfaz común** `verify()` unificada | **No** | — | Este plano la define (`cognia_x/verify/`) |
| `FactVerifier` (redundancia ≥2 fuentes) | **No** | — | Diseño nuevo aquí; consume el índice de recuperación (plano continual) |
| Calibración + abstención formalizadas como subsistema | **No** | — | Existe en toy (exp046 abstención calibrada, CYCLE 46); falta empaquetarlo aquí |

**Lectura honesta.** El **núcleo del verificador de código existe y corre** (sandbox real, no mock).
Lo que falta es (a) **unificar** los tres dominios bajo una interfaz, (b) **el verificador de hechos**,
y (c) **calibración/abstención + medición sistemática de FP-rate** empaquetadas como subsistema. NO se
parte de cero: se **envuelve** `code_executor`/`sandbox_tester` y se **porta** `interpret()` de exp018.

### 2.1 Una trampa real ya cazada en el código (no repetirla)

`sandbox_tester.py` (líneas 47-58) documenta que `run_python().success` **exige stdout no vacío**
(`code_executor.py:423`). Un módulo que sólo **define una clase/función no imprime nada** → `success`
sería `False` aunque el código sea correcto. `sandbox_tester` lo corrige redefiniendo "ejecuta" como
`exit_code==0 AND not timed_out AND not stderr`. **Lección de diseño:** el criterio `executes` ≠
`success`. El `CodeVerifier` de este plano **no debe** colgar su `ok` de `success`; debe colgar de
*"la suite de tests pasó"*, que es una señal **positiva** explícita (no la ausencia de salida).

---

## 3. Diseño detallado

### 3.1 La interfaz común — `VerifyResult` y el protocolo `Verifier`

Ubicación: `cognia_x/verify/base.py`. Estilo: dataclass plana + protocolo (igual densidad que
`code_executor.ExecutionResult`). Sin frameworks.

```python
# cognia_x/verify/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Protocol

@dataclass
class VerifyResult:
    """Salida UNIFICADA de cualquier verificador de dominio."""
    ok: Optional[bool]          # True=acepta, False=rechaza, None=ABSTIENE (no sabe)
    confidence: float           # [0,1] calibrada: P(candidato correcto | señales del verificador)
    evidence: dict              # trazas REALES y auditables (NO opinión del modelo)
    domain: str                 # "code" | "closed_form" | "fact"
    verifier_id: str            # nombre+versión, p.ej. "code@1" (para auditar regresiones)
    cost_ms: float = 0.0        # presupuesto gastado (decide retry/abstención en el lazo)
    abstained: bool = False     # True sii ok is None
    warnings: list = field(default_factory=list)

class Verifier(Protocol):
    domain: str
    def verify(self, candidate: dict) -> VerifyResult: ...
    def fp_rate(self) -> Optional[float]: ...   # FP-rate medido más reciente (None si sin calibrar)
```

**Contrato del `candidate` (dict, no clase, para no acoplar dominios):**
- `code`: `{"task_id", "code": str, "tests": str|list, "entrypoint": str, "lang": "python"}`.
- `closed_form`: `{"prompt": bytes|str, "answer": bytes|str}` (p.ej. `b"12="`, `b"3*4"`).
- `fact`: `{"claim": str, "query": str, "min_sources": int}`.

**Reglas duras del contrato (innegociables, del método del lab):**
1. `evidence` contiene **trazas ejecutables/recuperadas REALES** (stdout/stderr, valor calculado, IDs de
   fuentes), nunca un juicio del LLM. "Código que corre o no cuenta."
2. `verify()` **nunca lanza**: todo error interno → `ok=False` (o `None` si es indecisión genuina) con
   el traceback en `evidence["error"]`. Un verificador que crashea es un verificador que acepta basura
   por la rama de excepción — el modo de fallo más peligroso (ver `interpret()` de exp018, que captura
   todo y devuelve `(None, False, False)`).
3. `confidence` es **calibrada** (§3.6), no un score crudo. El lazo (plano 05) usa
   `confidence` para asignar presupuesto/abstención.

### 3.2 `CodeVerifier` — sandbox subprocess + tests + timeout

Ubicación: `cognia_x/verify/code_verifier.py`. **Envuelve** lo que ya corre; no reimplementa el sandbox.

Pipeline (orden de compuertas, barato→caro, igual que `sandbox_tester`):
1. **Sintaxis** (`validate_python` → AST). Falla ⇒ `ok=False`, `confidence` baja, `evidence` con el
   `SyntaxError`. No se gasta subprocess.
2. **Blocklist** (`BLOCKED_IMPORTS_PYTHON` vía `_scan_blocked_imports` + `__import__`). Falla ⇒ rechazo
   duro (seguridad), `ok=False`.
3. **Allowlist** (`validate_generated_module_imports` → AST, rechaza imports no previstos y relativos).
   Para código de tarea (no auto-generado de infra) la allowlist puede ampliarse por dominio; por
   defecto se usa `ALLOWED_IMPORTS_GENERATED`. Falla ⇒ `ok=False`.
4. **Ejecución de la SUITE DE TESTS** en subprocess aislado con timeout. **Aquí está la diferencia con
   `sandbox_tester`**: no ejecutamos "el módulo a ver si imprime"; **ensamblamos** `code + harness + tests`
   y exigimos que el harness imprima un **veredicto estructurado** (`PASS k/n`). El `ok` cuelga de los
   tests, no de stdout-no-vacío (evita la trampa §2.1).

```python
# pseudocódigo del paso 4 (harness determinista, sin pytest para no acoplar deps)
HARNESS = '''
import json, sys
{candidate_code}
{tests_code}            # define TESTS = [(args, expected), ...] o funciones test_*
_p, _n = 0, 0
for _name, _fn in [(k,v) for k,v in dict(globals()).items() if k.startswith("test_")]:
    _n += 1
    try:
        _fn(); _p += 1
    except Exception as _e:
        print("FAILDETAIL", _name, repr(_e), file=sys.stderr)
print("VERDICT", json.dumps({"passed": _p, "total": _n}))
'''
res = run_python(HARNESS.format(...), timeout=CODE_TIMEOUT_S)   # code_executor.run_python
# parsear la línea VERDICT del stdout; ok = (passed == total and total > 0)
```

- **Timeout:** `CODE_TIMEOUT_S` (config, default 15s = `TIMEOUT["python"]`). En el i3 (2c/4t) el
  subprocess compite por cores; el timeout protege contra loops infinitos (modo de fallo real).
- **`confidence` (propuesta, confianza media):** `passed/total` ajustado por **cobertura** de la suite:
  `confidence = (passed/total) * coverage_factor`, donde `coverage_factor∈(0,1]` penaliza suites
  triviales (1 sólo test, sin edge cases). Si `passed<total` ⇒ `ok=False`. Si `passed==total` pero
  `total<min_tests` ⇒ `ok=None` (**abstención**: la suite es demasiado débil para afirmar, ver §3.6).
  *No medido aún sobre código real; se calibra en §5.*
- **`evidence`:** `{"verdict": {passed,total}, "stderr": "...", "exit_code", "timed_out", "imports_blocked"}`.

**Por qué esto *debería* bloquear el reward-hack del dominio código (conjetura de diseño, NO medida):**
el atajo análogo al "echo" de exp018 es *"código que pasa una suite débil sin resolver la tarea"*. La
defensa propuesta es la **cobertura/fuerza de la suite** (= el "strong verifier" de exp018 que exige
operador) + **casos ocultos/aleatorizados (held-out)** que el candidato no vio. **CAVEAT FUERTE
(corrección):** el reward-hack **NO se reprodujo** en el toy del lab: exp019 (H-LEARN-4) está **REFUTADA**
(el débil no se hackeó ni con el atajo sembrado) y exp020 (H-LEARN-5) está **REFUTADA** (RL no se separó
de imitación). O sea: a escala toy ni la imitación ni el RL descubrieron el atajo, así que **no hay
evidencia propia de que (a) el hack emerja, ni (b) que el "strong"/held-out sea necesario** — es un riesgo
teórico (literatura RL + exp017 dose-response, que sí muestra que un FP sistemático colapsa) que el diseño
hedge-ea por precaución. La eficacia de la cobertura/held-out contra el hack se **mide en código** en A-V1,
no se asume. (Confianza media-baja; análogo a un hack que el lab aún no observó.)

### 3.3 `ClosedFormVerifier` — chequeo exacto (sin `eval`)

Ubicación: `cognia_x/verify/closed_form_verifier.py`. **Porta** `interpret()` de
`exp018_real_verifier/expression_task.py` a un verificador de propósito general.

- **Intérprete propio, NUNCA `eval()`** (regla 9): parser de gramática acotada
  (`NUM | a OP b`, allowlist de chars), extensible a `{+,-,*,//,%}` y comparaciones. Computa el valor y
  compara contra el target. `well_formed=False` ⇒ rechazo; cualquier char fuera del allowlist ⇒ rechazo.
- **Modo `strong` (default):** exige **computación real** (usa operador), bloquea el **echo** del target.
  Modo `weak` sólo para A/B de calibración (medir el FP que el strong cierra). Esta dicotomía es **la
  medición directa del FP-rate** (§5): el echo es un FP conocido y plantable.
- `ok = (val == target and (has_op if strong else True))`. `confidence` ≈ **1.0/0.0** (verificación
  exacta, no ruidosa) — salvo ambigüedad de parseo, donde abstiene. Es el verificador **más confiable**
  y el patrón a imitar.
- **`evidence`:** `{"parsed": "3*4", "value": 12, "target": 12, "has_op": true}`.

### 3.4 `FactVerifier` — redundancia ≥2 fuentes (diseño nuevo, sin exp propio)

Ubicación: `cognia_x/verify/fact_verifier.py`. **Confianza media** (apoyado en literatura de
RAG/auto-consistencia, sin experimento propio del lab — declararlo).

- **Principio:** un hecho se acepta sólo si **≥`min_sources` (default 2) fuentes independientes** lo
  corroboran. "Independientes" = distinto documento/origen tras dedup por near-duplicate (un mismo texto
  copiado en 3 sitios = 1 fuente, no 3). Consume el **índice de recuperación doc-level** del subsistema
  de aprendizaje continuo (RAG, base congelada, cero datos personales centralizados; ruido DP en
  cliente — restricción dura).
- **Pipeline:** recuperar top-k pasajes para `query` → extraer la aserción candidata de cada uno →
  **NLI/entailment ligero o coincidencia normalizada** entre el `claim` y cada pasaje → contar fuentes
  que *entail* (no sólo que mencionan) → `support = #fuentes_independientes_que_entail`.
- `ok = support >= min_sources`; si `support==0` ⇒ `ok=False`; si `1 <= support < min_sources` ⇒
  `ok=None` (**abstención**: evidencia insuficiente, no contradicción). Si fuentes se **contradicen** (unas
  entail, otras refutan) ⇒ `ok=None` con `evidence["conflict"]=True`.
- `confidence ≈ support / (support + refutes + 1)` (laplaciano; **propuesta, no calibrada**).
- **CPU-first:** el matcher de entailment debe correr en el i3 (embeddings/coincidencia, no un LLM
  pesado por pasaje). Decisión conservadora: empezar con **coincidencia léxica normalizada + numérica**
  (fechas/cifras), subir a NLI sólo si el FP-rate lo exige.
- **`evidence`:** `{"support": 2, "sources": ["docA#12","docC#3"], "snippets": [...], "conflict": false}`.

> **Riesgo declarado (alto):** 2 fuentes que repiten el **mismo error** (sesgo de corpus) pasan el gate.
> La redundancia acota el ruido independiente, **no** el error sistemático. Mitigación parcial: exigir
> **diversidad de origen** (distinto dominio/autor) y marcar `confidence` bajo si las fuentes comparten
> linaje. No resuelto; es el límite estructural del verificador de hechos.

### 3.5 El registry/dispatcher y la abstención de sistema

Ubicación: `cognia_x/verify/registry.py`. Concreto: un dict de dominio→verificador (igual que los
registries simples del repo).

```python
class VerifierRegistry:
    def __init__(self): self._v = {}              # domain -> Verifier
    def register(self, v: Verifier): self._v[v.domain] = v
    def verify(self, candidate: dict) -> VerifyResult:
        dom = candidate["domain"]
        v = self._v.get(dom)
        if v is None:                              # dominio sin verificador chequeable
            return VerifyResult(ok=None, confidence=0.0, evidence={"reason":"no verifier"},
                                domain=dom, verifier_id="none", abstained=True)
        return v.verify(candidate)
```

**Abstención como ciudadana de primera clase (exp046, CYCLE 46 — abstención calibrada):** un dominio
**sin** verificador chequeable **abstiene** (`ok=None`), **no** inventa un proxy. Esto encarna la
restricción dura *"nunca proxy auto-generado como fitness"*. El lazo (plano 05) trata `ok=None` como
"no entrenar con esto" (ni positivo ni negativo), preservando precisión a costa de cobertura — el
trade-off que exp046 mostró que sube precisión.

### 3.6 Calibración y abstención (saber cuándo no se sabe)

Ubicación: `cognia_x/verify/calibration.py`.

- **Por qué calibrar:** el lazo usa `confidence` para decidir presupuesto/retry/abstención. Un score
  crudo (p.ej. `passed/total`) no es una probabilidad. Calibramos `confidence → P(correcto)` con
  **isotónica o Platt** sobre el conjunto *gold* (§5), midiendo **ECE** (Expected Calibration Error).
  *Nota del ledger:* el arco R-VALOR 149-155 cerró que el residuo del lazo real es **ranking**, no
  calibración; por eso aquí la calibración es **para la decisión de abstención** (umbral), no para
  "acelerar el loss". Usar como brújula decisional acotada (`00_READINESS.md §5.2`).
- **Umbral de abstención τ por dominio:** se acepta sólo si `confidence ≥ τ_dom`; entre `[τ_lo, τ]`
  abstiene; bajo `τ_lo` rechaza. τ se **fija para que el FP-rate efectivo quede < e\*** (§5), no a ojo.
- **Política de cobertura/precisión:** reportar la curva **precisión vs cobertura** al barrer τ; el dueño
  del lazo elige el punto. Para el verificador de forma cerrada τ es trivial (confianza ~binaria); para
  código y hechos es la palanca real.

### 3.7 La guardia que sube e\* (dedup + replay limpio) — hook, no política

El ledger midió que el **FP-rate efectivo tolerable** sube de **e\*≈0.15 sin guardia** a **≈0.50 con
guardia** (dedup + replay limpio, CYCLE 50/53; **confianza media**, toy). La **política** vive en el
lazo (plano 05), pero el verificador expone los **hooks** que la habilitan:
- `evidence["fingerprint"]`: hash normalizado del candidato aceptado (para **dedup** — no dejar que un
  mismo acierto domine el set y amplifique un FP correlacionado).
- Un método `replay_eval(model, holdout)` del subsistema: re-evalúa sobre un set **limpio held-out** para
  detectar deriva. Esto es **parte del gate no-circular** (§3.8).

### 3.8 El gate NO circular (defensa contra H-SELF-2)

El modo de fallo `H-SELF-2` de Cognia: **evaluar sobre la misma DB que el sistema se auto-escribe** →
el gate aprueba su propio ruido. Defensas duras de este plano:
1. **Disjunción de datos:** el set *gold* de calibración/medición de FP **y** el `holdout` de
   `replay_eval` son **DISJUNTOS** de todo lo que el lazo genera o escribe (igual que `build_split()` de
   exp018 parte targets train/test disjuntos). El verificador **nunca** se mide sobre candidatos que él
   mismo aceptó.
2. **Persistencia separada:** los ledgers de FP-rate/calibración usan `storage/db_pool.py` (**verificado
   presente en el repo** por el verificador adversarial; regla dura: sin `sqlite3.connect` directo); si por
   algún motivo no estuviera disponible, un JSON **append-only** (patrón `results.json` del lab). La DB de
   verificación **no** es la DB de memoria que el sistema auto-escribe.
3. **Verificador ≠ generador:** el verificador no comparte parámetros con el modelo que genera (es
   código/recuperación, no el LLM juzgándose). Esto es lo que distingue "verificador chequeable" de
   "auto-recompensa", la línea roja del lab.

### 3.9 Configuración concreta (sin constantes mágicas dispersas)

Ubicación: `cognia_x/verify/config.py` (un módulo, auditado — análogo a la disciplina de
`shattering/model_constants.py`). Valores iniciales **confianza media**, a re-medir en §5:

```python
CODE_TIMEOUT_S       = 15      # = code_executor.TIMEOUT["python"]; loops infinitos cortados
CODE_MIN_TESTS       = 3       # < esto y todos pasan -> ABSTIENE (suite demasiado débil)
FACT_MIN_SOURCES     = 2       # redundancia mínima
E_STAR_NO_GUARD      = 0.15    # FP-rate efectivo tolerable sin guardia (exp017; toy, media)
E_STAR_WITH_GUARD    = 0.50    # con dedup+replay (CYCLE 50/53; toy, media)
TAU_ABSTAIN          = {"code": 0.80, "closed_form": 0.99, "fact": 0.75}  # PROPUESTOS, calibrar §5
```

---

## 4. Decisiones y alternativas

| # | Decisión | Conservadora | Moderada (elegida) | Radical | Evidencia |
|---|---|---|---|---|---|
| D1 | Algoritmo que consume las aceptaciones | — | **Imitación/STaR** (entrena lo aceptado) | RL con la señal del verificador | **Precaución (literatura RL + exp017)**, NO exp020: exp020 (H-LEARN-5) está **REFUTADA** — RL **no** se separó de imitación a escala toy (el hack no se demostró). La moderada se elige porque imitar opera con un verificador imperfecto (FP < e\*), no porque el lab haya medido que RL hackea. |
| D2 | Verificador de código: criterio de `ok` | "el módulo no crashea" (`success`) | **suite de tests pasa** (`passed==total`, `total≥min`) | fuzzing + property-based | §2.1: `success` exige stdout — falso negativo en módulos sin print. La suite es señal positiva. |
| D3 | Verificador de forma cerrada | usar `eval()` | **intérprete propio acotado** (port de exp018) | DSL completo con sandbox | Regla 9 (sin `eval` arbitrario); exp018 ya lo demostró. |
| D4 | `FactVerifier` matcher | coincidencia léxica + numérica | **léxico→NLI ligero si el FP lo exige** | LLM-judge por pasaje | CPU-first (i3): LLM por pasaje es caro; sin exp propio ⇒ empezar barato. |
| D5 | Dominio sin verificador | aceptar con confianza baja | **ABSTENER (`ok=None`)** | proxy auto-generado | Restricción dura (nunca proxy como fitness); exp046 (abstención sube precisión). |
| D6 | Defensa anti-reward-hack | confiar en el lazo | **suite con casos held-out ocultos** (análogo "strong") | adversarial test-gen | Conjetura de diseño: exp019 (separar explotabilidad) está **REFUTADA** y el echo no emergió en exp018; la eficacia del "strong"/held-out **se mide en A-V1**, no está demostrada. |

**Por qué la moderada en D1 es la columna vertebral:** todo el subsistema asume **imitación**. Si en el
futuro se quisiera RL, el verificador **debe** ser ~perfecto en ese dominio (FP→0), porque RL **tiende a**
buscar y explotar cualquier FP (literatura de reward-hacking + el dose-response de exp017, donde pasado
eps\* el lazo colapsa). **Honestidad (corrección):** el lab **NO** demostró este hack en su toy —
exp020 está **REFUTADA** (RL no se separó de imitación) y exp019 también (el débil no se explotó). Por
tanto la moderada es una decisión **precautoria/de bajo costo**, no un veredicto empírico del lab. Aun así
es la correcta: imitar permite operar con un verificador imperfecto (FP < e\*) y no introduce el modo de
fallo de auto-recompensa que la línea roja del lab prohíbe.

---

## 5. Plan de validación (cómo se mide que funciona)

El lever es la **CALIDAD** → el plan **mide el FP-rate real de cada verificador**, no asume que es bajo.

### 5.1 Definición operativa de FP-rate (la métrica maestra del subsistema)
> **FP-rate = fracción de candidatos INCORRECTOS que el verificador ACEPTA** (`ok=True`).
> Es el peligroso (aceptar basura), no el falso-negativo (rechazar lo bueno). Se mide sobre un
> **conjunto *gold* etiquetado** (candidato, etiqueta correcto/incorrecto) **disjunto** del lazo (§3.8).

### 5.2 Cómo construir el *gold* por dominio (CPU, barato)
- **Código:** N tareas con (a) soluciones **correctas** y (b) soluciones **incorrectas plantadas**
  (off-by-one, hardcode del output esperado, retorno constante, loop infinito → mide el timeout). El
  FP-rate = cuántas incorrectas pasan la suite. **Métrica clave: FP vs fuerza/cobertura de la suite**
  (réplica directa del strong-vs-weak de exp018 en el dominio código).
- **Forma cerrada:** el *gold* ya existe (exp018): el **echo** es el FP plantado. **Matiz honesto:** en
  exp018 el `degenerate` quedó en 0 en **ambos** brazos (weak y strong), porque a esa escala el lazo de
  imitación **nunca descubrió el echo** (no porque el strong cerrara un FP que el weak dejaba pasar). El
  A/B weak-vs-strong, por tanto, **aún no ha medido** una reducción real del FP del echo; A-V1 debe
  **sembrar** el atajo en la generación (no sólo permitirlo en el verificador) para que el A/B sea
  informativo. NO afirmar "el strong lleva el FP a 0" como hecho medido.
- **Hechos:** *gold* de claims (a) corroborados por ≥2 fuentes reales y (b) **falsos plausibles** +
  (c) **medio-verdades** corroboradas por 1 sola fuente (deben **abstener**, no aceptar).

### 5.3 Experimentos de validación (nuevos, estilo expNNN, CPU)
- **A-V1 (código):** barrer fuerza de la suite (1 test trivial → k tests con held-out) y reportar la
  curva **FP-rate vs cobertura**. **CHECK:** existe un punto de cobertura donde FP < e\* (0.15 sin
  guardia). DoD parcial del CodeVerifier.
- **A-V2 (calibración):** sobre el *gold*, ajustar isotónica/Platt y reportar **ECE** + curva
  **precisión-cobertura** al barrer τ. **CHECK:** τ que da FP-efectivo < e\* con cobertura ≥ X%.
- **A-V3 (gate no-circular):** repetir el lazo de exp018 pero **midiendo el gate sobre el holdout
  disjunto** (ya es así en exp018: test held-out). **CHECK:** la aceptación medida en holdout no diverge
  de la medida en train (si diverge → fuga circular).
- **A-V4 (hechos):** FP-rate y tasa-de-abstención del `FactVerifier` sobre el *gold* §5.2.
  **CHECK:** abstiene en las medio-verdades (1 fuente), no las acepta.

### 5.4 Verificación REAL end-to-end (no sólo pytest, método del repo)
Cerrar con CLI real: correr cada verificador sobre 3-5 candidatos de muestra y **mostrar el output
real** (VerifyResult con su evidencia). Para `CodeVerifier`, ejecutar contra el sandbox de verdad
(`code_executor.run_python`), incluyendo un caso de **timeout real** (loop infinito) y un caso de
**import bloqueado** (`import os; os.system(...)`) → ambos deben dar `ok=False` con la evidencia
correcta. Tests de regresión: uno que falle sin el fix y pase con él, por verificador.

### 5.5 CPU vs Kaggle
- **Todo este subsistema corre en CPU** (i3): es subprocess + parseo + recuperación, no entrenamiento.
  Sin necesidad de GPU. El timeout (15s) es el presupuesto que protege los 2 cores.
- **Kaggle GPU** sólo entra cuando el **lazo** (plano 05) entrena el modelo con las aceptaciones; el
  verificador en sí no entrena nada.

---

## 6. Lo que NO está probado / riesgos

| # | Riesgo | Severidad | Estado | Mitigación |
|---|---|---|---|---|
| R1 | **Transferencia toy→real del verificador de código.** exp018 demuestra forma cerrada (d=64, byte-level), NO suites de tests sobre funciones Python reales. | Alta | **ASUMIDO** | A-V1/A-V3 lo miden antes de comprometer el lazo. |
| R2 | **e\*≈0.15 / 0.50 son del toy** (exp017 / CYCLE 50-53), no del dominio código/hechos. | Media | **Confianza media** | Re-medir e\* por dominio (§5); no heredar el número. |
| R3 | **Verificador buggy que induce sesgo.** Un verificador con un FP sistemático (no aleatorio) **enseña el error** al lazo y se compone (exp017: pasado eps\* colapsa). | Alta | Inherente | (a) FP-rate medido y monitoreado; (b) suite con held-out oculto; (c) `verifier_id` versionado para detectar regresiones; (d) la guardia (dedup+replay) acota la amplificación. |
| R4 | **`FactVerifier` sin exp propio**; 2 fuentes con el mismo error sistemático pasan. | Alta | **PENDIENTE** (literatura) | Diversidad de origen; `confidence` bajo si comparten linaje; abstención por defecto. NO resuelto. |
| R5 | **Reward-hack del dominio código** (código que pasa suite débil sin resolver). | Media | **NO reproducido en el toy** (exp019/exp020 **REFUTADAS**) | Cobertura/held-out (D6) — eficacia **a medir** en A-V1. OJO: que el hack no emergiera en el toy NO implica que no emerja a escala/dominio real; el riesgo sigue vivo como precaución (literatura + exp017 dose-response). |
| R6 | **Calibración no transfiere de distribución.** ECE bajo en *gold* puede no sostenerse en producción. | Media | Conocido | Monitoreo de calibración online sobre el holdout (A-V3); re-fit periódico. |
| R7 | **Crash del verificador = aceptar basura.** Una excepción no capturada en la rama equivocada. | Alta | Mitigado | Contrato §3.1.2 (`verify` nunca lanza; excepción → `ok=False`); test de regresión con input adversarial. |
| R8 | **Confianza/`confidence` propuesta sin validar** (fórmulas §3.2/§3.4). | Media | **Confianza baja** | Son placeholders hasta A-V2; la decisión usa τ calibrado, no la fórmula cruda. |

---

## 7. Definición de Hecho (DoD) + dependencias

### 7.1 DoD verificable
- [ ] `cognia_x/verify/` con `base.py` (`VerifyResult`, `Verifier`), `registry.py`, `code_verifier.py`,
      `closed_form_verifier.py`, `fact_verifier.py`, `calibration.py`, `config.py`.
- [ ] `CodeVerifier` envuelve `code_executor.run_python`/`validate_*` **sin reimplementar el sandbox**;
      `ok` cuelga de la suite de tests (no de `success`); maneja timeout e import-bloqueado.
- [ ] `ClosedFormVerifier` porta `interpret()` de exp018; **sin `eval`**; A/B weak-vs-strong reproduce
      el cierre del echo (FP→0).
- [ ] `FactVerifier` con redundancia ≥2 fuentes + abstención en 1-fuente/conflicto.
- [ ] **FP-rate medido y reportado** por dominio sobre *gold* disjunto (A-V1/A-V4); existe τ que da
      FP-efectivo < e\* con cobertura reportada (A-V2).
- [ ] **Gate no-circular** demostrado: medición sobre holdout disjunto (A-V3); persistencia vía
      `db_pool` o JSON append-only, separada de la memoria auto-escrita.
- [ ] **Verificación REAL** (CLI): output real de los 3 verificadores sobre muestras, incl. timeout real
      e import bloqueado, con CHECK explícito.
- [ ] Tests de regresión (uno por verificador, falla sin fix / pasa con fix); suite dirigida verde
      (`venv312\Scripts\python.exe -m pytest cognia_x/verify/tests -q`).
- [ ] Entrada en `MANAGER_LOG.md` + commit enfocado con cómo-se-verificó.

### 7.2 Dependencias
- **Existentes (verificadas):** `cognia_v3/interfaces/code_executor.py`, `cognia_v3/core/sandbox_tester.py`,
  `cognia_x/experiments/exp018_real_verifier/expression_task.py`, `venv312` (Python 3.12).
- **De otros planos:** índice de recuperación doc-level (plano de aprendizaje continuo / gate G3) para el
  `FactVerifier`; el **lazo STaR** (plano 05) es el **consumidor** — este plano debe estar listo PRIMERO
  (orden Apéndice A, `00_READINESS.md`).
- **Infra opcional:** `storage/db_pool.py` (**verificado presente en el repo**) para los ledgers; fallback
  JSON append-only si no estuviera disponible.

### 7.3 Riesgos de cierre (resumen ejecutivo honesto)
El **CodeVerifier** y el **ClosedFormVerifier** son **construibles sobre código que ya corre** y tienen
respaldo experimental directo para el **motor de auto-mejora** (exp018 H-LEARN-3 + exp017 H-LEARN-2, ambas
**apoyadas**) — **confianza alta en dirección, media en constantes**. **PERO la defensa anti-reward-hack
NO tiene respaldo propio:** exp019/exp020 (las que debían demostrar el hack y la ventaja de imitación sobre
RL) están **REFUTADAS** en el ledger — el hack no emergió en el toy. La cobertura/held-out y la elección de
imitación son **precaución de diseño**, a medir en A-V1, no resultados del lab. El **FactVerifier** es
**diseño nuevo sin exp propio** (confianza media-baja) y arrastra el riesgo estructural del error
sistemático de corpus (R4). La métrica maestra (FP-rate < e\*) es **medible y
está en el plan**, pero los umbrales concretos (e\*, τ, fórmulas de confianza) son **placeholders del
toy** que **sólo se vuelven defendibles tras A-V1…A-V4** sobre *gold* del dominio real. No comprometer
el lazo de auto-mejora (plano 05) con un verificador cuyo FP-rate aún no se midió.
