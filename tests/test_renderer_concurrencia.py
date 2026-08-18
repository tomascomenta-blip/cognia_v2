"""
Concurrencia del Renderer (tanda UI 2026-08-17).

POR QUE EXISTE: emitir() copia la lista de suscriptores bajo su lock y reparte
FUERA de el, en el HILO DEL EMISOR (cognia/ux/events.py:250-256). El motor de
workflows corre paralelo(cap=2): DOS hilos entran a Renderer.__call__ a la vez
y hasta esta tanda el renderer no tenia ni un lock sobre _status/_flujo/la
Console. El invariante que se protege no es "una escritura atomica" sino "un
handler es una unidad indivisible".

Los dos primeros tests FALLAN sin NINGUN lock en __call__ (cualquier lock los
pasa, RLock o pelado — medido 2026-08-17):
- sin lock, las 3 lineas de un ToolFin se intercalan con las de otro y el
  de-dup del remoto (es_eco_renderer) empieza a ver lineas partidas,
- sin lock, dos _arrancar_status entrelazados dejan un spinner HUERFANO
  girando encima de la respuesta — el fallo que el guard de __call__ intentaba
  tapar.

Lo que exige que sea RLock y no Lock es OTRA cosa, y tiene su propio test
(test_un_handler_que_reemite_al_bus_no_se_deadlockea): emitir() reparte en el
hilo del emisor, asi que algo que re-emita DENTRO de un handler (una consola
que ecoa al bus, un suscriptor que republica) reentra por __call__ en el MISMO
hilo. NO es por _parar_status(): ese metodo no toma el lock.

Los ultimos fijan el contrato de los handlers del motor de workflows: NO
arrancan spinner (con cap=2 el _status unico no alcanza), sus lineas empiezan
por una marca que es_eco_renderer reconoce, y cierran el flujo de prosa antes
de imprimir (si no, la linea del agente se pega dentro de una frase a medias
en cuanto el motor streamea).
"""
import threading

from cognia.remoto.sesiones import es_eco_renderer
from cognia.ux import events
from cognia.ux.renderer import Renderer


# ---------------------------------------------------------------------------
# Dobles: consola que graba (hilo, texto) y BLOQUEA al hilo 'A' en su primera
# operacion. Ese bloqueo ES la ventana por la que 'B' se cuela cuando el
# despacho no esta serializado; con el lock, 'B' no puede entrar y 'A' agota
# su espera (1 s) pintando sus lineas seguidas.
# ---------------------------------------------------------------------------

class _StatusFalso:
    def __init__(self, texto, spinner=None):
        self.texto = texto
        self.spinner = spinner
        self.arrancado = False
        self.parado = False

    def start(self):
        self.arrancado = True

    def stop(self):
        self.parado = True

    def update(self, texto):
        pass


class _ConsolaBloqueante:
    def __init__(self, bloquear_en: str = "print", espera: float = 1.0):
        self.impresos = []          # [(nombre_hilo, texto)]
        self.statuses = []
        self._bloquear_en = bloquear_en
        self._espera = espera
        self.a_dentro = threading.Event()   # 'A' entro y esta bloqueado
        self._soltar = threading.Event()    # nadie la setea: 'A' agota el wait
        self._ya_bloqueo = False

    def _quiza_bloquear(self, donde: str) -> None:
        if donde != self._bloquear_en or self._ya_bloqueo:
            return
        if threading.current_thread().name != "A":
            return
        self._ya_bloqueo = True
        self.a_dentro.set()
        self._soltar.wait(timeout=self._espera)

    def print(self, *args, **kwargs):
        self.impresos.append((threading.current_thread().name,
                              str(args[0]) if args else ""))
        self._quiza_bloquear("print")

    def status(self, texto, spinner=None):
        # el bloqueo va ANTES de crear el status: es el instante en que 'A'
        # todavia no asigno self._status y el _parar_status de 'B' no ve nada
        # que parar
        self._quiza_bloquear("status")
        st = _StatusFalso(texto, spinner)
        self.statuses.append(st)
        return st


