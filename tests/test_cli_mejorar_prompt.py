# -*- coding: utf-8 -*-
"""Cableado de /mejorar (mejora del prompt con IA) en el REPL.

Lo que se protege aca:
- la puerta: /mejorar existe, esta en /ayuda y responde en sus 4 formas;
- la config persiste y un valor invalido no apaga la funcion en silencio;
- el enganche del bucle NO se activa sin tty (contrato con los e2e pipeados)
  ni sobre lineas que vienen de la cola de inyeccion (enrutador, monitores,
  rutinas, carril de fondo): reformular una orden que el usuario no escribio
  seria cambiarsela.
Ningun test llama al modelo: el experto se inyecta con monkeypatch.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def cfg_temporal(tmp_path, monkeypatch):
    """Toda la suite escribe en un ~/.cognia_config.json de mentira."""
    import cognia.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    return tmp_path


def _mejora(ok=True, texto="Arregla el login que rechaza usuarios validos.",
            original="arregla el login", motivo="ok", ms=42, modelo="qwythos"):
    from cognia.harness.mejorar_prompt import Mejora
    return Mejora(ok=ok, texto=texto, original=original, motivo=motivo,
                  ms=ms, modelo=modelo)


def _con_experto(monkeypatch, resultado, registro=None):
    """Sustituye mejorar_prompt.mejorar() por uno que no toca el backend."""
    from cognia.harness import mejorar_prompt

    def _falso(texto, **kw):
        if registro is not None:
            registro.append(texto)
        return resultado

    monkeypatch.setattr(mejorar_prompt, "mejorar", _falso)


def _con_tty(monkeypatch, valor=True):
    from cognia.ux import selector as sel
    monkeypatch.setattr(sel, "hay_tty", lambda: valor)


# ---------------------------------------------------------------- la puerta

def test_comando_registrado_en_ayuda():
    from cognia.cli import COMMANDS, _CMD_DETAILS
    assert "/mejorar" in COMMANDS
    assert "F3" in COMMANDS["/mejorar"]          # el atajo se documenta
    assert "/mejorar" in _CMD_DETAILS


def test_mejorar_sin_args_muestra_estado(capsys):
    import cognia.cli as cli_mod
    cli_mod._slash_mejorar("")
    out = capsys.readouterr().out
    assert "preguntar" in out                    # el default
    assert "/mejorar auto" in out                # la ayuda breve
    assert "F3" in out                           # el atajo


# ------------------------------------------------------- estado y persistencia

@pytest.mark.parametrize("arg,esperado", [
    ("auto", "auto"),
    ("off", "off"),
    ("preguntar", "preguntar"),
    ("on", "preguntar"),                         # alias pedido en el diseno
])
def test_cambio_de_estado_persiste(arg, esperado, capsys):
    import cognia.cli as cli_mod
    cli_mod._slash_mejorar(arg)
    assert cli_mod._load_config()["mejorar_prompt"] == esperado
    assert cli_mod._estado_mejorar() == esperado
    assert "guardado" in capsys.readouterr().out


def test_estado_invalido_cae_en_preguntar():
    # Una config corrupta NO puede apagar en silencio una funcion visible.
    import cognia.cli as cli_mod
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "xyz"})
    assert cli_mod._estado_mejorar() == "preguntar"


def test_clave_declarada_en_defaults():
    # /config set la rechaza si no esta en _CONFIG_DEFAULTS.
    import cognia.cli as cli_mod
    assert cli_mod._CONFIG_DEFAULTS["mejorar_prompt"] == "preguntar"


# ------------------------------------------------------- /mejorar <texto>

def test_mejorar_texto_imprime_y_no_envia(monkeypatch, capsys):
    import cognia.cli as cli_mod
    vistos = []
    _con_experto(monkeypatch, _mejora(), vistos)
    cli_mod._slash_mejorar("arregla el login")
    out = capsys.readouterr().out
    assert vistos == ["arregla el login"]
    assert "Arregla el login que rechaza usuarios validos." in out
    assert "original:" in out


def test_mejorar_texto_rechazado_dice_el_motivo(monkeypatch, capsys):
    import cognia.cli as cli_mod
    _con_experto(monkeypatch, _mejora(ok=False, texto="arregla el login",
                                      motivo="sin backend local"))
    cli_mod._slash_mejorar("arregla el login")
    out = capsys.readouterr().out
    assert "Sin mejorar" in out and "sin backend local" in out


# --------------------------------------------------- el enganche del bucle

def test_sin_tty_el_enganche_no_se_activa(monkeypatch):
    # Contrato con los e2e pipeados: sin tty el REPL se comporta como siempre.
    import cognia.cli as cli_mod
    _con_tty(monkeypatch, False)
    cli_mod._LINEA_INYECTADA[0] = False
    assert cli_mod._mejora_aplica("arregla el login de la aplicacion") is False


def test_linea_inyectada_jamas_se_mejora(monkeypatch):
    # La cola la llenan el enrutador, los monitores y las rutinas: eso NO es
    # texto tecleado y reformularlo cambiaria una orden del sistema.
    import cognia.cli as cli_mod
    _con_tty(monkeypatch, True)
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    cli_mod._LINEA_INYECTADA[0] = True
    try:
        assert cli_mod._mejora_aplica("/hacer arregla el login del panel") is False
        assert cli_mod._mejora_aplica("arregla el login del panel de admin") is False
    finally:
        cli_mod._LINEA_INYECTADA[0] = False


def test_off_y_no_candidatos_no_se_mejoran(monkeypatch):
    import cognia.cli as cli_mod
    _con_tty(monkeypatch, True)
    cli_mod._LINEA_INYECTADA[0] = False
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "off"})
    assert cli_mod._mejora_aplica("arregla el login de la aplicacion") is False
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "preguntar"})
    assert cli_mod._mejora_aplica("arregla el login de la aplicacion") is True
    assert cli_mod._mejora_aplica("/salir") is False       # comando
    assert cli_mod._mejora_aplica("hola") is False         # muy corta


def test_auto_devuelve_el_texto_mejorado(monkeypatch, capsys):
    import cognia.cli as cli_mod
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    _con_experto(monkeypatch, _mejora())
    salida = cli_mod._mejorar_linea_interactiva("arregla el login")
    assert salida == "Arregla el login que rechaza usuarios validos."
    assert "mejorado" in capsys.readouterr().out


def test_auto_degrada_al_original(monkeypatch, capsys):
    import cognia.cli as cli_mod
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    _con_experto(monkeypatch, _mejora(ok=False, texto="arregla el login",
                                      motivo="timeout o red: TimeoutError: "))
    salida = cli_mod._mejorar_linea_interactiva("arregla el login")
    assert salida == "arregla el login"          # jamas se traga la linea
    assert "sin mejorar" in capsys.readouterr().out.lower()


def test_preguntar_enviar_tal_cual_no_gasta_modelo(monkeypatch):
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    llamadas = []
    _con_experto(monkeypatch, _mejora(), llamadas)
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: "enviar")
    assert cli_mod._mejorar_linea_interactiva("arregla el login") == "arregla el login"
    assert llamadas == []                        # el modelo ni se toco


def test_preguntar_editar_precarga_el_prompt(monkeypatch):
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    _con_experto(monkeypatch, _mejora())
    respuestas = iter(["mejorar", "editar"])
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: next(respuestas))
    cli_mod._PRECARGA_PROMPT[0] = ""
    try:
        # None = no se envia nada: la linea vuelve al prompt para retocarla.
        assert cli_mod._mejorar_linea_interactiva("arregla el login") is None
        assert cli_mod._PRECARGA_PROMPT[0] == \
            "Arregla el login que rechaza usuarios validos."
    finally:
        cli_mod._PRECARGA_PROMPT[0] = ""


def test_preguntar_apagar_persiste_off(monkeypatch):
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: "off")
    assert cli_mod._mejorar_linea_interactiva("arregla el login") == "arregla el login"
    assert cli_mod._estado_mejorar() == "off"


def test_esc_en_el_menu_CANCELA_en_vez_de_enviar(monkeypatch):
    """Esc/Ctrl-C dentro del menu vale None (selector._elegir_flechas los liga
    a app.exit(result=None)). Hasta el fix eso caia en 'no elegiste mejorar' y
    la linea SE ENVIABA: el unico momento en que el usuario cree poder abortar
    significaba lo contrario, y en texto libre el auto-enrutado puede llevar
    ese mensaje a /hacer con herramientas."""
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    llamadas = []
    _con_experto(monkeypatch, _mejora(), llamadas)
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: None)
    cli_mod._PRECARGA_PROMPT[0] = ""
    cli_mod._MEJORA_YA_DECIDIDA[0] = False
    try:
        assert cli_mod._mejorar_linea_interactiva("borra los temporales") is None
        # no se pierde lo tecleado: vuelve al prompt tal cual
        assert cli_mod._PRECARGA_PROMPT[0] == "borra los temporales"
        assert llamadas == []                    # ni se toco el modelo
    finally:
        cli_mod._PRECARGA_PROMPT[0] = ""
        cli_mod._MEJORA_YA_DECIDIDA[0] = False


def test_el_menu_ofrece_cancelar_explicitamente(monkeypatch):
    # El gesto tiene que ser DESCUBRIBLE, no solo funcionar con Esc.
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    vistas = {}

    def _espia(titulo, opciones, **kw):
        vistas["opciones"] = [o[0] for o in opciones]
        return "enviar"

    monkeypatch.setattr(sel, "elegir", _espia)
    cli_mod._mejorar_linea_interactiva("borra los temporales del proyecto")
    assert "cancelar" in vistas["opciones"]


def test_la_linea_ya_decidida_no_vuelve_a_pasar_por_el_menu(monkeypatch):
    """Tras 'Editar el mejorado' (o F3) el texto vuelve al prompt; al dar Enter
    salia OTRA VEZ el menu sobre algo ya aprobado, y con el estado en 'auto' se
    llamaba al modelo una SEGUNDA vez para reformular la reformulacion."""
    import cognia.cli as cli_mod
    _con_tty(monkeypatch, True)
    cli_mod._LINEA_INYECTADA[0] = False
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    linea = "Arregla el login que rechaza usuarios validos."
    try:
        cli_mod._MEJORA_YA_DECIDIDA[0] = True
        assert cli_mod._mejora_aplica(linea) is False
        # es de UN SOLO uso: la linea siguiente vuelve a la normalidad
        assert cli_mod._mejora_aplica(linea) is True
    finally:
        cli_mod._MEJORA_YA_DECIDIDA[0] = False


@pytest.mark.parametrize("via,espera_texto", [("editar", True), (None, False)])
def test_volver_al_prompt_marca_la_linea_como_decidida(via, espera_texto,
                                                       monkeypatch):
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    _con_experto(monkeypatch, _mejora())
    respuestas = iter(["mejorar", via])
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: next(respuestas))
    cli_mod._MEJORA_YA_DECIDIDA[0] = False
    cli_mod._PRECARGA_PROMPT[0] = ""
    try:
        assert cli_mod._mejorar_linea_interactiva("arregla el login") is None
        assert cli_mod._MEJORA_YA_DECIDIDA[0] is True
        esperado = ("Arregla el login que rechaza usuarios validos."
                    if espera_texto else "arregla el login")
        assert cli_mod._PRECARGA_PROMPT[0] == esperado
    finally:
        cli_mod._MEJORA_YA_DECIDIDA[0] = False
        cli_mod._PRECARGA_PROMPT[0] = ""


def test_f3_marca_la_linea_como_decidida(monkeypatch):
    import cognia.cli as cli_mod
    _con_experto(monkeypatch, _mejora())
    cli_mod._MEJORA_YA_DECIDIDA[0] = False
    try:
        cli_mod._mejora_en_el_sitio("arregla el login")
        assert cli_mod._MEJORA_YA_DECIDIDA[0] is True
    finally:
        cli_mod._MEJORA_YA_DECIDIDA[0] = False


def test_no_volver_a_preguntar_que_no_se_guarda_NO_dice_que_quedo_off(
        monkeypatch, capsys):
    """HOME de solo lectura o disco lleno: _save_config lanza. Afirmar 'off' y
    volver a preguntar en el Enter siguiente es justo la promesa que da nombre
    a la opcion."""
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel

    def _no_guarda(cfg):
        raise OSError("disco lleno")

    monkeypatch.setattr(cli_mod, "_save_config", _no_guarda)
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: "off")
    assert cli_mod._mejorar_linea_interactiva("arregla el login") == "arregla el login"
    out = capsys.readouterr().out.lower()
    assert "mejora de prompts: off" not in out
    assert "no pude guardar" in out


def test_un_fallo_interno_del_experto_se_grita(monkeypatch):
    """El modulo es puro y no imprime; el `aviso` que trae la Mejora es lo
    unico que separa "no lo cablearon" de "se rompio"."""
    import cognia.cli as cli_mod
    gritos = []
    monkeypatch.setattr(cli_mod, "_aviso_degradado",
                        lambda via, motivo="": gritos.append((via, motivo)))
    _con_experto(monkeypatch, _mejora(), None)
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.setattr(
        mp, "mejorar",
        lambda texto, **kw: mp.Mejora(ok=True, texto="X" * 20, original=texto,
                                      motivo="ok", ms=1, modelo="m",
                                      aviso="no se pudo registrar la llamada"))
    cli_mod._mejora_generar("arregla el login", "cli.mejorar.test")
    assert any("no se pudo registrar" in m for _v, m in gritos), gritos


def test_el_bucle_del_repl_enruta_los_centinelas(monkeypatch):
    """Estructural (repl() tiene 1.500 lineas y su closure no se instancia):
    lo que se defiende es que el prompt de CONTINUACION ('\\' al final) y la
    rama sin prompt_toolkit no vuelvan a ignorar los centinelas. En la
    continuacion, '\\x00@mejora@...' se concatenaba EN MEDIO del mensaje
    ('\\x00' no es whitespace: strip() no lo quita) y viajaba al modelo."""
    from pathlib import Path
    import cognia.cli as cli_mod
    fuente = Path(cli_mod.__file__).read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("def repl():"):]
    cont = cuerpo[cuerpo.index('while line.endswith("\\\\"):'):]
    cont = cont[:cont.index("return line")]
    assert "_FONDO_MEJORA" in cont, "la continuacion se traga el centinela de F3"
    assert "_FONDO_F2" in cont, "la continuacion se traga el centinela de F2"
    # rama sin prompt_toolkit: consume la precarga en vez de perderla
    plano = cuerpo[cuerpo.index('return input(_g() + "cognia> "') - 900:]
    plano = plano[:plano.index("# Warm-up")]
    assert "_PRECARGA_PROMPT" in plano, \
        "sin PromptSession, 'Editar el mejorado' pierde el texto sin avisar"


def test_f3_sobre_un_comando_no_reformula(monkeypatch, capsys):
    import cognia.cli as cli_mod
    llamadas = []
    _con_experto(monkeypatch, _mejora(), llamadas)
    assert cli_mod._mejora_en_el_sitio("/salir") == "/salir"
    assert llamadas == []
    assert cli_mod._mejora_en_el_sitio("") == ""


def test_f3_devuelve_el_texto_reformulado(monkeypatch):
    import cognia.cli as cli_mod
    _con_experto(monkeypatch, _mejora())
    assert cli_mod._mejora_en_el_sitio("arregla el login") == \
        "Arregla el login que rechaza usuarios validos."


# ------------------------------------------------------------------ e2e real

def test_repl_pipeado_responde_mejorar():
    """El REPL de verdad, por stdin (sin tty): el dispatch responde y el
    enganche NO aparece por ningun lado."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-m", "cognia"],
                       input="/mejorar\n/salir\n".encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       cwd=str(ROOT), env=env, timeout=180)
    salida = p.stdout.decode("utf-8", errors="replace")
    assert "Mejora del prompt con IA" in salida, salida[-2000:]
    assert "Enviar tal cual" not in salida       # sin tty no se pregunta nada


