"""
tests/test_clases_jornada.py
============================
El ORQUESTADOR de la jornada de clases: los cuatro controles que el widget
necesita (pausar, mutear, el lock de proceso y el estado) y el bug que hacia
parpadear el cuaderno.

TRES DECISIONES DE MONTAJE:

  - `COGNIA_CLASES_DIR` a tmp_path en un fixture autouse. Sin eso, estos tests
    escribirian -- y borrarian el lock -- del cuaderno REAL del duenio.
  - La captura NO se puede usar: abre el loopback WASAPI de la maquina. Se
    inyecta `GrabadorFalso` por el parametro `grabador=` de JornadaViva, y la
    parte de captura que si se prueba de verdad (`Grabador._trozo_listo`) es la
    unica que no toca el dispositivo.
  - El lock se prueba contra PROCESOS REALES (un hijo `sys.executable` vivo y
    otro ya terminado) y no contra un PID inventado: lo que hay que comprobar
    es justo que "vivo" y "muerto" se distinguen en esta maquina.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from cognia.clases import almacen as alm
from cognia.clases import captura as cap
from cognia.clases import cuaderno as cua
from cognia.clases import jornada as jor

JORNADA = "2026-08-31"


@pytest.fixture(autouse=True)
def cuaderno_aislado(tmp_path, monkeypatch):
    """Cuaderno y lock en tmp_path, y sin jornada viva heredada de otro test."""
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path / "clases"))
    monkeypatch.setattr(jor, "_VIVA", None)
    yield
    # Antes de que monkeypatch deshaga la env var: si un test dejo lock, se
    # borra AQUI, donde ruta_lock() todavia apunta a tmp_path.
    try:
        os.unlink(str(jor.ruta_lock()))
    except OSError:
        pass


class GrabadorFalso:
    """El contrato minimo de captura.Grabador que usa JornadaViva.

    No es un mock de conveniencia: es el unico modo de probar el orquestador
    sin abrir el audio del equipo. Todo lo que de verdad hace la captura
    (descartar el trozo, el reloj, el WAV) se prueba aparte contra el Grabador
    de verdad en `test_mudo_*`.
    """

    def __init__(self, nombre: str = JORNADA):
        self.jornada = nombre
        self.cola: "queue.Queue" = queue.Queue()
        self.avisos: list = []
        self.mudo = False
        self.descartados = 0
        self._t = 0.0
        self.arrancado = False

    def arrancar(self) -> tuple:
        self.arrancado = True
        return True, "grabador falso"

    def parar(self, timeout: float = 10.0) -> None:
        self.arrancado = False

    @property
    def viva(self) -> bool:
        return self.arrancado


def _proceso_vivo():
    """Un proceso REAL que sigue corriendo (se mata en el finally del test)."""
    return subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(60)"])


def _pid_muerto() -> int:
    """El PID de un proceso que YA termino. Se arranca y se espera de verdad:
    inventar un PID alto no probaria nada porque podria estar en uso."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=60)
    return p.pid


def _escribir_lock(pid: int, nombre: str = "otra jornada",
                   epoch: float = 0.0) -> None:
    jor.ruta_lock().write_text(
        json.dumps({"pid": pid, "jornada": nombre,
                    "epoch": epoch or time.time()}),
        encoding="utf-8")


# Tope de colisiones PermissionError del lector, en tanto por uno de sus
# intentos. MEDIDO el 2026-08-31 en la maquina del duenio: 4 de 569 = 0,7%.
# El 10% deja diez veces ese margen y sigue cazando una regresion que rompa la
# lectura de verdad. SIN esta cota los dos tests de atomicidad pasaban igual
# con un lector que fallara el 90% de las veces: acumulaban las colisiones en
# una lista que nadie miraba, y un lector que casi nunca consigue leer no
# demuestra que la escritura sea atomica.
TOPE_COLISIONES = 0.10


def _cota_colisiones(vistas: list, colisiones: list) -> None:
    intentos = len(vistas) + len(colisiones)
    assert intentos, "el lector no llego a intentar nada"
    assert len(colisiones) <= TOPE_COLISIONES * intentos, (
        "el lector fallo %d de %d intentos (%.1f%%): con tantos fallos, que "
        "las lecturas buenas salgan bien no demuestra nada"
        % (len(colisiones), intentos, 100.0 * len(colisiones) / intentos))


