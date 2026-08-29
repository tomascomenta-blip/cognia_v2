# -*- coding: utf-8 -*-
"""
tests/test_arranque.py
======================
`cognia empezar` (cognia/arranque.py): las ramas que NO se pueden probar a
mano en esta maquina sin romper algo.

El camino feliz (config ya hecha + :8080 vivo + regimen NATIVO) se verifica
corriendo el comando de verdad, y esta en el informe de la sesion. Lo que se
prueba aqui es lo otro:

  - la rama de backend MUERTO, que en esta maquina NO se puede provocar: el
    llama-server de :8080 es compartido y `flota.arrancar` empieza por
    `parar()`. Se prueba con stubs, jamas parando el server real.
  - la PROHIBICION de relanzar un backend vivo (test de regresion: si alguien
    quita la guarda, este test falla).
  - la idempotencia: la segunda corrida no pregunta NADA.
  - el espacio en disco COMPROBADO ANTES de ofrecer la descarga.
  - el paso 4 con la sonda SIN RESPUESTA (timeout), que en esta maquina pasa
    de verdad ~1 de cada 2 homes virgenes pero no se puede provocar a mano de
    forma fiable: no se publica un regimen que no se midio.
"""

import importlib
import json
import os

import pytest

import cognia.arranque as A


@pytest.fixture(autouse=True)
def home_tmp(tmp_path):
    """COGNIA_HOME apuntando a un temporal, y la RESTAURACION del estado
    global al salir.

    arranque._first_run() recarga cognia.first_run cuando el home cambio (sus
    paths se congelan en el import). Sin este restore, el resto de la suite
    heredaria un first_run apuntando a un tmp_path ya borrado."""
    viejo = os.environ.get("COGNIA_HOME")
    # LLAMA_GGUF_PATH fuera: conftest.py:22 carga el .env DEL DUENO y ahi vive
    # la ruta a un GGUF real de 5.8 GB. Con esa variable puesta, el paso
    # 'pesos' salia [OK] por el entorno de la maquina y no por lo que el test
    # monta — el veredicto dependia de quien corriera la suite (cazado al
    # escribir estos tests: el caso "falta todo" daba la accion del paso 3).
    gguf = os.environ.pop("LLAMA_GGUF_PATH", None)
    os.environ["COGNIA_HOME"] = str(tmp_path)
    try:
        yield tmp_path
    finally:
        if gguf is not None:
            os.environ["LLAMA_GGUF_PATH"] = gguf
        if viejo is None:
            os.environ.pop("COGNIA_HOME", None)
        else:
            os.environ["COGNIA_HOME"] = viejo
        import cognia.first_run
        importlib.reload(cognia.first_run)


@pytest.fixture
def sin_preguntas(monkeypatch):
    """input() prohibido: cualquier pregunta en una rama que no debe
    preguntar rompe el test en vez de colgar la corrida."""
    def _prohibido(*a, **k):
        raise AssertionError("pregunto al usuario y no debia")
    monkeypatch.setattr("builtins.input", _prohibido)


def _sin_gguf(monkeypatch):
    monkeypatch.setattr(A, "_gguf_servible", lambda: None)


# ── Paso 1: config ───────────────────────────────────────────────────────────

