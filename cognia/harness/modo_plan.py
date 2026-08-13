"""
cognia/harness/modo_plan.py — MODO PLAN (solo-lectura hasta que el usuario apruebe)
==================================================================================
2026-08-12. Por que existe: Cognia ya tiene el plan como ARTEFACTO (`/plan` en el
CLI y `cognia/agent/plan_artifact.py`), pero NO tenia un MODO que impida escribir
mientras se planifica — grep de plan_mode/solo_lectura/read_only: sin resultados.
El artefacto describe lo que se va a hacer; nada frenaba al agente de hacerlo
igual. Esta pieza es el freno: la insignia de Claude Code (shift+tab -> plan
mode), Cline (Plan/Act) y Roo Code — el agente investiga en solo-lectura, propone
un plan, y recien cuando el usuario lo aprueba se toca algo.

Concreto: estado de sesion EN PROCESO (un dict a nivel de modulo), funciones
planas, cero BD y cero I/O. El modo vive lo que vive el REPL; si el proceso
muere, se vuelve a 'ejecutar' — que es el default seguro (nada queda bloqueado
por un archivo de estado olvidado).

Que bloquea (`es_de_escritura`), en este orden:
 1. ``danger=True`` del registry de tools -> BLOQUEADA. **La fuente de verdad es
    el registry** (`cognia/agent/tools.py`: TOOLS[nombre]["danger"]); este modulo
    no lo importa (seria un import pesado y circular): el llamador pasa el flag.
 2. ``_SEGUN_ARGS`` — tools cuyo efecto NO se decide por el nombre sino por sus
    argumentos (`delegar_subtarea` por rol, `repo_a_prompt` por el `| salida`).
    Va antes de las listas porque una misma tool cae de los dos lados.
 3. ``TOOLS_ESCRITURA`` — lista base explicita, medida contra el registry real de
    hoy, NO copiada a ciegas del enunciado. Dos correcciones que salieron de
    leerlo: (a) `git_estado`/`git_diff`/`git_log` son las UNICAS tools git que
    existen y son de LECTURA — bloquear `git_*` entero seria falso; se bloquea
    cualquier OTRA `git_*` (un `git_commit`/`git_push` futuro) por prefijo;
    (b) `escribir_archivo`/`editar_archivo`/`apendar_archivo`/`ejecutar` NO
    estan marcadas `danger=True` en el registry (solo lo estan `borrar_archivo`,
    `crear_herramienta`, `revertir_herramienta` y las `pantalla_*`), asi que el
    flag del registry solo no alcanza: por eso la lista base.
 4. ``TOOLS_LECTURA`` — allowlist de solo-lectura; corta el heuristico de abajo.
 5. heuristico por verbo en el nombre (escribir/borrar/crear/ejecutar/...), para
    que una tool nueva que nadie declaro no se cuele por default.

El barrido que hay que repetir al tocar los sets: prender TODOS los opt-in
(COGNIA_SCREEN / IMG_TOOLS / BROWSER / REPO_REVERSE / HORIZONTE / VOZ_TOOLS /
MUSICA_TOOLS / 3D_TOOLS / VLM_TOOLS = 1), importar TOOLS (69 tools, no 50) y
listar las que `es_de_escritura` deja pasar. Con solo el catalogo base (50) se
escapan tools que escriben en disco de verdad; ver TOOLS_ESCRITURA.

API para el integrador (el cableado al CLI/loop NO lo hace este modulo):
    from cognia.harness import modo_plan
    modo_plan.alternar()                      # shift+tab del REPL
    ok, motivo = modo_plan.puede_usar(nombre, danger=TOOLS[nombre]["danger"],
                                      args=args)
    if not ok: devolver `motivo` al modelo como RESULTADO de la tool (no cortar
               el loop: el motivo esta redactado para que reencauce a investigar)
    system += modo_plan.sufijo_system()       # solo agrega texto en modo plan
    modo_plan.guardar_plan(texto)             # el agente entrego su plan
    objetivo = modo_plan.aprobar_plan()       # el usuario dijo que si -> vuelve
                                              # a 'ejecutar' y devuelve el plan
                                              # para inyectarlo como objetivo

Limites declarados:
 - Estado GLOBAL por proceso: una sola sesion. Dos agentes concurrentes en el
   mismo proceso comparten modo (el REPL de Cognia es de una sesion; si eso
   cambia, el dict pasa a ser por-sesion, no la API).
 - No persiste (a proposito): sin BD, sin archivo, sin sqlite3.
 - No intercepta nada por si mismo: es una POLITICA. Si el integrador no llama
   a `puede_usar` antes de `run_tool`, no bloquea nada.
 - `delegar_subtarea` se decide por el rol que viene en los args
   ('implementador' escribe, 'investigador' no); sin args legibles se bloquea
   (conservador).
 - Trade-off consciente: `memorizar` y `kg_agregar` (memoria persistente del
   usuario) se bloquean — en modo plan lo unico que se guarda es el plan.
   `anotar`/`notas` (memoria de trabajo de la tarea) siguen permitidas, y
   `cuaderno` tambien aunque tenga subcomandos de ingesta: es la via de consulta
   del investigador. Ajustable editando los sets, que son publicos.
 - Una tool que escribe, no esta en la lista base, no se marca `danger=True` y
   no lleva un verbo conocido en el nombre PASA (p.ej. `musica_orquestar`).
   El arreglo correcto es marcarla `danger=True` en el registry, no crecer esta
   lista: por eso el punto 1 es el primero.
"""
from __future__ import annotations

