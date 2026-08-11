"""
cognia/agent/rlm.py
===================
Modo RLM: contexto mas grande que la ventana, tocado SOLO via tools.

POR QUE EXISTE: el contexto largo NO entra en la ventana del cerebro
(Qwythos ctx 32768). En vez de truncarlo o resumirlo a ciegas, vive en un
``ContextoRLM`` fuera de la conversacion y el modelo raiz lo explora con 5
herramientas (info/ver/grep/partir/llamar). La recursion (``rlm_llamar``)
manda un trozo a una subllamada LLM fresca SIN tools — profundidad 1
ESTRUCTURAL: los hijos no pueden llamar herramientas porque no se les pasan,
no porque un prompt se lo pida.

El contexto efectivo se MIDE SIEMPRE (``MedidorContexto``): que porcentaje
vio el raiz, que porcentaje vieron los hijos, la ventana pico real y los
tokens gastados. El informe se adjunta a CADA corrida, sin flag para
apagarlo — un numero sin su medicion es el modo de fallo historico del repo.

Sin estado global de modulo: todo vive en ``EstadoRLM`` dentro del ctx del
bucle (contrato congelado 2026-08-11). Los imports de tools/loop/schemas son
perezosos dentro de ``correr_rlm`` porque tools.py importa este modulo al
final: un import a nivel de modulo cerraria el ciclo.
"""
from __future__ import annotations

import bisect
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

# El paquete regex (presente en venv312) soporta timeout por busqueda; con re
# puro un patron con backtracking catastrofico ('(a+)+b') colgaria el REPL
# entero dentro de ctx_grep. Fallback a re si no esta instalado.
try:
    import regex as _regex
except ImportError:      # pragma: no cover - depende del entorno
    _regex = None

# Caps de las tools de lectura: lo que el raiz VE por llamada. 8000 chars es
# el mismo orden que el contexto por paso del camino legacy (char_cap de
# objective_context); mas que eso y el raiz termina cargandose el contexto a
# la ventana por la puerta de atras, que es exactamente lo que el modo evita.
MAX_CHARS_VISTA = 8000
# Cap del fragmento que viaja a una subllamada: 60k chars (~15k tok) entra
# comodo en la ventana del hijo con lugar para pensamiento y respuesta.
MAX_CHARS_TROZO = 60000
MAX_MATCHES_GREP = 80

# Deadlines de ctx_grep: timeout por busqueda (paquete regex) y tope de
# pared del barrido entero — espejo del _SCAN_DEADLINE_S de la tool buscar.
_GREP_TIMEOUT_S = 2.0
_GREP_DEADLINE_S = 12.0

# Al listar/mostrar lineas sueltas se capan a 200 chars: una linea gigante
# (minificado, JSONL) no debe comerse el presupuesto de vista entero.
_CAP_LINEA = 200

# Archivos > 2 MB se saltan al concatenar un directorio: casi siempre son
# datos generados, y un solo archivo asi ahogaria el contexto util.
_MAX_BYTES_ARCHIVO = 2 * 1024 * 1024

RLM_TOOLS = frozenset({"ctx_info", "ctx_ver", "ctx_grep", "ctx_partir",
                       "rlm_llamar"})

SYSTEM_RLM = """\
Sos el agente RLM de Cognia. El contexto sobre el que te preguntan NO esta
en tu ventana: vive afuera y lo tocas SOLO con estas herramientas:
- ctx_info: resumen del contexto (tamano, origen, primeras/ultimas lineas).
- ctx_ver <desde> | <hasta>: ver un rango CHICO de lineas.
- ctx_grep <patron>: buscar un regex y ver las lineas que matchean.
- ctx_partir <n>: limites de n trozos contiguos, para planificar.
- rlm_llamar <desde> | <hasta> | <pregunta>: delegar un trozo grande a una
  subllamada fresca que lo lee entero y te responde.
Metodo: explora primero con ctx_info / ctx_grep / ctx_partir; lee poco y
puntual con ctx_ver; los trozos grandes delegalos con rlm_llamar en vez de
leerlos vos. Cita linea y fuente en lo que afirmes. Cuando tengas la
respuesta, responde SIN llamar herramientas: esa respuesta final cierra."""


def _env_int(nombre: str, default: int) -> int:
    """Entero desde env con caida silenciosa al default (un typo en un env
    no debe tumbar el modo entero)."""
    try:
        return int(os.environ.get(nombre, "") or default)
    except ValueError:
        return default


# ── El contexto externo ────────────────────────────────────────────────