# ── 1. Cortes atomicos ───────────────────────────────────────────────────────

def test_reescribir_jsonl_nunca_se_ve_vacio_ni_a_medias(tmp_path):
    """El bug: `detectar` borraba cortes.jsonl y lo reapendaba linea a linea,
    dejando una ventana sin fichero cada 90 s. Quien leyera ahi (el cuaderno
    vivo) veia CERO cortes, que `sesiones_de` traduce a una jornada entera
    'Sin clasificar': el cuaderno parpadeaba de 'Fisica' a 'Sin clasificar'.

    Un lector en bucle mientras se reescribe 60 veces: nunca puede ver un
    numero de cortes distinto del que hay.

    MEDIDO el 2026-08-31 con este mismo montaje (60 reescrituras, lector cada
    1 ms) en la maquina del duenio:
      - con el codigo viejo (unlink + apendar): el lector vio 2, 3, 5, 6, 8, 9,
        10, 11 y 12 cortes, y ademas reventaba con FileNotFoundError en la
        ventana sin fichero;
      - con tmp + os.replace: 565 lecturas, todas de 12, y 4 colisiones
        PermissionError (el replace en vuelo), que son ruidosas y no mudas.
    """
    ruta = tmp_path / alm.CORTES
    cortes = [{"t": i * 60.0, "materia": "Fisica", "confianza": 0.8,
               "por": "deriva"} for i in range(12)]
    jor._reescribir_jsonl(ruta, cortes)

    vistas: list = []
    colisiones: list = []
    parar = threading.Event()

    def lector():
        while not parar.is_set():
            try:
                vistas.append(len(alm.leer_jsonl(ruta)))
            except FileNotFoundError:
                vistas.append(0)        # el fichero no estaba: ESE es el bug
            except PermissionError:
                # Windows: mientras el os.replace esta EN VUELO, abrir el
                # destino da 'acceso denegado'. Se apunta aparte porque no es
                # lo que este test persigue: es un fallo RUIDOSO y raro (el
                # lector lo ve y puede reintentar), no el hueco mudo del bug.
                colisiones.append(1)
            time.sleep(0.001)

    h = threading.Thread(target=lector, daemon=True, name="lector-cortes")
    h.start()
    try:
        for _ in range(60):
            jor._reescribir_jsonl(ruta, cortes)
    finally:
        parar.set()
        h.join(timeout=10.0)

    assert len(vistas) >= 10, "el lector apenas miro: la prueba no probaria nada"
    assert set(vistas) == {12}, "se vio el fichero a medias: %s" % sorted(set(vistas))
    _cota_colisiones(vistas, colisiones)


def test_detectar_no_deja_ventana_sin_cortes(monkeypatch):
    """Lo mismo, pero por el camino real: JornadaViva.detectar reescribiendo
    mientras alguien lee el cuaderno."""
    from cognia.clases import materias as mat

    d = alm.dir_jornada(JORNADA)
    for i in range(4):
        alm.apendar(d / alm.ENTRADAS,
                    {"t": i * 10.0, "tipo": cua.TIPO_TRANSCRIPCION,
                     "texto": "la energia cinetica", "fuente": "sistema"})
    fijos = [{"t": 0.0, "materia": "Fisica", "confianza": 0.9, "por": "deriva"},
             {"t": 20.0, "materia": "Historia", "confianza": 0.7,
              "por": "deriva"}]
    # El detector real depende del modelo y del corpus; aqui se mide la
    # ESCRITURA, no la deteccion.
    monkeypatch.setattr(mat, "detectar", lambda *a, **k: [dict(c) for c in fijos])

    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    assert len(jv.detectar()) == 2

    vistas: list = []
    colisiones: list = []
    parar = threading.Event()

    def lector():
        while not parar.is_set():
            try:
                vistas.append(len(alm.leer_jsonl(d / alm.CORTES)))
            except FileNotFoundError:
                vistas.append(0)        # el fichero no estaba: ESE es el bug
            except PermissionError:
                colisiones.append(1)    # replace en vuelo; ver el test de arriba
            time.sleep(0.001)

    h = threading.Thread(target=lector, daemon=True, name="lector-detectar")
    h.start()
    try:
        for _ in range(10):
            jv.detectar()
    finally:
        parar.set()
        h.join(timeout=10.0)

    assert len(vistas) >= 10, "el lector apenas miro: la prueba no probaria nada"
    assert set(vistas) == {2}, "cortes a medias: %s" % sorted(set(vistas))
    assert jv.avisos == []
    _cota_colisiones(vistas, colisiones)


