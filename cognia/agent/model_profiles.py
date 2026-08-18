"""
cognia/agent/model_profiles.py
==============================
Perfil del agente POR MODELO SERVIDO (A3 de la obra 2026-08-09).

POR QUE EXISTE: el arnes trataba a todo modelo como si fuera el 3B de la
instalacion por defecto — temperature=0.0, nothink, marco ACCION: por regex,
stop=['\\nACCION:'] que decapita razonadores. La evidencia baseline del
2026-08-09 lo muestra: gpt-oss-20b respondia BIEN en su formato harmony
nativo y el loop no lo entendia ("2 pasos sin ACCION valida" -> cierre por
prosa -> 0/1 en una tarea trivial). El corse del 3B pasa a ser UN perfil,
no EL default.

EL ADAPTADOR DEFINITIVO (2026-08-13). Hasta hoy este modulo decidia el
REGIMEN con `fam in modelo` contra cinco literales escritos a mano: un
modelo fuera de esa lista caia al marco de texto AUNQUE el server emitiera
tool_calls perfectos. El coste esta MEDIDO en el barrido del 2026-08-13
(COMPARACION_MODELOS_20260813.md): Qwen3-4B-Thinking saca 0/26 en texto y
15/26 en nativo — el mismo modelo, el mismo hardware, 15 puntos de 26 que
dependian de si alguien se habia acordado de anadir una cadena al dict.
Lo que era UN substring se parte en DOS decisiones independientes:

  CAPACIDAD (¿tool calls?) -> la MIDE cognia.agent.capacidad: una peticion
    real al server con una tool trivial. Nombre del fichero: irrelevante.
  SAMPLING (¿con que temperatura?) -> la tabla de familias de abajo, que ya
    NO decide el regimen y que ademas se extiende SIN TOCAR CODIGO desde
    ~/.cognia/perfiles_modelo.json. Y si el modelo no casa con ninguna
    familia, la base la da el propio server (default_generation_settings de
    /props) en vez del 0.7/0.8 Qwen-like inventado que habia aqui — que era
    exactamente el vicio que esta tarea elimina: declarar en vez de medir.

Contrato:
- ``perfil_del_agente()`` consulta el modelo servido via /props
  (backend_activo.props, cacheado con TTL) + la sonda de capacidad
  (cacheada 24h por (url, modelo)) y devuelve un dict plano con:
  tools ("nativo"|"texto"), sampling, reasoning_effort, max_tokens, n_ctx,
  motivo (POR QUE ese regimen) y el system prompt del rol agente.
- Sin backend o sonda negativa -> perfil "texto" (el camino legacy de
  siempre; degradable, jamas rompe /hacer).
- Overrides (GANAN a la sonda, son el contrafactual del plan):
    COGNIA_AGENT_TOOLS=nativo|texto  fuerza el regimen.
    COGNIA_AGENT_LEGACY=1            alias de texto (mas gritable en un A/B).
    COGNIA_REASONING_EFFORT=low|medium|high  esfuerzo del razonador.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Sampling POR FAMILIA. OJO: esta tabla ya NO decide si el regimen es nativo
# (eso lo mide la sonda); solo dice CON QUE PARAMETROS hablarle a una familia
# conocida, porque el 1.0/1.0 de harmony DISPERSA a un Qwen y el 0.7/0.8 de
# Qwen empobrece a gpt-oss. Un modelo que no case con ninguna entrada usa la
# base que declara el propio server, no un invento de este fichero.
#
#   usa_effort: si el reasoning_effort viaja por chat_template_kwargs (solo
#     harmony lo consume; Qwythos lo ACEPTA pero es no-op, asi que no se pasa).
_FAMILIAS_NATIVAS = {
    # gpt-oss / harmony: temp=1.0, top_p=1.0, SIN repetition penalty, esfuerzo
    # por chat_template_kwargs.reasoning_effort (2026-08-09, :8080, b10066).
    "gpt-oss": {"temperature": 1.0, "top_p": 1.0, "usa_effort": True},
    "gpt_oss": {"temperature": 1.0, "top_p": 1.0, "usa_effort": True},
    "gptoss":  {"temperature": 1.0, "top_p": 1.0, "usa_effort": True},
    # Qwythos-9B: sampling Qwen (0.7/0.8) medido 2026-08-09. Es RAZONADOR:
    # piensa fuerte hasta en prompts triviales (854 chars de reasoning para
    # "LISTO"; max_tokens=32 -> content vacio, medido) -> el presupuesto de
    # razonador y el clamp MIN_TOKENS_RAZONADOR lo protegen igual que a
    # gpt-oss.
    #
    # NO ES QWEN2.5. Hasta el 2026-08-17 esta linea (y flota.py:63) decian
    # "Qwen2.5 abliterado"; los metadatos del GGUF dicen otra cosa y estan
    # VERIFICADOS con cognia.agent.gguf_meta contra el fichero real:
    #   general.architecture      = qwen35
    #   general.base_model.0.name = Qwen3.5 9B  (repo Qwen/Qwen3.5-9B)
    #   qwen35.context_length     = 1048576 (yarn 4.0 sobre 262144)
    #   qwen35.block_count        = 33, de los cuales 9 con attn_k y 24 SSM
    # O sea: hibrido atencion+SSM de OTRA generacion. El coste de creerse el
    # nombre no era solo documental -> ver `piensa` mas abajo.
    #
    # `piensa` NO se declara aca A PROPOSITO: lo MIDE _conducta_medida() de la
    # plantilla que el server sirve. Declararlo seria repetir el error.
    "qwythos": {"temperature": 0.7, "top_p": 0.8, "usa_effort": False},
    # Nemotron 3.5 Lightning 30B-A3B (2026-08-14): MoE hibrido Mamba2 con
    # ventana NATIVA de 1.048.576 (medida entera en esta maquina: prompt real
    # de 1.046.706 tokens, aguja recuperada, 14.622 MiB de VRAM). El sampling
    # 1.0/0.95 NO es un invento: lo declara el propio GGUF en
    # general.sampling.temp / general.sampling.top_p.
    #
    # piensa: su chat template arranca con enable_thinking=True y el
    # razonamiento viaja por chat_template_kwargs (NO por reasoning_effort,
    # que es de harmony). Con thinking ON y max_tokens corto el content sale
    # VACIO -- el mismo modo de fallo que ya tuvo qwythos, por eso el clamp
    # MIN_TOKENS_RAZONADOR aplica igual.
    # La clave es 'nemotron-3.5' y NO 'nemotron': OpenReasoning-Nemotron-14B
    # es otra familia (Qwen2.5 destilado por NVIDIA) y con la clave corta se
    # llevaba este sampling y un enable_thinking que su plantilla NO lee.
    # Cuarta tabla del repo que casa por substring; el match va de patron mas
    # largo a mas corto para que el orden de escritura deje de importar.
    "nemotron-3.5": {"temperature": 1.0, "top_p": 0.95, "usa_effort": False,
                     "piensa": True},
}

# EL BACKSTOP DE METADATOS (2026-08-17). La tabla de arriba casa por SUBSTRING
# DEL NOMBRE DEL FICHERO, y la memoria del repo ya cobro esa factura: "toda
# tabla que decida por nombre de modelo es una bomba". Renombrar un GGUF, o
# bajarlo de otro repo con otro nombre, deja al modelo sin su sampling medido
# y sin decir nada.
#
# Aca la clave es `general.architecture`, que viaja DENTRO del fichero. Las
# tres entradas estan LEIDAS de los GGUF de esta maquina (no deducidas):
#   qwen35         <- Huihui-Qwythos-9B-...-abliterated-Q4_K.gguf
#   gpt-oss        <- gpt-oss-20b-MXFP4.gguf
#   nemotron_h_moe <- nemotron-3.5-lightning-30b-a3b-Q4_0.gguf
# El valor apunta a una entrada de _FAMILIAS_NATIVAS para NO duplicar numeros:
# el sampling sigue teniendo una sola fuente de verdad.
#
# Es BACKSTOP y no reemplazo: solo se consulta cuando el nombre no caso con
# nada, asi que ningun modelo que hoy funciona cambia de perfil. Deliberadamente
# NO mapea 'qwen2' ni 'qwen3': arquitecturas con decenas de modelos distintos
# (el coder-14b y OpenReasoning-Nemotron-14B son los dos 'qwen2') donde una
# entrada seria otra vez declarar en vez de medir.
_ARCH_A_FAMILIA = {
    "qwen35": "qwythos",
    "gpt-oss": "gpt-oss",
    "nemotron_h_moe": "nemotron-3.5",
}

# Familias cuyo razonamiento se enciende/apaga por chat_template_kwargs.
# COGNIA_THINKING=on|off pisa el default de la familia.
_CLAVE_THINKING = "enable_thinking"

# Claves de sampling que este modulo propaga al camino del agente. El resto de
# lo que declare el server (top_k, min_p, dry_*) no lo consume chat_client, y
# copiarlo seria fingir un control que no existe.
#
# repeat_penalty NO ESTA, y su ausencia esta medida (revision adversarial
# 2026-08-13): el sampling del agente lo arma loop.py:409-415 con
# {temperature, top_p, max_tokens, reasoning_effort, url} — repeat_penalty no
# viaja, y cli.py:10503 lo excluye A PROPOSITO ("rp=1.3 empujaba al 3B a
# basura", la regresion de 3.8.4 que llego a PyPI). Propagarlo aqui pintaba un
# control configurable — poner repeat_penalty en perfiles_modelo.json y ver el
# numero en el perfil — que no llegaba a NINGUN consumidor: dato muerto que
# aparenta gobernar. Cablearlo de verdad exige el GATE del camino feliz (5/5,
# CLAUDE.md:100-106) y la evidencia del repo hoy dice que rp!=1.0 hunde al
# agente, asi que la unica opcion honesta es no fingirlo.
_CLAVES_SAMPLING = ("temperature", "top_p")

# Presupuesto minimo del camino del agente con un razonador: max_tokens tiene
# que cubrir el PENSAMIENTO ademas de la respuesta (leccion "9 bugs identicos"
# de la memoria del repo). Nada por debajo de esto sale hacia el modelo.
MIN_TOKENS_RAZONADOR = 1024

# El system del agente NATIVO. No es el _AGENTE de system_prompt.py (ese
# habla del marco ACCION:/responder, que aca no existe): el cierre nativo es
# "responder sin tool calls".
_ROL_AGENTE_NATIVO = """\
TU PAPEL AHORA
Sos el agente de herramientas: no conversas, ejecutas. Tenes una tarea
concreta y herramientas nativas (tool calls). Llama las herramientas que
necesites; cada resultado te vuelve como turno de tool. Cuando la tarea este
HECHA y VERIFICADA, responde SIN llamar herramientas, con el resultado
concreto: esa respuesta final cierra la tarea.
- Verifica antes de cerrar: si la tarea pide ejecutar algo, ejecutalo de
  verdad y mostra su salida real.