class ContextoRLM:
    """El texto largo que NO entra en la ventana, con su indice de lineas.

    ``lineas`` se computa UNA vez (split al construir) y los offsets de char
    por linea tambien: las tools convierten rangos de lineas a intervalos de
    chars todo el tiempo y re-splitear seria cuadratico.
    """

    def __init__(self, texto: str, origen: str):
        self.texto = texto
        self.origen = origen
        self.lineas = texto.split("\n")
        self.chars = len(texto)
        # Etiquetado "aprox" a proposito: lo REAL medido sale del usage de
        # cada respuesta, esto solo orienta al raiz sobre el tamano.
        self.tokens_aprox = self.chars // 4
        self._offsets = [0]
        for ln in self.lineas[:-1]:
            self._offsets.append(self._offsets[-1] + len(ln) + 1)

    def rango_chars(self, desde: int, hasta: int) -> tuple:
        """Intervalo (ini, fin) de chars de las lineas 1-index inclusive."""
        ini = self._offsets[desde - 1]
        fin = self._offsets[hasta - 1] + len(self.lineas[hasta - 1])
        return ini, fin

    def offset_linea(self, linea: int) -> int:
        """Char donde arranca la linea 1-index."""
        return self._offsets[linea - 1]

    @classmethod
    def cargar(cls, ruta: str) -> "ContextoRLM":
        """Archivo -> tal cual; directorio -> concatenado con cabeceras.

        Lanza si la ruta no existe: correr_rlm es quien degrada sin lanzar
        (las tools nunca ven un contexto a medio cargar).
        """
        p = Path(ruta)
        if p.is_file():
            crudo = p.read_bytes()
            return cls(crudo.decode("utf-8", errors="replace"), str(p))
        if p.is_dir():
            partes = []
            # sorted sobre las rutas: orden ESTABLE entre corridas (los
            # numeros de linea del informe tienen que ser reproducibles).
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                try:
                    if f.stat().st_size > _MAX_BYTES_ARCHIVO:
                        continue
                    crudo = f.read_bytes()
                except OSError:
                    continue
                # Heuristica de binario barata: un NUL en la cabeza. Un PNG
                # o un GGUF concatenado como mojibake solo mete ruido.
                if b"\x00" in crudo[:4096]:
                    continue
                rel = f.relative_to(p).as_posix()
                partes.append(f"=== ARCHIVO: {rel} ===\n"
                              + crudo.decode("utf-8", errors="replace"))
            return cls("\n".join(partes), str(p))
        raise FileNotFoundError(f"no existe la ruta '{ruta}'")


# ── El medidor (el informe SIEMPRE sale de aca) ─────────────────────────


class MedidorContexto:
    """Cuenta que porcion del contexto se vio de verdad y cuanto costo.

    Los intervalos vistos se guardan crudos y se FUSIONAN al consultar:
    releer el mismo rango 10 veces no infla la cobertura (el solape se
    colapsa). Los tokens vienen del usage REAL del server, no de la
    aproximacion por chars.
    """

    def __init__(self, ctx_chars: int = 0, ctx_lineas: int = 0,
                 origen: str = "", n_ctx=None, max_hijos: int = 16,
                 presupuesto_tokens: int = 120000, url_hijos: str = ""):
        self.ctx_chars = ctx_chars
        self.ctx_tokens_aprox = ctx_chars // 4
        self.ctx_lineas = ctx_lineas
        self.origen = origen
        self.n_ctx = n_ctx
        self.max_hijos = max_hijos
        self.presupuesto_tokens = presupuesto_tokens
        # A donde viajan las subllamadas: "" = cerebro (perfil), una URL =
        # worker dedicado. Vive en el medidor porque el informe tiene que
        # DECIR por donde salieron los hijos (un numero sin su via no se
        # puede comparar entre corridas con y sin worker).
        self.url_hijos = url_hijos
        self.intervalos_raiz: list = []
        self.intervalos_hijos: list = []
        self.tokens_in_raiz = 0
        self.tokens_out_raiz = 0
        self.ventana_pico_raiz = 0
        self.llamadas_hijo = 0
        self.tokens_in_hijos = 0
        self.tokens_out_hijos = 0

    # -- registro --

    def _registrar(self, intervalos: list, ini: int, fin: int) -> None:
        ini = max(0, int(ini))
        fin = min(int(fin), self.ctx_chars) if self.ctx_chars else int(fin)
        if fin > ini:
            intervalos.append((ini, fin))

    def ver_raiz(self, ini: int, fin: int) -> None:
        self._registrar(self.intervalos_raiz, ini, fin)

    def ver_hijo(self, ini: int, fin: int) -> None:
        self._registrar(self.intervalos_hijos, ini, fin)

    def registrar_raiz(self, usage: dict) -> None:
        u = usage or {}
        prompt = int(u.get("prompt_tokens") or 0)
        self.tokens_in_raiz += prompt
        self.tokens_out_raiz += int(u.get("completion_tokens") or 0)
        if prompt > self.ventana_pico_raiz:
            self.ventana_pico_raiz = prompt

    def registrar_hijo(self, usage: dict) -> None:
        u = usage or {}
        self.llamadas_hijo += 1
        self.tokens_in_hijos += int(u.get("prompt_tokens") or 0)
        self.tokens_out_hijos += int(u.get("completion_tokens") or 0)

    # -- consulta --

    @staticmethod
    def _fusionar(intervalos: list) -> list:
        """Intervalos ordenados y sin solapes (la unica forma honesta de
        sumar cobertura)."""
        fusionados: list = []
        for ini, fin in sorted(intervalos):
            if fusionados and ini <= fusionados[-1][1]:
                fusionados[-1] = (fusionados[-1][0],
                                  max(fusionados[-1][1], fin))
            else:
                fusionados.append((ini, fin))
        return fusionados

    @classmethod
    def _chars_de(cls, intervalos: list) -> int:
        return sum(fin - ini for ini, fin in cls._fusionar(intervalos))

    def _cobertura(self, intervalos: list) -> float:
        if not self.ctx_chars:
            return 0.0
        return self._chars_de(intervalos) / self.ctx_chars

    def cobertura_raiz(self) -> float:
        return self._cobertura(self.intervalos_raiz)

    def cobertura_hijos(self) -> float:
        return self._cobertura(self.intervalos_hijos)

    def cobertura_union(self) -> float:
        return self._cobertura(self.intervalos_raiz + self.intervalos_hijos)

    def tokens_totales(self) -> int:
        return (self.tokens_in_raiz + self.tokens_out_raiz
                + self.tokens_in_hijos + self.tokens_out_hijos)

    def como_dict(self) -> dict:
        return {
            "ctx_chars": self.ctx_chars,
            "ctx_tokens_aprox": self.ctx_tokens_aprox,
            "ctx_lineas": self.ctx_lineas,
            "origen": self.origen,
            "visto_raiz_chars": self._chars_de(self.intervalos_raiz),
            "visto_hijos_chars": self._chars_de(self.intervalos_hijos),
            "visto_union_chars": self._chars_de(self.intervalos_raiz
                                                + self.intervalos_hijos),
            "cobertura_raiz": self.cobertura_raiz(),
            "cobertura_hijos": self.cobertura_hijos(),
            "cobertura_union": self.cobertura_union(),
            "tokens_in_raiz": self.tokens_in_raiz,
            "tokens_out_raiz": self.tokens_out_raiz,
            "ventana_pico_raiz": self.ventana_pico_raiz,
            "llamadas_hijo": self.llamadas_hijo,
            "tokens_in_hijos": self.tokens_in_hijos,
            "tokens_out_hijos": self.tokens_out_hijos,
            "tokens_totales": self.tokens_totales(),
            "max_hijos": self.max_hijos,
            "presupuesto_tokens": self.presupuesto_tokens,
            "n_ctx": self.n_ctx,
            "url_hijos": self.url_hijos,
        }

    def informe(self) -> str:
        """El bloque que se adjunta a CADA corrida (contrato: sin flag para
        apagarlo). Formato congelado 2026-08-11."""
        if self.n_ctx:
            pct = self.ventana_pico_raiz / int(self.n_ctx)
            ventana = (f"{self.ventana_pico_raiz:,} tok de {self.n_ctx} "
                       f"({pct:.1%})")
        else:
            # Sin n_ctx conocido el porcentaje seria inventado: se dice "?".
            ventana = f"{self.ventana_pico_raiz:,} tok de ? (?)"
        lineas = [
            "[contexto efectivo RLM]",
            (f"contexto: {self.ctx_chars:,} chars "
             f"(~{self.ctx_tokens_aprox:,} tok aprox) | "
             f"{self.ctx_lineas:,} lineas | origen: {self.origen}"),
            (f"visto raiz: {self.cobertura_raiz():.1%} "
             f"({self._chars_de(self.intervalos_raiz):,} chars) | "
             f"visto hijos: {self.cobertura_hijos():.1%} "
             f"({self._chars_de(self.intervalos_hijos):,} chars) | "
             f"union: {self.cobertura_union():.1%}"),
            f"ventana pico raiz: {ventana}",
            (f"subllamadas: {self.llamadas_hijo}/{self.max_hijos} | "
             f"tokens hijos: {self.tokens_in_hijos:,} in / "
             f"{self.tokens_out_hijos:,} out | "
             f"raiz: {self.tokens_in_raiz:,} in / "
             f"{self.tokens_out_raiz:,} out"),
            (f"presupuesto: {self.tokens_totales():,} de "
             f"{self.presupuesto_tokens:,} tok"),
        ]
        # SOLO si hubo subllamadas o worker activo (contrato 2026-08-11):
        # en una corrida sin hijos ni worker la linea seria ruido fijo.
        if self.llamadas_hijo or self.url_hijos:
            lineas.append(f"hijos via: {self.url_hijos or 'cerebro (:8080)'}")
        return "\n".join(lineas)