MODOS = ("ejecutar", "plan")
MODO_DEFECTO = "ejecutar"

# Lista base de tools que el modo plan bloquea (ver punto 2 del docstring).
# Cada nombre existe HOY en el registry salvo 'powershell', que se deja puesto
# porque es el nombre natural de una tool de shell en Windows si se agrega.
TOOLS_ESCRITURA = frozenset({
    # archivos
    "escribir_archivo", "editar_archivo", "apendar_archivo", "borrar_archivo",
    "copiar_archivo",
    # ejecucion (correr algo puede escribir cualquier cosa)
    "ejecutar", "powershell", "tests", "abrir", "contratos",
    # escriben codigo o tools invocables
    "generar_codigo", "crear_herramienta", "revertir_herramienta",
    # memoria persistente del usuario (ver trade-off en el docstring)
    "memorizar", "kg_agregar",
    # Familias OPT-IN que escriben ARCHIVOS y no llevan verbo en el nombre ni
    # danger=True: se escapaban del heuristico. Verificado leyendo su codigo:
    #   voz_decir     -> voz_tools.py: `guardar=<ruta.wav>` escribe el WAV en
    #                    una ruta ARBITRARIA (Path(guardar)), fuera del workspace.
    #   voz_clonar    -> voz_tools.py: escribe clon_<md5>.wav en _salida_voz().
    #   imagen_quitar_fondo -> image_tools.py: escribe el PNG de salida
    #                    (imagen_generar/imagen_editar ya caen por verbo).
    #   musica_orquestar -> escribe MIDI/WAV (era el ejemplo del docstring).
    # El arreglo de fondo sigue siendo marcarlas danger=True en el registry.
    "voz_decir", "voz_clonar", "imagen_quitar_fondo", "musica_orquestar",
})

# Allowlist de solo-lectura: corta el heuristico por verbo (no al danger=True).
# OJO: aca solo va lo que NO escribe NUNCA. `repo_a_prompt` estaba en esta lista
# y era falso: con `| salida` llama a dev_tools.write_file() (pisa el archivo y
# deja .bak) — pasa por _SEGUN_ARGS, no por aca.
TOOLS_LECTURA = frozenset({
    "leer_archivo", "listar", "arbol", "contar_lineas", "buscar",
    "buscar_en_repo", "repo_map", "code_grafo",
    "docs_repo", "preguntar_repo", "docs_libreria",
    "ctx_info", "ctx_ver", "ctx_grep", "ctx_partir", "rlm_llamar",
    "git_estado", "git_diff", "git_log",
    "calcular", "fecha", "http_get", "web_buscar", "web_abrir",
    "recordar", "kg_buscar", "notas", "anotar", "cuaderno", "resumir",
    "py_validar", "json_validar", "tarea_estado", "bitacora_buscar",
    "plan", "responder",
})