# ── 2. Pausar / reanudar ─────────────────────────────────────────────────────

def test_pausar_y_reanudar_escriben_el_estado_en_disco():
    """'pausada' ya lo respetaba olvido.ESTADOS_ABIERTOS y lo declaraba
    cuaderno.Jornada; lo que faltaba era quien lo escribiera."""
    g = GrabadorFalso()
    jv = jor.JornadaViva(JORNADA, grabador=g)
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="grabando"))

    assert jv.pausar()["cambio"] is True
    assert cua.cargar_jornada(JORNADA).estado == "pausada"
    assert g.mudo is True, "una pausa que sigue metiendo audio no es una pausa"
    assert jv.pausar()["cambio"] is False       # idempotente

    assert jv.reanudar()["cambio"] is True
    assert cua.cargar_jornada(JORNADA).estado == "grabando"
    assert g.mudo is False


def test_pausar_deja_marca_en_el_cuaderno():
    """Un hueco silencioso y una captura rota no pueden verse igual."""
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    jv.pausar()
    jv.reanudar()
    textos = [e.get("texto") for e in
              alm.leer_jsonl(alm.dir_jornada(JORNADA) / alm.ENTRADAS)]
    assert textos == ["jornada pausada", "jornada reanudada"]


def test_reanudar_no_desmutea_a_espaldas_del_duenio():
    g = GrabadorFalso()
    jv = jor.JornadaViva(JORNADA, grabador=g)
    jv.mutear()
    jv.pausar()
    jv.reanudar()
    assert jv.muteada is True
    assert g.mudo is True, "reanudar reabrio un micro que el duenio muteo"


# ── 3. Mutear ────────────────────────────────────────────────────────────────

def test_mudo_descarta_el_trozo_y_no_congela_el_reloj():
    """El mute descarta ANTES de encolar, no guarda WAV (o `transcribir`
    resucitaria lo callado) y NO para el reloj: si lo parara, todas las notas
    posteriores del duenio caerian en el mismo segundo del cuaderno."""
    np = pytest.importorskip("numpy")
    g = cap.Grabador(JORNADA)
    muestras = np.zeros(cap.TASA_DESTINO * 2, dtype=np.float32)   # 2 s

    trozo = g._trozo_listo(cap.FUENTE_SISTEMA, muestras, 0.0)
    assert trozo and g.cola.qsize() == 1
    assert g._t == pytest.approx(2.0)

    g.mudo = True
    assert g._trozo_listo(cap.FUENTE_SISTEMA, muestras, g._t) == {}
    assert g.cola.qsize() == 1, "el trozo mudo se encolo igual"
    assert g.descartados == 1
    assert g._t == pytest.approx(4.0), "el mute congelo el reloj de la jornada"

    wavs = list((alm.dir_jornada(JORNADA) / alm.DIR_AUDIO).glob("*.wav"))
    assert len(wavs) == 1, "el trozo mudo dejo WAV que 'transcribir' resucitaria"

    g.mudo = False
    assert g._trozo_listo(cap.FUENTE_SISTEMA, muestras, g._t)
    assert g.cola.qsize() == 2


def test_mutear_marca_el_cuaderno_y_no_para_la_grabacion():
    g = GrabadorFalso()
    jv = jor.JornadaViva(JORNADA, grabador=g)
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="grabando"))

    assert jv.mutear()["cambio"] is True
    assert g.mudo is True and jv.muteada is True
    assert cua.cargar_jornada(JORNADA).estado == "grabando", \
        "mutear no es pausar: la jornada sigue grabando"

    assert jv.desmutear()["cambio"] is True
    assert g.mudo is False

    entradas = alm.leer_jsonl(alm.dir_jornada(JORNADA) / alm.ENTRADAS)
    assert [e.get("tipo") for e in entradas] == [cua.TIPO_MARCA] * 2
    assert [e.get("texto") for e in entradas] == ["micro muteado",
                                                  "micro reanudado"]


# ── 4. Lock de proceso ───────────────────────────────────────────────────────