@dataclass
class EstadoRLM:
    """Todo el estado del modo, inyectable: viaja en ctx['_rlm'] y NADA vive
    a nivel de modulo (contrato; el estado global es el modo de fallo que ya
    mordio en chat_client con _KV_SUCIO)."""
    contexto: ContextoRLM
    medidor: MedidorContexto
    completar_fn: object          # inyectable en tests; default chat_client.completar
    perfil: dict
    max_hijos: int = 16
    presupuesto_tokens: int = 120000
    # 8192 (antes 2048, fix 2026-08-11): el hijo puede ser un razonador que
    # gasta el grueso del presupuesto PENSANDO en <think> — 2048 degollaba la
    # respuesta (la leccion repetida de los 10 bugs de presupuesto: todo
    # max_tokens debe cubrir el pensamiento).
    hijo_max_tokens: int = 8192
    # Cap EFECTIVO del trozo de rlm_llamar (fix 2026-08-11): correr_rlm lo
    # deriva de la ventana real del destino de los hijos — el cap historico
    # de 60k chars (~20k tok) NO cabe en un worker de ctx 16384 y el hijo
    # respondia sobre un fragmento degollado por el server en silencio.
    max_chars_trozo: int = MAX_CHARS_TROZO
    # Ruteo de hijos (contrato 2026-08-11): "" / None = cerebro con el
    # sampling del perfil, como siempre. Con worker: url_hijos apunta al rol
    # 'worker' del summoner y sampling_hijos trae su temperatura/top_p
    # propios (Qwen3 thinking pide 0.6/0.95, no el 0.7/0.8 de qwythos).
    url_hijos: str = ""
    sampling_hijos: dict = None


# ── Las 5 tools (fn(args, ctx) -> str) ─────────────────────────────────


def _estado_de(ctx: dict, tool_name: str):
    """(estado, error): las tools RLM solo funcionan con el modo armado."""
    estado = (ctx or {}).get("_rlm")
    if estado is None:
        return None, (f"RESULTADO {tool_name} ERROR: el modo RLM no esta "
                      "activo (usa /rlm).")
    return estado, ""


