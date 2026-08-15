# -*- coding: utf-8 -*-
"""
cognia/agent/workflows.py
=========================
Motor MINIMO de workflows: agentes con salida estructurada validada,
presupuesto de tokens transversal, resume por journal con cache por hash y
paralelismo realista (cap 2-3: la fisica medida dice que un slot serializa y
mas hilos solo solapan I/O o cerebro+worker).

POR QUE existe (contrato congelado 2026-08-11): el veredicto medido dijo que
lo barato que falta es (1) salida estructurada con retry sobre el error REAL,
(2) techo de tokens compartido entre llamadas, (3) poder retomar una corrida
cara sin re-pagar lo ya hecho. Cero frameworks: funciones planas + dataclases,
el estilo de la casa.

Diseno anti-degradacion-silenciosa:
- El journal es append-only con flush por linea (patron bitacora.py): un
  crash deja legible todo hasta la ultima linea entera, y el resume tolera
  una linea final truncada.
- completar() nunca lanza; aca se mira .error y .finish_reason SIEMPRE.
- finish_reason == 'length' NO se reintenta igual-igual: es presupuesto, no
  formato (la leccion de los 10 bugs identicos de max_tokens).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Sampling por rol (contrato): el worker es Qwen3-4B-Thinking (0.6/0.95,
# la receta del model card); el cerebro es qwythos (0.7/0.8). Una temperatura
# explicita del caller pisa ambos; el top_p queda del rol.
_SAMPLING_WORKER = {"temperature": 0.6, "top_p": 0.95}
_SAMPLING_CEREBRO = {"temperature": 0.7, "top_p": 0.8}


class PresupuestoTokens:
    """Techo de tokens COMPARTIDO entre llamadas (viaja por parametro, jamas
    global de modulo). total=None significa sin techo. Thread-safe porque
    paralelo() registra usage desde varios hilos.

    El techo es BLANDO por diseno (documentado 2026-08-11): el corte es
    check-then-act SIN reserva — agente() mira agotado() ANTES de llamar y
    registra el usage DESPUES — asi que hasta cap llamadas concurrentes
    pueden pasar el corte cuando queda presupuesto para una sola; el
    sobregiro maximo es cap x (tokens de una llamada). Es tolerancia
    deliberada, no bug: reservar exigiria adivinar el usage de una llamada
    antes de pagarla, y el error de esa adivinanza seria peor que el
    sobregiro acotado."""

    def __init__(self, total: int = None):
        self.total = total
        self._gastado = 0
        self._lock = threading.Lock()

    def registrar(self, usage: dict) -> None:
        """Suma prompt+completion de un usage REAL del server."""
        u = usage or {}
        delta = int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0)
        with self._lock:
            self._gastado += delta

    def gastado(self) -> int:
        with self._lock:
            return self._gastado

    def restante(self) -> float:
        if self.total is None:
            return float("inf")
        return max(float(self.total - self.gastado()), 0.0)

    def agotado(self) -> bool:
        return self.total is not None and self.gastado() >= self.total


def _dir_base() -> Path:
    """Raiz de las corridas; override por env para tests y bancos."""
    override = os.environ.get("COGNIA_WORKFLOWS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "workflows"


def _nuevo_run_id(nombre: str) -> str:
    """'YYYYmmdd-HHMMSS-<slug8>' — mismo formato que estado_tarea.nuevo_task_id
    (ordenable por nombre y legible a ojo)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (nombre or "").lower())[:8].strip("-")
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + (slug or "corrida")