# ---------------------------------- el ESTILO del system: puerta y config
# REGRESION (ronda 2). El unico mando del estilo era la env var
# COGNIA_MEJORA_PROMPT, leida dentro del modulo. Con ella puesta (por ejemplo
# olvidada de una sesion de medicion) 22 de cada 24 reformulaciones vuelven con
# motivo "identico al original" y el CLI no da ni una pista de que el estilo
# conservador esta activo: el sintoma se diagnostica como "el mejorador no
# mejora" o como backend caido. Es la confusion "no lo cablearon" vs "se rompio"
# que _motivo_backend() ya elimino en el eje de al lado.

def test_estilo_declarado_en_defaults():
    import cognia.cli as cli_mod
    assert "mejorar_prompt_estilo" in cli_mod._CONFIG_DEFAULTS
    assert cli_mod._CONFIG_DEFAULTS["mejorar_prompt_estilo"] == ""


def test_estilo_precedencia_env_sobre_config_sobre_default(monkeypatch):
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    # sin nada: manda el default del modulo
    assert cli_mod._estilo_mejorar() == (mp.VERSION_DEFECTO, "", "default del modulo")
    # el ORIGEN sale de la misma funcion que la precedencia, no de
    # una segunda copia de la logica en la puerta de diagnostico
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS,
                          "mejorar_prompt_estilo": "v3"})
    assert cli_mod._estilo_mejorar()[2] == "config mejorar_prompt_estilo"
    # config
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS,
                          "mejorar_prompt_estilo": "v1"})
    assert cli_mod._estilo_mejorar()[0] == "v1"
    # env gana a config
    monkeypatch.setenv(mp.ENV_VERSION, "v3")
    assert cli_mod._estilo_mejorar()[0] == "v3"