- Si una herramienta devuelve ERROR dos veces con los mismos argumentos,
  cambia de estrategia: el problema es la hipotesis, no la suerte.
- Las rutas de archivo son relativas al directorio de trabajo actual.
- Honestidad: si no se pudo, cerra explicando que probaste y el error exacto."""


def url_del_backend() -> str:
    """La URL del server del agente (misma convencion que backend_activo)."""
    return (os.environ.get("COGNIA_LLM_URL")
            or "http://127.0.0.1:8080").rstrip("/")


def n_ctx_del_backend(url: str = ""):
    """La ventana del server servido AHORA, o None. SIN SONDAR.

    POR QUE EXISTE (regresion MEDIDA el 2026-08-13): quien solo quiere un
    metadato del server no debe pagar la sonda de capacidad, que hace un POST
    real de generacion. La barra de estado del REPL (cli.py:6467) llamaba a
    perfil_del_agente() unicamente para sacar n_ctx, y prompt_toolkit la
    invoca EN CADA REDIBUJADO del prompt: con el cache de la sonda frio el
    primer pintado pasaba de 0,064 s a 3,42 s (medido, mismo :8080), y hasta
    los 30 s de capacidad._TIMEOUT_S si el server responde lento.

    /props es un GET local (~3 ms) y ademas ya viene cacheado con TTL, asi que
    esta via es la barata para todo consumidor que NO decide regimen.
    """
    try:
        from cognia.backend_activo import props
        return (props((url or url_del_backend()).rstrip("/")) or {}).get("n_ctx")
    except Exception:
        # Igual que perfil_del_agente: un metadato ausente jamas rompe a quien
        # lo pide (la barra pinta 'ctx ?', no revienta el REPL).
        return None


def _regimen_forzado() -> str:
    """'nativo'/'texto' si hay override por env, '' si decide la sonda."""
    if os.environ.get("COGNIA_AGENT_LEGACY", "").strip() == "1":
        return "texto"
    forzado = os.environ.get("COGNIA_AGENT_TOOLS", "").strip().lower()
    return forzado if forzado in ("nativo", "texto") else ""


def path_perfiles_usuario() -> Path:
    """~/.cognia/perfiles_modelo.json (COGNIA_HOME lo redirige, igual que en
    capacidad.py: sin esto no habria manera de probar sobre un HOME virgen)."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    home = Path(crudo) if crudo else Path.home() / ".cognia"
    return home / "perfiles_modelo.json"


