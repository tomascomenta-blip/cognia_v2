# -*- coding: utf-8 -*-
"""
tests/test_clases_widget.py
===========================
El cerebrito: el icono flotante del cuaderno (cognia/clases/widget.py), su
dibujo (widget_icono.py) y su puerta (`python -m cognia.clases`).

COMO SE PRUEBA ALGO QUE ES UNA VENTANA
--------------------------------------
Sin escritorio no hay `tk.Tk()`, asi que la mitad de este fichero se saltaria
en cualquier maquina sin pantalla -- y una suite que se salta lo que importa
esta en verde sin haber probado nada. Por eso la LOGICA vive fuera de la
ventana, en funciones puras que se prueban SIEMPRE:

  - `posicion_por_defecto` / `posicion_valida` / `elegir_posicion`: donde
    aparece el icono y que pasa si el monitor donde estaba ya no existe.
  - `entradas_menu` / `estado_icono` / `texto_tooltip`: que ofrece el menu y
    que cara pone el icono, para un `jornada.estado()` dado.
  - `buscar_navegador` / `comando_app`: como se abre el cuaderno en ventana
    propia.
  - `widget_icono.*`: el PNG, sus medidas y el cache.

Lo que SI necesita ventana (que la ventana sea flotante, transparente y sin
marco; que el menu se construya; que los `after` se cancelen al cerrar) va
detras de un fixture que salta si no hay display, y se prueba con un `Tk` DE
VERDAD -- nunca con un mock: lo unico que puede fallar ahi son justo los
atributos que un mock aceptaria sin rechistar.

AISLAMIENTO. `COGNIA_CLASES_DIR` se desvia a `tmp_path` en un fixture autouse
y se COMPRUEBA el desvio: sin eso, los PNG del icono, `widget.json` y
`widget.lock` se escribirian en el cuaderno REAL del duenio, y le moverian el
cerebrito de sitio cada vez que alguien corre la suite.
"""

import os
import subprocess
import sys
import threading
import time
import types

import pytest

pytest.importorskip("PIL")
pytest.importorskip("tkinter")

from PIL import Image                                          # noqa: E402

from cognia.clases import almacen as alm                       # noqa: E402
from cognia.clases import cuaderno as cua                      # noqa: E402
from cognia.clases import widget as wg                         # noqa: E402
from cognia.clases import widget_icono as ico                  # noqa: E402


@pytest.fixture(autouse=True)
def cuaderno_temporal(tmp_path, monkeypatch):
    """Todo lo que escriben estos tests cae en tmp_path, y se comprueba."""
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path))
    assert alm.raiz() == tmp_path, "el desvio de COGNIA_CLASES_DIR no cogio"
    # El memo de dibujos es de modulo: sin limpiarlo, un test que ya dibujo a
    # 40 px le daria a otro un icono "cacheado" que no esta en SU tmp_path.
    ico._MEMO.clear()
    yield


def _estado(**campos):
    """Un `jornada.estado()` de mentira, con TODAS las claves de la plantilla.

    Se construye desde `jornada._estado_base()` a proposito: si algun dia se
    aniade una clave, estos tests la ven en vez de probar una forma vieja.
    """
    from cognia.clases import jornada as jor
    base = jor._estado_base()
    base.update(campos)
    return base


# ── Posicion: el area de trabajo real, y la validacion contra monitores ──────

def test_posicion_por_defecto_usa_el_area_de_trabajo_no_la_pantalla():
    # Barra de tareas ARRIBA (y=40) y a la izquierda (x=48): la esquina de la
    # PANTALLA esta tapada y la del AREA no. Una implementacion con
    # winfo_screenwidth()/screenheight() daria (1920-48-12, 12).
    area = (48, 40, 1872, 1000)
    assert wg.posicion_por_defecto(area, lado=48, margen=12) == (1860, 52)


def test_posicion_por_defecto_en_monitor_secundario_a_la_derecha():
    # Segunda pantalla que empieza en x=1920: el icono va a SU esquina.
    assert wg.posicion_por_defecto((1920, 0, 1280, 1024), 48, 12) == (3140, 12)


def test_posicion_por_defecto_sin_area_cae_al_margen():
    assert wg.posicion_por_defecto((), 48, 12) == (12, 12)
    assert wg.posicion_por_defecto(None, 48, 12) == (12, 12)


def test_posicion_valida_dentro_y_fuera():
    pantallas = [(0, 0, 1920, 1080)]
    assert wg.posicion_valida((300, 300), pantallas, 48)
    assert not wg.posicion_valida((2600, 300), pantallas, 48)
    # Asomando por abajo: solo 20 px de 48 dentro (0,42) -- inagarrable.
    assert not wg.posicion_valida((300, 1060), pantallas, 48)
    # Justo la mitad dentro (24 px de 48): todavia vale.
    assert wg.posicion_valida((300, 1056), pantallas, 48)
    # Y no basta con que la esquina superior izquierda caiga dentro.
    assert not wg.posicion_valida((1900, 300), pantallas, 48)


def test_posicion_valida_sin_pantallas_conocidas_no_tira_la_del_duenio():
    # No se pudo enumerar: no se puede demostrar que sea mala, y moverle el
    # icono al duenio por no poder comprobarlo seria peor.
    assert wg.posicion_valida((2600, 300), [], 48)


def test_elegir_posicion_vuelve_al_defecto_si_el_monitor_desaparecio():
    # El caso real: el cerebrito vivia en el monitor de la derecha y hoy solo
    # hay portatil. Sin esta validacion se pintaria en x=2600, fuera de todo.
    pos = wg.elegir_posicion((2600, 300), [(0, 0, 1920, 1080)],
                             (0, 0, 1920, 1032), lado=48, margen=12)
    assert pos == (1860, 12)


