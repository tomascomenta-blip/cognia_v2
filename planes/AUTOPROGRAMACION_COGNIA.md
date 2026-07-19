# AUTOPROGRAMACIÓN — SUBIR EL TECHO DE CÓDIGO DE COGNIA

**Fecha:** 2026-07-19
**Estado:** G0 EN CURSO. G1-G4 PRE-REGISTRADOS — no ejecutar fuera de orden.
**Hardware:** Ryzen 5 9600X (6c/12t), 33.4 GB RAM, RTX 5060 Ti 16 GB, Windows 11.
**Backend medido:** llama-server en `127.0.0.1:8080`, sirviendo
`qwen2.5-coder-14b-instruct-q4_k_m` (14.77B, Q4_K_M, `n_ctx=8192` de 131072 de
entrenamiento). VRAM 15947/16311 MiB = 97.8% **[M]**.

**Pedido del dueño (2026-07-19):** *"quiero que programes cosas complejas con
Cognia"*, resuelto en dos decisiones suyas: **(1)** el sujeto es Cognia — hay que
subir SU techo, no que yo escriba features a mano; **(2)** el objetivo de
"complejo" es que **Cognia se modifique a sí misma**.

Convención de citas: **[V]** = leído en el código real. **[M]** = medido en esta
máquina, en esta sesión. **[?]** = no verificado, declarado como incógnita.

---

## 0. Resumen ejecutivo

- **El techo NO es el modelo. Es el harness.** Es el hallazgo que reordena todo
  el plan y contradice la hipótesis con la que se entró.
- Al `qwen2.5-coder-14b` se le pidió lo que el dueño llama complejo — task manager
  con SQLite, pila de undo, lenguaje de consulta y tests. **Lo entregó en 22.5 s:
  114 LOC, 13 funciones, `TestTaskManager` con 4 tests reales, undo funcional**
  **[M]**. Lo mató el sandbox y el intento se descartó sin un ciclo de reparación.
- El techo *observado* del corpus histórico es ridículamente más bajo que eso: de
  16 programas generados en toda la historia del repo, **3 corren**; el mayor que
  corre tiene **39 líneas únicas** (sus 78 LOC son un bloque duplicado literal)
  **[M]**. Esa brecha entre lo que el modelo produce y lo que el harness deja
  sobrevivir ES el problema.
- Por lo tanto **G0 no es infraestructura de relleno: es el trabajo**. Y arrastra
  un problema de seguridad activo que hay que cerrar sí o sí antes de dejar que
  Cognia escriba en su propio repo.

---

## 1. La causa raíz (medida, no supuesta)

`cognia/program_creator/sandbox_runner.py:58-75` inyecta `_RUNTIME_GUARD`, que
sobrescribe `builtins.__import__` de forma **global** dentro del subproceso. La
línea 70 —`if name.split('.')[0] in _BM`— se aplica entonces también a los
imports **internos** que hace la propia biblioteca estándar mientras carga.

Consecuencia medida con `run_in_sandbox` **[M]**:

| módulo | resultado |
|---|---|
| `pathlib` | `ImportError: [sandbox] blocked: urllib.parse` |
| `dataclasses` | `ImportError: [sandbox] blocked: importlib.machinery` |
| `unittest` | `ImportError: [sandbox] blocked: importlib.machinery` |
| `tempfile` | `ImportError: [sandbox] blocked: shutil` |
| `json`, `sqlite3`, `collections` | OK |

**Ninguno de los cuatro está en `BLOCKED_MODULES`** (17 entradas **[V]**). Mueren
por su cadena transitiva. Y son exactamente los cuatro pilares de un programa
complejo: **modelar estado** (`dataclasses`), **tocar archivos** (`pathlib`),
**escribir tests** (`unittest`), **tener workspace** (`tempfile`).

Están prohibidos **por accidente, no por diseño**. Esa distinción es el plan
entero: no hay que aflojar una política de seguridad, hay que arreglar un bug que
nadie eligió.

**Por qué cinco agentes de mapeo no lo vieron:** todos probaron módulos
*peligrosos* (`socket`, `subprocess`, `os`) y confirmaron que estaban bloqueados.
Ninguno probó los *benignos*. El sesgo de confirmación tiene forma de test suite.

---

## 2. El problema de seguridad, que es independiente y anterior

Dos agujeros verificados por ejecución **[M]**, no por lectura:

```
run_in_sandbox("import os; getattr(os,'sys'+'tem')('echo RCE_CONFIRMADO')")
  → success=True, exit_code=0, blocked_imports=[], stdout='RCE_CONFIRMADO'

run_in_sandbox("import os; print(os.getcwd())")
  → 'C:\Users\usuario\Desktop\cognia_v2'
```