def _parse_rango(sdesde: str, shasta: str, total: int, tool_name: str):
    """((desde, hasta), '') validado 1-index inclusive, o (None, ERROR)."""
    try:
        desde, hasta = int(str(sdesde).strip()), int(str(shasta).strip())
    except ValueError:
        return None, (f"RESULTADO {tool_name} ERROR: lineas invalidas "
                      f"'{sdesde} | {shasta}'; el rango valido es 1-{total}")
    if desde < 1 or hasta > total or desde > hasta:
        return None, (f"RESULTADO {tool_name} ERROR: rango {desde}-{hasta} "
                      f"fuera del contexto; el rango valido es 1-{total}")
    return (desde, hasta), ""


def _ctx_info(args: str, ctx: dict) -> str:
    estado, err = _estado_de(ctx, "ctx_info")
    if err:
        return err
    c = estado.contexto
    n = len(c.lineas)
    salida = [(f"RESULTADO ctx_info: {c.chars:,} chars "
               f"(~{c.tokens_aprox:,} tok aprox) | {n:,} lineas | "
               f"origen: {c.origen}")]
    # Bordes del contexto: primeras 15 + ultimas 5 (sin solapar si es corto).
    prim_hasta = min(15, n)
    salida.append(f"primeras {prim_hasta} lineas:")
    for i in range(1, prim_hasta + 1):
        salida.append(f"{i}: {c.lineas[i - 1][:_CAP_LINEA]}")
    ult_desde = 0
    if n > 20:
        ult_desde = n - 4
        salida.append("ultimas 5 lineas:")
        for i in range(ult_desde, n + 1):
            salida.append(f"{i}: {c.lineas[i - 1][:_CAP_LINEA]}")
    # Cada cabecera capada a _CAP_LINEA y la linea armada al cap de vista:
    # una linea de contenido que empiece con '=== ARCHIVO: ' (el contexto es
    # texto arbitrario) no debe poder colar contenido sin limite a la ventana.
    cabeceras = [ln[len("=== ARCHIVO: "):].rstrip("= ").strip()[:_CAP_LINEA]
                 for ln in c.lineas if ln.startswith("=== ARCHIVO: ")]
    if cabeceras:
        mostradas = cabeceras[:40]
        linea = f"archivos ({len(cabeceras)}): " + ", ".join(mostradas)
        if len(cabeceras) > len(mostradas):
            linea += f" ... y {len(cabeceras) - len(mostradas)} mas"
        salida.append(linea[:MAX_CHARS_VISTA])
    # Lo devuelto cuenta como VISTO por el raiz: SOLO la porcion mostrada de
    # cada linea (registrar lineas enteras capadas a 200 chars inflaria la
    # cobertura — con una linea minificada de 400k chars el informe diria
    # 100% habiendo mostrado 200 chars).
    if n and c.chars:
        indices = list(range(1, prim_hasta + 1))
        if ult_desde:
            indices += range(ult_desde, n + 1)
        for i in indices:
            ini = c.offset_linea(i)
            visto = min(len(c.lineas[i - 1]), _CAP_LINEA)
            if visto:
                estado.medidor.ver_raiz(ini, ini + visto)
    return "\n".join(salida)


def _ctx_ver(args: str, ctx: dict) -> str:
    estado, err = _estado_de(ctx, "ctx_ver")
    if err:
        return err
    c = estado.contexto
    partes = re.split(r"\s*\|\s*", (args or "").strip(), maxsplit=1)
    if len(partes) != 2:
        return ("RESULTADO ctx_ver ERROR: faltan argumentos; usa "
                f"ctx_ver <desde> | <hasta> con lineas 1-{len(c.lineas)}")
    rango, msg = _parse_rango(partes[0], partes[1], len(c.lineas), "ctx_ver")
    if rango is None:
        return msg
    desde, hasta = rango
    # Prefijo de lineas ENTERAS que entra en MAX_CHARS_VISTA; la primera se
    # acepta siempre (y se recorta despues si sola ya revienta el cap).
    acum, fin_linea = 0, desde
    for i in range(desde, hasta + 1):
        largo = len(c.lineas[i - 1]) + 1
        if i > desde and acum + largo > MAX_CHARS_VISTA:
            break
        acum += largo
        fin_linea = i
    cuerpo = [f"{i}: {c.lineas[i - 1]}" for i in range(desde, fin_linea + 1)]
    ini_char = c.offset_linea(desde)
    linea_recortada = False
    if fin_linea == desde and len(c.lineas[desde - 1]) > MAX_CHARS_VISTA:
        # Una sola linea gigante: se devuelve el prefijo y se registra SOLO
        # eso (registrar la linea entera inflaria la cobertura con texto que
        # el modelo jamas vio).
        cuerpo = [f"{desde}: {c.lineas[desde - 1][:MAX_CHARS_VISTA]}"]
        estado.medidor.ver_raiz(ini_char, ini_char + MAX_CHARS_VISTA)
        linea_recortada = True
    else:
        estado.medidor.ver_raiz(*c.rango_chars(desde, fin_linea))
    salida = (f"RESULTADO ctx_ver [lineas {desde}-{fin_linea}]:\n"
              + "\n".join(cuerpo))
    if linea_recortada:
        # Sin este aviso el modelo cree haber visto la linea ENTERA y
        # concluye que lo que esta despues del char 8000 no existe.
        salida += (f"\n[recortado: la linea {desde} mide "
                   f"{len(c.lineas[desde - 1])} chars y solo se muestran "
                   f"los primeros {MAX_CHARS_VISTA}; usa ctx_grep o "
                   "rlm_llamar]")
    if fin_linea < hasta:
        salida += (f"\n[recortado: devueltas lineas {desde}-{fin_linea} de "
                   f"{desde}-{hasta} pedidas; usa rangos mas finos o "
                   "rlm_llamar]")
    return salida