def test_elegir_posicion_respeta_lo_guardado_si_sigue_valiendo():
    pos = wg.elegir_posicion((300, 400), [(0, 0, 1920, 1080)],
                             (0, 0, 1920, 1032), lado=48, margen=12)
    assert pos == (300, 400)


def test_elegir_posicion_con_config_sin_estrenar_o_corrupta():
    area = (0, 0, 1920, 1032)
    pantallas = [(0, 0, 1920, 1080)]
    defecto = wg.posicion_por_defecto(area, 48, 12)
    for guardada in (None, (None, None), ("x", 3), (), {"x": 1}):
        assert wg.elegir_posicion(guardada, pantallas, area, 48, 12) == defecto


def test_el_proceso_queda_per_monitor_dpi_aware():
    """El efecto REAL de la llamada, no que la llamada exista.

    Sin per-monitor v2, en un monitor al 125 % Windows estira la ventana (el
    PNG sale borroso) y las coordenadas de `geometry()` dejan de ser pixeles
    fisicos, asi que el icono tampoco cae donde se le dijo. Se pregunta por
    `GetProcessDpiAwareness`, que es la unica forma de comprobarlo sin ojos.
    """
    if os.name != "nt":
        pytest.skip("el DPI por proceso es de Windows")
    assert wg.hacerse_consciente_del_dpi() == ""
    import ctypes
    valor = ctypes.c_int(-1)
    # hProcess = NULL -> el proceso actual. 2 = PROCESS_PER_MONITOR_DPI_AWARE.
    assert ctypes.windll.shcore.GetProcessDpiAwareness(
        0, ctypes.byref(valor)) == 0
    assert valor.value == 2, "el proceso quedo en modo DPI %d" % valor.value


def test_area_trabajo_y_monitores_reales_en_windows():
    if os.name != "nt":
        pytest.skip("SPI_GETWORKAREA es de Windows")
    area = wg.area_trabajo()
    assert len(area) == 4 and area[2] > 0 and area[3] > 0
    pantallas = wg.monitores()
    assert pantallas and all(p[2] > 0 and p[3] > 0 for p in pantallas)
    # El area de trabajo cae dentro de alguna pantalla: es la comprobacion de
    # que las dos APIs hablan del mismo sistema de coordenadas.
    assert wg.posicion_valida(wg.posicion_por_defecto(area), pantallas)


# ── El menu se construye desde jornada.estado() ──────────────────────────────

def _claves(entradas):
    fuera = []
    for e in entradas:
        if e.get("tipo") == "separador":
            continue
        fuera.append(e.get("clave"))
    return fuera


def test_menu_sin_jornada_ofrece_grabar_y_no_detener():
    claves = _claves(wg.entradas_menu(_estado(grabando=False)))
    assert "grabar" in claves
    for prohibida in ("detener", "pausar", "mutear"):
        assert prohibida not in claves, "ofrece %s sin jornada" % prohibida


def test_menu_grabando_ofrece_detener_y_ya_no_grabar():
    claves = _claves(wg.entradas_menu(_estado(grabando=True)))
    assert "grabar" not in claves
    assert {"detener", "pausar", "mutear"} <= set(claves)


def test_menu_pausada_dice_reanudar_y_muteada_dice_desmutear():
    ent = wg.entradas_menu(_estado(grabando=True, pausada=True, muteada=True))
    etiquetas = {e.get("clave"): e.get("etiqueta") for e in ent
                 if e.get("tipo") == "comando"}
    assert etiquetas["pausar"] == "Reanudar"
    assert etiquetas["mutear"] == "Desmutear"
    ent = wg.entradas_menu(_estado(grabando=True))
    etiquetas = {e.get("clave"): e.get("etiqueta") for e in ent
                 if e.get("tipo") == "comando"}
    assert etiquetas["pausar"] == "Pausar"
    assert etiquetas["mutear"] == "Mutear"


def test_menu_con_otro_proceso_grabando_no_ofrece_nada_de_grabacion():
    est = _estado(grabando=False, otro_proceso=True,
                  lock={"pid": 4321, "vivo": True, "ajeno": True})
    ent = wg.entradas_menu(est)
    claves = _claves(ent)
    assert "grabar" not in claves and "detener" not in claves
    ocupado = [e for e in ent if e.get("clave") == "ocupado"][0]
    assert ocupado["activo"] is False and "4321" in ocupado["etiqueta"]


def test_menu_con_otro_proceso_ofrece_la_salida_de_emergencia():
    """Con el lock en manos ajenas tiene que haber POR DONDE SALIR.

    `jornada._pid_vivo` responde VIVO cuando no puede comprobar el proceso, y
    Windows recicla los PID: sin esta entrada, un lock olvidado cuyo numero hoy
    es de otro programa deja la grabacion bloqueada para siempre y desde el
    cerebrito -- la unica interfaz que el duenio mira -- no hay forma de
    arreglarlo.
    """
    est = _estado(grabando=False, otro_proceso=True,
                  lock={"pid": 4321, "vivo": True, "ajeno": True})
    ent = wg.entradas_menu(est)
    liberar = [e for e in ent if e.get("clave") == "liberar"]
    assert liberar, "no ofrece liberar el bloqueo con la grabacion atascada"
    assert liberar[0]["activo"] is True
    # Y NO aparece cuando no hay bloqueo ajeno que soltar: una entrada que
    # solo puede romper algo no se ofrece por si acaso.
    for sano in (_estado(grabando=False), _estado(grabando=True)):
        assert "liberar" not in _claves(wg.entradas_menu(sano))


def test_menu_materia_trae_las_declaradas_mas_otra():
    cua.declarar_materias(["Fisica", "Matematicas", "Historia"])
    ent = wg.entradas_menu(_estado(grabando=True), cua.materias_conocidas())
    sub = [e for e in ent if e.get("tipo") == "submenu"][0]
    etiquetas = [h["etiqueta"] for h in sub["hijos"]]
    assert etiquetas == ["Fisica", "Matematicas", "Historia", "otra..."]
    assert sub["activo"] is True
    # Sin jornada no hay donde marcar la materia: el submenu va apagado.
    sub = [e for e in wg.entradas_menu(_estado(grabando=False))
           if e.get("tipo") == "submenu"][0]
    assert sub["activo"] is False