def _dos_hilos(r: Renderer, ev_a, ev_b, con: _ConsolaBloqueante) -> None:
    a = threading.Thread(target=r, args=(ev_a,), name="A")
    b = threading.Thread(target=r, args=(ev_b,), name="B")
    a.start()
    assert con.a_dentro.wait(timeout=5), "el hilo A nunca entro al handler"
    b.start()
    a.join(timeout=10)
    b.join(timeout=10)
    assert not a.is_alive() and not b.is_alive(), "un hilo quedo colgado"


# ---------------------------------------------------------------------------
# 1) un handler es una unidad indivisible
# ---------------------------------------------------------------------------

def test_dos_hilos_no_entrelazan_las_lineas_de_un_handler():
    """FALLA SIN EL LOCK: _on_tool_fin emite UNA linea logica + su resumen
    sangrado (3 prints). Con 'A' bloqueado tras el primero, 'B' pinta sus 3
    lineas en medio y la secuencia queda A,B,B,B,A,A."""
    con = _ConsolaBloqueante(bloquear_en="print")
    r = Renderer(console=con)

    def _ev(tag):
        return events.ToolFin(tool="leer_archivo", args=f"{tag}.py", ok=True,
                              resumen=f"{tag} uno\n{tag} dos\n{tag} tres",
                              paso=1)

    _dos_hilos(r, _ev("a"), _ev("b"), con)
    nombres = [h for h, _ in con.impresos]
    assert len(nombres) == 6, con.impresos
    bloques = [n for i, n in enumerate(nombres) if i == 0 or nombres[i - 1] != n]
    assert len(bloques) == len(set(bloques)), (
        f"las lineas de los dos hilos se intercalaron: {con.impresos}")


def test_no_quedan_dos_status_a_la_vez(monkeypatch):
    """FALLA SIN EL LOCK: _arrancar_status hace _parar_status()+start(). Con
    'A' bloqueado dentro de console.status(), 'B' no ve nada que parar, arranca
    el suyo y el de 'A' queda HUERFANO girando sobre la respuesta."""
    monkeypatch.setenv("COGNIA_SPINNER", "1")   # forzar el modo interactivo
    con = _ConsolaBloqueante(bloquear_en="status")
    r = Renderer(console=con)
    _dos_hilos(r,
               events.ToolInicio(tool="leer_archivo", args="a.py", paso=1),
               events.ToolInicio(tool="leer_archivo", args="b.py", paso=2),
               con)
    vivos = [st for st in con.statuses if st.arrancado and not st.parado]
    assert len(vivos) <= 1, (
        f"{len(vivos)} spinners a la vez: uno quedo huerfano")


def test_un_handler_que_revienta_no_deja_el_lock_tomado(monkeypatch):
    """El `with` suelta el lock aunque el handler lance, y el guard corre el
    _parar_status de rescate. (Este test NO dice nada del tipo de lock: el
    guard no reentra — _parar_status no toma self._lock.)"""
    con = _ConsolaBloqueante()
    r = Renderer(console=con)

    def _roto(self, ev):
        raise RuntimeError("boom")

    monkeypatch.setitem(Renderer._HANDLERS, "Aviso", _roto)
    r(events.Aviso(texto="x", origen="test"))
    r(events.ToolFin(tool="leer_archivo", args="a.py", ok=True,
                     resumen="42 lineas", paso=1))
    assert any("42 lineas" in t for _, t in con.impresos), con.impresos


class _ConsolaQueReemite:
    """Consola-sink que ECOA al bus: pintar emite un Aviso. Es la reentrancia
    de verdad — emitir() reparte en el hilo del emisor, asi que el Aviso
    vuelve a entrar por Renderer.__call__ sin haber salido del primero."""

    def __init__(self):
        self.impresos = []
        self._dentro = False

    def print(self, *args, **kwargs):
        self.impresos.append(str(args[0]) if args else "")
        if self._dentro:
            return                      # solo un nivel: no queremos recursion
        self._dentro = True
        try:
            events.emitir(events.Aviso(texto="eco del sink", origen="test"))
        finally:
            self._dentro = False


