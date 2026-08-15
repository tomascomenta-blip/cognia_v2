"""
cognia/agent/capacidad.py
=========================
LA SONDA: el par (server, modelo) que responde AHORA, ¿parsea tool calls?

POR QUE EXISTE: hasta hoy el regimen del agente lo decidia un substring del
nombre del fichero GGUF — ``_FAMILIAS_NATIVAS`` en model_profiles.py, cinco
literales escritos a mano. Un modelo que no estuviera en esa lista caia al
marco de texto "ACCION: <tool> <args>" AUNQUE el server emitiera tool_calls
perfectos. El coste de esa lista esta MEDIDO en el barrido del 2026-08-13
(COMPARACION_MODELOS_20260813.md): Qwen3-4B-Thinking saca 0/26 en texto y
15/26 en nativo — el mismo modelo, el mismo hardware, 15 puntos de 26 que
dependian de si alguien se habia acordado de anadir una cadena al dict.

Declarar una capacidad no es medirla. Este modulo la MIDE: una peticion real
al server con una tool trivial, y se acepta el regimen nativo solo si vuelve
``finish_reason='tool_calls'`` con ``arguments`` que parsean como JSON. Es el
mismo metodo que el repo ya exige en todo lo demas ("codigo que corre o no
cuenta"), aplicado a la decision que gobierna el resto del arnes.

    from cognia.agent.capacidad import soporta_tools, sondar, diagnostico
    soporta_tools()                      # bool, cacheado en disco
    sondar("http://127.0.0.1:8080")      # el dict crudo de la medicion
    print(diagnostico())                 # una linea para el doctor / arranque

LA CONTRAEVIDENCIA TAMBIEN CUENTA. El mismo barrido midio que forzar nativo a
quien lo emite MAL lo hunde: qwen2.5-coder-14b pasa de 13/26 (texto) a 0/26
(nativo). Una sonda de una peticion no distingue "emite tool_calls" de "sabe
trabajar con ellas", asi que los modelos con esa medida en contra viven en
``_NATIVO_DESACONSEJADO`` y ganan a la sonda. No es la tabla vieja al reves:
aquella declaraba sin medir y por DEFECTO excluia; esta solo registra lo que
se midio en contra, con su motivo y su fecha, y no toca a nadie mas.

Cache en ``~/.cognia/capacidad_nativa.json`` indexado por (url, modelo), con
sello de tiempo: sondar cuesta ~1,6 s contra el cerebro vivo y no hace falta
pagarlo en cada tarea, pero un swap de modelo en el mismo puerto cambia la
clave y la sonda se repite sola. ``invalidar()`` la limpia a mano.

Solo stdlib. NUNCA lanza: cualquier fallo (server caido, 404, timeout, JSON
raro) es un "no soporta" con motivo legible, que degrada al camino de texto
de siempre.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Modelos con el regimen nativo MEDIDO EN CONTRA. Substring del basename del
# GGUF en minusculas -> (motivo, fecha). Ganan a la sonda: emiten tool_calls
# bien formados y aun asi rinden peor que en texto, que es justo lo que una
# sonda de una peticion no puede ver. Anadir aqui EXIGE la medicion que lo
# respalde (un banco, no una impresion), igual que quitarlo.
_NATIVO_DESACONSEJADO = {
    "qwen2.5-coder-14b": (
        "banco de agente 2026-08-13: 13/26 en texto contra 0/26 en nativo "
        "forzado (COMPARACION_MODELOS_20260813.md)", "2026-08-13"),
    "openreasoning": (
        "banco de agente 2026-08-13: 2/26 en texto contra 0/26 en nativo "
        "forzado (COMPARACION_MODELOS_20260813.md)", "2026-08-13"),
}

# Cuanto vale una medicion antes de repetirla. Un llama-server no cambia de
# modelo sin reiniciar (y reiniciar cambia la clave), asi que el TTL solo
# protege del caso raro: el mismo binario recargado con otras banderas
# (--jinja puesto o quitado) sobre el mismo GGUF y el mismo puerto.
_TTL_S = 24 * 3600

_TIMEOUT_S = 30

# La tool de la sonda: un parametro obligatorio, nombre corto, sin ambiguedad
# posible. Se pide por su nombre en el user para que hasta un modelo tibio la
# llame; si aun asi contesta prosa, es exactamente el caso que buscamos.
_TOOL_SONDA = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Devuelve el texto que se le pasa. Herramienta de prueba.",
        "parameters": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "texto a devolver"}},
            "required": ["x"],
        },
    },
}
_USER_SONDA = "Llama a la herramienta ping con x=hola. No expliques nada."

# Cache en memoria del proceso (clave -> registro), encima del de disco.
_mem: dict = {}


def _home() -> Path:
    """~/.cognia, o COGNIA_HOME si el entorno lo redirige (misma convencion
    que first_run: sin esto no habria manera de probar sobre un HOME virgen)."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo) if crudo else Path.home() / ".cognia"