def test_menu_siempre_tiene_cuaderno_exportar_y_salir():
    for est in (_estado(), _estado(grabando=True),
                _estado(otro_proceso=True, lock={"pid": 9})):
        claves = set(_claves(wg.entradas_menu(est)))
        assert {"cuaderno", "exportar", "salir"} <= claves


# ── La cara del icono ────────────────────────────────────────────────────────

def test_estado_icono_y_su_orden_de_prioridad():
    assert wg.estado_icono(_estado(grabando=False)) == "apagado"
    assert wg.estado_icono(_estado(grabando=True)) == "grabando"
    assert wg.estado_icono(_estado(grabando=True, muteada=True)) == "muteado"
    assert wg.estado_icono(_estado(grabando=True, pausada=True)) == "pausada"
    # El fallo gana a todo: da igual que ademas este muteado y en pausa.
    assert wg.estado_icono(_estado(grabando=True, muteada=True, pausada=True,
                                   aviso="la captura se cayo")) == "fallo"
    # Un aviso del grabador cuenta igual que el guardado en jornada.json.
    assert wg.estado_icono(_estado(grabando=True,
                                   avisos=["WASAPI: sin dispositivo"])) == "fallo"


def test_el_icono_no_miente_cuando_graba_OTRO_proceso():
    """El caso normal del duenio: el REPL graba y el cerebrito mira.

    `jornada.estado()['grabando']` es True SOLO si la jornada vive en este
    proceso, asi que mirando esa clave a secas el icono se pintaba 'apagado'
    con la clase grabandose desde el REPL. El duenio lee el cerebrito de un
    vistazo: un apagado ahi es dar la clase por no grabada (o al reves) sin
    abrir nada.
    """
    otro = _estado(grabando=False, otro_proceso=True,
                   lock={"pid": 4321, "vivo": True, "ajeno": True})
    assert wg.graba_alguien(otro) is True
    assert wg.estado_icono(otro) == "grabando"
    # El estado fino de esa jornada ajena sale de lo que dejo escrito en el
    # cuaderno: pausa y avisos si.
    assert wg.estado_icono(_estado(otro_proceso=True, pausada=True)) == "pausada"
    assert wg.estado_icono(_estado(otro_proceso=True,
                                   aviso="la captura se cayo")) == "fallo"
    # Y sigue apagado cuando de verdad no graba nadie.
    assert wg.graba_alguien(_estado()) is False
    assert wg.estado_icono(_estado()) == "apagado"


def test_tooltip_dice_el_aviso_y_el_minuto():
    txt = wg.texto_tooltip(_estado(grabando=True, jornada="2026-08-31",
                                   segundos=185.0, materia="Fisica",
                                   muteada=True, aviso="la captura se cayo"))
    assert "2026-08-31" in txt and "3 min" in txt and "Fisica" in txt
    assert "MUTEADO" in txt
    assert "la captura se cayo" in txt
    # Con la jornada en otro proceso el icono va ENCENDIDO, asi que el tooltip
    # tiene que explicar por que no aparece Detener.
    ajeno = wg.texto_tooltip(_estado(otro_proceso=True,
                                     lock={"pid": 77, "jornada": "2026-08-31"}))
    assert "otro proceso" in ajeno and "77" in ajeno
    assert "GRABANDO" in ajeno and "2026-08-31" in ajeno


# ── El navegador en modo aplicacion ──────────────────────────────────────────

def test_buscar_navegador_elige_el_primero_que_existe(tmp_path):
    falso = tmp_path / "no-esta.exe"
    real = tmp_path / "msedge.exe"
    real.write_bytes(b"MZ")
    otro = tmp_path / "chrome.exe"
    otro.write_bytes(b"MZ")
    assert wg.buscar_navegador([str(falso), str(real), str(otro)]) == str(real)


def test_buscar_navegador_vacio_si_no_hay_ninguno(tmp_path):
    assert wg.buscar_navegador([str(tmp_path / "nada.exe"), "", None]) == ""


def test_comando_app_abre_ventana_propia():
    cmd = wg.comando_app(r"C:\x\msedge.exe", "http://127.0.0.1:9/?t=abc")
    assert cmd[0] == r"C:\x\msedge.exe"
    # `--app=` es LO QUE quita pestanias y barra de direcciones: si esto
    # desaparece, el duenio recibe una pestania mas y nadie se entera.
    assert "--app=http://127.0.0.1:9/?t=abc" in cmd
    assert any(a.startswith("--window-size=") for a in cmd)


def test_candidatos_navegador_no_hardcodea_una_sola_ruta():
    if os.name != "nt":
        pytest.skip("las rutas conocidas son de Windows")
    cands = wg.candidatos_navegador()
    assert len(cands) >= 3
    nombres = {os.path.basename(c).lower() for c in cands}
    assert "msedge.exe" in nombres and "chrome.exe" in nombres


def test_abrir_en_app_cae_al_navegador_por_defecto_diciendolo(monkeypatch):
    abiertas = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertas.append(u))
    wg._ULTIMO_ERROR.clear()
    ok, mensaje = wg.abrir_en_app("http://127.0.0.1:9/?t=x", candidatos=[])
    assert ok and abiertas == ["http://127.0.0.1:9/?t=x"]
    assert "sin --app" in mensaje
    # Y sobre todo: la caida NO es muda.
    assert "navegador" in wg.ultimo_error().get("donde", "")


# ── Config persistida ────────────────────────────────────────────────────────

def test_config_ida_y_vuelta():
    wg.guardar_config({"x": 640, "y": 480, "lado": 64})
    cfg = wg.cargar_config()
    assert (cfg["x"], cfg["y"], cfg["lado"]) == (640, 480, 64)