def _ctx_grep(args: str, ctx: dict) -> str:
    estado, err = _estado_de(ctx, "ctx_grep")
    if err:
        return err
    c = estado.contexto
    # El patron va INTACTO al compile: strip() solo para detectar vacio (un
    # regex con espacios significativos, 'ERROR ', perderia matches en
    # silencio si se recortara).
    patron = args or ""
    if not patron.strip():
        return ("RESULTADO ctx_grep ERROR: falta el patron; usa "
                "ctx_grep <patron> (regex)")
    motor = _regex or re
    try:
        rx = motor.compile(patron)
    except Exception as exc:
        return f"RESULTADO ctx_grep ERROR: patron regex invalido: {exc}"
    # Doble defensa contra colgar el REPL: timeout por busqueda (si el
    # paquete regex esta) + deadline de pared sobre el barrido completo.
    deadline = time.monotonic() + _GREP_DEADLINE_S
    mostradas, chars_out, total = [], 0, 0
    for i, ln in enumerate(c.lineas, 1):
        if time.monotonic() > deadline:
            return (f"RESULTADO ctx_grep ERROR: el barrido supero "
                    f"{_GREP_DEADLINE_S:.0f}s en la linea {i}; simplifica "
                    "el patron")
        try:
            m = (rx.search(ln, timeout=_GREP_TIMEOUT_S) if _regex
                 else rx.search(ln))
        except TimeoutError:
            return (f"RESULTADO ctx_grep ERROR: el patron tardo mas de "
                    f"{_GREP_TIMEOUT_S:.0f}s en la linea {i} (backtracking "
                    "catastrofico); simplifica el patron")
        if not m:
            continue
        total += 1
        if len(mostradas) >= MAX_MATCHES_GREP or chars_out >= MAX_CHARS_VISTA:
            continue     # se sigue CONTANDO para reportar cuantos quedaron
        # Ventana CENTRADA en el match: recortar siempre desde el inicio de
        # la linea escondia matches despues de la columna 200 (el modelo
        # recibia una linea "matcheada" sin el match adentro).
        if len(ln) <= _CAP_LINEA:
            desde_col = 0
        else:
            desde_col = max(0, min(m.start() - _CAP_LINEA // 2,
                                   len(ln) - _CAP_LINEA))
        recorte = ln[desde_col:desde_col + _CAP_LINEA]
        prefijo = f"{i} (char {desde_col}): ..." if desde_col else f"{i}: "
        mostradas.append(prefijo + recorte)
        chars_out += len(recorte) + len(prefijo)
        # Visto: SOLO la porcion mostrada de cada linea (registrar la linea
        # entera inflaria cobertura sobre texto no visto).
        ini = c.offset_linea(i) + desde_col
        estado.medidor.ver_raiz(ini, ini + len(recorte))
    if not total:
        return "RESULTADO ctx_grep: 0 matches de ese patron en el contexto"
    salida = (f"RESULTADO ctx_grep: {len(mostradas)} de {total} matches\n"
              + "\n".join(mostradas))
    if total > len(mostradas):
        salida += f"\n[... {total - len(mostradas)} matches mas; afina el patron]"
    return salida


def _ctx_partir(args: str, ctx: dict) -> str:
    estado, err = _estado_de(ctx, "ctx_partir")
    if err:
        return err
    c = estado.contexto
    try:
        n = int((args or "").strip())
    except ValueError:
        return ("RESULTADO ctx_partir ERROR: n invalido; usa "
                "ctx_partir <n> con n entre 2 y 64")
    if not 2 <= n <= 64:
        return (f"RESULTADO ctx_partir ERROR: n={n} fuera de rango; "
                "usa n entre 2 y 64")
    if not c.chars:
        return "RESULTADO ctx_partir ERROR: el contexto esta vacio"
    # Cortes por CHAR (trozos ~iguales en costo, no en lineas), alineados a
    # inicio de linea con bisect sobre los offsets ya computados.
    cortes = [0]
    for i in range(1, n):
        objetivo = c.chars * i // n
        idx = bisect.bisect_left(c._offsets, objetivo)
        idx = max(idx, cortes[-1] + 1)
        if idx >= len(c.lineas):
            break            # mas trozos que lineas: se devuelven menos
        cortes.append(idx)
    salida = []
    for j, ini in enumerate(cortes):
        fin = (cortes[j + 1] - 1) if j + 1 < len(cortes) else len(c.lineas) - 1
        ini_ch, fin_ch = c.rango_chars(ini + 1, fin + 1)
        salida.append(f"trozo {j + 1}: lineas {ini + 1}-{fin + 1} "
                      f"(~{fin_ch - ini_ch:,} chars)")
    # NO registra visto: los limites son indice, no contenido del contexto.
    return (f"RESULTADO ctx_partir ({len(cortes)} trozos):\n"
            + "\n".join(salida))