def test_lock_de_otro_proceso_vivo_impide_arrancar_y_dice_quien():
    """`_VIVA` es un singleton de MODULO: no ve al widget ni al REPL de al
    lado. Sin lock, los dos escribirian la misma carpeta."""
    hijo = _proceso_vivo()
    try:
        _escribir_lock(hijo.pid, "jornada del widget")
        jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
        ok, motivo = jv.arrancar()
        assert ok is False
        assert str(hijo.pid) in motivo, "el motivo no dice QUE proceso lo tiene"
        assert "jornada del widget" in motivo
        assert jv.grabador.arrancado is False, "abrio el audio pese al lock"
    finally:
        hijo.kill()
        hijo.wait(timeout=30)


def test_lock_rancio_se_roba_dejando_aviso_y_se_borra_al_parar():
    """El REPL anterior murio sin cerrar: el lock queda con un PID muerto. Se
    roba, pero se dice; 'no lo cerro nadie' y 'se lo he quitado a alguien' no
    pueden verse igual."""
    muerto = _pid_muerto()
    _escribir_lock(muerto, "la de ayer")

    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    ok, _motivo = jv.arrancar()
    assert ok is True
    assert any("rancio" in a and str(muerto) in a for a in jv.avisos), jv.avisos

    datos = json.loads(jor.ruta_lock().read_text(encoding="utf-8"))
    assert datos["pid"] == os.getpid()
    assert datos["jornada"] == JORNADA

    jv.parar()
    assert not jor.ruta_lock().exists(), "parar() dejo el lock puesto"


def test_arrancar_suelta_el_lock_si_la_captura_falla():
    """Si no hay audio no hay jornada, y un lock nuestro sin grabacion detras
    bloquearia el siguiente intento del propio duenio."""
    class GrabadorRoto(GrabadorFalso):
        def arrancar(self):
            return False, "este equipo no deja capturar la salida (loopback)"

    jv = jor.JornadaViva(JORNADA, grabador=GrabadorRoto())
    ok, motivo = jv.arrancar()
    assert ok is False and "loopback" in motivo
    assert not jor.ruta_lock().exists()


def test_soltar_lock_no_borra_el_de_otro_proceso():
    hijo = _proceso_vivo()
    try:
        _escribir_lock(hijo.pid)
        jor._soltar_lock()
        assert jor.ruta_lock().exists(), "borramos el lock de otro proceso"
    finally:
        hijo.kill()
        hijo.wait(timeout=30)


# ── 5. estado() enriquecido ──────────────────────────────────────────────────

def test_estado_da_lo_que_el_widget_necesita_para_pintar_el_menu(monkeypatch):
    g = GrabadorFalso()
    g._t = 125.0
    g.arrancado = True
    jv = jor.JornadaViva(JORNADA, grabador=g)
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="grabando",
                                    materia_actual="Fisica"))
    monkeypatch.setattr(jor, "_VIVA", jv)

    est = jor.estado()
    assert est["grabando"] is True
    assert est["jornada"] == JORNADA
    assert est["materia"] == "Fisica"
    assert est["segundos"] == pytest.approx(125.0)
    assert est["pausada"] is False and est["muteada"] is False
    assert est["otro_proceso"] is False
    # Lo que ya consumia el CLI sigue estando.
    for clave in ("trozos", "transcritos", "silencios", "avisos"):
        assert clave in est

    jv.mutear()
    jv.pausar()
    est = jor.estado()
    assert est["muteada"] is True and est["pausada"] is True
    assert est["estado"] == "pausada"


def test_estado_avisa_de_que_graba_otro_proceso():
    """Sin esto el widget se pintaria 'parado' mientras el REPL de al lado
    graba, y ofreceria un boton de grabar que solo puede fallar."""
    hijo = _proceso_vivo()
    try:
        _escribir_lock(hijo.pid, "jornada del REPL")
        est = jor.estado()
        assert est["grabando"] is False
        assert est["otro_proceso"] is True
        assert est["lock"]["pid"] == hijo.pid
        assert est["lock"]["jornada"] == "jornada del REPL"
    finally:
        hijo.kill()
        hijo.wait(timeout=30)


# ── 6. jornada.json: nadie pisa lo que escribio otro ─────────────────────────