class TestConfig:

    def test_home_virgen_crea_config_sin_preguntar_sin_tty(self, home_tmp):
        p = A.paso_config(interactivo=False)
        assert p["estado"] == "hago"
        assert (home_tmp / ".setup_done").is_file()
        texto = (home_tmp / "config.env").read_text(encoding="utf-8")
        assert "COGNIA_LANG=espanol" in texto

    def test_segunda_corrida_es_ok_y_no_pregunta(self, home_tmp, sin_preguntas):
        A.paso_config(interactivo=False)
        p = A.paso_config(interactivo=True)   # interactivo, pero ya esta hecho
        assert p["estado"] == "ok"

    def test_wizard_minimo_guarda_nombre_e_idioma(self, home_tmp, monkeypatch):
        respuestas = iter(["Anthuan", "ingles"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(respuestas))
        p = A.paso_config(interactivo=True)
        texto = (home_tmp / "config.env").read_text(encoding="utf-8")
        assert p["estado"] == "hago"
        assert "COGNIA_USER_NAME=Anthuan" in texto
        assert "COGNIA_LANG=ingles" in texto

    def test_idioma_raro_cae_a_espanol(self, home_tmp, monkeypatch):
        respuestas = iter(["", "klingon"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(respuestas))
        A.paso_config(interactivo=True)
        assert "COGNIA_LANG=espanol" in (home_tmp / "config.env").read_text(
            encoding="utf-8")


# ── Paso 2: pesos ────────────────────────────────────────────────────────────

class TestPesos:

    def test_no_confunde_un_adapter_ni_un_mmproj_con_un_modelo(self):
        # El bug que este filtro evita: decir "ya tenes pesos" senalando el
        # proyector multimodal (1.3 GB) o un LoRA del fleet.
        assert A._es_servible("Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf")
        assert not A._es_servible("mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf")
        assert not A._es_servible("cognia3b_v2_f16.lora.gguf")
        assert not A._es_servible("qwen2.5-0.5b-portero-q8_0.gguf")
        assert not A._es_servible("leeme.txt")
        # De un GGUF partido solo la parte 1 es el punto de entrada.
        assert A._es_servible("coder-14b-q4_k_m-00001-of-00002.gguf")
        assert not A._es_servible("coder-14b-q4_k_m-00002-of-00002.gguf")

    def test_encuentra_el_gguf_mas_grande_del_home(self, home_tmp, monkeypatch):
        monkeypatch.setattr(A, "MIN_GGUF_BYTES", 10)
        monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
        d = home_tmp / "models"
        d.mkdir()
        (d / "chico.gguf").write_bytes(b"x" * 100)
        (d / "grande.gguf").write_bytes(b"x" * 900)
        (d / "mmproj-vl.gguf").write_bytes(b"x" * 5000)   # pesa mas, no sirve
        assert A._gguf_servible().name == "grande.gguf"

    def test_backend_vivo_hace_innecesarios_los_pesos_locales(self, monkeypatch,
                                                              sin_preguntas):
        # Un server ya sirviendo (con un GGUF de fuera de ~/.cognia, o remoto)
        # deja la maquina lista igual: no se le ofrece bajar 2.6 GB al pedo.
        _sin_gguf(monkeypatch)
        monkeypatch.setattr(A, "_modelo_del_backend", lambda *a: {"modelo": "X.gguf"})
        p = A.paso_pesos(sin_descarga=False, interactivo=True, backend_ok=True)
        assert p["estado"] == "ok"
        assert "X.gguf" in p["detalle"]

    def test_sin_descarga_no_pregunta_y_da_la_orden_instalada(self, monkeypatch,
                                                              sin_preguntas):
        _sin_gguf(monkeypatch)
        p = A.paso_pesos(sin_descarga=True, interactivo=True, backend_ok=False)
        assert p["estado"] == "falta"
        assert p["accion"] == "python -m cognia install-model"
        assert "scripts" not in p["accion"]   # scripts/ no viaja en el wheel

    def test_espacio_insuficiente_se_ve_ANTES_de_preguntar(self, monkeypatch,
                                                           sin_preguntas):
        # La razon de model_install._check_espacio: la descarga de 1.9 GB
        # moria a la mitad con un error crudo de urllib. Aqui ni se ofrece.
        _sin_gguf(monkeypatch)
        monkeypatch.setattr(A, "_tam_remoto_gguf", lambda: 2_000_000_000)
        monkeypatch.setattr(A, "_espacio_libre", lambda p: 500_000_000)
        p = A.paso_pesos(sin_descarga=False, interactivo=True, backend_ok=False)
        assert p["estado"] == "falta"
        assert "2.7 GB" in p["detalle"] and "0.5 GB" in p["detalle"]
        assert "install-model" in p["accion"]

    def test_con_espacio_ofrece_una_vez_y_respeta_el_no(self, monkeypatch):
        _sin_gguf(monkeypatch)
        monkeypatch.setattr(A, "_tam_remoto_gguf", lambda: 2_000_000_000)
        monkeypatch.setattr(A, "_espacio_libre", lambda p: 50_000_000_000)
        veces = []
        monkeypatch.setattr("builtins.input",
                            lambda *a, **k: veces.append(1) or "n")
        p = A.paso_pesos(sin_descarga=False, interactivo=True, backend_ok=False)
        assert len(veces) == 1          # UNA vez, no una por paso
        assert p["estado"] == "falta"
        assert "declinada" in p["detalle"]

    def test_sin_tty_no_se_cuelga_esperando_una_respuesta(self, monkeypatch,
                                                          sin_preguntas):
        _sin_gguf(monkeypatch)
        monkeypatch.setattr(A, "_tam_remoto_gguf", lambda: 2_000_000_000)
        monkeypatch.setattr(A, "_espacio_libre", lambda p: 50_000_000_000)
        p = A.paso_pesos(sin_descarga=False, interactivo=False, backend_ok=False)
        assert p["estado"] == "falta"
        assert "TTY" in p["detalle"]


# ── Paso 3: backend ──────────────────────────────────────────────────────────

class TestBackend:

    def test_NUNCA_relanza_un_backend_vivo(self, monkeypatch):
        """REGRESION de la prohibicion dura: `flota.arrancar` empieza por
        `parar()`, que mata TODOS los llama-server de la maquina (el de
        :8080 lo comparten otros procesos). Si alguien quita la guarda y
        arranca 'por las dudas', este test falla."""
        def _explota():
            raise AssertionError("relanzo la flota con el backend VIVO")
        monkeypatch.setattr(A, "_arrancar_flota", _explota)
        monkeypatch.setattr(A, "_modelo_del_backend",
                            lambda *a: {"modelo": "Q.gguf", "n_ctx": 32768})
        p = A.paso_backend(vivo=True)
        assert p["estado"] == "ok"
        assert "Q.gguf" in p["detalle"] and "32768" in p["detalle"]

    def test_backend_muerto_levanta_el_combo_por_defecto(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(A, "_arrancar_flota",
                            lambda: llamadas.append(1) or 0)
        monkeypatch.setattr(A, "_backend_vivo", lambda *a: True)  # tras arrancar
        monkeypatch.setattr(A, "_modelo_del_backend", lambda *a: {"modelo": "Q.gguf"})
        p = A.paso_backend(vivo=False)
        assert llamadas == [1]
        assert p["estado"] == "hago"

    def test_si_la_flota_no_deja_nada_escuchando_lo_dice_con_la_orden(
            self, monkeypatch):
        monkeypatch.setattr(A, "_arrancar_flota", lambda: 1)
        monkeypatch.setattr(A, "_backend_vivo", lambda *a: False)
        p = A.paso_backend(vivo=False)
        assert p["estado"] == "falta"
        # Orden que existe INSTALADA (no 'python scripts/servir_flota.py').
        assert p["accion"] == "python -m cognia flota arrancar pensar-qwen38"

    def test_una_excepcion_de_la_flota_no_tumba_el_arranque(self, monkeypatch):
        def _revienta():
            raise RuntimeError("sin scripts/ en el wheel")
        monkeypatch.setattr(A, "_arrancar_flota", _revienta)
        p = A.paso_backend(vivo=False)
        assert p["estado"] == "falta"
        assert "sin scripts/" in p["detalle"]

    def test_mira_el_MISMO_server_que_usara_el_agente(self, monkeypatch):
        # Sondear un puerto fijo mientras el agente habla con otro es contar
        # el regimen de un server que el usuario no usa.
        monkeypatch.setenv("COGNIA_LLM_URL", "http://10.0.0.5:9999/")
        assert A.url_backend() == "http://10.0.0.5:9999"
        monkeypatch.delenv("COGNIA_LLM_URL")
        assert A.url_backend() == "http://127.0.0.1:8080"

    def test_un_backend_REMOTO_muerto_no_mata_los_locales(self, monkeypatch):
        # Levantar el combo local no arregla un server ajeno y en cambio
        # `parar()` se llevaria por delante los llama-server de esta maquina.
        monkeypatch.setattr(A, "_arrancar_flota", lambda: (_ for _ in ()).throw(
            AssertionError("arranco la flota local por un URL remoto")))
        p = A.paso_backend("http://10.0.0.5:9999", vivo=False)
        assert p["estado"] == "falta"
        assert "COGNIA_LLM_URL" in p["detalle"]

    def test_un_puerto_LOCAL_que_la_flota_no_sirve_tampoco_la_arranca(
            self, monkeypatch):
        """REGRESION medida el 2026-08-14 en esta maquina: con
        COGNIA_LLM_URL=http://127.0.0.1:8099 caido, `empezar` pasaba la guarda
        de _es_local (es 127.0.0.1) y arrancaba la flota — que empieza por
        parar() y mato el :8080 COMPARTIDO (pid 20872) para nada: la flota
        solo sirve 8080/8081/8082, asi que el :8099 siguio muerto y el paso
        termino en [FALTA] igual. Todo el coste, cero beneficio."""
        monkeypatch.setattr(A, "_arrancar_flota", lambda: (_ for _ in ()).throw(
            AssertionError("arranco la flota por un puerto que no sirve")))
        p = A.paso_backend("http://127.0.0.1:8099", vivo=False)
        assert p["estado"] == "falta"
        assert "8080" in p["detalle"]        # los puertos que SI sirve
        assert "8099" in p["detalle"]

    def test_puerto_ilegible_no_arranca_la_flota(self, monkeypatch):
        # La duda cae del lado de NO tocar procesos ajenos.
        monkeypatch.setattr(A, "_arrancar_flota", lambda: (_ for _ in ()).throw(
            AssertionError("arranco la flota con un puerto ilegible")))
        assert A._puerto("http://127.0.0.1") == 0
        assert A._puerto("http://127.0.0.1:puerto") == 0
        assert A._puerto("http://127.0.0.1:8080") == 8080
        assert A.paso_backend("http://127.0.0.1", vivo=False)["estado"] == "falta"

    def test_dos_sondas_antes_de_declararlo_muerto(self, monkeypatch):
        # La guarda que protege al server compartido de un timeout aislado.
        intentos = []
        monkeypatch.setattr(A, "_responde",
                            lambda u, t: intentos.append(t) or (len(intentos) > 1))
        monkeypatch.setattr(A.time, "sleep", lambda s: None)
        assert A._backend_vivo("http://127.0.0.1:8080") is True
        assert intentos == [3, 6]


# ── Paso 4: capacidad ────────────────────────────────────────────────────────

def _medicion(monkeypatch, reg):
    """capacidad.medicion() devolviendo `reg`, sin tocar el server real."""
    monkeypatch.setattr("cognia.agent.capacidad.medicion",
                        lambda url="", **k: dict(reg))


class TestCapacidad:

    def test_dice_el_regimen_en_una_linea(self, monkeypatch):
        _medicion(monkeypatch, {"soporta_tools": True, "modelo": "X.gguf",
                                "motivo": "tool call valido en 1.6s"})
        p = A.paso_capacidad(backend_ok=True)
        assert p["estado"] == "ok"
        assert p["detalle"] == "regimen NATIVO con X.gguf: tool call valido en 1.6s"

    def test_un_TEXTO_MEDIDO_si_se_publica(self, monkeypatch):
        # El contraste del test de abajo: cuando el server SI contesto y lo
        # que dijo fue "sin tool_calls", eso es un veredicto y se publica.
        _medicion(monkeypatch, {
            "soporta_tools": False, "modelo": "X.gguf",
            "motivo": "respondio sin tool_calls (finish_reason=stop): el "
                      "server no parsea tools"})
        p = A.paso_capacidad(backend_ok=True)
        assert p["estado"] == "ok"
        assert p["detalle"].startswith("regimen TEXTO con X.gguf")

    def test_una_sonda_SIN_RESPUESTA_no_se_publica_como_regimen(self, monkeypatch):
        """REGRESION del fleco real: la sonda tarda 26-30 s en esta maquina
        cargada contra su timeout de 30 s. Cuando se pasa, capacidad devuelve
        soporta_tools=False con motivo 'TimeoutError' — que NO es "va en modo
        texto", es "no se midio" — y la version anterior imprimia 'regimen
        TEXTO con <modelo>' como si fuera un veredicto."""
        _medicion(monkeypatch, {
            "soporta_tools": False, "modelo": "X.gguf",
            "motivo": "no se pudo consultar al server: TimeoutError: timed out"})
        invalidadas = []
        monkeypatch.setattr("cognia.agent.capacidad.invalidar",
                            lambda url="": invalidadas.append(url))
        p = A.paso_capacidad(backend_ok=True, url="http://127.0.0.1:8080")
        assert "regimen TEXTO" not in p["detalle"]
        assert "regimen NATIVO" not in p["detalle"]
        assert p["estado"] == "aviso"
        assert "no pude medir" in p["detalle"]
        assert "--forzar" in p["detalle"]
        # Y el fallo transitorio NO queda congelado 24 h en el cache: sin esta
        # llamada, medicion() lo devolveria igual durante todo un dia.
        assert invalidadas == ["http://127.0.0.1:8080"]

    def test_el_aviso_no_baja_el_exit_ni_deja_regimen_en_el_json(self, monkeypatch,
                                                                 capsys):
        # Decision explicita: la maquina ESTA lista (el backend responde y el
        # agente cae al marco de texto de siempre); lo que falta es saber el
        # regimen. Se avisa, se sale 0 y el campo 'regimen' va VACIO.
        monkeypatch.setattr(A, "_backend_vivo", lambda *a: True)
        monkeypatch.setattr(A, "_modelo_del_backend", lambda *a: {"modelo": "Q.gguf"})
        monkeypatch.setattr(A, "_arrancar_flota",
                            lambda: (_ for _ in ()).throw(AssertionError("no toca")))
        _medicion(monkeypatch, {
            "soporta_tools": False, "modelo": "Q.gguf",
            "motivo": "no se pudo consultar al server: TimeoutError: timed out"})
        monkeypatch.setattr("cognia.agent.capacidad.invalidar", lambda url="": None)
        codigo = A.main(["--sin-descarga", "--sin-repl", "--json"])
        salida = capsys.readouterr()
        datos = json.loads(salida.out)
        assert codigo == 0 and datos["listo"] is True
        assert datos["regimen"] == ""
        assert datos["pasos"][3]["estado"] == "aviso"
        assert "[AVISO]" in salida.err and "TEXTO" not in salida.err

    def test_si_capacidad_revienta_tampoco_inventa_un_regimen(self, monkeypatch):
        monkeypatch.setattr("cognia.agent.capacidad.medicion",
                            lambda url="", **k: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        p = A.paso_capacidad(backend_ok=True)
        assert p["estado"] == "aviso"
        assert "boom" in p["detalle"] and "regimen TEXTO" not in p["detalle"]

    def test_sin_backend_no_inventa_un_regimen(self):
        p = A.paso_capacidad(backend_ok=False)
        assert p["estado"] == "falta"
        assert p["detalle"] == "sin backend no hay regimen que medir"


# ── main(): el contrato con B1 y el JSON ─────────────────────────────────────

def _todo_bien(monkeypatch):
    monkeypatch.setattr(A, "_backend_vivo", lambda *a: True)
    monkeypatch.setattr(A, "_modelo_del_backend", lambda *a: {"modelo": "Q.gguf"})
    monkeypatch.setattr("cognia.agent.capacidad.medicion",
                        lambda url="", **k: {"soporta_tools": True,
                                             "modelo": "Q.gguf",
                                             "motivo": "tool call valido en 1.6s"})
    monkeypatch.setattr(A, "_arrancar_flota",
                        lambda: (_ for _ in ()).throw(AssertionError("no toca")))


class TestMain:

    def test_flag_desconocido_no_hace_nada_en_silencio(self):
        assert A.main(["--sin-descrga"]) == 2      # typo a proposito

    def test_ayuda(self, capsys):
        assert A.main(["--help"]) == 0
        assert "cognia empezar" in capsys.readouterr().out

    def test_json_lleva_los_cuatro_pasos_y_sale_0(self, monkeypatch, capsys):
        _todo_bien(monkeypatch)
        codigo = A.main(["--sin-descarga", "--sin-repl", "--json"])
        salida = capsys.readouterr()
        datos = json.loads(salida.out)             # stdout = SOLO json
        assert codigo == 0 and datos["listo"] is True
        assert [p["paso"] for p in datos["pasos"]] == [
            "config", "pesos", "backend", "capacidad"]
        assert datos["regimen"].startswith("regimen NATIVO")
        assert "[OK]" in salida.err                # el progreso va a stderr

    def test_json_no_entra_al_repl_aunque_no_se_pida(self, monkeypatch):
        _todo_bien(monkeypatch)
        monkeypatch.setattr("cognia.cli.repl",
                            lambda: (_ for _ in ()).throw(
                                AssertionError("entro al REPL en modo json")))
        assert A.main(["--json", "--sin-descarga"]) == 0

    def test_cierra_entrando_al_repl_cuando_quedo_lista(self, monkeypatch):
        # Lo que el usuario queria desde el principio: hablarle. Sin esto,
        # `empezar` seria un chequeo mas y harian falta DOS comandos.
        _todo_bien(monkeypatch)
        entradas = []
        monkeypatch.setattr("cognia.cli.repl", lambda: entradas.append(1))
        assert A.main(["--sin-descarga"]) == 0
        assert entradas == [1]

    def test_si_falta_algo_sale_1_con_UNA_linea_accionable(self, monkeypatch,
                                                           capsys):
        monkeypatch.setattr(A, "_backend_vivo", lambda *a: False)
        monkeypatch.setattr(A, "_arrancar_flota", lambda: 1)
        codigo = A.main(["--sin-descarga", "--sin-repl", "--json"])
        salida = capsys.readouterr()
        datos = json.loads(salida.out)
        assert codigo == 1 and datos["listo"] is False
        accionables = [l for l in salida.err.splitlines() if l.startswith("  -> ")]
        assert len(accionables) == 1
        assert accionables[0] == "  -> python -m cognia install-model"

    def test_no_entra_al_repl_si_la_maquina_no_quedo_lista(self, monkeypatch):
        # Meter al usuario en un REPL sin cerebro es la degradacion silenciosa
        # que el repo lleva anos cazando: se sale con el motivo.
        monkeypatch.setattr(A, "_backend_vivo", lambda *a: False)
        monkeypatch.setattr(A, "_arrancar_flota", lambda: 1)
        monkeypatch.setattr("cognia.cli.repl",
                            lambda: (_ for _ in ()).throw(
                                AssertionError("entro al REPL sin backend")))
        assert A.main(["--sin-descarga"]) == 1

    def test_contrato_con_B1_main_toma_lista_y_devuelve_int(self, monkeypatch):
        # B1 cablea `cognia empezar` -> arranque.main(sys.argv[2:]).
        _todo_bien(monkeypatch)
        r = A.main(["--json", "--sin-descarga", "--sin-repl"])
        assert isinstance(r, int)