def _rlm_llamar(args: str, ctx: dict) -> str:
    estado, err = _estado_de(ctx, "rlm_llamar")
    if err:
        return err
    c = estado.contexto
    # La pregunta es contenido libre (puede contener '|') y va ULTIMA:
    # maxsplit=2 la preserva entera (regla transversal del separador legacy).
    partes = re.split(r"\s*\|\s*", (args or "").strip(), maxsplit=2)
    if len(partes) != 3 or not partes[2].strip():
        return ("RESULTADO rlm_llamar ERROR: faltan argumentos; usa "
                "rlm_llamar <desde> | <hasta> | <pregunta>")
    rango, msg = _parse_rango(partes[0], partes[1], len(c.lineas),
                              "rlm_llamar")
    if rango is None:
        return msg
    desde, hasta = rango
    pregunta = partes[2].strip()
    med = estado.medidor
    # Guardas EN ORDEN (contrato): fan-out, presupuesto, tamano del trozo.
    # Cada una con su mensaje propio para que el raiz sepa QUE ajustar.
    if med.llamadas_hijo >= estado.max_hijos:
        return (f"RESULTADO rlm_llamar ERROR: limite de {estado.max_hijos} "
                "subllamadas agotado")
    usados = med.tokens_totales()
    if usados >= estado.presupuesto_tokens:
        return (f"RESULTADO rlm_llamar ERROR: presupuesto RLM de "
                f"{estado.presupuesto_tokens} tokens agotado (llevas "
                f"{usados}); cierra con lo que tienes")
    ini_ch, fin_ch = c.rango_chars(desde, hasta)
    # El limite EFECTIVO (derivado de la ventana del destino de los hijos,
    # fix 2026-08-11) y no el cap historico: el mensaje tiene que decir el
    # numero contra el que el trozo choco DE VERDAD, o el raiz re-parte
    # apuntando a un limite que no rige.
    limite_trozo = estado.max_chars_trozo
    if fin_ch - ini_ch > limite_trozo:
        return (f"RESULTADO rlm_llamar ERROR: trozo de {fin_ch - ini_ch} "
                f"chars supera el limite de {limite_trozo}; parti mas "
                "fino (ctx_partir)")
    fragmento = "\n".join(c.lineas[desde - 1:hasta])
    perfil = estado.perfil or {}
    # Ruteo del hijo: worker si correr_rlm lo resolvio, perfil si no. El
    # sampling viaja JUNTO con la url (mandar 0.7/0.8 de qwythos a un Qwen3
    # thinking degrada al hijo en silencio, que es peor que no rutear).
    sampling = estado.sampling_hijos or {}
    mensajes = [
        {"role": "system", "content": (
            "Sos un analista. Responde SOLO con base en el FRAGMENTO dado. "
            "Si la respuesta no esta en el fragmento, decilo "
            "explicitamente: 'no esta en este fragmento'. Se conciso y "
            "textual (cita literal cuando sirva).")},
        {"role": "user", "content": (
            f"FRAGMENTO (lineas {desde}-{hasta} de {c.origen}):\n"
            f"{fragmento}\n\nPREGUNTA: {pregunta}")},
    ]
    # SIN kwarg tools: la profundidad 1 es ESTRUCTURAL — el hijo no puede
    # llamar herramientas porque el server nunca se las ofrece.
    resp = estado.completar_fn(
        mensajes,
        max_tokens=estado.hijo_max_tokens,
        razonador=True,
        temperature=sampling.get("temperature",
                                 perfil.get("temperature", 0.7)),
        top_p=sampling.get("top_p", perfil.get("top_p", 0.8)),
        url=estado.url_hijos or perfil.get("url", ""),
        via="rlm_hijo",
    )
    if resp.error and estado.url_hijos:
        # Worker que MUERE a mitad de corrida (fix 2026-08-11): el worker es
        # un EXTRA, jamas una dependencia — su caida no puede costar la
        # subllamada ni las que siguen. Se degrada el ESTADO (url_hijos vacia:
        # los proximos hijos van directo al cerebro, sin volver a golpear un
        # muerto) y ESTA llamada se reintenta UNA vez contra el cerebro con
        # el sampling del perfil (el 0.6/0.95 del worker no aplica al cerebro).
        pf = (ctx or {}).get("print_fn")
        if callable(pf):
            pf(f"worker cayo: {resp.error}; hijos degradan al cerebro")
        estado.url_hijos = ""
        estado.sampling_hijos = None
        # El informe tambien degrada: la llamada al worker FALLO (ningun hijo
        # exitoso salio de ahi), asi que dejar su url en el medidor mentiria
        # "hijos via: worker" sobre hijos que en realidad atendio el cerebro.
        estado.medidor.url_hijos = ""
        resp = estado.completar_fn(
            mensajes,
            max_tokens=estado.hijo_max_tokens,
            razonador=True,
            temperature=perfil.get("temperature", 0.7),
            top_p=perfil.get("top_p", 0.8),
            url=perfil.get("url", ""),
            via="rlm_hijo",
        )
    if resp.error:
        return f"RESULTADO rlm_llamar ERROR: {resp.error}"
    med.registrar_hijo(resp.usage)
    med.ver_hijo(ini_ch, fin_ch)
    # El texto del hijo va en linea APARTE: la convencion \bERROR\b del bucle
    # se evalua sobre la primera linea, y un hijo que cite errores del
    # contexto (el caso de uso central: logs) no debe marcar la tool fallida.
    salida = f"RESULTADO rlm_llamar [lineas {desde}-{hasta}]:\n{resp.texto}"
    if resp.finish_reason == "length":
        # Los dos modos de fallo (respuesta corta legitima vs degollada por
        # presupuesto) se veian iguales sin esto (leccion stop_type/usage).
        salida += "\n[respuesta del hijo truncada por max_tokens]"
    return salida