def test_config_corrupta_no_impide_arrancar():
    wg.ruta_config().write_text("[1, 2, 3]", encoding="utf-8")
    wg._ULTIMO_ERROR.clear()
    cfg = wg.cargar_config()
    assert cfg["x"] is None and cfg["lado"] == wg.LADO
    assert "config" in wg.ultimo_error().get("donde", "")


def test_config_con_lado_absurdo_se_acota():
    wg.guardar_config({"x": 1, "y": 1, "lado": 99999})
    assert wg.cargar_config()["lado"] == 256


# ── Un unico cerebrito: el lock ──────────────────────────────────────────────

def test_lock_widget_niega_a_un_segundo_proceso_vivo():
    otro = subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(30)"])
    try:
        alm.guardar_json(wg.ruta_lock_widget(),
                         {"pid": otro.pid, "epoch": time.time()})
        ok, aviso = wg.tomar_lock_widget()
        assert not ok
        assert str(otro.pid) in aviso and "cerebrito" in aviso
    finally:
        otro.terminate()
        otro.wait(timeout=10)


def test_lock_widget_roba_el_de_un_pid_muerto_pero_lo_dice():
    muerto = subprocess.Popen([sys.executable, "-c", "pass"])
    muerto.wait(timeout=10)
    alm.guardar_json(wg.ruta_lock_widget(),
                     {"pid": muerto.pid, "epoch": time.time()})
    ok, aviso = wg.tomar_lock_widget()
    assert ok
    assert aviso and "ya no existe" in aviso
    assert wg.lock_widget_actual()["pid"] == os.getpid()


def test_lock_widget_ilegible_se_toma_pero_no_en_silencio():
    wg.ruta_lock_widget().write_text("", encoding="utf-8")
    ok, aviso = wg.tomar_lock_widget()
    assert ok and "ilegible" in aviso


def test_soltar_lock_no_borra_el_de_otro():
    alm.guardar_json(wg.ruta_lock_widget(), {"pid": 999999, "epoch": time.time()})
    motivo = wg.soltar_lock_widget()
    assert "no suelto" in motivo
    assert wg.ruta_lock_widget().exists()


def test_lock_propio_se_toma_y_se_suelta():
    ok, aviso = wg.tomar_lock_widget()
    assert ok and aviso == ""
    assert wg.soltar_lock_widget() == ""
    assert not wg.ruta_lock_widget().exists()


def test_main_se_niega_si_ya_hay_otro_cerebrito(capsys, monkeypatch):
    from cognia.clases import __main__ as puerta

    def _trampa(*a, **k):
        raise AssertionError("main() paso del lock y abrio una ventana")

    # LA TRAMPA NO ES DECORACION: si el lock dejara pasar, `main()` abriria el
    # cerebrito y se quedaria en el mainloop PARA SIEMPRE -- un test colgado,
    # no un test rojo. Asi falla en el acto y con el motivo escrito.
    monkeypatch.setattr(wg, "Cerebrito", _trampa)
    otro = subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(30)"])
    try:
        alm.guardar_json(wg.ruta_lock_widget(),
                         {"pid": otro.pid, "epoch": time.time()})
        assert puerta.main([]) == 1
        assert "ya hay un cerebrito" in capsys.readouterr().out
    finally:
        otro.terminate()
        otro.wait(timeout=10)


def test_main_ayuda_no_abre_ventana(capsys):
    from cognia.clases import __main__ as puerta
    assert puerta.main(["--help"]) == 0
    assert "cerebrito" in capsys.readouterr().out


# ── El icono: se dibuja de verdad y se cachea ────────────────────────────────

def test_icono_png_se_genera_y_mide_lo_que_debe():
    ruta = ico.icono_png("grabando", 40, 0)
    assert ruta.is_file() and ruta.stat().st_size > 0
    with Image.open(ruta) as img:
        assert img.size == (40, 40)
    # Y esta en el cuaderno (COGNIA_CLASES_DIR), no en una carpeta del sistema.
    assert alm.raiz() in ruta.parents


def test_el_cache_no_redibuja_lo_que_ya_esta():
    antes = ico.dibujos()
    ico.icono_png("grabando", 40, 0)
    assert ico.dibujos() == antes + 1
    for _ in range(5):
        ico.icono_png("grabando", 40, 0)
    assert ico.dibujos() == antes + 1, "el cache no esta evitando el dibujo"


def test_cache_truncado_se_detecta_y_se_redibuja():
    ruta = ico.icono_png("apagado", 40, 0)
    # El proceso murio a mitad del write: el fichero existe y no sirve.
    ruta.write_bytes(b"")
    assert ico.cache_valido(ruta, 40) is False
    antes = ico.dibujos()
    ico.icono_png("apagado", 40, 0)
    assert ico.dibujos() == antes + 1
    with Image.open(ruta) as img:
        assert img.size == (40, 40)


def test_dos_hilos_pidiendo_el_mismo_icono_lo_dibujan_una_vez():
    """La regresion del 2026-08-31, cazada por la propia suite.

    El widget precalienta los iconos EN UN HILO mientras el hilo de Tk pide
    el primero: los dos generan el MISMO PNG a la vez. Sin el lock de
    `widget_icono`, los dos deciden que falta, los dos dibujan y los dos
    renombran su temporal sobre el mismo destino -- que en Windows revienta
    con `PermissionError [WinError 32]` y deja al widget sin icono.
    """
    import threading

    antes = ico.dibujos()
    n = 6
    puerta = threading.Barrier(n)
    fallos = []

    def _pide():
        puerta.wait(timeout=10)
        try:
            ico.icono_png("pausada", 36, 0)
        except Exception as exc:            # noqa: BLE001 - se reporta entero
            fallos.append("%s: %s" % (type(exc).__name__, exc))

    hilos = [threading.Thread(target=_pide) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)
    assert fallos == []
    assert ico.dibujos() == antes + 1, "se dibujo %d veces" % (
        ico.dibujos() - antes)