def familias_usuario() -> dict:
    """La tabla de sampling del USUARIO: {familia: {temperature, top_p,
    usa_effort}}. Cualquier otra clave (repeat_penalty, top_k, min_p...) se
    IGNORA en silencio a proposito: no hay consumidor para ellas en el camino
    del agente (loop.py:409-415) y aceptarlas seria prometer un control que no
    existe. EXTIENDE y PISA a _FAMILIAS_NATIVAS, para
    que estrenar un modelo nuevo sea editar un JSON y no editar codigo (que es
    lo que hacia falta hasta hoy, y por eso la tabla llevaba meses con cinco
    entradas). Fichero ausente/corrupto -> {} y se sigue: es configuracion,
    jamas una dependencia."""
    try:
        with open(path_perfiles_usuario(), "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except Exception:
        return {}
    if not isinstance(datos, dict):
        return {}
    limpio = {}
    for fam, cfg in datos.items():
        if isinstance(fam, str) and isinstance(cfg, dict):
            limpio[fam.lower()] = cfg
    return limpio


def familia_por_arch(ruta: str) -> tuple:
    """(cfg, familia) deducidos de `general.architecture` del GGUF en `ruta`.

    (None, '') si no hay ruta, el fichero no se puede leer, o la arquitectura
    no esta en _ARCH_A_FAMILIA. Nunca lanza: es un backstop, no un requisito.
    """
    if not ruta:
        return None, ""
    try:
        from cognia.agent.gguf_meta import meta
        arch = (meta(ruta) or {}).get("arch") or ""
    except Exception:
        return None, ""
    fam = _ARCH_A_FAMILIA.get(arch.lower())
    if fam and fam in _FAMILIAS_NATIVAS:
        return dict(_FAMILIAS_NATIVAS[fam]), fam
    return None, ""


def _conducta_medida(plantilla: str, caps: dict) -> dict:
    """{piensa, usa_effort} LEIDOS de la plantilla que el server sirve.

    POR QUE (2026-08-17). Estos dos booleanos venian de un dict escrito a mano
    y a Qwythos le faltaba `piensa`: su plantilla SI lee `enable_thinking`
    (verificado en el GGUF), asi que `COGNIA_THINKING=off` era un NO-OP mudo
    sobre el cerebro principal de la casa — el usuario apagaba el pensamiento
    y el modelo seguia pensando.

    La regla es la plantilla, que es el unico sitio donde esos kwargs se
    consumen de verdad. Contrastada contra los 6 GGUF de esta maquina
    (2026-08-17): reproduce EXACTO las 5 entradas escritas a mano
    (gpt-oss reasoning_effort, nemotron-3.5 enable_thinking, y coder-14b /
    OpenReasoning-14B / Qwen3-4B-Thinking sin ninguno de los dos) y agrega el
    unico que faltaba, qwythos. Una regla que reproduce la tabla y ademas tapa
    su agujero es la que se queda.

    `caps` es chat_template_caps de /props: llama-server ya calcula
    supports_reasoning_effort parseando la plantilla, asi que cuando viene se
    prefiere a nuestro substring.
    """
    out = {}
    t = plantilla or ""
    if t:
        out["piensa"] = _CLAVE_THINKING in t
    soporte = (caps or {}).get("supports_reasoning_effort")
    if isinstance(soporte, bool):
        out["usa_effort"] = soporte
    elif t:
        out["usa_effort"] = "reasoning_effort" in t
    return out


def _cfg_familia(modelo: str, ruta: str = "") -> tuple:
    """(cfg, nombre_familia) de la primera familia que case por substring, con
    el fichero del usuario mirado ANTES que la tabla del codigo (asi 'pisa').

    Si NINGUN nombre casa y hay `ruta` al GGUF, se cae al backstop por
    arquitectura (familia_por_arch): el nombre del fichero se puede cambiar,
    `general.architecture` no. (None, '') si tampoco por ahi."""
    bajo = (modelo or "").lower()
    if bajo:
        # De patron MAS LARGO a mas corto en las dos tablas: 'nemotron-3.5'
        # tiene que ganarle a 'nemotron' aunque alguien escriba las entradas
        # en otro orden. Es la misma colision que ya mordio en flota.CEREBROS
        # y en servir_modelo.PERFILES_ARRANQUE.
        usuario = familias_usuario()
        for fam in sorted((f for f in usuario if f), key=len, reverse=True):
            if fam in bajo:
                return dict(usuario[fam]), fam
        for fam in sorted(_FAMILIAS_NATIVAS, key=len, reverse=True):
            if fam in bajo:
                return dict(_FAMILIAS_NATIVAS[fam]), fam
    return familia_por_arch(ruta)


def _sampling_base(props_sampling: dict, cfg: dict) -> tuple:
    """(sampling, origen) para el camino nativo.

    Orden de precedencia, de menos a mas fiable:
      1. 0.7/0.8 Qwen-like — ULTIMO RECURSO, solo si el server no dijo nada
         (esta es la linea que antes se aplicaba a TODO modelo desconocido).
      2. default_generation_settings de /props: lo que el propio server usa.
      3. la familia (medida a mano en esta maquina), si el modelo casa.
    """
    sampling = {"temperature": 0.7, "top_p": 0.8}
    origen = "fallback 0.7/0.8 (el server no declaro sampling)"
    base = {k: v for k, v in (props_sampling or {}).items()
            if k in _CLAVES_SAMPLING and isinstance(v, (int, float))}
    if base:
        sampling.update(base)
        origen = "default_generation_settings del server"
    if cfg:
        puestos = {k: cfg[k] for k in _CLAVES_SAMPLING
                   if isinstance(cfg.get(k), (int, float))}
        sampling.update(puestos)
    return sampling, origen


def _kwargs_plantilla(cfg: dict) -> dict:
    """chat_template_kwargs que pide la FAMILIA, con override por entorno.

    Solo devuelve algo para familias que declaran `piensa`: para todas las
    demas el body sale byte-identico al historico (el contrafactual del
    adaptador nativo no se puede romper por agregar una familia).

    COGNIA_THINKING=on|off pisa el default. Existe porque el eje es MEDIBLE:
    con Nemotron el razonamiento cuesta ~50 tok/s de latencia por paso del
    bucle, y hasta no tener el A/B corrido el default es lo que el modelo
    trae entrenado (on).
    """
    # `piensa` falso o ausente = la plantilla NO lee enable_thinking -> no se
    # manda nada y el body sale byte-identico al historico. Desde que
    # _conducta_medida rellena la clave, `not cfg.get(...)` y el viejo
    # `"piensa" not in cfg` valen lo mismo para las familias escritas a mano
    # (ninguna declara piensa=False) y evitan mandarle enable_thinking=False
    # a un coder-14b cuya plantilla lo ignora.
    if not cfg.get("piensa"):
        return {}
    env = os.environ.get("COGNIA_THINKING", "").strip().lower()
    if env in ("on", "1", "true", "si"):
        piensa = True
    elif env in ("off", "0", "false", "no"):
        piensa = False
    else:
        piensa = bool(cfg.get("piensa"))
    return {_CLAVE_THINKING: piensa}


def perfil_del_agente(url: str = "", forzar: bool = False) -> dict:
    """El perfil de corrida del agente para el modelo servido AHORA.

    Nunca lanza: cualquier fallo (server caido, /props raro, sonda que
    revienta) degrada al perfil texto, que es el camino que siempre existio.
    """
    url = (url or url_del_backend()).rstrip("/")
    modelo, n_ctx, base = "", None, {}
    ruta, plantilla, caps = "", "", {}
    try:
        from cognia.backend_activo import props
        p = props(url, forzar=forzar)
        modelo = (p.get("modelo") or "").lower()
        n_ctx = p.get("n_ctx")
        base = dict(p.get("sampling") or {})
        # Datos CRUDOS del server para no decidir por el nombre del fichero:
        # `ruta` abre los metadatos del GGUF (arquitectura) y plantilla/caps
        # dicen si el modelo lee enable_thinking / reasoning_effort.
        ruta = str(p.get("ruta") or "")
        plantilla = str(p.get("plantilla") or "")
        caps = dict(p.get("caps") or {})
    except Exception:
        modelo, n_ctx, base = "", None, {}

    # ── (1) CAPACIDAD: se MIDE, no se deduce del nombre del fichero ────────
    forzado = _regimen_forzado()
    if forzado:
        # El override gana SIEMPRE a la sonda: es el contrafactual del plan
        # (poder forzar legacy sobre un nativo, y nativo sobre un modelo que
        # la sonda no alcanzo a medir) y el interruptor de emergencia.
        es_nativo = (forzado == "nativo")
        via, motivo = "forzado", f"regimen forzado por entorno (={forzado})"
    else:
        try:
            from cognia.agent import capacidad
            es_nativo = capacidad.soporta_tools(url, forzar=forzar)
            # medicion() aqui es un acierto de cache (soporta_tools acaba de
            # poblarla): sale gratis y trae el POR QUE legible.
            motivo = str((capacidad.medicion(url) or {}).get("motivo") or "")
            via = "sonda"
        except Exception as exc:
            es_nativo, via = False, "sonda"
            motivo = (f"la sonda de capacidad fallo ({type(exc).__name__}: "
                      f"{exc}); se degrada a texto")

    # ── (2) SAMPLING: familia (codigo o JSON del usuario) sobre la base del
    #        server. Independiente del regimen: un modelo puede ser nativo sin
    #        estar en ninguna tabla, y entonces se le habla como el server dice.
    cfg, familia = _cfg_familia(modelo)
    familia_via = "nombre del fichero"
    if not cfg:
        # Backstop: el nombre no dijo nada, la ARQUITECTURA del GGUF si puede.
        cfg, familia = familia_por_arch(ruta)
        if cfg:
            familia_via = "arch del GGUF"
    # (2b) CONDUCTA MEDIDA de la plantilla servida. La familia escrita a mano
    # pisa lo medido SOLO donde declara la clave: hoy no la contradice en
    # ninguno de los 6 GGUF de la casa, y asi un modelo nuevo no se queda sin
    # enable_thinking por no estar en la tabla (el agujero de qwythos).
    medido = _conducta_medida(plantilla, caps)
    tabla = dict(cfg or {})
    if medido:
        cfg = dict(medido, **tabla)
    sampling, origen = _sampling_base(base, cfg or {})

    if not es_nativo:
        # Perfil TEXTO (legacy): el bucle ACCION:/regex de cli.py con su
        # sampling medido para el 3B. Este dict solo informa; el camino viejo
        # no lee nada de aca (por eso el contrafactual no puede romperse).
        return {
            "nombre": "texto_legacy",
            "modelo": modelo or "(sin backend)",
            "url": url,
            "tools": "texto",
            "n_ctx": n_ctx,
            "capacidad": via,
            "motivo": motivo,
        }

    effort = ""
    if (cfg or {}).get("usa_effort"):
        effort = os.environ.get("COGNIA_REASONING_EFFORT", "").strip().lower()
        if effort not in ("low", "medium", "high"):
            # low: la seleccion de herramienta no necesita un ensayo; el eje
            # esfuerzo esta medido como plano (high-low +4, MDE +-8) y low
            # corta la latencia por paso. Subible por env para medir.
            #
            # PERO solo cuando 'low' esta MEDIDO para esa familia, o sea
            # cuando usa_effort viene de la tabla escrita a mano. Si lo unico
            # que sabemos es que la plantilla ACEPTA reasoning_effort
            # (_conducta_medida), el default se lo queda el server: inventarle
            # 'low' a un modelo que nadie midio seria cambiarle el esfuerzo
            # por defecto en silencio. Con "" el body sale byte-identico al
            # historico (chat_client solo manda la clave si hay valor).
            effort = "low" if tabla.get("usa_effort") else ""
    perfil = {
        "nombre": "razonador_nativo",
        "modelo": modelo,
        "url": url,
        "tools": "nativo",
        "n_ctx": n_ctx,
        "reasoning_effort": effort,
        # Cubre pensamiento + respuesta; chat_client ademas CLAMPEA cualquier
        # pedido por debajo de MIN_TOKENS_RAZONADOR (chequeo que corre, no
        # leccion en prosa).
        "max_tokens": 4096,
        "system_perfil": "completo",
        # Trazabilidad del adaptador: de donde salio CADA decision. Sin esto,
        # un perfil raro en produccion no se puede diagnosticar sin reproducir.
        "capacidad": via,
        "motivo": motivo,
        "familia": familia,
        "sampling_origen": (f"familia '{familia}' (por {familia_via})"
                            if familia else origen),
    }
    # La ARQUITECTURA real del GGUF, no la que sugiere el nombre. Sin este
    # campo, "Qwythos es Qwen2.5" se pudo repetir dos anos en dos ficheros sin
    # que ninguna corrida lo desmintiera.
    if ruta:
        try:
            from cognia.agent.gguf_meta import meta
            m = meta(ruta) or {}
        except Exception:
            m = {}
        if m.get("arch"):
            perfil["arch"] = m["arch"]
        if m.get("base"):
            perfil["base"] = m["base"]
    if medido:
        perfil["conducta_medida"] = dict(medido)
    kwargs_plantilla = _kwargs_plantilla(cfg or {})
    if kwargs_plantilla:
        perfil["kwargs_plantilla"] = kwargs_plantilla
    perfil.update(sampling)
    return perfil


def system_agente_nativo() -> str:
    """System prompt del agente en regimen nativo: identidad + conducta +
    rol nativo. Sin manual de tools (van como schemas) y sin el marco ACCION.
    Best-effort: sin system_prompt.py disponible, el rol solo alcanza."""
    partes = []
    try:
        from cognia.system_prompt import _CONDUCTA_COMPLETA, _IDENTIDAD
        partes = [_IDENTIDAD.strip(), _CONDUCTA_COMPLETA.strip()]
    except Exception:
        partes = []
    partes.append(_ROL_AGENTE_NATIVO.strip())
    return "\n\n".join(partes)


def verificar_arranque(perfil: dict) -> list:
    """Chequeos de coherencia perfil<->server que corren al entrar al camino
    nativo (gate del plan: no lecciones en prosa). Devuelve avisos (vacio=ok).

    El chequeo de capacidad consulta a la SONDA, no al nombre del modelo: la
    version vieja comparaba el perfil consigo mismo (mismo dict de familias
    que ya lo habia decidido), o sea no podia fallar nunca — un chequeo que
    no puede fallar no es un chequeo.
    """
    avisos = []
    if perfil.get("tools") != "nativo":
        return avisos
    if int(perfil.get("max_tokens") or 0) < MIN_TOKENS_RAZONADOR:
        avisos.append(
            f"max_tokens={perfil.get('max_tokens')} < "
            f"{MIN_TOKENS_RAZONADOR} con perfil razonador: el presupuesto "
            f"no cubre el pensamiento (leccion '9 bugs identicos')")
    modelo = (perfil.get("modelo") or "").lower() or "(sin backend)"
    if perfil.get("capacidad") == "sonda":
        # El perfil ya nacio de una medicion positiva; repetirla aqui solo
        # gastaria una peticion para leer el mismo cache.
        return avisos
    # Regimen FORZADO (o perfil armado a mano): aca SI hay algo que verificar.
    try:
        from cognia.agent import capacidad
        reg = capacidad.medicion(perfil.get("url") or url_del_backend()) or {}
    except Exception as exc:
        reg = {"soporta_tools": False,
               "motivo": f"la sonda fallo ({type(exc).__name__}: {exc})"}
    if not reg.get("soporta_tools"):
        avisos.append(
            f"regimen nativo FORZADO sobre '{modelo}' y la sonda dice que NO: "
            f"{reg.get('motivo') or 'sin motivo'} — los tool calls pueden no "
            f"parsearse")
    return avisos
