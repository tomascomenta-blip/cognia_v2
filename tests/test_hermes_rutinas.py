# -*- coding: utf-8 -*-
"""
tests/test_hermes_rutinas.py
============================
Tests del motor de rutinas programadas (cognia/hermes/rutinas.py).

TODOS corren SIN modelo y SIN red: `correr_agente_fn` se inyecta y el almacen
se aisla en tmp_path via COGNIA_RUTINAS_DIR. Lo unico que sale del proceso son
los scripts de prueba, que son python/bash de dos lineas escritos por el propio
test dentro de la jaula.
"""

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta

import pytest

from cognia.hermes import rutinas as R


@pytest.fixture(autouse=True)
def almacen_aislado(tmp_path, monkeypatch):
    """Cada test estrena almacen. El modulo lee la env var en CADA llamada, asi
    que no hace falta recargarlo."""
    monkeypatch.setenv("COGNIA_RUTINAS_DIR", str(tmp_path / "rutinas"))
    monkeypatch.delenv("COGNIA_RUTINAS_SCRIPT_TIMEOUT", raising=False)
    monkeypatch.delenv("COGNIA_RUTINAS_INACTIVIDAD", raising=False)
    R._asegurar_dirs()
    return tmp_path


def _agente(respuesta="informe", registro=None):
    """Fabrica un correr_agente_fn inyectable que apunta lo que recibio."""
    def _fn(prompt, rutina):
        if registro is not None:
            registro.append({"prompt": prompt, "rutina": rutina})
        return respuesta
    return _fn


def _escribir_script(nombre, cuerpo):
    ruta = R.dir_scripts() / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(cuerpo, encoding="utf-8")
    return nombre


# ---------------------------------------------------------------------------
# 1) Parser: las cuatro formas + errores
# ---------------------------------------------------------------------------

def test_parse_duracion_unidades():
    assert R.parse_duracion("30m") == 30
    assert R.parse_duracion("2h") == 120
    assert R.parse_duracion("1d") == 1440
    assert R.parse_duracion(" 45 minutos ") == 45


@pytest.mark.parametrize("malo", ["", "m", "0m", "-5m", "30x", "media hora"])
def test_parse_duracion_rechaza(malo):
    with pytest.raises(ValueError):
        R.parse_duracion(malo)


def test_parse_horario_una_vez_por_duracion():
    ahora = datetime(2026, 8, 18, 10, 0)
    h = R.parse_horario("30m", ahora=ahora)
    assert h["clase"] == "una_vez"
    assert R._desde_iso(h["correr_en"]) == R._aware(ahora + timedelta(minutes=30))


def test_parse_horario_intervalo_en_dos_idiomas():
    for txt in ("cada 30m", "every 30m", "CADA 30 minutos"):
        h = R.parse_horario(txt)
        assert h["clase"] == "intervalo"
        assert h["minutos"] == 30
    assert R.parse_horario("every 2h")["minutos"] == 120


def test_parse_horario_cron_cinco_campos():
    h = R.parse_horario("0 2 * * *")
    assert h["clase"] == "cron"
    assert h["campos"]["minuto"] == [0]
    assert h["campos"]["hora"] == [2]
    assert h["campos"]["dia_libre"] and h["campos"]["semana_libre"]


def test_parse_horario_iso_anclado():
    h = R.parse_horario("2026-09-01T07:30")
    assert h["clase"] == "una_vez"
    dt = R._desde_iso(h["correr_en"])
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 9, 1, 7, 30)


@pytest.mark.parametrize("malo", [
    "",
    "   ",
    "cada 0m",
    "cada rato",
    "0 2 * *",              # cuatro campos
    "0 2 * * * *",          # seis campos
    "99 2 * * *",           # minuto fuera de rango
    "0 24 * * *",           # hora fuera de rango
    "0 2 * * 1-9",          # dia de semana fuera de rango
    "*/0 * * * *",          # paso 0
    "5-1 * * * *",          # rango invertido
    "manana por la manana",
])
def test_parse_horario_rechaza_lo_ilegible(malo):
    with pytest.raises(ValueError):
        R.parse_horario(malo)


