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

Contrato:
- ``perfil_del_agente()`` consulta el modelo servido via /props
  (backend_activo.props, cacheado) y devuelve un dict plano con:
  tools ("nativo"|"texto"), sampling, reasoning_effort, max_tokens, n_ctx,
  y el system prompt del rol agente para ese regimen.
- Sin backend o modelo desconocido -> perfil "texto" (el camino legacy de
  siempre; degradable, jamas rompe /hacer).
- Overrides:
    COGNIA_AGENT_TOOLS=nativo|texto  fuerza el regimen (contrafactual del
                                     plan: legacy forzado sobre el 20B).
    COGNIA_AGENT_LEGACY=1            alias de texto (mas gritable en un A/B).
    COGNIA_REASONING_EFFORT=low|medium|high  esfuerzo del razonador.

Solo se declara NATIVO lo verificado de primera mano: gpt-oss servido por
llama-server con --jinja parsea tools/tool_calls de harmony en
/v1/chat/completions (probado 2026-08-09 contra :8080, build b10066:
finish_reason=tool_calls, arguments JSON, reasoning_content, usage real).
Un modelo que no este en la tabla usa el marco texto aunque quiza soporte
tools: preferible a estrenar un template no medido en produccion.
"""
from __future__ import annotations

import os

# Familias con tool-calling nativo VERIFICADO en esta maquina (substring del
# basename del GGUF, en minusculas). Agregar una familia exige repetir la
# verificacion manual del 2026-08-09 (POST con tools -> message.tool_calls).
_FAMILIAS_NATIVAS = ("gpt-oss", "gpt_oss", "gptoss")

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


def _regimen_forzado() -> str:
    """'nativo'/'texto' si hay override por env, '' si decide el modelo."""
    if os.environ.get("COGNIA_AGENT_LEGACY", "").strip() == "1":
        return "texto"
    forzado = os.environ.get("COGNIA_AGENT_TOOLS", "").strip().lower()
    return forzado if forzado in ("nativo", "texto") else ""


def perfil_del_agente(url: str = "", forzar: bool = False) -> dict:
    """El perfil de corrida del agente para el modelo servido AHORA.

    Nunca lanza: cualquier fallo (server caido, /props raro) degrada al
    perfil texto, que es el camino que siempre existio.
    """
    url = (url or url_del_backend()).rstrip("/")
    modelo, n_ctx = "", None
    try:
        from cognia.backend_activo import props
        p = props(url, forzar=forzar)
        modelo = (p.get("modelo") or "").lower()
        n_ctx = p.get("n_ctx")
    except Exception:
        modelo, n_ctx = "", None

    forzado = _regimen_forzado()
    es_nativo = any(f in modelo for f in _FAMILIAS_NATIVAS)
    if forzado:
        es_nativo = (forzado == "nativo")

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
        }

    effort = os.environ.get("COGNIA_REASONING_EFFORT", "").strip().lower()
    if effort not in ("low", "medium", "high"):
        # low: la seleccion de herramienta no necesita un ensayo; el eje
        # esfuerzo esta medido como plano (high-low +4, MDE +-8) y low corta
        # la latencia por paso. Subible por env para medir.
        effort = "low"
    return {
        "nombre": "razonador_nativo",
        "modelo": modelo,
        "url": url,
        "tools": "nativo",
        "n_ctx": n_ctx,
        # Sampling recomendado por la familia gpt-oss: temp=1.0, top_p=1.0,
        # SIN repetition penalty. El 0.0/nothink del 3B a este modelo lo
        # empobrece (y el pensamiento ya sale por reasoning_content).
        "temperature": 1.0,
        "top_p": 1.0,
        "reasoning_effort": effort,
        # Cubre pensamiento + respuesta; chat_client ademas CLAMPEA cualquier
        # pedido por debajo de MIN_TOKENS_RAZONADOR (chequeo que corre, no
        # leccion en prosa).
        "max_tokens": 4096,
        "system_perfil": "completo",
    }


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
    """
    avisos = []
    if perfil.get("tools") == "nativo":
        if int(perfil.get("max_tokens") or 0) < MIN_TOKENS_RAZONADOR:
            avisos.append(
                f"max_tokens={perfil.get('max_tokens')} < "
                f"{MIN_TOKENS_RAZONADOR} con perfil razonador: el presupuesto "
                f"no cubre el pensamiento (leccion '9 bugs identicos')")
        modelo = (perfil.get("modelo") or "").lower()
        if not any(f in modelo for f in _FAMILIAS_NATIVAS):
            avisos.append(
                f"regimen nativo FORZADO sobre '{modelo or '(sin backend)'}', "
                f"que no esta en la tabla de familias verificadas: los tool "
                f"calls pueden no parsearse")
    return avisos
