"""
tests/test_monitores_nucleo.py
==============================
El motor de monitores persistente (cognia/monitores/nucleo.py) probado ENTERO
en seco: reloj inyectado, COGNIA_MONITORES_DIR a tmp_path, sin red y sin
modelo. Las unicas dependencias externas que se tocan de verdad son el
subproceso de `echo` (la accion 'ejecutar' tiene que estar probada contra un
proceso REAL: es literalmente su trabajo) y el disco.

QUE se prueba y POR QUE cada cosa:
  * persistencia entre dos instancias -> es EL fallo del motor viejo
    (cognia/console/monitors.py vivia en memoria y cerrar el REPL lo borraba).
  * recurrente vs una_vez            -> la CARDINALIDAD de Claude Code.
  * debounce y horas de silencio     -> el anti-ruido; sin esto un monitor
                                        recurrente lo apaga el usuario el dia 1.
  * contrato [SILENT]                -> registrar sin notificar (Hermes).
  * los TRES estados del ledger      -> completed/failed/unknown, y 'unknown'
                                        SOLO cuando nadie puede probar nada.
  * sonda que revienta               -> ultimo_error y el tick SIGUE. En el
                                        motor viejo una excepcion del check_fn
                                        mataba el monitor para siempre.
"""

import json
import time

import pytest

from cognia.monitores import nucleo


# ── utilidades ────────────────────────────────────────────────────────────

class Reloj:
    """Reloj fijo inyectable. El motor NO usa time.time() por dentro cuando se
    le pasa uno: asi el debounce y las horas de silencio se prueban sin dormir."""

    def __init__(self, t=1_000_000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def avanzar(self, segundos):
        self.t += float(segundos)
        return self.t


def _ts_hora_local(hora, minuto=0):
    """Timestamp de HOY a la hora local pedida. Se construye con mktime para
    que el test valga en cualquier zona horaria (en_horas_silencio mira la hora
    LOCAL, que es la que le importa a un humano que duerme)."""
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hora, minuto, 0, 0, 0, -1))