def test_parse_cron_listas_rangos_y_pasos():
    campos = R.parse_cron("*/15 1,3 1-5 * *")
    assert campos["minuto"] == [0, 15, 30, 45]
    assert campos["hora"] == [1, 3]
    assert campos["dia"] == [1, 2, 3, 4, 5]
    assert campos["dia_libre"] is False
    assert campos["semana_libre"] is True


def test_parse_cron_domingo_es_0_y_7():
    assert 0 in R.parse_cron("0 0 * * 0")["semana"]
    assert 0 in R.parse_cron("0 0 * * 7")["semana"]
    # '5-7' es viernes-sabado-domingo, NO lunes-viernes.
    semana = set(R.parse_cron("0 0 * * 5-7")["semana"])
    assert {5, 6, 7, 0} <= semana
    assert 1 not in semana


def test_siguiente_cron_diario_y_mensual():
    campos = R.parse_cron("0 2 * * *")
    base = R._aware(datetime(2026, 8, 18, 3, 0))
    nxt = R._siguiente_cron(campos, base)
    assert (nxt.day, nxt.hour, nxt.minute) == (19, 2, 0)

    campos = R.parse_cron("30 9 1 * *")          # el 1 de cada mes 09:30
    nxt = R._siguiente_cron(campos, R._aware(datetime(2026, 8, 18, 3, 0)))
    assert (nxt.month, nxt.day, nxt.hour, nxt.minute) == (9, 1, 9, 30)


def test_siguiente_cron_dia_de_semana():
    campos = R.parse_cron("0 8 * * 1")           # lunes 08:00
    # 2026-08-18 es martes -> el proximo lunes es el 24.
    nxt = R._siguiente_cron(campos, R._aware(datetime(2026, 8, 18, 12, 0)))
    assert (nxt.day, nxt.isoweekday(), nxt.hour) == (24, 1, 8)


def test_siguiente_cron_imposible_devuelve_none():
    # El 30 de febrero no llega nunca; el parser lo acepta y el calculo dice
    # "no hay proxima" en vez de colgarse buscando.
    assert R._siguiente_cron(R.parse_cron("0 0 30 2 *"),
                             R._aware(datetime(2026, 1, 1))) is None


def test_siguiente_una_vez_no_vuelve_tras_correr():
    h = R.parse_horario("30m")
    assert R.siguiente(h, ultima_en=None) is not None
    assert R.siguiente(h, ultima_en=R._ahora().isoformat()) is None


def test_siguiente_intervalo_se_ancla_a_la_ultima_corrida():
    h = R.parse_horario("cada 60m")
    ahora = R._aware(datetime(2026, 8, 18, 10, 0))
    ultima = R._aware(datetime(2026, 8, 18, 9, 30)).isoformat()
    prox = R._desde_iso(R.siguiente(h, ultima_en=ultima, ahora=ahora))
    assert prox == R._aware(datetime(2026, 8, 18, 10, 30))


def test_siguiente_no_dispara_en_tromba_tras_un_mes_parado():
    # Una rutina 'cada 5m' parada un mes NO puede quedar con proxima corrida a
    # un mes de distancia hacia atras: se adelanta al siguiente hueco.
    h = R.parse_horario("cada 5m")
    ahora = R._aware(datetime(2026, 8, 18, 10, 0))
    ultima = R._aware(datetime(2026, 7, 18, 10, 0)).isoformat()
    prox = R._desde_iso(R.siguiente(h, ultima_en=ultima, ahora=ahora))
    assert prox > ahora


# ---------------------------------------------------------------------------
# 2) CRUD + pendientes() con reloj fijo
# ---------------------------------------------------------------------------