# Verbos que delatan escritura en el nombre de una tool no declarada.
_VERBOS_ESCRITURA = (
    "escribir", "editar", "borrar", "eliminar", "crear", "apendar", "agregar",
    "guardar", "instalar", "aplicar", "mover", "renombrar", "copiar",
    "revertir", "publicar", "subir", "enviar", "ejecutar", "correr",
    "generar", "commit", "push", "sobrescribir", "parchear",
)

MOTIVO_PLAN = (
    "BLOQUEADA por el MODO PLAN: '{tool}' escribe o ejecuta. Estas en MODO "
    "PLAN: investiga y propone; no se escribe hasta que el usuario apruebe. "
    "Usa solo tools de lectura (leer_archivo, listar, buscar, repo_map) y "
    "termina entregando el plan en pasos numerados."
)

# Estado de sesion (en proceso, sin BD). 'plan' = texto propuesto sin aprobar.
_ESTADO: dict = {"modo": MODO_DEFECTO, "plan": None}


# ── modo ──────────────────────────────────────────────────────────────────────

def modo_actual() -> str:
    """Modo vigente de la sesion: 'ejecutar' (default) o 'plan'."""
    return _ESTADO["modo"]


def activar(modo: str) -> str:
    """Fija el modo. Lanza ValueError si el nombre no es valido.

    Entrar en modo plan descarta un plan viejo ya propuesto (ese plan era de la
    tanda anterior; arrastrarlo haria que `aprobar_plan` apruebe algo que el
    usuario no acaba de leer). Salir a 'ejecutar' NO lo descarta: el CLI puede
    querer mostrarlo despues de aprobar.
    """
    nombre = (modo or "").strip().lower()
    if nombre not in MODOS:
        raise ValueError(f"Modo invalido: {modo!r}. Validos: {', '.join(MODOS)}")
    if nombre == "plan":
        _ESTADO["plan"] = None
    _ESTADO["modo"] = nombre
    return nombre


def alternar() -> str:
    """Conmuta ejecutar <-> plan (el shift+tab del REPL). Devuelve el modo nuevo."""
    return activar("ejecutar" if modo_actual() == "plan" else "plan")


def en_modo_plan() -> bool:
    return modo_actual() == "plan"


def reiniciar() -> None:
    """Vuelve al estado inicial (modo 'ejecutar', sin plan pendiente).

    Lo usa el CLI al abrir una sesion nueva y los tests para aislarse entre si;
    el estado es global por proceso (ver limites del docstring)."""
    _ESTADO["modo"] = MODO_DEFECTO
    _ESTADO["plan"] = None


# ── politica de tools ─────────────────────────────────────────────────────────

def es_de_escritura(nombre_tool: str, danger: bool = False,
                    args: str = "") -> bool:
    """True si la tool escribe/ejecuta y por lo tanto el modo plan la bloquea.

    ``danger`` viene del registry (TOOLS[nombre]["danger"]) — es la fuente de
    verdad y manda sobre todo lo demas. ``args`` solo se mira para las tools
    cuyo efecto depende de sus argumentos (hoy: delegar_subtarea).
    """
    nombre = (nombre_tool or "").strip().lower()
    if not nombre:
        return True                       # sin nombre no se puede juzgar
    if danger:
        return True                       # el registry ya la marco peligrosa
    decide = _SEGUN_ARGS.get(nombre)
    if decide is not None:
        return decide(args)
    if nombre in TOOLS_ESCRITURA:
        return True
    if nombre in TOOLS_LECTURA:
        return False
    if nombre.startswith("git_"):
        return True                       # git_* que no sea de lectura conocida
    return any(v in nombre for v in _VERBOS_ESCRITURA)