1. **El scan AST no es una frontera de seguridad.** `_SandboxVisitor.visit_Attribute`
   compara el literal `os.system` **[V]**; cualquier indirección lo evade. Un scan
   estático nunca podrá cerrar esto — es defensa en profundidad, no la muralla.
2. **El cwd del sandbox es la raíz del repo.** El subproceso hereda el directorio
   del padre; `open('cognia/algo.py','w')` desde código generado por un LLM
   sobrescribe el fuente de Cognia. Ya se verificó escritura efectiva a disco.

**Por qué esto bloquea el objetivo del dueño y no es una digresión:** el objetivo
elegido es que Cognia se modifique a sí misma. Un sistema que se reescribe encima
de un sandbox cuyo cwd es su propio código fuente no tiene forma de distinguir una
auto-modificación aprobada de una corrupción accidental. Es el único camino por el
que este proyecto se rompe de manera irreversible.

**Agravante de alcance:** este sandbox es la compuerta de
`cognia/agent/tool_synthesis.py`, cuyo docstring promete *"Nothing unverified ever
becomes callable"* **[V]**. Hoy esa promesa es falsa: una herramienta sintetizada
puede ejecutar comandos arbitrarios y quedar registrada como verificada.

**Honestidad sobre el alcance del arreglo:** sin Docker ni Job Objects de Windows
**no se puede prometer un sandbox de seguridad duro**. Lo que G0 entrega es
*contención best-effort contra código generado por un LLM que se equivoca* — no
contra un atacante humano dedicado. Esa distinción va escrita en el docstring del
módulo, no solo en este plan. Prometer más sería exactamente el tipo de sello
falso de "verificado" que este repo ya decidió no poner (ver la decisión de no
usar un LLM débil como refutador en `INVESTIGACION_Y_ANTIRUIDO.md` §1.2).

---

## 3. Gates

### RESULTADO DE G0 (2026-07-19): el gate hizo su trabajo — FALLÓ

El primer intento de G0 fue un guard **in-process**. El equipo rojo pre-registrado
(§4) lo **rompió**: 11 fugas BLOQUEANTE/ALTO reproducidas ejecutando de verdad —
lanzó `cmd.exe`, abrió sockets, escribió en la raíz del repo, y **desarmó el guard
entero en 2 líneas** (`import _cognia_guard; _cognia_guard._real_import(...)`).

**Causa raíz, decisiva y única:** un guard in-process de Python **no puede
contener código Python**. El lenguaje es demasiado reflexivo — `gc.get_objects()`
alcanza cualquier built-in, en Windows `os` re-exporta de `nt` (que el guard no
tocó), `importlib._gcd_import` esquiva `__import__`, las closures devuelven los
originales. No son 11 bugs para parchear: es la arquitectura. Por eso PyPy
abandonó su sandbox in-process. **Aplica el disyuntor (regla 11):** no se
re-parcha el mismo enfoque; se cambia la causa.

**Lo que del intento SÍ sirve y queda commiteado** (verificado, sin regresiones en
la suite de 2913): el desbloqueo de los 4 pilares (`pathlib`/`dataclasses`/
`unittest`/`tempfile`), la ejecución multi-archivo, los 41 tests de regresión, y
el cwd fuera del repo. `run_in_sandbox` queda como contención **best-effort contra
accidentes de un LLM**, con la advertencia de seguridad escrita en su cabecera y
una guarda que impide usarlo como frontera para código no confiable.

**Decisión del dueño (2026-07-19): contención DURA.** Medición de la máquina:
Docker **no** está, la sesión **no** es admin, y `wsl.exe` existe pero **WSL no
está instalado** (`wsl --status` → "no está instalado"; el `which` engaña con el
stub de System32). Job Objects sí accesibles vía `ctypes`, pero contienen
procesos/RAM/CPU, **no** FS/red/imports. Por lo tanto la contención dura exige o
bien que el dueño instale WSL/Docker (admin + reinicio), o bien AppContainer
nativo vía ctypes. **Camino a definir — ver G0-SO abajo.**

### G0-SO — Contención a nivel de sistema operativo (rediseño, PRE-REGISTRADO)

El ejecutor de código no confiable pasa a una capa de SO real. Opciones, a fijar
con el dueño según lo medido:
- **WSL** (requiere instalación por el dueño): correr en Linux, usuario sin
  privilegios, FS confinado, `setrlimit` real, red cortada.
- **AppContainer + Job Object nativos** (sin instalar nada): confinamiento de
  FS/red por SID de capacidades + límites de proceso/RAM por Job Object. Todo
  ctypes. A medir su viabilidad antes de comprometerse.