def test_crear_listar_borrar():
    R.crear("diaria", "0 2 * * *", "resume el dia")
    R.crear("otra", "cada 30m", "mira el disco")
    nombres = [r["nombre"] for r in R.listar()]
    assert sorted(nombres) == ["diaria", "otra"]
    assert R.obtener("diaria")["prompt"] == "resume el dia"
    assert R.borrar("diaria") is True
    assert R.borrar("diaria") is False
    assert [r["nombre"] for r in R.listar()] == ["otra"]


def test_crear_valida_la_configuracion():
    R.crear("una", "cada 10m", "x")
    with pytest.raises(ValueError):
        R.crear("una", "cada 10m", "x")               # nombre repetido
    with pytest.raises(ValueError):
        R.crear("../fuga", "cada 10m", "x")           # nombre con ruta
    with pytest.raises(ValueError):
        R.crear("sin_prompt", "cada 10m", "")         # agente sin prompt
    with pytest.raises(ValueError):
        R.crear("sin_script", "cada 10m", "x", despertar_agente=False)
    with pytest.raises(ValueError):
        R.crear("pasada", "2020-01-01T00:00", "x")    # one-shot ya pasado


def test_pendientes_con_reloj_fijo():
    R.crear("cada_hora", "cada 60m", "revisa")
    creada = R.obtener("cada_hora")
    prox = R._desde_iso(creada["proxima_en"])

    assert R.pendientes(prox - timedelta(seconds=1)) == []
    debidas = R.pendientes(prox)
    assert [r["nombre"] for r in debidas] == ["cada_hora"]
    assert [r["nombre"] for r in R.pendientes(prox + timedelta(hours=5))] == ["cada_hora"]


def test_pendientes_ignora_las_desactivadas_y_las_sin_proxima():
    R.crear("una", "30m", "haz algo")
    prox = R._desde_iso(R.obtener("una")["proxima_en"])
    R.marcar_corrida("una", "completada", ahora=prox)
    tras = R.obtener("una")
    assert tras["activa"] is False and tras["proxima_en"] is None
    assert R.pendientes(prox + timedelta(days=1)) == []


def test_marcar_corrida_rearma_la_recurrente():
    R.crear("cada_hora", "cada 60m", "revisa")
    prox = R._desde_iso(R.obtener("cada_hora")["proxima_en"])
    R.marcar_corrida("cada_hora", "fallida", detalle="se cayo", ahora=prox)
    tras = R.obtener("cada_hora")
    assert tras["ultimo_estado"] == "fallida"
    assert tras["ultimo_detalle"] == "se cayo"
    assert tras["corridas"] == 1
    assert tras["activa"] is True                       # NO se apaga sola
    assert R._desde_iso(tras["proxima_en"]) > prox


def test_marcar_corrida_no_lanza_con_estado_desconocido():
    R.crear("x", "cada 10m", "y")
    tras = R.marcar_corrida("x", "inventado")
    assert tras["ultimo_estado"] == "fallida"
    assert "inventado" in tras["ultimo_detalle"]
    assert R.marcar_corrida("no_existe", "completada") is None


# ---------------------------------------------------------------------------
# 3) Ledger: tres estados terminales, inmutabilidad, cero reintentos
# ---------------------------------------------------------------------------

def test_ledger_completada_y_fallida():
    e1 = R.abrir_ejecucion("r1")
    assert e1["estado"] == "reclamada"
    assert R.marcar_corriendo(e1["id"])["estado"] == "corriendo"
    assert R.cerrar_ejecucion(e1["id"], "completada")["estado"] == "completada"

    e2 = R.abrir_ejecucion("r1")
    R.marcar_corriendo(e2["id"])
    cerrada = R.cerrar_ejecucion(e2["id"], "fallida", detalle="se rompio")
    assert cerrada["estado"] == "fallida" and cerrada["detalle"]

    estados = {e["id"]: e["estado"] for e in R.ejecuciones("r1")}
    assert estados[e1["id"]] == "completada"
    assert estados[e2["id"]] == "fallida"