def test_detectar_no_pisa_la_pausa_pulsada_mientras_corria(monkeypatch):
    """EL BUG GRAVE (lost update). `detectar` cargaba jornada.json al empezar
    y guardaba el objeto ENTERO al terminar. Si el duenio pulsaba Pausa en
    medio -- y el vigia abre ese hueco cada 90 s -- la copia rancia devolvia
    el estado a 'grabando' y la pausa se perdia, sin traza ninguna.

    Aqui la deteccion pausa la jornada DESDE DENTRO: es exactamente el mismo
    orden de eventos (leer, pausar, escribir) sin depender del reloj.
    """
    from cognia.clases import materias as mat

    d = alm.dir_jornada(JORNADA)
    for i in range(3):
        alm.apendar(d / alm.ENTRADAS,
                    {"t": i * 10.0, "tipo": cua.TIPO_TRANSCRIPCION,
                     "texto": "la energia cinetica", "fuente": "sistema"})
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="grabando"))
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())

    def detector_que_tarda(*a, **k):
        # El duenio pulsa Pausa MIENTRAS corre la deteccion.
        jv.pausar()
        return [{"t": 0.0, "materia": "Fisica", "confianza": 0.9,
                 "por": "deriva"}]

    monkeypatch.setattr(mat, "detectar", detector_que_tarda)
    jv.detectar()

    j = cua.cargar_jornada(JORNADA)
    assert j.estado == "pausada", \
        "la deteccion piso la pausa con su copia vieja de jornada.json"
    assert j.materia_actual == "Fisica", "y ademas perdio lo suyo"


def test_actualizar_jornada_no_baja_el_reloj_ni_toca_lo_que_no_es_suyo():
    """El contrato del escritor por campos: quien persiste el reloj no puede
    tocar el estado, y no puede hacerlo RETROCEDER.

    Lo segundo es lo que obliga a aceptar callables: la unica forma de decir
    'sube el reloj si el mio va por delante' sin traer de fuera una copia
    entera de la jornada -- y esa copia entera era exactamente el bug.
    """
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="pausada",
                                    segundos=120.0, materia_actual="Fisica"))
    jor._actualizar_jornada(JORNADA, segundos=lambda v: max(v, 30.0))

    j = cua.cargar_jornada(JORNADA)
    assert j.segundos == 120.0, "el reloj de la jornada retrocedio"
    assert j.estado == "pausada" and j.materia_actual == "Fisica", \
        "el escritor de 'segundos' piso campos que no son suyos"


def test_detectar_no_borra_el_corte_manual_apendado_mientras_corria(monkeypatch):
    """El docstring de `detectar` promete que el corte manual gana SIEMPRE, y
    lo perdia: leia los manuales al principio y reescribia el fichero entero
    al final, asi que un `/grabar-clase materia X` tecleado en medio
    desaparecia."""
    from cognia.clases import materias as mat

    d = alm.dir_jornada(JORNADA)
    for i in range(3):
        alm.apendar(d / alm.ENTRADAS,
                    {"t": i * 10.0, "tipo": cua.TIPO_TRANSCRIPCION,
                     "texto": "la energia cinetica", "fuente": "sistema"})
    g = GrabadorFalso()
    g._t = 300.0                        # el corte manual cae lejos del auto
    jv = jor.JornadaViva(JORNADA, grabador=g)

    def detector_que_tarda(*a, **k):
        # El duenio corrige la materia MIENTRAS corre la deteccion.
        jv.marcar_materia("Latin")
        return [{"t": 0.0, "materia": "Fisica", "confianza": 0.9,
                 "por": "deriva"}]

    monkeypatch.setattr(mat, "detectar", detector_que_tarda)
    jv.detectar()

    en_disco = alm.leer_jsonl(d / alm.CORTES)
    manuales = [c for c in en_disco if c.get("por") == "manual"]
    assert [c.get("materia") for c in manuales] == ["Latin"], \
        "la reescritura borro el corte manual: %s" % en_disco
    assert sorted(c.get("materia") for c in en_disco) == ["Fisica", "Latin"]


# ── 7. El lock no roba en silencio y siempre tiene salida ────────────────────