def test_la_puerta_de_diagnostico_DICE_que_estilo_corre(monkeypatch, capsys):
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.setenv(mp.ENV_VERSION, "v1")
    cli_mod._slash_mejorar("")
    out = capsys.readouterr().out
    assert "estilo del system" in out.lower()
    assert "v1" in out
    assert cli_mod._MEJORA_ENV in out            # y DE DONDE sale


def test_un_estilo_desconocido_se_grita_en_la_puerta(monkeypatch, capsys):
    """El aviso existia, pero solo despues de gastar una reformulacion. La
    puerta de diagnostico es justo donde se viene a mirar por que no mejora."""
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.setenv(mp.ENV_VERSION, "V2 mal escrito")
    cli_mod._slash_mejorar("")
    out = capsys.readouterr().out
    assert "desconocida" in out
    assert mp.VERSION_DEFECTO in out


def test_slash_mejorar_estilo_persiste_y_vuelve_al_default(monkeypatch, capsys):
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    cli_mod._slash_mejorar("estilo v1")
    assert cli_mod._load_config()["mejorar_prompt_estilo"] == "v1"
    assert cli_mod._estilo_mejorar()[0] == "v1"
    cli_mod._slash_mejorar("estilo auto")
    assert cli_mod._load_config()["mejorar_prompt_estilo"] == ""
    assert cli_mod._estilo_mejorar()[0] == mp.VERSION_DEFECTO
    assert "guardado" in capsys.readouterr().out