def test_ledger_un_terminal_no_se_reescribe():
    e = R.abrir_ejecucion("r1")
    R.marcar_corriendo(e["id"])
    assert R.cerrar_ejecucion(e["id"], "completada") is not None
    assert R.cerrar_ejecucion(e["id"], "fallida") is None
    assert R.marcar_corriendo(e["id"]) is None
    assert R.ejecuciones("r1")[0]["estado"] == "completada"
    assert R.cerrar_ejecucion(e["id"], "en_curso") is None   # no es terminal


def test_ledger_es_append_only():
    e = R.abrir_ejecucion("r1")
    R.marcar_corriendo(e["id"])
    R.cerrar_ejecucion(e["id"], "completada")
    lineas = R._fichero_ledger().read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 3
    assert [json.loads(l)["estado"] for l in lineas] == [
        "reclamada", "corriendo", "completada"]


def test_desconocida_solo_con_el_dueno_probado_muerto():
    # Un proceso REAL que ya termino: eso si es prueba de muerte.
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=60)
    muerto = p.pid
    reg = R.abrir_ejecucion("r1")
    R.marcar_corriendo(reg["id"])
    huerfana = dict(R._estados_efectivos()[reg["id"]])
    huerfana.update({"proceso": "otro-proceso", "pid": muerto, "arranque": 1,
                     "maquina": platform.node() or "?"})
    R._anexar_ledger(huerfana)

    assert R.recuperar_interrumpidas() == 1
    assert R.ejecuciones("r1")[0]["estado"] == "desconocida"
    # Y no se reintenta nada: recuperar no vuelve a tocarla.
    assert R.recuperar_interrumpidas() == 0


def test_sin_prueba_de_muerte_no_se_marca_desconocida():
    vivo = R.abrir_ejecucion("viva")
    R.marcar_corriendo(vivo["id"])                  # dueno = este proceso

    otra_maquina = R.abrir_ejecucion("ajena")
    reg = dict(R._estados_efectivos()[otra_maquina["id"]])
    reg.update({"proceso": "otro", "maquina": "una-maquina-que-no-es-esta"})
    R._anexar_ledger(reg)

    pid_ajeno_vivo = R.abrir_ejecucion("ajena_viva")
    reg2 = dict(R._estados_efectivos()[pid_ajeno_vivo["id"]])
    reg2.update({"proceso": "otro", "pid": os.getpid(),
                 "arranque": R._arranque_proceso(os.getpid())})
    R._anexar_ledger(reg2)

    assert R.recuperar_interrumpidas() == 0
    estados = {e["rutina"]: e["estado"] for e in R.ejecuciones(limite=10)}
    assert estados["viva"] in ("reclamada", "corriendo")
    assert estados["ajena"] in ("reclamada", "corriendo")
    assert estados["ajena_viva"] in ("reclamada", "corriendo")


# ---------------------------------------------------------------------------
# 4) Contrato [SILENT]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "[SILENT]",
    "  [silent]  ",
    "SILENT",
    "NO_REPLY",
    "NO REPLY",
    ".NO_REPLY",
    "[SILENT] sin cambios detectados",
    "2 ofertas filtradas\n\n[SILENT]",
    "[SILENT]\nno hubo nada",
])
def test_es_silencio_suprime(texto):
    assert R.es_silencio(texto) is True


@pytest.mark.parametrize("texto", [
    "",
    "   ",
    "Pense en quedarme [SILENT] pero aqui va el resumen del dia.",
    "Silent retry succeeded: el reintento silencioso funciono",
    "El informe menciona NO_REPLY como una constante del codigo y sigue.",
])
def test_es_silencio_no_se_traga_un_informe(texto):
    assert R.es_silencio(texto) is False


def test_silent_suprime_la_entrega_pero_no_la_pierde():
    R.crear("vigia", "cada 10m", "avisa solo si cambia algo")
    rutina = R.obtener("vigia")
    informe = R.ejecutar(rutina, _agente("[SILENT] nada nuevo"))

    assert informe["agente_llamado"] is True
    assert informe["entregado"] is False
    assert informe["suprimido"] == "[SILENT]"
    assert informe["salida"] == ""
    assert informe["estado"] == "completada"
    # No se pierde: queda en el ledger y en disco.
    assert R.ejecuciones("vigia")[0]["suprimido"] == "[SILENT]"
    assert informe["ruta_salida"] and os.path.isfile(informe["ruta_salida"])
    assert "nada nuevo" in open(informe["ruta_salida"], encoding="utf-8").read()