@dataclass
class Corrida:
    """Estado de UNA corrida de workflow. Viaja por parametro (regla
    transversal: nada de estado global nuevo de modulo)."""
    nombre: str = ""
    run_id: str = ""
    dir: Path = None
    presupuesto: PresupuestoTokens = None
    print_fn: object = print
    cache: dict = field(default_factory=dict)   # clave sha256 -> resultado ok
    _fh: object = None                          # journal.jsonl abierto en 'a'

    def _journal(self, linea: dict) -> None:
        """Append + flush por linea (patron bitacora._escribir): un crash deja
        el journal legible hasta el ultimo evento. Traga excepciones: el
        journal es constancia, no puede tumbar la corrida."""
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception as e:
            # Un thunk HUERFANO de paralelo() puede llegar aca con la corrida
            # ya cerrada (write sobre fh cerrado -> ValueError): se traga con
            # aviso a stderr en vez de en silencio (2026-08-11) — la linea se
            # pierde a sabiendas, pero la degradacion queda a la vista.
            try:
                print(f"aviso: journal no escribible "
                      f"({type(e).__name__}: {e}); linea perdida",
                      file=sys.stderr)
            except Exception:
                pass

    def cerrar(self) -> None:
        """Cierra el journal (idempotente). En Windows dejar el handle abierto
        bloquea renombres/truncados del archivo, asi que los tests y los
        callers prolijos cierran al terminar."""
        try:
            if self._fh is not None:
                self._fh.close()
        except Exception:
            pass
        self._fh = None


def _cargar_cache_de_journal(ruta: Path) -> dict:
    """Lee un journal viejo linea a linea y devuelve {clave: resultado} de los
    agente() que terminaron SIN error. Tolera la ultima linea truncada por un
    crash (json.loads falla -> se salta): el resume nunca exige un archivo
    perfecto, solo lineas enteras."""
    cache: dict = {}
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            for cruda in fh:
                cruda = cruda.strip()
                if not cruda:
                    continue
                try:
                    d = json.loads(cruda)
                except ValueError:
                    continue    # linea a medio escribir: se pierde solo esa
                if (d.get("tipo") == "agente" and not d.get("error")
                        and "resultado" in d and d.get("clave")):
                    cache[d["clave"]] = d["resultado"]
    except OSError:
        pass
    return cache


def corrida(nombre: str, presupuesto_tokens: int = None,
            resume_de: str = "", print_fn=print) -> Corrida:
    """Abre una corrida nueva bajo <base>/<run_id>/ con su journal.jsonl.

    resume_de = run_id de una corrida previa: se cargan del journal viejo los
    resultados OK de agente() y las claves identicas se sirven de cache sin
    llamar al LLM (el hit queda anotado en el journal NUEVO)."""
    c = Corrida(nombre=nombre, run_id=_nuevo_run_id(nombre),
                presupuesto=PresupuestoTokens(presupuesto_tokens),
                print_fn=print_fn or (lambda *_a, **_k: None))
    # Des-colisionar: dos corridas del mismo nombre en el MISMO segundo
    # compartirian run_id (la resolucion del timestamp es 1 s) y por lo tanto
    # journal — el resume leeria historia ajena. Sufijo -2, -3... si ya existe.
    base = _dir_base()
    candidato, n = c.run_id, 1
    while True:
        try:
            # mkdir ATOMICO como reserva del run_id: exists()+mkdir(exist_ok=
            # True) era TOCTOU (dos corridas concurrentes pasaban ambas el
            # check y compartian dir+journal). FileExistsError = reintentar.
            (base / candidato).mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            n += 1
            candidato = f"{c.run_id}-{n}"
    c.run_id = candidato
    c.dir = base / c.run_id
    if resume_de:
        c.cache = _cargar_cache_de_journal(_dir_base() / resume_de / "journal.jsonl")
    # 'a' y no 'w': si un reloj repetido choca run_id, no se pisa historia.
    c._fh = open(c.dir / "journal.jsonl", "a", encoding="utf-8")
    c._journal({"tipo": "corrida", "nombre": nombre, "run_id": c.run_id,
                "resume_de": resume_de or None,
                "cache_precargada": len(c.cache), "ts": time.time()})
    return c