def test_slash_mejorar_estilo_NO_guarda_un_nombre_desconocido(monkeypatch,
                                                              capsys):
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    cli_mod._slash_mejorar("estilo v9")
    assert cli_mod._load_config()["mejorar_prompt_estilo"] == ""
    out = capsys.readouterr().out
    assert "desconocido" in out and "No se guardo" in out


def test_estilo_seguido_de_una_FRASE_sigue_siendo_texto_a_reformular(
        monkeypatch):
    """El mando nuevo no puede comerse una peticion del usuario: 'estilo de
    redaccion para el correo' es texto, no un cambio de configuracion."""
    import cognia.cli as cli_mod
    vistos = []
    _con_experto(monkeypatch, _mejora(), vistos)
    cli_mod._slash_mejorar("estilo de redaccion para el correo del lunes")
    assert vistos == ["estilo de redaccion para el correo del lunes"]
    assert cli_mod._load_config()["mejorar_prompt_estilo"] == ""


def test_el_estilo_resuelto_VIAJA_al_experto(monkeypatch):
    """Sin esto la clave de config no tendria ningun efecto: el modulo
    resolveria por su cuenta y la unica marcha atras seguiria siendo la env
    var invisible."""
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt as mp
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS,
                          "mejorar_prompt_estilo": "v1"})
    vistas = []

    def _falso(texto, **kw):
        vistas.append(kw.get("version"))
        return _mejora()

    monkeypatch.setattr(mp, "mejorar", _falso)
    cli_mod._slash_mejorar("arregla el login del panel")
    assert vistas == ["v1"]