def test_una_respuesta_normal_si_se_entrega():
    R.crear("diaria", "cada 10m", "resume")
    informe = R.ejecutar(R.obtener("diaria"), _agente("Hoy hubo 3 cambios."))
    assert informe["entregado"] is True
    assert informe["suprimido"] is None
    assert informe["salida"] == "Hoy hubo 3 cambios."


# ---------------------------------------------------------------------------
# 5) Puerta wakeAgent
# ---------------------------------------------------------------------------

def test_puerta_despertar_solo_la_ultima_linea_json():
    assert R.puerta_despertar("") is True
    assert R.puerta_despertar("hola") is True
    assert R.puerta_despertar('{"wakeAgent": true}') is True
    assert R.puerta_despertar('{"otra": 1}') is True
    assert R.puerta_despertar("[1,2,3]") is True
    assert R.puerta_despertar('datos\n{"wakeAgent": false}') is False
    assert R.puerta_despertar('{"wakeAgent": false}\n\n') is False
    # Si el JSON NO es la ultima linea, no es una puerta.
    assert R.puerta_despertar('{"wakeAgent": false}\ncambios detectados') is True


def test_wakeagent_false_salta_al_agente():
    _escribir_script("puerta.py", 'print(\'{"wakeAgent": false}\')\n')
    R.crear("monitor", "cada 10m", "resume el cambio", script="puerta.py")
    llamadas = []
    informe = R.ejecutar(R.obtener("monitor"), _agente(registro=llamadas))

    assert llamadas == []                      # el agente NO se desperto
    assert informe["agente_llamado"] is False
    assert informe["suprimido"] == "wakeAgent=false"
    assert informe["entregado"] is False
    assert informe["estado"] == "completada"


# ---------------------------------------------------------------------------
# 6) Inyeccion del stdout del script
# ---------------------------------------------------------------------------

def test_el_script_inyecta_su_stdout_en_el_prompt():
    _escribir_script("precio.py", "print('PRECIO 42 (bajo 3%)')\n")
    R.crear("precios", "cada 10m", "Si CAMBIO, resumelo.", script="precio.py")
    llamadas = []
    informe = R.ejecutar(R.obtener("precios"), _agente("bajo un 3%", llamadas))

    assert informe["script_ok"] is True
    assert informe["script_salida"] == "PRECIO 42 (bajo 3%)"
    assert len(llamadas) == 1
    prompt = llamadas[0]["prompt"]
    assert "## Salida del script" in prompt
    assert "PRECIO 42 (bajo 3%)" in prompt
    assert "Si CAMBIO, resumelo." in prompt
    assert "[SILENT]" in prompt                 # el contrato viaja en el prompt
    assert informe["entregado"] is True


def test_script_sin_salida_no_gasta_una_llamada_al_modelo():
    _escribir_script("mudo.py", "pass\n")
    R.crear("mudo", "cada 10m", "analiza", script="mudo.py")
    llamadas = []
    informe = R.ejecutar(R.obtener("mudo"), _agente(registro=llamadas))
    assert llamadas == []
    assert informe["agente_llamado"] is False
    assert informe["suprimido"] == "script sin salida"


def test_script_roto_se_reporta_y_el_agente_lo_cuenta():
    _escribir_script("roto.py", "import sys; sys.stderr.write('boom'); sys.exit(3)\n")
    R.crear("roto", "cada 10m", "analiza", script="roto.py")
    llamadas = []
    informe = R.ejecutar(R.obtener("roto"), _agente("el script fallo", llamadas))

    assert informe["script_ok"] is False
    assert informe["estado"] == "fallida"       # el fallo NO se esconde
    assert "boom" in informe["detalle"]
    assert "## Error del script" in llamadas[0]["prompt"]