def test_un_handler_que_reemite_al_bus_no_se_deadlockea():
    """LA razon de que el lock sea RLock. Con un threading.Lock PELADO esto se
    cuelga para siempre en la segunda adquisicion (medido: el hilo nunca vuelve
    y 'eco del sink' no se imprime). Se corre en un hilo aparte justo para que
    el deadlock salga como FALLO y no cuelgue la suite."""
    con = _ConsolaQueReemite()
    r = Renderer(console=con)
    events.suscribir(r)
    hecho = threading.Event()

    def _emisor():
        events.emitir(events.ToolFin(tool="leer_archivo", args="a.py", ok=True,
                                     resumen="42 lineas", paso=1))
        hecho.set()

    try:
        t = threading.Thread(target=_emisor, name="emisor", daemon=True)
        t.start()
        assert hecho.wait(timeout=5), (
            "deadlock: el evento re-emitido reentro en __call__ y el lock no "
            "es reentrante")
    finally:
        events.desuscribir(r)
    assert any("42 lineas" in t for t in con.impresos), con.impresos
    assert any("eco del sink" in t for t in con.impresos), con.impresos


# ---------------------------------------------------------------------------
# 2) los handlers del motor de workflows
# ---------------------------------------------------------------------------

def _eventos_wf() -> list:
    ident = dict(run_id="r1", agente_id="r1#pasos.2", indice=2, total=6,
                 fase="pasos", etiqueta="resume TLS")
    return [
        events.WorkflowInicio(run_id="r1", nombre="repl", total_agentes=6,
                              presupuesto_tokens=60000, cache_precargada=2),
        events.AgenteInicio(rol="", clave="ab12", **ident),
        events.AgenteFin(ok=True, tokens=812, intentos=1, duracion_s=4.1,
                         resumen="3 parrafos", **ident),
        events.AgenteFin(ok=True, cache_hit=True, resumen="ya estaba",
                         **ident),
        events.AgenteFin(ok=False,
                         motivo="presupuesto de 60000 tokens agotado", **ident),
        events.WorkflowFin(run_id="r1", nombre="repl", ok=True, agentes=6,
                           fallidos=1, cache_hits=2, tokens=4210,
                           presupuesto_tokens=60000, duracion_s=31.2),
        events.WorkflowFin(run_id="r1", nombre="repl", ok=False,
                           resumen="el workflow fallo: boom"),
    ]


def test_los_eventos_de_agente_no_arrancan_spinner(monkeypatch):
    """Con paralelo(cap=2) hay dos agentes vivos y _arrancar_status mantiene
    UN solo _status: el segundo mataria el spinner del primero. Linea quieta."""
    monkeypatch.setenv("COGNIA_SPINNER", "1")
    con = _ConsolaBloqueante()
    r = Renderer(console=con)
    for ev in _eventos_wf():
        r(ev)
    assert con.statuses == []


def test_las_lineas_de_agente_empiezan_por_marca(capsys):
    """Contrato con el de-dup del remoto: sin la marca inicial el movil pinta
    cada agente DOS veces (una por el evento, otra por esta linea como prosa)."""
    r = Renderer(console=None)
    eventos = _eventos_wf()
    for ev in eventos:
        r(ev)
    lineas = [l for l in capsys.readouterr().out.split("\n") if l.strip()]
    assert len(lineas) == len(eventos), lineas
    for l in lineas:
        assert l.strip()[:1] in ("⏺", "·", "✗"), l
        assert es_eco_renderer(l), l


def _lineas_no_vacias(capsys) -> list:
    return [l for l in capsys.readouterr().out.split("\n") if l.strip()]


def _prosa_a_medias(r: Renderer) -> None:
    """Deja el flujo de prosa ABIERTO con una frase sin terminar (parte
    emitida, parte todavia en el buffer de FlujoSuave)."""
    for tok in ("La respuesta ", "va por la mitad ", "de una frase "):
        r(events.TokenTexto(texto=tok))
    assert r._flujo is not None