def register(tool):
    """Registra las 5 tools RLM en el registry de tools.py.

    Llamado desde tools.py al final del modulo (patron horizonte: siempre
    registradas, gateadas por ctx['_rlm'] en runtime, NO en CORE_TOOLS)."""
    tool("ctx_info",
         "ctx_info                              -- resumen del contexto RLM (tamano, origen, bordes)",
         desc=("Resumen del contexto RLM cargado: tamano en chars/lineas, "
               "origen, primeras y ultimas lineas y lista de archivos si es "
               "un directorio concatenado. Usala PRIMERO para orientarte."),
         params=[])(_ctx_info)
    tool("ctx_ver",
         "ctx_ver <desde> | <hasta>             -- ver lineas del contexto RLM",
         desc=("Muestra un rango CHICO de lineas del contexto RLM (1-index "
               "inclusive, cap 8000 chars por llamada). Para trozos grandes "
               "usa rlm_llamar en vez de leerlos vos."),
         params=[{"nombre": "desde", "tipo": "integer", "requerido": True,
                  "descripcion": "primera linea del rango (1-index)"},
                 {"nombre": "hasta", "tipo": "integer", "requerido": True,
                  "descripcion": "ultima linea del rango (inclusive)"}])(_ctx_ver)
    tool("ctx_grep",
         "ctx_grep <patron>                     -- buscar regex en el contexto RLM",
         desc=("Busca un regex en el contexto RLM y devuelve las lineas que "
               "matchean con su numero (hasta 80 matches). Es la forma "
               "barata de localizar donde esta algo antes de leer."),
         params=[{"nombre": "patron", "tipo": "string", "requerido": True,
                  "descripcion": "regex a buscar (respeta mayusculas)"}])(_ctx_grep)
    tool("ctx_partir",
         "ctx_partir <n>                        -- limites de n trozos contiguos del contexto RLM",
         desc=("Devuelve los limites de n trozos contiguos de tamano "
               "parecido (por chars) del contexto RLM, sin mostrar "
               "contenido. Para planificar subllamadas rlm_llamar."),
         params=[{"nombre": "n", "tipo": "integer", "requerido": True,
                  "descripcion": "cantidad de trozos (entre 2 y 64)"}])(_ctx_partir)
    tool("rlm_llamar",
         "rlm_llamar <desde> | <hasta> | <pregunta>  -- delegar un trozo a una subllamada LLM fresca",
         desc=("Manda las lineas desde-hasta del contexto RLM a una "
               "subllamada LLM fresca (sin herramientas) que las lee "
               "enteras y responde la pregunta. Es la via para trozos que "
               "no entran en ctx_ver; el trozo se capa a 60000 chars o "
               "menos segun la ventana del hijo (el ERROR dice el limite)."),
         params=[{"nombre": "desde", "tipo": "integer", "requerido": True,
                  "descripcion": "primera linea del trozo (1-index)"},
                 {"nombre": "hasta", "tipo": "integer", "requerido": True,
                  "descripcion": "ultima linea del trozo (inclusive)"},
                 {"nombre": "pregunta", "tipo": "string", "requerido": True,
                  "descripcion": "pregunta a responder SOLO con ese trozo"}])(_rlm_llamar)


# ── El runner ──────────────────────────────────────────────────────────


