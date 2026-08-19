"""
cognia/autopsia/replay.py
=========================
QUE RESUELVE: reproducir una trayectoria del agente SIN volver a pagar el modelo
y SIN volver a tocar el mundo, y poder mutarla (ablacion) para preguntar "y si en
el paso 7 hubiera hecho otra cosa?". Es el sustrato de la atribucion causal: sin
replay, "cual de mis 200 pasos causo el fallo" no se puede ni plantear.

POR QUE EXISTE (hueco medido, 2026-08-18): la literatura tiene las dos mitades
SEPARADAS y nadie las junto. DeltaBox (arXiv 2605.22781) restaura el estado de un
paso en ~5 ms pero no razona sobre causas; Causal Agent Replay (arXiv 2606.08275)
necesita re-ejecutar desde el paso i pero no tiene con que restaurar barato. Son
comunidades disjuntas. Este modulo es la pieza que falta del lado del replay: una
trayectoria normalizada, reproducible a coste cero desde cache, ablacionable, y
con una huella estable que permite DEMOSTRAR que dos reproducciones son la misma.

EVIDENCIA PROPIA (medicion de este modulo, no numero declarado). Traza REAL de 8
pasos generada corriendo `cognia.agent.tools.run_tool` de verdad contra ficheros
de verdad (escribir/leer/py_validar/ejecutar/escribir/leer/contar/listar) en un
workspace temporal:
  - la corrida ORIGINAL costo 115,1 ms de pared; el replay en cache de los 8
    pasos costo 0,057 ms (2018x mas barato, cero efectos sobre el disco);
  - los dos formatos de traza del repo (legacy de loop.py y JSONL del grabador)
    normalizaron a la MISMA huella 1a9bb67eb8664cf8, estable entre procesos;
  - 5 reproducciones seguidas dieron la misma huella de resultados
    (verificar_determinismo -> determinista=True);
  - los dos `leer_archivo suma.py` (MISMA firma, uno antes y otro despues de
    mutar el fichero) devolvieron 'return a + b' y 'return a - b': la cache NO
    los colapso, que es la decision 1;
  - el replay REAL en un workspace nuevo divergio del grabado en el paso 0, y
    el motivo es informativo: el resultado de escribir_archivo trae la RUTA
    ABSOLUTA, asi que esa trayectoria NO es reproducible fuera de su workspace.
    El modulo lo DETECTA (divergencia_informes) en vez de esconderlo.
  - modo real sin ws: 0 pasos ejecutados, ok=False (decision 4, comprobada).

DECISIONES QUE COSTARON ALGO
----------------------------
1. LA CACHE NO PUEDE SER {firma -> resultado}. Es la trampa obvia y fabrica
   evidencia: `leer_archivo x` ANTES y DESPUES de un editar_archivo tienen la
   MISMA firma (mismo tool, mismos args) y resultados DISTINTOS. Un dict plano
   devolveria el contenido nuevo al reproducir el paso viejo, o al reves, y el
   informe diria "reproducido" sobre algo que nunca paso. Aqui la cache guarda
   la LISTA ordenada de resultados por firma y los consume en orden, y ademas
   indexa por numero de paso; el indice manda, la firma es el respaldo. El
   consumo es LOCAL a cada `reproducir` (la Cache no se muta), asi que dos
   reproducciones de la misma cache dan exactamente lo mismo -- que es la
   definicion de determinismo que este modulo promete.

2. EL INFORME DECLARA LA FUENTE DE CADA PASO, SIEMPRE. Un replay que mezcla
   pasos leidos de cache con pasos re-ejecutados de verdad y lo presenta como
   una sola cosa es fabricacion de evidencia: el lector cree que el sistema
   volvio a hacer 200 cosas cuando volvio a hacer 3. Cada paso lleva `fuente`
   en {cache, real, ausente, rechazado} y el informe lleva los conteos, un
   `mezclado: bool` y `modo` DECLARADO. `n_ausente > 0` no se esconde: es un
   agujero en la reproduccion y el consumidor tiene que verlo.

3. MODO REAL RECHAZA LOS ARGS SOSPECHOSOS DE ESTAR TRUNCADOS. Los dos formatos
   de traza del repo GUARDAN LOS ARGS RECORTADOS: `loop.py` escribe
   `args=args_str[:200]` (loop.py:922) y el bus del grabador recorta a 120
   (`via_bus=True`). Re-ejecutar `escribir_archivo` con el contenido cortado a
   200 chars no reproduce el paso: ESCRIBE UN FICHERO MUTILADO. Por eso el modo
   real marca esos pasos `fuente="rechazado"` en vez de correrlos, y hace falta
   `permitir_args_truncados=True` explicito para pasar por encima. La deteccion
   es una COTA, no un oraculo: si len(args) llega justo al limite del formato,
   se sospecha. Puede haber falsos positivos (un args de exactamente 200 chars);
   nunca un falso negativo por debajo del limite.

4. MODO REAL EXIGE `ws`. Sin workspace aislado, re-ejecutar una trayectoria
   ejecuta `borrar_archivo`, `git_commit` y `ejecutar` sobre el repo de verdad.
   `reproducir` con `run_tool_fn` y sin `ws` devuelve ok=False y NO corre nada.

5. UNA TRAYECTORIA ABLACIONADA SE MARCA COMO TAL. `es_real=False` y la lista
   `ablaciones` viaja dentro. Este repo ya pago que una traza de atasco se
   ascendiera a "procedimiento verificado"; una trayectoria contrafactual que
   se pueda confundir con una grabacion real es el mismo error con otro nombre.

LIMITES DECLARADOS (lo que este modulo NO hace)
-----------------------------------------------
- NO restaura el estado del disco. Reproducir en modo real sobre un `ws` vacio
  no reconstruye los ficheros que la trayectoria original leia y no escribio.
  El snapshot/restore es de otro modulo; aqui se declara el agujero.
- NO revierte efectos externos (git push, correo, filas en una BD). El modo
  cache es seguro por construccion; el modo real es tan peligroso como las
  tools que le pases.
- NO decide equivalencia semantica entre acciones distintas. `divergencia`
  compara tool/args/ok literalmente. Aceptar `ls dir` y `find dir -maxdepth 1`
  como el MISMO efecto es un problema aparte (equivalencia de efecto), y este
  modulo no lo resuelve ni finge resolverlo.
- `os.chdir` del modo real es GLOBAL AL PROCESO: no es seguro con hilos.

Solo stdlib. No importa nada de cognia al importarse (grabador se importa
perezoso dentro de la funcion que lo usa, y su ausencia no rompe nada), para que
los tests corran secos y sin ciclos.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Limites de recorte de los DOS productores de traza del repo. No son adornos:
# deciden si un paso se puede re-ejecutar de verdad (decision 3 de la cabecera).
LIMITE_ARGS_LEGACY = 200   # cognia/agent/loop.py:922 -> args_str[:200]
LIMITE_ARGS_BUS = 120      # bus de eventos -> args_str[:120] (via_bus=True)

FUENTES = ("cache", "real", "ausente", "rechazado")


# ---------------------------------------------------------------------------
# La trayectoria normalizada.
# ---------------------------------------------------------------------------

@dataclass
class Trayectoria:
    """Una secuencia de pasos del agente, normalizada desde cualquiera de los
    formatos del repo.

    `es_real` distingue una grabacion de un contrafactual: False en cuanto
    `ablacionar` la toca. `origen` dice de que formato vino, porque el formato
    decide cuanta informacion hay (el legacy no trae duracion ni exit_code).
    """
    id: str = ""
    titulo: str = ""
    tarea: str = ""
    workspace: str = ""
    origen: str = ""          # 'legacy' | 'grabador' | 'vacia'
    es_real: bool = True
    ablaciones: list = field(default_factory=list)
    pasos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.pasos)

    def a_dict(self) -> dict:
        return {
            "id": self.id, "titulo": self.titulo, "tarea": self.tarea,
            "workspace": self.workspace, "origen": self.origen,
            "es_real": self.es_real, "ablaciones": list(self.ablaciones),
            "pasos": copy.deepcopy(self.pasos), "avisos": list(self.avisos),
        }


def _paso_normal(n: int, tool: str, args: str, ok: bool, resumen: str,
                 duracion_s: float = 0.0, ficheros=None, comando: str = "",
                 exit_code=None, paso_agente: int = 0, via_bus: bool = False,
                 origen: str = "") -> dict:
    """Un paso en la forma unica. `args_sospechoso` se calcula UNA vez aqui:
    depende del formato de origen y despues nadie mas tiene el dato."""
    args = args if isinstance(args, str) else ("" if args is None else str(args))
    tool = (tool or "").strip()
    limite = LIMITE_ARGS_BUS if via_bus else LIMITE_ARGS_LEGACY
    # Cota, no oraculo: solo se puede sospechar cuando la longitud LLEGA al
    # limite del recorte. Por debajo del limite el args esta completo seguro.
    sospechoso = len(args) >= limite
    return {
        "n": int(n),
        "tool": tool,
        "args": args,
        "ok": bool(ok),
        "resumen": resumen if isinstance(resumen, str) else str(resumen or ""),
        "duracion_s": round(float(duracion_s or 0.0), 4),
        "ficheros_tocados": list(ficheros or []),
        "comando": comando or "",
        "exit_code": exit_code,
        "paso_agente": int(paso_agente or 0),
        "via_bus": bool(via_bus),
        "args_sospechoso": bool(sospechoso),
        "origen_paso": origen,
    }


def _derivar(args: str, tool: str, resumen: str) -> tuple:
    """Ficheros/comando/exit_code para el formato legacy, que no los trae.

    Reutiliza el grabador si esta; si no esta, devuelve vacios. NO adivina por
    su cuenta: una lista de ficheros inventada es una mentira que despues
    alguien usa para decidir (regla del grabador, misma logica)."""
    try:
        from cognia.flujos import grabador as _g  # perezoso, a proposito
    except Exception:
        return ([], "", None)
    try:
        return (list(_g.derivar_ficheros(args, tool) or []),
                _g.derivar_comando(args, tool) or "",
                _g.derivar_exit_code(resumen, tool))
    except Exception:
        return ([], "", None)


def normalizar(traza, *, id: str = "", titulo: str = "", tarea: str = "",
               workspace: str = "") -> Trayectoria:
    """Convierte cualquiera de los formatos aceptados en una `Trayectoria`.

    Acepta:
      - lista de {action, args, ok, result_head}  (el `trace` de loop.py /
        `_actions_trace` de cli.py). origen='legacy'.
      - dict {id, titulo, tarea, pasos:[{n, tool, args, ok, resumen_resultado,
        duracion_s, ficheros_tocados, comando, exit_code, ...}]} (grabador).
        origen='grabador'.
      - un objeto con `.a_dict()` (una `Grabacion` del grabador).
      - una `Trayectoria` (idempotente: devuelve una copia).

    Nunca lanza por un paso raro: lo salta y lo anota en `avisos`. Una traza a
    medias es el caso NORMAL en este repo (tareas que mueren a los 18 pasos), y
    perder la trayectoria entera por la ultima linea seria absurdo.
    """
    if isinstance(traza, Trayectoria):
        t = Trayectoria(**traza.a_dict())
        return t
    if hasattr(traza, "a_dict") and not isinstance(traza, dict):
        try:
            traza = traza.a_dict()
        except Exception:
            pass

    avisos = []
    pasos_crudos = []
    origen = "vacia"

    if isinstance(traza, dict):
        origen = "grabador"
        id = id or str(traza.get("id") or "")
        titulo = titulo or str(traza.get("titulo") or "")
        tarea = tarea or str(traza.get("tarea") or "")
        workspace = workspace or str(traza.get("workspace") or "")
        pasos_crudos = traza.get("pasos") or []
        if not isinstance(pasos_crudos, list):
            avisos.append("el campo 'pasos' no es una lista; trayectoria vacia")
            pasos_crudos = []
    elif isinstance(traza, (list, tuple)):
        pasos_crudos = list(traza)
        # El formato se decide POR PASO mas abajo; aca solo la etiqueta global.
        origen = "legacy"
        for p in pasos_crudos:
            if isinstance(p, dict) and ("tool" in p or "resumen_resultado" in p):
                origen = "grabador"
                break
    elif traza is None:
        avisos.append("traza None")
    else:
        avisos.append(f"formato no reconocido: {type(traza).__name__}")

    pasos = []
    n = 0
    for crudo in pasos_crudos:
        if not isinstance(crudo, dict):
            avisos.append(f"paso #{n} no es dict ({type(crudo).__name__}); saltado")
            continue
        tool = crudo.get("tool") or crudo.get("action") or ""
        if not str(tool).strip():
            avisos.append(f"paso #{n} sin tool/action; saltado")
            continue
        es_grabador = ("tool" in crudo) or ("resumen_resultado" in crudo)
        args = crudo.get("args", "")
        ok = crudo.get("ok", True)
        resumen = (crudo.get("resumen_resultado")
                   if "resumen_resultado" in crudo
                   else crudo.get("result_head", ""))
        via_bus = bool(crudo.get("via_bus", False))
        if es_grabador:
            fich = crudo.get("ficheros_tocados")
            com = crudo.get("comando", "")
            exc = crudo.get("exit_code")
            if fich is None and com == "" and exc is None:
                fich, com, exc = _derivar(str(args), str(tool), str(resumen or ""))
            dur = crudo.get("duracion_s", 0.0)
            pa = crudo.get("paso_agente", 0)
            org = "grabador"
        else:
            fich, com, exc = _derivar(str(args), str(tool), str(resumen or ""))
            dur, pa, org = 0.0, 0, "legacy"
        n += 1
        pasos.append(_paso_normal(
            n=n, tool=str(tool), args=args, ok=ok, resumen=resumen,
            duracion_s=dur, ficheros=fich, comando=com, exit_code=exc,
            paso_agente=pa, via_bus=via_bus, origen=org))

    if pasos and origen == "vacia":
        origen = "legacy"
    return Trayectoria(id=id, titulo=titulo, tarea=tarea, workspace=workspace,
                       origen=origen, es_real=True, pasos=pasos, avisos=avisos)


def cargar_jsonl(ruta) -> Trayectoria:
    """Lee un JSONL del grabador (cabecera/paso/anotacion/cierre) y lo normaliza.

    Existe para que el replay pueda comer una grabacion de disco sin depender de
    que `cognia.flujos.grabador` este importable. Tolera lineas rotas: las cuenta
    en `avisos` en vez de tumbar la lectura (un fichero cortado a mitad de
    escritura es el caso normal, no el raro).
    """
    p = Path(ruta)
    cab = {"id": p.stem, "titulo": "", "tarea": "", "workspace": ""}
    pasos, malas = [], 0
    try:
        crudo = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        t = normalizar([], id=p.stem)
        t.avisos.append(f"no se pudo leer {p}: {exc}")
        return t
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            obj = json.loads(linea)
        except Exception:
            malas += 1
            continue
        if not isinstance(obj, dict):
            malas += 1
            continue
        tipo = obj.get("tipo")
        if tipo == "cabecera":
            for k in ("id", "titulo", "tarea", "workspace"):
                if obj.get(k):
                    cab[k] = obj[k]
        elif tipo == "anotacion":
            campo = obj.get("campo")
            if campo in cab:
                cab[campo] = str(obj.get("valor", ""))
        elif tipo == "paso":
            pasos.append(obj)
    t = normalizar({"pasos": pasos, **cab})
    if malas:
        t.avisos.append(f"{malas} lineas ilegibles en {p.name}")
    return t


# ---------------------------------------------------------------------------
# Firma y huella. Sin esto no hay determinismo demostrable.
# ---------------------------------------------------------------------------

def firma(tool: str, args: str) -> str:
    """Identidad de una ACCION (tool + args exactos), estable entre procesos.

    sha256 y no hash(): PYTHONHASHSEED aleatoriza hash() de str por defecto y
    una firma que cambia entre procesos hace inutil cualquier cache persistida.
    Los args NO se normalizan (ni strip, ni collapse de espacios): en este repo
    los args son un protocolo posicional con '|' y tocarlos cambia el efecto.
    """
    tool = (tool or "").strip()
    args = args if isinstance(args, str) else ("" if args is None else str(args))
    crudo = json.dumps([tool, args], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


def _sha_corto(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8", "replace")).hexdigest()[:16]


def huella(trayectoria) -> str:
    """Hash estable de una trayectoria: (n, tool, args, ok) de cada paso.

    NO incluye resumenes ni duraciones: son el RESULTADO de correrla, no la
    trayectoria. Dos trayectorias con la misma huella piden las mismas acciones
    en el mismo orden; si al reproducirlas dan resultados distintos, el no
    determinista es el MUNDO, y eso es justo lo que se quiere poder distinguir.
    """
    t = trayectoria if isinstance(trayectoria, Trayectoria) else normalizar(trayectoria)
    filas = [[p["n"], p["tool"], p["args"], bool(p["ok"])] for p in t.pasos]
    crudo = json.dumps(filas, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


def huella_informe(informe: dict) -> str:
    """Hash de lo que una reproduccion PRODUJO: (n, tool, args, ok, sha(result)).

    Deliberadamente NO incluye la `fuente`, para que la huella de un replay en
    cache y la de un replay real sean COMPARABLES: si coinciden, re-ejecutar dio
    exactamente lo mismo que estaba grabado. Los conteos por fuente viajan
    aparte en el informe, donde nadie los puede confundir con esto.
    """
    filas = []
    for p in (informe or {}).get("pasos", []):
        filas.append([p.get("n"), p.get("tool"), p.get("args"),
                      bool(p.get("ok")), _sha_corto(p.get("resultado") or "")])
    crudo = json.dumps(filas, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Cache de resultados grabados.
# ---------------------------------------------------------------------------

@dataclass
class Cache:
    """Resultados grabados, indexados para poder reproducir sin ejecutar.

    `por_indice`: n -> entrada. Es el indice PREFERIDO (exacto).
    `por_firma`: firma -> lista ORDENADA de entradas. Respaldo para cuando la
    trayectoria a reproducir no es la original (una ablacion corre los numeros
    de paso). La lista es ordenada y se consume en orden porque la misma accion
    repetida da resultados DISTINTOS -- ver decision 1 de la cabecera.

    La Cache es INMUTABLE durante `reproducir`: el consumo vive en un contador
    local de cada llamada. Por eso dos reproducciones dan lo mismo.
    """
    por_indice: dict = field(default_factory=dict)
    por_firma: dict = field(default_factory=dict)
    origen: str = ""

    def __len__(self) -> int:
        return len(self.por_indice)

    def firmas(self) -> int:
        return len(self.por_firma)


def grabar_resultados(traza) -> Cache:
    """Indexa {firma(tool,args) -> resultados} a partir de una traza/trayectoria.

    Es lo que hace posible el modo cache: coste cero, cero efectos, determinista.
    """
    t = traza if isinstance(traza, Trayectoria) else normalizar(traza)
    c = Cache(origen=t.id or t.origen)
    for p in t.pasos:
        f = firma(p["tool"], p["args"])
        entrada = {"n": p["n"], "firma": f, "tool": p["tool"], "args": p["args"],
                   "ok": bool(p["ok"]), "resultado": p["resumen"],
                   "duracion_s": p["duracion_s"], "exit_code": p["exit_code"]}
        c.por_indice[p["n"]] = entrada
        c.por_firma.setdefault(f, []).append(entrada)
    return c


def _buscar_en_cache(cache: Cache, paso: dict, consumidos: dict):
    """(entrada, via) con via en {'indice','firma','miss'}.

    El indice manda: si el paso n de la trayectoria pide la MISMA accion que el
    paso n grabado, ese es el resultado, sin ambiguedad. Solo si no cuadra se
    cae a la firma, consumiendo en orden las ocurrencias no usadas.
    """
    if cache is None:
        return (None, "miss")
    f = firma(paso["tool"], paso["args"])
    ent = cache.por_indice.get(paso["n"])
    if ent is not None and ent.get("firma") == f and paso["n"] not in consumidos:
        consumidos[paso["n"]] = True
        # marcar tambien el consumo por firma para que el respaldo no la repita
        lista = cache.por_firma.get(f) or []
        for i, e in enumerate(lista):
            if e is ent:
                consumidos[("f", f, i)] = True
                break
        return (ent, "indice")
    lista = cache.por_firma.get(f) or []
    for i, e in enumerate(lista):
        if consumidos.get(("f", f, i)):
            continue
        consumidos[("f", f, i)] = True
        consumidos[e["n"]] = True
        return (e, "firma")
    return (None, "miss")


# ---------------------------------------------------------------------------
# Reproduccion.
# ---------------------------------------------------------------------------

def _informe_vacio(modo: str, ws: str = "") -> dict:
    return {"ok": True, "modo": modo, "pasos": [], "n_pasos": 0,
            "n_cache": 0, "n_real": 0, "n_ausente": 0, "n_rechazado": 0,
            "mezclado": False, "huella": "", "huella_trayectoria": "",
            "ms": 0.0, "ws": ws, "avisos": [], "error": ""}


def reproducir(trayectoria, *, hasta=None, cache=None, run_tool_fn=None,
               ws=None, ctx=None, preferir_cache: bool = False,
               permitir_args_truncados: bool = False,
               parar_en_fallo: bool = False) -> dict:
    """Re-ejecuta los pasos 0..`hasta` de una trayectoria y devuelve el Informe.

    MODOS (siempre DECLARADOS en el informe, nunca deducidos por el lector):
      - `run_tool_fn is None`  -> modo 'cache': los resultados salen de lo
        grabado. Coste cero, cero efectos, determinista.
      - `run_tool_fn` dado     -> modo 'real': se ejecutan de verdad en `ws`.
        `ws` es OBLIGATORIO (decision 4): sin el, no corre nada y ok=False.
      - `run_tool_fn` + `cache` + `preferir_cache=True` -> modo 'mixto': lo que
        este en cache sale de cache, el resto se ejecuta. El informe marca
        `mezclado=True` y cada paso trae su `fuente`.

    `hasta` es INCLUSIVO y en indice 0-based sobre la lista de pasos (hasta=6
    reproduce los 7 primeros), que es como se pregunta "y si el paso 7...".
    None = toda la trayectoria.

    NUNCA lanza: un fallo viaja dentro del informe (ok=False + error). Un fallo
    que devuelve None es invisible y este repo ya lo pago.
    """
    # perf_counter y NO time.time: en Windows time.time() tiene resolucion de
    # ~15,6 ms y un replay en cache (microsegundos) se reporta como "0.0 ms".
    # Medido aqui mismo: la primera version de este modulo imprimio "0.000ms" y
    # un ahorro de 5e10x, que es exactamente fabricar un numero.
    t0 = time.perf_counter()
    t = trayectoria if isinstance(trayectoria, Trayectoria) else normalizar(trayectoria)

    if run_tool_fn is None:
        modo = "cache"
    elif cache is not None and preferir_cache:
        modo = "mixto"
    else:
        modo = "real"

    inf = _informe_vacio(modo, str(ws or ""))
    inf["huella_trayectoria"] = huella(t)
    inf["es_real"] = bool(t.es_real)
    if t.avisos:
        inf["avisos"].extend(list(t.avisos))

    if modo in ("real", "mixto"):
        if not ws:
            inf["ok"] = False
            inf["error"] = ("modo REAL sin ws: re-ejecutar una trayectoria en el "
                            "directorio actual puede borrar/commitear cosas de "
                            "verdad. Pasa ws=<workspace aislado>.")
            inf["ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return inf
        try:
            Path(ws).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            inf["ok"] = False
            inf["error"] = f"no se pudo preparar ws={ws}: {exc}"
            inf["ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return inf

    n_total = len(t.pasos)
    if hasta is None:
        limite = n_total
    else:
        try:
            limite = int(hasta) + 1
        except Exception:
            limite = n_total
            inf["avisos"].append(f"hasta={hasta!r} no es un entero; se usa toda la traza")
        limite = max(0, min(limite, n_total))
        if hasta is not None and int(hasta) >= n_total:
            inf["avisos"].append(
                f"hasta={hasta} supera el ultimo paso ({n_total - 1}); "
                f"se reproduce hasta el final")

    consumidos: dict = {}
    previo = None
    if modo in ("real", "mixto"):
        previo = os.getcwd()
        try:
            os.chdir(str(ws))
        except Exception as exc:
            inf["ok"] = False
            inf["error"] = f"no se pudo entrar a ws={ws}: {exc}"
            inf["ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return inf

    ctx = dict(ctx or {})
    try:
        for idx in range(limite):
            paso = t.pasos[idx]
            fila = {"i": idx, "n": paso["n"], "tool": paso["tool"],
                    "args": paso["args"], "ok_grabado": bool(paso["ok"]),
                    "ok": bool(paso["ok"]), "fuente": "ausente",
                    "resultado": "", "motivo": "", "ms": 0.0,
                    "args_sospechoso": bool(paso["args_sospechoso"])}
            t_paso = time.perf_counter()

            usar_cache = (modo == "cache") or (modo == "mixto")
            entrada, via = (None, "miss")
            if usar_cache:
                entrada, via = _buscar_en_cache(cache, paso, consumidos)

            if entrada is not None:
                fila["fuente"] = "cache"
                fila["resultado"] = entrada.get("resultado") or ""
                fila["ok"] = bool(entrada.get("ok"))
                fila["motivo"] = f"cache por {via}"
                inf["n_cache"] += 1
            elif modo == "cache":
                fila["fuente"] = "ausente"
                fila["ok"] = False
                fila["motivo"] = ("sin resultado grabado para esta accion "
                                  "(la cache no la tiene o ya se consumio)")
                inf["n_ausente"] += 1
            elif paso["args_sospechoso"] and not permitir_args_truncados:
                fila["fuente"] = "rechazado"
                fila["ok"] = False
                fila["motivo"] = (
                    f"args de {len(paso['args'])} chars: llega al limite de "
                    f"recorte del formato ({LIMITE_ARGS_BUS if paso['via_bus'] else LIMITE_ARGS_LEGACY}) "
                    f"y re-ejecutarlo escribiria datos MUTILADOS. "
                    f"Usa permitir_args_truncados=True si sabes que esta entero.")
                inf["n_rechazado"] += 1
            else:
                try:
                    res = run_tool_fn(paso["tool"], paso["args"], ctx)
                    res = res if isinstance(res, str) else str(res)
                    fila["resultado"] = res
                    fila["ok"] = not _parece_error(res)
                    fila["fuente"] = "real"
                    fila["motivo"] = "ejecutado"
                except Exception as exc:
                    fila["resultado"] = f"EXCEPCION {type(exc).__name__}: {exc}"
                    fila["ok"] = False
                    fila["fuente"] = "real"
                    fila["motivo"] = "la tool lanzo"
                inf["n_real"] += 1

            fila["ms"] = round((time.perf_counter() - t_paso) * 1000, 3)
            fila["resultado_head"] = (fila["resultado"] or "")[:160]
            inf["pasos"].append(fila)
            if parar_en_fallo and not fila["ok"]:
                inf["avisos"].append(f"parado en el paso {idx} (ok=False)")
                break
    finally:
        if previo:
            try:
                os.chdir(previo)
            except Exception:
                pass

    inf["n_pasos"] = len(inf["pasos"])
    inf["mezclado"] = bool(inf["n_cache"] and inf["n_real"])
    inf["huella"] = huella_informe(inf)
    inf["ms"] = round((time.perf_counter() - t0) * 1000, 3)
    if inf["n_ausente"] or inf["n_rechazado"]:
        inf["ok"] = False
        inf["error"] = (f"reproduccion INCOMPLETA: {inf['n_ausente']} pasos sin "
                        f"resultado grabado, {inf['n_rechazado']} rechazados")
    return inf


_MARCA_ERROR = "ERROR"


def _parece_error(resultado: str) -> bool:
    """Misma regla que loop.py:900: solo la PRIMERA linea clasifica. El
    CONTENIDO de un exito (un log con la palabra ERROR leido por leer_archivo)
    no puede marcar fallo -- ese bug ya se arreglo una vez en el bucle."""
    import re as _re
    primera = (resultado or "").split("\n", 1)[0][:120]
    return bool(_re.search(r"\bERROR\b", primera))


def resumen_linea(informe: dict) -> str:
    """Una linea legible que NUNCA esconde la mezcla de fuentes."""
    i = informe or {}
    partes = [f"modo={i.get('modo','?')}", f"pasos={i.get('n_pasos',0)}",
              f"cache={i.get('n_cache',0)}", f"real={i.get('n_real',0)}"]
    if i.get("n_ausente"):
        partes.append(f"AUSENTES={i['n_ausente']}")
    if i.get("n_rechazado"):
        partes.append(f"RECHAZADOS={i['n_rechazado']}")
    if i.get("mezclado"):
        partes.append("MEZCLADO")
    partes.append(f"huella={i.get('huella','')}")
    partes.append(f"{i.get('ms',0.0)}ms")
    return " ".join(partes)


def verificar_determinismo(trayectoria, cache=None, *, veces: int = 2,
                           hasta=None) -> dict:
    """Reproduce `veces` en modo cache y compara las huellas.

    POR QUE ES OBLIGATORIO: si dos replays del mismo material dan huellas
    distintas, el replay no sirve como sustrato causal y hay que DECIRLO en vez
    de seguir construyendo encima.
    """
    huellas = []
    for _ in range(max(1, int(veces))):
        inf = reproducir(trayectoria, hasta=hasta, cache=cache)
        huellas.append(inf["huella"])
    return {"determinista": len(set(huellas)) == 1, "huellas": huellas,
            "veces": len(huellas), "huella": huellas[0] if huellas else ""}


# ---------------------------------------------------------------------------
# Ablacion: la operacion contrafactual.
# ---------------------------------------------------------------------------

MODOS_ABLACION = ("saltar", "invertir_ok", "sustituir")


def ablacionar(trayectoria, i: int, modo: str, *, paso=None, ok=None) -> Trayectoria:
    """Devuelve una trayectoria MUTADA (copia) para el contrafactual.

      - 'saltar'      : quita el paso i.
      - 'invertir_ok' : invierte el `ok` del paso i, o lo fuerza con ok=<bool>.
      - 'sustituir'   : reemplaza el paso i por `paso` (dict con al menos
                        tool/action; se normaliza igual que una traza).

    La original NO se toca (deepcopy). El resultado lleva `es_real=False` y la
    ablacion anotada: un contrafactual que se pueda confundir con una grabacion
    real es exactamente el error que este repo ya pago (decision 5).

    Los `n` se RENUMERAN al quitar/insertar, y eso es a proposito: sin renumerar,
    el indice por paso de la cache apuntaria a resultados de otra accion. La
    consecuencia declarada es que despues de un 'saltar' la cache cae al respaldo
    por firma para los pasos posteriores, que es correcto pero mas debil.
    """
    t = trayectoria if isinstance(trayectoria, Trayectoria) else normalizar(trayectoria)
    nueva = Trayectoria(id=t.id, titulo=t.titulo, tarea=t.tarea,
                        workspace=t.workspace, origen=t.origen, es_real=False,
                        ablaciones=list(t.ablaciones),
                        pasos=copy.deepcopy(t.pasos), avisos=list(t.avisos))
    modo = (modo or "").strip()
    if modo not in MODOS_ABLACION:
        nueva.avisos.append(f"modo de ablacion desconocido: {modo!r}; sin cambios")
        nueva.ablaciones.append({"i": i, "modo": modo, "aplicada": False,
                                 "motivo": "modo desconocido"})
        return nueva
    if not isinstance(i, int) or i < 0 or i >= len(nueva.pasos):
        nueva.avisos.append(f"indice de ablacion fuera de rango: {i!r}")
        nueva.ablaciones.append({"i": i, "modo": modo, "aplicada": False,
                                 "motivo": "indice fuera de rango"})
        return nueva

    antes = copy.deepcopy(nueva.pasos[i])
    if modo == "saltar":
        nueva.pasos.pop(i)
    elif modo == "invertir_ok":
        nuevo_ok = (not antes["ok"]) if ok is None else bool(ok)
        nueva.pasos[i]["ok"] = nuevo_ok
        # El resumen grabado decia otra cosa: dejarlo intacto haria que el
        # informe mostrara 'ok=False' junto a un resultado de exito. Se ANOTA.
        nueva.pasos[i]["resumen"] = (
            f"[ABLACION invertir_ok -> {nuevo_ok}] " + (antes["resumen"] or ""))
    else:  # sustituir
        if not isinstance(paso, dict):
            nueva.avisos.append("sustituir sin `paso` dict; sin cambios")
            nueva.ablaciones.append({"i": i, "modo": modo, "aplicada": False,
                                     "motivo": "falta paso"})
            return nueva
        aux = normalizar([paso])
        if not aux.pasos:
            nueva.avisos.append("sustituir con un paso invalido; sin cambios")
            nueva.ablaciones.append({"i": i, "modo": modo, "aplicada": False,
                                     "motivo": "paso invalido"})
            return nueva
        nuevo = aux.pasos[0]
        nuevo["origen_paso"] = "sustituido"
        nueva.pasos[i] = nuevo

    for k, p in enumerate(nueva.pasos):
        p["n"] = k + 1
    nueva.ablaciones.append({
        "i": i, "modo": modo, "aplicada": True,
        "antes": {"tool": antes["tool"], "args": antes["args"], "ok": antes["ok"]},
        "despues": ({"tool": nueva.pasos[i]["tool"], "args": nueva.pasos[i]["args"],
                     "ok": nueva.pasos[i]["ok"]} if modo != "saltar" and i < len(nueva.pasos)
                    else None),
    })
    return nueva


# ---------------------------------------------------------------------------
# Divergencia: donde empiezan a diferir dos trayectorias.
# ---------------------------------------------------------------------------

_CAMPOS_DIVERGENCIA = ("tool", "args", "ok")


def divergencia(traj_a, traj_b) -> dict:
    """Primer paso donde `a` y `b` difieren, y EN QUE.

    Compara literalmente tool, args y ok, en ese orden. NO intenta decidir si
    dos acciones distintas tienen el mismo efecto (`ls dir` vs `find dir
    -maxdepth 1`): eso es equivalencia de efecto, otro problema, y fingir que se
    resuelve aqui daria un "no divergen" falso.

    Devuelve {divergen, paso, campo, a, b, motivo, n_a, n_b, huella_a, huella_b}.
    `paso` es el indice 0-based del primer paso distinto, o None si son iguales.
    """
    ta = traj_a if isinstance(traj_a, Trayectoria) else normalizar(traj_a)
    tb = traj_b if isinstance(traj_b, Trayectoria) else normalizar(traj_b)
    out = {"divergen": False, "paso": None, "campo": "", "a": None, "b": None,
           "motivo": "", "n_a": len(ta.pasos), "n_b": len(tb.pasos),
           "huella_a": huella(ta), "huella_b": huella(tb)}
    comun = min(len(ta.pasos), len(tb.pasos))
    for k in range(comun):
        pa, pb = ta.pasos[k], tb.pasos[k]
        for campo in _CAMPOS_DIVERGENCIA:
            if pa[campo] != pb[campo]:
                out.update({"divergen": True, "paso": k, "campo": campo,
                            "a": pa[campo], "b": pb[campo],
                            "motivo": f"paso {k}: {campo} distinto"})
                return out
    if len(ta.pasos) != len(tb.pasos):
        mas = "a" if len(ta.pasos) > len(tb.pasos) else "b"
        extra = (ta if mas == "a" else tb).pasos[comun]
        out.update({"divergen": True, "paso": comun, "campo": "longitud",
                    "a": len(ta.pasos), "b": len(tb.pasos),
                    "motivo": (f"iguales hasta el paso {comun - 1}; "
                               f"'{mas}' sigue con {extra['tool']!r} y la otra "
                               f"se acaba")})
    return out


def divergencia_informes(inf_a: dict, inf_b: dict) -> dict:
    """Igual que `divergencia` pero sobre lo que dos reproducciones PRODUJERON.

    Es la pregunta que de verdad importa para atribuir: no "pidieron lo mismo"
    sino "salio lo mismo". Compara ok y el hash del resultado paso a paso.
    """
    pa = (inf_a or {}).get("pasos", [])
    pb = (inf_b or {}).get("pasos", [])
    out = {"divergen": False, "paso": None, "campo": "", "a": None, "b": None,
           "motivo": "", "n_a": len(pa), "n_b": len(pb),
           "huella_a": (inf_a or {}).get("huella", ""),
           "huella_b": (inf_b or {}).get("huella", "")}
    for k in range(min(len(pa), len(pb))):
        for campo in ("tool", "args", "ok"):
            if pa[k].get(campo) != pb[k].get(campo):
                out.update({"divergen": True, "paso": k, "campo": campo,
                            "a": pa[k].get(campo), "b": pb[k].get(campo),
                            "motivo": f"paso {k}: {campo} distinto"})
                return out
        ha = _sha_corto(pa[k].get("resultado") or "")
        hb = _sha_corto(pb[k].get("resultado") or "")
        if ha != hb:
            out.update({"divergen": True, "paso": k, "campo": "resultado",
                        "a": (pa[k].get("resultado") or "")[:120],
                        "b": (pb[k].get("resultado") or "")[:120],
                        "motivo": f"paso {k}: el resultado difiere"})
            return out
    if len(pa) != len(pb):
        out.update({"divergen": True, "paso": min(len(pa), len(pb)),
                    "campo": "longitud", "a": len(pa), "b": len(pb),
                    "motivo": "distinta cantidad de pasos reproducidos"})
    return out