def test_agente_inicio_no_se_pega_a_la_prosa(capsys):
    """FALLA SIN EL FIX: _on_agente_inicio era uno de los dos unicos handlers
    que imprimian sin _cerrar_flujo() antes. Salida vieja, medida:
    '  La respuesta va por la mitad   · agente 2/6 resume TLS…' (y el resto de
    la frase todavia en el buffer). Hoy no muerde porque completar() no
    streamea, pero el motor esta pasando a stream."""
    ident = dict(run_id="r1", agente_id="r1#pasos.2", indice=2, total=6,
                 fase="pasos", etiqueta="resume TLS")
    r = Renderer(console=None)
    _prosa_a_medias(r)
    r(events.AgenteInicio(rol="", clave="ab12", **ident))
    lineas = _lineas_no_vacias(capsys)
    assert any(l.strip() == "· agente 2/6 resume TLS…" for l in lineas), lineas
    prosa = [l for l in lineas if "La respuesta" in l]
    assert len(prosa) == 1, lineas
    assert "agente" not in prosa[0], prosa[0]
    # y el buffer se vacio: la frase no se pierde a medias
    assert "de una frase" in prosa[0], prosa[0]


def test_agente_fin_no_se_pega_a_la_prosa(capsys):
    """El gemelo de arriba para _on_agente_fin (mismo bug, misma salida
    pegada: '…de una frase   ⏺ agente 2/6 resume TLS — 3 parrafos')."""
    ident = dict(run_id="r1", agente_id="r1#pasos.2", indice=2, total=6,
                 fase="pasos", etiqueta="resume TLS")
    r = Renderer(console=None)
    _prosa_a_medias(r)
    r(events.AgenteFin(ok=True, tokens=812, intentos=1, duracion_s=4.1,
                       resumen="3 parrafos", **ident))
    lineas = _lineas_no_vacias(capsys)
    assert any(l.strip() == "⏺ agente 2/6 resume TLS — 3 parrafos "
               "(4.1s · 812 tok)" for l in lineas), lineas
    prosa = [l for l in lineas if "La respuesta" in l]
    assert len(prosa) == 1, lineas
    assert "agente" not in prosa[0], prosa[0]
    assert "de una frase" in prosa[0], prosa[0]


def test_los_eventos_de_agente_cierran_el_flujo_pensar(capsys, monkeypatch):
    """La otra mitad del mismo cierre: con COGNIA_PENSAR=ver la prosa ∴ queda
    abierta y la linea del agente se pegaria dentro de ella."""
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    ident = dict(run_id="r1", agente_id="r1#pasos.2", indice=2, total=6,
                 fase="pasos", etiqueta="resume TLS")
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=20, fragmento="pienso a medias"))
    assert r._flujo_pensar is not None
    r(events.AgenteFin(ok=False, motivo="timeout", **ident))
    assert r._flujo_pensar is None
    lineas = _lineas_no_vacias(capsys)
    pensado = [l for l in lineas if "pienso a medias" in l]
    assert len(pensado) == 1, lineas
    assert "agente" not in pensado[0], pensado[0]
    assert any(l.strip() == "✗ agente 2/6 resume TLS — fallo: timeout"
               for l in lineas), lineas


def test_las_lineas_de_agente_dicen_lo_que_paso(capsys):
    r = Renderer(console=None)
    for ev in _eventos_wf():
        r(ev)
    out = capsys.readouterr().out
    assert "· workflow «repl» — 6 agentes · 2 de cache" in out
    assert "· agente 2/6 resume TLS…" in out
    assert "⏺ agente 2/6 resume TLS — 3 parrafos (4.1s · 812 tok)" in out
    assert "⏺ agente 2/6 resume TLS — de cache" in out
    assert ("✗ agente 2/6 resume TLS — fallo: presupuesto de 60000 tokens "
            "agotado") in out
    assert "⏺ workflow «repl» — 5 de 6 · 4210 tokens · 31.2s" in out
    assert "✗ workflow «repl» — fallo: el workflow fallo: boom" in out