def test_lock_ilegible_se_toma_pero_diciendolo():
    """Un lock vacio o corrupto (alguien murio a mitad del write) dejaba
    `lock_actual()` en {} y pid=0: no entraba ni en la rama 'vivo' ni en la
    'rancio', se reescribia con ok=True y aviso="". Ni se negaba ni avisaba."""
    jor.ruta_lock().write_text("", encoding="utf-8")

    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    ok, _motivo = jv.arrancar()
    assert ok is True
    assert any("ilegible" in a for a in jv.avisos), \
        "se robo un lock ilegible sin decir nada: %s" % jv.avisos
    datos = json.loads(jor.ruta_lock().read_text(encoding="utf-8"))
    assert datos["pid"] == os.getpid()
    jv.parar()


def test_soltar_lock_no_borra_un_lock_ilegible_y_lo_dice():
    """`_soltar_lock` caia al unlink cuando el fichero no era un dict con PID:
    le quitaba el lock a OTRO proceso (el que lo estuviera escribiendo justo
    entonces) en silencio. El nuestro lo escribimos nosotros y siempre es
    legible, asi que uno ilegible no puede ser el nuestro."""
    jor.ruta_lock().write_text("{ esto no es json", encoding="utf-8")

    aviso = jor._soltar_lock()
    assert jor.ruta_lock().exists(), "borramos un lock que ni pudimos leer"
    assert "ilegible" in aviso, aviso
    assert "forzar_liberacion" in aviso, "no dice como quitarlo si toca"


def test_lock_viejisimo_de_un_pid_reciclado_se_trata_como_rancio():
    """Los PID se reciclan: un lock de anteayer cuyo numero hoy es de
    chrome.exe contesta VIVO y bloqueaba la grabacion para siempre."""
    hijo = _proceso_vivo()
    try:
        _escribir_lock(hijo.pid, "la de anteayer",
                       epoch=time.time() - jor.EDAD_LOCK_ABSURDA - 3600.0)
        jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
        ok, motivo = jv.arrancar()
        assert ok is True, \
            "un PID reciclado bloquea la grabacion sin salida: %s" % motivo
        assert any("reciclado" in a for a in jv.avisos), jv.avisos
        assert jor.lock_actual()["pid"] == os.getpid()
        jv.parar()
    finally:
        hijo.kill()
        hijo.wait(timeout=30)


def test_lock_ocupado_ofrece_la_salida_de_emergencia_y_forzar_la_abre():
    """El lock de un proceso vivo se respeta (eso no cambia), pero el mensaje
    tiene que decir COMO salir, y esa salida tiene que existir y funcionar."""
    hijo = _proceso_vivo()
    try:
        _escribir_lock(hijo.pid, "jornada fantasma")
        jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
        ok, motivo = jv.arrancar()
        assert ok is False
        assert "forzar_liberacion" in motivo, \
            "el mensaje no dice como desbloquearse: %s" % motivo

        res = jor.forzar_liberacion("ese PID ya no es Cognia")
        assert res["liberado"] is True
        assert res["lock"]["pid"] == hijo.pid
        assert "ese PID ya no es Cognia" in res["aviso"]
        assert not jor.ruta_lock().exists()

        jv2 = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
        ok2, _m2 = jv2.arrancar()
        assert ok2 is True, "forzar no desbloqueo de verdad"
        jv2.parar()
    finally:
        hijo.kill()
        hijo.wait(timeout=30)


def test_forzar_liberacion_sin_lock_lo_dice_en_vez_de_mentir():
    res = jor.forzar_liberacion()
    assert res["liberado"] is False and res["lock"] == {}
    assert "no habia" in res["aviso"]


@pytest.mark.skipif(os.name != "nt", reason="solo Windows pregunta a kernel32")
def test_kernel32_declara_el_handle_entero():
    """Sin argtypes/restype, ctypes asume que OpenProcess devuelve un c_int de
    32 bits CON signo: el HANDLE de 64 bits llega truncado y ese valor roto es
    el que va luego a GetExitCodeProcess y a CloseHandle (un 'muerto' falso, el
    robo de un lock vivo y una fuga de handles). No se puede comprobar por el
    resultado -- los handles de un proceso recien arrancado caben de sobra en
    32 bits -- asi que se comprueba la DECLARACION, que es lo que falta."""
    from ctypes import wintypes

    k32 = jor._kernel32()
    assert k32.OpenProcess.restype is wintypes.HANDLE
    assert k32.OpenProcess.argtypes == [wintypes.DWORD, wintypes.BOOL,
                                        wintypes.DWORD]
    assert k32.GetExitCodeProcess.argtypes[0] is wintypes.HANDLE
    assert k32.GetExitCodeProcess.restype is wintypes.BOOL
    assert k32.CloseHandle.argtypes == [wintypes.HANDLE]
    # Y que sigue contestando bien lo unico que importa.
    assert jor._pid_vivo(os.getpid()) is True