def _path_cache() -> Path:
    return _home() / "capacidad_nativa.json"


def url_por_defecto() -> str:
    """La URL del server del agente (misma convencion que model_profiles)."""
    return (os.environ.get("COGNIA_LLM_URL")
            or "http://127.0.0.1:8080").rstrip("/")


def _modelo_de(url: str) -> str:
    """El basename del GGUF servido, '' si el server no responde."""
    try:
        from cognia.backend_activo import props
        return (props(url) or {}).get("modelo") or ""
    except Exception:
        return ""


def _clave(url: str, modelo: str) -> str:
    return f"{url}|{modelo or '?'}"


def _leer_cache() -> dict:
    try:
        with open(_path_cache(), "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except Exception:
        # Fichero ausente, corrupto o ilegible: la sonda se repite, que es
        # barata. Un cache es una optimizacion, jamas una dependencia.
        return {}


def _escribir_cache(datos: dict) -> None:
    try:
        p = _path_cache()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
        tmp.replace(p)   # atomico: dos procesos no dejan un JSON a medias
    except Exception:
        pass


def desaconsejado(modelo: str) -> str:
    """El motivo por el que este modelo NO debe ir nativo, '' si no hay."""
    bajo = (modelo or "").lower()
    for trozo, (motivo, fecha) in _NATIVO_DESACONSEJADO.items():
        if trozo in bajo:
            return f"{motivo} [{fecha}]"
    return ""


def sondar(url: str = "", timeout: float = _TIMEOUT_S) -> dict:
    """UNA peticion real: ¿este server emite tool calls parseables?

    Devuelve siempre un dict, nunca lanza:
      soporta_tools  bool     el veredicto
      motivo         str      por que (legible para un humano)
      finish_reason  str      lo que dijo el server
      modelo         str      basename del GGUF que respondio
      argumentos_json bool    los arguments parsearon como JSON
      nombre_ok      bool     llamo a la tool que se le pidio
      latencia_s     float
      cuando         float    epoch de la medicion
    """
    url = (url or url_por_defecto()).rstrip("/")
    modelo = _modelo_de(url)
    r = {"soporta_tools": False, "motivo": "", "finish_reason": "",
         "modelo": modelo, "argumentos_json": False, "nombre_ok": False,
         "latencia_s": 0.0, "cuando": time.time(), "url": url}

    def _tirar(max_tokens: int, kwargs_plantilla: dict) -> tuple:
        """Una peticion de sonda. Devuelve (crudo, error) — nunca lanza."""
        cuerpo_d = {
            # El campo model lo ignora llama-server (sirve UN modelo) pero lo
            # exigen otros backends compatibles con la API de OpenAI.
            "model": modelo or "local",
            "messages": [{"role": "user", "content": _USER_SONDA}],
            "tools": [_TOOL_SONDA],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        if kwargs_plantilla:
            cuerpo_d["chat_template_kwargs"] = kwargs_plantilla
        try:
            pedido = urllib.request.Request(
                url + "/v1/chat/completions",
                data=json.dumps(cuerpo_d).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(pedido, timeout=timeout) as resp:
                return json.loads(
                    resp.read().decode("utf-8", errors="replace")), ""
        except urllib.error.HTTPError as e:
            return None, (f"el server respondio HTTP {e.code} a "
                          f"/v1/chat/completions")
        except Exception as e:
            return None, (f"no se pudo consultar al server: "
                          f"{type(e).__name__}: {e}")

    def _leer(crudo: dict) -> tuple:
        try:
            choice = (crudo.get("choices") or [{}])[0]
            mensaje = choice.get("message") or {}
            return (str(choice.get("finish_reason") or ""),
                    mensaje.get("tool_calls") or [], "")
        except Exception:
            return "", [], ("la respuesta del server no tiene la forma de la "
                            "API OpenAI")

    t0 = time.time()
    crudo, err = _tirar(256, {})
    if err:
        r["latencia_s"] = round(time.time() - t0, 2)
        r["motivo"] = err
        return r
    r["latencia_s"] = round(time.time() - t0, 2)
    r["finish_reason"], llamadas, err = _leer(crudo)
    if err:
        r["motivo"] = err
        return r

    if r["finish_reason"] == "length":
        # NO es "no soporta tools": es que se quedo sin presupuesto. Un
        # razonador gasta el canal de pensamiento ANTES de emitir la llamada,
        # y 256 tokens no lo cubren (Nemotron 3.5 con enable_thinking=True
        # falla asi el 2026-08-14, y el motivo viejo acusaba a --jinja: un
        # diagnostico FALSO que mandaba al 30B al regimen de texto legacy).
        # El reintento apaga el pensamiento donde se puede y ensancha el
        # presupuesto; si con eso llama, la capacidad ESTA y lo que faltaba
        # eran tokens.
        #
        # Se reintenta HAYA o NO llamadas: el corte por presupuesto parte el
        # tool call a la mitad y deja unos arguments truncados ('{"x":"hola')
        # que parecen "el modelo emite JSON invalido" — medido, y es el mismo
        # veredicto falso una capa mas abajo.
        kwargs = {}
        try:
            from cognia.agent.model_profiles import _cfg_familia, _kwargs_plantilla
            cfg, _fam = _cfg_familia(modelo)
            kwargs = _kwargs_plantilla(cfg or {})
            if kwargs:
                kwargs = dict(kwargs, enable_thinking=False)
        except Exception:
            kwargs = {}
        crudo2, err2 = _tirar(1024, kwargs)
        if not err2 and crudo2:
            fr2, llamadas2, _ = _leer(crudo2)
            r["latencia_s"] = round(time.time() - t0, 2)
            if llamadas2:
                r["finish_reason"], llamadas = fr2, llamadas2
                r["reintento"] = ("la primera sonda murio por presupuesto "
                                  "(256 tokens); con 1024"
                                  f"{' y sin pensamiento' if kwargs else ''} "
                                  "si emitio el tool call")
            else:
                r["finish_reason"] = fr2 or r["finish_reason"]
                # Y se DESCARTA lo de la primera pasada: si el reintento no
                # llamó, lo que quedaba en `llamadas` era el tool call
                # TRUNCADO por presupuesto, y juzgarlo daba el veredicto
                # "emitió un tool call pero sus arguments no son JSON válido"
                # — otra vez culpando al modelo de un corte nuestro.
                llamadas = llamadas2

    if not llamadas:
        # El caso exacto que hunde una tarea sin avisar: sin --jinja el server
        # devuelve la prosa del modelo y el bucle nativo lee "sin tool_calls"
        # como FIN NATURAL, o sea cierra en el paso 1 sin ejecutar nada.
        if r["finish_reason"] == "length":
            r["motivo"] = ("se quedo sin tokens ANTES de emitir el tool call "
                           "(finish_reason=length) hasta con 1024 de "
                           "presupuesto: el modelo razona mas de lo que cabe "
                           "en la sonda, no es que no sepa llamar tools")
        else:
            r["motivo"] = (f"respondio sin tool_calls (finish_reason="
                           f"{r['finish_reason'] or 'vacio'}): el server no "
                           f"parsea tools — ¿le falta --jinja, o el modelo no "
                           f"las soporta?")
        return r

    fn = (llamadas[0] or {}).get("function") or {}
    r["nombre_ok"] = (fn.get("name") == "ping")
    args = fn.get("arguments")
    if isinstance(args, dict):
        # Algun backend ya lo entrega deserializado; cuenta igual.
        r["argumentos_json"] = True
    else:
        try:
            json.loads(args if isinstance(args, str) else "")
            r["argumentos_json"] = True
        except Exception:
            r["argumentos_json"] = False

    if not r["argumentos_json"]:
        r["motivo"] = ("emitio un tool call pero sus arguments no son JSON "
                       "valido: el arnes no podria leer los parametros")
        return r

    contra = desaconsejado(modelo)
    if contra:
        r["motivo"] = (f"emite tool calls correctos, PERO tiene el regimen "
                       f"nativo medido en contra: {contra}")
        return r

    r["soporta_tools"] = True
    r["motivo"] = (f"tool call valido en {r['latencia_s']}s "
                   f"(finish_reason={r['finish_reason'] or 'n/d'}"
                   f"{'' if r['nombre_ok'] else ', con otro nombre de tool'})"
                   + (f"; {r['reintento']}" if r.get("reintento") else ""))
    return r


def medicion(url: str = "", forzar: bool = False) -> dict:
    """La sonda con cache (memoria -> disco -> medir). Nunca lanza."""
    url = (url or url_por_defecto()).rstrip("/")
    modelo = _modelo_de(url)
    clave = _clave(url, modelo)

    if not forzar:
        reg = _mem.get(clave)
        if reg is None:
            reg = _leer_cache().get(clave)
        if isinstance(reg, dict) and reg.get("cuando"):
            if (time.time() - float(reg.get("cuando") or 0)) < _TTL_S:
                _mem[clave] = reg
                return reg

    reg = sondar(url)
    _mem[clave] = reg
    datos = _leer_cache()
    datos[clave] = reg
    _escribir_cache(datos)
    return reg


def soporta_tools(url: str = "", forzar: bool = False) -> bool:
    """¿El agente puede hablarle a este server en tool-calling nativo?"""
    return bool(medicion(url, forzar=forzar).get("soporta_tools"))


def invalidar(url: str = "") -> None:
    """Olvida lo medido (todo, o solo lo de esa URL). La llaman
    backend_activo.resetear_cache() y el summoner al relanzar un rol: si el
    server cambio, la medicion vieja habla de un modelo que ya no esta."""
    global _mem
    if not url:
        _mem = {}
        try:
            _path_cache().unlink()
        except Exception:
            pass
        return
    url = url.rstrip("/")
    _mem = {k: v for k, v in _mem.items() if not k.startswith(url + "|")}
    datos = _leer_cache()
    quedan = {k: v for k, v in datos.items() if not k.startswith(url + "|")}
    if quedan != datos:
        _escribir_cache(quedan)


def diagnostico(url: str = "", forzar: bool = False) -> str:
    """Una linea para el doctor, el arranque y los avisos del CLI."""
    reg = medicion(url, forzar=forzar)
    modelo = reg.get("modelo") or "(sin backend)"
    if reg.get("soporta_tools"):
        return f"regimen NATIVO con {modelo}: {reg.get('motivo')}"
    return f"regimen TEXTO con {modelo}: {reg.get('motivo')}"


def main(argv: Optional[list] = None) -> int:
    """`python -m cognia.agent.capacidad [url] [--forzar]`: la medicion a mano."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    forzar = "--forzar" in argv
    urls = [a for a in argv if not a.startswith("--")]
    reg = medicion(urls[0] if urls else "", forzar=forzar)
    print(json.dumps(reg, ensure_ascii=False, indent=2))
    return 0 if reg.get("soporta_tools") else 1


if __name__ == "__main__":
    raise SystemExit(main())
