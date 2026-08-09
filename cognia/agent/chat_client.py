"""
cognia/agent/chat_client.py
===========================
Cliente UNICO del agente sobre /v1/chat/completions (A1 de la obra 2026-08-09).

POR QUE EXISTE: cada paso del agente pasaba por una plantilla ChatML
hardcodeada + POST crudo a /completion con stops de Qwen. gpt-oss (harmony)
recibia los marcadores ChatML como texto plano y el loop no entendia su
respuesta — la causa raiz medida de "el mismo modelo rinde peor en Cognia"
(evidencia baseline 2026-08-09: 0/1 en una tarea trivial).

Aca el agente manda MENSAJES ESTRUCTURADOS (system/user/assistant/tool) y
TOOLS nativas; el server aplica la plantilla del modelo (llama-server con
--jinja parsea los tool calls de harmony gratis) y este cliente expone lo
que el arnes viejo tiraba: finish_reason, usage REAL y reasoning_content.

Verificado de primera mano (2026-08-09, :8080, build b10066): POST con
tools -> finish_reason='tool_calls' + message.tool_calls con arguments JSON;
turno role='tool' + reasoning_content en el assistant aceptados de vuelta;
chat_template_kwargs.reasoning_effort aceptado; cierre en prosa ->
finish_reason='stop' sin tool_calls.

Solo stdlib (urllib). Sin streaming: el paso del agente consume la respuesta
entera; el streaming de la prosa final es asunto del renderer (WP3/WP4).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR, url_del_backend

# El agente puede tardar: un paso con pensamiento largo en CPU/GPU chica va
# por minutos, no segundos. Override por env para bancos/tests.
_TIMEOUT_S = float(os.environ.get("COGNIA_CHAT_TIMEOUT", "300"))


@dataclass
class ToolCall:
    """Un tool call parseado por el server (arguments ya como dict)."""
    id: str = ""
    nombre: str = ""
    argumentos: dict = field(default_factory=dict)
    argumentos_crudos: str = ""   # el JSON original, para el round-trip


@dataclass
class RespuestaChat:
    """Lo que el paso del agente necesita ver de una respuesta, completo.

    El arnes viejo solo miraba .text y por eso los dos modos de fallo
    (truncado por presupuesto vs stop mal puesto) se veian iguales.
    """
    texto: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str = ""       # 'stop' | 'tool_calls' | 'length' | ...
    usage: dict = field(default_factory=dict)
    reasoning_content: str = ""
    error: str = ""               # no-vacio => la peticion fallo (degradable)
    duracion_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


def _parse_tool_calls(crudos: list) -> list:
    calls = []
    for tc in crudos or []:
        fn = tc.get("function") or {}
        crudo = fn.get("arguments") or ""
        try:
            args = json.loads(crudo) if crudo else {}
            if not isinstance(args, dict):
                args = {"args": args}
        except ValueError:
            # JSON roto: no se pierde — la tool vera el crudo y su error de
            # formato volvera al modelo como turno tool (señal correcta).
            args = {"args": crudo}
        calls.append(ToolCall(id=tc.get("id") or "", nombre=fn.get("name") or "",
                              argumentos=args, argumentos_crudos=crudo))
    return calls


def completar(mensajes: list, tools: list = None, url: str = "",
              temperature: float = 1.0, top_p: float = 1.0,
              max_tokens: int = 4096, reasoning_effort: str = "",
              razonador: bool = True, timeout: float = None,
              via: str = "agente_chat") -> RespuestaChat:
    """UN turno de chat completions contra el server del agente.

    Nunca lanza: cualquier fallo vuelve como RespuestaChat(error=...) para
    que el bucle degrade con causa visible en vez de morir.
    """
    url = (url or url_del_backend()).rstrip("/")
    # Chequeo que CORRE (no leccion en prosa): con un razonador, max_tokens
    # tiene que cubrir el pensamiento. 9 bugs identicos en la memoria del
    # repo por presupuestos de 16-256 tokens que degollaban el canal analysis.
    if razonador and max_tokens < MIN_TOKENS_RAZONADOR:
        max_tokens = MIN_TOKENS_RAZONADOR

    cuerpo: dict = {
        "messages": mensajes,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if tools:
        cuerpo["tools"] = tools
    if reasoning_effort:
        # El esfuerzo REAL se fija aca, no recortando tokens (memoria:
        # presupuesto-tokens-razonamiento).
        cuerpo["chat_template_kwargs"] = {"reasoning_effort": reasoning_effort}

    t0 = time.time()
    try:
        req = urllib.request.Request(
            url + "/v1/chat/completions",
            data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT_S) as r:
            crudo = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            detalle = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detalle = ""
        return RespuestaChat(error=f"HTTP {e.code} de {url}: {detalle}",
                             duracion_s=time.time() - t0)
    except Exception as e:
        return RespuestaChat(error=f"{type(e).__name__}: {e}",
                             duracion_s=time.time() - t0)

    try:
        eleccion = (crudo.get("choices") or [{}])[0]
        msg = eleccion.get("message") or {}
        resp = RespuestaChat(
            texto=(msg.get("content") or "").strip(),
            tool_calls=_parse_tool_calls(msg.get("tool_calls")),
            finish_reason=eleccion.get("finish_reason") or "",
            usage=crudo.get("usage") or {},
            reasoning_content=(msg.get("reasoning_content") or ""),
            duracion_s=time.time() - t0,
        )
    except Exception as e:
        return RespuestaChat(error=f"respuesta inesperada del server: {e}",
                             duracion_s=time.time() - t0)

    # Constancia de quien atendio (backend_activo): auditoria jsonl + linea
    # stderr (silenciable con COGNIA_BACKEND_LOG=0). Best-effort.
    try:
        from cognia import backend_activo
        backend_activo.registrar(via, url, rol="pensar",
                                 finish=resp.finish_reason,
                                 tokens=resp.usage.get("completion_tokens"))
    except Exception:
        pass
    return resp


def mensaje_assistant(resp: RespuestaChat) -> dict:
    """El turno assistant para devolver al server en el siguiente paso.

    Preserva el CoT entre tool calls (reasoning_content round-trip verificado)
    y re-serializa los arguments con el JSON original del server."""
    msg: dict = {"role": "assistant", "content": resp.texto or ""}
    if resp.reasoning_content:
        msg["reasoning_content"] = resp.reasoning_content
    if resp.tool_calls:
        msg["tool_calls"] = [
            {"type": "function", "id": tc.id,
             "function": {"name": tc.nombre,
                          "arguments": tc.argumentos_crudos
                          or json.dumps(tc.argumentos, ensure_ascii=False)}}
            for tc in resp.tool_calls]
    return msg


def mensaje_tool(tool_call_id: str, contenido: str) -> dict:
    """El turno tool con el resultado de una herramienta."""
    return {"role": "tool", "tool_call_id": tool_call_id,
            "content": contenido or "(sin output)"}
