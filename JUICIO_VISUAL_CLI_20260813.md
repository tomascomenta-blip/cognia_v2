# Juicio visual del CLI de Cognia contra los CLIs de agente punteros

**Método:** capturas **reales** (no descripciones) de 10 CLIs, descargadas de sus repos y docs
oficiales a `C:\Users\usuario\Desktop\galeria_cli\` (85 imágenes), y capturas del CLI de Cognia
**corriendo de verdad** — `scripts/captura_terminal_png.py` ejecuta el proceso con color forzado,
interpreta el ANSI con rich y lo rasteriza con Chromium, así que lo que se juzga es exactamente lo que
el proceso escribió en stdout. Las imágenes se leyeron con visión, una por una y comparándolas.

Fecha: 2026-08-13. Capturas de Cognia: `galeria_cli/cognia/01_repl_arranque.png` (con `/ayuda`) y
`02_repl_limpio.png` (arranque).

---

## 1. Lo que hacen los punteros — patrón convergente

Nueve de los diez coinciden en estas seis cosas. La convergencia es la señal:

| Rasgo | Claude Code | Codex CLI | opencode | Crush | Goose | Gemini CLI |
|---|---|---|---|---|---|---|
| Cabecera ≤ 5 líneas | 4 líneas | 4 líneas (caja) | 1 línea | 1 línea | 1 línea | banner + tips |
| Métricas de sesión visibles | barra inferior | — | `39,413  20% ($0.29)` | coste + `+5 -5` | — | barra inferior |
| Barra de atajos | `(esc to interrupt)` | — | `esc interrupt · ctrl+p commands` | `esc cancel · tab focus chat · …` | `^C exit` | — |
| Tool call de 1 línea + resultado colgante | `● Read(package.json)` / `└ Read 46 lines (ctrl+o to expand)` | viñetas | `* Grep "…" (18 matches)` | cajas | cajas con punto verde | caja con borde |
| Prompt del usuario destacado | fondo gris | fondo gris | barra lateral azul | — | — | — |
| Un color de acento | coral | cian | azul | violeta/rosa | verde | degradado azul |

Detalles que valen la pena robar tal cual:

- **Razonamiento plegado en una línea**: `∴ Thought for 4s (ctrl+o to show thinking)`. Ocupa una línea
  y no pierde la información.
- **Spinner con gerundio + atajo + siguiente paso** (Claude Code):
  `✳ Identifying testing framework… (esc to interrupt)` y debajo `└ Next: Run tests with coverage`.
- **Descripción natural de la acción, no el nombre técnico** (Goose): *"searching for X in message
  file"* en vez de `grep(pattern=…)`.
- **Diálogo de permiso con el diff dentro y tres salidas** (Crush): `Allow` / `Allow for Session` /
  `Deny`. La opción del medio es la que evita las 40 confirmaciones de una sesión larga.
- **Plan con checkboxes y el paso activo en negrita+color** (Codex CLI).

## 2. Cognia hoy — medido, no opinado

| Métrica | Cognia | Punteros |
|---|---|---|
| Altura del arranque | **2 338 px / ~45 líneas** | 4-6 líneas |
| Altura de `/ayuda` | **13 438 px, 198 comandos de golpe** | portada + `/help <tema>` |
| Colores de acento | prácticamente ninguno (gato y logo en blanco) | 1 acento consistente |
| Barra de estado | no existe | universal |
| Barra de atajos | no existe | 5 de 6 |
| Métricas en vivo (ctx/tokens/coste) | no existe (`/costo` estima con `len//4`) | 3 de 6 |
| Prompt del usuario destacado | no | 3 de 6 |
| Pie de arranque | **se desborda del ancho** (`tema oscuro` parte de línea) | — |

Lo que Cognia ya hace bien y **no** se toca: la identidad (gato Braille + logo `COGNIA` en bloques +
marco con versión) es más memorable que el banner de casi todos los rivales; el bloque "Para empezar"
con 8 comandos está bien curado; el pie declara modelo, sesión y continuidad restaurada, algo que
solo opencode iguala.

## 3. Veredicto

En **identidad** Cognia gana a la mayoría. En **densidad, jerarquía y estado** pierde contra los seis
punteros, y no por poco: arranca gastando toda la pantalla en el logo, no dice en ningún momento
cuánta ventana queda, y su ayuda es inutilizable para un usuario nuevo. Son defectos de
**presentación**, no de capacidad — y por eso son baratos de cerrar.

## 4. Lo que se implementa a partir de esto

1. **Banner adaptativo** (`cognia/harness/banner_adaptativo.py`): el gato sigue siendo el default,
   pero se elige la variante según las filas reales de la terminal (completo ≥48 filas / medio ≥34 /
   compacto ≥20 / mínimo). La identidad no se pierde: se hace caber.
2. **Barra de estado y de atajos** (`cognia/harness/barra_estado.py`): modelo · ctx usado/total (%) ·
   tokens · modo · rama, con prioridad de recorte, sobre `bottom_toolbar` de prompt_toolkit.
3. **Render de llamadas a herramienta** (`cognia/harness/render_tools.py`): glifo de estado +
   `tool(args)` + resultado colgante resumido + razonamiento plegado + spinner con atajo.
4. **Ayuda navegable** (`cognia/harness/ayuda.py`): portada con categorías, `/ayuda <categoría>`,
   `/ayuda buscar <texto>` y "¿quisiste decir…?" para los 198 comandos.
5. **Permiso con tres salidas** (`cognia/harness/permisos_reglas.py`): Sí / Siempre / No, con las
   reglas persistidas por proyecto — el `Allow for Session` de Crush, hecho permanente y por patrón.
6. **Métricas reales** (`cognia/harness/contexto_vivo.py`): se usa el `usage` que ya llega del backend
   en vez de estimar con `len//4`.