**G0-SO (gate):** el mismo equipo rojo de §4 corre contra el nuevo ejecutor y
**ninguno** de los 5 vectores pasa. Recién entonces G0 cierra.
**KILL G0-SO:** si el arranque de la capa de SO tarda >2 s por ejecución, el lazo
de reparación (G1) se vuelve inusable; se reevalúa el enfoque.

### (histórico) G0 intento 1 — Guard in-process que deja pasar lo benigno

Cuatro arreglos en `cognia/program_creator/sandbox_runner.py`:

- **(a) Política solo sobre el código del usuario.** El guard aplica la denylist
  únicamente cuando el import nace de un archivo del workspace del usuario
  (inspección del frame llamador). Los imports internos de la stdlib pasan.
  Diseñado desde el principio para multi-archivo: la regla es "¿el frame llamador
  vive en el workspace?", no "¿es *el* archivo?".
- **(b) Workspace aislado.** `cwd` = directorio temporal propio y descartable,
  nunca la raíz del repo.
- **(c) Neutralización en runtime.** Los atributos peligrosos de `os` se
  reemplazan **antes** de que corra el código del usuario, así `getattr(os,
  's'+'ystem')` obtiene la versión neutralizada. Esto sí atrapa la indirección; el
  scan AST se degrada explícitamente a defensa en profundidad.
- **(d) Éxito honesto.** Hoy `sandbox_runner.py:231-233` marca `success=True` ante
  un timeout si hubo >10 chars de stdout **[V]** — un programa que imprime un menú
  y se cuelga en `input()` cuenta como éxito. Se elimina.

**G0 (gate):** los cuatro módulos de la tabla §1 importan y corren; el equipo rojo
falla en los cinco vectores (§4); la suite completa del repo sigue verde.
**KILL G0:** si cerrar el bypass exige romper `tool_synthesis` o volver
inimportable algo hoy benigno, se para y se reevalúa — no se acepta cambiar un
agujero por una regresión.

### G1 — Lazo de reparación: el error vuelve al modelo

Hoy `program_creator.py:143-182` calcula `exec_result` y `eval_result` y **los
tira** **[V]**: un fallo no se repara, se regenera desde cero. El task manager de
114 LOC se perdió entero por esto.

Lo que se porta ya existe en el repo: `game_manager.py:508 _fix_runtime_error`
reinyecta el traceback al modelo, con `MAX_FIX_ATTEMPTS=3` **[V]**.

**Cableado obligatorio desde el primer commit:** contra `cognia/disciplina/` — es
literalmente el bucle de parches estériles que ese módulo existe para cortar.
Agregarlo después sería repetir el error que el propio repo documentó.

**G1:** el task manager de §0 se repara y pasa en ≤3 intentos.
**KILL G1:** si el disyuntor dispara en >50% de las generaciones, el lazo produce
más ruido que señal y se saca del camino por defecto.

**[?] Bug conocido a resolver antes de apoyarse en él:** `cognia/disciplina/reparacion.py:216`
—el verde no limpia el contador— produce falsos positivos justo después de un
arreglo exitoso. Reportado en el mapeo, **no verificado por mí**.

### G2 — Verificación por tests reales

Hoy "funciona" significa `exit_code==0 and len(stdout.strip())>0` **[V]**. Por eso
`euclidean_empire` está archivado con **8.9/10** y la nota *"Program ran
successfully."* cuando en realidad sale con `exit=1` **[M]**.

Depende de G0(a): `unittest` tiene que ser importable primero.

**G2:** la nota sale de tests que pasan, no de heurísticas de stdout.
**Efecto esperado y deseado, anticipado para no leerlo como regresión:** las notas
se hunden y la biblioteca se vacía — con criterio real, 13 de 16 del corpus
histórico no pasan **[M]**.

**Deuda que G2 arrastra y hay que arreglar de paso:** `evaluator.py:49-56` premia
`input()` y `while True`, que es exactamente lo que `generator.py:188` rechaza
**[V]**. Criterios contradictorios dentro del mismo módulo; es el origen de los 9
`EOFError` heredados de la biblioteca.

### G3 — Proyecto multi-archivo