def test_cache_de_otro_tamanio_no_vale():
    ruta = ico.icono_png("apagado", 40, 0)
    assert ico.cache_valido(ruta, 40) is True
    assert ico.cache_valido(ruta, 64) is False


def test_precalentar_deja_un_png_por_estado_y_fotograma():
    rutas = ico.precalentar(32)
    esperados = sum(ico.pasos_de(e) for e in ico.ESTADOS)
    assert len(rutas) == esperados
    assert all(r.is_file() for r in rutas)


def test_el_borde_es_duro_no_hay_halo_del_color_clave():
    """La comprobacion del contrato: ni un solo pixel a medio camino.

    Tk hace transparente EXACTAMENTE el color clave y nada mas. Un borde
    suavizado deja pixeles casi-magenta que no desaparecen y se ven como un
    halo contra el escritorio. Aqui se exige que cada pixel sea, o el color
    clave exacto, o algo LEJOS de el.
    """
    img = ico.componer("grabando", 48)
    clave = ico.rgb(ico.COLOR_CLAVE)
    px = img.load()
    sospechosos = 0
    for y in range(48):
        for x in range(48):
            c = px[x, y]
            if c == clave:
                continue
            d = sum((a - b) ** 2 for a, b in zip(c, clave)) ** 0.5
            if d < 60:
                sospechosos += 1
    assert sospechosos == 0, "%d pixeles con halo del color clave" % sospechosos


def test_el_icono_no_tiene_agujeros_transparentes_por_dentro():
    for estado in ico.ESTADOS:
        img = ico.componer(estado, 48)
        _, silueta = ico._base(48, alarma=(estado == "fallo"))
        assert ico.colisiones_clave(img, silueta) == 0, estado
    # Y sin la silueta la cuenta NO es cero: el fondo cuadrado es clave a
    # proposito. (Si esto fuera 0, la mascara no estaria haciendo nada.)
    assert ico.colisiones_clave(ico.componer("grabando", 48)) > 0


def test_los_estados_se_distinguen_a_ojo():
    def _centro(estado):
        img = ico.componer(estado, 48)
        px = img.load()
        # Una banda del cerebro, evitando el borde de la esfera.
        pts = [px[x, y] for y in range(20, 30) for x in range(16, 32)]
        n = float(len(pts))
        return tuple(sum(p[i] for p in pts) / n for i in range(3))

    grabando = _centro("grabando")
    muteado = _centro("muteado")
    apagado = _centro("apagado")
    # Grabando: verde de verdad (el canal G manda con holgura).
    assert grabando[1] > grabando[0] + 30 and grabando[1] > grabando[2] + 30
    # Muteado: gris literal, los tres canales pegados.
    assert max(muteado) - min(muteado) < 6
    # Apagado: mas oscuro que grabando.
    assert sum(apagado) < sum(grabando)
    # Fallo: el anillo rojo. Se mira el PRIMER pixel de dentro de la silueta
    # en la fila del centro -- que es exactamente donde cae el anillo -- y no
    # una coordenada fija, que segun el tamanio cae fuera del disco.
    def _anillo(estado):
        img = ico.componer(estado, 48)
        _, silueta = ico._base(48, alarma=(estado == "fallo"))
        m, px = silueta.load(), img.load()
        for x in range(48):
            if m[x, 24]:
                return px[x, 24]
        raise AssertionError("la silueta no cruza la fila del centro")

    rojo_fallo, rojo_ok = _anillo("fallo")[0], _anillo("grabando")[0]
    assert rojo_fallo > rojo_ok + 60, (rojo_fallo, rojo_ok)


def test_latido_recorre_el_ciclo_y_vuelve():
    assert ico.pasos_de("grabando") == ico.PASOS_LATIDO
    assert all(ico.pasos_de(e) == 1 for e in ico.ESTADOS if e != "grabando")
    factores = [ico.factor_latido(p) for p in range(ico.PASOS_LATIDO)]
    assert min(factores) >= ico.LATIDO_MIN - 1e-9
    assert max(factores) <= ico.LATIDO_MAX + 1e-9
    assert len(set(round(f, 4) for f in factores)) > 1, "el latido no late"
    # Cierra el ciclo: el fotograma PASOS es otra vez el 0.
    assert ico.factor_latido(ico.PASOS_LATIDO) == pytest.approx(factores[0])


def test_la_paleta_sale_del_svg_y_no_de_otro_sitio():
    """La regla de la unica fuente, comprobada contra el fichero.

    Si alguien cambia un color en widget_icono.py sin tocar el SVG (o al
    reves) hay dos cerebritos distintos: uno en la pagina del cuaderno y otro
    en el escritorio. Esto lo caza.
    """
    svg = (__import__("pathlib").Path(ico.__file__).parent
           / "assets" / "cerebro.svg").read_text(encoding="utf-8")
    for nombre, color in ico.PALETA.items():
        assert color in svg, "%s (%s) no esta en cerebro.svg" % (nombre, color)


# ── La ventana de verdad (salta sin escritorio) ──────────────────────────────