def correr_rlm(pregunta: str, ruta: str, print_fn=None, completar_fn=None,
               max_turns: int = 24, url: str = "",
               worker: bool = None) -> dict:
    """Corre el modo RLM: carga el contexto, arma el estado y lanza el bucle
    nativo con SOLO las 5 tools RLM.

    worker: rutear las subllamadas (hijos) al rol 'worker' del summoner en
    vez del cerebro. None (default) delega en COGNIA_RLM_WORKER == "1";
    True/False explicitos pisan el env. El worker es un EXTRA, jamas una
    dependencia: cualquier fallo del summoner degrada al cerebro con aviso
    por print_fn y la corrida sigue (contrato 2026-08-11).

    Devuelve {"texto", "ok", "pasos", "informe", "medidor", ...}: el dict
    del bucle mas el informe del medidor, que se adjunta SIEMPRE — aun
    cuando el bucle termino en error (medir es parte del contrato, no un
    premio del camino feliz).
    """
    pf = print_fn or (lambda *a, **k: None)
    try:
        contexto = ContextoRLM.cargar(ruta)
    except Exception as exc:
        # Ruta inexistente / ilegible: se degrada sin lanzar (contrato).
        return {"texto": f"ERROR cargando el contexto de '{ruta}': {exc}",
                "ok": False, "pasos": 0, "informe": "", "medidor": {}}

    # Imports PEREZOSOS: tools.py importa este modulo al final para
    # registrar las tools — un import de tools/loop/schemas a nivel de
    # modulo cerraria el ciclo.
    from cognia.agent import loop as _loop
    from cognia.agent import tools as _tools
    from cognia.agent.chat_client import mensaje_assistant, mensaje_tool
    from cognia.agent.tool_schemas import args_legacy, schemas_para

    try:
        from cognia.agent import model_profiles as _mp
        perfil = _mp.perfil_del_agente(url)
    except Exception:
        perfil = None
    if not perfil or "temperature" not in perfil:
        # Backend caido o perfil texto (sin sampling): fallback Qwen-like.
        # El modo RLM necesita tool-calling nativo si o si; con el server
        # muerto el bucle igual degrada con causa visible al primer paso.
        perfil = {"nombre": "rlm_fallback", "modelo": "?", "url": url,
                  "tools": "nativo", "n_ctx": 32768, "temperature": 0.7,
                  "top_p": 0.8, "reasoning_effort": "", "max_tokens": 4096}

    if completar_fn is None:
        from cognia.agent.chat_client import completar as completar_fn

    # Ruteo de hijos al worker (opt-in por flag o env). El import del
    # summoner es PEREZOSO y esta adentro del try: importar el modulo o
    # llamar ensure puede fallar por mil causas (VRAM, puerto tomado, GGUF
    # ausente) y NINGUNA puede colgar ni abortar el modo RLM — el peor caso
    # contratado es "hijos al cerebro, con aviso".
    if worker is None:
        worker = os.environ.get("COGNIA_RLM_WORKER", "") == "1"
    url_hijos, sampling_hijos, n_ctx_worker = "", None, None
    if worker:
        causa = ""
        try:
            from cognia import summoner as _summoner
            res_w = _summoner.ensure("worker", evictar=False)
            url_hijos = str(res_w.get("url") or "")
            # La ventana REAL del worker viaja en el dict de ensure: es el
            # dato del que se deriva el trozo maximo (fix 2026-08-11).
            n_ctx_worker = res_w.get("n_ctx")
            if not url_hijos:
                # ensure "ok" sin url (respuesta rara) es tan inservible
                # para rutear como un fallo: misma degradacion.
                causa = "ensure no devolvio url"
        except Exception as exc:
            causa = str(exc) or type(exc).__name__
        if url_hijos:
            # Sampling del worker (Qwen3 thinking): 0.6/0.95, no el del
            # cerebro. Viaja apareado con la url en el estado.
            sampling_hijos = {"temperature": 0.6, "top_p": 0.95}
        else:
            pf(f"worker no disponible: {causa}; hijos van al cerebro")

    # Default 8192 (antes 2048, fix 2026-08-11): el hijo razonador piensa en
    # <think> y 2048 degollaba la respuesta (leccion de los 10 bugs).
    hijo_max_tokens = _env_int("COGNIA_RLM_HIJO_TOKENS", 8192)
    # El trozo maximo de rlm_llamar se deriva de la ventana REAL del destino
    # de los hijos (fix 2026-08-11): 60k chars (~20k tok) NO caben en un
    # worker de ctx 16384 — el server truncaria el fragmento y el hijo
    # responderia en silencio sobre un texto que nunca vio entero. 3 chars/tok
    # conservador; -1024 de margen para system+pregunta; piso 8000 (una vista)
    # para que un ctx chico no vuelva inutil a rlm_llamar; techo el cap
    # historico (mas de 60k tampoco conviene por costo del hijo).
    n_ctx_hijo = n_ctx_worker if url_hijos else None
    if not n_ctx_hijo:
        n_ctx_hijo = perfil.get("n_ctx")
    max_chars_trozo = MAX_CHARS_TROZO
    if n_ctx_hijo:
        max_chars_trozo = min(
            MAX_CHARS_TROZO,
            max(8000, (int(n_ctx_hijo) - hijo_max_tokens - 1024) * 3))

    medidor = MedidorContexto(
        ctx_chars=contexto.chars, ctx_lineas=len(contexto.lineas),
        origen=contexto.origen, n_ctx=perfil.get("n_ctx"),
        max_hijos=_env_int("COGNIA_RLM_MAX_HIJOS", 16),
        presupuesto_tokens=_env_int("COGNIA_RLM_PRESUPUESTO", 120000),
        url_hijos=url_hijos)
    estado = EstadoRLM(
        contexto=contexto, medidor=medidor, completar_fn=completar_fn,
        perfil=perfil, max_hijos=medidor.max_hijos,
        presupuesto_tokens=medidor.presupuesto_tokens,
        hijo_max_tokens=hijo_max_tokens,
        url_hijos=url_hijos, sampling_hijos=sampling_hijos,
        max_chars_trozo=max_chars_trozo)

    def _completar_raiz(mensajes, **kw):
        # El wrapper MIDE cada paso del raiz (usage real + ventana pico).
        # No corta por presupuesto: ese corte vive en rlm_llamar — el raiz
        # siempre puede cerrar con lo que tiene, cortarlo aca lo dejaria
        # mudo justo cuando debe redactar la respuesta.
        resp = completar_fn(mensajes, **kw)
        medidor.registrar_raiz(getattr(resp, "usage", None) or {})
        return resp

    ctx = {"_rlm": estado, "_allowed_tools": set(RLM_TOOLS),
           "working_memory": {}, "agent_state": {}, "print_fn": pf}
    try:
        res = _loop.bucle_nativo(
            task=pregunta, system=SYSTEM_RLM, completar=_completar_raiz,
            schemas=schemas_para(RLM_TOOLS), args_legacy=args_legacy,
            mensaje_assistant=mensaje_assistant, mensaje_tool=mensaje_tool,
            run_tool=_tools.run_tool, ctx=ctx, perfil=perfil,
            history=[pregunta], trace=[], print_fn=pf,
            max_turns=min(max_turns, 40))
    except Exception as exc:
        # El informe sale IGUAL: lo medido hasta el fallo es evidencia.
        res = {"texto": f"ERROR en el bucle RLM: {exc}", "pasos": 0,
               "ok": False, "tokens": 0, "finish": ""}

    salida = dict(res)
    salida["informe"] = medidor.informe()
    salida["medidor"] = medidor.como_dict()
    return salida