Lo que el dueño pidió literalmente, y que hoy **no existe en ninguna parte del
repo**: `grep -rln 'multi_file|scaffold|project_generator|generate_project'` da
**cero hits** **[M]**. Exige cambiar tres contratos a la vez: el generador emite
un árbol y no un string (`generator.py:159` parsea UN bloque ```python), 
`save_program` escribe ese árbol (`storage.py:199` escribe exactamente un
`program.py`), y el sandbox ejecuta un directorio con imports entre módulos
propios — que dependen de G0(a) por diseño.

**G3:** un proyecto de ≥3 módulos que se importan entre sí, con su suite, pasa.
**KILL G3:** si el 14B no sostiene coherencia entre módulos en 3 intentos, se
declara límite de capacidad del modelo y se cierra la vía. **No se sustituye por
un modelo más grande sin medir antes el costo de VRAM.**

**[?] Incógnita de capacidad, sin medir:** nunca se le pidió al 14B un proyecto
multi-archivo. Lo único probado es un archivo de 114 LOC con 4 componentes, y ahí
sí salió coherente — pero eso **no extrapola** a un árbol de módulos.
**[?] Techo físico, sin medir:** `n_ctx=8192` y VRAM al 97.8%. No se sabe si un
contexto mayor —prerrequisito de multi-archivo— entra sin descargar un modelo.

### G4 — Auto-modificación

El objetivo elegido. **No arranca hasta G0-G3 cerrados**, y su blindaje se
pre-registra acá para que no se negocie bajo entusiasmo:

- Cognia trabaja **siempre en una rama git dedicada**, nunca en `main`.
- Un cambio solo se propone si **la suite completa del repo pasa** (hoy 2872
  tests **[V]** según `INVESTIGACION_Y_ANTIRUIDO.md` §1.0).
- **Rollback automático** ante fallo: `git checkout` de la rama, sin excepción.
- **Ningún push a `origin` sin revisión humana.** El "Modo Manager Autónomo" del
  `CLAUDE.md` autoriza al agente, **no** al código que el agente genera.
- Lista negra de rutas intocables: `cognia/disciplina/`, `sandbox_runner.py` y el
  propio G4. **Un sistema no se auto-modifica sus propios frenos.**

**KILL G4:** si Cognia rompe la suite dos veces seguidas sin repararla sola, se
cierra la vía y queda como asistente de propuestas con humano en el lazo.

---

## 4. Equipo rojo de G0 (pre-registrado, para no calificarse solo)

Cinco vectores independientes, cada uno verificado **por ejecución real** contra
el sandbox nuevo. G0 no cierra si alguno pasa:

1. **Escape de imports** — indirección, `exec`/`eval`, `__builtins__`, trucos de
   codificación.
2. **Escritura fuera del workspace** — rutas relativas, `..`, absolutas, symlinks.
3. **Ejecución de comandos** — todas las variantes de indirección sobre `os`, no
   solo `getattr`.
4. **Agotamiento de recursos** — bomba de memoria, de CPU, de descriptores.
5. **Evasión del scan AST** — construir código en runtime para eludir el análisis
   estático.

Regla anti-sesgo, aprendida de §1: **los atacantes también prueban módulos
benignos.** Un sandbox que se vuelve seguro rompiendo `pathlib` no pasa G0.

---

## 5. Orden y por qué es este

```
G0 (sandbox)  →  G1 (reparación)  →  G2 (tests reales)  →  G3 (multi-archivo)  →  G4 (auto-mod)
   BLOQUEANTE       ALTO                BLOQUEANTE            el pedido literal      el objetivo
   + seguridad
```

G0 primero porque es bloqueante **y** de seguridad. G2 antes que G3 porque subir
el tamaño sin señal de corrección real **solo produce basura más grande** — y ese
es el modo de fallo más probable de todo este plan. G4 último porque es
irreversible cuando sale mal.

**Fuera de alcance, explícito:** subir `max_tokens`/límite de líneas
(`generator.py:125,154`) es un cambio de dos constantes y **no se toca hasta G2**,
por la razón de arriba. Revivir `game_manager` (cableado a Ollama, que no está
instalado **[M]**) es barato y tentador pero **arrastra su evaluador sesgado**;
queda diferido hasta que G2 arregle el criterio.

---

## 6. Incógnitas abiertas (declaradas, no escondidas)

- **[?]** Coherencia del 14B en multi-archivo — nunca medida (G3).
- **[?]** Si `n_ctx` mayor entra en VRAM sin descargar un modelo.
- **[?]** `ShatteringOrchestrator(mode='local')` lanza
  `ValueError: Provide manifest or manifest_path`; corta el lazo autónomo de
  `tool_synthesis` (`background_tick` → `skipped`). Heredado del mapeo, sin verificar.
- **[?]** La mitad generativa de `tool_synthesis` (`generate_tool_code` /
  `repair_tool_code`) nunca se ejercitó contra el modelo vivo — los 11 tests
  inyectan `code=` explícito.
- **[?]** La medición "3 de 16 corren" usa el sandbox viejo, con el guard
  envenenado. Algunos de esos 13 fallos podrían ser inducidos por el bug y no por
  el código. **El número de fallos genuinos podría ser menor.** Se re-mide tras G0.
- **[?]** `index.json` declara 21 programas y en disco hay 13; el usuario ve
  "Biblioteca Cognia (21 programas) / Promedio: 7.3/10". Deuda de datos, no de
  código; no bloquea ningún gate.