def test_modo_sin_agente_entrega_el_stdout_tal_cual():
    _escribir_script("vigia.py", "print('DISCO 91%')\n")
    R.crear("disco", "cada 10m", "", script="vigia.py", despertar_agente=False)
    llamadas = []
    informe = R.ejecutar(R.obtener("disco"), _agente(registro=llamadas))

    assert llamadas == []
    assert informe["salida"] == "DISCO 91%"
    assert informe["entregado"] is True
    assert informe["estado"] == "completada"


def test_modo_sin_agente_stdout_vacio_es_silencio():
    _escribir_script("callado.py", "pass\n")
    R.crear("callado", "cada 10m", "", script="callado.py", despertar_agente=False)
    informe = R.ejecutar(R.obtener("callado"), _agente())
    assert informe["entregado"] is False
    assert informe["suprimido"] == "script sin salida"


def test_script_fuera_de_la_jaula_se_bloquea(tmp_path):
    fuera = tmp_path / "fuera.py"
    fuera.write_text("print('hola')\n", encoding="utf-8")
    ok, salida = R.correr_script(str(fuera))
    assert ok is False and "jaula" in salida
    ok, salida = R.correr_script("../fuera.py")
    assert ok is False


# ---------------------------------------------------------------------------
# 7) Timeouts: el script y el agente no cuelgan el tick
# ---------------------------------------------------------------------------

def test_timeout_del_script_no_cuelga(monkeypatch):
    monkeypatch.setenv("COGNIA_RUTINAS_SCRIPT_TIMEOUT", "1")
    _escribir_script("lento.py", "import time; time.sleep(60)\n")
    R.crear("lenta", "cada 10m", "analiza", script="lento.py",
            despertar_agente=False)

    t0 = time.time()
    informe = R.ejecutar(R.obtener("lenta"), _agente())
    tardo = time.time() - t0

    assert tardo < 30, "el timeout no corto: tardo %.1fs" % tardo
    assert informe["script_ok"] is False
    assert informe["estado"] == "fallida"
    assert "agoto el tiempo" in informe["detalle"]
    assert informe["entregado"] is True          # un vigia roto avisa


def test_timeout_por_inactividad_del_agente(monkeypatch):
    monkeypatch.setenv("COGNIA_RUTINAS_INACTIVIDAD", "1")
    R.crear("colgada", "cada 10m", "piensa")

    def _agente_colgado(prompt, rutina):
        time.sleep(30)
        return "tarde"

    t0 = time.time()
    informe = R.ejecutar(R.obtener("colgada"), _agente_colgado)
    tardo = time.time() - t0

    assert tardo < 20, "el watchdog no corto: tardo %.1fs" % tardo
    assert informe["estado"] == "fallida"
    assert "inactividad" in informe["detalle"]


def test_el_latido_estira_el_limite_de_inactividad(monkeypatch):
    """El limite es de INACTIVIDAD, no de duracion: un agente que sigue dando
    senales corre mas que el limite sin que lo maten."""
    monkeypatch.setenv("COGNIA_RUTINAS_INACTIVIDAD", "1")
    R.crear("trabajadora", "cada 10m", "piensa")

    def _agente_activo(prompt, rutina, latir=None):
        for _ in range(6):
            time.sleep(0.4)
            if latir:
                latir()
        return "termine"

    informe = R.ejecutar(R.obtener("trabajadora"), _agente_activo)
    assert informe["estado"] == "completada"
    assert informe["salida"] == "termine"


def test_una_excepcion_del_agente_no_rompe_el_turno():
    R.crear("explota", "cada 10m", "piensa")

    def _agente_malo(prompt, rutina):
        raise RuntimeError("el backend se cayo")

    informe = R.ejecutar(R.obtener("explota"), _agente_malo)
    assert informe["estado"] == "fallida"
    assert "el backend se cayo" in informe["detalle"]
    assert informe["entregado"] is True          # un fallo que nadie ve, no existe
    assert R.ejecuciones("explota")[0]["estado"] == "fallida"