@pytest.fixture(scope="module")
def cerebrito(tmp_path_factory):
    """EL UNICO `Cerebrito` del fichero. Salta si no hay escritorio.

    DE AMBITO MODULO, y es un limite MEDIDO, no una optimizacion. En esta
    maquina, crear y destruir un `Cerebrito` por test hace que el SIGUIENTE
    `tk.Tk()` del proceso falle con "Can't find a usable init.tcl": el
    interprete anterior no acaba de soltarse y Tk no vuelve a inicializar.
    Reproducido el 2026-08-31: `tk.Tk()` pelado aguanta ~20 creaciones
    seguidas dentro de pytest, pero con la ventana completa del widget
    (overrideredirect, transparente, topmost, con PhotoImage y visible) el
    fallo asoma ya en la segunda o la tercera, de forma intermitente. En
    PRODUCCION no pasa nunca -- hay un cerebrito por proceso y vive hasta que
    se cierra -- asi que el sitio donde se arregla es aqui: UN interprete en
    todo el fichero, y por eso tampoco hay un fixture aparte que abra otro
    solo para decidir el skip.

    Los tests que lo usan no lo dejan en un estado que estorbe al siguiente:
    el que arrastra deja la posicion GUARDADA, que es justo lo que el de la
    posicion vuelve a calcular.
    """
    tk = pytest.importorskip("tkinter")
    carpeta = tmp_path_factory.mktemp("cerebrito")
    mp = pytest.MonkeyPatch()
    mp.setenv("COGNIA_CLASES_DIR", str(carpeta))
    assert alm.raiz() == carpeta, "el desvio de COGNIA_CLASES_DIR no cogio"
    try:
        app = wg.Cerebrito(lado=32)
    except tk.TclError as exc:
        mp.undo()
        pytest.skip("sin display para Tk: %s" % exc)
    try:
        yield app
    finally:
        app.cerrar()
        mp.undo()


def test_la_ventana_es_flotante_transparente_y_sin_marco(cerebrito):
    r = cerebrito.raiz
    r.update_idletasks()
    assert r.overrideredirect() in (1, True)
    assert int(r.attributes("-topmost")) == 1
    # `attributes` devuelve un Tcl_Obj, no un str: hay que pasarlo por str().
    assert str(r.attributes("-transparentcolor")).lower() \
        == ico.COLOR_CLAVE.lower()
    # El fondo TIENE que ser el color clave exacto o la transparencia no
    # recorta nada y sale un cuadrado magenta.
    assert str(r.cget("bg")).lower() == ico.COLOR_CLAVE.lower()
    assert str(cerebrito.etiqueta.cget("bg")).lower() == ico.COLOR_CLAVE.lower()


def test_el_cerebrito_nace_con_el_estado_ya_leido(cerebrito):
    """Al arrancar ya sabe si se graba, sin esperar al primer refresco.

    Sin esto el icono nace 'apagado' y no se corrige hasta un segundo
    despues: el duenio que enciende el cerebrito con la clase grabandose lo
    ve diciendo que no se graba, que es la mentira que este widget existe
    para no contar.
    """
    assert cerebrito.est, "el widget arranco sin leer jornada.estado()"
    assert "grabando" in cerebrito.est and "otro_proceso" in cerebrito.est
    assert cerebrito.icono_actual == wg.estado_icono(cerebrito.est)


def test_la_ventana_arranca_en_la_posicion_calculada(cerebrito):
    cerebrito.raiz.update_idletasks()
    esperada = wg.elegir_posicion(
        (cerebrito.cfg.get("x"), cerebrito.cfg.get("y")),
        wg.monitores(), wg.area_trabajo(), cerebrito.lado, wg.MARGEN)
    assert (cerebrito.raiz.winfo_x(), cerebrito.raiz.winfo_y()) == esperada


def test_la_imagen_mide_el_lado_del_icono_y_se_cachea(cerebrito):
    img = cerebrito._imagen("apagado", 0)
    assert (img.width(), img.height()) == (cerebrito.lado, cerebrito.lado)
    # La segunda vez es LA MISMA: el latido pide un icono cada 120 ms y
    # construir un PhotoImage nuevo cada vez llenaria el interprete de Tcl de
    # imagenes que nadie borra.
    assert cerebrito._imagen("apagado", 0) is img


def test_el_menu_de_tk_sale_del_estado(cerebrito):
    entradas = wg.entradas_menu(_estado(grabando=True), ["Fisica"])
    m = cerebrito._menu_tk(entradas)
    etiquetas = []
    for i in range(m.index("end") + 1):
        if m.type(i) == "separator":
            continue
        etiquetas.append(m.entrycget(i, "label"))
    assert "Detener" in etiquetas and "Grabar" not in etiquetas
    assert "Materia" in etiquetas and "Salir" in etiquetas
    # Sin jornada, el mismo constructor no crea Detener.
    m2 = cerebrito._menu_tk(wg.entradas_menu(_estado(grabando=False)))
    etq2 = [m2.entrycget(i, "label") for i in range(m2.index("end") + 1)
            if m2.type(i) != "separator"]
    assert "Grabar" in etq2 and "Detener" not in etq2
    cerebrito._soltar_menu(m)
    cerebrito._soltar_menu(m2)


def test_los_menus_no_se_acumulan_en_el_interprete(cerebrito):
    """Cada clic crea un menu; si no se destruye, se queda ahi todo el dia.

    `tk.Menu` no desaparece del interprete de Tcl porque su objeto Python se
    quede sin referencias. En una jornada de siete horas de clics eso son
    cientos de widgets colgando de la ventana.
    """
    antes = len(cerebrito.raiz.winfo_children())
    menus = [cerebrito._menu_tk(wg.entradas_menu(_estado(grabando=True),
                                                 ["Fisica"]))
             for _ in range(5)]
    assert len(cerebrito.raiz.winfo_children()) > antes
    for m in menus:
        cerebrito._soltar_menu(m)
    assert len(cerebrito.raiz.winfo_children()) == antes


def test_arrastrar_mueve_y_persiste_la_posicion(cerebrito):
    r = cerebrito.raiz
    r.update_idletasks()
    x0, y0 = r.winfo_x(), r.winfo_y()

    def ev(dx, dy):
        return types.SimpleNamespace(x_root=x0 + 10 + dx, y_root=y0 + 10 + dy)

    cerebrito._al_pulsar(ev(0, 0))
    cerebrito._al_arrastrar(ev(-120, 80))
    cerebrito._al_soltar(ev(-120, 80))
    r.update_idletasks()
    assert (r.winfo_x(), r.winfo_y()) == (x0 - 120, y0 + 80)
    cfg = wg.cargar_config()
    assert (cfg["x"], cfg["y"]) == (x0 - 120, y0 + 80)


