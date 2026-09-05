# 03 — Superficie de CLI, config, observabilidad y bancos (auditoría 2026-09-04)

Repo: `C:\Users\usuario\Desktop\cognia_v2` · paquete `cognia` · venv `venv312\Scripts\python.exe`.
Todas las rutas son relativas a la raíz del repo salvo que se diga lo contrario. Las líneas
son las del árbol de trabajo de hoy (`cognia/cli.py` tiene 28.790 líneas).

Reglas vinculantes de `CLAUDE.md` que gobiernan cualquier adición (sección "REGLA — Toda adición
se entrega EN EL CLI", `CLAUDE.md:70-104`):
1. **Puerta**: comando slash registrado en `_CMD_DESCRIPTIONS` (`cognia/cli.py:3097`) y visible en `/ayuda`.
2. **Expandible**: config persistida con `_load_config()/_save_config()` (`cli.py:8907/8916`),
   default sensato, on/off explícito, un punto de extensión (dict/registry).
3. **No calla**: todo fallo pasa por `_aviso_degradado(origen, motivo)` (`cli.py:331`); prohibido `except: pass`.
4. **Tecleado**: ≥3 tareas humanas en el REPL con salida real pegada.
5. **Regresión**: test que falla sin el fix + suite dirigida.

---

## 1. Cómo se registra un comando slash (y un subcomando de `cognia`)

### 1.1 El registro: `_CMD_DESCRIPTIONS` — `cognia/cli.py:3097-3447`
Dict plano `{"/comando": "descripcion corta  [uso]"}` agrupado por comentarios de categoría.
Es la **única fuente** de `/ayuda`, autocompletado, `/comandos` y del "comando desconocido":
- `cli.py:3449` `COMMANDS = _CMD_DESCRIPTIONS` (alias público).
- `cli.py:3452-3471` `_cmds_visibles()`: filtra por nivel `/avanzado` vía `cognia/cli_visibilidad.py`
  ("OCULTAR NO ES DESACTIVAR": el despachador ve el dict entero).
- `cli.py:23935-23936` `/ayuda` -> `cognia.harness.ayuda.todo(_CMD_DESCRIPTIONS, ancho)`.
- `cli.py:26100-26130` rama final `elif raw.startswith("/")`: `ayuda.mensaje_desconocido(_CMD_DESCRIPTIONS, raw)` sugiere el parecido.
- `cli.py:11186` `_es_comando_conocido`: `cmd in _CMD_DESCRIPTIONS or cmd in _CMD_DETAILS`.
- `_CMD_DETAILS` (`cli.py:3518`) = ficha larga opcional por comando (`/ayuda /x` la muestra, `cli.py:11189-11200`).

### 1.2 El despachador: cadena `if/elif raw == "/x" or raw.startswith("/x ")` — `cli.py:23662-26130`
No hay tabla de handlers: es un if-chain de **318 ramas** dentro de `repl()`. Empieza en
`cli.py:23662` (`/deshacer-borrado`, "van primero porque son la red de seguridad") y termina en
`cli.py:26100` con el fallback de desconocido. Patrón canónico de una rama:

```python
# cli.py:23843
elif raw == "/horizonte" or raw.startswith("/horizonte "):
    _slash_horizonte(
        raw[len("/horizonte "):] if raw.startswith("/horizonte ") else "")
```
Trampas documentadas en el propio chain: el orden importa por prefijo (`/deshacer-borrado` antes
que `/deshacer`, `cli.py:23662-23667`; `/modelos` vs `/modelo`, `cli.py:23721-23726`);
`/compactar` a secas (`cli.py:23705`) y `/compactar <args>` (`cli.py:23820`) son DOS ramas distintas.

### 1.3 Config persistida: `_load_config` / `_save_config` — `cli.py:8907-8917`
```python
_CONFIG_PATH = Path.home() / ".cognia_config.json"          # cli.py:8643
_CONFIG_DEFAULTS: dict = {...}                                # cli.py:8645-8905
def _load_config() -> dict:                                   # cli.py:8907
    if _CONFIG_PATH.exists():
        try: return {**_CONFIG_DEFAULTS, **json.load(_CONFIG_PATH.open(encoding="utf-8"))}
        except Exception: return dict(_CONFIG_DEFAULTS)
    return dict(_CONFIG_DEFAULTS)
def _save_config(cfg: dict) -> None:                          # cli.py:8916
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
```
Contrato de siembra al arranque: cada subsistema tiene un `_aplicar_config_<x>()` que copia la
clave persistida al `os.environ` **sin pisar lo que puso el usuario** y marca la siembra con
`_marcar_env_sembrada(var)` (`cli.py:14383`, delega en `harness/config_resuelta.marcar_sembrada`)
para que `/config-resuelta` no atribuya el valor a "env:COGNIA_*". Lista actual:
`_aplicar_config_estilo:13565, _offload:14404, _compactacion:14582, _barra:14605, _revision:14629,
_lazo:14942, _telemetria:14955, _horizonte:14977, _bucle:17412, _entrega:18253, _notificaciones:18272`.
Punto de extensión: añadir clave en `_CONFIG_DEFAULTS` + un `_aplicar_config_<nuevo>()` + llamarlo
donde se llaman los demás en el arranque del REPL.

### 1.4 Degradación: `_aviso_degradado(via, detalle="", backend=None)` — `cli.py:331-364`
Aviso VISIBLE una vez por turno y motivo (`_AVISOS_VISTOS`), emite evento `Degradado` al bus
`cognia/ux/events.py` (si nadie escucha, grita a stderr) y toast opcional por
`harness/notificaciones`. Uso: `_aviso_degradado("cli.contexto_vivo", f"{type(exc).__name__}: {exc}")`.

### 1.5 Ejemplo mínimo REAL para calcar: `/horizonte` — `cli.py:17256-17340` + rama `cli.py:23843`
Es el ejemplo más completo del patrón "expandible" (config + env + siembra + estado + degradado):
```python
def _slash_horizonte(arg: str = "") -> None:                            # cli.py:17256
    """... on|off -> clave 'horizonte' (COGNIA_HORIZONTE); rondas <n> -> 'horizonte_max_rondas'
    (COGNIA_HORIZONTE_CICLOS); handoff <chars> -> 'horizonte_handoff_max'..."""
    try:
        from cognia.agent import horizonte as _hz
    except Exception as exc:
        _aviso_degradado("horizonte", f"modulo no importable: {exc}"); return
    arg = (arg or "").strip(); bajo = arg.lower()
    if bajo in ("on", "off"):
        cfg = _load_config(); cfg["horizonte"] = bajo; _save_config(cfg)
        os.environ[_hz.FLAG] = "1" if bajo == "on" else "0"
        _marcar_env_sembrada(_hz.FLAG)
        _print_line(f"[info_dim]modo horizonte: {bajo} (guardado; aplica a los proximos /hacer)[/info_dim]")
        return
    if bajo.startswith("rondas"): ...  # valida int, techo _hz._TECHO_CICLOS, persiste + env
    if arg and bajo != "estado":
        _print_line("[warn_cl]Uso: /horizonte \\[estado | on | off | rondas <n> | handoff <chars>][/warn_cl]"); return
    # Estado (default): cfg = _load_config(); _fuente(var, clave) dice si manda env o config
```
Y el ejemplo más pequeño (sin persistencia, solo estado de proceso): `/contexto-auto` — `cli.py:6240-6250`
(global `_CONTEXT_AUTO`, `on|off|estado`) con su rama en `cli.py:26086`. El `/lazo` inline
(`cli.py:25866-25882`) muestra el anti-patrón de handler metido en la rama.

Checklist mecánico para un `/nuevo`:
1. `_CMD_DESCRIPTIONS["/nuevo"] = "Que hace  [estado | on | off | ...]"` (`cli.py:~3360`, junto a `/horizonte`).
2. `def _slash_nuevo(arg: str = "")` cerca de sus hermanos (`cli.py:14434 /offload`, `14772 /compactar`, `17256 /horizonte`).
3. Rama `elif raw == "/nuevo" or raw.startswith("/nuevo "):` en el chain (`cli.py:~23843`), ANTES de cualquier comando con el mismo prefijo.
4. Clave(s) en `_CONFIG_DEFAULTS` (`cli.py:8645`) + `_aplicar_config_nuevo()` + `_marcar_env_sembrada`.
5. Todo fallo → `_aviso_degradado("nuevo", ...)`. Test en `tests/test_cli_<nuevo>.py` con `monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path/"cfg.json")`.

### 1.6 Subcomandos de `cognia <cmd>` — `cognia/__main__.py:616-804`
`main()` lee `sys.argv[1]` y despacha por `if/elif cmd == "..."` (sin argparse global). Subcomandos
existentes: `--version, help, init, install-weights, install-model, server, node, coordinator, modo,
status, doctor, config-resuelta, empezar, leave, contribucion, bbrain, fleet, flota, tui, voz, remoto,
tutor, rlm, hacer/do, responder/confianza, "" (REPL)`. Para añadir uno:
1. Rama `elif cmd == "nuevo":` en `__main__.py` (import perezoso + `raise SystemExit(main(sys.argv[2:]))`,
   patrón de `hacer` en `__main__.py:729-735` → `cognia/cli_hacer.py`).
2. Entrada en `_HELP` (`__main__.py:~560-590`) **y** en `cognia/ayuda_cli.py:26` `GRUPOS`
   (tupla `("nuevo", "<args>", "que hace")`) — la ayuda jerárquica se genera de ahí.
Ejemplo mínimo: `rlm` (`__main__.py:709-728`): valida argv, import perezoso de
`cognia.agent.rlm.correr_rlm`, imprime texto + informe, `sys.exit(0 if ok else 1)`.

---

## 2. Comandos existentes de memoria / contexto / sesiones

Todas las líneas apuntan a `cognia/cli.py` (registro → rama → handler → módulo).

| Comando (registro) | Qué hace (1 línea) | Handler / módulo |
|---|---|---|
| `/hacer` `:3204` | Modo agente con tools | `_run_agent_task` → `cognia/agent/loop.py` (bucle nativo) |
| `/rlm [<ruta>] <preg>` `:3222` | Contexto largo por tools: LOCALIZA, no sintetiza; sin ruta usa el "corpus vivo" de la sesión | rama `:25079`; `cognia/agent/rlm.correr_rlm`; `_rlm_corpus_vivo(ai)` |
| `/largo` `:3224` | Generación larga con progreso + checkpoint, `--continuar <archivo>` | `_slash_largo:11972`, `_slash_largo_continuar:12203` |
| `/horizonte` `:3360` | Rondas de worker fresco con report de 5 campos + GoalContract | `_slash_horizonte:17256`; `cognia/agent/horizonte.py` (`FLAG=COGNIA_HORIZONTE`) |
| `/tx`, `/libro` `:3245-3246` | Agente de horizonte largo TX y su memoria append-only | `_slash_tx`, `_slash_libro` (`:25853-25858`); `cognia/tx/*` (`COGNIA_TX`) |
| `/compactar` (a secas) `:3350` | Resumen visual de la sesión (feature vieja) | `_slash_compactar_sesion:5697` (rama `:23705`) |
| `/compactar estado\|resumen\|truncado\|umbral\|retencion\|cap` | Puerta F4 de la compactación del contexto del agente | `_slash_compactar:14772` (rama `:23820`); `cognia/harness/compactacion.py` |
| `/offload` `:3349` | Salidas grandes de tools a disco (cabeza+cola+handle `recuperar`) | `_slash_offload:14434`; `cognia/harness/offloading.py` |
| `/contexto-vivo [avanzado\|json]` `:3234` | Cuánto contexto queda, dónde vive (KV/RAM/VRAM) y a qué velocidad | `_slash_contexto_vivo:10622`; `harness/medidor_contexto.py` (+ `contexto_vivo.py`) |
| `/ventana` `:3357` | Presupuesto de SALIDA real (`n_ctx - prompt`), modo continuo | `_slash_ventana` (rama `:23840`) |
| `/pasos` `:3343` | Pasos ilimitados (default) o con presupuesto | `_pasos_ilimitados:4721` (`COGNIA_PASOS_ILIMITADOS`, clave `pasos_ilimitados`) |
| `/estado` `:3400` | Estado rápido de todos los sistemas (HTTP a :8765) | `_slash_estado:6364` |
| `/memoria` `:3328` | Estado de memoria y KG; `agente on\|off\|estado` = memoria como DATO en /hacer | `ai.introspect` (`:23714`), `_slash_memoria_agente:18837` |
| `/memoria-stats` `:3260` | Episodios, observaciones, conceptos cristalizados | rama `:25518`; `ai.episodic`, `ai.semantic`, `storage.db_pool` |
| `/memoria-limite` `:3361` | Tope de recuerdos/MB (persiste) | `_slash_memoria_limite:18861` |
| `/memorias` `:3161` | Librería de todo lo producido (dashboard/buscar/fichas) | `_slash_memorias:11561` |
| `/buscar-memoria` `:3390` | TF-IDF sobre todo el historial | `_slash_buscar_memoria:5989` |
| `/recap` `:3228` | Recapitulación extractiva sin LLM, auto cada N turnos | `_slash_recap:8927`; `cognia/memory/recap_policy.should_recap` |
| `/resumir` `:3327` · `/resumen-sesion` `:3319` | Resume la conversación / resumen completo de la sesión | `_slash_resumen_sesion_full:20052` |
| `/sesiones` `:3287` · `/resume [id\|dir\|list]` `:3288` · `/sesion-ver` `:3290` | Listar / reanudar (carga el hilo al contexto) / ver una sesión | `_slash_sesiones:18931`, `_slash_resume:18962`; `ai.chat_history`, `cognia/config.DB_PATH` |
| `/limpiar-sesion` `:3320` | Limpia `_history` en memoria (no borra persistencia) | `_slash_limpiar_sesion` (rama `:26097`) |
| `/contexto <q> \| prompt` `:3322` · `/contexto-mapa` `:3323` · `/contexto-stats` `:3324` · `/contexto-auto on\|off` `:3325` | Mapa de contexto `cognia_context.md` (buscar / regenerar / punteros / auto-indexar) | `_slash_contexto:6187` (`cognia/context/context_engine`), `_slash_contexto_auto:6240` |
| `/ver-contexto` `:3321` | Qué contexto inyectaría Cognia para una pregunta | `_slash_ver_contexto:19991` (HTTP :8765) |
| `/contexto-semantico` `:3392` | Contexto relacionado semánticamente | rama en el chain |
| `/deshacer [n\|lista\|diff\|hasta]` `:3208` · `/deshacer-borrado` `:3209` | Checkpoints de lo que el agente escribió / papelera de lo borrado | `_slash_deshacer:20738` → `harness/checkpoints.py`; `_slash_deshacer_borrado:20770` → `harness/papelera.py` |
| `/historial` `:3261` · `/buscar-historial` `:3289` · `/historial-limpiar` `:3291` | Tareas recientes del agente / búsqueda / borrado del historial | chain |
| `/tarea-crear\|lista\|ok\|borrar` `:3295-3298`, `/tareas` `:3116` | Tablero de tareas de sesión (checkboxes) | chain |
| `/grafo` `:3159`, `/grafo-html` `:3160`, `/hecho` `:3164`, `/buscar-kg` `:3302`, `/kg-*` `:3303-3310`, `/conflictos-kg` `:3439`, `/verificar-kg` `:3440`, `/hechos-solidos` `:3421`, `/cristalizar` `:3422` | Knowledge graph (ver, exportar, inferir, caminos, consistencia) | `cognia/knowledge/graph.py`, `ai.semantic` |
| `/recordar` `:3363`, `/recordar-cancelar` `:3365` | Recordatorios temporales (NO memoria) | chain |
| `/olvido` `:3124`, `/cognia-olvida` `:3436` | Ciclo de olvido / olvidar un hecho | chain |
| `/hermes` `:3251` | Presupuesto, guardia de bucle, parada verificada del arnés Hermes | chain |
| `/telemetria [estado\|on\|off\|ultimo\|ruta]` — **SIN REGISTRO** | Diario JSONL del turno | `_slash_telemetria:18476`, rama `:23813`; solo aparece dentro de la descripción de `/debug` (`:3333`) |

**Hallazgos**:
- `/telemetria` está despachado (`cli.py:23813`) y tiene handler, pero **no está en `_CMD_DESCRIPTIONS`**
  (0 coincidencias en `3097-3517`): viola la regla de puerta; no sale en `/ayuda` ni autocompleta.
- Las claves `telemetria` y `pasos_ilimitados` se leen con `.get(..., default)` pero **no están en
  `_CONFIG_DEFAULTS`** (0 coincidencias en `8645-8905`): `/config-resuelta` no las enumera.
- No existe ningún comando `/checkpoint`, `/bitacora`, `/canal` ni `/estado-canal`: el canal de estado
  (`cognia/estado/canal.py`) solo se ve indirectamente vía `/tx` (`cli.py:8614`, "P0-4 G2 se mide sobre").

---

## 3. Observabilidad

### 3.1 `cognia/harness/telemetria.py` (173 líneas) — el diario JSONL de una tarea
- Encendido: env `COGNIA_TELEMETRIA=<ruta.jsonl>` (`ENV`, `:39`); `ruta()`/`activa()` `:47-53`.
  Apagado por defecto; `/telemetria on` persiste `telemetria=on` y `_aplicar_config_telemetria`
  (`cli.py:14955`) manda a `~/.cognia/telemetria/YYYYMMDD.jsonl` si no hay env (la env gana).
- `evento(tipo, **campos)` `:61-98`: una línea JSON `{"t": <s monotónicos>, "tipo": ..., campos}` con
  append + flush, campos acotados (str 600, listas 40×200, dicts 40 claves). Nunca lanza; un solo
  aviso por proceso si no puede escribir.
- `leer(ruta)` `:101`, `resumir(ruta)` `:118-173` → dict: `eventos, turnos, tokens_entrada/salida/totales,
  tok_s_salida, tool_calls, tool_calls_por_nombre, tool_calls_fallidas, tools_que_fallaron,
  turnos_cortados_por_tope, duracion_s, prompt_tokens_max, eventos_por_tipo, presupuesto_pasos,
  techo_pasos, tarea_chars, cierre_motivo/razon/ok/pasos/finish, incidencias[], n_compactaciones, n_cortes`.
- **Tipos de evento emitidos hoy** (grep de `_tel.evento(` en el repo):
  - `inicio` (`cli.py:27858`): presupuesto, techo, tarea_chars, dificultad, modalidad.
  - `turno` (`agent/loop.py:492`): paso, tokens_entrada, tokens_salida, estimado, finish, n_tool_calls, ms.
  - `tool` (`loop.py:3390`): nombre, paso, ok, ...
  - `contrato` `:1865`, `compuerta_contrato` `:2953/2965`, `aviso_pared` `:2165`, `advertencia_progreso` `:2213/2249`,
    `corte` `:2409` (razonamiento_desbocado), `rescate` `:2652` (tool_call_cortado_500),
    `espiral_depuracion` `:3349`, `lazo_corto` `:3385`, `aviso_racha` `:3626`, `cierre` `:3958`
    (ok, pasos, tokens, finish, razon, motivo, chars_respuesta).
  - **Nunca se emiten** `compactacion`, `reintento` ni `degradado`, aunque `resumir()` los cuenta
    (`:160-166`): `n_compactaciones` siempre es 0. La compactación se anota aparte en
    `harness/compactacion.anotar_truncado/anotar_error` (`:165-186`, memoria de proceso `_ULTIMA`,
    visible solo en `/compactar estado`), llamada desde `loop.py:3712-3720`.

### 3.2 `cognia/harness/barra_estado.py` (856 líneas) — barra inferior + atajos
Constructor puro (no imprime): `barra_estado(datos, ancho)` `:663`, `_sec_ctx` `:476` pinta
`ctx 12.4k/128k (90% libre)` con headroom fijo de 1024 tokens y mini-barra de bloques
(`COGNIA_BARRA_BLOQUES`, `:192`; clave `barra_bloques` default on `cli.py:8780`), `nivel_contexto` `:446`,
`toolbar_prompt_toolkit` `:772`. Datos: modo, modelo, directorio, rama, ctx usado/total, tokens.

### 3.3 `cognia/harness/contexto_vivo.py` (502) y `medidor_contexto.py` (539)
- `contexto_vivo`: acumulador de proceso con `usage` REAL del backend. `registrar_uso` `:259`,
  `registrar_contexto` `:285`, `estado()` `:328` → `{entrada, salida, total, cacheados, n_ctx, ocupacion,
  porcentaje, restante, modelo, turnos, estimado, nivel}`; `aviso_umbral` `:353`; `barra` `:372`.
  Umbrales: `COGNIA_CTX_AVISO` (default = `compactacion.umbral_frac()*100`, `:193-206`),
  `COGNIA_CTX_CRITICO` (default 90, `:206-209`); claves `contexto_umbral_aviso` ("") y
  `contexto_umbral_critico` ("90") en `cli.py:8778-8779`. Todo número sin `usage` va marcado `estimado`/`~`.
- `medidor_contexto.medir(url)` `:266` → `Instantanea` con cada campo `{valor, origen: medido|estimado|?}`:
  `GET /slots` (n_ctx, n_prompt_tokens), `timings` (prefill/gen tok/s, TTFT), `/metrics` si `--metrics`,
  nvidia-smi, RAM del proceso, flags del cmdline del server (kv quant, cache-ram, no-kv-offload).
  `formato_humano` `:458` / `formato_tecnico` `:496` alimentan `/contexto-vivo [avanzado|json]`.

### 3.4 `cognia/ux/events.py` (667) — bus único de eventos del turno
`emitir(evento)` `:448` (no lanzante), `suscribir/desuscribir` `:436-447`, `a_dict` `:460`,
`activar_sink_jsonl(ruta)` `:597` (una línea JSON por evento: es lo que consume el remoto).
Dataclasses frozen (herencia de `Evento` `:79`): `TareaInicio:89, PasoIntencion:97, ToolInicio:104,
ToolFin:111, TokenTexto:121, RazonamientoTick:127, TokensVivos:135, PasoInicio:161, TextoAgente:175,
Progreso:187, Aviso:195, Degradado:202, TareaFin:212, Confianza:226, FooterTurno:246, WorkflowInicio:271,
AgenteInicio:287, AgenteFin:310, MensajeAlAgente:354, AgenteProgreso:373, WorkflowFin:386`.
Hay `marcar_agente/agente_actual` `:57-66` para atribuir eventos a sub-agentes.
**No existe** un evento de contexto/compactación (`Compactacion`, `ContextoNivel`) en el bus: la
ocupación viaja por `FooterTurno`/`TokensVivos` y la compactación solo se ve como `print_fn("[detail]…")`.

### 3.5 `cognia hacer --json` — `cognia/cli_hacer.py:49-191`
Args: `--pasos N`, `--json`, `--silencioso/-s`. stdout = resultado, stderr = progreso. JSON (`:178-181`):
```json
{"tarea": str, "respuesta": str, "segundos": float, "cwd": str, "ok": bool,
 "telemetria": <telemetria.resumir(ruta) | null>}
```
`ok` se degrada a `false` si la respuesta contiene marcas de fallo (`_MARCAS_FALLO`, `:148-154`).
`telemetria` solo se llena con `COGNIA_TELEMETRIA` puesto (`:166-173`). Corre `cli._run_agent_task(ai, tarea, progreso, max_steps=args.pasos)` (`:135`).

---

## 4. Bancos y mediciones reutilizables

| Script | Qué mide | Invocación | Modelo | Duración | Dataset / agujas |
|---|---|---|---|---|---|
| `scripts/ventana_eficaz.py` (166) | Ventana EFICAZ del cerebro: RECUPERAR (1 aguja literal) y RAZONAR (2 agujas a sumar en extremos opuestos) a profundidades 10/50/90% | `PYTHONUTF8=1 venv312\Scripts\python.exe scripts\ventana_eficaz.py [longitudes...]` | Sí, `:8080` | Minutos-decenas (5 longitudes × 3 prof. × 2 pruebas) | Pajar sintético de frases `_FRASES`, `SEED=20260813`, `LONGITUDES=[4k,16k,64k,128k,190k]` tokens |
| `scripts/rlm_escala.py` (166) | Alcance del RLM: aguja hex de 8 chars en pajares de 0,4M-32M chars | `... scripts\rlm_escala.py [chars...]` (default 400k 2M 8M) | Sí (flota) | Largo (escalones de M chars) | Pajar determinista `SEED=20260811`; exit 3 sin backend |
| `scripts/rlm_integracion.py` (131) | Memoria de trabajo del RLM: N agujas numéricas dispersas, respuesta = SUMA exacta; compara RLM vs prompt directo | `... scripts\rlm_integracion.py [Ns...]` | Sí | Medio | `SEED=20260813`; hipótesis firmada "se rompe entre 8 y 16 agujas" |
| `scripts/e2e_rlm_smoke.py` (161) | Smoke RLM: 3 agujas hex en ~400k chars con las 5 tools RLM | `... scripts\e2e_rlm_smoke.py` | Sí | ~minutos | `SEED=20260811`; `E2E RLM SMOKE: N/3 OK`, exit 3 sin backend |
| `scripts/banco_rlm_sintesis.py` (1047) | SÍNTESIS del RLM (contar/comparar/cruzar hilos) con 4 brazos (azar_uniforme, azar_marginal, tonto, rlm) + oráculo y techo_tonto, en 3 celdas (cabe/apenas/no_cabe) | `--celda --filler --docs --clones --por-tipo --brazos --ventana --limite --muestra --salida --seed` | Sí (brazos tonto/rlm); brazos azar/oráculo gratis | Largo | Corpus sintético de documentos con relleno hasta 2M; test `tests/test_banco_rlm_sintesis.py` |
| `scripts/b5_banco_busqueda.py` (259) | ¿El contexto ancho encuentra lo que el snippet no? 4 brazos (estrecho/medio/ancho/ciego) intercalados | `--items 8 --paginas --profundidad 6000 --chars-pagina --puerto --brazos --backend --salida --aguja-fija` | Sí | Medio | Páginas sintéticas servidas por `http.server` local; `--agujas` sembradas a PROFUNDIDAD |
| `scripts/banco_kv.py` (569) | Compromiso contexto↔velocidad: 4 configs de KV (f16/q8_0 × VRAM/`--no-kv-offload`) × barrido de n_ctx; tok/s, TTFT, VRAM, RAM | `--modelo --ctxs --configs --cache-ram --frac-prompt --estres --salida` | Sí (arranca llama-server por config) | Largo | Aguja plantada en el prompt (calidad = la contiene o no); bitácora append-only |
| `cognia/estado/medicion_conservacion.py` (181) | Recall de artefactos y restricciones tras compactación de juguete (cola / cabeza+cola), CON y SIN canal de estado | `PYTHONUTF8=1 ./venv312/Scripts/python.exe -m cognia.estado.medicion_conservacion` | **No** (determinista) | Segundos | Turno sintético de 40 mensajes, 6 ficheros REALES del repo, 3 restricciones (`FICHEROS:27`, `RESTRICCIONES:36`, `construir_turno:49`) |
| `scripts/e2e_happy_path.py` (163) | GATE pre-release: 5 tareas /hacer con postcondición en DISCO | `PYTHONUTF8=1 venv312\Scripts\python.exe scripts\e2e_happy_path.py` | Sí | ~5 min | 5 tareas fijas (`:126-135`); `COGNIA_EFIMERO=1` por setdefault; exit 0 si 5/5 |
| `scripts/banco_cerebro.py` (1025) | Banco graduado (3 fáciles/4 medias/5 difíciles) para comparar cerebros; puntos, no tareas | `... scripts\banco_cerebro.py [--solo id --dif --pasos --json --minimo]` o importado (`correr_banco`) | Sí | ~10-30 min | 12 tareas con `postcondicion(ws)` |
| `scripts/banco_trazas.py` (514) · `banco_multimodal.py` (283) | Fabrican trazas selladas (`verificar_ws`) para dataset; multimodal ejercita voz/imagen/VLM | `--n --semilla --desde --pasos` / `--listar --solo --pasos` | Sí | Largo | Plantillas parametrizadas por semilla |
| `scripts/banco_rutas.py` (451) | Enrutado chat vs agente, dos brazos apareados en la misma corrida | `--solo-determinista --json [--escalon3]` | Opcional (`--solo-determinista` sin backend) | Minutos | Mensajes etiquetados ACCION/CHAT/RESCATE |
| `scripts/e2e_100k_gate.py` (198) | Generación delegada de 100k tokens escribiendo incrementalmente | env `LARGO_TARGET/LARGO_TASKS/LARGO_OUT` | Sí | ~4 h en i3 | — |
| `scripts/b2_banco_brutal.py`, `b3_ventana.py` | Banco brutal (juez+contrato) / ventana temporal de LCB | — | b2 sí | — | `b1_tareas_brutales.json`, `lcb_test*.jsonl` |
| `banco_largo/` (runner, evaluador, motor, tareas) | Tareas LARGAS (25 JSON en `banco_largo/tareas/`, 240-540 s y 40-80 pasos cada una) contra `cognia hacer` en proceso aparte; evaluación multicapa A-H (`evaluador.py:PESOS`) | `venv312\Scripts\python.exe -m banco_largo.runner --ronda <n> [--python <exe>] [--cwd-cli] [--tareas a,b] [--familia] [--factor] [--deadline HH:MM] [--vigilar]`; informe con `-m banco_largo.informe --antes A --despues B` | Sí | 20 min/tarea con `BANCO_PRESUPUESTO=1200` (ver `ab_20min.sh`) | 17 corridas en `banco_largo/corridas/`; telemetría derivada por regex del stdout (`runner.py:_RE_*`) y capa G (`evaluador.capa_verificacion:180`) |
| `scripts/medir_inmune.py` | Coste real de `inmune.anticuerpos.evaluar` + mutantes contrafactuales | `[--contrafactual]` | No | Segundos | — |

**Siembra de agujas en historiales largos** (lo que ya existe):
- `cognia/estado/canal.sembrar_trazadores(estado, k=4, semilla=None)` (`canal.py:465`): hechos
  `TRZ-XXXXXX` no inferibles, entran en la sección del canal que les toca por tipo;
  `comprobar_trazadores(estado, texto, fuente)` (`:520`) cuenta supervivientes por ID y exige que el
  texto no sea la propia proyección (`FUENTE_RESPUESTA`, `assert_integridad_proyeccion:580`). Es la
  única aguja "de conversación" del repo; tests en `tests/test_estado_canal.py:208-258`.
- `ventana_eficaz.py`, `rlm_escala.py`, `rlm_integracion.py`, `e2e_rlm_smoke.py`, `e2e_workflows_smoke.py:64-80`
  siembran agujas en **pajares de texto** (prompt/fichero), no en un historial de mensajes de agente.
- `medicion_conservacion.py` es el más cercano a "historial de agente + compactación", pero con
  compactador de juguete (cola / cabeza+cola), no con `harness/compactacion.compactar`.
- **No existe** un banco que siembre agujas en un historial de `/hacer` real y las busque tras una
  compactación de `compactacion.compactar` o tras `_recortar_mensajes` — es el hueco a cubrir.

---

## 5. Tests: convenciones y aislamiento

### 5.1 `tests/conftest.py` (235 líneas)
- `sys.path` = solo ROOT (no `ROOT/cognia`, `:12-14`); `load_dotenv(ROOT/.env, override=False)`.
- Fixtures **autouse**: `_semilla_reproducible` (`random.seed(20260720)` + numpy, `:60`),
  `_feromona_aislada` (`:75`), `_prompt_usuario_aislado` (env `COGNIA_PROMPT_USUARIO_PATH` → tmp, `:93`),
  `_telemetria_sellos_aislada` (`:104`), `_papelera_aislada` (env `COGNIA_PAPELERA_DIR` → tmp, `:117`),
  disyuntor JSONL a tmp (`:120+`).
- **No hay** aislamiento global de `~/.cognia` ni de `~/.cognia_config.json`: cada test lo hace a mano.

### 5.2 Cómo se aísla `~/.cognia` en los tests (patrones medidos por nº de ficheros)
- `monkeypatch.setenv("COGNIA_HOME", str(tmp_path))` — 26 ficheros (`tests/test_adaptador_regimen.py:43`,
  `test_arnes_ampliacion_pasos.py:40`, `test_bots_*.py`). `COGNIA_HOME` lo lee `cognia/first_run.py:26-28`
  (config.env) y los módulos que derivan `~/.cognia` de ahí.
- `monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")` — 16 ficheros
  (`tests/test_cli_confianza.py:33`, `test_cli_bots.py:41`, `test_clases_cli.py:60`): es la forma de aislar `_load_config/_save_config`.
- `Path.home` parcheado — 11 ficheros; `COGNIA_DB_PATH` — 5 (`cognia/config.py:18` deriva `DB_PATH`);
  `COGNIA_EFIMERO=1` — 10 (`cognia/cli.py:1072`, `memory/chat.py:29`, `harness/permisos_reglas.py:976`:
  no escribe chat_history/perfil/episódica del dueño); `COGNIA_OFFLOAD_DIR` — 7; `COGNIA_ESTADO_DIR` — 1
  (`tests/test_estado_canal.py:285`). `COGNIA_DATA_DIR` / `dir_datos` / `COGNIA_TELEMETRIA`: 0 usos en tests.
- Regla de knobs: `tests/test_harness_compactacion.py:28-38` fixture autouse `knobs_limpios` hace
  `monkeypatch.delenv` de `COGNIA_COMPACT*` y `setenv COGNIA_OFFLOAD_DIR` a tmp ("sin esto los tests
  escribirían en el ~/.cognia real").

### 5.3 Ejemplos de tests de compactación / estado / canal
- `tests/test_harness_compactacion.py` (417): compacta listas de mensajes REALES con
  `loop._compactar_por_resumen` y `harness.compactacion`: system+objetivo intactos (`:87`), cola intacta,
  resumen con tools descartadas y su spill F3 (`:105`), canal de estado dentro del resumen (`:120`),
  idempotencia (`:162`), cap (`:187`), modo truncado byte-idéntico (`:221`), env fuerza modo (`:231`),
  fallo del resumen degrada a truncado (`:244`), telemetría de la puerta (`:257`), bucle compacta sin
  prompt_tokens (`:272`), trunca cuando el resumen no libera (`:363`).
- `tests/test_estado_canal.py` (25 tests): mide sha/bytes del disco (`:29`), render prioriza
  restricciones (`:88`), conservación (`:159-198`), trazadores (`:208-258`), serialización (`:260-285`),
  `test_el_canal_mejora_el_recall_sobre_la_compactacion_real` (`:294`, usa `medicion_conservacion`).
- `tests/test_estado_presupuesto.py` (26 tests): tipos de avance verificado, meseta, agotado, tasas.
- `tests/test_estado_tarea.py`: persistencia/retomado de tareas (`cognia/estado/tarea`?).
- Otros relacionados: `test_harness_contexto_vivo.py`, `test_harness_barra_estado.py`,
  `test_harness_offloading.py`, `test_offload_leer_entero.py`, `test_harness_checkpoints.py`,
  `test_horizonte*.py`, `test_rlm*.py`, `test_recap_policy.py`, `test_resume_sessions.py`,
  `test_tareas_largas_ventana.py`, `test_contexto_ventana_nunca_none.py`, `test_presupuesto_*.py`.

---

## 6. Config: cómo se leen los flags y cuáles gobiernan el contexto

### 6.1 Tres capas (de menor a mayor prioridad)
1. **`~/.cognia_config.json`** (`_CONFIG_PATH`, `cli.py:8643`) con `_CONFIG_DEFAULTS` (`:8645-8905`):
   lo escriben los `/comandos on|off|...`; lo siembra al env `_aplicar_config_<x>()` en cada arranque
   del REPL (marcando la siembra). Solo el CLI lo lee; los módulos del harness leen SIEMPRE `os.environ`
   ("embebido sin CLI es opt-in por env a propósito", `harness/offloading.py:354-368`).
2. **`~/.cognia/config.env`** (`cognia/first_run.py:26-28`, `COGNIA_HOME` lo reubica): lo escribe el
   wizard/`install-model`; `apply_config()` (`first_run.py:340`) lo carga a `os.environ` al arrancar
   `cognia`/`cognia hacer`. Claves hoy en la máquina: `COGNIA_DATA_DIR, SHARD_WEIGHTS_DIR, LLAMA_GGUF_PATH,
   LLAMA_SERVER_PORT, LLAMA_SERVER_PATH, LLAMA_N_GPU_LAYERS, LLAMA_CTX_SIZE, LLAMA_N_THREADS,
   COGNIA_PERF_PROFILE, COGNIA_PENSAR, COGNIA_THEME, COGNIA_PERMISSION_MODE, COGNIA_CMD_NIVEL`
   (ninguna de contexto/memoria).
3. **Env del sistema**: manda sobre todo (`__main__.py:~585`: "Las env vars del sistema MANDAN").
   `cognia config-resuelta` (`__main__.py:662-668`, `harness/config_resuelta`) imprime la config
   efectiva con el origen de cada clave.

`cognia/config.py` (169 líneas) NO gestiona flags: solo `DB_PATH` (`COGNIA_DB_PATH`, `:18-20`), banderas
`HAS_*` de dependencias opcionales y `registrar_degradado/degradados` (`:96-104`, consumido por `doctor`).
No hay helper `_activo` central: `harness/familias.py:31` e `interceptor.py:74` tienen el suyo; el patrón
dominante es `os.environ.get("COGNIA_X", "").strip().lower() in ("1","on","true","yes","si")`.

### 6.2 Flags que ya gobiernan el contexto (lector con línea, default y clave persistida)

| Env var | Lector | Default | Clave config (`_CONFIG_DEFAULTS`) / puerta |
|---|---|---|---|
| `COGNIA_COMPACT` = `resumen\|truncado` | `harness/compactacion.modo():117` | `resumen` | `compactacion` `cli.py:8727` / `/compactar` |
| `COGNIA_COMPACT_UMBRAL` (0.3-0.99) | `umbral_frac():141` | 0.8 | `compactacion_umbral` `:8728` |
| `COGNIA_COMPACT_RETENCION` (0.02-0.5) | `retencion_frac():146` | 0.16 | `compactacion_retencion` `:8729` |
| `COGNIA_COMPACT_CAP` (≥600 chars) | `cap_chars():151` | 4000 | `compactacion_cap` `:8730` |
| `COGNIA_OFFLOAD` | `harness/offloading.activo():354` | env vacía = off; el CLI siembra `on` | `offload` `:8710` / `/offload` |
| `COGNIA_TOOL_RESULT_MAX` (bytes) | `umbral_bytes():304` | 2000 | `offload_umbral` `:8711` |
| `COGNIA_TOOL_RESULT_MAX_LECTURA`, `COGNIA_OFFLOAD_CABEZA[_LECTURA]`, `COGNIA_OFFLOAD_DIR` | `offloading.py:166-167, 298, 330-410` | 32768 / 15 / 200 / `~/.cognia/offload` | `offload_umbral_lectura:8716`, `offload_cabeza:8712`, `offload_cabeza_lectura:8717`, `offload_cola:8718` |
| `COGNIA_TAREAS_LARGAS` | `offloading.tareas_largas():321` (lo usa `loop.py:1440,1467` para el gobernador y la ampliación de presupuesto) | `1` (on) | sin clave; sin puerta propia |
| `COGNIA_ESTADO` | `agent/loop.py:1433` | `1` (on): canal de estado + gobernador por progreso | **sin clave ni puerta** (solo se ve en `/tx`) |
| `COGNIA_ESTADO_DIR` | `estado/canal.dir_estado():596` | `~/.cognia/estado` | — |
| `COGNIA_HORIZONTE` (=1), `COGNIA_HORIZONTE_CICLOS`, `COGNIA_HORIZONTE_HANDOFF_MAX` | `agent/horizonte.py:67-69, habilitado():108, max_ciclos_env():113` | off / 0 (según /esfuerzo) / 16384 | `horizonte:8827`, `horizonte_max_rondas:8828`, `horizonte_handoff_max:8829` / `/horizonte` |
| `COGNIA_RLM_WORKER`, `COGNIA_RLM_MAX_HIJOS`, `COGNIA_RLM_PRESUPUESTO`, `COGNIA_RLM_HIJO_TOKENS`, `COGNIA_RLM_VIVO_MAX_CHARS` | `agent/rlm.py:1335, 1277, 1278, 1361, 358` | (ver módulo) | sin clave; puerta `/rlm` sin subcomando `estado` |
| `COGNIA_PASOS_ILIMITADOS` | `cli._pasos_ilimitados():4721` | on | `pasos_ilimitados` (leída con `.get`, NO en defaults) / `/pasos` |
| `COGNIA_TELEMETRIA=<ruta>` | `harness/telemetria.ruta():47` | off | `telemetria` (NO en defaults) / `/telemetria` (sin registro) |
| `COGNIA_CTX_AVISO`, `COGNIA_CTX_CRITICO` (%) | `harness/contexto_vivo.py:193-209` | umbral_frac×100 / 90 | `contexto_umbral_aviso:8778`, `contexto_umbral_critico:8779` |
| `COGNIA_CTX_MAX` | `summoner.py:1132` | 1010176 | — |
| `COGNIA_BARRA_BLOQUES` | `harness/barra_estado.py:192` | on | `barra_bloques:8780` |
| `COGNIA_CHECKPOINTS_DIR` | `harness/checkpoints.py:101` | `~/.cognia/checkpoints` | `/deshacer` |
| `COGNIA_TX` | `tx/flag.py:35`, `harness/interceptor.py:92` | off | `/tx on\|off` |
| `COGNIA_EFIMERO=1` | `cli.py:1072`, `memory/chat.py:29`, `permisos_reglas.py:976` | off | sin memoria persistente (bancos y tests) |
| `COGNIA_DB_PATH`, `COGNIA_HOME` | `config.py:18`, `first_run.py:26` | `~/.cognia` | — |
| `COGNIA_REVISION`, `COGNIA_REVISION_EJECUTAR`, `COGNIA_CONFIANZA` | (documentados en `_CMD_DESCRIPTIONS:3355-3356`) | on | `revision*:8878-8881` |

Cableado de referencia en el bucle (`cognia/agent/loop.py`): compactación por resumen
`_compactar_por_resumen:1223` / recorte viejo `_recortar_mensajes:1044`; reinyección del canal de estado
tras recortar `loop.py:3735-3748` (`_canal.render(_estado, tope_chars=1200)` como mensaje user);
telemetría de compactación `:3712-3720`; recorte de EMERGENCIA cerca de `n_ctx` `:3721+`.

---

## Resumen de huecos detectados (para el diseño)
1. `/telemetria` sin puerta en `_CMD_DESCRIPTIONS` (rama `cli.py:23813`, handler `:18476`).
2. `COGNIA_ESTADO` (canal + gobernador) y `COGNIA_TAREAS_LARGAS` no tienen clave persistida ni comando `estado`.
3. `telemetria.resumir` cuenta `compactacion/reintento/degradado` que nadie emite; `n_compactaciones` siempre 0.
4. El bus `ux/events` no tiene evento de compactación/nivel de contexto.
5. No hay banco que siembre agujas en un historial de `/hacer` real y las busque tras `compactacion.compactar`
   (lo más cercano: `canal.sembrar_trazadores` + `medicion_conservacion` con compactador de juguete).
6. `_CONFIG_DEFAULTS` no declara `telemetria` ni `pasos_ilimitados` (se leen con `.get`).