# ---------------------------------------------------------------------------
# 8) tick() y los tres ficheros de liveness
# ---------------------------------------------------------------------------

def test_tick_corre_lo_pendiente_y_rearma():
    R.crear("cada_hora", "cada 60m", "revisa")
    prox = R._desde_iso(R.obtener("cada_hora")["proxima_en"])

    vacio = R.tick(prox - timedelta(minutes=5), _agente())
    assert vacio["pendientes"] == 0 and vacio["corridas"] == []

    informe = R.tick(prox, _agente("todo bien"))
    assert informe["pendientes"] == 1
    assert informe["error"] is None
    assert [c["salida"] for c in informe["entregables"]] == ["todo bien"]

    tras = R.obtener("cada_hora")
    assert tras["ultimo_estado"] == "completada"
    assert tras["corridas"] == 1
    assert R._desde_iso(tras["proxima_en"]) > prox


def test_tick_de_una_rutina_de_una_sola_vez():
    R.crear("recordatorio", "30m", "recuerdale la reunion")
    prox = R._desde_iso(R.obtener("recordatorio")["proxima_en"])
    informe = R.tick(prox, _agente("recordado"))
    assert len(informe["corridas"]) == 1
    tras = R.obtener("recordatorio")
    assert tras["activa"] is False and tras["estado"] == "completada"
    assert R.tick(prox + timedelta(hours=2), _agente())["pendientes"] == 0


def test_liveness_heartbeat_exito_y_error():
    assert R.edad_latido() is None
    R.tick(None, _agente())
    assert R.edad_latido() is not None
    assert R.edad_ultimo_exito() is not None
    assert R.ultimo_error_tick() is None

    R.registrar_error_tick("jobs.json con dueno equivocado")
    assert "dueno equivocado" in R.ultimo_error_tick()
    R.limpiar_error_tick()
    assert R.ultimo_error_tick() is None


def test_tick_no_propaga_una_excepcion_del_almacen(monkeypatch):
    R.crear("x", "cada 1m", "y")

    def _revienta(*_a, **_k):
        raise OSError("disco lleno")

    monkeypatch.setattr(R, "pendientes", _revienta)
    informe = R.tick(None, _agente())
    assert informe["error"] and "disco lleno" in informe["error"]
    assert "disco lleno" in R.ultimo_error_tick()


def test_un_json_corrupto_no_mata_el_motor():
    R.crear("x", "cada 10m", "y")
    R._fichero_rutinas().write_text("{no es json", encoding="utf-8")
    assert R.listar() == []
    assert R.pendientes() == []
    R._fichero_ledger().write_text("basura\n", encoding="utf-8")
    assert R.ejecuciones() == []


# ── revision adversarial 2026-08-25 ──────────────────────────────────────────

def test_nombre_libre_es_max_mas_uno_no_len_mas_uno():
    assert R.nombre_libre() == "rutina-1"
    for i in (1, 2, 3):
        R.crear("rutina-%d" % i, "cada 2h", "p%d" % i)
    R.crear("vigia", "cada 2h", "libre")            # no mueve el contador
    assert R.borrar("rutina-2")
    assert len(R.listar()) == 3                     # len+1 daria 'rutina-3': existe
    assert R.nombre_libre() == "rutina-4"
    R.crear(R.nombre_libre(), "cada 2h", "cuatro")  # no lanza 'Ya existe'
    assert R.nombre_libre("vigia") == "vigia-1"
    assert R.nombre_libre() == "rutina-5"


def test_llamar_agente_hereda_las_contextvars_del_tick():
    import contextvars
    quien = contextvars.ContextVar("quien_de_prueba", default=None)
    token = quien.set("ana")
    try:
        ok, resp, err = R.llamar_agente(lambda p, r: "vi:%s" % quien.get(), "p",
                                        {"nombre": "x"}, limite=30)
    finally:
        quien.reset(token)
    assert (ok, resp, err) == (True, "vi:ana", None)