def test_un_clic_sin_mover_no_guarda_posicion_nueva(cerebrito, monkeypatch):
    # El clic abre el menu; aqui solo interesa que NO se confunda con un
    # arrastre de 0 px y reescriba la config.
    abiertos = []
    monkeypatch.setattr(cerebrito, "_abrir_menu",
                        lambda ev=None: abiertos.append(1))
    guardados = []
    monkeypatch.setattr(wg, "guardar_config", lambda c: guardados.append(c))
    e = types.SimpleNamespace(x_root=500, y_root=500)
    cerebrito._al_pulsar(e)
    cerebrito._al_arrastrar(types.SimpleNamespace(x_root=502, y_root=501))
    cerebrito._al_soltar(e)
    assert abiertos == [1] and guardados == []


def test_el_tick_repinta_el_latido_sin_dormir(cerebrito):
    """El latido avanza fotograma en cada tick, sin `time.sleep`.

    `time.sleep` en el hilo de Tk congela la ventana entera. Aqui se
    comprueba el efecto: un tick cambia el fotograma y deja el `after`
    reprogramado.
    """
    cerebrito.est = _estado(grabando=True)
    cerebrito._pintar("grabando", 0)
    # `_ticks` a 0 a proposito: en el tick multiplo de TICKS_POR_REFRESCO el
    # widget RELEE `jornada.estado()` -- que aqui dice que no se graba -- y
    # repinta 'apagado', asi que el latido no avanzaria. Es el comportamiento
    # bueno; lo que se prueba en este test es el otro.
    cerebrito._ticks = 0
    cerebrito._tick_id = cerebrito._tras(60000, lambda: None)
    paso0 = cerebrito._paso
    cerebrito._tick()
    assert cerebrito._paso == (paso0 + 1) % ico.pasos_de("grabando")
    assert cerebrito._tick_id in cerebrito._pendientes


def test_el_latido_no_dibuja_el_png_en_el_hilo_de_tk(cerebrito, monkeypatch):
    """Un fotograma que no esta en el cache se dibuja EN UN HILO.

    `widget_icono.icono_png` compone el PNG con Pillow y al publicarlo puede
    llegar a dormir medio segundo reintentando el `os.replace` (20 x 25 ms).
    En el hilo de Tk eso es la ventana congelada -- menu incluido -- que es
    justo lo que promete el encabezado de widget.py que no pasa.
    """
    real = ico.icono_png
    hilos = []

    def _espia(estado, lado, paso=0):
        hilos.append(threading.current_thread().name)
        return real(estado, lado, paso)

    monkeypatch.setattr(ico, "icono_png", _espia)
    # Cache frio: este test corre con COGNIA_CLASES_DIR en SU tmp_path, donde
    # no hay ningun PNG todavia.
    cerebrito._imagenes.pop(("pausada", 0), None)
    cerebrito._pidiendo.discard(("pausada", 0))
    assert not ico.cache_valido(ico.ruta_cache("pausada", cerebrito.lado, 0),
                                cerebrito.lado)

    cerebrito._pintar("pausada", 0, dibujar=False)
    # La cara que TOCA se apunta igual, o el refresco volveria a pedirla cada
    # segundo y el latido dejaria de avanzar.
    assert cerebrito.icono_actual == "pausada"
    for h in list(cerebrito._hilos):
        h.join(timeout=30)
    # Se dibujo -- si no, no se probaria nada -- pero NUNCA en el hilo de Tk.
    # (El hilo de trabajo puede haber terminado antes de esta linea: por eso se
    # mira QUIEN dibujo y no cuando.)
    assert hilos, "no se llego a dibujar el fotograma"
    assert "MainThread" not in hilos, "dibujo el PNG en el hilo de Tk: %s" % hilos
    # Y el fotograma deja de estar "pedido" en cuanto vuelve, para que un
    # fallo al dibujarlo se pueda reintentar en el siguiente refresco.
    cerebrito._vaciar_cola()
    assert ("pausada", 0) not in cerebrito._pidiendo


def test_liberar_el_bloqueo_pregunta_antes_de_forzar(cerebrito, monkeypatch):
    """La salida de emergencia no se dispara sola.

    Forzar el lock con una grabacion viva de verdad deja dos grabadores sobre
    la misma clase: por eso hay dialogo, y por eso un 'no' no llama a
    `jornada.forzar_liberacion`.
    """
    import tkinter.messagebox as mb

    forzados = []
    monkeypatch.setattr(wg.jor, "forzar_liberacion",
                        lambda motivo="": forzados.append(motivo) or
                        {"liberado": True, "lock": {}, "aviso": "liberado"})

    def _inline(trabajo, luego=None, nombre=""):
        res = trabajo()
        if luego is not None:
            luego(res)

    monkeypatch.setattr(cerebrito, "_en_hilo", _inline)
    cerebrito.est = _estado(otro_proceso=True,
                            lock={"pid": 4321, "jornada": "2026-08-31"})

    respuestas = [False]
    preguntas = []

    def _preguntar(*a, **k):
        preguntas.append(a[1] if len(a) > 1 else k.get("message", ""))
        return respuestas.pop(0)

    monkeypatch.setattr(mb, "askyesno", _preguntar)
    cerebrito.ejecutar("liberar")
    assert forzados == [], "forzo el lock sin que el duenio dijera que si"
    assert preguntas and "4321" in preguntas[0], preguntas

    respuestas[:] = [True]
    cerebrito.ejecutar("liberar")
    assert len(forzados) == 1 and "cerebrito" in forzados[0]


def test_ejecutar_desconocido_no_revienta_y_avisa(cerebrito):
    wg._ULTIMO_ERROR.clear()
    cerebrito.ejecutar("no-existe")
    assert "menu" in wg.ultimo_error().get("donde", "")


