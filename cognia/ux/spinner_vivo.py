"""
cognia/ux/spinner_vivo.py
=========================
La linea de estado VIVA del turno (F2, 2026-08-23).

POR QUE EXISTE: la linea de espera de Claude Code/Codex SIEMPRE responde tres
preguntas — ¿esta vivo? ¿cuanto lleva? ¿como lo paro? — y el spinner de Cognia
era mas mudo que eso ('pensando… (3s)' en el mejor caso). Este modulo COMPONE
esa linea: verbo rotatorio con personalidad de gato + segundos + ~tokens
recibidos del stream + el hint de corte REAL de Cognia (Ctrl-C corta el turno,
no el REPL — cli.py maneja KeyboardInterrupt en el streaming y en /hacer; no
existe 'esc' aqui y decirlo seria mentir).

Solo composicion PURA y lectura de config: el que anima es el renderer
(ux/renderer.py, un hilo ticker sobre el rich status ya existente). Asi la
linea se testea sin terminal ni hilos.

Config (a CALL-TIME, mismo patron que renderer._config_colapso):
- clave 'spinner_info' on|off (default on) -> /spinner on|off
- clave 'spinner_verbos' (lista JSON o texto separado por comas; vacia = los
  VERBOS_GATO de aqui) -> /spinner verbos ...
- env COGNIA_SPINNER_INFO=0 apaga la linea viva GANANDO a la config (y =1 la
  fuerza); COGNIA_SPINNER=0 sigue apagando TODO el spinner (renderer).

ASPECTO POR ELEMENTO (P8 del sistema de estilos, 2026-08-24): la marca '·',
el nombre del spinner de rich, el hint, el separador ' · ', la palabra 'tok'
y el 'pensando…' salen del registro cognia/ux/aspecto (ids spinner.tool,
spinner.pensar, spinner.comando) via aspecto_spinner(id), a CALL-TIME y con
los literales de hoy como default (golden 'spinner' byte-identico sin fichero
de estilo). Si el registro no se puede leer, se AVISA por _aviso_degradado
('spinner', ...) y se usan los defaults: nunca en silencio. estilo_spinner(id)
entrega el EstiloGlow que glow.LineaViva anima dentro del console.status del
renderer (cero hilos nuevos: el ticker de 1 s ya existente dispara lv.set y la
Live del status recoge el cuadro del reloj compartido glow.RELOJ).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# El hint de corte REAL: Ctrl-C corta el turno y el REPL sigue vivo
# (cli.py: except KeyboardInterrupt en el streaming y en el spinner de
# 'Procesando...'). No es 'esc': prompt_toolkit no cablea escape a nada aqui.
HINT_CORTE = "ctrl+c corta"

# Separador y palabra 'tok' de hoy (defaults de aspecto: spinner.*.separador y
# texto.tok). Son los literales que el golden 'spinner' fija.
SEPARADOR = " · "
PALABRA_TOK = "tok"

# Cada cuantos segundos rota el verbo. 4s: bastante para leerlo, poco para
# que la linea parezca congelada.
PERIODO_ROTACION = 4

# ~4 chars por token: es una ESTIMACION honesta (por eso el '~' en la linea).
# El footer final sigue mostrando los tokens REALES del backend; esta cifra
# solo dice "siguen llegando cosas" mientras no hay footer.
_CHARS_POR_TOKEN = 4

# Los ~20 verbos gato por defecto: personalidad propia, sobrios, ASCII puro
# (la consola cp1252 no tiene donde tropezar). Se reemplazan enteros con la
# clave de config 'spinner_verbos' (/spinner verbos ...).
VERBOS_GATO = [
    "Maullando ideas",
    "Afilando garras",
    "Olfateando el repo",
    "Persiguiendo el hilo",
    "Amasando la respuesta",
    "Acechando el problema",
    "Ronroneando en voz baja",
    "Trepando al contexto",
    "Cazando el bug",
    "Escarbando en los datos",
    "Atando cabos",
    "Rumiando opciones",
    "Hilando fino",
    "Merodeando la solucion",
    "Desenredando el ovillo",
    "Agazapado, pensando",
    "Husmeando pistas",
    "Estirando el lomo",
    "Ordenando bigotes",
    "Saltando entre ramas",
]


def estimar_tokens(chars: int) -> int:
    """~tokens a partir de chars del stream. 0 si todavia no llego nada."""
    return max(0, int(chars) // _CHARS_POR_TOKEN)


def _sanear_verbo(v) -> str:
    """Un verbo de config apto para la linea: sin corchetes (romperian el
    markup de rich del status), sin saltos de linea, recortado."""
    return str(v).replace("[", "").replace("]", "").replace("\n", " ").strip()


def verbos_config(cfg_valor=None) -> list:
    """La lista de verbos vigente. Acepta el valor crudo de la config (lista
    JSON o texto separado por comas); vacio/invalido -> VERBOS_GATO."""
    crudo = cfg_valor
    if isinstance(crudo, str):
        crudo = [p for p in crudo.split(",")]
    if not isinstance(crudo, (list, tuple)):
        return list(VERBOS_GATO)
    limpios = [s for s in (_sanear_verbo(v) for v in crudo) if s]
    return limpios or list(VERBOS_GATO)


def config() -> tuple:
    """(info_activa, verbos) a CALL-TIME.

    COGNIA_SPINNER_INFO manda ('0' apaga la linea viva, '1' la fuerza); sin la
    env decide la config persistida del CLI (claves 'spinner_info' y
    'spinner_verbos', se cambian con /spinner). Se mira sys.modules y NO se
    importa cli: en el REPL ya esta cargado, y un renderer suelto (tests,
    scripts) no paga las 15k lineas de cli.py por un default."""
    activo, verbos = True, list(VERBOS_GATO)
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            cfg = _cli._load_config()
            activo = (str(cfg.get("spinner_info", "on")).strip().lower()
                      not in ("off", "0", "false", "no"))
            verbos = verbos_config(cfg.get("spinner_verbos", ""))
    except Exception:
        activo, verbos = True, list(VERBOS_GATO)
    v = (os.environ.get("COGNIA_SPINNER_INFO") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        activo = False
    elif v in ("1", "true", "si", "on"):
        activo = True
    return activo, verbos


def activo() -> bool:
    return config()[0]


def verbo_rotante(t0: float, ahora: float, verbos: list | None = None,
                  periodo: int = PERIODO_ROTACION) -> str:
    """El verbo del momento: rota cada `periodo` segundos. El offset por int(t0)
    hace que cada turno arranque en un verbo distinto sin dejar de ser
    determinista (mismos t0/ahora -> mismo verbo, testeable)."""
    verbos = verbos or VERBOS_GATO
    if not verbos:
        return "Trabajando"
    transcurrido = max(0.0, float(ahora) - float(t0))
    idx = (int(t0) + int(transcurrido // max(1, periodo))) % len(verbos)
    return verbos[idx]


def componer_linea(verbo: str, segundos: int, tokens: int = 0,
                   hint: str = HINT_CORTE, ancho: int = 100,
                   sep: str = SEPARADOR, tok: str = PALABRA_TOK,
                   aprox: bool = True) -> str:
    """UNA linea: 'Maullando ideas… (12s · ~340 tok · ctrl+c corta)'.

    `hint`, `sep` y `tok` son los textos editables del elemento spinner.*
    (aspecto: texto.hint, separador, texto.tok); los defaults son los
    literales de siempre. Truncado elegante para anchos estrechos, por
    prioridad de las tres preguntas (¿vivo? ¿cuanto? ¿como paro?): primero
    caen los ~tokens (el bonus), despues el hint, y al final se recorta el
    verbo con '…'. Los segundos no caen nunca: son el latido. JAMAS devuelve
    '\\n' ni una linea mas larga que `ancho` (anti-jitter: una linea que
    envuelve salta de altura y ensucia el scrollback)."""
    verbo = (verbo or "Trabajando").rstrip(".").rstrip("…").strip()
    segundos = max(0, int(segundos))
    sep = SEPARADOR if sep is None else str(sep)
    tok = PALABRA_TOK if tok is None else str(tok).strip()
    candidatas = []
    partes = [f"{segundos}s"]
    if tokens > 0:
        # '~' solo cuando la cifra es la estimacion chars/4; con tokens
        # contados de verdad (TokensVivos.tokens) se dice el numero pelado.
        partes.append(f"{'~' if aprox else ''}{tokens} {tok}".rstrip())
    if hint:
        partes.append(hint)
    candidatas.append(partes)                       # completa
    # Orden de caida (2026-09-02, pedido del dueno: "los tokens en vivo"):
    # primero cae la PISTA (ctrl+c corta), que es comodidad; el contador de
    # tokens es la informacion y se queda hasta el final. Antes era al reves
    # y en una consola de 80 columnas el numero parpadeaba (aparecia y
    # desaparecia segun el largo del verbo gato).
    if tokens > 0 and hint:
        candidatas.append([f"{segundos}s", partes[1]])
    if hint or tokens > 0:
        candidatas.append([f"{segundos}s"])         # solo el latido
    for p in candidatas:
        linea = f"{verbo}… ({sep.join(p)})"
        if len(linea) <= ancho:
            return linea
    # ni con solo los segundos entra: recortar el verbo, conservar '(Ns)'
    cola = f"… ({segundos}s)"
    sitio = ancho - len(cola)
    if sitio >= 2:
        return verbo[:sitio - 1] + "…" + cola[1:] if len(verbo) > sitio \
            else verbo[:sitio] + cola
    # ancho absurdo (< ~8): devolver lo que quepa, sin romper linea
    return (f"{verbo}{cola}")[:max(1, ancho)]


def sufijo_diagnostico(tokens: int, segundos: float, fase: str | None,
                       sep: str) -> str:
    """`· 47 tok/s · razonando` — la mitad diagnostica de la linea viva.

    POR QUE (2026-09-01). La linea decia cuantos tokens llevaba y cuanto tiempo,
    que no distingue los dos fallos que de verdad se sufren en una tarea larga:
    el modelo generando despacio y el modelo generando rapido PERO en el canal
    de razonamiento sin llegar a llamar a nada. Con la velocidad y la fase se
    ven separados y en el acto.

    Silencio hasta tener con que: por debajo de dos segundos o de unos pocos
    tokens la division da numeros ridiculos (1200 tok/s en el primer frame) y un
    numero que salta no informa, distrae.
    """
    if tokens < 40 or segundos < 2.0:
        return ""
    tps = tokens / max(0.001, segundos)
    # `sep` ya trae sus espacios (' · '): anadir mas produce '  |  28 tok/s'
    # cuando el registro lo cambia a ' | '. Lo cazo el test de overrides.
    out = "%s%d tok/s" % (sep, int(round(tps)))
    if fase:
        out += "%s%s" % (sep, str(fase)[:14])
    return out


def linea_estado(base: str | None, t0: float, ahora: float, chars: int,
                 ancho: int = 100, id: str | None = None,
                 fase: str | None = None, tokens: int | None = None) -> str:
    """La linea viva completa para el ticker del renderer. `base` es la
    etiqueta de la tool en curso ('Leyendo motor.py…' — mas honesta que un
    verbo generico); None = fase de pensar, verbo gato rotatorio. Con `id`
    (spinner.tool / spinner.pensar) el hint, el separador y 'tok' salen del
    registro de aspecto; sin id, los literales de hoy."""
    _, verbos = config()
    if base:
        verbo = base
    else:
        verbo = verbo_rotante(t0, ahora, verbos)
    asp = aspecto_spinner(id) if id else ASPECTO_DEFECTO
    _seg = max(0.0, ahora - t0)
    # `tokens` (contados por el productor, uno por delta SSE) manda sobre la
    # estimacion por chars: es el numero real y se pinta sin '~'.
    _aprox = not (tokens is not None and int(tokens) > 0)
    _toks = estimar_tokens(chars) if _aprox else int(tokens)
    _suf = sufijo_diagnostico(_toks, _seg, fase, asp.sep)
    # El ancho se le resta ANTES a componer_linea: si el sufijo se pegara
    # despues sin descontarlo, la linea envolveria y el salto de altura ensucia
    # el scrollback (que es justo lo que el recorte de componer_linea evita).
    return componer_linea(verbo, int(_seg),
                          tokens=_toks, hint=asp.hint,
                          ancho=max(12, ancho - len(_suf)),
                          sep=asp.sep, tok=asp.tok, aprox=_aprox) + _suf


# ---------------------------------------------------------------------------
# Aspecto por elemento (P8): lo que el registro decide del spinner
# ---------------------------------------------------------------------------

IDS_SPINNER = ("spinner.tool", "spinner.pensar", "spinner.comando")


@dataclass(frozen=True)
class AspectoSpinner:
    """Lo que el renderer necesita de un elemento spinner.*, ya decidido.
    Los defaults son los literales de hoy (byte-identico sin fichero)."""
    id: str = "spinner.tool"
    marca: str = "·"                # glifo delante del texto (renderer._MARCA_ACTIVIDAD)
    spinner_rich: str = "dots"      # nombre en rich.spinner.SPINNERS
    hint: str = HINT_CORTE
    tok: str = PALABRA_TOK
    sep: str = SEPARADOR
    pensando: str = "pensando…"     # etiqueta clasica de la fase de pensar
    animar: bool = False            # animacion.activa del elemento Y capacidades().animar
    fps: int = 12                   # refresh_per_second del status cuando anima


ASPECTO_DEFECTO = AspectoSpinner()

_AVISOS_STDERR: set = set()


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE por _aviso_degradado('spinner', motivo) del CLI
    (de-duplica por turno); sin cli cargado (tests, scripts) una vez por
    motivo a stderr. Jamas en silencio (regla del repo)."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            _cli._aviso_degradado("spinner", motivo)
            return
    except Exception:
        pass
    if motivo in _AVISOS_STDERR:
        return
    _AVISOS_STDERR.add(motivo)
    try:
        print(f"  degradado — spinner: {motivo}", file=sys.stderr)
    except Exception:
        pass


def _nombre_spinner(nombre: str, id: str) -> str:
    """Un nombre de rich.spinner.SPINNERS o 'dots' con aviso: un nombre malo
    haria reventar console.status y el renderer caeria a la linea quieta en
    silencio."""
    nombre = (nombre or "").strip()
    try:
        from rich.spinner import SPINNERS
    except Exception:
        return nombre or "dots"
    if nombre in SPINNERS:
        return nombre
    _avisar(f"{id}: '{nombre}' no es un spinner de rich (hay {len(SPINNERS)}: "
            f"dots, line, arc, ...); se usa 'dots'")
    return "dots"


def aspecto_spinner(id: str = "spinner.tool") -> AspectoSpinner:
    """Marca, spinner de rich, textos y permiso de animar de un elemento
    spinner.* a CALL-TIME (el registro puede cambiar por /estilo o por hot
    reload entre dos statuses). Conecta el motor (aspecto.conectar_glow, idem-
    potente) para que LineaViva resuelva el id. Ante cualquier fallo del
    registro: aviso por _aviso_degradado y los defaults de hoy."""
    id = id or "spinner.tool"
    if id not in IDS_SPINNER:
        _avisar(f"'{id}' no es un elemento spinner.* ({', '.join(IDS_SPINNER)}); "
                "se usa spinner.tool")
        id = "spinner.tool"
    try:
        from . import aspecto as A
        A.conectar_glow()
        est = A.estilo_de(id)
        textos = A.textos(id)
        d = ASPECTO_DEFECTO
        if id == "spinner.comando":
            # aqui el 'glifo' ES el spinner de rich (nota del registro)
            nombre = A.glifo(id) or textos.get("spinner_rich", d.spinner_rich)
            marca = d.marca
        else:
            nombre = textos.get("spinner_rich", d.spinner_rich)
            marca = A.glifo(id) or d.marca
        anim = est.animacion
        animar = False
        if anim is not None and anim.activa:
            from . import glow
            animar = bool(glow.capacidades().animar)
        return AspectoSpinner(
            id=id, marca=marca, spinner_rich=_nombre_spinner(nombre, id),
            hint=str(textos.get("hint", d.hint)), tok=str(textos.get("tok", d.tok)),
            sep=A.separador(id) if A.Cap.SEPARADOR in A.elemento(id).caps else d.sep,
            pensando=str(textos.get("pensando", d.pensando)), animar=animar,
            fps=_fps())
    except Exception as exc:
        _avisar(f"aspecto de {id} ilegible ({type(exc).__name__}: {exc}); "
                "spinner por defecto")
        return AspectoSpinner(id=id)


def _fps() -> int:
    try:
        from . import glow
        return int(glow.FPS)
    except Exception:
        return ASPECTO_DEFECTO.fps


def estilo_spinner(id: str):
    """El glow.EstiloGlow con el que LineaViva anima el elemento. Es
    aspecto.estilo_glow(id) con una correccion NECESARIA para el barrido: sin
    override de color, estilo_glow entrega color '' (para que el frame
    estatico sea el token del Theme, byte-identico), pero un barrido sin
    color base no tiene nada que mezclar y sale como bold/dim sin color (lo
    delato la captura: 0 escapes '38;2;'). Aqui, SOLO cuando hay animacion o
    glow, el color base pasa a ser el resuelto del token (#4fd010 en
    oscuro). None si el registro/motor no estan (ya avisado)."""
    try:
        import dataclasses
        from . import aspecto as A
        A.conectar_glow()
        e = A.estilo_glow(id)
        if (e.anim_activa or e.glow_intensidad > 0) and not e.color:
            r = A.estilo_resuelto(id)
            if r.color:
                e = dataclasses.replace(e, color=A.color_rich(r.color))
        return e
    except Exception as exc:
        _avisar(f"estilo de {id} irresoluble ({type(exc).__name__}: {exc}); "
                "spinner sin animar")
        return None


def comando(clave: str = "procesando") -> tuple:
    """(markup, nombre_del_spinner) para los console.status de cli.py que
    dicen 'Procesando...' / 'Mejorando el prompt...' (elemento
    spinner.comando; claves 'procesando' y 'mejorando'). Default byte-identico:
    ('[spinner]Procesando...[/spinner]', 'dots'). Gancho en cli.py:
        markup, nombre = spinner_vivo.comando('procesando')
        with _console.status(markup, spinner=nombre): ..."""
    defaults = {"procesando": "Procesando...", "mejorando": "Mejorando el prompt..."}
    texto = defaults.get(clave, clave)
    nombre = "dots"
    try:
        from . import aspecto as A
        texto = A.texto("spinner.comando", clave)
        nombre = _nombre_spinner(A.glifo("spinner.comando"), "spinner.comando")
    except Exception as exc:
        _avisar(f"spinner.comando ilegible ({type(exc).__name__}: {exc}); texto por defecto")
    return f"[spinner]{texto}[/spinner]", nombre