def test_la_ayuda_NO_vende_un_A_B_ciego_que_no_lo_fue():
    """REGRESION (ronda 2). En 10 de las 12 filas de pares.json un lado era el
    texto del usuario INTACTO (v1 devolvio passthrough en 22 de 24 llamadas),
    asi que el juez identificaba el brazo sin la clave: el juicio no fue ciego
    y el '11-1' no midio 'v2 reformula mejor'. El texto que lee el dueno tiene
    que decir lo que se midio."""
    from cognia.cli import _CMD_DETAILS
    detalle = _CMD_DETAILS["/mejorar"]
    assert "A/B ciego" not in detalle
    assert "11-1" not in detalle
    # lo que SI esta medido
    assert "24/24" in detalle and "22 de 24" in detalle
    assert "1-1" in detalle                      # el cara a cara real
    # y la puerta nueva del estilo se documenta
    assert "mejorar_prompt_estilo" in detalle


# ---------------------------------------- F3 con un paste colapsado (2026-08-24)

def test_f3_expande_el_paste_antes_de_reformular(monkeypatch):
    """Revision adversarial 2026-08-24: la marca '[pegado #N: +X lineas]' solo
    se expandia en el main loop AL ENVIAR, pero F3 corre antes y reemplaza el
    buffer con lo que devuelve el modelo; si este no copia la marca byte a
    byte, al dar Enter no hay nada que expandir y el paste se pierde en
    silencio. Ahora el reformulador recibe el contenido pegado, no la marca."""
    import cognia.cli as cli_mod
    from cognia.harness import pegados
    pegados.limpiar()
    contenido = "\n".join(f"linea {i}" for i in range(10))
    marca = pegados.registrar(contenido)
    assert marca.startswith("[pegado #")
    visto = []
    _con_experto(monkeypatch, _mejora(texto="Analiza el log adjunto."), visto)
    _con_tty(monkeypatch)
    out = cli_mod._mejora_en_el_sitio(f"analiza esto {marca}")
    assert visto, "el reformulador no se llamo"
    assert "linea 9" in visto[0] and "[pegado #" not in visto[0]
    assert out == "Analiza el log adjunto."


def test_f3_con_paste_enorme_devuelve_la_linea_intacta(monkeypatch):
    """Un paste por encima de MAX_CHARS no se reformula (es_candidato lo
    rechaza): la linea vuelve con su marca, que se expande al enviar. Ni se
    pierde ni se manda al modelo a reformular 4000 chars."""
    import cognia.cli as cli_mod
    from cognia.harness import pegados
    pegados.limpiar()
    marca = pegados.registrar("x" * 9000)
    visto = []
    _con_experto(monkeypatch, _mejora(), visto)
    _con_tty(monkeypatch)
    linea = f"resume esto {marca}"
    assert cli_mod._mejora_en_el_sitio(linea) == linea
    assert visto == []