@pytest.fixture
def almacen(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_MONITORES_DIR", str(tmp_path / "monitores"))
    nucleo.reiniciar_motor()
    yield tmp_path / "monitores"
    nucleo.reiniciar_motor()


def _motor(reloj=None, **kw):
    return nucleo.MotorMonitores(reloj=reloj, **kw)


def _ledger(motor):
    return motor.ledger(n=0)


# ── persistencia: el fallo principal del motor viejo ──────────────────────

def test_persistencia_entre_dos_instancias(almacen):
    reloj = Reloj()
    a = _motor(reloj)
    creado = a.crear("build", {"tipo": "fichero_existe", "ruta": "x.bin"},
                     {"tipo": "avisar"}, intervalo_s=30, modo="una_vez",
                     debounce_s=5, horas_silencio=[22, 7])
    assert creado["id"] == "m1"
    assert (almacen / "monitores.json").exists()

    # Instancia NUEVA (simula reiniciar el REPL): lee del disco, no de memoria.
    b = _motor(Reloj())
    vivos = b.listar()
    assert [m["id"] for m in vivos] == ["m1"]
    assert vivos[0]["nombre"] == "build"
    assert vivos[0]["modo"] == "una_vez"
    assert vivos[0]["debounce_s"] == 5
    assert vivos[0]["horas_silencio"] == [22, 7]
    assert vivos[0]["condicion"]["ruta"] == "x.bin"

    # Y el id no se reusa: la instancia nueva sigue la numeracion.
    otro = b.crear("segundo", {"tipo": "fichero_existe", "ruta": "y.bin"})
    assert otro["id"] == "m2"
    assert [m["id"] for m in _motor(Reloj()).listar()] == ["m1", "m2"]


def test_borrar_persiste(almacen):
    a = _motor(Reloj())
    a.crear("uno", {"tipo": "fichero_existe", "ruta": "x"})
    assert a.borrar("m1") is True
    assert a.borrar("m1") is False
    assert _motor(Reloj()).listar() == []


def test_crear_rechaza_condicion_y_accion_desconocidas(almacen):
    m = _motor(Reloj())
    malo = m.crear("x", {"tipo": "telepatia"})
    assert "error" in malo and "telepatia" in malo["error"]
    malo2 = m.crear("x", {"tipo": "fichero_existe", "ruta": "a"},
                    {"tipo": "invocar_demonio"})
    assert "error" in malo2 and "invocar_demonio" in malo2["error"]
    assert m.listar() == []          # nada a medio crear queda persistido


# ── cardinalidad: una_vez vs recurrente ───────────────────────────────────

def test_una_vez_dispara_una_sola_vez_y_se_desactiva(almacen, tmp_path):
    objetivo = tmp_path / "salida.bin"
    objetivo.write_text("listo", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("aparecio", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "avisar"}, intervalo_s=0, modo="una_vez")

    inf1 = m.tick(reloj.t)
    assert inf1["disparados"] == ["m1"]
    reloj.avanzar(60)
    inf2 = m.tick(reloj.t)
    assert inf2["disparados"] == []
    assert inf2["evaluados"] == 0            # ya no se evalua: esta inactivo

    mon = m.obtener("m1")
    assert mon["disparos"] == 1
    assert mon["activo"] is False
    assert mon["estado"] == "disparado"
    assert len(m.pop_eventos()) == 1


def test_recurrente_dispara_en_cada_ocurrencia(almacen, tmp_path):
    objetivo = tmp_path / "salida.bin"
    objetivo.write_text("listo", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("sigue", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "avisar"}, intervalo_s=0, modo="recurrente")

    for _ in range(3):
        m.tick(reloj.t)
        reloj.avanzar(10)

    mon = m.obtener("m1")
    assert mon["disparos"] == 3
    assert mon["activo"] is True
    assert len(m.pop_eventos()) == 3


def test_intervalo_respeta_el_reloj(almacen, tmp_path):
    objetivo = tmp_path / "x"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("cada60", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            intervalo_s=60, modo="recurrente")

    assert m.tick(reloj.t)["evaluados"] == 1      # primera vez siempre evalua
    assert m.tick(reloj.avanzar(30))["evaluados"] == 0
    assert m.tick(reloj.avanzar(31))["evaluados"] == 1


# ── anti-ruido ────────────────────────────────────────────────────────────

def test_debounce_real_bloquea_el_redisparo(almacen, tmp_path):
    objetivo = tmp_path / "parpadea"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("ruidoso", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "avisar"}, intervalo_s=0, modo="recurrente", debounce_s=100)

    assert m.tick(reloj.t)["disparados"] == ["m1"]
    # Dentro de la ventana: la condicion SIGUE cumpliendose y aun asi no dispara.
    inf = m.tick(reloj.avanzar(50))
    assert inf["disparados"] == []
    assert [d["resultado"] for d in inf["detalle"] if d["id"] == "m1"] == ["debounce"]
    # Fuera de la ventana: vuelve a disparar.
    assert m.tick(reloj.avanzar(60))["disparados"] == ["m1"]
    assert m.obtener("m1")["disparos"] == 2


def test_horas_de_silencio_acumulan_y_liberan_al_salir(almacen, tmp_path):
    objetivo = tmp_path / "x"
    objetivo.write_text("1", encoding="utf-8")
    emitidos = []
    reloj = Reloj(_ts_hora_local(23, 30))          # dentro de 22:00-07:00
    m = _motor(reloj, emitir_fn=emitidos.append)
    m.crear("nocturno", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "avisar"}, intervalo_s=0, modo="una_vez",
            horas_silencio=[22, 7])

    inf = m.tick(reloj.t)
    assert inf["disparados"] == ["m1"]
    assert inf["silenciados"] == 1
    assert inf["notificados"] == 0
    assert m.pop_eventos() == []                   # el REPL no ve nada de noche
    assert m.silenciados_pendientes() == 1
    assert emitidos == []

    # El disparo SI quedo en el ledger aunque no se notificara: acumular no es
    # tragarse el evento.
    filas = [f for f in _ledger(m) if f["fase"] == "accion"]
    assert filas and filas[-1]["notificado"] is False
    assert filas[-1]["estado"] == "completed"

    # Al salir del rango, lo acumulado se libera (llega TARDE, no se pierde).
    inf2 = m.tick(_ts_hora_local(8, 0))
    assert inf2["notificados"] == 1
    assert m.silenciados_pendientes() == 0
    eventos = m.pop_eventos()
    assert len(eventos) == 1 and eventos[0].startswith("[monitor m1] nocturno:")
    assert len(emitidos) == 1