def _clave_cache(prompt: str, system: str, schema, rol: str,
                 max_tokens: int) -> str:
    """sha256 del JSON canonico de lo que DEFINE la salida. La temperatura NO
    entra a proposito: ajustar sampling no debe invalidar un resume."""
    carga = {"prompt": prompt, "system": system, "schema": schema,
             "rol": rol, "max_tokens": max_tokens}
    canon = json.dumps(carga, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _valida(obj, schema, ruta: str = "$") -> list:
    """Validacion JSON Schema MINIMA sin dependencia externa: type /
    properties / required / items / enum. Devuelve lista de errores legibles
    (vacia = conforme). Suficiente para schemas de salida de agentes; lo que
    no entiende, lo ignora (permisivo a proposito: el server ya fuerza la
    gramatica, esto es la red de seguridad local)."""
    errores: list = []
    if not isinstance(schema, dict):
        return errores

    tipo = schema.get("type")
    if tipo:
        tipos = tipo if isinstance(tipo, list) else [tipo]
        # bool es subclase de int en Python: excluirlo explicitamente de
        # integer/number para que true no pase por 1.
        def _es(t):
            if t == "object":
                return isinstance(obj, dict)
            if t == "array":
                return isinstance(obj, list)
            if t == "string":
                return isinstance(obj, str)
            if t == "integer":
                return isinstance(obj, int) and not isinstance(obj, bool)
            if t == "number":
                return isinstance(obj, (int, float)) and not isinstance(obj, bool)
            if t == "boolean":
                return isinstance(obj, bool)
            if t == "null":
                return obj is None
            return True     # tipo desconocido: no opinar
        if not any(_es(t) for t in tipos):
            errores.append(f"{ruta}: se esperaba type {tipo!r} y vino "
                           f"{type(obj).__name__}")
            return errores  # sin el tipo correcto, lo demas no aplica

    if "enum" in schema:
        # Igualdad a mano (2026-08-11): en Python True == 1 (bool es subclase
        # de int), asi que 'obj in enum' dejaba pasar true contra [1, 2] — el
        # server lo rechazaria. bool solo matchea bool; entre no-bools vale la
        # igualdad numerica matematica (1.0 si matchea 1, como en JSON).
        def _en_enum(v, op):
            if isinstance(v, bool) != isinstance(op, bool):
                return False
            return v == op
        if not any(_en_enum(obj, op) for op in schema["enum"]):
            errores.append(
                f"{ruta}: valor {obj!r} fuera del enum {schema['enum']!r}")

    if isinstance(obj, dict):
        for req in schema.get("required") or []:
            if req not in obj:
                errores.append(f"{ruta}: falta la clave requerida '{req}'")
        for k, sub in (schema.get("properties") or {}).items():
            if k in obj:
                errores.extend(_valida(obj[k], sub, f"{ruta}.{k}"))

    if isinstance(obj, list) and isinstance(schema.get("items"), dict):
        for i, elem in enumerate(obj):
            errores.extend(_valida(elem, schema["items"], f"{ruta}[{i}]"))

    return errores


def _resolver_backend(c: Corrida, rol: str, url: str) -> tuple:
    """(url, sampling) segun rol. rol 'worker' -> summoner.ensure con
    DEGRADACION al cerebro (jamas colgar la corrida por el worker: el aviso
    va por print_fn y se sigue)."""
    if url:
        return url, dict(_SAMPLING_CEREBRO)
    if rol == "worker":
        try:
            # Import perezoso: summoner arrastra estado de flota y aca solo
            # se necesita si el caller pidio el rol. Via importlib (sys.modules
            # manda): `from cognia import summoner` resuelve por el atributo
            # del paquete cuando el modulo real ya se importo, y un stub de
            # sys.modules en tests quedaria ignorado segun el ORDEN de la
            # suite (verde aislado, rojo en suite — cazado 2026-08-11).
            import importlib
            summoner = importlib.import_module("cognia.summoner")
            res = summoner.ensure("worker")
            if res.get("url"):
                return res["url"], dict(_SAMPLING_WORKER)
            raise RuntimeError("ensure devolvio sin url")
        except Exception as e:
            try:
                c.print_fn(f"aviso: worker no disponible "
                           f"({type(e).__name__}: {e}); hijos van al cerebro")
            except Exception:
                pass
    from cognia.agent.model_profiles import url_del_backend
    return url_del_backend(), dict(_SAMPLING_CEREBRO)


def _completar_por_defecto():
    """Import perezoso de chat_client (regla transversal: riesgo de ciclo)."""
    from cognia.agent.chat_client import completar
    return completar


def _llamar(fn, mensajes, rf, **kw):
    """Una llamada tolerando que el kwarg response_format (WP1) no haya
    aterrizado aun: si la FIRMA de fn no lo acepta, se llama sin el — el
    schema pierde la gramatica del server pero la validacion local y el
    retry siguen cubriendo el contrato.

    La decision es por inspect.signature y UNA sola llamada (2026-08-11):
    el try/except TypeError anterior tragaba un TypeError INTERNO de fn y
    pagaba una SEGUNDA llamada identica con la gramatica caida en silencio
    (doble gasto + bug enmascarado). Un TypeError de adentro ahora se
    propaga tal cual."""
    if rf is None:
        return fn(mensajes, **kw)
    try:
        params = inspect.signature(fn).parameters
        acepta = ("response_format" in params
                  or any(p.kind is inspect.Parameter.VAR_KEYWORD
                         for p in params.values()))
    except (TypeError, ValueError):
        # Firma no introspectable (builtin/C): asumir el chat_client nuevo.
        acepta = True
    if acepta:
        return fn(mensajes, response_format=rf, **kw)
    return fn(mensajes, **kw)


def agente(c: Corrida, prompt: str, schema: dict = None, *, system: str = "",
           rol: str = "", url: str = "", max_tokens: int = 2048,
           temperatura: float = None, reintentos: int = 1,
           completar_fn=None, via: str = "wf_agente"):
    """UN agente de workflow: prompt -> str, o prompt+schema -> dict validado.

    Contrato (congelado 2026-08-11):
    - cache por sha256 canonico de {prompt, system, schema, rol, max_tokens};
      un hit (corrida con resume_de) se devuelve SIN llamar al LLM.
    - presupuesto agotado -> {"_error": ...} SIN llamar; cada respuesta real
      registra su usage.
    - schema -> response_format json_schema (forma verificada EN VIVO contra
      :8080, ver abajo) + json.loads + _valida; fallo -> 1 reintento con el
      error REAL apendeado al prompt (patron structure.py repair); segundo
      fallo -> {"_error": ..., "_crudo": texto}.
    - finish_reason 'length' -> error de presupuesto con numeros, SIN retry.
    - Todo (hit o real) deja una linea en el journal.
    Los errores vuelven como dict {"_error": ...}, nunca como excepcion.
    """
    # Clamp del razonador ANTES que nada (2026-08-11): chat_client ya clampea
    # por su lado, asi que el error de 'length' reportaba el max_tokens
    # PRE-clamp (p.ej. 64) mientras la llamada real iba con 1024 — clave de
    # cache, llamada y mensajes de error tienen que hablar del MISMO numero.
    # Import perezoso: model_profiles arrastra la tabla de familias y aca
    # solo hace falta la constante.
    from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR
    max_tokens = max(int(max_tokens), MIN_TOKENS_RAZONADOR)

    clave = _clave_cache(prompt, system, schema, rol, max_tokens)

    # --- cache hit (resume): resultado ya pagado en una corrida previa ---
    if clave in c.cache:
        resultado = c.cache[clave]
        c._journal({"tipo": "agente", "clave": clave, "cache_hit": True,
                    "rol": rol, "url": "", "usage": None, "error": None,
                    "resultado": resultado, "ts": time.time()})
        return resultado

    def _falla(msg: str, crudo: str = None, usage: dict = None,
               url_j: str = None):
        # usage/url_j (2026-08-11): los caminos de FALLO perdian el usage
        # pagado y la url efectiva en el journal — un fallo post-llamada
        # tiene que dejar constancia de lo que COSTO y contra que backend.
        salida = {"_error": msg}
        if crudo is not None:
            salida["_crudo"] = crudo
        c._journal({"tipo": "agente", "clave": clave, "cache_hit": False,
                    "rol": rol, "url": url_j if url_j is not None else url,
                    "usage": usage, "error": msg, "ts": time.time()})
        return salida

    # Techo ANTES de tocar backend alguno: con el presupuesto agotado ni
    # siquiera se convoca al worker (convocar cuesta VRAM y segundos).
    if c.presupuesto and c.presupuesto.agotado():
        return _falla(f"presupuesto de {c.presupuesto.total} tokens "
                      f"agotado (gastados {c.presupuesto.gastado()})")

    fn = completar_fn or _completar_por_defecto()
    url_efectiva, sampling = _resolver_backend(c, rol, url)
    if temperatura is not None:
        sampling["temperature"] = temperatura

    # Forma de response_format VERIFICADA EN VIVO 2026-08-11 contra :8080
    # (Qwythos-9B, llama-server): {"type": "json_schema", "json_schema":
    # {"name": ..., "schema": <JSON Schema>, "strict": true}} -> HTTP 200,
    # el server fuerza la gramatica y el content sale JSON conforme
    # (probado con {"x": integer} -> '{ "x": 7 }'). La forma plana
    # {"type": "json_object", "schema": ...} tambien funciona, pero se fija
    # la anidada por ser la del estandar OpenAI (portable a otros servers).
    rf = None
    # 'is not None' y no truthiness (2026-08-11): schema={} es falsy pero ES
    # un schema valido (todo JSON conforme) — tratarlo como texto libre
    # devolvia el string crudo sin parsear ni pedir gramatica.
    if schema is not None:
        rf = {"type": "json_schema",
              "json_schema": {"name": "salida", "schema": schema,
                              "strict": True}}

    mensajes = ([{"role": "system", "content": system}] if system else []) \
        + [{"role": "user", "content": prompt}]

    intentos = 1 + max(int(reintentos), 0) if schema is not None else 1
    texto = ""
    for intento in range(intentos):
        # El techo se mira ANTES de cada llamada (tambien de los retries):
        # un retry no tiene licencia para pasarse del presupuesto.
        if c.presupuesto and c.presupuesto.agotado():
            return _falla(f"presupuesto de {c.presupuesto.total} tokens "
                          f"agotado (gastados {c.presupuesto.gastado()})",
                          url_j=url_efectiva)

        resp = _llamar(fn, mensajes, rf, url=url_efectiva,
                       temperature=sampling["temperature"],
                       top_p=sampling["top_p"], max_tokens=max_tokens,
                       razonador=True, via=via)
        # El usage se registra SIEMPRE que hubo respuesta del server, aunque
        # el parseo/validacion falle despues: esos tokens ya se pagaron.
        usage_resp = getattr(resp, "usage", None) or {}
        if c.presupuesto:
            c.presupuesto.registrar(usage_resp)

        if getattr(resp, "error", ""):
            return _falla(resp.error, usage=usage_resp, url_j=url_efectiva)

        if getattr(resp, "finish_reason", "") == "length":
            # NO reintentar igual-igual: el mismo prompt con el mismo techo
            # trunca igual (la leccion de los 10 bugs de max_tokens). El error
            # lleva los numeros para que el caller suba el presupuesto.
            usados = usage_resp.get("completion_tokens", "?")
            return _falla(f"salida truncada (finish_reason=length): "
                          f"max_tokens={max_tokens}, completion_tokens="
                          f"{usados}; subir max_tokens, no reintentar",
                          usage=usage_resp, url_j=url_efectiva)

        texto = getattr(resp, "texto", "") or ""

        if schema is None:
            resultado = texto
            break

        # --- schema: parsear y validar localmente (red de seguridad aunque
        # el server ya haya forzado gramatica) ---
        try:
            obj = json.loads(texto)
            errores = _valida(obj, schema)
        except ValueError as e:
            errores = [f"JSON invalido: {e}"]
        if not errores:
            resultado = obj
            break

        detalle = "; ".join(errores)
        if intento + 1 >= intentos:
            return _falla(f"salida no conforme al schema tras "
                          f"{intentos} intento(s): {detalle}", crudo=texto,
                          usage=usage_resp, url_j=url_efectiva)
        # Retry con el ERROR REAL en el prompt (patron structure.py:
        # build_repair_hint): el modelo corrige lo que el validador vio,
        # no adivina.
        mensajes = mensajes[:-1] + [{
            "role": "user",
            "content": prompt + "\n\nSALIDA INVALIDA en el intento "
                       f"anterior: {detalle}\nRespuesta cruda: "
                       f"{texto[:500]}\nDevolve SOLO el JSON conforme "
                       "al schema pedido."}]

    c._journal({"tipo": "agente", "clave": clave, "cache_hit": False,
                "rol": rol, "url": url_efectiva, "usage": usage_resp,
                "error": None, "resultado": resultado, "ts": time.time()})
    c.cache[clave] = resultado
    return resultado


def paralelo(thunks: list, cap: int = 2, timeout_s: float = 900) -> list:
    """Corre thunks (callables sin args) en un pool de cap hilos y devuelve
    los resultados EN ORDEN; un thunk que lanza o agota el timeout vale None.

    cap default 2: la fisica medida de esta maquina — un slot de GPU
    serializa, 2-3 hilos solo solapan I/O o cerebro+worker; mas es mentira.
    timeout_s generoso POR future (bajo contencion la pared medida llego a
    35x el computo). Un timeout no mata el hilo (limitacion de threads en
    Python): el thunk colgado queda como hilo HUERFANO VIVO hasta que termine
    solo — paralelo() retorna igual (shutdown con wait=False, 2026-08-11) y
    el huerfano puede seguir gastando backend/VRAM en segundo plano. Si el
    huerfano escribe al journal de una corrida ya cerrada, _journal lo traga
    con aviso a stderr: no rompe nada."""
    resultados: list = []
    # SIN 'with': el __exit__ del context manager hace shutdown(wait=True) y
    # eso ESPERABA al thunk colgado — el timeout era cosmetico (la pared real
    # era la del thunk, cazado 2026-08-11). El executor se cierra a mano con
    # wait=False para devolver el control apenas se decidio cada resultado.
    ex = ThreadPoolExecutor(max_workers=max(int(cap), 1))
    try:
        futuros = [ex.submit(t) for t in thunks]
        for i, fut in enumerate(futuros):
            try:
                resultados.append(fut.result(timeout=timeout_s))
            except Exception as e:
                print(f"aviso: thunk {i} fallo ({type(e).__name__}: {e}); "
                      f"resultado None", file=sys.stderr)
                resultados.append(None)
    finally:
        # cancel_futures: lo que no arranco no arranca (un thunk colgado no
        # tiene licencia para encolar mas trabajo). Lo que YA corre queda
        # huerfano vivo (ver docstring).
        ex.shutdown(wait=False, cancel_futures=True)
    return resultados


def paralelo_env(thunks: list, cap: int = 2, timeout_s: float = 900):
    """Como `paralelo()`, pero un fallo VUELVE con su causa en vez de `None`.

    Existe porque el `None` de `paralelo()` significa dos cosas a la vez —
    "reventó" y "corrió bien y no había nada"— y las dos piden decisiones
    OPUESTAS: la primera hay que re-despacharla, la segunda es información.
    En un workflow con 12 ramas, una caída silenciosa se lee como "esa rama
    no tenía nada que aportar" y la síntesis final concluye sobre un hueco.

    Devuelve un `cognia.search.fanout.Lote`: sobres en ORDEN DE ENTRADA, con
    `.ok`, `.fallidos`, `.resumen()` y `.volcar()` para dejar rastro en disco.

    `paralelo()` NO se toca: tiene llamadores cuyo contrato es el `None`.
    Cambiarlo por debajo sería arreglar un fallo silencioso creando otro.
    """
    from cognia.search.fanout import en_paralelo
    # Los thunks no llevan spec propio: el índice ES la identidad, y por eso
    # el orden de entrada no es un detalle estético sino la única forma de
    # saber qué rama falló.
    return en_paralelo(list(range(len(thunks))),
                       lambda i: thunks[i](), cap=cap, timeout_s=timeout_s)


def pipeline(items: list, *etapas, cap: int = 2) -> list:
    """Cada item atraviesa TODAS las etapas SIN barrera entre items: un item
    puede ir por la etapa 2 mientras otro sigue en la 1 (un future por item
    que encadena las etapas — la ausencia de barrera sale gratis de ahi).
    Etapa que lanza -> ese item queda None y no sigue; los demas continuan."""
    def _correr(item):
        valor = item
        for etapa in etapas:
            valor = etapa(valor)
        return valor

    resultados: list = []
    with ThreadPoolExecutor(max_workers=max(int(cap), 1)) as ex:
        futuros = [ex.submit(_correr, it) for it in items]
        for i, fut in enumerate(futuros):
            try:
                resultados.append(fut.result())
            except Exception as e:
                print(f"aviso: item {i} fallo en una etapa "
                      f"({type(e).__name__}: {e}); resultado None",
                      file=sys.stderr)
                resultados.append(None)
    return resultados