def puede_usar(nombre_tool: str, danger: bool = False,
               args: str = "") -> tuple[bool, str]:
    """(permitido, motivo). En modo ejecutar siempre permite con motivo "".

    El ``motivo`` esta escrito PARA EL MODELO: dice que hacer en vez de la
    accion bloqueada, para que el loop reencauce a investigar en lugar de
    reintentar la misma tool.
    """
    if not en_modo_plan():
        return True, ""
    if not es_de_escritura(nombre_tool, danger, args):
        return True, ""
    return False, MOTIVO_PLAN.format(tool=(nombre_tool or "?").strip())


def _delegacion_escribe(args: str) -> bool:
    """delegar_subtarea: 'investigador' es solo-lectura, 'implementador' escribe.

    El rol es el primer campo de los args ('rol | subtarea', formato confirmado
    en el doc del registry). Sin rol legible -> True (conservador: no se sabe
    que va a hacer el sub-agente)."""
    rol = (args or "").split("|", 1)[0].strip().lower()
    return rol != "investigador"


def _repo_a_prompt_escribe(args: str) -> bool:
    """repo_a_prompt: 'repo_a_prompt <ruta-o-url>' LEE; con '| salida' ESCRIBE.

    El segundo campo es un archivo de salida y el tool lo escribe con
    dev_tools.write_file() (pisa lo que haya, dejando .bak). Leer un repo es
    justo lo que el investigador necesita en modo plan, asi que se bloquea solo
    la forma que escribe, no la tool entera."""
    partes = (args or "").split("|", 1)
    return len(partes) == 2 and bool(partes[1].strip())


# Tools cuyo efecto depende de los ARGUMENTOS, no del nombre (ver docstring).
# Van antes que las listas: la misma tool cae de los dos lados segun como se
# la llame, y por eso NO figuran en TOOLS_ESCRITURA/TOOLS_LECTURA.
_SEGUN_ARGS = {
    "delegar_subtarea": _delegacion_escribe,
    "repo_a_prompt": _repo_a_prompt_escribe,
}


# ── plan propuesto ────────────────────────────────────────────────────────────

def guardar_plan(texto: str) -> str:
    """Guarda el plan propuesto (pendiente de aprobacion) y lo devuelve.

    Lanza ValueError con texto vacio: un plan vacio aprobado dejaria al agente
    sin objetivo, y ese fallo es mejor ruidoso que silencioso."""
    plan = (texto or "").strip()
    if not plan:
        raise ValueError("El plan esta vacio: no hay nada que aprobar")
    _ESTADO["plan"] = plan
    return plan


def plan_pendiente() -> str | None:
    """El plan propuesto sin aprobar, o None."""
    return _ESTADO["plan"]


def aprobar_plan() -> str | None:
    """Aprueba el plan pendiente: pasa a modo 'ejecutar' y lo devuelve para que
    el CLI lo inyecte como objetivo. Deja de estar pendiente.

    Sin plan pendiente devuelve None y NO cambia el modo (no hubo aprobacion:
    salir de plan mode sin plan es `activar('ejecutar')`, explicito)."""
    plan = _ESTADO["plan"]
    if plan is None:
        return None
    _ESTADO["plan"] = None
    _ESTADO["modo"] = "ejecutar"
    return plan


# ── system prompt ─────────────────────────────────────────────────────────────

_SUFIJO_PLAN = """
MODO PLAN (solo lectura). Reglas de este modo:
- No escribis, no editas, no borras, no ejecutas comandos. Nada se toca todavia.
- Investiga con las tools de lectura: leer_archivo, listar, buscar, repo_map.
- Cerra con un PLAN en pasos numerados: que archivo tocas y que cambia cada uno.
- El usuario aprueba el plan antes de que se ejecute. Si te falta un dato para
  planificar, buscalo; si no se puede saber leyendo, decilo en el plan.
""".strip()


def sufijo_system(modo: str | None = None) -> str:
    """El trozo de system prompt que hay que agregar. "" en modo ejecutar.

    ``modo`` None = el vigente (lo normal); se puede pasar explicito para
    armar el prompt de un modo que todavia no se activo."""
    nombre = (modo or modo_actual()).strip().lower()
    if nombre not in MODOS:
        raise ValueError(f"Modo invalido: {modo!r}. Validos: {', '.join(MODOS)}")
    return _SUFIJO_PLAN if nombre == "plan" else ""