def test_rango_de_silencio_cruzando_medianoche_y_formatos():
    assert nucleo.en_horas_silencio([22, 7], _ts_hora_local(23, 0)) is True
    assert nucleo.en_horas_silencio([22, 7], _ts_hora_local(3, 0)) is True
    assert nucleo.en_horas_silencio([22, 7], _ts_hora_local(12, 0)) is False
    assert nucleo.en_horas_silencio("22-7", _ts_hora_local(23, 0)) is True
    assert nucleo.en_horas_silencio(["22:30", "07:15"], _ts_hora_local(22, 0)) is False
    assert nucleo.en_horas_silencio(["22:30", "07:15"], _ts_hora_local(22, 45)) is True
    assert nucleo.en_horas_silencio([9, 17], _ts_hora_local(12, 0)) is True
    # Un rango mal escrito NO puede silenciar un monitor para siempre.
    assert nucleo.en_horas_silencio("basura", _ts_hora_local(3, 0)) is False
    assert nucleo.en_horas_silencio([], _ts_hora_local(3, 0)) is False


def test_contrato_silent_registra_pero_no_notifica(almacen, tmp_path):
    """El comando decide si hay algo que contar. 'echo SILENT' es un comando
    REAL: el contrato se prueba contra un subproceso, no contra un doble."""
    objetivo = tmp_path / "x"
    objetivo.write_text("1", encoding="utf-8")
    emitidos = []
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=emitidos.append)
    m.crear("callado", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "ejecutar", "cmd": "echo SILENT"},
            intervalo_s=0, modo="una_vez")

    inf = m.tick(reloj.t)
    assert inf["disparados"] == ["m1"]
    assert inf["notificados"] == 0
    assert m.pop_eventos() == []
    assert emitidos == []

    fila = [f for f in _ledger(m) if f["fase"] == "accion"][-1]
    assert fila["silent"] is True
    assert fila["notificado"] is False
    assert fila["estado"] == "completed"          # corrio bien; solo no cuenta
    assert "SILENT" in fila["salida"]


@pytest.mark.parametrize("salida,esperado", [
    ("[SILENT]", True),
    ("[SILENT] nada que ver", True),
    ("todo en orden\nNO_REPLY", True),
    ("SILENT", True),
    ("hay 3 errores nuevos", False),
    ("", False),
    ("el proceso SILENT-ador fallo", False),   # la marca va en un extremo
])
def test_es_silencioso(salida, esperado):
    assert nucleo.es_silencioso(salida) is esperado


# ── acciones ──────────────────────────────────────────────────────────────

def test_accion_ejecutar_corre_un_comando_real(almacen, tmp_path):
    objetivo = tmp_path / "gatillo"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("echo", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "ejecutar", "cmd": "echo hola-monitor"},
            intervalo_s=0, modo="una_vez")

    inf = m.tick(reloj.t)
    assert inf["disparados"] == ["m1"]
    accion = [d for d in inf["detalle"] if d.get("accion")][0]["accion"]
    assert accion["estado"] == "completed"
    assert "hola-monitor" in accion["salida"]
    eventos = m.pop_eventos()
    assert len(eventos) == 1 and "hola-monitor" in eventos[0]


def test_despertar_agente_encola_tarea_y_no_llama_a_nadie(almacen, tmp_path):
    objetivo = tmp_path / "gatillo"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("despierta", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "despertar_agente", "tarea": "revisa el build y avisa"},
            intervalo_s=0, modo="una_vez")

    m.tick(reloj.t)
    tareas = m.tareas_pendientes()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "tarea"
    assert tareas[0]["tarea"] == "revisa el build y avisa"
    assert tareas[0]["monitor_id"] == "m1"
    assert m.tareas_pendientes() == []            # se drena

    # Mientras nadie la atienda, el estado honesto es 'unknown'.
    fila = [f for f in _ledger(m) if f["fase"] == "accion"][-1]
    assert fila["estado"] == "unknown"
    assert fila["tarea_id"] == tareas[0]["id"]

    # Quien la atendio es el UNICO que puede cerrarla.
    m.confirmar_tarea(tareas[0]["id"], True, "hecho")
    cierre = [f for f in _ledger(m) if f["fase"] == "tarea"][-1]
    assert cierre["estado"] == "completed"