def test_salir_pregunta_antes_de_cortar_una_clase(cerebrito, monkeypatch):
    """Cerrar con la clase grabandose pregunta; sin jornada, no.

    Una clase no se puede rehacer, y un clic sin querer en 'Salir' se ve
    exactamente igual que uno queriendo. Las tres respuestas tienen que hacer
    tres cosas distintas: Si para y cierra, No cierra sin parar, Cancelar no
    cierra.
    """
    import tkinter.messagebox as mb

    cerrados, parados = [], []
    monkeypatch.setattr(cerebrito, "cerrar", lambda: cerrados.append(1))
    monkeypatch.setattr(wg.jor, "parar", lambda: parados.append(1))

    def _inline(trabajo, luego=None, nombre=""):
        res = trabajo()
        if luego is not None:
            luego(res)

    monkeypatch.setattr(cerebrito, "_en_hilo", _inline)

    preguntas = []
    monkeypatch.setattr(mb, "askyesnocancel",
                        lambda *a, **k: preguntas.pop(0))

    # Sin jornada: cierra directo, sin molestar con un dialogo.
    cerebrito.est = _estado(grabando=False)
    cerebrito.salir()
    assert cerrados == [1] and parados == []

    cerebrito.est = _estado(grabando=True)
    preguntas[:] = [None]               # Cancelar
    cerebrito.salir()
    assert cerrados == [1] and parados == [], "cerro pese a Cancelar"

    preguntas[:] = [True]               # Si: para la jornada y cierra
    cerebrito.salir()
    assert parados == [1] and cerrados == [1, 1]

    preguntas[:] = [False]              # No: cierra sin parar
    cerebrito.salir()
    assert parados == [1] and cerrados == [1, 1, 1]


# ── El menu que cierra la ventana (en OTRO proceso: destruye su Tk) ──────────

# Va en un proceso aparte y no con el fixture porque para reproducir el bug hay
# que DESTRUIR la ventana desde dentro del menu, y el `Cerebrito` del fixture lo
# comparten los demas tests (ademas, un segundo `tk.Tk()` en este proceso falla:
# ver el docstring del fixture).
_GUION_SALIR = '''
import os, sys
os.environ["COGNIA_CLASES_DIR"] = sys.argv[1]
import tkinter as tk
from cognia.clases import widget as wg

try:
    app = wg.Cerebrito(lado=32)
except tk.TclError as exc:
    print("SIN-DISPLAY: %s" % exc)
    raise SystemExit(3)

original = wg.Cerebrito._menu_tk


def _con_salir(self, entradas, padre=None):
    m = original(self, entradas, padre)
    if padre is None:
        # Tk ejecuta el comando de la entrada elegida ANTES de que tk_popup
        # vuelva. Eso es lo unico que hace falta simular (no hay raton aqui):
        # cuando el `finally` de _abrir_menu corre, la ventana YA no existe.
        m.tk_popup = lambda x, y: self.ejecutar("salir")
    return m


wg.Cerebrito._menu_tk = _con_salir
app._abrir_menu(None)
print("MENU-CERRADO-SIN-EXCEPCION")
raise SystemExit(0)
'''


def test_elegir_salir_en_el_menu_no_vuelca_un_tclerror(tmp_path):
    """Salir destruye la ventana DENTRO de tk_popup; el finally viene despues.

    Con la ventana destruida, `m.grab_release()` lanza
    `TclError: can't invoke "grab" command: application has been destroyed`, y
    estaba en un `finally` sin proteger: la excepcion se escapaba del
    manejador del clic en mitad del cierre y salia por la consola del duenio
    cada vez que cerraba el cerebrito desde su propio menu.
    """
    guion = tmp_path / "salir_desde_el_menu.py"
    guion.write_text(_GUION_SALIR, encoding="utf-8")
    # El PYTHONPATH se pone a mano: el subproceso no hereda el sys.path que
    # pytest arma, y sin esto el `import cognia` de alli falla y el test se
    # veria rojo por el motivo equivocado.
    paquete = os.path.dirname(os.path.dirname(os.path.abspath(wg.__file__)))
    entorno = dict(os.environ)
    entorno["PYTHONPATH"] = (os.path.dirname(paquete) + os.pathsep
                             + entorno.get("PYTHONPATH", ""))
    fin = subprocess.run([sys.executable, str(guion), str(tmp_path / "cuad")],
                         capture_output=True, text=True, timeout=180,
                         env=entorno)
    if fin.returncode == 3:
        pytest.skip("sin display para Tk: %s" % fin.stdout.strip())
    assert "Traceback" not in fin.stderr, fin.stderr
    assert "MENU-CERRADO-SIN-EXCEPCION" in fin.stdout, (fin.stdout, fin.stderr)
    assert fin.returncode == 0, (fin.returncode, fin.stdout, fin.stderr)


# ESTE TEST CIERRA EL CEREBRITO COMPARTIDO Y TIENE QUE QUEDARSE EL ULTIMO DEL
# FICHERO. Cualquier test de ventana puesto detras se encontraria la ventana
# ya destruida. Lo que no se puede hacer es abrir otro `Cerebrito` para el:
# ver el docstring del fixture (el segundo `tk.Tk()` del proceso falla).
def test_cerrar_cancela_los_after_pendientes(cerebrito):
    app = cerebrito
    ident = app._tras(60000, lambda: None)
    assert ident in app._pendientes
    app.cerrar()
    assert app._pendientes == set()
    assert app._cerrando is True
    # Y despues de cerrar no se puede programar nada nuevo: un `after` que
    # salte tras el destroy() toca widgets muertos.
    assert app._tras(10, lambda: None) is None
    # Las imagenes tambien se sueltan: una PhotoImage que sobrevive a la
    # ventana llama a Tcl desde el recolector, en el hilo que toque.
    assert app._imagenes == {} and app._hilos == []