# ── 8. estado(): la misma forma en las tres ramas ────────────────────────────

def test_estado_devuelve_las_mismas_claves_en_las_tres_ramas(monkeypatch):
    """El widget lee este dict CADA segundo y en cualquiera de los tres
    estados. Faltaban 'descartados' fuera de la rama grabando, y 'estado' y
    'segundos' con el cuaderno vacio; ademas 'materias' era un 0 en una rama y
    una lista en otra."""
    vacio = jor.estado()
    assert vacio["grabando"] is False and vacio["jornada"] == ""

    g = GrabadorFalso()
    g.arrancado = True
    g._t = 60.0
    g.descartados = 3
    jv = jor.JornadaViva(JORNADA, grabador=g)
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="grabando"))
    monkeypatch.setattr(jor, "_VIVA", jv)
    grabando = jor.estado()

    monkeypatch.setattr(jor, "_VIVA", None)
    cua.guardar_jornada(cua.Jornada(nombre=JORNADA, estado="cerrada",
                                    segundos=60.0))
    cerrada = jor.estado()

    assert set(vacio) == set(grabando) == set(cerrada), (
        "claves que aparecen y desaparecen: vacio-grabando %s, "
        "grabando-cerrada %s"
        % (set(vacio) ^ set(grabando), set(grabando) ^ set(cerrada)))
    for etiqueta, est in (("vacio", vacio), ("grabando", grabando),
                          ("cerrada", cerrada)):
        for clave in ("estado", "segundos", "descartados", "materia",
                      "materias", "sesiones", "avisos", "lock"):
            assert clave in est, "%s: falta %r" % (etiqueta, clave)
        assert isinstance(est["materias"], list), \
            "%s: 'materias' cambia de tipo segun la rama" % etiqueta
    assert grabando["descartados"] == 3
    assert cerrada["estado"] == "cerrada"


def test_estado_no_comparte_las_listas_entre_llamadas():
    """La plantilla de claves lleva mutables: si se copiara con dict(), quien
    ordenara `materias` se lo ordenaria a todos los demas."""
    a = jor.estado()
    a["materias"].append("Fisica")
    a["avisos"].append("ruido")
    b = jor.estado()
    assert b["materias"] == [] and b["avisos"] == []


# ── 9. Mutear: lo que hace y lo que promete ──────────────────────────────────

def test_mutear_dice_la_verdad_sobre_la_granularidad_del_trozo():
    """El mudo se mira UNA vez, al cerrar cada trozo de 30 s: mutear tira el
    trozo en vuelo entero (tambien la clase anterior al muteo) y desmutear
    conserva entero el que empezo mudo. El docstring prometia lo contrario
    ('al desmutear se retoma sin cortes'), y un contrato que miente sobre
    cuanto se pierde es peor que el propio recorte."""
    np = pytest.importorskip("numpy")
    g = cap.Grabador(JORNADA)
    muestras = np.zeros(cap.TASA_DESTINO * 2, dtype=np.float32)

    g.mudo = True                       # muteado a mitad del trozo en vuelo
    assert g._trozo_listo(cap.FUENTE_SISTEMA, muestras, 0.0) == {}
    assert g.descartados == 1, "se descarta el trozo ENTERO, no un cacho"
    g.mudo = False                      # desmuteado a mitad del siguiente
    assert g._trozo_listo(cap.FUENTE_SISTEMA, muestras, g._t), \
        "se conserva el trozo ENTERO, tambien la parte que sonaba muda"

    doc = jor.JornadaViva.mutear.__doc__ or ""
    assert "sin cortes" not in doc, \
        "el docstring sigue prometiendo un corte limpio que no existe"
    assert "trozo" in doc.lower(), "no dice cual es la unidad real"
    assert "30 s" in doc, "no dice cuanto se puede perder a cada lado"
    assert "trozo" in (jor.JornadaViva.desmutear.__doc__ or "").lower()
    assert "GRANULARIDAD DEL MUDO" in (cap.Grabador.__doc__ or ""), \
        "captura.Grabador tampoco lo declara"