def test_accion_flujo_encola_sin_reproductor_y_corre_con_el(almacen, tmp_path):
    objetivo = tmp_path / "gatillo"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()

    sin = _motor(reloj, emitir_fn=lambda t: None)
    sin.crear("f", {"tipo": "fichero_existe", "ruta": str(objetivo)},
              {"tipo": "flujo", "nombre": "publicar", "valores": {"v": "1"}},
              intervalo_s=0, modo="una_vez")
    sin.tick(reloj.t)
    tareas = sin.tareas_pendientes()
    assert len(tareas) == 1 and tareas[0]["tipo"] == "flujo"
    assert tareas[0]["flujo"] == "publicar" and tareas[0]["valores"] == {"v": "1"}

    llamadas = []

    def reproducir(nombre, valores):
        llamadas.append((nombre, valores))
        return {"ok": True, "resumen": "3 pasos ok"}

    con = _motor(reloj, emitir_fn=lambda t: None, reproducir_flujo_fn=reproducir)
    con.borrar("m1")
    con.crear("f2", {"tipo": "fichero_existe", "ruta": str(objetivo)},
              {"tipo": "flujo", "nombre": "publicar"}, intervalo_s=0, modo="una_vez")
    con.tick(reloj.t)
    assert llamadas == [("publicar", {})]
    assert con.tareas_pendientes() == []
    assert [f for f in _ledger(con) if f["fase"] == "accion"][-1]["estado"] == "completed"


def test_accion_que_revienta_queda_failed_sin_matar_el_tick(almacen, tmp_path):
    objetivo = tmp_path / "gatillo"
    objetivo.write_text("1", encoding="utf-8")

    def reproducir_roto(nombre, valores):
        raise RuntimeError("el reproductor no esta")

    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None, reproducir_flujo_fn=reproducir_roto)
    m.crear("f", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            {"tipo": "flujo", "nombre": "x"}, intervalo_s=0, modo="una_vez")

    inf = m.tick(reloj.t)                          # no lanza
    assert inf["disparados"] == ["m1"]
    fila = [f for f in _ledger(m) if f["fase"] == "accion"][-1]
    assert fila["estado"] == "failed"
    assert "RuntimeError" in m.pop_eventos()[0]


# ── el ledger y sus TRES estados terminales ───────────────────────────────

def test_ledger_registra_los_tres_estados_terminales(almacen, tmp_path):
    """completed / failed / unknown, y 'unknown' SOLO donde nadie puede probar
    nada: el comando que MATAMOS por timeout y la tarea que sigue en la cola."""
    objetivo = tmp_path / "gatillo"
    objetivo.write_text("1", encoding="utf-8")

    def ejecutar_falso(cmd, timeout_s=30.0, cwd=""):
        if "cuelga" in cmd:
            return {"codigo": None, "salida": "", "error": "timeout", "timeout": True}
        if "malo" in cmd:
            return {"codigo": 3, "salida": "", "error": "boom", "timeout": False}
        return {"codigo": 0, "salida": "ok", "error": "", "timeout": False}

    reloj = Reloj()
    m = _motor(reloj, ejecutar_fn=ejecutar_falso, emitir_fn=lambda t: None)
    cond = {"tipo": "fichero_existe", "ruta": str(objetivo)}
    m.crear("bien", cond, {"tipo": "ejecutar", "cmd": "bueno"}, intervalo_s=0, modo="una_vez")
    m.crear("mal", cond, {"tipo": "ejecutar", "cmd": "malo"}, intervalo_s=0, modo="una_vez")
    m.crear("colgado", cond, {"tipo": "ejecutar", "cmd": "cuelga"}, intervalo_s=0, modo="una_vez")
    m.crear("agente", cond, {"tipo": "despertar_agente", "tarea": "mira esto"},
            intervalo_s=0, modo="una_vez")

    m.tick(reloj.t)

    por_monitor = {f["monitor_id"]: f for f in _ledger(m) if f["fase"] == "accion"}
    assert por_monitor["m1"]["estado"] == "completed"
    assert por_monitor["m2"]["estado"] == "failed"
    assert por_monitor["m3"]["estado"] == "unknown"     # lo matamos: no se sabe
    assert por_monitor["m4"]["estado"] == "unknown"     # nadie la atendio aun
    assert set(f["estado"] for f in por_monitor.values()) <= set(nucleo.ESTADOS_TERMINALES)


