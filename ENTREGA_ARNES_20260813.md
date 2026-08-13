# Entrega — destilación de 107 harnesses al CLI de Cognia

**Corrida:** 2026-08-12 22:10 → 2026-08-13 05:00 (deadline con apagado programado).
**Modo:** autónomo total, ultracode con workflows. **Encargo:** investigar los mejores agentes/harness
de IA en ≥10 campos (≈100 sistemas), destilar sus funcionalidades insignia al CLI de Cognia e
implementarlas con pulido; después juzgar visualmente el CLI contra los punteros con VLM real; y por
último un **adaptador nativo** para que nada de esto dependa de instrucciones ciegas en el prompt.

---

## 1. Investigación — 107 sistemas en 9 campos

| Campo | Sistemas |
|---|---|
| Ingeniería de software agéntica | Claude Code, mini/Live-SWE-agent, OpenHands, Aider, Cline, opencode, Codex CLI, Gemini CLI, Goose, Crush… |
| Deep research | GPT-Researcher, STORM, open_deep_research, Perplexica, WebThinker, MindSearch… |
| Orquestación multiagente | LangGraph, AG2, CrewAI, MetaGPT, OpenAI Agents SDK, deepagents, Agno, Letta… |
| Memoria y contexto largo | MemGPT/Letta, mem0, Zep/Graphiti, A-MEM, HippoRAG, memory tool de Anthropic… |
| Verificación y auto-reparación | AlphaCodium, AgentCoder, Reflexion, Self-Refine, LDB, terminal-bench… |
| Navegador y computer-use | Browser-Use, Stagehand, Skyvern, UI-TARS, Playwright MCP… |
| Planificación y razonamiento | ToT, LATS, ReWOO, ADaPT, Voyager, plan mode… |
| UX de CLI/TUI | Claude Code, Codex CLI, Gemini CLI, opencode, Crush, Aider, gptme, mods, oterm… |
| Fiabilidad y seguridad | Langfuse, AgentOps, OTel GenAI, permisos de Claude Code, hooks, checkpoints… |

Salidas: `INVESTIGACION_HARNESSES_20260812.md` (ranking transversal de 35 funcionalidades puntuadas
por `valor × convergencia / dificultad`) y `investigacion_campos.json` (las 107 fichas con mecánica
interna y URL). Se cayó 1 de los 10 campos (ejecución/sandbox) por un agente atascado; los 107
sistemas superan igualmente los 100 pedidos.

## 2. Lo implementado — `cognia/harness/`

16 módulos nuevos, cada uno con su test de regresión (**781 tests propios**, todos verdes) y
revisión adversarial independiente que ya cazó dos bugs graves (deshacer que CRLF-izaba ficheros
enteros; hooks que rompían acentos al decodificar).

| Módulo | Destilado de | Estado |
|---|---|---|
| `checkpoints` | Claude Code `/rewind`, Cline checkpoints, Aider auto-commits | **cableado** |
| `verificacion` | Aider auto-lint/auto-test, OpenHands | **cableado** (sintaxis; tests opt-in) |
| `modo_plan` | plan mode de Claude Code, Plan/Act de Cline | **cableado** |
| `hooks` | PreToolUse/PostToolUse de Claude Code | **cableado** |
| `permisos_reglas` | allow/deny por patrón de Claude Code, "Allow for Session" de Crush | **cableado** (`/permisos`) |
| `interceptor` | el punto único donde todo lo anterior se aplica | **cableado en `run_tool`** |
| `banner_adaptativo` | cabeceras de 4-6 líneas de todos los punteros | **cableado** |
| `offloading` | `TOOL_RESULT_CHAR_LIMIT` de Cline, artifact passing de Anthropic Research | opt-in |
| `registro_dinamico` | tool-search de Anthropic, catálogo dinámico de MCP | opt-in |
| `limites` | límites triples de mini-SWE-agent, `max_budget_usd` de Claude Code | listo |
| `oraculo` | architect/editor de Aider, modelo por subagente | opt-in |
| `contexto_vivo` | barra de contexto de opencode/Gemini CLI | listo |
| `barra_estado` | barra inferior universal | listo, sin cablear |
| `render_tools` | `● Read(x)` + `└ resultado` de Claude Code | listo, sin cablear |
| `ayuda` | portada + categorías + búsqueda | listo, sin cablear |
| `menciones` | `@ruta` de Claude Code / Gemini CLI | listo, sin cablear |

**Lo opt-in lo es por evidencia, no por pereza:**
- `COGNIA_AUTO_TESTS` — la suite del repo son 6 909 tests / 12 min; dispararla tras cada edición
  sería inviable. Aider también la trae opt-in.
- `COGNIA_OFFLOAD` — `run_tool` ya recorta con `aci_trim`, y el repo tiene **medido** que el doble
  truncado hace que el modelo edite con SEARCH/REPLACE texto que nunca vio. Adoptarlo exige medirlo
  contra `aci_trim`, no encenderlo por fe.
- Ninguna herramienta nueva entró en `CORE_TOOLS`: el A/B del propio repo midió que 46 herramientas
  bajan el camino feliz de 4.25/5 a 2.5/5.

## 3. Adaptador nativo (F6) — el hallazgo de la noche

El agente ya corría en régimen nativo, pero `tool_schemas.schemas_para` **ignoraba los `params` del
registry**: sólo tipaba las tools de una tabla hardcodeada y a todas las demás les publicaba una
única propiedad `args` con la línea de ayuda dentro. El modelo recibía **una instrucción en prosa
donde debía recibir una firma**.

Cerrado, y verificado contra el cerebro real (`scripts/e2e_arnes_nativo.py`, gate de 5 pasos):

```
antes:   {"args": "res:3f2a1b lineas 200-260"}
después: {"handle": "res:3f2a1b", "lineas": "200-260"}
ARNES NATIVO: todo OK — las capacidades llegan al cerebro como tools nativas
```

## 4. Juicio visual

`JUICIO_VISUAL_CLI_20260813.md`, con 85 capturas reales de 10 CLIs en `Desktop/galeria_cli/` y
capturas de Cognia **corriendo de verdad** (`scripts/captura_terminal_png.py`).

Veredicto: Cognia gana en **identidad** (el gato Braille es más memorable que casi todos los
rivales) y pierde en **densidad, jerarquía y estado**. El arranque gastaba 2 338 px / ~45 líneas y
`/ayuda` vuelca 198 comandos en 13 438 px.

Corregido y medido: el banner ahora se adapta a la altura real — cabe en 60×120, 60×100, 40×100,
36×100, 30×100 y 24×80, verificado capturando la salida real en las seis. El gato sigue por defecto:
no se esconde, se hace caber.

## 5. Lo que queda pendiente (dicho explícitamente)

1. Cablear `barra_estado` al `bottom_toolbar`, `ayuda` navegable, `menciones` y `render_tools`: los
   módulos están hechos y probados, falta el enganche en `cli.py`.
2. Medir los opt-in con brazos intercalados antes de encenderlos por defecto.
3. El motor de workflows (`agent/workflows.py`) sigue **huérfano del CLI**: completo y probado, pero
   sin ninguna entrada de usuario.
4. Interrupción con ESC durante el streaming: sigue sin existir.