def test_ledger_es_append_only_y_sobrevive_a_la_instancia(almacen, tmp_path):
    objetivo = tmp_path / "x"
    objetivo.write_text("1", encoding="utf-8")
    reloj = Reloj()
    a = _motor(reloj, emitir_fn=lambda t: None)
    a.crear("uno", {"tipo": "fichero_existe", "ruta": str(objetivo)},
            intervalo_s=0, modo="una_vez")
    a.tick(reloj.t)
    antes = len(_ledger(a))
    assert antes >= 3                                  # alta + disparo + accion

    b = _motor(Reloj())
    b.crear("dos", {"tipo": "fichero_existe", "ruta": str(objetivo)})
    filas = _ledger(b)
    assert len(filas) == antes + 1
    # Y el fichero es JSONL de verdad, una linea por evento.
    crudo = (almacen / "eventos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(crudo) == len(filas)
    assert all(json.loads(l)["ts"] for l in crudo)


# ── sondas: nunca matan el tick ───────────────────────────────────────────

def test_sonda_que_revienta_deja_ultimo_error_sin_matar_el_tick(almacen):
    """En el motor viejo una excepcion del check_fn mataba el hilo y el monitor
    quedaba muerto en silencio. Aca es ultimo_error y se reintenta."""
    llamadas = {"n": 0}

    def ejecutar_explosivo(cmd, timeout_s=30.0, cwd=""):
        llamadas["n"] += 1
        raise OSError("la sonda revento")

    reloj = Reloj()
    m = _motor(reloj, ejecutar_fn=ejecutar_explosivo, emitir_fn=lambda t: None)
    m.crear("sonda-mala", {"tipo": "comando", "cmd": "loquesea",
                           "dispara_si": "exit0"},
            {"tipo": "avisar"}, intervalo_s=0, modo="recurrente")

    inf = m.tick(reloj.t)                              # no lanza
    assert inf["errores"] == ["m1"]
    assert inf["disparados"] == []
    mon = m.obtener("m1")
    assert "OSError" in mon["ultimo_error"]
    assert mon["activo"] is True                       # sigue vivo
    assert mon["disparos"] == 0

    # El tick SIGUIENTE vuelve a intentarlo: el monitor no quedo muerto.
    m.tick(reloj.avanzar(10))
    assert llamadas["n"] == 2
    fallos = [f for f in _ledger(m) if f["fase"] == "sonda"]
    assert len(fallos) == 2 and all(f["estado"] == "failed" for f in fallos)


def test_condicion_desconocida_no_lanza():
    res = nucleo.evaluar_condicion({"tipo": "adivinacion"})
    assert res["disparo"] is False
    assert "adivinacion" in res["error"]


def test_sonda_url_no_lanza_con_url_muerta():
    # Sin red: un host inexistente devuelve arriba=False, no una excepcion.
    res = nucleo.sonda_url("http://127.0.0.1:9/nada", timeout_s=0.5)
    assert res["arriba"] is False and res["detalle"]


# ── los evaluadores declarativos ──────────────────────────────────────────

def test_fichero_existe_en_las_dos_direcciones(tmp_path):
    ruta = tmp_path / "lock"
    cond = {"tipo": "fichero_existe", "ruta": str(ruta)}
    assert nucleo.evaluar_condicion(cond)["disparo"] is False
    ruta.write_text("x", encoding="utf-8")
    assert nucleo.evaluar_condicion(cond)["disparo"] is True
    ausente = dict(cond, dispara_si="ausente")
    assert nucleo.evaluar_condicion(ausente)["disparo"] is False
    ruta.unlink()
    assert nucleo.evaluar_condicion(ausente)["disparo"] is True


def test_fichero_cambio_toma_linea_base_y_detecta_edicion(tmp_path):
    ruta = tmp_path / "config.json"
    ruta.write_text("a", encoding="utf-8")
    cond = {"tipo": "fichero_cambio", "ruta": str(ruta)}

    base = nucleo.evaluar_condicion(cond, {})
    assert base["disparo"] is False                    # linea base, no disparo
    assert base["estado"]["huella"]

    igual = nucleo.evaluar_condicion(cond, base["estado"])
    assert igual["disparo"] is False

    # Mismo tamano, contenido distinto: el mtime en FAT/NFS puede no moverse,
    # por eso la huella lleva ADEMAS el sha256 del contenido.
    ruta.write_text("b", encoding="utf-8")
    cambio = nucleo.evaluar_condicion(cond, igual["estado"])
    assert cambio["disparo"] is True
    assert nucleo.evaluar_condicion(cond, cambio["estado"])["disparo"] is False


def test_comando_los_cuatro_dispara_si():
    def falso(codigo, salida):
        def fn(cmd, timeout_s=30.0, cwd=""):
            return {"codigo": codigo, "salida": salida, "error": "", "timeout": False}
        return fn

    cond = {"tipo": "comando", "cmd": "x"}
    ok = {"ejecutar": falso(0, "")}
    assert nucleo.evaluar_condicion(dict(cond, dispara_si="exit0"), {}, ok)["disparo"] is True
    assert nucleo.evaluar_condicion(dict(cond, dispara_si="exit_no_0"), {}, ok)["disparo"] is False
    assert nucleo.evaluar_condicion(dict(cond, dispara_si="salida"), {}, ok)["disparo"] is False

    con_texto = {"ejecutar": falso(1, "ERROR: fallo el test\n")}
    assert nucleo.evaluar_condicion(dict(cond, dispara_si="salida"), {}, con_texto)["disparo"] is True
    assert nucleo.evaluar_condicion(dict(cond, dispara_si="exit_no_0"), {}, con_texto)["disparo"] is True
    regex = nucleo.evaluar_condicion(
        dict(cond, dispara_si="regex", patron=r"ERROR: .*"), {}, con_texto)
    assert regex["disparo"] is True and "fallo el test" in regex["detalle"]
    assert nucleo.evaluar_condicion(
        dict(cond, dispara_si="regex", patron=r"TODO OK"), {}, con_texto)["disparo"] is False


def test_comando_con_timeout_es_error_de_sonda_no_disparo():
    def cuelga(cmd, timeout_s=30.0, cwd=""):
        return {"codigo": None, "salida": "", "error": "timeout tras 1s", "timeout": True}

    res = nucleo.evaluar_condicion({"tipo": "comando", "cmd": "x", "dispara_si": "exit_no_0"},
                                   {}, {"ejecutar": cuelga})
    # exit_no_0 con codigo None podria "parecer" un disparo: inventar un disparo
    # con datos que no tenemos es el fallo silencioso que este repo ya pago.
    assert res["disparo"] is False
    assert "timeout" in res["error"]


def test_salida_shell_solo_mira_lineas_nuevas():
    lineas = ["arrancando", "compilando"]
    cond = {"tipo": "salida_shell", "shell_id": 1, "patron": r"BUILD OK"}
    sondas = {"shell": lambda sid: list(lineas)}

    r1 = nucleo.evaluar_condicion(cond, {}, sondas)
    assert r1["disparo"] is False and r1["estado"]["cursor_shell"] == 2

    lineas.append("BUILD OK en 42s")
    r2 = nucleo.evaluar_condicion(cond, r1["estado"], sondas)
    assert r2["disparo"] is True and "BUILD OK" in r2["detalle"]

    # La MISMA linea no vuelve a disparar: si no, un monitor recurrente
    # notificaria para siempre por un match viejo.
    r3 = nucleo.evaluar_condicion(cond, r2["estado"], sondas)
    assert r3["disparo"] is False


def test_proceso_vivo_sonda_real_sobre_este_proceso():
    import os as _os
    assert nucleo.sonda_proceso_vivo(_os.getpid())["vivo"] is True
    # pid imposible: la sonda contesta, no revienta (y en Windows NO usa
    # os.kill, que ahi MATA el proceso en vez de mirarlo).
    assert nucleo.sonda_proceso_vivo(999_999_998)["vivo"] is False
    assert nucleo.sonda_proceso_vivo("no-soy-un-pid")["vivo"] is False


def test_url_dispara_por_arriba_o_por_caida():
    cond = {"tipo": "url", "url": "http://x"}
    arriba = {"url": lambda u, t=5.0: {"arriba": True, "detalle": "HTTP 200"}}
    abajo = {"url": lambda u, t=5.0: {"arriba": False, "detalle": "timeout"}}
    assert nucleo.evaluar_condicion(cond, {}, arriba)["disparo"] is True
    assert nucleo.evaluar_condicion(cond, {}, abajo)["disparo"] is False
    caida = dict(cond, dispara_si="abajo")
    assert nucleo.evaluar_condicion(caida, {}, abajo)["disparo"] is True
    assert nucleo.evaluar_condicion(caida, {}, arriba)["disparo"] is False


# ── pausa, hilo vivo y heartbeat ──────────────────────────────────────────

def test_pausar_y_reanudar(almacen, tmp_path):
    ruta = tmp_path / "x"
    ruta.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("p", {"tipo": "fichero_existe", "ruta": str(ruta)},
            intervalo_s=0, modo="recurrente")
    assert m.pausar("m1") is True
    assert m.tick(reloj.t)["evaluados"] == 0
    assert _motor(Reloj()).obtener("m1")["activo"] is False    # la pausa persiste
    assert m.reanudar("m1") is True
    assert m.tick(reloj.avanzar(1))["evaluados"] == 1
    assert m.pausar("no-existe") is False


def test_hilo_vivo_dispara_y_para(almacen, tmp_path):
    ruta = tmp_path / "aparece"
    ruta.write_text("1", encoding="utf-8")
    m = _motor(emitir_fn=lambda t: None)           # reloj real: es el modo vivo
    m.crear("hilo", {"tipo": "fichero_existe", "ruta": str(ruta)},
            {"tipo": "avisar"}, intervalo_s=0, modo="una_vez")
    assert m.arrancar_hilo(paso_s=0.05) is True
    assert m.arrancar_hilo(paso_s=0.05) is False    # idempotente: UN solo hilo
    limite = time.time() + 5.0
    while time.time() < limite and not m.obtener("m1")["disparos"]:
        time.sleep(0.05)
    m.parar_hilo()
    assert m.hilo_vivo() is False
    assert m.obtener("m1")["disparos"] == 1
    assert len(m.pop_eventos()) == 1


def test_latido_en_fichero_aparte(almacen, tmp_path):
    ruta = tmp_path / "x"
    ruta.write_text("1", encoding="utf-8")
    reloj = Reloj()
    m = _motor(reloj, emitir_fn=lambda t: None)
    m.crear("l", {"tipo": "fichero_existe", "ruta": str(ruta)}, intervalo_s=0)
    m.tick(reloj.t)
    latido = m.latido()
    assert latido["ts"] == reloj.t
    assert latido["activos"] == 1 and latido["evaluados"] == 1
    assert (almacen / "latido.json").exists()


# ── el singleton que usa el cableado ──────────────────────────────────────

def test_api_de_modulo_usa_el_env(almacen, tmp_path):
    ruta = tmp_path / "x"
    ruta.write_text("1", encoding="utf-8")
    creado = nucleo.crear("desde-modulo", {"tipo": "fichero_existe", "ruta": str(ruta)},
                          {"tipo": "avisar"}, intervalo_s=0, modo="una_vez")
    assert creado["id"] == "m1"
    assert [m["id"] for m in nucleo.listar()] == ["m1"]
    nucleo.tick()
    eventos = nucleo.pop_eventos()
    assert len(eventos) == 1 and isinstance(eventos[0], str)
    assert nucleo.pop_eventos() == []              # drenado, como el motor viejo
    assert (almacen / "monitores.json").exists()
    assert nucleo.borrar("m1") is True


# ── regresion 2026-08-19: el tick MANUAL ignora el intervalo ────────────────

def test_tick_forzado_evalua_aunque_no_toque(tmp_path, monkeypatch):
    """`/centinela tick` es "comproba AHORA", no "si toca".

    Sin forzar=True, crear un monitor con el intervalo por defecto (60 s) y
    tickear a los 2 s devolvia "evaluados 0" con el monitor activo y la
    condicion ya cumplida: indistinguible de un motor roto. Lo cazo tecleando
    el comando en el REPL, no un test.
    """
    monkeypatch.setenv("COGNIA_MONITORES_DIR", str(tmp_path))
    from cognia.monitores import nucleo
    nucleo.reiniciar_motor()
    objetivo = tmp_path / "aparece.txt"
    nucleo.crear("aparece el fichero",
                 {"tipo": "fichero_existe", "ruta": str(objetivo)},
                 {"tipo": "avisar"}, intervalo_s=60)
    nucleo.tick()                       # marca ultimo_chequeo
    objetivo.write_text("ya", encoding="utf-8")
    sin_forzar = nucleo.tick()
    assert sin_forzar["evaluados"] == 0, "dentro del intervalo no toca"
    forzado = nucleo.tick(forzar=True)
    assert forzado["evaluados"] == 1
    assert len(forzado["disparados"]) == 1
